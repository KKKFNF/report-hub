"""
guru.html(구현 설명 페이지) 생성기.
수식·가중치·임계값 표는 config.py 에서 직접 읽어 만들기 때문에 문서와 코드가 어긋나지 않는다.
예시 블록은 tests/fixtures/fixture_company.json(가상 기업)으로 실제 코드를 돌려 만든다.

python -m guru docs --out guru.html
"""
from __future__ import annotations

import html as H
import json
import os
from datetime import date

from . import config as C
from . import rules
from .hub_postprocess import md_block_to_html
from .render import render_block
from .schema import DecisionCard, GuruBlockData
from .serialize import fundamentals_from_dict, market_from_dict, regime_from_dict

HERE = os.path.dirname(__file__)


def _esc(x) -> str:
    return H.escape(str(x))


def _scale_txt(lo, hi) -> str:
    def f(v):
        if isinstance(v, float) and abs(v) < 1 and v != 0:
            return f"{v*100:.0f}%" if abs(v) >= 0.01 else f"{v:.3f}"
        return f"{v:g}"
    arrow = "낮을수록 좋음(반전)" if lo > hi else ""
    return f"{f(lo)} → 0점, {f(hi)} → 1점 {arrow}".strip()


def table(headers, rows) -> str:
    th = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


SCALE_ALIAS = {
    "valuation": ["per_inv", "pbr"], "trend_rs": ["ret60"], "flows": ["flow_frac"], "asymmetry": ["rr"], "change": ["op_yoy"],
}
SCALE_LABEL = {"per_inv": "1/PER: PER 25배 → 0점, 8배 → 1점", "pbr": "PBR 3.0 → 0점, 0.8 → 1점(반전)", "ret60": "60일 수익률 ",
               "flow_frac": "(외인20+기관20)/(ADV20×20) ", "rr": "손익비 R ", "op_yoy": "영업이익 YoY "}


def weights_table(cfg: dict, desc: dict) -> str:
    rows = []
    for k, w in cfg["weights"].items():
        scales = cfg.get("scales", {})
        if k in scales:
            sc_txt = _scale_txt(*scales[k])
        elif k in SCALE_ALIAS:
            bits = []
            for a in SCALE_ALIAS[k]:
                if a in scales:
                    lab = SCALE_LABEL.get(a, a + " ")
                    bits.append(lab if a in ("per_inv", "pbr") else lab + _scale_txt(*scales[a]))
            sc_txt = " · ".join(bits)
        else:
            sc_txt = "직접 0~1"
        rows.append([f"<code>{k}</code>", _esc(desc.get(k, "")), f"{w:.2f}", _esc(sc_txt)])
    return table(["구성요소", "정의", "가중치", "스케일 s(x)"], rows)


def adj_table(cfg: dict) -> str:
    rows = []
    for k, (d, why) in cfg.get("bonus", {}).items():
        rows.append(["보너스", _esc(why), f"{d:+.2f}"])
    for k, (d, why) in cfg.get("penalty", {}).items():
        rows.append(["페널티", _esc(why), f"{d:+.2f}"])
    for why in cfg.get("hard_fail", []):
        rows.append(["하드페일", _esc(why), "→ 부적합"])
    return table(["구분", "조건", "조정"], rows) if rows else ""


def example_block_html() -> str:
    with open(os.path.join(HERE, "tests", "fixtures", "fixture_company.json"), encoding="utf-8") as fh:
        FIX = json.load(fh)
    f = fundamentals_from_dict(FIX["fundamentals"])
    mk = market_from_dict(FIX["market"])
    card = DecisionCard(**FIX["card"])
    rg = regime_from_dict(FIX["regime"])
    vs = rules.run_all(f, mk, card, rg)
    llm = {
        "buffett": {"moat": "중", "moat_evidence": "매출총이익률 25→27% 완만 개선, 가격결정력 직접 증거 없음", "capital_allocation": "우수",
                    "accounting_quality_flags": [], "management_red_flags": [], "verdict": "보류", "confidence": 0.6, "one_line": "성장은 숫자로 확인, 해자는 미증명"},
        "munger": {"how_it_fails": ["전방 수요 둔화 시 고정비 레버리지 역작용", "재고 증가가 실수요가 아닐 가능성"], "predictability": "보통",
                   "incentive_alignment": "정렬", "too_hard_pile": False, "verdict": "보류", "confidence": 0.55, "one_line": "단순한 사업, 사이클 의존은 남음"},
        "druckenmiller": {"change_thesis": "영업이익 YoY +30%, 외인·기관 동반 순매수", "what_must_be_true": ["3Q 영업이익 증가 지속", "환율·외인 흐름 유지"],
                          "asymmetry": "높음", "liquidity_headwind": False, "verdict": "적합", "confidence": 0.65, "one_line": "변화 방향과 수급이 같은 쪽"},
    }
    for v in vs:
        if v.guru in llm:
            v.llm = llm[v.guru]
    fit, bucket, mean_score, summary = rules.consensus(vs)
    d = GuruBlockData(code="000000", name="가상A사", report="20261019-120000-가상A사-000000", generated_at="2026-10-19 12:00",
                      rules_version=C.RULES_VERSION, prompt_version=C.PROMPT_VERSION, data_snapshot={}, verdicts=vs,
                      consensus_fit=fit, consensus_bucket=bucket, mean_score=mean_score, summary=summary,
                      card_relation=rules.card_relation(vs, card), falsifiers=rules.guru_falsifiers(vs))
    md = render_block(d, card, ["DART 연결 FY2023·FY2024·FY2025·TTM(2Q26) · (픽스처)", "KIS enrich 2026-10-19 15:38", "레짐 2026-10-19",
                                "유니버스 통계 없음(절대 스케일)", f"룰 v{C.RULES_VERSION} · 프롬프트 v{C.PROMPT_VERSION} · anthropic/{C.LLM['default_model']} (예시 응답) · 생성 2026-10-19 12:00"])
    comp = {v.guru: v for v in vs}
    return md_block_to_html(md), comp, md


