"""FastAPI sensor-gateway: ``POST /readings`` (T112).

Принимает одиночное чтение или пакет, валидирует конверт, проставляет
``receivedAt`` только здесь, публикует валидные в ``sensors.readings.v1``
(ключ ``stationId``), битые — в ``sensors.readings.dlq`` с причиной.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from config import Settings, get_settings
from observability import (
    ApiError,
    RequestIdMiddleware,
    configure_logging,
    get_logger,
    install_exception_handlers,
    render_metrics,
)

from .publisher import (
    DeadReadingPublisher,
    KafkaPublisher,
    NullPublisher,
    ReadingPublisher,
    dlq_topic,
    readings_topic,
)
from .service import ReadingProcessor

_log = get_logger(__name__)

API_PREFIX = "/api/v1"


def create_app(
    *,
    settings: Settings | None = None,
    processor: ReadingProcessor | None = None,
    readings: ReadingPublisher | None = None,
    dead_letters: DeadReadingPublisher | None = None,
) -> FastAPI:
    """Собрать приложение шлюза датчиков с инъекцией публикаторов."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — Sensor Gateway", version="1.0.0")
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)

    app.state.settings = resolved
    app.state.processor = processor or ReadingProcessor()
    app.state.readings = readings or NullPublisher()
    app.state.dead_letters = dead_letters or NullPublisher()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "sensor-gateway"}

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")

    @app.post(f"{API_PREFIX}/readings")
    async def ingest_reading(request: Request) -> dict[str, int]:
        try:
            body: Any = await request.json()
        except ValueError as error:
            # Битый JSON — клиентская ошибка, а не 500 (QR-5).
            raise ApiError(400, "BAD_REQUEST", "Некорректный JSON") from error
        result = request.app.state.processor.ingest(body)
        for reading in result.accepted:
            await request.app.state.readings.publish(reading, reading.stationId)
        for rejected in result.dead:
            await request.app.state.dead_letters.publish(rejected, rejected.readingId)
        return {"accepted": len(result.accepted), "dead": len(result.dead)}

    return app


def main() -> None:
    """Запустить шлюз датчиков под uvicorn с Kafka-публикаторами."""
    import uvicorn

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="sensor-gateway")
    settings = get_settings()
    bootstrap = settings.kafka.bootstrap_servers
    app = create_app(
        settings=settings,
        readings=KafkaPublisher(bootstrap, readings_topic()),
        dead_letters=KafkaPublisher(bootstrap, dlq_topic()),
    )
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = ["API_PREFIX", "create_app", "main"]
