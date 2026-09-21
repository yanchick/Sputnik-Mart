"""CLI генератора ``sim``: sensors и dirty (T125)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dirty import DirtyConfig, contaminate
from .sensors import (
    DEFAULT_INTERVAL_SEC,
    DEFAULT_PERIODS,
    DEFAULT_SEED,
    build_stations,
    generate_readings,
)


def _write(records: list[dict[str, object]], destination: str | None) -> None:
    payload = "\n".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False, default=str) for record in records
    )
    if destination:
        Path(destination).write_text(payload + ("\n" if payload else ""), encoding="utf-8")
        return
    print(payload)


def _sensors(args: argparse.Namespace) -> int:
    stations = build_stations()
    if args.stations:
        stations = stations[: args.stations]
    periods = args.periods
    if args.volume:
        periods = max(1, -(-args.volume // max(1, len(stations))))
    readings = generate_readings(
        seed=args.seed,
        stations=stations,
        interval_sec=args.interval,
        periods=periods,
    )
    _write(readings, args.out)
    return 0


def _dirty(args: argparse.Namespace) -> int:
    source = Path(args.input).read_text(encoding="utf-8") if args.input else ""
    readings: list[dict[str, object]] = []
    for line in source.splitlines():
        if line.strip():
            readings.append(json.loads(line))
    config = DirtyConfig(
        missing=args.missing,
        duplicate=args.duplicate,
        outlier=args.outlier,
        broken=args.broken,
    )
    _write(contaminate(readings, seed=args.seed, config=config), args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер CLI ``sim``."""
    parser = argparse.ArgumentParser(prog="sim", description="Генераторы «Спутник Данные»")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sensors = subparsers.add_parser("sensors", help="сгенерировать чтения датчиков")
    sensors.add_argument("--seed", type=int, default=DEFAULT_SEED)
    sensors.add_argument("--stations", type=int, default=0, help="ограничить число станций")
    sensors.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC)
    sensors.add_argument("--periods", type=int, default=DEFAULT_PERIODS)
    sensors.add_argument("--volume", type=int, default=0, help="общее число чтений")
    sensors.add_argument("--out", default=None, help="файл NDJSON вместо stdout")
    sensors.set_defaults(func=_sensors)

    dirty = subparsers.add_parser("dirty", help="загрязнить NDJSON чтений")
    dirty.add_argument("--input", default=None, help="исходный NDJSON (stdin не поддерживается)")
    dirty.add_argument("--seed", type=int, default=DEFAULT_SEED)
    dirty.add_argument("--missing", type=float, default=0.0)
    dirty.add_argument("--duplicate", type=float, default=0.0)
    dirty.add_argument("--outlier", type=float, default=0.0)
    dirty.add_argument("--broken", type=float, default=0.0)
    dirty.add_argument("--out", default=None)
    dirty.set_defaults(func=_dirty)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI ``sim``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover - ручной запуск
    sys.exit(main())


__all__ = ["build_parser", "main"]
