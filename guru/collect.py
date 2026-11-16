"""
리포트 md 의 hub:guru 블록을 다시 읽어 기계가독 요약(guru_index.json)을 만든다.
(블록이 유일한 원천 — 사이드카 파일이 어긋날 일이 없다.)
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Dict, List, Optional

from . import config as C
from .rules import LABELS

LABEL2KEY = {v: k for k, v in LABELS.items()}
RE_BLOCK = re.compile(r"<!--\s*hub:guru:begin:(\d{6})\s*(v\d+)?\s*-->(.*?)<!--\s*hub:guru:end:\1\s*-->", re.S)
RE_ROW = re.compile(r"^\|\s*([가-힣]+)\s*\|\s*([^|]*?)\s*\|\s*(?:[🟢🟡🔴⚪]\s*)?([가-힣]+)\s*\|", re.M)
RE_FIT = re.compile(r"\*\*합의\*\*\s*적합\s*(\d+)/(\d+)\s*·\s*평균\s*([\d.]+|—)\s*·\s*([^\n]*)")
RE_REL = re.compile(r"\*\*결정카드 관계\*\*\s*([^\n]*)")
RE_SNAP = re.compile(r"^\*(.*?)\*\s*$", re.M)


def parse_block(block_text: str, code: str, ver: str = "") -> dict:
    v: Dict[str, str] = {}
    s: Dict[str, Optional[float]] = {}
    for m in RE_ROW.finditer(block_text):
        label, sc, verdict = m.group(1), m.group(2).strip(), m.group(3)
        key = LABEL2KEY.get(label)
        if not key:
            continue
        v[key] = verdict
        if "/" in sc:  # 피오트로스키 n/9
            try:
                s[key] = round(float(sc.split("/")[0]) / 9.0, 2)
            except ValueError:
                s[key] = None
        else:
            try:
                s[key] = float(sc)
            except ValueError:
                s[key] = None
    fit, total, mean, summary = None, 6, None, ""
    m = RE_FIT.search(block_text)
    if m:
        fit, total = int(m.group(1)), int(m.group(2))
        mean = None if m.group(3) == "—" else float(m.group(3))
        summary = m.group(4).strip()
    if fit is None:
        fit = sum(1 for x in v.values() if x == "적합")
    bucket = "hi" if fit >= C.CONSENSUS_HI else ("mid" if fit >= C.CONSENSUS_MID else "lo")
    rel = ""
    m = RE_REL.search(block_text)
    if m:
        rel = m.group(1).strip()
    name = ""
    m = re.search(r"##\s*🧭\s*투자구루 판단의견\s*—\s*(.+?)\(" + code + r"\)", block_text)
    if m:
        name = m.group(1).strip()
    snap = ""
    snaps = RE_SNAP.findall(block_text)
    if snaps:
        snap = snaps[-1].strip()
    return {"code": code, "name": name, "ver": ver or "", "fit": fit, "total": total, "bucket": bucket,
            "mean": mean, "summary": summary, "v": v, "s": s, "rel": rel, "snapshot": snap}


def blocks_in_text(text: str) -> List[dict]:
    out = []
    for m in RE_BLOCK.finditer(text):
        out.append(parse_block(m.group(3), m.group(1), m.group(2) or ""))
    return out


def collect(repo_dir: str, pattern: str = "2026*.md") -> List[dict]:
    rows: List[dict] = []
    for path in sorted(glob.glob(os.path.join(repo_dir, pattern))):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        stem = os.path.splitext(os.path.basename(path))[0]
        for b in blocks_in_text(text):
            b["report"] = stem
            b["date"] = stem[:8]
            rows.append(b)
    return rows


def latest_by_code(rows: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x["report"]):
        out[r["code"]] = r
    return out


def write_index(rows: List[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": C.RULES_VERSION, "count": len(rows), "rows": rows}, fh, ensure_ascii=False, indent=1)


def export_ledger_csv(rows: List[dict], path: str) -> None:
    import csv
    keys = ["report", "date", "code", "name", "fit", "bucket", "mean", "rel"] + [f"v_{k}" for k in LABELS] + [f"s_{k}" for k in LABELS]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(keys)
        for r in rows:
            w.writerow([r.get("report"), r.get("date"), r.get("code"), r.get("name"), r.get("fit"), r.get("bucket"),
                        r.get("mean"), r.get("rel")] + [r["v"].get(k, "") for k in LABELS] + [r["s"].get(k, "") for k in LABELS])
