"""
허브 후처리기 — 빌더(춘식이)가 index.html / 리포트 html 을 만든 '뒤'에 실행한다.
빌더 코드는 건드리지 않고, 산출물만 멱등적으로 덧씌운다.

index.html
  1) 내비에 '🧭 투자구루 판단'(guru.html) 링크
  2) 필터 칩 '🧭 구루 합의 4+' (data-f="guru:hi"), '🧭 구루 2~3' (guru:mid)  — 기존 필터 JS(data-<key>==value) 그대로 활용
  3) 각 카드 <li> 에 data-guru="hi|mid|lo" data-gurun="N" 속성 + 배지(툴팁에 구루별 판정)
  4) 상단 stats 에 '🧭 구루 평가 N'
리포트 html
  5) md 에는 블록이 있는데 html 에 없으면(빌더가 html 을 재생성하지 않은 경우) 블록을 html 로 변환해 결정카드 앞에 삽입
"""
from __future__ import annotations

import html as H
import os
import re
from typing import Dict, List, Optional, Tuple

from . import config as C
from .collect import RE_BLOCK, blocks_in_text, collect, latest_by_code
from .inject import write_atomic
from .rules import LABELS, ORDER

ICON = {"적합": "🟢", "보류": "🟡", "부적합": "🔴", "데이터부족": "⚪", "해당없음": "⚪"}
GURU_CSS = (
    '<style id="guru-css">.tag.guru-hi{color:#7ee7a1;border-color:rgba(126,231,161,.45)}'
    '.tag.guru-mid{color:#ffd166;border-color:rgba(255,209,102,.45)}'
    '.tag.guru-lo{color:#a8b0bb;border-color:rgba(168,176,187,.35)}'
    '.guru-block{border:1px solid #2a2f3a;border-radius:14px;padding:4px 16px 10px;margin:14px 0;background:#1a1d24}'
    '.guru-block table{border-collapse:collapse;width:100%;font-size:13px}'
    '.guru-block th,.guru-block td{border:1px solid #2a2f3a;padding:5px 7px;vertical-align:top;text-align:left}'
    '.guru-block th{color:#9aa2ad;font-weight:600}'
    '.guru-block td:nth-child(-n+3){white-space:nowrap}</style>'
)


def _badge(row: dict) -> str:
    fit, total, bucket = row["fit"], row.get("total", 6), row["bucket"]
    mean = row.get("mean")
    mean_s = "—" if mean is None else f"{mean:.2f}"
    per = []
    for k in ORDER:
        if k in row["v"]:
            sc = row["s"].get(k)
            sc_s = "" if sc is None else (f" {sc:.2f}" if k != "piotroski" else f" {int(round(sc*9))}/9")
            per.append(f"{LABELS[k]} {ICON.get(row['v'][k],'')}{row['v'][k]}{sc_s}")
    tip = (
        f'<div class="tp-h">🧭 투자구루 판단의견 — 적합 {fit}/{total} · 평균 {mean_s}</div>'
        f'<div class="tp-r">{H.escape(" · ".join(per))}</div>'
        f'<div class="tp-r"><b>결정카드 관계</b> {H.escape(row.get("rel",""))}</div>'
        f'<div class="tp-f">룰 점수 + LLM 정성 필터(익명화). 의견 전용 — 결정카드 판정 불변. 산식·검증 게이트: guru.html</div>'
    )
    return (f'<span class="tt guru-badge" tabindex="0"><span class="tag guru-{bucket}">🧭 구루 {fit}/{total}</span>'
            f'<span class="tip">{tip}</span></span>')


def _patch_nav(s: str) -> str:
    if 'href="./guru.html"' in s:
        return s
    return re.sub(r'(<div class="nav">.*?)(</div>)', lambda m: m.group(1) + '<a href="./guru.html">🧭 투자구루 판단</a>' + m.group(2), s, count=1, flags=re.S)


def _patch_chips(s: str) -> str:
    if 'data-f="guru:hi"' in s:
        return s
    chips = '<span class="chip" data-f="guru:hi">🧭 구루 합의 4+</span><span class="chip" data-f="guru:mid">🧭 구루 2~3</span>'
    return re.sub(r'(<div class="filters">.*?)(\n?</div>)', lambda m: m.group(1) + "\n" + chips + m.group(2), s, count=1, flags=re.S)


def _patch_css(s: str) -> str:
    if 'id="guru-css"' in s:
        return s
    return s.replace("</head>", GURU_CSS + "</head>", 1)


def _patch_stats(s: str, n: int) -> str:
    s = re.sub(r'<span class="stat">🧭 구루 평가 <b>\d+</b></span>', "", s)
    return re.sub(r'(<div class="stats">)', lambda m: m.group(1) + f'<span class="stat">🧭 구루 평가 <b>{n}</b></span>', s, count=1)


RE_CARD_HEAD = re.compile(
    r'<li class="card"([^>]*)><div class="ch"><a class="rt" href="\./([^"#]+)\.html(?:#card-(\d{6}))?">(.*?)</a><span class="tags">'
    r'(?:<span class="tt guru-badge".*?</span></span>)?',
    re.S,
)


