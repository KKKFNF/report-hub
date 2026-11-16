"""
투자구루 판단의견(hub:guru) — 단일 진실 공급원(설정값).

이 파일의 숫자·가중치·임계값이 곧 '구현 사양'이다. guru.html(구현 설명 페이지)은
docs_export.py 가 이 파일을 읽어 표로 만들기 때문에 문서와 코드가 어긋날 수 없다.
값을 바꾸면 RULES_VERSION 을 올려라(블록 스냅샷 줄에 기록되어 사후 비교가 가능해진다).
"""
from __future__ import annotations

RULES_VERSION = "1.0.0"      # 룰 레이어 버전 (가중치·임계값 변경 시 올림)
PROMPT_VERSION = "1.0.0"     # LLM 정성 필터 프롬프트 버전
BLOCK_VERSION = "v1"         # 마커에 기록되는 블록 포맷 버전

# ── 판정 임계값(점수 0~1) ─────────────────────────────────────────────
VERDICT_FIT = 0.65    # score ≥ 0.65 → 적합
VERDICT_HOLD = 0.45   # 0.45 ≤ score < 0.65 → 보류, 그 미만 → 부적합
MIN_WEIGHT_COVERAGE = 0.50  # 계산 가능한 지표의 가중치 합이 이 값 미만이면 '데이터부족'

# 합의(consensus) 버킷: 6구루 중 '적합' 수
CONSENSUS_HI = 4   # ≥4 → hi
CONSENSUS_MID = 2  # 2~3 → mid, 0~1 → lo

# ── 스케일 함수 정의: s(x; lo, hi) = clip((x - lo)/(hi - lo), 0, 1) ─────────
# lo > hi 이면 '낮을수록 좋음'으로 자동 반전(예: PBR 3.0→0, 0.8→1)

# ── 1) 버핏: 품질 × 가격, 보수적 재무 ────────────────────────────────
BUFFETT = {
    "weights": {                 # 합 = 1.00
        "roe_avg":       0.25,   # 지배주주 ROE 평균(FY-3·FY-2·FY-1·TTM)
        "roe_min":       0.15,   # 같은 기간 ROE 최저값(일관성)
        "fcf_yield":     0.20,   # (영업CF − CAPEX, TTM) / 시총
        "opm_stability": 0.15,   # 1 − 영업이익률 변동계수
        "interest_cov":  0.10,   # 영업이익 / 금융비용(TTM)
        "valuation":     0.15,   # 0.5·s(1/PER) + 0.5·s(PBR)
    },
    "scales": {
        "roe_avg":      (0.08, 0.20),
        "roe_min":      (0.05, 0.15),
        "fcf_yield":    (0.00, 0.08),
        "interest_cov": (3.0, 15.0),
        "per_inv":      (1/25, 1/8),    # PER 25배→0, 8배→1
        "pbr":          (3.0, 0.8),     # PBR 3.0→0, 0.8→1 (반전)
    },
    "bonus": {
        "quality_combo":   (0.05, "ROE_avg ≥ 15% 이고 순차입금/자본 ≤ 0.3"),
        "shareholder_yld": (0.05, "배당+자사주소각 수익률 ≥ 3%"),
    },
    "penalty": {
        "net_debt_hi":   (-0.15, "순차입금/자본 > 1.0"),
        "cov_lo":        (-0.10, "이자보상배율 < 3"),
        "fcf_neg":       (-0.10, "TTM FCF ≤ 0"),
        "dilution_5":    (-0.10, "잠재희석(CB·BW·RCPS) ≥ 5%"),
        "dilution_15":   (-0.10, "잠재희석 ≥ 15% (추가)"),
        "rights_issue":  (-0.05, "최근 24개월 유상증자"),
    },
    "hard_fail": [
        "감사의견 비적정(한정·부적정·의견거절) 또는 계속기업 불확실성",
        "이자보상배율 < 1.5 (TTM)",
        "순차입금/자본 > 2.0",
    ],
}

