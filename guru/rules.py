"""
룰 레이어 — 6명의 구루를 결정론적 수식으로 번역한다.

원칙
 1. 같은 입력이면 같은 출력(난수·LLM 없음). 가중치·임계값은 config.py 가 유일한 원천.
 2. 계산 불가 지표는 빼고 가중치를 재정규화한다. 가중치 커버리지가 MIN_WEIGHT_COVERAGE 미만이면
    점수를 내지 않고 '데이터부족'으로 표기한다(억지로 채우지 않음).
 3. 하드페일(감사의견 등)은 점수와 무관하게 '부적합'.
 4. 모든 근거 문장에 사용한 숫자를 그대로 적어 사람이 검산할 수 있게 한다.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Dict, List, Optional, Sequence, Tuple

from . import config as C
from .schema import DecisionCard, Fundamentals, GuruVerdict, Market, Period, Regime

LABELS = {
    "buffett": "버핏",
    "munger": "멍거",
    "graham": "그레이엄",
    "piotroski": "피오트로스키",
    "greenblatt": "그린블라트",
    "druckenmiller": "드러켄밀러",
}
ORDER = ["buffett", "munger", "druckenmiller", "graham", "piotroski", "greenblatt"]


# ──────────────────────────────────────────────────────────────────────
# 수학 도우미
# ──────────────────────────────────────────────────────────────────────
def s(x: Optional[float], lo: float, hi: float) -> Optional[float]:
    """선형 스케일 → [0,1]. lo > hi 이면 '낮을수록 좋음'으로 반전."""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    if lo == hi:
        return 0.5
    v = (x - lo) / (hi - lo)
    return max(0.0, min(1.0, v))


def cv(values: Sequence[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    m = mean(vals)
    if m <= 0:
        return None
    return pstdev(vals) / m


def ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def pct(x: Optional[float], d: int = 1) -> str:
    return "n/a" if x is None else f"{x*100:.{d}f}%"


def fx(x: Optional[float], d: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{d}f}"


def _finalize(gv: GuruVerdict, weights: Dict[str, float], fit=C.VERDICT_FIT, hold=C.VERDICT_HOLD) -> GuruVerdict:
    avail = {k: v for k, v in gv.components.items() if v is not None}
    wsum = sum(weights[k] for k in avail)
    gv.coverage = round(wsum, 3)
    if wsum < C.MIN_WEIGHT_COVERAGE:
        gv.score = None
        gv.verdict = "데이터부족"
        return gv
    base = sum(weights[k] * avail[k] for k in avail) / wsum
    adj = sum(float(a.split("|")[0]) for a in gv.adjustments if not a.startswith("HARDFAIL"))
    score = max(0.0, min(1.0, base + adj))
    gv.score = round(score, 3)
    if any(a.startswith("HARDFAIL") for a in gv.adjustments):
        gv.verdict = "부적합"
    elif score >= fit:
        gv.verdict = "적합"
    elif score >= hold:
        gv.verdict = "보류"
    else:
        gv.verdict = "부적합"
    return gv


def _adj(gv: GuruVerdict, delta: float, why: str):
    gv.adjustments.append(f"{delta:+.2f}|{why}")


def _hardfail(gv: GuruVerdict, why: str):
    gv.adjustments.append(f"HARDFAIL|{why}")


def _audit_bad(f: Optional[Fundamentals]) -> Optional[str]:
    if f is None:
        return None
    if f.flags.going_concern:
        return "계속기업 불확실성"
    if f.flags.audit_opinion and f.flags.audit_opinion != "적정":
        return f"감사의견 {f.flags.audit_opinion}"
    return None


def _per_pbr(mk: Optional[Market]) -> Tuple[Optional[float], Optional[float]]:
    if mk is None:
        return None, None
    per = mk.per
    if per is None and mk.price and mk.eps and mk.eps > 0:
        per = mk.price / mk.eps
    return per, mk.pbr


def _roe_series(f: Fundamentals) -> List[Tuple[str, float]]:
    out = []
    for p in f.periods:
        r = ratio(p.ni_parent, p.equity_parent)
        if r is not None:
            out.append((p.label, r))
    return out


def _invested_capital(p: Period) -> Optional[float]:
    """그린블라트 투하자본: (유동자산−현금) − (유동부채−단기차입) + 순유형자산."""
    if p.current_assets is None or p.current_liab is None or p.net_ppe is None:
        return None
    ca = p.current_assets - (p.cash or 0.0)
    cl = p.current_liab - (p.st_debt or 0.0)
    ic = (ca - cl) + p.net_ppe
    return ic if ic > 0 else None


# ──────────────────────────────────────────────────────────────────────
# 1) 버핏
# ──────────────────────────────────────────────────────────────────────
def score_buffett(f: Optional[Fundamentals], mk: Optional[Market]) -> GuruVerdict:
    cfg = C.BUFFETT
    gv = GuruVerdict("buffett", LABELS["buffett"], None, "")
    W = cfg["weights"]
    comp: Dict[str, Optional[float]] = {k: None for k in W}

    if f is None or not f.periods:
        gv.missing.append("DART 재무제표(연결) 전체")
    else:
        roes = _roe_series(f)
        if roes:
            ra = mean([r for _, r in roes])
            rm = min(r for _, r in roes)
            comp["roe_avg"] = s(ra, *cfg["scales"]["roe_avg"])
            comp["roe_min"] = s(rm, *cfg["scales"]["roe_min"])
            gv.values["roe_avg"], gv.values["roe_min"] = ra, rm
            gv.reasons.append(f"지배주주 ROE 평균 {pct(ra)} · 최저 {pct(rm)} ({len(roes)}기)")
        else:
            gv.missing.append("ROE(지배주주순이익·지배주주지분)")
        t = f.ttm()
        if t and t.cfo is not None and t.capex is not None and mk and mk.mcap:
            fcf = t.cfo - t.capex
            fy = fcf / mk.mcap
            comp["fcf_yield"] = s(fy, *cfg["scales"]["fcf_yield"])
            gv.values["fcf_yield"] = fy
            gv.reasons.append(f"FCF(영업CF−CAPEX) {fcf:,.0f}억 → FCF 수익률 {pct(fy)}")
            if fcf <= 0:
                _adj(gv, *cfg["penalty"]["fcf_neg"])
        else:
            gv.missing.append("FCF 수익률(영업CF·CAPEX·시총)")
        opms = [ratio(p.op, p.revenue) for p in f.periods]
        opms = [o for o in opms if o is not None]
        if len(opms) >= 2:
            c = cv(opms)
            stab = 0.0 if c is None else max(0.0, 1.0 - c)
            comp["opm_stability"] = stab
            gv.values["opm_cv"] = c
            gv.reasons.append(f"영업이익률 {'/'.join(pct(o,0) for o in opms)} → 안정성 {stab:.2f}")
        else:
            gv.missing.append("영업이익률 시계열")
        if t:
            if t.interest_exp and t.interest_exp > 0 and t.op is not None:
                cov = t.op / t.interest_exp
                comp["interest_cov"] = s(cov, *cfg["scales"]["interest_cov"])
                gv.values["interest_cov"] = cov
                gv.reasons.append(f"이자보상배율 {cov:.1f}배")
                if cov < 3:
                    _adj(gv, *cfg["penalty"]["cov_lo"])
                if cov < 1.5:
                    _hardfail(gv, cfg["hard_fail"][1])
            elif t.debt is not None and t.debt == 0:
                comp["interest_cov"] = 1.0
                gv.reasons.append("무차입(이자보상배율 상한 처리)")
            else:
                gv.missing.append("이자보상배율(금융비용)")
            nde = None
            if t.debt is not None and t.cash is not None and t.equity_parent:
                nde = (t.debt - t.cash) / t.equity_parent
                gv.values["net_debt_to_equity"] = nde
                gv.reasons.append(f"순차입금/자본 {nde:.2f}")
                if nde > 1.0:
                    _adj(gv, *cfg["penalty"]["net_debt_hi"])
                if nde > 2.0:
                    _hardfail(gv, cfg["hard_fail"][2])
            # 주주환원
            fys = f.fiscal_years()
            last = fys[-1] if fys else t
            if last and mk and mk.mcap and (last.dividends_paid is not None or last.buyback is not None):
                sy = ((last.dividends_paid or 0.0) + (last.buyback or 0.0)) / mk.mcap
                gv.values["shareholder_yield"] = sy
                if sy >= 0.03:
                    _adj(gv, *cfg["bonus"]["shareholder_yld"])
                gv.reasons.append(f"주주환원수익률(배당+자사주) {pct(sy)}")
            if roes and nde is not None and mean([r for _, r in roes]) >= 0.15 and nde <= 0.3:
                _adj(gv, *cfg["bonus"]["quality_combo"])
        # 플래그
        d = f.flags.dilution_potential
        if d is not None:
            gv.values["dilution"] = d
            if d >= 0.05:
                _adj(gv, *cfg["penalty"]["dilution_5"])
            if d >= 0.15:
                _adj(gv, *cfg["penalty"]["dilution_15"])
        if f.flags.rights_issue_24m:
            _adj(gv, *cfg["penalty"]["rights_issue"])
        bad = _audit_bad(f)
        if bad:
            _hardfail(gv, f"{bad} — {cfg['hard_fail'][0]}")

    per, pbr = _per_pbr(mk)
    if per is not None or pbr is not None:
        parts = []
        if per is not None and per > 0:
            parts.append(s(1.0 / per, *cfg["scales"]["per_inv"]))
        if pbr is not None and pbr > 0:
            parts.append(s(pbr, *cfg["scales"]["pbr"]))
        comp["valuation"] = mean(parts) if parts else None
        gv.values["per"], gv.values["pbr"] = per, pbr
        gv.reasons.append(f"후행 PER {fx(per,1)} · PBR {fx(pbr)}")
    else:
        gv.missing.append("밸류에이션(PER·PBR)")

    gv.components = comp
    return _finalize(gv, W)


# ──────────────────────────────────────────────────────────────────────
# 2) 멍거
# ──────────────────────────────────────────────────────────────────────
def score_munger(f: Optional[Fundamentals]) -> GuruVerdict:
    cfg = C.MUNGER
    gv = GuruVerdict("munger", LABELS["munger"], None, "")
    W = cfg["weights"]
    comp: Dict[str, Optional[float]] = {k: None for k in W}
    if f is None or not f.periods:
        gv.missing.append("DART 재무제표(연결) 전체")
        gv.components = comp
        return _finalize(gv, W)

    ops = [p.op for p in f.periods if p.op is not None]
    if len(ops) >= 3:
        c = cv(ops)
        pred = 0.0 if c is None else max(0.0, 1.0 - c)
        comp["predictability"] = pred
        gv.values["op_cv"] = c
        gv.reasons.append(f"영업이익 {'/'.join(f'{o:,.0f}' for o in ops)}억 → 변동계수 {fx(c)} · 예측가능성 {pred:.2f}")
        losses = sum(1 for o in ops if o <= 0)
        if losses:
            d, why = cfg["penalty"]["loss_period"]
            _adj(gv, max(-0.20, d * losses), f"{why}: {losses}회")
    else:
        gv.missing.append("영업이익 시계열(3기 이상)")

    roics = []
    for p in f.periods:
        ic = _invested_capital(p)
        if ic and p.op is not None:
            roics.append(p.op * (1 - cfg["scales"]["tax_rate"]) / ic)
    if roics:
        persist = sum(1 for r in roics if r >= cfg["scales"]["roic_threshold"]) / len(roics)
        comp["roic_persist"] = persist
        gv.values["roic_last"] = roics[-1]
        gv.reasons.append(f"세후 ROIC {'/'.join(pct(r,0) for r in roics)} → ≥10% 기간 비율 {persist:.2f}")
    else:
        gv.missing.append("ROIC(순운전자본·순유형자산)")

    t = f.ttm()
    gm = ratio(t.gross_profit, t.revenue) if t else None
    if gm is not None:
        comp["gross_margin"] = s(gm, *cfg["scales"]["gross_margin"])
        gv.values["gross_margin"] = gm
        gv.reasons.append(f"매출총이익률(TTM) {pct(gm)}")
    else:
        gv.missing.append("매출총이익률")

    rp = f.flags.related_party_sales_ratio
    if rp is not None:
        comp["related_party"] = max(0.0, 1.0 - rp / cfg["scales"]["related_party_cap"])
        gv.values["related_party"] = rp
        gv.reasons.append(f"특수관계자 매출비중 {pct(rp)}")
        if rp > 0.5:
            _hardfail(gv, cfg["hard_fail"][1])
    else:
        gv.missing.append("특수관계자 매출비중(주석)")

    gov_w, gov_v = 0.0, 0.0
    if f.flags.audit_opinion is not None:
        gov_w += 0.6
        gov_v += 0.6 if f.flags.audit_opinion == "적정" else 0.0
    if f.flags.icfr_opinion is not None:
        gov_w += 0.4
        gov_v += 0.4 if f.flags.icfr_opinion == "적정" else 0.0
    if gov_w > 0:
        comp["governance"] = gov_v / gov_w
        gv.reasons.append(f"감사의견 {f.flags.audit_opinion or 'n/a'} · 내부회계 {f.flags.icfr_opinion or 'n/a'}")
    else:
        gv.missing.append("감사의견·내부회계 의견")

    d = f.flags.dilution_potential
    if d is not None and d >= 0.05:
        _adj(gv, *cfg["penalty"]["dilution_5"])
    if f.flags.holdco:
        _adj(gv, *cfg["penalty"]["holdco"])
    bad = _audit_bad(f)
    if bad:
        _hardfail(gv, f"{bad} — {cfg['hard_fail'][0]}")

    gv.components = comp
    return _finalize(gv, W)


# ──────────────────────────────────────────────────────────────────────
# 3) 그레이엄
# ──────────────────────────────────────────────────────────────────────
def score_graham(f: Optional[Fundamentals], mk: Optional[Market]) -> GuruVerdict:
    cfg = C.GRAHAM
    gv = GuruVerdict("graham", LABELS["graham"], None, "")
    tests: Dict[str, Optional[float]] = {k: None for k in cfg["tests"]}
    if f is None or not f.periods:
        gv.missing.append("DART 재무제표(연결) 전체")
    else:
        t = f.ttm()
        cr = ratio(t.current_assets, t.current_liab) if t else None
        if cr is not None:
            tests["current_ratio"] = 1.0 if cr >= 2.0 else (0.5 if cr >= 1.5 else 0.0)
            gv.values["current_ratio"] = cr
            gv.reasons.append(f"유동비율 {cr:.2f}")
        else:
            gv.missing.append("유동비율")
        if t and t.lt_debt is not None and t.current_assets is not None and t.current_liab is not None:
            nca = t.current_assets - t.current_liab
            tests["lt_debt_nca"] = 1.0 if t.lt_debt <= nca else 0.0
            gv.reasons.append(f"장기차입 {t.lt_debt:,.0f}억 vs 순유동자산 {nca:,.0f}억")
        else:
            gv.missing.append("장기차입금·순유동자산")
        nis = [p.ni_parent for p in f.periods if p.ni_parent is not None]
        if len(nis) >= 3:
            tests["earnings_pos"] = 1.0 if all(n > 0 for n in nis) else 0.0
            gv.reasons.append(f"지배주주순이익 {len(nis)}기 {'전부 흑자' if all(n>0 for n in nis) else '적자 포함'}")
        else:
            gv.missing.append("순이익 시계열(3기 이상)")
        fys = f.fiscal_years()[-3:]
        if fys and any(p.dividends_paid is not None or p.buyback is not None for p in fys):
            yrs = sum(1 for p in fys if (p.dividends_paid or 0) > 0 or (p.buyback or 0) > 0)
            tests["dividend_rec"] = 1.0 if yrs >= len(fys) else (0.5 if yrs >= 2 else 0.0)
            gv.reasons.append(f"배당·자사주 실행 {yrs}/{len(fys)}년")
        else:
            gv.missing.append("배당·자사주 기록")
        if len(nis) >= 3 and nis[0] > 0 and nis[-1] > 0:
            g = nis[-1] / nis[0] - 1
            tests["eps_growth"] = 1.0 if g >= 0.10 else (0.5 if g >= 0 else 0.0)
            gv.values["eps_growth_3y"] = g
            gv.reasons.append(f"3년 이익성장(EPS 대용) {pct(g,0)}")
        elif len(nis) >= 3:
            tests["eps_growth"] = 0.0
        # 넷넷
        if t and mk and mk.mcap and t.current_assets is not None and t.total_liab is not None:
            ncav = t.current_assets - t.total_liab
            gv.values["ncav"] = ncav
            if ncav > 0 and mk.mcap <= 0.67 * ncav:
                gv.tags.append("넷넷(net-net)")
    per, pbr = _per_pbr(mk)
    if per is not None:
        tests["per_cap"] = 1.0 if per <= 15 else (0.5 if per <= 20 else 0.0)
    else:
        gv.missing.append("PER")
    if per is not None and pbr is not None:
        tests["per_x_pbr"] = 1.0 if per * pbr <= 22.5 else 0.0
        gv.reasons.append(f"PER {per:.1f} × PBR {pbr:.2f} = {per*pbr:.1f}")
    elif pbr is None:
        gv.missing.append("PBR")

    avail = {k: v for k, v in tests.items() if v is not None}
    gv.components = {k: (v if v is not None else None) for k, v in tests.items()}
    gv.coverage = round(len(avail) / len(tests), 3)
    if len(avail) < 4:
        gv.verdict = "데이터부족"
        gv.score = None
        return gv
    score = sum(avail.values()) / len(tests)   # 미확인 검사는 0점 처리(보수적)
    if "넷넷(net-net)" in gv.tags:
        score = min(1.0, score + cfg["netnet_bonus"][0])
        _adj(gv, cfg["netnet_bonus"][0], "넷넷 보너스")
    gv.score = round(score, 3)
    gv.verdict = "적합" if score >= 0.70 else ("보류" if score >= 0.45 else "부적합")
    gv.reasons.insert(0, f"7개 검사 통과점수 {sum(avail.values()):.1f}/7 (미확인 {len(tests)-len(avail)}개는 0점)")
    return gv


# ──────────────────────────────────────────────────────────────────────
# 4) 피오트로스키
# ──────────────────────────────────────────────────────────────────────
def score_piotroski(f: Optional[Fundamentals]) -> GuruVerdict:
    gv = GuruVerdict("piotroski", LABELS["piotroski"], None, "")
    sig: Dict[str, Optional[float]] = {k: None for k, _ in C.PIOTROSKI["signals"]}
    if f is None or not f.periods:
        gv.missing.append("DART 재무제표(연결) 전체")
        gv.components = sig
        gv.verdict = "데이터부족"
        return gv
    cur, prv = f.ttm(), f.prev()
    basis = f"{cur.label} vs {prv.label}" if (cur and prv) else (cur.label if cur else "")
    roa = ratio(cur.ni_parent, cur.total_assets) if cur else None
    if roa is not None:
        sig["roa_pos"] = 1.0 if roa > 0 else 0.0
        gv.values["roa"] = roa
    if cur and cur.cfo is not None:
        sig["cfo_pos"] = 1.0 if cur.cfo > 0 else 0.0
    if cur and cur.cfo is not None and cur.ni_total is not None:
        sig["accrual"] = 1.0 if cur.cfo > cur.ni_total else 0.0
    elif cur and cur.cfo is not None and cur.ni_parent is not None:
        sig["accrual"] = 1.0 if cur.cfo > cur.ni_parent else 0.0
    if cur and cur.share_issue_proceeds is not None:
        sig["no_issue"] = 1.0 if cur.share_issue_proceeds <= 0 else 0.0
    elif cur and prv and cur.shares_out and prv.shares_out:
        sig["no_issue"] = 1.0 if cur.shares_out <= prv.shares_out else 0.0
    if prv:
        roa_p = ratio(prv.ni_parent, prv.total_assets)
        if roa is not None and roa_p is not None:
            sig["d_roa"] = 1.0 if roa > roa_p else 0.0
        lev, lev_p = ratio(cur.lt_debt, cur.total_assets), ratio(prv.lt_debt, prv.total_assets)
        if lev is not None and lev_p is not None:
            sig["d_leverage"] = 1.0 if lev < lev_p else 0.0
        cr, cr_p = ratio(cur.current_assets, cur.current_liab), ratio(prv.current_assets, prv.current_liab)
        if cr is not None and cr_p is not None:
            sig["d_liquidity"] = 1.0 if cr > cr_p else 0.0
        gm, gm_p = ratio(cur.gross_profit, cur.revenue), ratio(prv.gross_profit, prv.revenue)
        if gm is not None and gm_p is not None:
            sig["d_gm"] = 1.0 if gm > gm_p else 0.0
        at, at_p = ratio(cur.revenue, cur.total_assets), ratio(prv.revenue, prv.total_assets)
        if at is not None and at_p is not None:
            sig["d_turnover"] = 1.0 if at > at_p else 0.0
    avail = {k: v for k, v in sig.items() if v is not None}
    gv.components = sig
    gv.coverage = round(len(avail) / 9, 3)
    gv.missing += [desc for k, desc in C.PIOTROSKI["signals"] if sig[k] is None]
    if len(avail) < 5:
        gv.verdict = "데이터부족"
        gv.score = None
        gv.reasons.append(f"평가 가능 신호 {len(avail)}/9 ({basis})")
        return gv
    F = sum(avail.values())
    gv.score = round(F / 9.0, 3)
    gv.values["f_score"] = F
    gv.verdict = "적합" if F >= 7 else ("보류" if F >= 4 else "부적합")
    passed = [k for k, v in avail.items() if v == 1.0]
    gv.reasons.append(f"F-Score {int(F)}/9 ({basis}) · 통과: {', '.join(passed) if passed else '없음'}")
    return gv


# ──────────────────────────────────────────────────────────────────────
# 5) 그린블라트
# ──────────────────────────────────────────────────────────────────────
def score_greenblatt(f: Optional[Fundamentals], mk: Optional[Market], universe: Optional[dict] = None) -> GuruVerdict:
    cfg = C.GREENBLATT
    gv = GuruVerdict("greenblatt", LABELS["greenblatt"], None, "")
    gv.components = {"ey": None, "roc": None}
    if f is None or not f.periods or mk is None or not mk.mcap:
        gv.missing.append("영업이익(TTM)·EV 구성요소·시총")
        gv.verdict = "데이터부족"
        return gv
    if f.flags.sector_group in ("금융", "지주"):
        gv.verdict = "해당없음"
        gv.reasons.append(f"{f.flags.sector_group} — 마법공식 비적용 업종")
        return gv
    t = f.ttm()
    if t.op is None or t.op <= 0:
        gv.verdict = "부적합"
        gv.score = 0.0
        gv.reasons.append(f"영업이익(TTM) {fx(t.op,0)}억 ≤ 0 → 부적격")
        return gv
    if t.debt is None or t.cash is None:
        gv.missing.append("총차입금·현금성자산(EV)")
        gv.verdict = "데이터부족"
        return gv
    ev = mk.mcap + t.debt - t.cash
    ic = _invested_capital(t)
    if ev <= 0 or ic is None:
        gv.verdict = "부적합" if ev <= 0 else "데이터부족"
        gv.reasons.append(f"EV {ev:,.0f}억 · 투하자본 {fx(ic,0)}")
        return gv
    ey, roc = t.op / ev, t.op / ic
    gv.values.update({"ey": ey, "roc": roc, "ev": ev, "invested_capital": ic})
    if universe and universe.get("ey") and universe.get("roc"):
        from .universe import percentile_rank
        pe, pr = percentile_rank(universe["ey"], ey), percentile_rank(universe["roc"], roc)   # 0~1, 높을수록 상위
        gv.components = {"ey": pe, "roc": pr}
        score = (pe + pr) / 2.0
        gv.reasons.append(f"EY {pct(ey)} (상위 {pct(1-pe,0)}) · ROC {pct(roc)} (상위 {pct(1-pr,0)}) · 유니버스 N={universe.get('n')}")
    else:
        se, sr = s(ey, *cfg["fallback_scales"]["ey"]), s(roc, *cfg["fallback_scales"]["roc"])
        gv.components = {"ey": se, "roc": sr}
        score = (se + sr) / 2.0
        gv.reasons.append(f"EY {pct(ey)} · ROC {pct(roc)} (유니버스 통계 없음 → 절대 스케일)")
        gv.missing.append("유니버스 순위(universe_stats.json)")
    cov = ratio(t.op, t.interest_exp) if t.interest_exp else None
    if cov is not None and cov < 3:
        _adj(gv, *cfg["safety_penalty"]["cov_lo"])
    de = ratio(t.debt, t.equity_parent)
    if de is not None and de > 1.0:
        _adj(gv, *cfg["safety_penalty"]["de_hi"])
    score = max(0.0, min(1.0, score + sum(float(a.split("|")[0]) for a in gv.adjustments)))
    gv.score = round(score, 3)
    gv.coverage = 1.0
    gv.verdict = "적합" if score >= C.VERDICT_FIT else ("보류" if score >= C.VERDICT_HOLD else "부적합")
    return gv


# ──────────────────────────────────────────────────────────────────────
# 6) 드러켄밀러 — 상황 점수
# ──────────────────────────────────────────────────────────────────────
def regime_score(rg: Optional[Regime]) -> Tuple[Optional[float], List[str]]:
    if rg is None:
        return None, []
    parts, notes = [], []
    if rg.kospi_above_ma200 is not None:
        parts.append(1.0 if rg.kospi_above_ma200 else 0.0)
        notes.append(f"KOSPI MA200 {'위' if rg.kospi_above_ma200 else '아래'}")
    if rg.vkospi is not None:
        parts.append(1.0 if rg.vkospi < 25 else 0.0)
        notes.append(f"VKOSPI {rg.vkospi:.1f}")
    if rg.usdkrw_ret20 is not None:
        parts.append(1.0 if rg.usdkrw_ret20 < 0 else 0.0)
        notes.append(f"USDKRW 20일 {pct(rg.usdkrw_ret20)}")
    if rg.foreign_net20_market is not None:
        parts.append(1.0 if rg.foreign_net20_market > 0 else 0.0)
        notes.append(f"외인 시장 20일 {rg.foreign_net20_market:+,.0f}억")
    if not parts:
        return None, []
    return sum(parts) / len(parts), notes


def score_druckenmiller(f: Optional[Fundamentals], mk: Optional[Market], card: Optional[DecisionCard], rg: Optional[Regime]) -> GuruVerdict:
    cfg = C.DRUCKENMILLER
    gv = GuruVerdict("druckenmiller", LABELS["druckenmiller"], None, "")
    W = cfg["weights"]
    comp: Dict[str, Optional[float]] = {k: None for k in W}

    rs, notes = regime_score(rg)
    if rs is None:
        comp["regime"] = 0.5
        gv.missing.append("시장 레짐 파일(market_regime.json) → 중립 0.5 적용")
        gv.reasons.append("레짐: 데이터 없음 → 중립 0.5")
    else:
        comp["regime"] = rs
        gv.values["regime"] = rs
        gv.reasons.append("레짐 " + " · ".join(notes) + f" → {rs:.2f}")

    if mk and mk.ret60 is not None:
        tr = 0.6 * s(mk.ret60, *cfg["scales"]["ret60"])
        above = []
        if mk.price and mk.ma20:
            above.append(1.0 if mk.price > mk.ma20 else 0.0)
        if mk.price and mk.ma60:
            above.append(1.0 if mk.price > mk.ma60 else 0.0)
        tr += 0.4 * (mean(above) if above else 0.5)
        comp["trend_rs"] = tr
        gv.values["ret60"] = mk.ret60
        gv.reasons.append(f"60일 {pct(mk.ret60)} · MA20/MA60 상회 {'/'.join('O' if a else 'X' for a in above) or 'n/a'}")
    else:
        gv.missing.append("60일 수익률·이동평균(enrich)")

    if mk and mk.frgn20 is not None and mk.orgn20 is not None and mk.adv20:
        frac = (mk.frgn20 + mk.orgn20) / (mk.adv20 * 20.0)
        fl = s(frac, *cfg["scales"]["flow_frac"])
        if mk.short_above_days is not None and mk.short_above_days >= 5:
            fl = max(0.0, fl - 0.25)
            gv.adjustments.append("+0.00|공매도 20일 평균 상회 연속 ≥5일 → flows −0.25 반영")
        comp["flows"] = fl
        gv.values["flow_frac"] = frac
        gv.reasons.append(f"외인20 {mk.frgn20:+,.0f}억 · 기관20 {mk.orgn20:+,.0f}억 / ADV20×20 → {pct(frac)}")
    else:
        gv.missing.append("수급(외인·기관 20일·ADV20)")

    if card and card.rr1 is not None:
        comp["asymmetry"] = s(card.rr1, *cfg["scales"]["rr"])
        gv.values["rr1"] = card.rr1
        gv.reasons.append(f"결정카드 1차 손익비 1:{card.rr1:.2f}")
    else:
        gv.missing.append("결정카드 손익비")

    if f and f.ttm():
        cur, prv = f.ttm(), f.prev()
        yoy = None
        if prv and prv.op and prv.op > 0 and cur.op is not None:
            yoy = cur.op / prv.op - 1
        fys = f.fiscal_years()
        accel = None
        if fys and cur.label.startswith("TTM") and fys[-1].op is not None and cur.op is not None:
            accel = 1.0 if cur.op > fys[-1].op else 0.0
        if yoy is not None or accel is not None:
            parts = []
            if yoy is not None:
                parts.append((0.6, s(yoy, *cfg["scales"]["op_yoy"])))
            if accel is not None:
                parts.append((0.4, accel))
            comp["change"] = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
            gv.values["op_yoy"] = yoy
            gv.reasons.append(f"영업이익 YoY {pct(yoy,0)} · 최근 TTM>직전FY {'O' if accel==1.0 else ('X' if accel==0.0 else 'n/a')}")
        else:
            gv.missing.append("영업이익 변화(YoY)")
    else:
        gv.missing.append("영업이익 변화(DART)")

    gv.components = comp
    gv = _finalize(gv, W)
    if gv.score is not None:
        if comp["regime"] is not None and comp["regime"] < 0.25 and gv.verdict == "적합":
            gv.verdict = "보류"
            gv.adjustments.append("+0.00|약세 레짐(<0.25) → 판정 상한 보류")
        if card and card.rr1 is not None and card.rr1 >= 3 and gv.score >= 0.70 and gv.coverage >= 0.95:
            gv.tags.append("집중 베팅 후보(손실한도 유지)")   # 5개 구성요소가 모두 산출된 경우에만
    return gv


# ──────────────────────────────────────────────────────────────────────
# 전체 실행 + 합의
# ──────────────────────────────────────────────────────────────────────
def run_all(f: Optional[Fundamentals], mk: Optional[Market], card: Optional[DecisionCard],
            rg: Optional[Regime], universe: Optional[dict] = None) -> List[GuruVerdict]:
    out = {
        "buffett": score_buffett(f, mk),
        "munger": score_munger(f),
        "druckenmiller": score_druckenmiller(f, mk, card, rg),
        "graham": score_graham(f, mk),
        "piotroski": score_piotroski(f),
        "greenblatt": score_greenblatt(f, mk, universe),
    }
    return [out[k] for k in ORDER]


def consensus(verdicts: List[GuruVerdict]) -> Tuple[int, str, Optional[float], str]:
    fit = sum(1 for v in verdicts if v.verdict == "적합")
    bucket = "hi" if fit >= C.CONSENSUS_HI else ("mid" if fit >= C.CONSENSUS_MID else "lo")
    scored = [v.score for v in verdicts if v.score is not None]
    mean_score = round(mean(scored), 3) if scored else None
    value_axis = [v for v in verdicts if v.guru in ("buffett", "munger", "graham", "piotroski", "greenblatt")]
    vfit = sum(1 for v in value_axis if v.verdict == "적합")
    vdata = sum(1 for v in value_axis if v.verdict != "데이터부족")
    d = next(v for v in verdicts if v.guru == "druckenmiller")
    if vdata == 0:
        val_txt = "가치·품질 축 데이터부족"
    elif vfit >= 3:
        val_txt = "가치·품질 적합"
    elif vfit >= 1:
        val_txt = "가치·품질 부분 적합"
    else:
        val_txt = "가치·품질 미달"
    sit_txt = {"적합": "상황 우호", "보류": "상황 중립", "부적합": "상황 비우호", "데이터부족": "상황 데이터부족"}.get(d.verdict, "상황 n/a")
    return fit, bucket, mean_score, f"{val_txt} · {sit_txt}"


def card_relation(verdicts: List[GuruVerdict], card: Optional[DecisionCard]) -> str:
    fit = sum(1 for v in verdicts if v.verdict == "적합")
    nodata = sum(1 for v in verdicts if v.verdict in ("데이터부족", "해당없음"))
    if card is None or not card.verdict_norm:
        return "결정카드 없음 — 비교 불가"
    if nodata >= 4:
        return "데이터부족 — 카드 판정과 비교 보류"
    if card.verdict_norm == "매수" and fit <= 1:
        return "상충: 카드 매수인데 구루 적합 ≤1 (퀄리티·가격 근거 약함)"
    if card.verdict_norm in ("관심", "관망") and fit >= 4:
        return "우호: 카드 관심/관망인데 구루 적합 ≥4 (눌림 시 가중 검토 근거)"
    if card.verdict_norm == "매수" and fit >= 3:
        return "보강: 카드 매수 + 구루 적합 ≥3"
    return "중립: 카드 판정과 뚜렷한 상충 없음"


def guru_falsifiers(verdicts: List[GuruVerdict]) -> List[str]:
    out = []
    for v in verdicts:
        if v.verdict != "적합":
            continue
        if v.guru == "buffett":
            out.append("버핏: 다음 보고서에서 지배주주 ROE(TTM) < 8% 또는 FCF ≤ 0 전환 시 철회")
        elif v.guru == "munger":
            out.append("멍거: 분기 영업적자 발생 또는 감사의견·내부회계 비적정 시 철회")
        elif v.guru == "graham":
            out.append("그레이엄: 유동비율 < 1.5 또는 PER×PBR > 22.5 로 이탈 시 철회")
        elif v.guru == "piotroski":
            out.append("피오트로스키: 다음 보고서 F-Score < 4 시 철회")
        elif v.guru == "greenblatt":
            out.append("그린블라트: 영업이익(TTM) 적자 전환 또는 EY·ROC 유니버스 하위 50% 이탈 시 철회")
        elif v.guru == "druckenmiller":
            out.append("드러켄밀러: KOSPI MA200 하향 이탈 또는 외인·기관 20일 합산 순매도 전환 시 상황점수 하향")
    return out