CSS = """
:root{--bg:#0f1115;--card:#191c22;--card2:#1e222b;--bd:#2a2f3a;--tx:#e7eaee;--mut:#9aa2ad;--acc:#5db0ff;--up:#7ee7a1;--dn:#ff7b7b;--wn:#ffd166}
*{box-sizing:border-box}
body{font:15.5px/1.75 -apple-system,'Apple SD Gothic Neo',system-ui,Segoe UI,sans-serif;max-width:980px;margin:0 auto;padding:20px 18px 70px;color:var(--tx);background:var(--bg)}
a{color:var(--acc)} h1{font-size:25px;letter-spacing:-.3px;margin:6px 0 8px} h2{font-size:19px;margin:34px 0 10px;padding-top:14px;border-top:1px solid var(--bd)} h3{font-size:16px;margin:20px 0 6px;color:#cdd3dc}
.top{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px} .top a{background:var(--card2);color:#cdd3dc;padding:7px 13px;border-radius:9px;text-decoration:none;font-size:13px;border:1px solid var(--bd)}
.hero{background:linear-gradient(160deg,#1c2230,#191c22);border:1px solid var(--bd);border-radius:16px;padding:22px 24px 18px;margin-bottom:18px}
.meta{color:var(--mut);font-size:13px} .pill{display:inline-block;background:var(--card);border:1px solid var(--bd);border-radius:9px;padding:3px 10px;font-size:12.5px;margin:4px 6px 0 0;color:#cdd3dc}
.pill.ok{color:var(--up);border-color:rgba(126,231,161,.35)} .pill.wn{color:var(--wn);border-color:rgba(255,209,102,.35)}
.toc{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:12px 18px;font-size:14px} .toc{display:flex;flex-wrap:wrap;gap:2px 14px} .toc a{text-decoration:none;line-height:2}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0 14px;background:var(--card)} th,td{border:1px solid var(--bd);padding:6px 9px;vertical-align:top;text-align:left} th{color:var(--mut);font-weight:600;background:var(--card2)}
code{background:#242a35;padding:1px 5px;border-radius:5px;font-size:12.5px} pre{background:#0b0d11;border:1px solid var(--bd);border-radius:12px;padding:12px 14px;overflow:auto;font-size:12.5px;line-height:1.55}
.note{background:var(--card);border-left:3px solid var(--acc);padding:8px 14px;border-radius:0 10px 10px 0;margin:10px 0;color:#cdd3dc;font-size:14px}
.warn{border-left-color:var(--wn)} .bad{border-left-color:var(--dn)}
.flow{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch;margin:12px 0} .box{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:10px 12px;min-width:150px;flex:1;font-size:13px} .box b{display:block;color:#fff;margin-bottom:3px} .arrow{align-self:center;color:var(--mut);font-size:20px}
.guru-block{border:1px solid var(--bd);border-radius:14px;padding:4px 16px 10px;margin:14px 0;background:#1a1d24} .guru-block table{font-size:13px} .guru-block td:nth-child(-n+3){white-space:nowrap}
ul{padding-left:22px} li{margin:3px 0} .small{font-size:13px;color:var(--mut)}
"""

DESC = {
    "buffett": {"roe_avg": "지배주주순이익 ÷ 지배주주지분, FY-3·FY-2·FY-1·TTM 평균", "roe_min": "같은 기간 ROE 최저값(일관성)",
                "fcf_yield": "(영업CF − 유형자산 취득, TTM) ÷ 시총", "opm_stability": "1 − 영업이익률 변동계수(기간 전체)",
                "interest_cov": "영업이익 ÷ 금융비용(이자비용 우선, TTM). 무차입이면 1점", "valuation": "0.5·s(1/PER) + 0.5·s(PBR), 후행 PER·PBR(KIS)"},
    "munger": {"predictability": "1 − 영업이익 변동계수(3기 이상)", "roic_persist": "세후 ROIC ≥ 10% 인 기간 비율 · ROIC = 영업이익×(1−22%) ÷ (순운전자본+순유형자산)",
               "gross_margin": "매출총이익률(TTM)", "related_party": "1 − 특수관계자 매출비중 ÷ 30% (주석 입력 없으면 미확인)",
               "governance": "감사의견 적정 0.6 + 내부회계 적정 0.4 (가용 항목 기준 정규화)"},
    "druckenmiller": {"regime": "KOSPI MA200 위 · VKOSPI<25 · 원화 20일 강세 · 외인 시장 20일 순매수 → 각 0/1 평균(파일 없으면 0.5)",
                      "trend_rs": "0.6·s(60일 수익률) + 0.4·(MA20·MA60 상회 비율)", "flows": "s((외인20+기관20) ÷ (ADV20×20)); 공매도 20일평균 상회 연속≥5일이면 −0.25",
                      "asymmetry": "결정카드 1차 손익비 R 의 s(R)", "change": "0.6·s(영업이익 TTM YoY) + 0.4·(TTM 영업이익 > 직전 FY 영업이익)"},
}


