"""
python -m guru <command>

  inject REPORT.md [...]        리포트에 🧭 투자구루 판단의견 블록 주입(멱등)
  backfill REPO_DIR             블록 없는 리포트 전부 처리 (--force 로 전부 재생성)
  postprocess REPO_DIR          index.html 배지·필터·내비 + 리포트 html 반영 (빌더 뒤에 실행)
  collect REPO_DIR              guru_index.json / ledger CSV 내보내기
  fundamentals --code 000000    DART 추출표 검산 출력
  regime-sample --out FILE      레짐 파일 예시 생성
  universe-build --codes FILE   유니버스 통계 생성(DART 대량 조회)
  docs --out guru.html          구현 설명 페이지 재생성(설정값 표 = config.py)
  remove REPORT.md              블록 제거
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import date

from . import config as C
from .data_dart import DartClient, DartError, fetch_fundamentals, render_fundamentals_table
from .persona import LLMClient
from .pipeline import Options, process_report


def _common(p: argparse.ArgumentParser):
    p.add_argument("--no-dart", action="store_true", help="DART 조회 안 함(enrich·카드만으로 계산)")
    p.add_argument("--dart-key", default=None, help="OpenDART API 키(기본: 환경변수 DART_API_KEY)")
    p.add_argument("--offline", action="store_true", help="DART 캐시만 사용")
    p.add_argument("--fundamentals-dir", default="~/.guru/fundamentals", help="재무 JSON 저장/우선 로드 폴더")
    p.add_argument("--llm", default=None, choices=["anthropic", "command", "none"], help="정성 필터 백엔드(기본: $GURU_LLM_BACKEND 또는 none)")
    p.add_argument("--llm-model", default=None)
    p.add_argument("--regime", default="~/.guru/market_regime.json")
    p.add_argument("--universe", default="~/.guru/universe_stats.json")
    p.add_argument("--sector-group", default=None, choices=["일반", "금융", "지주"])
    p.add_argument("--asof", default=None, help="YYYY-MM-DD (DART 기준일, 기본 오늘)")
    p.add_argument("--codes", default=None, help="쉼표로 구분한 종목코드만 처리")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--backup", action="store_true", help="최초 1회 .bak 보관")
    p.add_argument("--print", action="store_true", help="생성 블록을 stdout 에 출력")
    p.add_argument("-v", "--verbose", action="store_true")


def _opts(a) -> Options:
    return Options(
        dart=not a.no_dart, dart_key=a.dart_key, offline=a.offline, fundamentals_dir=a.fundamentals_dir,
        llm_backend=a.llm, llm_model=a.llm_model, regime_file=a.regime, universe_file=a.universe,
        sector_group=a.sector_group, dry_run=a.dry_run, backup=a.backup, verbose=a.verbose,
        asof=date.fromisoformat(a.asof) if a.asof else None,
        codes=[c.strip() for c in a.codes.split(",")] if a.codes else None,
    )


def _clients(opts: Options):
    client = DartClient(api_key=opts.dart_key, offline=opts.offline) if opts.dart else None
    llm = LLMClient(backend=opts.llm_backend, model=opts.llm_model)
    return client, llm


def cmd_inject(a):
    opts = _opts(a)
    client, llm = _clients(opts)
    for path in a.reports:
        res = process_report(path, opts, client, llm)
        if a.print:
            for code, r in res.items():
                print(r["block"])
    if client:
        print(f"DART 호출 {client.calls}회 · LLM 호출 {llm.calls}회", file=sys.stderr)


def cmd_backfill(a):
    opts = _opts(a)
    client, llm = _clients(opts)
    paths = sorted(glob.glob(os.path.join(a.repo, "2026*.md")))
    if a.since:
        paths = [p for p in paths if os.path.basename(p)[:8] >= a.since]
    done = 0
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            has = "hub:guru:begin" in fh.read()
        if has and not a.force:
            continue
        process_report(p, opts, client, llm)
        done += 1
        if a.limit and done >= a.limit:
            break
    print(f"처리 {done}건 · DART 호출 {client.calls if client else 0}회 · LLM 호출 {llm.calls}회")


def cmd_postprocess(a):
    from .hub_postprocess import run
    print(json.dumps(run(a.repo, dry_run=a.dry_run, patch_reports=not a.no_report_html), ensure_ascii=False))


def cmd_collect(a):
    from .collect import collect, export_ledger_csv, write_index
    rows = collect(a.repo)
    write_index(rows, a.out)
    if a.csv:
        export_ledger_csv(rows, a.csv)
    print(f"{len(rows)} 블록 → {a.out}" + (f", {a.csv}" if a.csv else ""))


def cmd_fundamentals(a):
    client = DartClient(api_key=a.dart_key, offline=a.offline)
    try:
        f = fetch_fundamentals(a.code, client, asof=date.fromisoformat(a.asof) if a.asof else None, sector_group=a.sector_group)
    except DartError as e:
        print("오류:", e)
        sys.exit(2)
    print(render_fundamentals_table(f))
    if a.save:
        from .serialize import fundamentals_to_dict
        os.makedirs(os.path.expanduser(a.save), exist_ok=True)
        out = os.path.join(os.path.expanduser(a.save), f"{a.code}.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(fundamentals_to_dict(f), fh, ensure_ascii=False, indent=1)
        print("저장:", out)


def cmd_regime_sample(a):
    sample = {"asof": date.today().isoformat(), "kospi_above_ma200": True, "kospi_ret60": 0.08, "vkospi": 21.5,
              "usdkrw_ret20": -0.01, "foreign_net20_market": 12000.0, "source": "sample — 실제 값으로 교체할 것"}
    with open(os.path.expanduser(a.out), "w", encoding="utf-8") as fh:
        json.dump(sample, fh, ensure_ascii=False, indent=1)
    print("예시 레짐 파일:", a.out)


def cmd_universe_build(a):
    from .universe import build
    client = DartClient(api_key=a.dart_key, offline=a.offline)
    codes = [ln.strip().split()[0] for ln in open(a.codes, encoding="utf-8") if ln.strip() and not ln.startswith("#")]
    recs, errs = [], 0
    for i, code in enumerate(codes, 1):
        try:
            f = fetch_fundamentals(code, client)
            t = f.ttm()
            rec = {"code": code, "sector_group": f.flags.sector_group, "ey": None, "roc": None, "roe": None, "pbr": None}
            if t and t.op and t.op > 0 and t.debt is not None and t.cash is not None and t.equity_parent:
                # 시총이 없어 EV 를 못 만들면 EY 는 비움 — 시총은 mcap 파일(code→억원)로 보강 가능
                if a.mcap and code in _mcaps:
                    ev = _mcaps[code] + t.debt - t.cash
                    rec["ey"] = t.op / ev if ev > 0 else None
                    rec["pbr"] = _mcaps[code] / t.equity_parent
                from .rules import _invested_capital
                ic = _invested_capital(t)
                rec["roc"] = t.op / ic if ic else None
                rec["roe"] = (t.ni_parent / t.equity_parent) if t.ni_parent is not None else None
            recs.append(rec)
        except Exception as e:  # noqa
            errs += 1
        if i % 50 == 0:
            print(f"{i}/{len(codes)} (오류 {errs})", file=sys.stderr)
    stats = build(recs, date.today().isoformat())
    with open(os.path.expanduser(a.out), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False)
    print(f"유니버스 N={stats['n']} → {a.out} (오류 {errs})")


_mcaps = {}


def cmd_docs(a):
    from .docs_export import write_docs
    write_docs(a.out)
    print("생성:", a.out)


def cmd_remove(a):
    from .inject import remove_block
    for p in a.reports:
        print(p, "→", "제거" if remove_block(p, a.code) else "블록 없음")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="guru", description="투자구루 판단의견(hub:guru) 도구")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inject", help="리포트에 블록 주입")
    p.add_argument("reports", nargs="+")
    _common(p)
    p.set_defaults(fn=cmd_inject)

    p = sub.add_parser("backfill", help="저장소 전체 처리")
    p.add_argument("repo")
    p.add_argument("--since", default=None, help="YYYYMMDD 이후 파일만")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--force", action="store_true", help="블록이 있어도 재생성")
    _common(p)
    p.set_defaults(fn=cmd_backfill)

    p = sub.add_parser("postprocess", help="index.html·리포트 html 후처리")
    p.add_argument("repo")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-report-html", action="store_true")
    p.set_defaults(fn=cmd_postprocess)

    p = sub.add_parser("collect", help="guru_index.json / CSV")
    p.add_argument("repo")
    p.add_argument("--out", default="guru_index.json")
    p.add_argument("--csv", default=None)
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("fundamentals", help="DART 추출 검산")
    p.add_argument("--code", required=True)
    p.add_argument("--dart-key", default=None)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--asof", default=None)
    p.add_argument("--sector-group", default=None)
    p.add_argument("--save", default=None, help="저장 폴더(기본 ~/.guru/fundamentals 권장)")
    p.set_defaults(fn=cmd_fundamentals)

    p = sub.add_parser("regime-sample")
    p.add_argument("--out", default="~/.guru/market_regime.json")
    p.set_defaults(fn=cmd_regime_sample)

    p = sub.add_parser("universe-build")
    p.add_argument("--codes", required=True, help="종목코드 목록 파일(한 줄 하나)")
    p.add_argument("--mcap", default=None, help="종목코드→시총(억원) JSON (EY·PBR 계산용)")
    p.add_argument("--out", default="~/.guru/universe_stats.json")
    p.add_argument("--dart-key", default=None)
    p.add_argument("--offline", action="store_true")
    p.set_defaults(fn=cmd_universe_build)

    p = sub.add_parser("docs")
    p.add_argument("--out", default="guru.html")
    p.set_defaults(fn=cmd_docs)

    p = sub.add_parser("remove")
    p.add_argument("reports", nargs="+")
    p.add_argument("--code", default=None)
    p.set_defaults(fn=cmd_remove)

    a = ap.parse_args(argv)
    if getattr(a, "cmd", "") == "universe-build" and a.mcap:
        with open(os.path.expanduser(a.mcap), encoding="utf-8") as fh:
            _mcaps.update({k: float(v) for k, v in json.load(fh).items()})
    a.fn(a)


if __name__ == "__main__":
    main()
