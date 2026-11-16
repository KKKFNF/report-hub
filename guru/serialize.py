"""dataclass ↔ dict/JSON (Fundamentals·Market·Regime 저장/로드)."""
from __future__ import annotations

import json
from dataclasses import asdict, fields
from typing import Any, Dict

from .schema import Flags, Fundamentals, Market, Period, Regime


def _from_dict(cls, d: Dict[str, Any]):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def fundamentals_to_dict(f: Fundamentals) -> dict:
    return asdict(f)


def fundamentals_from_dict(d: dict) -> Fundamentals:
    periods = [_from_dict(Period, p) for p in d.get("periods", [])]
    ttm_prev = _from_dict(Period, d["ttm_prev"]) if d.get("ttm_prev") else None
    flags = _from_dict(Flags, d.get("flags", {}) or {})
    return Fundamentals(
        code=d["code"], name=d.get("name", ""), periods=periods, ttm_prev=ttm_prev,
        flags=flags, fetched_at=d.get("fetched_at", ""), sources=d.get("sources", []),
    )


def market_from_dict(d: dict) -> Market:
    return _from_dict(Market, d)


def regime_from_dict(d: dict) -> Regime:
    return _from_dict(Regime, d)


def dump(obj, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(obj), fh, ensure_ascii=False, indent=2)


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