def build_html() -> str:
    ex_html, comp, ex_md = example_block_html()
    b = comp["buffett"]
    today = date.today().isoformat()
    buffett_check = (
        f"ROE 평균 {b.values['roe_avg']*100:.1f}% → s(8%,20%) = {b.components['roe_avg']:.2f} · "
        f"ROE 최저 {b.values['roe_min']*100:.1f}% → {b.components['roe_min']:.2f} · "
        f"FCF 수익률 {b.values['fcf_yield']*100:.1f}% → {b.components['fcf_yield']:.2f} · "
        f"OPM 안정성 {b.components['opm_stability']:.2f} · 이자보상 {b.values['interest_cov']:.1f}배 → {b.components['interest_cov']:.2f} · "
        f"밸류(PER {b.values['per']:.1f}, PBR {b.values['pbr']:.2f}) → {b.components['valuation']:.2f}"
    )
    wsum = " + ".join(f"{w:.2f}×{b.components[k]:.2f}" for k, w in C.BUFFETT['weights'].items())
    base = sum(w * b.components[k] for k, w in C.BUFFETT["weights"].items())

    parts = []
    parts.append(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>🧭 투자구루 판단의견 — 구현 설명</title><style>{CSS}</style></head><body>
<div class="top"><a href="./index.html">🐤 허브 홈</a><a href="./ledger.html">📒 신호 원장</a></div>
<div class="hero"><h1>🧭 투자구루 판단의견 — 어떻게 구현했나</h1>
<div class="meta">리포트 허브의 각 종목 리포트에 붙는 <b>🧭 투자구루 판단의견</b> 블록(hub:guru)의 산식·데이터·운영 규칙을 그대로 적은 문서입니다.
아래 표의 가중치·임계값은 <code>guru/config.py</code>에서 자동 생성되므로 코드와 문서가 어긋나지 않습니다. 문서 생성일 {today}.</div>
<div><span class="pill ok">룰 v{C.RULES_VERSION}</span><span class="pill ok">프롬프트 v{C.PROMPT_VERSION}</span><span class="pill">블록 {C.BLOCK_VERSION}</span><span class="pill wn">상태: 의견 전용 — 결정카드 판정 불변</span><span class="pill">6구루: 버핏·멍거·드러켄밀러·그레이엄·피오트로스키·그린블라트</span></div></div>
<div class="toc"><a href="#why">1 설계 원칙</a><a href="#where">2 블록 위치·파이프라인</a><a href="#data">3 데이터 소스</a><a href="#rules">4 룰 레이어 수식</a><a href="#llm">5 LLM 정성 필터</a><a href="#consensus">6 합의·관계·반증</a><a href="#hub">7 허브 표시</a><a href="#gate">8 검증 게이트</a><a href="#limits">9 한계·주의</a><a href="#run">10 실행 방법</a><a href="#example">11 예시 출력</a><a href="#check">12 검산 예시</a><a href="#files">13 파일·버전</a></div>
""")

    parts.append(f"""<h2 id="why">1. 설계 원칙 — 왜 이렇게 만들었나</h2>
<p>구루 원칙을 에이전트로 만든 공개 사례와 백테스트 검증 논문을 먼저 검토한 결과는 다음 한 줄로 요약됩니다. <b>정량 룰이 수익의 몸통이고, LLM 페르소나는 알파 원천이 아니라 정성 필터·설명 레이어로 쓸 때만 방어 가능하다.</b></p>
<ul>
<li><b>룰은 결정론적</b>: 같은 입력이면 같은 출력. 가중치·임계값은 config.py 한 곳에만 있고, 바꾸면 버전을 올려 블록 스냅샷 줄에 남깁니다(GuruAgents 가 쓴 '결정론적 파이프라인' 방식).</li>
<li><b>LLM 은 점수에 섞지 않음</b>: 버핏·멍거·드러켄밀러 3인에만 정성 필터를 붙이고 결과는 별도 열에 표기합니다. 20년·100+종목(FINSABER)·지식컷오프 이후 구간(Profit Mirage)에서 LLM 직접 판단의 우위가 사라진다는 결과를 반영한 것입니다.</li>
<li><b>누수 방지</b>: LLM 입력은 종목명·코드·절대연도를 지우고 매출=100·총자산=100 지수로 바꿉니다(Kim·Muhn·Nikolaev 의 익명화 재무제표 방식). LLM 이 '외운 미래'로 답하는 것을 줄이기 위함입니다.</li>
<li><b>의견 전용</b>: v1 은 결정카드(판정·진입·손절·목표)를 절대 바꾸지 않습니다. 원장(ledger)에서 사후 수익률 엣지가 확인될 때만 판정 입력으로 승격합니다(8절).</li>
<li><b>검산 가능</b>: 모든 근거 문장에 사용한 숫자를 그대로 적고, 데이터 스냅샷(DART 접수번호·KIS 시각·룰/프롬프트 버전·모델)을 블록 끝에 남깁니다.</li>
</ul>
<div class="note">참고한 근거: GuruAgents(CIKM 2025, 프롬프트에 스코어링 수식 공개) · FINSABER(KDD 2026, 20년·100+종목 백테스트에서 LLM 전략 열위) · Profit Mirage(2025, 컷오프 이후 샤프 51~62% 감소) · Buffett's Alpha(AQR, 버핏 알파 = 저베타·퀄리티 + 1.7× 레버리지) · Validea 구루 모델 22년 트랙레코드(룰 기반 소폭 초과). 상세 분석은 별도 리서치 노트.</div>
""")

    parts.append(f"""<h2 id="where">2. 블록 위치·파이프라인</h2>
<div class="flow">
<div class="box"><b>① 리포트 md 파싱</b>종목코드·결정카드·<code>hub:enrich</code> 블록(KIS 실측)을 읽음. 원문은 읽기 전용.</div><div class="arrow">→</div>
<div class="box"><b>② 데이터</b>DART 연결 재무(FY-3~TTM) · KIS enrich · 결정카드 · 레짐 파일 · 유니버스 통계</div><div class="arrow">→</div>
<div class="box"><b>③ 룰 레이어</b>6구루 점수 0~1 → 적합/보류/부적합/데이터부족</div><div class="arrow">→</div>
<div class="box"><b>④ LLM 정성 필터</b>익명화 패킷 → JSON(버핏·멍거·드러켄밀러). 점수에 미반영.</div><div class="arrow">→</div>
<div class="box"><b>⑤ 렌더·주입</b>Markdown 블록을 <code>&lt;!-- hub:guru:begin:코드 --&gt;</code> 마커로 감싸 <b>enrich 블록 뒤, 📋 결정카드 앞</b>에 삽입(멱등: 있으면 교체)</div><div class="arrow">→</div>
<div class="box"><b>⑥ 허브 후처리</b>빌더가 index/html 을 만든 뒤 배지·필터·내비·리포트 html 반영</div></div>
<ul>
<li>마커 규칙은 기존 <code>&lt;!-- hub:enrich:begin:코드 --&gt;</code> 와 같은 방식입니다. 테마 리포트(종목별 카드 분리)는 종목마다 블록 1개.</li>
<li>결정카드가 "리포트 맨 끝"이라는 허브 파서 전제를 지키기 위해 블록은 항상 카드 <b>앞</b>에 들어갑니다. 블록 본문에 <code>📋 결정카드</code> 문자열을 쓰지 않아 카드 파서·품질점수와 충돌하지 않습니다.</li>
<li>재실행(가격 갱신·데이터 갱신) 시 같은 코드의 블록만 통째로 교체되므로 중복이 생기지 않습니다. 리포트 본문은 한 글자도 바뀌지 않습니다.</li>
<li>허브 빌더의 md→html 변환기가 raw HTML 을 이스케이프하므로 블록은 순수 Markdown(제목·표·목록·기울임)만 씁니다.</li>
</ul>
""")

    parts.append(f"""<h2 id="data">3. 데이터 소스와 기준</h2>
{table(["데이터", "출처", "기준·단위", "비고"], [
    ["연간 재무 FY-3·FY-2·FY-1", "OpenDART <code>fnlttSinglAcntAll</code> (사업보고서 11011, 연결 CFS)", "억원, 지배주주 기준", "연결이 없으면 별도(OFS)로 폴백하고 플래그 기록"],
    ["TTM", "FY-1 + 당해 최신 분(반)기 누적 − 전년 동기 누적", "손익·현금흐름 항목만 합성, 재무상태표는 최신 분기말 잔액", "한 항목이라도 빠지면 그 항목은 None(억지 합성 금지)"],
    ["TTM-1Y", "FY-2 + 전년 동기 누적 − 전전년 동기 누적", "피오트로스키 YoY 비교 전용", "없으면 FY-1 과 비교하고 표기"],
    ["계정 매칭", "account_id(IFRS 태그) 우선 → account_nm 정규식", "'-표준계정코드 미사용-' 대응", "<code>guru fundamentals --code 코드</code> 로 추출표를 눈으로 검산할 것"],
    ["감사의견·계속기업", "OpenDART <code>accnutAdtorNmNdAdtOpinion</code>", "최신 사업보고서", "비적정·계속기업 불확실성은 버핏·멍거 하드페일"],
    ["잠재희석", "OpenDART CB·BW·EB 미상환잔액 ÷ 발행주식수(<code>stockTotqySttus</code>)", "비율", "≥5% 페널티, ≥15% 추가 페널티"],
    ["유상증자 24개월", "현금흐름표 '유상증자' 유입(최근 2기)", "bool", "버핏 −0.05"],
    ["시장 데이터", "허브 enrich 블록(KIS 실측): 현재가·시총·PER·PBR·MA·52주·5/20/60일·ADV20·외인/기관 20일·공매도·ATR·선물", "리포트 적재 시점 값", "별도 KIS 호출 없이 리포트에 적힌 실측값을 그대로 사용"],
    ["결정카드", "📋 결정카드 (갱신 카드가 있으면 갱신본)", "판정·진입·손절·목표·손익비", "드러켄밀러 비대칭 점수와 '관계' 판단에 사용"],
    ["시장 레짐", "<code>~/.guru/market_regime.json</code> (일 1회 생성)", "KOSPI MA200 위/아래, VKOSPI, USDKRW 20일, 외인 시장 20일 순매수", "없으면 중립 0.5 로 처리하고 블록에 표기. 기존 macro·supply 데이터·NDF 모델 출력으로 채울 수 있음"],
    ["유니버스 통계", "<code>~/.guru/universe_stats.json</code> (<code>guru universe-build</code>)", "EY·ROC·ROE·PBR 분포(금융·지주 제외)", "없으면 그린블라트는 절대 스케일 폴백"],
])}
""")

    # rules
    parts.append(f"""<h2 id="rules">4. 룰 레이어 수식 (코드와 동일)</h2>
<p>공통: <code>s(x; lo, hi) = clip((x − lo)/(hi − lo), 0, 1)</code>, lo &gt; hi 이면 '낮을수록 좋음'으로 자동 반전. 점수 = Σ(가중치×구성요소) ÷ Σ(가용 가중치) + 보너스/페널티, 0~1 로 클립.
가용 가중치 합이 <b>{C.MIN_WEIGHT_COVERAGE:.0%} 미만이면 점수를 내지 않고 '데이터부족'</b>. 판정: 점수 ≥ {C.VERDICT_FIT} 적합 · ≥ {C.VERDICT_HOLD} 보류 · 미만 부적합(그레이엄·피오트로스키는 자체 임계값).</p>

<h3>4.1 버핏 — 품질 × 가격, 보수적 재무</h3>
{weights_table(C.BUFFETT, DESC['buffett'])}{adj_table(C.BUFFETT)}

<h3>4.2 멍거 — 예측가능성·자본수익 지속성·거버넌스</h3>
{weights_table(C.MUNGER, DESC['munger'])}{adj_table(C.MUNGER)}

<h3>4.3 그레이엄 — 방어적 투자자 7개 검사(한국형)</h3>
{table(["검사", "기준"], [[f"<code>{k}</code>", _esc(v)] for k, v in C.GRAHAM['tests'].items()])}
<p>점수 = 통과점수 합 ÷ 7 (미확인 검사는 0점 = 보수적). 넷넷 보너스: {_esc(C.GRAHAM['netnet_bonus'][1])}. 판정: {_esc(C.GRAHAM['verdict'])}. 평가 가능 검사가 4개 미만이면 데이터부족.</p>

<h3>4.4 피오트로스키 F-Score</h3>
{table(["신호", "정의"], [[f"<code>{k}</code>", _esc(v)] for k, v in C.PIOTROSKI['signals']])}
<p>TTM vs TTM-1Y(없으면 FY-1 vs FY-2). 점수 = F/9, 판정: {_esc(C.PIOTROSKI['verdict'])}. 평가 가능 신호 5개 미만이면 데이터부족.</p>

<h3>4.5 그린블라트 마법공식</h3>
<ul><li>{_esc(C.GREENBLATT['ey'])}</li><li>{_esc(C.GREENBLATT['roc'])}</li><li>적격: {_esc(C.GREENBLATT['eligibility'])} (금융·지주는 '해당없음')</li>
<li>{_esc(C.GREENBLATT['universe_rank'])}</li><li>유니버스 없을 때: 0.5·s(EY; {C.GREENBLATT['fallback_scales']['ey'][0]:.0%}→0, {C.GREENBLATT['fallback_scales']['ey'][1]:.0%}→1) + 0.5·s(ROC; 0→0, {C.GREENBLATT['fallback_scales']['roc'][1]:.0%}→1)</li>
<li>안전 페널티: {", ".join(f"{_esc(w)} {d:+.2f}" for d, w in C.GREENBLATT['safety_penalty'].values())}</li></ul>

<h3>4.6 드러켄밀러 — 종목 스크린이 아닌 '상황 점수'</h3>
{weights_table(C.DRUCKENMILLER, DESC['druckenmiller'])}
<ul>{''.join(f'<li>{_esc(r)}</li>' for r in C.DRUCKENMILLER['rules'])}</ul>
<div class="note warn">드러켄밀러 원칙(변화·유동성·비대칭·집중)은 재무제표 스크린으로 환원되지 않습니다. 그래서 이 행은 '이 종목이 좋은가'가 아니라 '지금 이 베팅 구조가 드러켄밀러 식으로 유리한 상황인가'를 점수화합니다. 레짐 파일이 없으면 중립 0.5 로 두고 그 사실을 블록에 적습니다.</div>
""")

    parts.append(f"""<h2 id="llm">5. LLM 정성 필터</h2>
<ul>
<li>대상: {', '.join(C.LLM['personas'])} (그레이엄·피오트로스키·그린블라트는 룰만). temperature {C.LLM['temperature']}, 기본 모델 <code>{C.LLM['default_model']}</code>, 최대 {C.LLM['max_tokens']} 토큰.</li>
<li>익명화: {''.join(f'<br>· {_esc(a)}' for a in C.LLM['anonymize'])}</li>
<li>프롬프트 핵심 명령: "회사를 추정하지 말고 제시된 사실만으로 판단, 없는 사실은 '불명', 출력은 JSON 하나". 프롬프트 원문은 <code>guru/prompts/*.md</code>.</li>
<li>출력 스키마(키 고정): 버핏 <code>{', '.join(C.LLM['schema_buffett'])}</code> · 멍거 <code>how_it_fails, predictability, incentive_alignment, too_hard_pile, verdict, confidence, one_line</code> · 드러켄밀러 <code>{', '.join(C.LLM['schema_druck'])}</code>. 스키마가 깨지면 그 셀은 'LLM 오류'로 표기하고 룰 결과는 그대로 둡니다.</li>
<li>캐시: (프롬프트 버전·페르소나·모델·패킷 해시) → <code>{C.LLM['cache_dir']}</code>. 같은 입력은 다시 호출하지 않습니다.</li>
<li>백엔드: <code>GURU_LLM_BACKEND=anthropic</code>(API 키) 또는 <code>command</code>(OpenClaw/Claude CLI 등 셸 명령에 stdin 으로 프롬프트 전달) 또는 <code>none</code>.</li>
</ul>
<div class="note bad">LLM 셀은 룰 점수·합의 수에 <b>전혀</b> 반영되지 않습니다. "해자·자본배분·회계품질·실패경로·변화 가설"처럼 숫자로 환원되지 않는 항목을 사람이 읽기 위한 보조 의견입니다.</div>
""")

    parts.append(f"""<h2 id="consensus">6. 합의 · 결정카드 관계 · 반증</h2>
<ul>
<li><b>합의</b> = 6구루 중 '적합' 수. 버킷: ≥{C.CONSENSUS_HI} hi · {C.CONSENSUS_MID}~{C.CONSENSUS_HI-1} mid · 0~{C.CONSENSUS_MID-1} lo. 평균은 점수가 산출된 구루만의 평균이며 '산출 n/6'을 함께 표기합니다(데이터부족이 많으면 평균이 과대해 보일 수 있어서).</li>
<li><b>요약문</b>: 가치·품질 축(버핏·멍거·그레이엄·피오트로스키·그린블라트) 적합 ≥3 → '가치·품질 적합', 1~2 → '부분 적합', 0 → '미달' + 드러켄밀러 판정을 '상황 우호/중립/비우호'로 붙입니다.</li>
<li><b>결정카드 관계</b>(카드는 바꾸지 않고 비교만): 카드 매수 & 적합 ≤1 → <i>상충</i> · 카드 관심/관망 & 적합 ≥4 → <i>우호</i> · 카드 매수 & 적합 ≥3 → <i>보강</i> · 데이터부족 ≥4 → <i>비교 보류</i> · 그 외 <i>중립</i>.</li>
<li><b>구루 레이어 반증</b>: '적합'으로 판정된 구루마다 철회 조건을 자동 생성합니다(버핏: ROE&lt;8% 또는 FCF≤0, 멍거: 분기 영업적자·감사의견 비적정, 그레이엄: 유동비율&lt;1.5 또는 PER×PBR&gt;22.5, 피오트로스키: F&lt;4, 그린블라트: 영업적자 또는 하위 50%, 드러켄밀러: MA200 하향·외인/기관 합산 순매도 전환).</li>
</ul>
""")

    parts.append(f"""<h2 id="hub">7. 허브 표시(후처리)</h2>
<p><code>python -m guru postprocess REPO</code> 는 빌더(춘식이)가 index.html 과 리포트 html 을 만든 <b>뒤</b>에 실행합니다. 빌더 코드는 건드리지 않습니다.</p>
<ul>
<li>index 카드: <code>data-guru="hi|mid|lo" data-gurun="N"</code> 속성 + 배지 <code>🧭 구루 N/6</code>(툴팁에 구루별 판정·점수·카드 관계). 기존 필터 JS(<code>data-키 == 값</code>)를 그대로 이용해 칩 <b>🧭 구루 합의 4+</b>, <b>🧭 구루 2~3</b> 을 추가합니다.</li>
<li>내비에 <b>🧭 투자구루 판단</b>(이 페이지) 링크, 상단 stats 에 '구루 평가 N'.</li>
<li>리포트 html: 빌더가 md 를 재렌더해 블록이 이미 있으면 건너뛰고, 없으면 같은 블록을 html 로 변환해 결정카드 앞에 삽입(<code>&lt;!--guru:html:begin:코드--&gt;</code> 마커로 멱등).</li>
<li>카드와 리포트 파일명(stem)·코드가 정확히 일치할 때만 배지를 붙입니다. 종목의 최신 리포트에 블록이 없으면(예: 10/14 리포트가 최신인데 10/12 리포트에만 블록) 배지를 붙이지 않습니다 — 오래된 의견을 최신 카드에 달지 않기 위함.</li>
<li>원장 연계: <code>python -m guru collect REPO --csv guru_ledger.csv</code> 가 (리포트, 날짜, 코드, 합의, 버킷, 구루별 판정/점수) CSV 를 내보냅니다. 원장 빌더가 날짜·코드로 조인해 D+5/D+20 표에 '구루 합의 hi/mid/lo' 행을 추가하면 됩니다.</li>
</ul>
""")

    parts.append(f"""<h2 id="gate">8. 검증 게이트 — 의견에서 판정 입력으로</h2>
<p>{_esc(C.GATE['policy'])}</p>
{table(["조건", "값"], [["원장 D+20 평가 완료 건수", f"≥ {C.GATE['min_evaluated']}"], ["합의 hi 그룹 − lo 그룹의 D+20 코스피 대비 초과수익", f"≥ {C.GATE['hi_vs_lo_min_edge_pp']}%p"], ["부트스트랩 p-값", f"< {C.GATE['bootstrap_p_max']}"], ["승격 내용(v2)", "예: 합의 ≤1 이면 '매수' 판정 금지 게이트 / 합의 ≥4 이면 눌림 진입 가중"]])}
<p>월 1회 <code>guru collect</code> CSV 와 원장을 조인해 버킷별 D+5·D+20 평균·중앙·승률·코스피대비를 계산하고, 결과를 이 페이지 하단 '검증 로그'에 날짜와 함께 추가합니다. 통과 전까지 룰 가중치를 사후 성과에 맞춰 조정하지 않습니다(데이터 스누핑 방지).</p>
""")

    parts.append(f"""<h2 id="limits">9. 한계·주의</h2>
<ul>
<li><b>계정 매칭</b>: DART 의 '-표준계정코드 미사용-' 계정은 이름 정규식으로 잡습니다. 첫 도입 시 종목 몇 개를 <code>guru fundamentals --code</code> 로 뽑아 DART 원문과 대조하세요. 틀리면 <code>~/.guru/fundamentals/코드.json</code> 을 손으로 고치면 그 파일이 우선 적용됩니다.</li>
<li><b>이자비용</b>이 분리 공시되지 않으면 금융비용(외환손실 포함)을 써서 이자보상배율이 과소평가될 수 있습니다(블록 근거에 표기).</li>
<li><b>TTM 합성</b>은 손익·현금흐름만 하고 재무상태표는 최신 분기말을 씁니다. 분기 보고서에 없는 항목(배당·자사주 등)은 TTM 에서 None 이 되어 해당 구성요소가 빠집니다.</li>
<li><b>익명화는 불완전</b>합니다. 제품명·업종 서술로 LLM 이 회사를 알아볼 수 있습니다. 그래서 LLM 셀은 점수에 넣지 않고, 프롬프트로 '추정 금지'를 명령하며, 원장 검증에서는 룰 점수만 봅니다.</li>
<li><b>금융·지주</b>: 그린블라트 '해당없음', 버핏·멍거는 지주 페널티 플래그만. 은행·보험은 별도 프레임이 필요하며 v1 에서는 데이터부족으로 나올 수 있습니다.</li>
<li><b>command 백엔드</b>(CLI 경유)는 temperature 를 보장하지 못해 LLM 셀이 재실행 시 달라질 수 있습니다. 캐시가 같은 입력의 재호출은 막습니다.</li>
<li><b>레짐 파일</b>이 없으면 드러켄밀러 레짐 점수는 중립 0.5 입니다. 블록에 그 사실이 적히므로 '레짐 2026-..'이 없는 블록은 상황 점수를 할인해서 읽으세요.</li>
<li>이 블록은 투자 권유가 아니며, 허브의 결정카드와 마찬가지로 사후 엣지 검증 전까지는 아이디어 점검용입니다.</li>
</ul>
""")

    parts.append(f"""<h2 id="run">10. 실행 방법 (Mac mini)</h2>
<pre>cd ~/report-hub            # 허브 저장소(guru/ 패키지 포함)
export DART_API_KEY=...     # OpenDART
export GURU_LLM_BACKEND=command
export GURU_LLM_CMD='claude -p --output-format text'   # 또는 GURU_LLM_BACKEND=anthropic + ANTHROPIC_API_KEY

python -m guru fundamentals --code 306200                     # 1) DART 추출표 검산(최초 몇 종목)
python -m guru regime-sample --out ~/.guru/market_regime.json # 2) 레짐 파일 — 실제 값은 매크로 잡이 매일 덮어쓰기
python -m guru inject 20261010-161032-세아제강.md             # 3) 리포트 1건 (멱등)
python -m guru backfill . --since 20260901                     # 4) 기존 리포트 일괄
python -m guru postprocess .                                   # 5) 빌더 실행 '뒤' index·html 반영
python -m guru collect . --out guru_index.json --csv guru_ledger.csv   # 6) 원장용 CSV</pre>
<p><b>파이프라인 훅 순서</b>: 리포트 생성 → enrich 블록 주입(기존) → <code>guru inject</code> → 빌더(index/html) → <code>guru postprocess</code> → git push. LaunchAgent 의 빌드 스크립트에서 빌더 호출 바로 뒤에 postprocess 한 줄을 추가하면 됩니다. 가격 갱신(30분 주기)마다 index 가 재생성되므로 postprocess 도 그때마다 같이 돕니다(몇 초).</p>
<p>테스트: <code>GURU_TEST_REPO=~/report-hub python -m unittest guru.tests.test_guru guru.tests.test_dart -v</code> (저장소 355건 파싱: 코드 식별 349 · 결정카드 322 · enrich 시장데이터 347 · 복수종목 29 — 2026-10-19 기준).</p>
""")

    parts.append(f"""<h2 id="example">11. 예시 출력 — 가상 기업 'A사'(픽스처, 실존 기업 아님)</h2>
<p>아래는 <code>guru/tests/fixtures/fixture_company.json</code>(가상 수치)에 실제 코드를 돌린 결과입니다. LLM 열은 예시 응답입니다. 실제 리포트에서는 같은 표가 enrich 블록 뒤, 결정카드 앞에 들어갑니다.</p>
{ex_html}
<p class="small">실제 리포트에 DART 없이(<code>--no-dart</code>) 돌리면 재무 기반 구루는 '데이터부족'으로, 드러켄밀러는 enrich·결정카드·레짐만으로 산출됩니다. 그 경우 '산출 n/6'이 작게 찍혀 평균을 과신하지 않도록 설계했습니다.</p>
""")

    parts.append(f"""<h2 id="check">12. 검산 예시 — 버핏 점수</h2>
<p>A사 구성요소: {_esc(buffett_check)}</p>
<p>가중합 = {_esc(wsum)} = <b>{base:.3f}</b> → 보너스/페널티 {sum(float(a.split('|')[0]) for a in b.adjustments if not a.startswith('HARDFAIL')):+.2f} → 점수 <b>{b.score:.2f}</b> → {b.verdict}(임계 {C.VERDICT_FIT}/{C.VERDICT_HOLD}).</p>
<p>피오트로스키: TTM(2Q26) vs TTM-1Y(2Q25) 9개 신호 전부 통과(자산회전율 0.785→0.827 증가 포함) → 9/9. 그린블라트: EY = 520/(5,000+370−720)= 11.2%, ROC = 520/((2,450−720)−(1,050−110)+1,850)= 19.7%.</p>
""")

    parts.append(f"""<h2 id="files">13. 파일·버전</h2>
{table(["파일", "역할"], [
    ["<code>guru/config.py</code>", "가중치·임계값·버전(유일한 원천)"],
    ["<code>guru/parse_report.py</code>", "리포트 md 파싱(코드·결정카드·enrich 시장데이터)"],
    ["<code>guru/data_dart.py</code>", "OpenDART 어댑터·TTM 합성·검산표"],
    ["<code>guru/rules.py</code>", "6구루 룰 + 합의·관계·반증"],
    ["<code>guru/anonymize.py</code> · <code>persona.py</code> · <code>prompts/</code>", "LLM 정성 필터(익명화·백엔드·캐시·프롬프트)"],
    ["<code>guru/render.py</code> · <code>inject.py</code>", "Markdown 블록 렌더·멱등 주입"],
    ["<code>guru/collect.py</code> · <code>hub_postprocess.py</code>", "블록 재수집(guru_index.json·CSV)·index/html 후처리"],
    ["<code>guru/universe.py</code>", "그린블라트 유니버스 통계"],
    ["<code>guru/docs_export.py</code>", "이 페이지 생성(<code>python -m guru docs</code>)"],
    ["<code>guru/tests/</code>", "단위 테스트·픽스처·DART 응답 형식 테스트"],
    ["<code>guru/scripts/make_regime_pykrx.py</code>", "레짐 파일 생성 예시(pykrx)"],
    ["<code>GURU_README.md</code>", "설치·환경변수·훅 순서"],
])}
<h3>버전 이력</h3>
<ul><li>v{C.RULES_VERSION} ({today}) — 최초 구현. 6구루 룰, LLM 정성 필터 3인, 의견 전용, 허브 후처리.</li></ul>
<h3>검증 로그</h3>
<ul><li>(월 1회 원장 조인 결과를 여기에 날짜와 함께 추가)</li></ul>
<p class="small">이 문서는 <code>python -m guru docs --out guru.html</code> 로 재생성됩니다. 수식 표는 config.py 에서 읽어 오므로 코드가 바뀌면 문서도 바뀝니다.</p>
</body></html>""")
    return "\n".join(parts)


def write_docs(out: str) -> None:
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(build_html())
