"""
허브 리포트(md) 파서.

- 종목코드/종목명 추출(제목·파일명·결정카드 헤더·enrich 마커)
- 📋 결정카드 파싱(종목별)
- <!-- hub:enrich:begin[:CODE] --> 블록(KIS 실측)에서 시장 데이터 파싱
리포트 원문은 절대 수정하지 않는다(읽기 전용).
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from .schema import DecisionCard, Market

RE_CODE_IN_PAREN = re.compile(r"([가-힣A-Za-z0-9&·\-\.\s]{1,40}?)\s*\((\d{6})\)")
RE_ENRICH = re.compile(
    r"<!--\s*hub:enrich:begin(?::(\d{6}))?\s*-->(.*?)<!--\s*hub:enrich:end(?::\d{6})?\s*-->",
    re.S,
)
RE_CARD_HDR = re.compile(r"^📋\s*결정카드(?P<rest>[^\n]*)$", re.M)
RE_GURU_BLOCK = re.compile(
    r"<!--\s*hub:guru:begin:(\d{6})[^>]*-->.*?<!--\s*hub:guru:end:\1\s*-->\n?", re.S
)


def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("−", "-").replace("+", "")
    if s in ("", "-", "N/A", "n/a", "NA"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _amount_to_eok(num: str, unit: str) -> Optional[float]:
    v = _num(num)
    if v is None:
        return None
    return v * 10000.0 if unit == "조" else v


def _pct(s: Optional[str]) -> Optional[float]:
    v = _num(s)
    return None if v is None else v / 100.0


# ──────────────────────────────────────────────────────────────────────
# 종목 식별
# ──────────────────────────────────────────────────────────────────────
def report_stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def report_date(path: str) -> str:
    m = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", os.path.basename(path))
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"


def find_targets(text: str, path: str = "") -> List[Tuple[str, str]]:
    """리포트가 다루는 (code, name) 목록. 우선순위: 결정카드 헤더 → enrich 마커 → 제목 → 파일명."""
    found: Dict[str, str] = {}
    order: List[str] = []

    def add(code: str, name: str):
        if code not in found:
            found[code] = name.strip()
            order.append(code)
        elif not found[code] and name:
            found[code] = name.strip()

    for m in RE_CARD_HDR.finditer(text):
        rest = m.group("rest")
        mm = RE_CODE_IN_PAREN.search(rest)
        if mm:
            add(mm.group(2), mm.group(1))
    for m in re.finditer(r"<!--\s*hub:enrich:begin:(\d{6})\s*-->", text):
        add(m.group(1), "")
    first = text.split("\n", 1)[0]
    mm = RE_CODE_IN_PAREN.search(first)
    if mm:
        add(mm.group(2), mm.group(1))
    if path:
        base = re.sub(r"^\d{8}-\d{6}-", "", os.path.basename(path))   # 앞의 날짜-시각(HHMMSS) 제거
        mm2 = re.search(r"(?:^|-)(\d{6})(?=-|\.md$)", base)
        if mm2:
            add(mm2.group(1), "")
    # 이름 보강: 본문 어디든 'NAME(CODE)' 첫 등장
    for code in order:
        if not found[code]:
            mm3 = re.search(r"([가-힣A-Za-z0-9&·\-\.]{1,30})\s*\(" + code + r"\)", text)
            if mm3:
                found[code] = mm3.group(1)
    return [(c, found[c]) for c in order]


# ──────────────────────────────────────────────────────────────────────
# 결정카드
# ──────────────────────────────────────────────────────────────────────
def _card_blocks(text: str) -> List[Tuple[str, str, int]]:
    """(헤더 rest, 카드 본문, 헤더 시작 위치) 리스트. 본문 = 헤더 다음 줄부터 빈 줄 2개 또는 다음 헤더 전까지."""
    out = []
    hdrs = list(RE_CARD_HDR.finditer(text))
    for i, m in enumerate(hdrs):
        start = m.end()
        end = hdrs[i + 1].start() if i + 1 < len(hdrs) else len(text)
        body = text[start:end]
        # 카드 키:값 줄들만 (첫 빈줄 이후의 ※ 각주는 유지하되 20줄 제한)
        lines = body.strip("\n").split("\n")
        keep = []
        for ln in lines:
            if ln.startswith("<!--"):
                break
            keep.append(ln)
            if len(keep) > 24:
                break
        out.append((m.group("rest"), "\n".join(keep), m.start()))
    return out


def normalize_verdict(v: str) -> str:
    v = v.strip()
    if v.startswith("매수") or "매수추천" in v[:8]:
        return "매수"
    if v.startswith("관심") or v.startswith("中립") or v.startswith("중립"):
        return "관심"
    if v.startswith("관망") or v.startswith("회피") or v.startswith("부적합"):
        return "관망"
    return "기타"


def _first_price(s: str) -> Optional[float]:
    m = re.search(r"([\d]{1,3}(?:,\d{3})+|\d{3,})(?:\s*원)?", s)
    return _num(m.group(1)) if m else None


def parse_card(rest: str, body: str) -> DecisionCard:
    card = DecisionCard(raw=body)
    mm = RE_CODE_IN_PAREN.search(rest)
    if mm:
        card.code, card.name = mm.group(2), mm.group(1).strip()
    kv: Dict[str, str] = {}
    for ln in body.split("\n"):
        m = re.match(r"^\s*(판정|선물|현재가|진입|손절|목표|손익비|기간|촉매|반증|대상)\s*[:：]\s*(.*)$", ln)
        if m:
            kv.setdefault(m.group(1), m.group(2).strip())
    card.verdict = kv.get("판정", "")
    card.verdict_norm = normalize_verdict(card.verdict) if card.verdict else ""
    if "진입" in kv:
        card.entry = _first_price(kv["진입"])
    if "손절" in kv:
        card.stop = _first_price(kv["손절"])
    if "목표" in kv:
        prices = re.findall(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원", kv["목표"])
        if prices:
            card.target1 = _num(prices[0])
            if len(prices) > 1:
                card.target2 = _num(prices[1])
    if "손익비" in kv:
        card.rr_text = kv["손익비"]
        m = re.search(r"1\s*:\s*(\d+(?:\.\d+)?)", kv["손익비"])
        if m:
            card.rr1 = _num(m.group(1))
        else:
            m = re.search(r"(\d+(?:\.\d+)?)\s*:\s*1", kv["손익비"])
            if m:
                card.rr1 = _num(m.group(1))
    card.horizon = kv.get("기간", "")
    card.catalyst = kv.get("촉매", "")
    card.falsifier = kv.get("반증", "")
    # 카드에 진입·손절·목표가 있으면 손익비 재계산(1차)
    if card.rr1 is None and card.entry and card.stop and card.target1 and card.entry > card.stop:
        card.rr1 = round((card.target1 - card.entry) / (card.entry - card.stop), 2)
    return card


def parse_cards(text: str) -> List[DecisionCard]:
    cards = []
    for rest, body, _pos in _card_blocks(text):
        if "갱신" in rest and not RE_CODE_IN_PAREN.search(rest):
            # '📋 결정카드 갱신' 은 직전 카드의 갱신 — 코드 없는 갱신 카드는 별도 보관
            c = parse_card(rest, body)
            c.raw = "[갱신]" + c.raw
            cards.append(c)
            continue
        cards.append(parse_card(rest, body))
    return cards


def card_for(text: str, code: str, default_code: str = "") -> Optional[DecisionCard]:
    """code 의 결정카드(갱신 카드가 있으면 갱신본 우선 — 허브 규칙 '맨 끝 카드가 유효')."""
    cards = parse_cards(text)
    if not cards:
        return None
    coded = [c for c in cards if c.code == code]
    if coded:
        return coded[-1]
    uncoded = [c for c in cards if not c.code]
    if uncoded and (code == default_code or len(coded) == 0):
        return uncoded[-1]
    return None


# ──────────────────────────────────────────────────────────────────────
# enrich 블록 → Market
# ──────────────────────────────────────────────────────────────────────
def enrich_blocks(text: str) -> Dict[str, str]:
    """{code or '': block_text}. 코드 없는 블록은 '' 키."""
    out: Dict[str, str] = {}
    for m in RE_ENRICH.finditer(text):
        out[m.group(1) or ""] = m.group(2)
    return out


def parse_market(block: str, code: str, name: str = "") -> Market:
    mk = Market(code=code, name=name)
    m = re.search(r"KIS\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", block)
    if m:
        mk.asof = m.group(1)
    m = re.search(
        r"현재가\s+([\d,]+)원\s*\(([+\-−]?[\d.]+)%\)\s*·\s*시총\s+([\d.,]+)\s*(억|조)"
        r"(?:\s*·\s*5일\s+([+\-−]?[\d.]+)%\s*/\s*20일\s+([+\-−]?[\d.]+)%\s*/\s*60일\s+([+\-−]?[\d.]+)%)?",
        block,
    )
    if m:
        mk.price = _num(m.group(1))
        mk.mcap = _amount_to_eok(m.group(3), m.group(4))
        mk.ret5, mk.ret20, mk.ret60 = _pct(m.group(5)), _pct(m.group(6)), _pct(m.group(7))
        mk.raw_found.append("price")
    m = re.search(r"MA5\s+([\d,]+)원\s*/\s*MA20\s+([\d,]+)원\s*/\s*MA60\s+([\d,]+)원", block)
    if m:
        mk.ma5, mk.ma20, mk.ma60 = _num(m.group(1)), _num(m.group(2)), _num(m.group(3))
        mk.raw_found.append("ma")
    m = re.search(r"52주\s*고\s+([\d,]+)원\s*/\s*저\s+([\d,]+)원", block)
    if m:
        mk.high52, mk.low52 = _num(m.group(1)), _num(m.group(2))
    m = re.search(
        r"후행\s*PER\s+([\-−]?[\d.,]+|N/A|-)\s*/\s*PBR\s+([\-−]?[\d.,]+|N/A|-)\s*\(EPS\s+([\-−]?[\d,]+)원\s*·\s*BPS\s+([\-−]?[\d,]+)원\)",
        block,
    )
    if m:
        mk.per, mk.pbr, mk.eps, mk.bps = _num(m.group(1)), _num(m.group(2)), _num(m.group(3)), _num(m.group(4))
        if mk.per is not None and mk.per <= 0:
            mk.per = None  # 적자 → PER 무의미
        mk.raw_found.append("valuation")
    m = re.search(r"20일\s*평균\s*거래대금\s+([\d.,]+)억\s*\(5일\s+([\d.,]+)억\)", block)
    if m:
        mk.adv20 = _num(m.group(1))
    m = re.search(
        r"외국인\s*순매수\s*5일\s+([\-−]?[\d.,]+)억\s*/\s*20일\s+([\-−]?[\d.,]+)억\s*·\s*기관\s*5일\s+([\-−]?[\d.,]+)억\s*/\s*20일\s+([\-−]?[\d.,]+)억(?:\s*·\s*개인\s*20일\s+([\-−]?[\d.,]+)억)?",
        block,
    )
    if m:
        mk.frgn5, mk.frgn20, mk.orgn5, mk.orgn20 = (_num(m.group(i)) for i in range(1, 5))
        mk.indiv20 = _num(m.group(5))
        mk.raw_found.append("flows")
    if re.search(r"개별주식선물:\s*⚡\s*상장", block):
        mk.futures = True
    elif re.search(r"개별주식선물:\s*❌", block):
        mk.futures = False
    m = re.search(
        r"공매도\s*비중:\s*당일\s+([\d.]+)%.*?5일\s*평균\s+([\d.]+)%\s*/\s*20일\s*평균\s+([\d.]+)%.*?연속\s+(\d+)일",
        block,
        re.S,
    )
    if m:
        mk.short_today, mk.short5, mk.short20 = _pct(m.group(1)), _pct(m.group(2)), _pct(m.group(3))
        mk.short_above_days = int(m.group(4))
        mk.raw_found.append("short")
    m = re.search(r"ATR14\s+([\d,]+)원", block)
    if m:
        mk.atr14 = _num(m.group(1))
    return mk


def market_for(text: str, code: str, name: str = "", default_code: str = "") -> Optional[Market]:
    blocks = enrich_blocks(text)
    if code in blocks:
        return parse_market(blocks[code], code, name)
    if "" in blocks and (code == default_code or len(blocks) == 1):
        return parse_market(blocks[""], code, name)
    return None


# ──────────────────────────────────────────────────────────────────────
# 리포트 요약(LLM 정성 필터 입력용 발췌)
# ──────────────────────────────────────────────────────────────────────
def excerpt_sections(text: str, max_chars: int = 6000) -> str:
    """한줄 결론 + ②③(사업·실적) 절 발췌. hub 블록·결정카드는 제외."""
    t = RE_ENRICH.sub("", text)
    t = RE_GURU_BLOCK.sub("", t)
    t = re.sub(r"<!--\s*hub:v\d\w*:begin\s*-->.*?<!--\s*hub:v\d\w*:end\s*-->", "", t, flags=re.S)
    idx = t.find("📋 결정카드")
    if idx > 0:
        t = t[:idx]
    parts = []
    m = re.search(r"(📌\s*한줄\s*결론[^\n]*\n(?:[^\n]*\n){0,6})", t)
    if m:
        parts.append(m.group(1))
    for key in ("②", "③"):
        m = re.search(r"(" + key + r"[^\n]*\n(?:(?!^[①-⑨])[^\n]*\n){1,40})", t, re.M)
        if m:
            parts.append(m.group(1))
    out = "\n".join(parts) if parts else t[:max_chars]
    return out[:max_chars]
