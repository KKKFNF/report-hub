"""
LLM 정성 필터 입력 익명화.

목적: LLM 이 종목을 알아보고 '외운 미래'를 답하는 정보 누수(Profit Mirage 문제)를 줄인다.
 - 종목명·코드 → A사/B사…,  절대 연도 → t-0/t-1…,  분기 표기 → nQ(t-k)
 - 지표 패킷은 매출=100, 총자산=100 지수와 비율만 전달(절대 금액·시총·주가 없음)
완전한 익명화는 불가능하다(제품명·업종 서술로 식별될 수 있음). 그래서 프롬프트에서도
'회사를 추정하지 말고 제시된 사실만으로 판단'을 명령하고, 결과는 룰 점수와 섞지 않는다.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from .schema import DecisionCard, Fundamentals, Market, Period

ALIASES = ["A사", "B사", "C사", "D사", "E사", "F사", "G사", "H사"]


def anonymize_text(text: str, names: Sequence[str], codes: Sequence[str], base_year: int) -> str:
    t = text
    uniq = []
    for n in names:
        if n and n not in uniq:
            uniq.append(n)
    alias_of = {n: ALIASES[min(i, len(ALIASES) - 1)] for i, n in enumerate(uniq)}
    for nm in sorted(uniq, key=len, reverse=True):          # 긴 이름부터(세아제강지주 → 세아제강 순)
        t = re.sub(re.escape(nm) + r"(?:\(\d{6}\))?", alias_of[nm], t)
    for c in codes:
        t = t.replace(c, "######")
    t = re.sub(r"\b\d{6}\b", "######", t)

    def rel(y: int) -> str:
        k = base_year - y
        return f"t-{k}" if k >= 0 else f"t+{-k}"

    # 2026-10-10, 2026.10, 2026년
    t = re.sub(r"(20\d{2})-(\d{2})-(\d{2})", lambda m: f"{rel(int(m.group(1)))}-{m.group(2)}-{m.group(3)}", t)
    t = re.sub(r"(20\d{2})\.(\d{1,2})", lambda m: f"{rel(int(m.group(1)))}.{m.group(2)}", t)
    # 1Q26, 3Q25, FY25, FY2025, 26Q2, 2025 2Q, 2026년 2분기
    t = re.sub(r"\b([1-4])Q(\d{2})\b", lambda m: f"{m.group(1)}Q({rel(2000+int(m.group(2)))})", t)
    t = re.sub(r"\b(\d{2})Q([1-4])\b", lambda m: f"{m.group(2)}Q({rel(2000+int(m.group(1)))})", t)
    t = re.sub(r"\bFY(20)?(\d{2})\b", lambda m: f"FY({rel(2000+int(m.group(2)))})", t)
    t = re.sub(r"(20\d{2})년?\s*([1-4])분기", lambda m: f"{m.group(2)}Q({rel(int(m.group(1)))})", t)
    t = re.sub(r"(20\d{2})년?\s*([1-4])Q", lambda m: f"{m.group(2)}Q({rel(int(m.group(1)))})", t)
    t = re.sub(r"(20\d{2})\s*(상반기|하반기|반기)", lambda m: f"{m.group(2)}({rel(int(m.group(1)))})", t)
    t = re.sub(r"\b(20\d{2})년?\b", lambda m: rel(int(m.group(1))), t)
    t = re.sub(r"접수\s*\d{14}", "접수번호", t)
    return t


def _idx(v: Optional[float], base: Optional[float]) -> Optional[float]:
    if v is None or not base:
        return None
    return round(v / base * 100.0, 1)


def _r(v: Optional[float], d: int = 3) -> Optional[float]:
    return None if v is None else round(v, d)


def period_packet(p: Period) -> Dict[str, Optional[float]]:
    rev, ta = p.revenue, p.total_assets
    return {
        "label": p.label,
        "revenue_growth_base": 100.0 if rev else None,
        "gross_margin": _r((p.gross_profit / rev) if (p.gross_profit is not None and rev) else None),
        "op_margin": _r((p.op / rev) if (p.op is not None and rev) else None),
        "net_margin_parent": _r((p.ni_parent / rev) if (p.ni_parent is not None and rev) else None),
        "cfo_to_revenue": _r((p.cfo / rev) if (p.cfo is not None and rev) else None),
        "capex_to_revenue": _r((p.capex / rev) if (p.capex is not None and rev) else None),
        "roe_parent": _r((p.ni_parent / p.equity_parent) if (p.ni_parent is not None and p.equity_parent) else None),
        "equity_to_assets": _idx(p.equity_parent, ta),
        "current_assets_idx": _idx(p.current_assets, ta),
        "current_liab_idx": _idx(p.current_liab, ta),
        "cash_idx": _idx(p.cash, ta),
        "debt_idx": _idx(p.debt, ta),
        "ppe_idx": _idx(p.net_ppe, ta),
        "inventory_idx": _idx(p.inventories, ta),
        "interest_cov": _r((p.op / p.interest_exp) if (p.op is not None and p.interest_exp) else None, 1),
        "dividend_to_revenue": _r((p.dividends_paid / rev) if (p.dividends_paid is not None and rev) else None),
        "buyback_to_revenue": _r((p.buyback / rev) if (p.buyback is not None and rev) else None),
        "share_issue_flag": (None if p.share_issue_proceeds is None else (p.share_issue_proceeds > 0)),
    }


def metrics_packet(f: Optional[Fundamentals], mk: Optional[Market], card: Optional[DecisionCard]) -> dict:
    pk: dict = {"periods": [], "growth": {}, "market": {}, "flags": {}, "card": {}}
    if f and f.periods:
        pk["periods"] = [period_packet(p) for p in f.periods]
        base = f.periods[0]
        for p in f.periods[1:]:
            if base.revenue and p.revenue is not None:
                pk["growth"][f"revenue_{p.label}_vs_{base.label}"] = _r(p.revenue / base.revenue - 1)
            if base.op and base.op > 0 and p.op is not None:
                pk["growth"][f"op_{p.label}_vs_{base.label}"] = _r(p.op / base.op - 1)
        fl = f.flags
        pk["flags"] = {
            "audit_opinion": fl.audit_opinion, "going_concern": fl.going_concern, "icfr": fl.icfr_opinion,
            "dilution_potential": _r(fl.dilution_potential), "rights_issue_24m": fl.rights_issue_24m,
            "holdco": fl.holdco, "sector_group": fl.sector_group,
        }
    if mk:
        pk["market"] = {
            "per": _r(mk.per, 1), "pbr": _r(mk.pbr, 2),
            "ret5": _r(mk.ret5), "ret20": _r(mk.ret20), "ret60": _r(mk.ret60),
            "above_ma20": (None if not (mk.price and mk.ma20) else mk.price > mk.ma20),
            "above_ma60": (None if not (mk.price and mk.ma60) else mk.price > mk.ma60),
            "pos_in_52w": (None if not (mk.price and mk.high52 and mk.low52 and mk.high52 > mk.low52)
                           else _r((mk.price - mk.low52) / (mk.high52 - mk.low52))),
            "foreign20_to_adv": (None if not (mk.frgn20 is not None and mk.adv20) else _r(mk.frgn20 / (mk.adv20 * 20))),
            "inst20_to_adv": (None if not (mk.orgn20 is not None and mk.adv20) else _r(mk.orgn20 / (mk.adv20 * 20))),
            "short_ratio_20d": _r(mk.short20), "short_above_avg_days": mk.short_above_days,
            "futures_listed": mk.futures,
        }
    if card:
        pk["card"] = {
            "verdict": card.verdict_norm, "rr1": card.rr1,
            "stop_pct": (None if not (card.entry and card.stop) else _r(card.stop / card.entry - 1)),
            "target1_pct": (None if not (card.entry and card.target1) else _r(card.target1 / card.entry - 1)),
            "horizon": card.horizon,
        }
    return pk
