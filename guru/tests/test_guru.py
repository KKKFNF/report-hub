"""
python -m unittest guru.tests.test_guru -v
환경변수 GURU_TEST_REPO=/path/to/report-hub 가 있으면 실제 저장소 파싱 테스트도 수행.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import tempfile
import unittest

from guru import collect, config as C, inject, parse_report, render, rules
from guru.schema import DecisionCard, GuruBlockData
from guru.serialize import fundamentals_from_dict, market_from_dict, regime_from_dict

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "fixtures", "fixture_company.json"), encoding="utf-8") as _fh:
    FIX = json.load(_fh)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def fixture_objects():
    f = fundamentals_from_dict(FIX["fundamentals"])
    mk = market_from_dict(FIX["market"])
    card = DecisionCard(**FIX["card"])
    rg = regime_from_dict(FIX["regime"])
    return f, mk, card, rg


def make_block(f, mk, card, rg, llm=None):
    verdicts = rules.run_all(f, mk, card, rg)
    if llm:
        for v in verdicts:
            if v.guru in llm:
                v.llm = llm[v.guru]
    fit, bucket, mean_score, summary = rules.consensus(verdicts)
    d = GuruBlockData(code=f.code, name=f.name, report="20261019-120000-가상A사-000000", generated_at="2026-10-19 12:00",
                      rules_version=C.RULES_VERSION, prompt_version=C.PROMPT_VERSION, data_snapshot={},
                      verdicts=verdicts, consensus_fit=fit, consensus_bucket=bucket, mean_score=mean_score,
                      summary=summary, card_relation=rules.card_relation(verdicts, card),
                      falsifiers=rules.guru_falsifiers(verdicts))
    return d, render.render_block(d, card, ["DART 연결 FY2023·FY2024·FY2025·TTM(2Q26)", "KIS enrich 2026-10-19 15:38",
                                            "레짐 2026-10-19", "유니버스 통계 없음(절대 스케일)",
                                            f"룰 v{C.RULES_VERSION} · 프롬프트 v{C.PROMPT_VERSION} · LLM 미실행 · 생성 2026-10-19 12:00"])


class RulesTest(unittest.TestCase):
    def test_deterministic_and_sane(self):
        f, mk, card, rg = fixture_objects()
        a = [v.to_dict() for v in rules.run_all(f, mk, card, rg)]
        b = [v.to_dict() for v in rules.run_all(f, mk, card, rg)]
        self.assertEqual(a, b)
        byg = {v["guru"]: v for v in a}
        self.assertEqual(set(byg), set(rules.ORDER))
        for g, v in byg.items():
            self.assertIn(v["verdict"], ("적합", "보류", "부적합", "데이터부족", "해당없음"), g)
            if v["score"] is not None:
                self.assertTrue(0.0 <= v["score"] <= 1.0, g)
        # 픽스처 기대 범위(수작업 검산: 버핏 base ≈0.62)
        self.assertAlmostEqual(byg["buffett"]["score"], 0.62, delta=0.03)
        self.assertEqual(byg["buffett"]["verdict"], "보류")
        self.assertEqual(byg["piotroski"]["values"]["f_score"], 9.0)   # 수작업 검산: 9개 신호 모두 통과(회전율 0.785→0.827 증가)
        self.assertEqual(byg["piotroski"]["verdict"], "적합")
        self.assertEqual(byg["druckenmiller"]["values"]["rr1"], 3.0)
        self.assertGreaterEqual(byg["druckenmiller"]["score"], 0.65)
        self.assertIn("집중 베팅 후보(손실한도 유지)", byg["druckenmiller"]["tags"])

    def test_missing_data_marks_insufficient(self):
        _, mk, card, rg = fixture_objects()
        vs = {v.guru: v for v in rules.run_all(None, mk, card, rg)}
        self.assertEqual(vs["munger"].verdict, "데이터부족")
        self.assertEqual(vs["piotroski"].verdict, "데이터부족")
        self.assertEqual(vs["greenblatt"].verdict, "데이터부족")
        self.assertIsNotNone(vs["druckenmiller"].score)   # enrich·카드·레짐만으로 계산 가능
        self.assertEqual(vs["buffett"].verdict, "데이터부족")   # 밸류에이션(0.15)만 가용 → 커버리지 < 0.5

    def test_hard_fail(self):
        f, mk, card, rg = fixture_objects()
        f.flags.audit_opinion = "한정"
        v = rules.score_buffett(f, mk)
        self.assertEqual(v.verdict, "부적합")
        self.assertTrue(any(a.startswith("HARDFAIL") for a in v.adjustments))

    def test_weights_sum_to_one(self):
        for cfg in (C.BUFFETT, C.MUNGER, C.DRUCKENMILLER):
            self.assertAlmostEqual(sum(cfg["weights"].values()), 1.0, places=6)


class RenderCollectTest(unittest.TestCase):
    def test_roundtrip(self):
        f, mk, card, rg = fixture_objects()
        llm = {"buffett": {"moat": "중", "capital_allocation": "우수", "accounting_quality_flags": [], "management_red_flags": [],
                           "verdict": "보류", "confidence": 0.6, "one_line": "성장은 확인, 해자는 숫자로 미증명"}}
        d, block = make_block(f, mk, card, rg, llm)
        self.assertIn("<!-- hub:guru:begin:000000 v1 -->", block)
        self.assertIn("<!-- hub:guru:end:000000 -->", block)
        self.assertNotIn("<sub>", block)
        parsed = collect.parse_block(block, "000000", "v1")
        self.assertEqual(parsed["fit"], d.consensus_fit)
        self.assertEqual(parsed["v"]["buffett"], "보류")
        self.assertEqual(parsed["name"], "가상A사")
        self.assertIn("해자 중", block)


class InjectTest(unittest.TestCase):
    SAMPLE = ("🚀 정밀 리서치 — 가상A사(000000)\n\n📌 한줄 결론: 테스트\n\n① 포착 신호\n- 현재가 25,000원\n\n"
              "<!-- hub:enrich:begin -->\n## 📐 실전 체크\n- 현재가 25,000원 (+1.0%) · 시총 5,000억 · 5일 +2.0% / 20일 +6.0% / 60일 +18.0%\n"
              "<!-- hub:enrich:end -->\n\n📋 결정카드\n판정: 관심\n진입: 24,000원\n손절: 22,000원\n목표: 1차 30,000원 (2차 34,000원)\n손익비: 1:3.0\n기간: 스윙\n촉매: 3Q\n반증: 없음\n")

    def test_idempotent_insert_before_card(self):
        f, mk, card, rg = fixture_objects()
        _, block = make_block(f, mk, card, rg)
        t1 = inject.inject_text(self.SAMPLE, "000000", block)
        self.assertEqual(t1.count("hub:guru:begin:000000"), 1)
        self.assertLess(t1.find("hub:guru:begin:000000"), t1.find("📋 결정카드"))
        self.assertGreater(t1.find("hub:guru:begin:000000"), t1.find("hub:enrich:end"))
        t2 = inject.inject_text(t1, "000000", block.replace("## 🧭", "## 🧭 ").replace("가상A사(000000)", "가상A사(000000)"))
        self.assertEqual(t2.count("hub:guru:begin:000000"), 1)
        self.assertEqual(t2.count("📋 결정카드"), 1)
        # 본문 불변
        self.assertTrue(t2.startswith(self.SAMPLE.split("<!-- hub:enrich")[0]))

    def test_parse_sample(self):
        tg = parse_report.find_targets(self.SAMPLE)
        self.assertEqual(tg[0][0], "000000")
        c = parse_report.card_for(self.SAMPLE, "000000", "000000")
        self.assertEqual(c.verdict_norm, "관심")
        self.assertEqual(c.rr1, 3.0)
        mk = parse_report.market_for(self.SAMPLE, "000000", "가상A사", "000000")
        self.assertEqual(mk.mcap, 5000)
        self.assertAlmostEqual(mk.ret60, 0.18)


@unittest.skipUnless(os.environ.get("GURU_TEST_REPO"), "GURU_TEST_REPO 미설정")
class RealRepoTest(unittest.TestCase):
    def test_parse_all_reports(self):
        repo = os.environ["GURU_TEST_REPO"]
        paths = sorted(glob.glob(os.path.join(repo, "2026*.md")))
        self.assertGreater(len(paths), 50)
        ok_code = ok_card = ok_mk = 0
        for p in paths:
            text = _read(p)
            tg = parse_report.find_targets(text, p)
            hhmmss = os.path.basename(p)[9:15]
            self.assertNotIn(hhmmss, [c for c, _ in tg], p)   # 파일명 시각이 코드로 잡히면 안 됨
            if tg:
                ok_code += 1
                code = tg[0][0]
                if parse_report.card_for(text, code, code):
                    ok_card += 1
                mk = parse_report.market_for(text, code, tg[0][1], code)
                if mk and mk.price:
                    ok_mk += 1
        self.assertGreaterEqual(ok_code / len(paths), 0.97)
        self.assertGreaterEqual(ok_card / len(paths), 0.85)
        self.assertGreaterEqual(ok_mk / len(paths), 0.85)

    def test_postprocess_on_copy(self):
        from guru import hub_postprocess
        repo = os.environ["GURU_TEST_REPO"]
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(os.path.join(repo, "index.html"), td)
            # 매수 섹션의 첫 리포트 하나를 복사해 블록 주입
            idx = _read(os.path.join(td, "index.html"))
            import re
            m = re.search(r'data-st="buy".*?href="\./([^"#]+)\.html(?:#card-(\d{6}))?"', idx, re.S)
            stem, code = m.group(1), m.group(2)
            shutil.copy(os.path.join(repo, stem + ".md"), td)
            shutil.copy(os.path.join(repo, stem + ".html"), td)
            text = _read(os.path.join(td, stem + ".md"))
            tg = parse_report.find_targets(text)
            code = code or tg[0][0]
            name = dict(tg).get(code, "")
            f, _, _, rg = fixture_objects()
            f.code, f.name = code, name
            mk = parse_report.market_for(text, code, name, tg[0][0])
            card = parse_report.card_for(text, code, tg[0][0])
            d, block = make_block(f, mk, card, rg)
            block = block.replace("000000", code).replace("가상A사", name)
            inject.inject_file(os.path.join(td, stem + ".md"), code, block)
            r1 = hub_postprocess.run(td)
            r2 = hub_postprocess.run(td)
            self.assertEqual(r1["index_cards"], 1)
            self.assertEqual(r2["index_cards"], 1)
            out = _read(os.path.join(td, "index.html"))
            self.assertEqual(out.count('class="tt guru-badge"'), 1)
            self.assertIn('data-f="guru:hi"', out)
            self.assertIn('href="./guru.html"', out)
            self.assertEqual(out.count('href="./guru.html"'), 1)
            self.assertEqual(out.count('data-f="guru:hi"'), 1)
            html = _read(os.path.join(td, stem + ".html"))
            self.assertEqual(html.count(f"<!--guru:html:begin:{code}-->"), 1)


if __name__ == "__main__":
    unittest.main()
