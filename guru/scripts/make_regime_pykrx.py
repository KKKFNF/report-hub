#!/usr/bin/env python3
"""
시장 레짐 파일(~/.guru/market_regime.json) 생성 예시 — pykrx 사용(선택 의존성).
Mac mini 의 일일 잡(06:30)에서 한 번 실행한다. 구할 수 없는 항목은 None 으로 두면
드러켄밀러 레짐 점수가 '가용 항목 평균'으로 계산된다(모두 None 이면 중립 0.5).

  pip install pykrx
  python guru/scripts/make_regime_pykrx.py --out ~/.guru/market_regime.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="~/.guru/market_regime.json")
    a = ap.parse_args()
    out = {"asof": date.today().isoformat(), "kospi_above_ma200": None, "kospi_ret60": None, "vkospi": None,
           "usdkrw_ret20": None, "foreign_net20_market": None, "source": "pykrx"}
    try:
        from pykrx import stock
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=400)).strftime("%Y%m%d")
        df = stock.get_index_ohlcv(start, end, "1001")          # KOSPI
        close = df["종가"].dropna()
        if len(close) >= 200:
            out["kospi_above_ma200"] = bool(close.iloc[-1] > close.tail(200).mean())
        if len(close) >= 61:
            out["kospi_ret60"] = float(close.iloc[-1] / close.iloc[-61] - 1)
        try:
            inv = stock.get_market_trading_value_by_investor((date.today() - timedelta(days=40)).strftime("%Y%m%d"), end, "KOSPI")
            # 외국인 순매수(원) 최근 20영업일 합 → 억원
            if "외국인" in inv.index:
                out["foreign_net20_market"] = float(inv.loc["외국인", "순매수"]) / 1e8
        except Exception:
            pass
    except Exception as e:  # pykrx 미설치 등
        out["source"] = f"pykrx 실패: {e}"
    # VKOSPI·USDKRW 는 기존 매크로 파이프라인(macro.html 데이터, NDF 모델)에서 채워 넣을 것:
    #   out["vkospi"] = ..., out["usdkrw_ret20"] = (오늘 USDKRW / 20영업일 전 USDKRW − 1)
    p = os.path.expanduser(a.out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
