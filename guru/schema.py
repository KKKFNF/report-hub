"""데이터 모델. 모든 금액은 억원, 비율은 소수(0.12 = 12%), 주가는 원."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class Period:
    """한 회계기간(연간 FY 또는 TTM)의 연결 지배주주 기준 수치. 값이 없으면 None."""
    label: str                                   # 'FY2023', 'FY2024', 'FY2025', 'TTM(2Q26)'
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    op: Optional[float] = None                   # 영업이익(K-IFRS 1001 영업이익)
    ni_parent: Optional[float] = None            # 지배기업소유주 귀속 순이익
    ni_total: Optional[float] = None
    cfo: Optional[float] = None
    capex: Optional[float] = None                # 유형자산 취득(양수)
    da: Optional[float] = None                   # 감가상각비+무형자산상각비
    interest_exp: Optional[float] = None         # 금융비용(이자비용)
    total_assets: Optional[float] = None
    total_liab: Optional[float] = None
    equity_parent: Optional[float] = None
    current_assets: Optional[float] = None
    current_liab: Optional[float] = None
    cash: Optional[float] = None
    st_debt: Optional[float] = None              # 단기차입금+유동성장기부채
    lt_debt: Optional[float] = None              # 장기차입금+사채
    net_ppe: Optional[float] = None
    inventories: Optional[float] = None
    dividends_paid: Optional[float] = None       # 배당금 지급(양수)
    buyback: Optional[float] = None              # 자기주식 취득(양수), 소각 포함
    share_issue_proceeds: Optional[float] = None # 유상증자 현금유입(양수)
    shares_out: Optional[float] = None           # 발행주식수(주)
    source: str = ""                             # DART 접수번호 등

    @property
    def debt(self) -> Optional[float]:
        if self.st_debt is None and self.lt_debt is None:
            return None
        return (self.st_debt or 0.0) + (self.lt_debt or 0.0)


@dataclass
class Flags:
    audit_opinion: Optional[str] = None          # '적정' | '한정' | '부적정' | '의견거절'
    going_concern: Optional[bool] = None
    icfr_opinion: Optional[str] = None           # 내부회계관리제도 의견
    related_party_sales_ratio: Optional[float] = None
    dilution_potential: Optional[float] = None   # 잠재주식수/발행주식수 (CB·BW·RCPS)
    rights_issue_24m: Optional[bool] = None
    holdco: Optional[bool] = None
    sector_group: str = "일반"                   # '일반' | '금융' | '지주'
    notes: List[str] = field(default_factory=list)


@dataclass
class Fundamentals:
    code: str
    name: str = ""
    periods: List[Period] = field(default_factory=list)   # 오래된 순 → 마지막이 TTM(없으면 FY-1)
    ttm_prev: Optional[Period] = None                     # 1년 전 TTM(피오트로스키 YoY 비교용)
    flags: Flags = field(default_factory=Flags)
    fetched_at: str = ""
    sources: List[str] = field(default_factory=list)

    def ttm(self) -> Optional[Period]:
        return self.periods[-1] if self.periods else None

    def prev(self) -> Optional[Period]:
        """TTM 과 비교할 1년 전 기간: ttm_prev 가 있으면 그것, 없으면 직전 FY."""
        if self.ttm_prev is not None:
            return self.ttm_prev
        return self.periods[-2] if len(self.periods) >= 2 else None

    def fiscal_years(self) -> List[Period]:
        return [p for p in self.periods if p.label.startswith("FY")]


@dataclass
class Market:
    """허브 enrich 블록(KIS 실측)에서 파싱한 시장 데이터."""
    code: str
    name: str = ""
    asof: str = ""
    price: Optional[float] = None
    mcap: Optional[float] = None       # 억원
    per: Optional[float] = None
    pbr: Optional[float] = None
    eps: Optional[float] = None
    bps: Optional[float] = None
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ret5: Optional[float] = None       # 소수
    ret20: Optional[float] = None
    ret60: Optional[float] = None
    high52: Optional[float] = None
    low52: Optional[float] = None
    adv20: Optional[float] = None      # 억원
    frgn5: Optional[float] = None      # 억원
    frgn20: Optional[float] = None
    orgn5: Optional[float] = None
    orgn20: Optional[float] = None
    indiv20: Optional[float] = None
    short_today: Optional[float] = None   # 소수
    short5: Optional[float] = None
    short20: Optional[float] = None
    short_above_days: Optional[int] = None
    atr14: Optional[float] = None
    futures: Optional[bool] = None
    raw_found: List[str] = field(default_factory=list)


@dataclass
class DecisionCard:
    code: str = ""
    name: str = ""
    verdict: str = ""        # 판정 원문
    verdict_norm: str = ""   # 매수 | 관심 | 관망 | 기타
    entry: Optional[float] = None
    stop: Optional[float] = None
    target1: Optional[float] = None
    target2: Optional[float] = None
    rr_text: str = ""
    rr1: Optional[float] = None
    horizon: str = ""
    catalyst: str = ""
    falsifier: str = ""
    raw: str = ""


@dataclass
class Regime:
    """시장 레짐(일별 1회 Mac mini 잡이 생성). 없으면 중립 0.5."""
    asof: str = ""
    kospi_above_ma200: Optional[bool] = None
    kospi_ret60: Optional[float] = None
    vkospi: Optional[float] = None
    usdkrw_ret20: Optional[float] = None       # +면 원화 약세
    foreign_net20_market: Optional[float] = None  # 억원, 전체 시장 외인 20일 순매수
    source: str = ""


@dataclass
class GuruVerdict:
    guru: str                       # 'buffett' …
    label: str                      # '버핏'
    score: Optional[float]          # 0~1, None = 데이터부족
    verdict: str                    # 적합 | 보류 | 부적합 | 데이터부족
    components: Dict[str, float] = field(default_factory=dict)   # 지표별 0~1
    values: Dict[str, Optional[float]] = field(default_factory=dict)  # 원값
    reasons: List[str] = field(default_factory=list)   # 사람이 읽는 근거(수치 포함)
    adjustments: List[str] = field(default_factory=list)  # 보너스/페널티/하드페일
    missing: List[str] = field(default_factory=list)
    coverage: float = 0.0
    tags: List[str] = field(default_factory=list)
    llm: Optional[dict] = None      # 정성 필터 결과(JSON)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GuruBlockData:
    code: str
    name: str
    report: str                     # md 파일명(stem)
    generated_at: str
    rules_version: str
    prompt_version: str
    data_snapshot: Dict[str, str]
    verdicts: List[GuruVerdict]
    consensus_fit: int
    consensus_bucket: str           # hi | mid | lo
    mean_score: Optional[float]
    summary: str
    card_relation: str
    falsifiers: List[str]

    def compact(self) -> dict:
        """index 후처리기가 쓰는 소형 JSON(HTML 주석에 내장)."""
        return {
            "code": self.code,
            "name": self.name,
            "report": self.report,
            "gen": self.generated_at,
            "rv": self.rules_version,
            "fit": self.consensus_fit,
            "bucket": self.consensus_bucket,
            "mean": None if self.mean_score is None else round(self.mean_score, 3),
            "v": {v.guru: v.verdict for v in self.verdicts},
            "s": {v.guru: (None if v.score is None else round(v.score, 2)) for v in self.verdicts},
            "rel": self.card_relation,
        }