def _patch_cards(s: str, by_key: Dict[Tuple[str, str], dict]) -> Tuple[str, int]:
    """카드의 여는 태그(data-guru 속성)와 .tags 앞머리(배지)만 바꾼다 — 나머지 카드 본문은 손대지 않는다."""
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        attrs, stem, code, title = m.group(1), m.group(2), m.group(3), m.group(4)
        if "data-st=" not in attrs:
            return m.group(0)
        if not code:
            dm = re.search(r'data-s="([^"]*)"', attrs)
            cands = re.findall(r"\b(\d{6})\b", dm.group(1)) if dm else []
            code = cands[-1] if cands else None
        attrs2 = re.sub(r'\s*data-guru="[^"]*"\s*data-gurun="[^"]*"', "", attrs)
        row = by_key.get((stem, code)) if code else None
        if not row:
            return f'<li class="card"{attrs2}><div class="ch"><a class="rt" href="./{stem}.html{"#card-"+code if m.group(3) else ""}">{title}</a><span class="tags">'
        attrs2 += f' data-guru="{row["bucket"]}" data-gurun="{row["fit"]}"'
        n += 1
        return (f'<li class="card"{attrs2}><div class="ch"><a class="rt" href="./{stem}.html{"#card-"+code if m.group(3) else ""}">{title}</a>'
                f'<span class="tags">{_badge(row)}')

    return RE_CARD_HEAD.sub(repl, s), n


def patch_index(index_path: str, rows: List[dict], dry_run: bool = False) -> int:
    with open(index_path, encoding="utf-8") as fh:
        s = fh.read()
    by_key = {(r["report"], r["code"]): r for r in rows}
    s = _patch_css(s)
    s = _patch_nav(s)
    s = _patch_chips(s)
    s, n = _patch_cards(s, by_key)
    s = _patch_stats(s, len(latest_by_code(rows)))
    if not dry_run:
        write_atomic(index_path, s)
    return n


# ──────────────────────────────────────────────────────────────────────
# 리포트 html 에 블록 삽입(빌더가 html 을 재생성하지 않는 경우 대비)
# ──────────────────────────────────────────────────────────────────────
def _inline(md: str) -> str:
    t = H.escape(md)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", t)
    return t


def md_block_to_html(md: str) -> str:
    out: List[str] = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("<!--") or not ln.strip():
            i += 1
            continue
        if ln.startswith("## "):
            out.append(f'<h2 id="guru">{_inline(ln[3:])}</h2>')
            i += 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            if len(cells) >= 2 and all(set(c) <= set("-: ") for c in cells[1]):
                head, body = cells[0], cells[2:]
            else:
                head, body = None, cells
            h = "<table>"
            if head:
                h += "<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead>"
            h += "<tbody>" + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table>"
            out.append(h)
            continue
        if ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        out.append(f"<p>{_inline(ln)}</p>")
        i += 1
    return "\n".join(out)


def patch_report_html(html_path: str, md_text: str, dry_run: bool = False) -> int:
    """md 의 각 guru 블록을 html 에 반영(이미 빌더가 렌더했으면 건너뜀). 반환: 삽입/교체 수."""
    if not os.path.exists(html_path):
        return 0
    with open(html_path, encoding="utf-8") as fh:
        h = fh.read()
    n = 0
    for m in RE_BLOCK.finditer(md_text):
        code = m.group(1)
        if f"투자구루 판단의견 — " in h and f"({code})</h2>" in h and "guru-block" not in h:
            continue  # 빌더가 md 를 재렌더한 경우(블록이 h2 로 이미 존재)
        frag = f'<!--guru:html:begin:{code}--><div class="guru-block">{md_block_to_html(m.group(0))}</div><!--guru:html:end:{code}-->'
        rx = re.compile(r"<!--guru:html:begin:" + code + r"-->.*?<!--guru:html:end:" + code + r"-->", re.S)
        if rx.search(h):
            h2 = rx.sub(lambda _m: frag, h, count=1)
        else:
            anchor = f'<span id="card-{code}"></span>'
            if anchor in h:
                h2 = h.replace("<p>" + anchor, frag + "<p>" + anchor, 1) if ("<p>" + anchor) in h else h.replace(anchor, frag + anchor, 1)
            else:
                k = h.find("📋 결정카드")
                if k < 0:
                    continue
                p = h.rfind("<p>", 0, k)
                h2 = h[:p] + frag + h[p:] if p >= 0 else h[:k] + frag + h[k:]
        if h2 != h:
            h = h2
            n += 1
    if n and "guru-css" not in h:
        h = h.replace("</head>", GURU_CSS + "</head>", 1)
    if n and not dry_run:
        write_atomic(html_path, h)
    return n


def run(repo_dir: str, dry_run: bool = False, patch_reports: bool = True) -> dict:
    rows = collect(repo_dir)
    idx = os.path.join(repo_dir, "index.html")
    n_cards = patch_index(idx, rows, dry_run=dry_run) if os.path.exists(idx) else 0
    n_html = 0
    if patch_reports:
        seen = set()
        for r in rows:
            if r["report"] in seen:
                continue
            seen.add(r["report"])
            md_path = os.path.join(repo_dir, r["report"] + ".md")
            with open(md_path, encoding="utf-8") as fh:
                md_text = fh.read()
            n_html += patch_report_html(os.path.join(repo_dir, r["report"] + ".html"), md_text, dry_run=dry_run)
    return {"blocks": len(rows), "index_cards": n_cards, "report_htmls": n_html}
