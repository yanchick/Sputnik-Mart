"""FastAPI order: заказы и подписки покупателя (T079)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from contracts import (
    CreateOrderRequest,
    CreateSubscriptionRequest,
    FulfillOrderRequest,
    Order,
    OrderAccess,
    PagedOrders,
    Subscription,
)
from db.postgres import create_engine, create_session_factory
from observability import (
    ApiError,
    RequestIdMiddleware,
    configure_logging,
    get_logger,
    install_exception_handlers,
    paged_payload,
    user_id_from_headers,
)
from service_client import HttpServiceClient, ServiceClient

from . import service
from .events import EventPublisher, NullPublisher
from .subscription_states import SubscriptionAction

_log = get_logger(__name__)

API_PREFIX = "/api/v1"


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    events: EventPublisher | None = None,
    catalog_client: ServiceClient | None = None,
) -> FastAPI:
    """Собрать приложение заказов."""
    resolved = settings or get_settings()
    app = FastAPI(title="Спутник Данные — Order Service", version="1.0.0")
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)

    if session_factory is None:
        engine = create_engine(resolved.postgres.async_dsn())
        session_factory = create_session_factory(engine)
        app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = resolved
    publisher: EventPublisher = events or NullPublisher()
    app.state.events = publisher
    # Цена датасета принадлежит каталогу; order читает её по HTTP (M6).
    app.state.catalog_client = catalog_client or HttpServiceClient("catalog")

    async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
        factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
        session = factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def require_user(request: Request) -> str:
        user_id = user_id_from_headers(
            request.headers.get("Authorization"),
            request.headers.get("X-User-Id"),
            request.app.state.settings.app.auth_secret,
        )
        if user_id is None:
            raise ApiError(401, "UNAUTHORIZED", "Требуется аутентификация")
        return user_id

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "order"}

    @app.post(
        f"{API_PREFIX}/orders",
        response_model=Order,
        status_code=201,
        tags=["orders"],
    )
    async def create_order(
        payload: CreateOrderRequest,
        request: Request,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Order:
        order, _ = await service.create_order(
            session,
            request.app.state.events,
            request.app.state.catalog_client,
            user_id=user_id,
            dataset_id=payload.datasetId,
            quantity=payload.quantity,
            idempotency_key=idempotency_key or f"{user_id}:{payload.datasetId}:{payload.quantity}",
            auto_pay=request.app.state.settings.app.demo_auto_pay,
        )
        return service.to_order_contract(order)

    @app.post(f"{API_PREFIX}/orders/{{orderId}}/pay", response_model=Order, tags=["orders"])
    async def pay_order(
        orderId: str,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Order:
        """Оплатить заказ: ``ORDER_PENDING → ORDER_PAID`` (m12)."""
        order = await service.pay_order(session, user_id=user_id, order_id=orderId)
        return service.to_order_contract(order)

    @app.post(f"{API_PREFIX}/orders/fulfill", response_model=Order, tags=["orders"])
    async def fulfill_order(
        payload: FulfillOrderRequest,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Order:
        """Отметить выдачу оплаченного заказа: ``ORDER_PAID → ORDER_FULFILLED`` (m12)."""
        order = await service.fulfill_order(session, user_id=user_id, dataset_id=payload.datasetId)
        return service.to_order_contract(order)

    @app.get(f"{API_PREFIX}/orders/access", response_model=OrderAccess, tags=["orders"])
    async def order_access(
        datasetId: str = Query(min_length=1),
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> OrderAccess:
        """Проверить право скачивания для delivery-сервиса (FR-007, M6)."""
        access = await service.has_download_access(session, user_id=user_id, dataset_id=datasetId)
        return OrderAccess(datasetId=datasetId, hasAccess=access)

    @app.get(f"{API_PREFIX}/orders", response_model=PagedOrders, tags=["orders"])
    async def list_orders(
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
        page: int = 1,
        pageSize: int = 20,
    ) -> dict[str, object]:
        orders, total = await service.list_orders(session, user_id, page=page, page_size=pageSize)
        return paged_payload(
            [order.model_dump(mode="json") for order in orders], page, pageSize, total
        )

    @app.get(f"{API_PREFIX}/downloads", tags=["orders"])
    async def list_downloads(
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
        page: int = 1,
        pageSize: int = 20,
    ) -> dict[str, object]:
        downloads, total = await service.list_downloads(
            session, user_id, page=page, page_size=pageSize
        )
        return paged_payload(downloads, page, pageSize, total)

    @app.post(
        f"{API_PREFIX}/subscriptions",
        response_model=Subscription,
        status_code=201,
        tags=["subscriptions"],
    )
    async def create_subscription(
        payload: CreateSubscriptionRequest,
        request: Request,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Subscription:
        subscription = await service.create_subscription(
            session,
            request.app.state.events,
            request.app.state.catalog_client,
            user_id=user_id,
            dataset_id=payload.datasetId,
            interval_sec=payload.intervalSec,
        )
        return service.to_subscription_contract(subscription)

    @app.get(f"{API_PREFIX}/subscriptions", response_model=PagedOrders, tags=["subscriptions"])
    async def list_subscriptions(
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, object]:
        """Подписки текущего покупателя (identity читает их отсюда, M6)."""
        subscriptions = await service.list_subscriptions(session, user_id)
        items = [service.to_subscription_contract(item) for item in subscriptions]
        return paged_payload(
            [item.model_dump(mode="json") for item in items], 1, max(len(items), 1), len(items)
        )

    @app.get(
        f"{API_PREFIX}/subscriptions/{{subscriptionId}}",
        response_model=Subscription,
        tags=["subscriptions"],
    )
    async def get_subscription(
        subscriptionId: str,
        _: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Subscription:
        """Подписка по идентификатору (delivery проверяет владельца сам, M6)."""
        subscription = await service.get_subscription(session, subscriptionId)
        return service.to_subscription_contract(subscription)

    async def _change_state(
        user_id: str,
        session: AsyncSession,
        subscription_id: str,
        action: SubscriptionAction,
    ) -> Subscription:
        subscription = await service.change_subscription_state(
            session,
            user_id=user_id,
            subscription_id=subscription_id,
            action=action,
        )
        return service.to_subscription_contract(subscription)

    @app.post(
        f"{API_PREFIX}/subscriptions/{{subscriptionId}}/pause",
        response_model=Subscription,
        tags=["subscriptions"],
    )
    async def pause_subscription(
        subscriptionId: str,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Subscription:
        return await _change_state(user_id, session, subscriptionId, SubscriptionAction.PAUSE)

    @app.post(
        f"{API_PREFIX}/subscriptions/{{subscriptionId}}/resume",
        response_model=Subscription,
        tags=["subscriptions"],
    )
    async def resume_subscription(
        subscriptionId: str,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Subscription:
        return await _change_state(user_id, session, subscriptionId, SubscriptionAction.RESUME)

    @app.post(
        f"{API_PREFIX}/subscriptions/{{subscriptionId}}/cancel",
        response_model=Subscription,
        tags=["subscriptions"],
    )
    async def cancel_subscription(
        subscriptionId: str,
        user_id: str = Depends(require_user),
        session: AsyncSession = Depends(get_session),
    ) -> Subscription:
        return await _change_state(user_id, session, subscriptionId, SubscriptionAction.CANCEL)

    return app


def main() -> None:
    """Запустить сервис заказов под uvicorn."""
    import uvicorn

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    _log.info("service_started", service="order")
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("SERVICE_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


__all__ = ["API_PREFIX", "create_app", "main"]
