"""
유니버스 통계(그린블라트 순위용).

universe_stats.json 포맷:
{
  "asof": "2026-10-19", "n": 2412, "excluded": ["금융","지주"],
  "ey":  [정렬된 값 리스트],
  "roc": [정렬된 값 리스트],
  "roe": [...], "pbr": [...]
}
`guru universe-build --codes codes.txt` 로 생성한다(DART 대량 조회, 하루 1회·재개 가능).
파일이 없으면 rules.score_greenblatt 가 절대 스케일로 폴백한다(블록에 '유니버스 통계 없음' 표기).
"""
from __future__ import annotations

import bisect
import json
import os
from typing import Dict, List, Optional


def load(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    for k in ("ey", "roc", "roe", "pbr"):
        if k in data and data[k]:
            data[k] = sorted(float(x) for x in data[k] if x is not None)
    return data


def percentile_rank(sorted_values: List[float], x: float) -> float:
    """x 가 유니버스에서 차지하는 백분위(0~1, 1 = 최상위). 값이 클수록 좋음 가정."""
    if not sorted_values:
        return 0.5
    i = bisect.bisect_left(sorted_values, x)
    return i / len(sorted_values)


def build(records: List[Dict[str, Optional[float]]], asof: str, excluded=("금융", "지주")) -> dict:
    """records: [{code, ey, roc, roe, pbr, sector_group}] → 통계 파일 dict."""
    out = {"asof": asof, "excluded": list(excluded), "n": 0, "ey": [], "roc": [], "roe": [], "pbr": []}
    for r in records:
        if r.get("sector_group") in excluded:
            continue
        ok = False
        for k in ("ey", "roc", "roe", "pbr"):
            v = r.get(k)
            if v is not None and isinstance(v, (int, float)):
                out[k].append(float(v))
                ok = True
        if ok:
            out["n"] += 1
    for k in ("ey", "roc", "roe", "pbr"):
        out[k].sort()
    return out
