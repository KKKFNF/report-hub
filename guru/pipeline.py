"""리포트 1건 처리: 파싱 → 데이터 → 룰 → (LLM) → 렌더 → 주입."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

from . import config as C
from . import rules
from .anonymize import anonymize_text, metrics_packet
from .data_dart import DartClient, DartError, fetch_fundamentals
from .inject import inject_file
from .parse_report import (card_for, excerpt_sections, find_targets, market_for, report_date, report_stem)
from .persona import LLMClient, run_personas
from .render import render_block
from .schema import Fundamentals, GuruBlockData, Regime
from .serialize import fundamentals_from_dict, fundamentals_to_dict, load_json, regime_from_dict
from .universe import load as load_universe


@dataclass
class Options:
    dart: bool = True
    dart_key: Optional[str] = None
    offline: bool = False
    fundamentals_dir: str = "~/.guru/fundamentals"
    llm_backend: Optional[str] = None       # None → 환경변수 GURU_LLM_BACKEND, 없으면 none
    llm_model: Optional[str] = None
    regime_file: Optional[str] = "~/.guru/market_regime.json"
    universe_file: Optional[str] = "~/.guru/universe_stats.json"
    sector_group: Optional[str] = None
    dry_run: bool = False
    backup: bool = False
    force: bool = False
    verbose: bool = False
    asof: Optional[date] = None
    codes: Optional[List[str]] = None       # 지정하면 그 종목만


def load_regime(path: Optional[str]) -> Optional[Regime]:
    if not path:
        return None
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return None
    return regime_from_dict(load_json(p))


def get_fundamentals(code: str, opts: Options, client: Optional[DartClient], log) -> Optional[Fundamentals]:
    fdir = os.path.expanduser(opts.fundamentals_dir)
    os.makedirs(fdir, exist_ok=True)
    # 1) 수동/캐시 JSON (CPA 검산 후 수정본을 두면 그것을 우선)
    for cand in (os.path.join(fdir, f"{code}.json"),):
        if os.path.exists(cand):
            try:
                f = fundamentals_from_dict(load_json(cand))
                log(f"  fundamentals: {cand} (파일)")
                return f
            except Exception as e:  # noqa
                log(f"  fundamentals 파일 오류 {cand}: {e}")
    # 2) DART
    if not opts.dart or client is None:
        return None
    try:
        f = fetch_fundamentals(code, client, asof=opts.asof, sector_group=opts.sector_group)
        with open(os.path.join(fdir, f"{code}.json"), "w", encoding="utf-8") as fh:
            json.dump(fundamentals_to_dict(f), fh, ensure_ascii=False, indent=1)
        log(f"  fundamentals: DART {len(f.periods)}기 ({', '.join(p.label for p in f.periods)})")
        return f
    except DartError as e:
        log(f"  DART 실패: {e}")
        return None


def snapshot_lines(f: Optional[Fundamentals], mk, rg: Optional[Regime], uni: Optional[dict], llm: Optional[LLMClient]) -> List[str]:
    out = []
    if f and f.periods:
        out.append("DART 연결 " + "·".join(p.label for p in f.periods) + (" · " + f.sources[0] if f.sources else ""))
    else:
        out.append("DART 미조회(룰 중 재무 항목 데이터부족)")
    out.append(f"KIS enrich {mk.asof}" if mk and mk.asof else "KIS enrich 없음")
    out.append(f"레짐 {rg.asof}" if rg and rg.asof else "레짐 파일 없음(중립 0.5)")
    out.append(f"유니버스 N={uni.get('n')} ({uni.get('asof')})" if uni else "유니버스 통계 없음(절대 스케일)")
    model = f"{llm.backend}/{llm.model}" if llm and llm.backend != "none" else "LLM 미실행"
    out.append(f"룰 v{C.RULES_VERSION} · 프롬프트 v{C.PROMPT_VERSION} · {model} · 생성 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return out


def process_report(path: str, opts: Options, client: Optional[DartClient] = None,
                   llm: Optional[LLMClient] = None, log=print) -> Dict[str, dict]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    targets = find_targets(text, path)
    if not targets:
        log(f"{os.path.basename(path)}: 종목코드를 찾지 못함 → 건너뜀")
        return {}
    if opts.codes:
        targets = [t for t in targets if t[0] in opts.codes]
    default_code = targets[0][0]
    rg = load_regime(opts.regime_file)
    uni = load_universe(opts.universe_file)
    stem = report_stem(path)
    base_year = int(stem[:4]) if stem[:4].isdigit() else date.today().year
    results: Dict[str, dict] = {}
    names = [n for _, n in targets if n]
    codes = [c for c, _ in targets]

    for code, name in targets:
        log(f"{stem} · {name}({code})")
        card = card_for(text, code, default_code)
        mk = market_for(text, code, name, default_code)
        f = get_fundamentals(code, opts, client, log)
        verdicts = rules.run_all(f, mk, card, rg, uni)
        if llm and llm.backend != "none":
            packet = metrics_packet(f, mk, card)
            excerpt = anonymize_text(excerpt_sections(text), names, codes, base_year)
            llm_out = run_personas(llm, packet, excerpt)
            for v in verdicts:
                if v.guru in llm_out:
                    v.llm = llm_out[v.guru]
        fit, bucket, mean_score, summary = rules.consensus(verdicts)
        data = GuruBlockData(
            code=code, name=name or (f.name if f else code), report=stem,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            rules_version=C.RULES_VERSION, prompt_version=C.PROMPT_VERSION,
            data_snapshot={"report_date": report_date(path), "kis": (mk.asof if mk else ""), "dart": (f.fetched_at if f else "")},
            verdicts=verdicts, consensus_fit=fit, consensus_bucket=bucket, mean_score=mean_score,
            summary=summary, card_relation=rules.card_relation(verdicts, card), falsifiers=rules.guru_falsifiers(verdicts),
        )
        block = render_block(data, card, snapshot_lines(f, mk, rg, uni, llm))
        changed = inject_file(path, code, block, backup=opts.backup, dry_run=opts.dry_run)
        log(f"  → 적합 {fit}/6 ({bucket}) · {summary} · {'변경 없음' if not changed else ('DRY-RUN' if opts.dry_run else '주입 완료')}")
        results[code] = {"fit": fit, "bucket": bucket, "mean": mean_score, "block": block, "changed": changed,
                         "verdicts": [v.to_dict() for v in verdicts]}
    return results
