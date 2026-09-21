# syntax=docker/dockerfile:1
# Спутник Данные — общий multi-stage Dockerfile сервисов (T012).
# Сборка: docker build -f infra/docker/service.Dockerfile \
#           --build-arg SERVICE=api-gateway \
#           --build-arg SERVICE_PKG=api_gateway -t sputnik/api-gateway .
ARG PYTHON_VERSION=3.12

FROM ghcr.io/astral-sh/uv:0.11.33 AS uv

FROM python:${PYTHON_VERSION}-slim AS builder
ARG SERVICE
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY services ./services
COPY generators ./generators
COPY frontend ./frontend
COPY specs ./specs
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package "sputnik-${SERVICE}"

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG SERVICE
ARG SERVICE_PKG
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVICE_PKG=${SERVICE_PKG}
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/libs/db /app/libs/db
COPY specs ./specs
COPY scripts ./scripts
CMD ["sh", "-c", "python -c \"from ${SERVICE_PKG}.main import main; main()\""]