# ── 2) 멍거: 예측가능성·자본수익 지속성·단순성·거버넌스 ──────────────
MUNGER = {
    "weights": {
        "predictability": 0.30,  # 1 − 영업이익 변동계수(FY-3~TTM, 4기)
        "roic_persist":   0.25,  # ROIC ≥ 10% 인 기간 비율
        "gross_margin":   0.15,  # 매출총이익률 수준
        "related_party":  0.15,  # 1 − 특수관계자 매출비중/30%
        "governance":     0.15,  # 감사의견 적정(0.6) + 내부회계 적정(0.4)
    },
    "scales": {
        "gross_margin": (0.20, 0.50),
        "related_party_cap": 0.30,
        "roic_threshold": 0.10,
        "tax_rate": 0.22,        # ROIC = 영업이익×(1−세율) / (순운전자본 + 순유형자산)
    },
    "penalty": {
        "loss_period":  (-0.10, "영업적자 기간 1회당(최대 −0.20)"),
        "dilution_5":   (-0.10, "잠재희석 ≥ 5%"),
        "holdco":       (-0.05, "지주회사(이중할인·현금흐름 간접) — 플래그"),
    },
    "hard_fail": [
        "감사의견 비적정 또는 계속기업 불확실성",
        "특수관계자 매출비중 > 50%",
    ],
}

# ── 3) 그레이엄: 방어적 투자자 7개 검사(한국형) ────────────────────────
GRAHAM = {
    "tests": {  # 이름: (설명, 통과 1.0 / 부분 0.5 기준)
        "current_ratio":  "유동비율 ≥ 2.0 (1.5~2.0 은 0.5점)",
        "lt_debt_nca":    "장기차입금 ≤ 순유동자산",
        "earnings_pos":   "FY-3·FY-2·FY-1·TTM 모두 지배주주순이익 > 0",
        "dividend_rec":   "최근 3개 회계연도 배당 또는 자사주소각 실행",
        "eps_growth":     "3년 누적 EPS 성장 ≥ +10% (0~10% 는 0.5점)",
        "per_cap":        "TTM PER ≤ 15 (15~20 은 0.5점)",
        "per_x_pbr":      "PER × PBR ≤ 22.5",
    },
    "netnet_bonus": (0.20, "시총 ≤ 0.67 × NCAV(유동자산 − 총부채) 이면 +0.20"),
    "score": "통과 점수 합 / 7 (+ 넷넷 보너스, 상한 1.0)",
    "verdict": "≥0.70 적합 · ≥0.45 보류 · 그 미만 부적합",
}

# ── 4) 피오트로스키 F-Score (TTM vs 직전 TTM, 없으면 FY-1 vs FY-2) ──────
PIOTROSKI = {
    "signals": [
        ("roa_pos",       "ROA > 0 (지배주주순이익/총자산)"),
        ("cfo_pos",       "영업CF > 0"),
        ("d_roa",         "ΔROA > 0"),
        ("accrual",       "영업CF > 당기순이익(발생액 음수)"),
        ("d_leverage",    "Δ(장기차입/총자산) < 0"),
        ("d_liquidity",   "Δ유동비율 > 0"),
        ("no_issue",      "신주 발행 없음(유상증자 현금유입 0)"),
        ("d_gm",          "Δ매출총이익률 > 0"),
        ("d_turnover",    "Δ자산회전율 > 0"),
    ],
    "verdict": "F ≥ 7 적합 · 4~6 보류 · ≤3 부적합",
}

# ── 5) 그린블라트 마법공식 ──────────────────────────────────────────────
GREENBLATT = {
    "ey":   "이익수익률 = 영업이익(TTM) / EV,  EV = 시총 + 총차입금 − 현금성자산",
    "roc":  "자본수익률 = 영업이익(TTM) / (순운전자본 + 순유형자산)",
    "eligibility": "영업이익 > 0, EV > 0, 투하자본 > 0, 금융·지주 제외",
    "universe_rank": "유니버스 통계 파일이 있으면 Score = 1 − (rank_EY + rank_ROC − 2)/(2N − 2)",
    "fallback_scales": {"ey": (0.0, 0.15), "roc": (0.0, 0.40)},   # 유니버스 없을 때: 0.5·s(EY)+0.5·s(ROC)
    "safety_penalty": {"cov_lo": (-0.03, "이자보상배율 < 3"), "de_hi": (-0.03, "총차입금/자본 > 1.0")},
}

