"""Unit-тесты сериализации и валидации контрактов (T026)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from contracts import (
    Dataset,
    DatasetCategory,
    ErrorBody,
    ErrorDetail,
    ErrorEnvelope,
    FileFormat,
    PagedResponse,
    Pagination,
    SchemaField,
    SchemaFieldType,
)

pytestmark = pytest.mark.unit


def _dataset() -> Dataset:
    return Dataset(
        datasetId="ds_weather-stations",
        providerId="pv_metro",
        name="Метеостанции города",
        category=DatasetCategory.WEATHER,
        frequencySec=60,
        volumeEstimate="1.2M rows/month",
        pricePerUnit=1200.0,
        qualityScore=0.92,
        lastUpdatedAt=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        licence="sputnik_edu_v1",
    )


def test_dataset_round_trip_keeps_camel_case() -> None:
    payload = _dataset().model_dump(mode="json")

    assert payload["datasetId"] == "ds_weather-stations"
    assert payload["qualityScore"] == 0.92
    assert payload["lastUpdatedAt"].startswith("2026-09-07T12:00:00")
    assert Dataset.model_validate(payload) == _dataset()


def test_dataset_rejects_quality_score_out_of_range() -> None:
    with pytest.raises(ValidationError):
        Dataset.model_validate({**_dataset().model_dump(), "qualityScore": 1.5})


def test_dataset_rejects_invalid_id_pattern() -> None:
    with pytest.raises(ValidationError):
        Dataset.model_validate({**_dataset().model_dump(), "datasetId": "weather"})


def test_dataset_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Dataset.model_validate({**_dataset().model_dump(), "unknown": 1})


def test_schema_field_defaults_and_type() -> None:
    field = SchemaField.model_validate({"name": "temperature", "type": "DOUBLE"})

    assert field.type is SchemaFieldType.DOUBLE
    assert field.nullable is True
    assert field.unit is None


def test_pagination_contract_shape() -> None:
    pagination = Pagination(page=1, pageSize=20, total=3, totalPages=1, hasMore=False)

    assert pagination.model_dump() == {
        "page": 1,
        "pageSize": 20,
        "total": 3,
        "totalPages": 1,
        "hasMore": False,
    }


def test_paged_response_of_datasets() -> None:
    response = PagedResponse[Dataset](
        data=[_dataset()],
        pagination=Pagination(page=1, pageSize=20, total=1, totalPages=1, hasMore=False),
    )

    payload = response.model_dump(mode="json")
    assert payload["data"][0]["datasetId"] == "ds_weather-stations"
    assert payload["pagination"]["hasMore"] is False


def test_error_envelope_exact_shape() -> None:
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code="VALIDATION_ERROR",
            message="Некорректный запрос",
            requestId="req_abc123",
            details=[ErrorDetail(field="email", message="bad", code="INVALID_FORMAT")],
        )
    )

    assert envelope.model_dump() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Некорректный запрос",
            "requestId": "req_abc123",
            "details": [{"field": "email", "message": "bad", "code": "INVALID_FORMAT"}],
        }
    }


def test_error_envelope_requires_code_and_message() -> None:
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate({"error": {"code": "X"}})


def test_file_format_values() -> None:
    assert [item.value for item in FileFormat] == ["CSV", "JSON", "PARQUET"]
