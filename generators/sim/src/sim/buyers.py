"""Генератор ``sim-buyers``: покупатели, машинные ключи и поведение (T100)."""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from observability.auth import hash_api_key, mask_email
from observability.pii import DEFAULT_PII_KEY, encrypt_pii, pii_key_ref

DEFAULT_SEED = 42


@dataclass(frozen=True)
class BuyerRecord:
    """Предсозданный демонстрационный покупатель."""

    user_id: str
    display_name: str
    email: str
    phone: str
    api_key_id: str
    api_key_prefix: str
    api_key: str
    scopes: tuple[str, ...]

    @property
    def masked_email(self) -> str:
        """Маскированный email для выгрузок и профиля."""
        return mask_email(self.email)


def build_buyers(seed: int = DEFAULT_SEED, count: int = 3) -> tuple[BuyerRecord, ...]:
    """Детерминированно собрать демонстрационных покупателей (FR-029)."""
    base: tuple[BuyerRecord, ...] = (
        BuyerRecord(
            "us_demo_buyer",
            "Демо Покупатель",
            "buyer@sputnik.demo",
            "+79990000001",
            "ak_demo_buyer",
            "sk_demo_buy",
            "sk_demo_buyer_key",
            ("read", "download"),
        ),
        BuyerRecord(
            "us_demo_analyst",
            "Демо Аналитик",
            "analyst@sputnik.demo",
            "+79990000002",
            "ak_demo_analyst",
            "sk_demo_ana",
            "sk_demo_analyst_key",
            ("read",),
        ),
        BuyerRecord(
            "us_demo_partner",
            "Демо Партнёр",
            "partner@sputnik.demo",
            "+79990000003",
            "ak_demo_partner",
            "sk_demo_par",
            "sk_demo_partner_key",
            ("read", "stream"),
        ),
    )
    if count <= len(base):
        return base[: max(count, 1)]
    generator = random.Random(seed)
    generated = [*base]
    for index in range(len(base), count):
        suffix = f"{index + 1:02d}"
        generated.append(
            BuyerRecord(
                f"us_sim_{suffix}",
                f"Синтетический Покупатель {suffix}",
                f"buyer{suffix}@sputnik.demo",
                f"+7999000{suffix}00",
                f"ak_sim_{suffix}",
                f"sk_sim_{suffix}"[:11],
                f"sk_sim_{suffix}_key",
                ("read", "download") if generator.random() < 0.5 else ("read",),
            )
        )
    return tuple(generated)


async def seed_buyers(
    session: AsyncSession, buyers: tuple[BuyerRecord, ...] | None = None
) -> list[str]:
    """Идемпотентно создать покупателей, PII и машинные ключи."""
    records = buyers or build_buyers()
    pii_key = os.environ.get("PII_ENCRYPTION_KEY", DEFAULT_PII_KEY)
    key_ref = pii_key_ref(pii_key)
    user_ids: list[str] = []
    for buyer in records:
        await session.execute(
            text("""
                INSERT INTO identity.users (user_id, display_name, status)
                VALUES (:user_id, :display_name, 'ACTIVE')
                ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name
                """),
            {"user_id": buyer.user_id, "display_name": buyer.display_name},
        )
        await session.execute(
            text("""
                INSERT INTO identity.pii_vault (user_id, email_enc, phone_enc, key_ref)
                VALUES (:user_id, :email, :phone, :key_ref)
                ON CONFLICT (user_id) DO UPDATE SET
                    email_enc = EXCLUDED.email_enc,
                    phone_enc = EXCLUDED.phone_enc,
                    key_ref = EXCLUDED.key_ref
                """),
            {
                "user_id": buyer.user_id,
                "email": encrypt_pii(buyer.email, pii_key),
                "phone": encrypt_pii(buyer.phone, pii_key),
                "key_ref": key_ref,
            },
        )
        await session.execute(
            text("""
                INSERT INTO identity.api_keys
                    (key_id, user_id, key_prefix, key_hash, scopes, revoked_at)
                VALUES (:key_id, :user_id, :key_prefix, :key_hash, :scopes, NULL)
                ON CONFLICT (key_id) DO UPDATE SET
                    key_hash = EXCLUDED.key_hash,
                    scopes = EXCLUDED.scopes,
                    revoked_at = NULL
                """),
            {
                "key_id": buyer.api_key_id,
                "user_id": buyer.user_id,
                "key_prefix": buyer.api_key_prefix,
                "key_hash": hash_api_key(buyer.api_key),
                "scopes": list(buyer.scopes),
            },
        )
        user_ids.append(buyer.user_id)
    return user_ids


def build_behavior(
    buyers: tuple[BuyerRecord, ...] | None = None,
    *,
    dataset_ids: tuple[str, ...] = ("ds_weather-stations", "ds_air-quality"),
    seed: int = DEFAULT_SEED,
) -> list[dict[str, object]]:
    """Детерминированный сценарий поведения покупателей (просмотры/заказы)."""
    records = buyers or build_buyers()
    generator = random.Random(seed)
    behavior: list[dict[str, object]] = []
    for buyer in records:
        for dataset_id in dataset_ids:
            behavior.append(
                {
                    "eventId": f"ev_click_{buyer.user_id}_{dataset_id}",
                    "userId": buyer.user_id,
                    "datasetId": dataset_id,
                    "kind": "CLICK",
                    "source": generator.choice(["STORE", "SAMPLE", "DOCS"]),
                    "at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
                }
            )
        behavior.append(
            {
                "eventId": f"ev_order_{buyer.user_id}",
                "userId": buyer.user_id,
                "datasetId": dataset_ids[0],
                "kind": "ORDER",
                "at": datetime(2026, 9, 1, 1, tzinfo=UTC).isoformat(),
            }
        )
    return behavior


def write_behavior(
    base_dir: Path,
    buyers: tuple[BuyerRecord, ...] | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> Path:
    """Записать сценарий поведения в ``lake/sim/buyers_behavior.json``."""
    directory = base_dir / "sim"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "buyers_behavior.json"
    path.write_text(
        json.dumps(build_behavior(buyers, seed=seed), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


__all__ = [
    "DEFAULT_SEED",
    "BuyerRecord",
    "build_behavior",
    "build_buyers",
    "seed_buyers",
    "write_behavior",
]