# ── 6) 드러켄밀러: 종목 스크린이 아닌 '상황 점수' ────────────────────────
DRUCKENMILLER = {
    "weights": {
        "regime":    0.25,  # 시장 레짐(KOSPI MA200 위·VKOSPI<25·원화 20일 강세·외인 시장 20일 순매수 → 각 0.25)
        "trend_rs":  0.20,  # 60일 수익률(상대강도 대용) + MA20·MA60 상회
        "flows":     0.15,  # 외인·기관 20일 순매수(ADV20×20 대비) − 공매도 비중 추세
        "asymmetry": 0.20,  # 결정카드 1차 손익비 R: s(R; 1→0, 3→1)
        "change":    0.20,  # 영업이익 TTM YoY 성장 s(0→0, +50%→1) (0.6) + 최근 분기 QoQ 가속 (0.4)
    },
    "scales": {
        "ret60":     (-0.10, 0.30),
        "flow_frac": (-0.05, 0.05),   # (외인20+기관20)/(ADV20×20)
        "rr":        (1.0, 3.0),
        "op_yoy":    (0.0, 0.50),
    },
    "rules": [
        "레짐 점수 < 0.25 (약세 레짐)이면 판정 상한 '보류' — 유동성 역풍에는 베팅하지 않는다",
        "R ≥ 3 이고 점수 ≥ 0.70 이면 '집중 베팅 후보' 태그 — 단 1회 손실한도(결정카드 사이징)는 그대로",
        "공매도 비중 20일 평균 상회 연속 ≥ 5일이면 flows 에서 −0.25",
    ],
}

# ── LLM 정성 필터 ────────────────────────────────────────────────────────
LLM = {
    "personas": ["buffett", "munger", "druckenmiller"],   # 그레이엄·피오트로스키·그린블라트는 룰만
    "temperature": 0.0,
    "default_model": "claude-sonnet-5-5",
    "max_tokens": 700,
    "anonymize": [
        "종목명·종목코드 → A사 (리포트 내 다른 종목은 B사·C사…)",
        "절대 연도 → t-0/t-1/t-2 (리포트 발행연도 기준), 분기표기 1Q26 → 1Q(t-0)",
        "손익계산서 항목은 매출=100 기준 지수, 재무상태표 항목은 총자산=100 기준 지수로 변환",
        "절대 금액(억원)·시총·주가는 전달하지 않음(기업 식별 방지)",
    ],
    "schema_buffett": ["moat", "moat_evidence", "capital_allocation", "accounting_quality_flags",
                       "management_red_flags", "verdict", "confidence", "one_line"],
    "schema_druck":   ["change_thesis", "what_must_be_true", "asymmetry", "verdict", "confidence", "one_line"],
    "cache_dir": "~/.guru/cache/llm",
}

# ── 검증 게이트(의견 → 판정 입력 승격 조건) ─────────────────────────────
GATE = {
    "min_evaluated": 60,            # ledger 에서 D+20 평가 완료 건수
    "hi_vs_lo_min_edge_pp": 3.0,    # 합의 hi 그룹 − lo 그룹 D+20 코스피 대비 초과(%p)
    "bootstrap_p_max": 0.10,
    "policy": "v1 은 의견 전용. 결정카드 판정·진입·손절·목표를 절대 바꾸지 않는다.",
}

# 블록 마커
MARK_BEGIN = "<!-- hub:guru:begin:{code} {ver} -->"
MARK_END = "<!-- hub:guru:end:{code} -->"
DATA_MARK = "<!-- hub:guru:data {json} -->"
