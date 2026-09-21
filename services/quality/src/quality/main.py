"""FastAPI quality-service для Quality-page (T122)."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Protocol

from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from db.postgres import create_engine, create_session_factory
from observability import (
    API_KEY_HEADER,
    ApiError,
    RequestIdMiddleware,
    bearer_user_id,
    configure_logging,
    get_logger,
    install_exception_handlers,
    render_metrics,
)
from service_client import HttpServiceClient, ServiceClient, forward_auth, resolve_api_key

from . import service

_log = get_logger(__name__)

API_PREFIX = "/api/v1"

MetricsRefresher = Callable[[AsyncSession], Awaitable[None]]


def _default_metrics_refresher(settings: Settings) -> MetricsRefresher:
    """Обновлять лаг/свежесть из ClickHouse при каждом скрейпе ``/metrics``."""

    async def refresh(session: AsyncSession) -> None:
        from db.clickhouse import create_client

        from .runtime_metrics import refresh_runtime_metrics

        client = create_client(
            host=settings.clickhouse.host,
            port=settings.clickhouse.port,
            username=settings.clickhouse.user,
            password=settings.clickhouse.password,
            database=settings.clickhouse.database,
        )
        try:
            await refresh_runtime_metrics(session, client)
        finally:
            await client.close()

    return refresh


class ReportProvider(Protocol):
    """Источник последнего отчёта о качестве по датасету."""

    async def latest_report(self, dataset_id: str) -> Mapping[str, Any] | None:
        """Вернуть отчёт или ``None``."""
        ...


class NullReportProvider:
    """Провайдер без отчётов (каталог-only)."""

    async def latest_report(self, dataset_id: str) -> Mapping[str, Any] | None:
        """Всегда ``None``."""
        return None


class MinioReportProvider:
    """Чтение последнего ``report.json`` из MinIO для Quality-page."""

    def __init__(self, store: Any, bucket: str) -> None:
        self._store = store
        self._bucket = bucket

    async def latest_report(self, dataset_id: str) -> Mapping[str, Any] | None:
        """Найти отчёт по датасету в последних датах ``reports/quality``.

        Если объектное хранилище недоступно (например, профиль ``base`` без
        MinIO), возвращаем ``None``: страница качества остаётся работоспособной
        с показателями каталога.
        """
        try:
            keys = sorted(
                (key for key in await self._store.list_keys(self._bucket, "reports/quality/")),
                reverse=True,
            )
            for key in keys:
                if not key.endswith("report.json"):
                    continue
                payload = json.loads(
                    (await self._store.get_bytes(self._bucket, key)).decode("utf-8")
                )
                report = payload.get("datasets", {}).get(dataset_id)
                if report is not None:
                    return dict(report)
        except Exception as error:  # граница внешнего объектного хранилища
            _log.warning("quality_report_unavailable", dataset_id=dataset_id, error=str(error))
            return None
        return None


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    report_provider: ReportProvider | None = None,
    metrics_refresher: MetricsRefresher | None = None,
    catalog_client: ServiceClient | None = None,
    identity_client: ServiceClient | None = None,
) -> FastAPI:
    """Собрать приложение quality-service."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — Quality Service", version="1.0.0")
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)

    if session_factory is None:
        engine = create_engine(resolved.postgres.async_dsn())
        session_factory = create_session_factory(engine)
        app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = resolved
    app.state.report_provider = report_provider or NullReportProvider()
    app.state.metrics_refresher = metrics_refresher or _default_metrics_refresher(resolved)
    # Запись qualityScore — только через каталог; ключи — через identity (M6).
    app.state.catalog_client = catalog_client or HttpServiceClient("catalog")
    app.state.identity_client = identity_client or HttpServiceClient("identity")

    async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
        factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    async def require_operator(request: Request) -> str:
        """Допустить операцию записи только с валидным Bearer-токеном/ключом (M4, M6).

        Публичного доступа к пересчёту нет: неподписанный токен и неизвестный
        ``X-Api-Key`` (проверяется по identity через API) отклоняются единым
        конвертом 401.
        """
        settings: Settings = request.app.state.settings
        user_id = bearer_user_id(request.headers.get("Authorization"), settings.app.auth_secret)
        if user_id is not None:
            return user_id
        api_key = request.headers.get(API_KEY_HEADER)
        if api_key:
            key_user = await resolve_api_key(request.app.state.identity_client, api_key)
            if key_user is not None:
                return key_user
        raise ApiError(401, "UNAUTHORIZED", "Требуется аутентификация")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "quality"}

    @app.get("/metrics")
    async def metrics(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> PlainTextResponse:
        """Отдать текущие метрики; лаг/свежесть обновляются из реальных источников."""
        refresher: MetricsRefresher = request.app.state.metrics_refresher
        try:
            await refresher(session)
        except Exception as error:  # скрейп метрик не должен падать из-за БД
            _log.warning("metrics_refresh_failed", error=str(error))
        return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")

    @app.get(f"{API_PREFIX}/quality")
    async def list_quality(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> dict[str, Any]:
        snapshots = await service.list_quality_snapshots(session)
        provider: ReportProvider = request.app.state.report_provider
        enriched = [
            service.merge_report(snapshot, await provider.latest_report(snapshot.dataset_id))
            for snapshot in snapshots
        ]
        return {"data": [service.snapshot_payload(snapshot) for snapshot in enriched]}

    @app.get(f"{API_PREFIX}/quality/{{datasetId}}")
    async def get_quality(
        datasetId: str,
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        snapshot = await service.get_quality_snapshot(session, datasetId)
        if snapshot is None:
            raise ApiError(404, "NOT_FOUND", "Датасет не найден")
        report = await request.app.state.report_provider.latest_report(datasetId)
        enriched = service.merge_report(snapshot, report)
        return service.snapshot_payload(enriched)

    @app.post(f"{API_PREFIX}/quality/recalculate")
    async def recalculate(
        request: Request,
        _principal: str = Depends(require_operator),
    ) -> dict[str, Any]:
        try:
            body: Any = await request.json()
        except ValueError as error:
            raise ApiError(400, "BAD_REQUEST", "Некорректный JSON") from error
        if not isinstance(body, dict):
            raise ApiError(400, "BAD_REQUEST", "Ожидался JSON-объект")
        reports = body.get("datasets", {})
        updated = await service.recalculate_quality_scores(
            reports,
            request.app.state.catalog_client,
            auth_header=forward_auth(request.headers),
        )
        return {"updated": updated, "count": len(updated)}

    return app


def main() -> None:
    """Запустить quality-service под uvicorn (с MinIO-провайдером отчётов)."""
    import uvicorn

    from db import create_object_store

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="quality")
    settings = get_settings()
    store = create_object_store(
        endpoint_url=settings.minio.endpoint,
        aws_access_key_id=settings.minio.access_key,
        aws_secret_access_key=settings.minio.secret_key,
        region_name=settings.minio.region,
    )
    app = create_app(
        settings=settings,
        report_provider=MinioReportProvider(store, settings.minio.lake_bucket),
    )
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = [
    "API_PREFIX",
    "MetricsRefresher",
    "MinioReportProvider",
    "NullReportProvider",
    "ReportProvider",
    "create_app",
    "main",
]
