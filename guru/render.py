"""
hub:guru 블록 렌더링(순수 Markdown).

허브 빌더의 md→html 변환기는 raw HTML 을 이스케이프하므로(enrich 마커가 본문에 그대로 보이는 것과 동일)
HTML 태그·주석을 쓰지 않는다. 표는 파이프 테이블(빌더가 <table> 로 렌더함을 확인).
표의 열 순서·구분자는 collect.parse_block() 이 다시 읽으므로 바꾸면 collect.py 도 같이 바꿀 것.
"""
from __future__ import annotations

from typing import List, Optional

from . import config as C
from .schema import DecisionCard, GuruBlockData, GuruVerdict

ICON = {"적합": "🟢", "보류": "🟡", "부적합": "🔴", "데이터부족": "⚪", "해당없음": "⚪"}
NOTE = ("룰 기반 점수(결정론적, 0~1)와 LLM 정성 필터(익명화 입력)를 분리 표기한 **의견**입니다. "
        "결정카드(📋)의 판정·진입·손절·목표는 바꾸지 않습니다. 산식·데이터·검증 게이트는 [구현 설명 페이지](./guru.html) 참조.")


def _clean(s: str) -> str:
    return str(s).replace("|", "/").replace("\n", " ").strip()


def _llm_cell(guru: str, llm: Optional[dict]) -> str:
    if llm is None:
        return "— (미실행)"
    if "error" in llm:
        return "LLM 오류: " + _clean(llm["error"])[:60]
    v = llm.get("verdict", "보류")
    try:
        conf_s = f"{float(llm.get('confidence', 0.0)):.1f}"
    except (TypeError, ValueError):
        conf_s = "?"
    one = _clean(llm.get("one_line", ""))
    if guru == "buffett":
        head = f"해자 {llm.get('moat','불명')} · 자본배분 {llm.get('capital_allocation','불명')}"
        flags = [_clean(x) for x in (llm.get("accounting_quality_flags") or [])][:2]
        if flags:
            head += " · 회계플래그: " + "; ".join(flags)
    elif guru == "munger":
        head = f"예측가능성 {llm.get('predictability','불명')} · 인센티브 {llm.get('incentive_alignment','불명')}"
        if llm.get("too_hard_pile"):
            head += " · too-hard"
    else:
        head = f"비대칭 {llm.get('asymmetry','불명')}" + (" · 유동성 역풍" if llm.get("liquidity_headwind") else "")
    return _clean(f"{head} · 판정 {ICON.get(v,'')}{v}({conf_s}) — {one}")[:220]


def _rule_cell(v: GuruVerdict) -> str:
    parts = list(v.reasons[:3])
    adj = [a for a in v.adjustments if not a.startswith("+0.00")]
    hard = [a.split("|", 1)[1] for a in adj if a.startswith("HARDFAIL")]
    nums = [a for a in adj if not a.startswith("HARDFAIL")]
    if nums:
        tot = sum(float(a.split("|")[0]) for a in nums)
        parts.append(f"조정 {tot:+.2f}(" + "; ".join(a.split("|", 1)[1] for a in nums)[:90] + ")")
    if hard:
        parts.append("하드페일: " + "; ".join(hard)[:90])
    if v.tags:
        parts.append("태그: " + ", ".join(v.tags))
    txt = " · ".join(_clean(p) for p in parts)
    return txt if txt else "—"


def score_text(v: GuruVerdict) -> str:
    if v.score is None:
        return "—"
    if v.guru == "piotroski":
        return f"{int(v.values.get('f_score', round(v.score*9)))}/9"
    return f"{v.score:.2f}"


def render_block(d: GuruBlockData, card: Optional[DecisionCard], snapshot_lines: List[str]) -> str:
    rows = []
    for v in d.verdicts:
        llm = _llm_cell(v.guru, v.llm) if v.guru in C.LLM["personas"] else "— (룰만)"
        rows.append(f"| {v.label} | {score_text(v)} | {ICON.get(v.verdict,'')} {v.verdict} | {_rule_cell(v)} | {llm} |")
    missing = [f"{v.label}: " + ", ".join(_clean(m) for m in v.missing[:3]) for v in d.verdicts if v.missing]
    mean_s = "—" if d.mean_score is None else f"{d.mean_score:.2f}"
    card_txt = f" (카드 판정: {card.verdict_norm or card.verdict})" if card and (card.verdict or card.verdict_norm) else ""
    lines = [
        C.MARK_BEGIN.format(code=d.code, ver=C.BLOCK_VERSION),
        "",
        f"## 🧭 투자구루 판단의견 — {d.name}({d.code})",
        "",
        f"*{NOTE}*",
        "",
        "| 구루 | 점수 | 판정 | 룰 근거(검산용 수치) | 정성 필터(LLM) |",
        "|---|---|---|---|---|",
        *rows,
        "",
        f"- **합의** 적합 {d.consensus_fit}/6 · 평균 {mean_s} · 산출 {sum(1 for v in d.verdicts if v.score is not None)}/6 · {d.summary}",
        f"- **결정카드 관계** {d.card_relation}{card_txt}",
    ]
    if d.falsifiers:
        lines.append("- **구루 레이어 반증** " + " / ".join(d.falsifiers))
    if missing:
        lines.append("- **미확인** " + " / ".join(missing))
    lines.append("")
    lines.append("*" + " · ".join(_clean(x) for x in snapshot_lines) + "*")
    lines.append("")
    lines.append(C.MARK_END.format(code=d.code))
    return "\n".join(lines) + "\n"
