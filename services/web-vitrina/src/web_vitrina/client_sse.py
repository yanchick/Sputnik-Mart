"""SSE-клиент фасада на ``httpx-sse`` (T149, ADR-0003, ADR-0006).

Panel-сервер — синхронный, поэтому долгоживущее соединение читается в
фоновом потоке, а в UI кадры забираются неблокирующим :meth:`SseStreamReader.poll`.
"""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

import httpx
from httpx_sse import ServerSentEvent, connect_sse

DEFAULT_SSE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


@dataclass(frozen=True)
class StreamFrame:
    """Разобранный кадр живого потока."""

    event: str
    event_id: str | None
    data: dict[str, Any]


@dataclass
class SseStreamReader:
    """Читает ``/streams/{subscriptionId}`` в отдельном потоке.

    Кадры складываются в очередь; :meth:`poll` забирает накопленное, не
    блокируя Panel. Повторное подключение безопасно: дедупликация по ``id``
    выполняется на сервере.
    """

    base_url: str = DEFAULT_SSE_URL
    subscription_id: str = ""
    token: str | None = None
    api_key: str | None = None
    timeout: float = 60.0
    _queue: queue.Queue[StreamFrame] = field(default_factory=queue.Queue, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _error: str | None = field(default=None, init=False)

    def headers(self) -> dict[str, str]:
        """Заголовки аутентификации: Bearer или ``X-Api-Key``."""
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.api_key:
            return {"X-Api-Key": self.api_key}
        return {}

    def url(self) -> str:
        """URL живого потока подписки."""
        return f"{self.base_url.rstrip('/')}{API_PREFIX}/streams/{self.subscription_id}"

    def iter_frames(self) -> Any:
        """Блокирующий генератор кадров (для ноутбуков и тестов)."""
        with (
            httpx.Client(base_url=self.base_url, timeout=self.timeout) as client,
            connect_sse(client, "GET", self.url(), headers=self.headers()) as source,
        ):
            for raw in source.iter_sse():
                frame = parse_frame(raw)
                if frame is not None:
                    yield frame

    def start(self) -> None:
        """Открыть поток в фоновом потоке."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sse-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Остановить фоновый поток."""
        self._stop.set()
        self._thread = None

    def _run(self) -> None:
        try:
            for frame in self.iter_frames():
                if self._stop.is_set():
                    return
                self._queue.put(frame)
        except Exception as error:  # граница сети: сообщение доступно в UI
            self._error = str(error)

    def poll(self) -> list[StreamFrame]:
        """Забрать накопленные кадры, не блокируя вызывающий поток."""
        frames: list[StreamFrame] = []
        while True:
            try:
                frames.append(self._queue.get_nowait())
            except queue.Empty:
                return frames

    @property
    def error(self) -> str | None:
        """Текст последней сетевой ошибки, если поток оборвался."""
        return self._error


def parse_frame(raw: ServerSentEvent) -> StreamFrame | None:
    """Разобрать ``ServerSentEvent``; пинг тоже становится кадром."""
    data: dict[str, Any] = {}
    if raw.data:
        try:
            loaded = json.loads(raw.data)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    return StreamFrame(event=raw.event or "message", event_id=raw.id, data=data)


__all__ = ["DEFAULT_SSE_URL", "SseStreamReader", "StreamFrame", "parse_frame"]
