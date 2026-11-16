"""
OpenDART 어댑터 — 연결(CFS) 지배주주 기준 Fundamentals 생성.

사용 API(모두 공식 OpenDART, 키 필요: 환경변수 DART_API_KEY)
  - corpCode.xml                 종목코드 → 고유번호(캐시 30일)
  - fnlttSinglAcntAll.json       단일회사 전체 재무제표 (BS/IS/CIS/CF)
  - accnutAdtorNmNdAdtOpinion    감사의견
  - cndlCaplScritsNrdmpBlce      전환사채 미상환잔액 / bdwtWithWtsNrdmpBlce 신주인수권부사채 / exbdNrdmpBlce 교환사채
  - stockTotqySttus              주식 총수 (발행주식수)

기간 구성
  FY-3, FY-2, FY-1  = 사업보고서(11011) 연간
  TTM               = FY-1 + 당해 최신 분(반)기 누적 − 전년 동기 누적   (IS/CF 항목)
                      BS 항목은 최신 분(반)기 말 잔액
  TTM-1Y            = FY-2 + 전년 동기 누적 − 전전년 동기 누적          (피오트로스키 YoY 비교)

모든 금액은 억원으로 변환(원/1e8). 계정은 account_id(IFRS 태그) 우선, 없으면 account_nm 정규식.
'-표준계정코드 미사용-' 계정이 많으므로 반드시 `guru fundamentals --show` 로 추출표를 눈으로 검산할 것.
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from .schema import Flags, Fundamentals, Period

BASE = "https://opendart.fss.or.kr/api/"
REPRT = {"11011": "사업보고서", "11012": "반기보고서", "11013": "1분기보고서", "11014": "3분기보고서"}
# 분기 코드 → (분기 말 월)
REPRT_MONTH = {"11013": 3, "11012": 6, "11014": 9}

# ── 계정 매칭 사전: (statement set, [account_id 후보], [account_nm 정규식]) ─────
_IS = ("IS", "CIS")
ACCOUNTS: Dict[str, Tuple[Tuple[str, ...], List[str], List[str]]] = {
    "revenue":       (_IS, ["ifrs-full_Revenue", "ifrs_Revenue"], [r"^매출액$", r"^수익\(매출액\)$", r"^매출$", r"^영업수익$", r"^매출및지분법손익$"]),
    "gross_profit":  (_IS, ["ifrs-full_GrossProfit", "ifrs_GrossProfit"], [r"^매출총이익$", r"^매출총이익\(손실\)$"]),
    "op":            (_IS, ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"], [r"^영업이익$", r"^영업이익\(손실\)$", r"^영업손실$", r"^영업손익$"]),
    "ni_total":      (_IS, ["ifrs-full_ProfitLoss", "ifrs_ProfitLoss"], [r"^(당기|분기|반기)순이익$", r"^(당기|분기|반기)순이익\(손실\)$", r"^(당기|분기|반기)순손익$"]),
    "ni_parent":     (_IS, ["ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs_ProfitLossAttributableToOwnersOfParent"],
                      [r"지배기업.{0,6}소유주.{0,10}(순이익|순손익|지분)", r"지배기업주주지분", r"지배주주.{0,4}순이익", r"지배기업의\s*소유주"]),
    "cfo":           (("CF",), ["ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"], [r"^영업활동.{0,6}현금흐름$", r"^영업활동으로\s*인한\s*현금흐름$"]),
    "capex":         (("CF",), ["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"], [r"^유형자산의?\s*취득$", r"^유형자산\s*취득$"]),
    "da_dep":        (("CF",), ["ifrs-full_DepreciationExpense", "dart_DepreciationExpense"], [r"^감가상각비$"]),
    "da_amort":      (("CF",), ["ifrs-full_AmortisationExpense", "dart_AmortisationExpense"], [r"^무형자산상각비$", r"^무형자산\s*상각비$"]),
    "interest_exp":  (_IS, ["ifrs-full_InterestExpense"], [r"^이자비용$"]),
    "finance_costs": (_IS, ["ifrs-full_FinanceCosts"], [r"^금융비용$", r"^금융원가$"]),
    "total_assets":  (("BS",), ["ifrs-full_Assets", "ifrs_Assets"], [r"^자산총계$"]),
    "total_liab":    (("BS",), ["ifrs-full_Liabilities", "ifrs_Liabilities"], [r"^부채총계$"]),
    "equity_parent": (("BS",), ["ifrs-full_EquityAttributableToOwnersOfParent", "ifrs_EquityAttributableToOwnersOfParent"], [r"지배기업.{0,6}소유주.{0,14}(지분|자본)", r"지배기업주주지분", r"지배주주지분", r"지배기업소유지분"]),
    "current_assets":(("BS",), ["ifrs-full_CurrentAssets", "ifrs_CurrentAssets"], [r"^유동자산$"]),
    "current_liab":  (("BS",), ["ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"], [r"^유동부채$"]),
    "cash":          (("BS",), ["ifrs-full_CashAndCashEquivalents", "ifrs_CashAndCashEquivalents"], [r"^현금및현금성자산$", r"^현금\s*및\s*현금성자산$"]),
    "st_borrow":     (("BS",), ["ifrs-full_ShorttermBorrowings", "ifrs_ShorttermBorrowings"], [r"^단기차입금$"]),
    "cur_lt_debt":   (("BS",), ["ifrs-full_CurrentPortionOfLongtermBorrowings", "dart_CurrentPortionOfLongTermBorrowings"], [r"^유동성장기(부채|차입금)$", r"^유동성\s*장기(부채|차입금)$"]),
    "cur_bonds":     (("BS",), ["dart_CurrentPortionOfBonds", "dart_ShortTermBondsIssued"], [r"^유동성사채$", r"^유동성\s*사채$"]),
    "lt_borrow":     (("BS",), ["ifrs-full_LongtermBorrowings", "ifrs_LongtermBorrowings"], [r"^장기차입금$"]),
    "bonds":         (("BS",), ["dart_BondsIssued", "ifrs-full_BondsIssued"], [r"^사채$", r"^비유동사채$"]),
    "net_ppe":       (("BS",), ["ifrs-full_PropertyPlantAndEquipment", "ifrs_PropertyPlantAndEquipment"], [r"^유형자산$"]),
    "inventories":   (("BS",), ["ifrs-full_Inventories", "ifrs_Inventories"], [r"^재고자산$"]),
    "dividends_paid":(("CF",), ["ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "ifrs_DividendsPaidClassifiedAsFinancingActivities"], [r"^배당금의?\s*지급$", r"^배당금지급$", r"^현금배당금의\s*지급$"]),
    "buyback":       (("CF",), ["ifrs-full_PaymentsToAcquireOrRedeemEntitysShares"], [r"^자기주식의?\s*취득$", r"^자기주식\s*취득$"]),
    "share_issue":   (("CF",), ["ifrs-full_ProceedsFromIssuingShares"], [r"^유상증자$", r"^주식의\s*발행$", r"^신주발행$"]),
}
ABS_FIELDS = {"capex", "dividends_paid", "buyback", "share_issue", "da_dep", "da_amort"}


class DartError(RuntimeError):
    pass


def _eok(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    v = str(v).strip().replace(",", "")
    if v in ("", "-", "−"):
        return None
    try:
        return float(v) / 1e8
    except ValueError:
        return None


class DartClient:
    def __init__(self, api_key: Optional[str] = None, cache_dir: str = "~/.guru/cache/dart",
                 offline: bool = False, sleep: float = 0.15):
        self.key = api_key or os.environ.get("DART_API_KEY", "")
        self.cache = os.path.expanduser(cache_dir)
        os.makedirs(self.cache, exist_ok=True)
        self.offline = offline
        self.sleep = sleep
        self.calls = 0

    # ── 저수준 ──
    def _cache_path(self, name: str, params: dict) -> str:
        key = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "crtfc_key")
        safe = re.sub(r"[^A-Za-z0-9_=&.-]", "_", key)
        return os.path.join(self.cache, f"{name}__{safe}.json")

    def get_json(self, name: str, params: dict, ttl_days: int = 3650) -> dict:
        path = self._cache_path(name, params)
        if os.path.exists(path):
            age = (time.time() - os.path.getmtime(path)) / 86400
            if age <= ttl_days or self.offline:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
        if self.offline:
            raise DartError(f"offline: 캐시 없음 {name} {params}")
        if not self.key:
            raise DartError("DART_API_KEY 가 없습니다 (환경변수 또는 --dart-key).")
        q = dict(params)
        q["crtfc_key"] = self.key
        url = BASE + name + ".json?" + urllib.parse.urlencode(q)
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=25) as r:
                    data = json.loads(r.read().decode("utf-8"))
                self.calls += 1
                time.sleep(self.sleep)
                break
            except Exception as e:  # noqa
                last = e
                time.sleep(1.5 * (attempt + 1))
        else:
            raise DartError(f"DART 호출 실패 {name}: {last}")
        if data.get("status") not in ("000", "013"):   # 013 = 조회 데이터 없음
            raise DartError(f"DART 오류 {name} status={data.get('status')} {data.get('message')}")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return data

    # ── 고유번호 ──
    def corp_code(self, stock_code: str) -> Tuple[str, str]:
        path = os.path.join(self.cache, "corpCode.json")
        table: Dict[str, Tuple[str, str]] = {}
        fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) / 86400 <= 30
        if os.path.exists(path) and (fresh or self.offline):
            with open(path, encoding="utf-8") as fh:
                table = {k: tuple(v) for k, v in json.load(fh).items()}
        else:
            if not self.key:
                raise DartError("DART_API_KEY 가 없습니다.")
            url = BASE + "corpCode.xml?" + urllib.parse.urlencode({"crtfc_key": self.key})
            with urllib.request.urlopen(url, timeout=60) as r:
                blob = r.read()
            self.calls += 1
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                xml = z.read(z.namelist()[0])
            root = ET.fromstring(xml)
            for el in root.iter("list"):
                sc = (el.findtext("stock_code") or "").strip()
                if sc:
                    table[sc] = ((el.findtext("corp_code") or "").strip(), (el.findtext("corp_name") or "").strip())
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(table, fh, ensure_ascii=False)
        if stock_code not in table:
            raise DartError(f"corpCode 에 종목코드 {stock_code} 없음")
        return table[stock_code]

    # ── 재무제표 ──
    def statements(self, corp: str, year: int, reprt: str) -> List[dict]:
        data = self.get_json("fnlttSinglAcntAll", {"corp_code": corp, "bsns_year": str(year), "reprt_code": reprt, "fs_div": "CFS"})
        rows = data.get("list") or []
        if not rows:  # 연결 없으면 별도(OFS)로 폴백 — 플래그 기록
            data = self.get_json("fnlttSinglAcntAll", {"corp_code": corp, "bsns_year": str(year), "reprt_code": reprt, "fs_div": "OFS"})
            rows = data.get("list") or []
            for r in rows:
                r["_ofs"] = True
        return rows


def _match(rows: List[dict], field: str, col: str) -> Tuple[Optional[float], Optional[str]]:
    """field 의 금액(억원)과 매칭된 계정명을 돌려준다. col = thstrm_amount | thstrm_add_amount | frmtrm_add_amount …"""
    sjs, ids, names = ACCOUNTS[field]
    cands = [r for r in rows if r.get("sj_div") in sjs]
    if not cands:
        return None, None
    # IS 와 CIS 가 모두 있으면 IS 우선
    if "IS" in sjs and any(r.get("sj_div") == "IS" for r in cands):
        cands = [r for r in cands if r.get("sj_div") == "IS"]
    for aid in ids:
        for r in cands:
            if r.get("account_id") == aid:
                v = _eok(r.get(col))
                if v is not None:
                    return (abs(v) if field in ABS_FIELDS else v), r.get("account_nm")
    for pat in names:
        rx = re.compile(pat)
        for r in cands:
            nm = re.sub(r"\s+", "", r.get("account_nm", "")) if "\\s" not in pat else r.get("account_nm", "")
            if rx.search(nm):
                v = _eok(r.get(col))
                if v is not None:
                    return (abs(v) if field in ABS_FIELDS else v), r.get("account_nm")
    return None, None


def _period_from_rows(label: str, rows: List[dict], flow_col: str, bs_col: str = "thstrm_amount",
                      rcept: str = "") -> Tuple[Period, Dict[str, str]]:
    p = Period(label=label, source=rcept)
    matched: Dict[str, str] = {}

    def take(field, col):
        v, nm = _match(rows, field, col)
        if nm:
            matched[field] = nm
        return v

    p.revenue = take("revenue", flow_col)
    p.gross_profit = take("gross_profit", flow_col)
    p.op = take("op", flow_col)
    p.ni_total = take("ni_total", flow_col)
    p.ni_parent = take("ni_parent", flow_col)
    if p.ni_parent is None and p.ni_total is not None:
        p.ni_parent = p.ni_total
        matched["ni_parent"] = "(지배주주 미분리 → 당기순이익 사용)"
    p.cfo = take("cfo", flow_col)
    p.capex = take("capex", flow_col)
    dep, amo = take("da_dep", flow_col), take("da_amort", flow_col)
    p.da = None if dep is None and amo is None else (dep or 0.0) + (amo or 0.0)
    ie = take("interest_exp", flow_col)
    if ie is None:
        ie = take("finance_costs", flow_col)
        if ie is not None:
            matched["interest_exp"] = matched.get("finance_costs", "금융비용") + " (이자비용 미분리 → 금융비용 사용)"
    p.interest_exp = ie
    p.dividends_paid = take("dividends_paid", flow_col)
    p.buyback = take("buyback", flow_col)
    p.share_issue_proceeds = take("share_issue", flow_col)
    # BS
    p.total_assets = take("total_assets", bs_col)
    p.total_liab = take("total_liab", bs_col)
    p.equity_parent = take("equity_parent", bs_col)
    if p.equity_parent is None and p.total_assets is not None and p.total_liab is not None:
        p.equity_parent = p.total_assets - p.total_liab
        matched["equity_parent"] = "(지배주주지분 미분리 → 자본총계 사용)"
    p.current_assets = take("current_assets", bs_col)
    p.current_liab = take("current_liab", bs_col)
    p.cash = take("cash", bs_col)
    sb, cl, cb = take("st_borrow", bs_col), take("cur_lt_debt", bs_col), take("cur_bonds", bs_col)
    p.st_debt = None if all(x is None for x in (sb, cl, cb)) else (sb or 0.0) + (cl or 0.0) + (cb or 0.0)
    lb, bd = take("lt_borrow", bs_col), take("bonds", bs_col)
    p.lt_debt = None if all(x is None for x in (lb, bd)) else (lb or 0.0) + (bd or 0.0)
    p.net_ppe = take("net_ppe", bs_col)
    p.inventories = take("inventories", bs_col)
    return p, matched


FLOW_FIELDS = ["revenue", "gross_profit", "op", "ni_total", "ni_parent", "cfo", "capex", "da",
               "interest_exp", "dividends_paid", "buyback", "share_issue_proceeds"]
BS_FIELDS = ["total_assets", "total_liab", "equity_parent", "current_assets", "current_liab", "cash",
             "st_debt", "lt_debt", "net_ppe", "inventories"]


def _combine_ttm(label: str, fy: Period, ytd_cur: Period, ytd_prev: Period, bs_from: Period) -> Period:
    """TTM = FY + YTD(당해) − YTD(전년동기); BS 는 최신 분기말."""
    p = Period(label=label, source=f"{fy.source}+{ytd_cur.source}")
    for fld in FLOW_FIELDS:
        a, b, c = getattr(fy, fld), getattr(ytd_cur, fld), getattr(ytd_prev, fld)
        if a is None or b is None or c is None:
            setattr(p, fld, None)
        else:
            setattr(p, fld, a + b - c)
    for fld in BS_FIELDS:
        setattr(p, fld, getattr(bs_from, fld))
    p.shares_out = bs_from.shares_out
    return p


def _rcept(rows: List[dict]) -> str:
    for r in rows:
        if r.get("rcept_no"):
            return r["rcept_no"]
    return ""


def fetch_fundamentals(code: str, client: DartClient, asof: Optional[date] = None,
                       sector_group: Optional[str] = None, show: bool = False) -> Fundamentals:
    asof = asof or date.today()
    corp, corp_name = client.corp_code(code)
    f = Fundamentals(code=code, name=corp_name, fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    matched_all: Dict[str, Dict[str, str]] = {}

    # 연간 3개 (가장 최근 확정 사업보고서 연도 = asof.year-1, 단 3월 이전이면 아직 미제출일 수 있어 1년 더 내려감)
    last_fy = asof.year - 1
    annual: Dict[int, List[dict]] = {}
    for y in range(last_fy, last_fy - 4, -1):
        rows = client.statements(corp, y, "11011")
        if rows:
            annual[y] = rows
        if len(annual) == 3:
            break
    if not annual:
        raise DartError(f"{code}: 사업보고서 재무제표를 찾을 수 없음")
    years = sorted(annual)
    fy_periods: Dict[int, Period] = {}
    for y in years:
        p, m = _period_from_rows(f"FY{y}", annual[y], "thstrm_amount", "thstrm_amount", _rcept(annual[y]))
        if any(r.get("_ofs") for r in annual[y]):
            f.flags.notes.append(f"FY{y}: 연결 없음 → 별도 재무제표 사용")
        fy_periods[y] = p
        matched_all[f"FY{y}"] = m
        f.sources.append(f"FY{y} 사업보고서 {p.source}")
    f.periods = [fy_periods[y] for y in years]
    newest_fy = years[-1]

    # 당해 최신 분(반)기 → TTM
    cur_year = newest_fy + 1
    q_rows, q_code = None, None
    for rc in ("11014", "11012", "11013"):
        rows = client.statements(corp, cur_year, rc)
        if rows:
            q_rows, q_code = rows, rc
            break
    if q_rows:
        ytd_cur, m1 = _period_from_rows(f"YTD{cur_year}{q_code}", q_rows, "thstrm_add_amount", "thstrm_amount", _rcept(q_rows))
        # 1분기보고서는 thstrm_add_amount 가 비어있을 수 있음 → thstrm_amount 사용
        if ytd_cur.revenue is None and ytd_cur.op is None:
            ytd_cur, m1 = _period_from_rows(f"YTD{cur_year}{q_code}", q_rows, "thstrm_amount", "thstrm_amount", _rcept(q_rows))
        ytd_prev, _ = _period_from_rows("YTDprev", q_rows, "frmtrm_add_amount", "frmtrm_amount")
        if ytd_prev.revenue is None and ytd_prev.op is None:
            # 전기 누적이 없으면 전년 동일 보고서 조회
            prow = client.statements(corp, cur_year - 1, q_code)
            ytd_prev, _ = _period_from_rows("YTDprev", prow, "thstrm_add_amount" if q_code != "11013" else "thstrm_amount", "thstrm_amount", _rcept(prow))
        mon = REPRT_MONTH[q_code]
        ttm = _combine_ttm(f"TTM({mon//3}Q{str(cur_year)[2:]})", fy_periods[newest_fy], ytd_cur, ytd_prev, ytd_cur)
        ttm.source = f"{fy_periods[newest_fy].source} + {ytd_cur.source}"
        f.periods.append(ttm)
        matched_all[ttm.label] = m1
        f.sources.append(f"{REPRT[q_code]} {cur_year} {ytd_cur.source} (TTM 합성)")
        # TTM-1Y
        if newest_fy - 1 in fy_periods:
            prow = client.statements(corp, cur_year - 1, q_code)
            if prow:
                col_add = "thstrm_add_amount" if q_code != "11013" else "thstrm_amount"
                yp_cur, _ = _period_from_rows("YTDp", prow, col_add, "thstrm_amount", _rcept(prow))
                yp_prev, _ = _period_from_rows("YTDpp", prow, "frmtrm_add_amount" if q_code != "11013" else "frmtrm_amount", "frmtrm_amount")
                if yp_cur.op is not None and yp_prev.op is not None:
                    f.ttm_prev = _combine_ttm(f"TTM-1Y({mon//3}Q{str(cur_year-1)[2:]})", fy_periods[newest_fy - 1], yp_cur, yp_prev, yp_cur)
    else:
        f.flags.notes.append(f"{cur_year}년 분(반)기 보고서 없음 → TTM = FY{newest_fy}")

    # 발행주식수 (최신 보고서)
    try:
        yq = (cur_year, q_code) if q_rows else (newest_fy, "11011")
        st = client.get_json("stockTotqySttus", {"corp_code": corp, "bsns_year": str(yq[0]), "reprt_code": yq[1]})
        for r in st.get("list") or []:
            if "보통주" in (r.get("se") or "") or r.get("se") in ("합계", "보통주식"):
                v = str(r.get("istc_totqy", "")).replace(",", "")
                if v.isdigit():
                    f.periods[-1].shares_out = float(v)
                    break
    except DartError as e:
        f.flags.notes.append(f"주식총수 조회 실패: {e}")

    # 감사의견 (최신 사업보고서)
    try:
        ad = client.get_json("accnutAdtorNmNdAdtOpinion", {"corp_code": corp, "bsns_year": str(newest_fy), "reprt_code": "11011"})
        rows = ad.get("list") or []
        if rows:
            r = rows[0]
            op = (r.get("adt_opinion") or "").strip()
            f.flags.audit_opinion = "적정" if op.startswith("적정") else (op or None)
            txt = " ".join(str(r.get(k) or "") for k in ("adt_reprt_spcmnt_matter", "emphs_matter", "core_adt_matter"))
            f.flags.going_concern = ("계속기업" in txt and "불확실" in txt) or None
            f.sources.append(f"감사의견 FY{newest_fy}: {op}")
    except DartError as e:
        f.flags.notes.append(f"감사의견 조회 실패: {e}")

    # 잠재희석(CB·BW·EB 미상환 잔액의 전환가능주식수 / 발행주식수)
    try:
        yq = (cur_year, q_code) if q_rows else (newest_fy, "11011")
        pot = 0.0
        for api in ("cndlCaplScritsNrdmpBlce", "bdwtWithWtsNrdmpBlce", "exbdNrdmpBlce"):
            d = client.get_json(api, {"corp_code": corp, "bsns_year": str(yq[0]), "reprt_code": yq[1]})
            for r in d.get("list") or []:
                for k, v in r.items():
                    if ("stock_co" in k or "psbl" in k) and isinstance(v, str) and v.replace(",", "").isdigit():
                        pot += float(v.replace(",", ""))
                        break
        sh = f.periods[-1].shares_out
        if sh:
            f.flags.dilution_potential = pot / sh
            f.sources.append(f"잠재희석주식 {pot:,.0f}주 / 발행 {sh:,.0f}주")
    except DartError as e:
        f.flags.notes.append(f"CB·BW 조회 실패: {e}")

    # 유상증자 24개월: 최신 2개 기간의 유상증자 현금유입
    recent = [p for p in f.periods[-2:]]
    vals = [p.share_issue_proceeds for p in recent if p.share_issue_proceeds is not None]
    f.flags.rights_issue_24m = (any(v > 0 for v in vals)) if vals else None

    # 업종 그룹/지주 플래그
    nm = corp_name
    f.flags.holdco = bool(re.search(r"(지주|홀딩스|Holdings)", nm, re.I))
    if sector_group:
        f.flags.sector_group = sector_group
    elif re.search(r"(은행|증권|보험|화재|생명|금융|캐피탈|카드|저축은행|투자|자산운용)", nm):
        f.flags.sector_group = "금융"
    elif f.flags.holdco:
        f.flags.sector_group = "지주"

    if show:
        print(render_fundamentals_table(f, matched_all))
    return f


def render_fundamentals_table(f: Fundamentals, matched: Optional[Dict[str, Dict[str, str]]] = None) -> str:
    """검산용 표(억원). CPA 가 DART 원문과 대조하라고 만든 출력."""
    cols = f.periods + ([f.ttm_prev] if f.ttm_prev else [])
    lines = [f"# {f.name}({f.code}) 연결 지배주주 기준 (억원) · 조회 {f.fetched_at}"]
    hdr = "| 항목 | " + " | ".join(p.label for p in cols) + " |"
    lines += [hdr, "|" + "---|" * (len(cols) + 1)]
    for fld in FLOW_FIELDS + BS_FIELDS + ["shares_out"]:
        row = [fld]
        for p in cols:
            v = getattr(p, fld)
            row.append("" if v is None else (f"{v:,.0f}" if fld == "shares_out" else f"{v:,.1f}"))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("플래그: " + json.dumps(f.flags.__dict__, ensure_ascii=False))
    lines.append("출처: " + " / ".join(f.sources))
    if matched:
        lines.append("")
        lines.append("계정 매칭(검산용):")
        for lab, m in matched.items():
            lines.append(f"  [{lab}] " + ", ".join(f"{k}←{v}" for k, v in m.items()))
    return "\n".join(lines)
