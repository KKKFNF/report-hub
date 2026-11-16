"""OpenDART 응답 형식 픽스처로 계정 매칭·TTM 합성 검증(네트워크 없음)."""
from __future__ import annotations

import unittest

from guru.data_dart import _combine_ttm, _match, _period_from_rows


def row(sj, aid, nm, this, add=None, frm=None, frm_add=None, rcept="20260814000001"):
    return {"sj_div": sj, "account_id": aid, "account_nm": nm, "thstrm_amount": this,
            "thstrm_add_amount": add, "frmtrm_amount": frm, "frmtrm_add_amount": frm_add, "rcept_no": rcept}


ANNUAL = [
    row("IS", "ifrs-full_Revenue", "매출액", "390,000,000,000"),
    row("IS", "-표준계정코드 미사용-", "매출총이익", "105,000,000,000"),
    row("IS", "dart_OperatingIncomeLoss", "영업이익(손실)", "45,000,000,000"),
    row("IS", "ifrs-full_ProfitLoss", "당기순이익(손실)", "35,000,000,000"),
    row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent", "지배기업의 소유주에게 귀속되는 당기순이익(손실)", "34,200,000,000"),
    row("IS", "-표준계정코드 미사용-", "이자비용", "1,600,000,000"),
    row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "50,000,000,000"),
    row("CF", "-표준계정코드 미사용-", "유형자산의 취득", "-20,000,000,000"),
    row("CF", "-표준계정코드 미사용-", "감가상각비", "15,000,000,000"),
    row("CF", "-표준계정코드 미사용-", "무형자산상각비", "2,000,000,000"),
    row("CF", "ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "배당금의 지급", "-9,000,000,000"),
    row("BS", "ifrs-full_Assets", "자산총계", "490,000,000,000"),
    row("BS", "ifrs-full_Liabilities", "부채총계", "170,000,000,000"),
    row("BS", "-표준계정코드 미사용-", "지배기업의 소유주에게 귀속되는 자본", "315,000,000,000"),
    row("BS", "ifrs-full_CurrentAssets", "유동자산", "230,000,000,000"),
    row("BS", "ifrs-full_CurrentLiabilities", "유동부채", "100,000,000,000"),
    row("BS", "ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "65,000,000,000"),
    row("BS", "ifrs-full_ShorttermBorrowings", "단기차입금", "8,000,000,000"),
    row("BS", "-표준계정코드 미사용-", "유동성장기부채", "4,000,000,000"),
    row("BS", "ifrs-full_LongtermBorrowings", "장기차입금", "28,000,000,000"),
    row("BS", "ifrs-full_PropertyPlantAndEquipment", "유형자산", "180,000,000,000"),
]
HALF = [  # 반기보고서: thstrm_add = 당해 누적, frmtrm_add = 전년 동기 누적
    row("IS", "ifrs-full_Revenue", "매출액", "110,000,000,000", "215,000,000,000", "100,000,000,000", "175,000,000,000"),
    row("IS", "dart_OperatingIncomeLoss", "영업이익(손실)", "14,000,000,000", "27,000,000,000", "10,000,000,000", "20,000,000,000"),
    row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent", "지배기업 소유주지분 순이익", "11,000,000,000", "21,000,000,000", "8,000,000,000", "16,000,000,000"),
    row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "", "30,000,000,000", "", "24,000,000,000"),
    row("CF", "-표준계정코드 미사용-", "유형자산의 취득", "", "-11,000,000,000", "", "-10,000,000,000"),
    row("BS", "ifrs-full_Assets", "자산총계", "520,000,000,000"),
    row("BS", "ifrs-full_Liabilities", "부채총계", "175,000,000,000"),
    row("BS", "-표준계정코드 미사용-", "지배기업의 소유주에게 귀속되는 자본", "340,000,000,000"),
    row("BS", "ifrs-full_CurrentAssets", "유동자산", "245,000,000,000"),
    row("BS", "ifrs-full_CurrentLiabilities", "유동부채", "105,000,000,000"),
    row("BS", "ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "72,000,000,000"),
]


class DartParseTest(unittest.TestCase):
    def test_annual_matching(self):
        p, matched = _period_from_rows("FY2025", ANNUAL, "thstrm_amount", "thstrm_amount", "20260323000001")
        self.assertEqual(p.revenue, 3900.0)
        self.assertEqual(p.gross_profit, 1050.0)      # 표준코드 미사용 → 계정명 매칭
        self.assertEqual(p.op, 450.0)
        self.assertEqual(p.ni_parent, 342.0)
        self.assertEqual(p.interest_exp, 16.0)
        self.assertEqual(p.capex, 200.0)              # 부호 반전(절대값)
        self.assertEqual(p.da, 170.0)
        self.assertEqual(p.dividends_paid, 90.0)
        self.assertEqual(p.equity_parent, 3150.0)
        self.assertEqual(p.st_debt, 120.0)
        self.assertEqual(p.lt_debt, 280.0)
        self.assertEqual(p.debt, 400.0)
        self.assertIn("gross_profit", matched)

    def test_ttm_synthesis(self):
        fy, _ = _period_from_rows("FY2025", ANNUAL, "thstrm_amount", "thstrm_amount")
        ytd_cur, _ = _period_from_rows("YTD", HALF, "thstrm_add_amount", "thstrm_amount")
        ytd_prev, _ = _period_from_rows("YTDprev", HALF, "frmtrm_add_amount", "frmtrm_amount")
        ttm = _combine_ttm("TTM(2Q26)", fy, ytd_cur, ytd_prev, ytd_cur)
        self.assertEqual(ttm.revenue, 3900 + 2150 - 1750)     # 4300
        self.assertEqual(ttm.op, 450 + 270 - 200)               # 520
        self.assertEqual(ttm.ni_parent, 342 + 210 - 160)        # 392
        self.assertEqual(ttm.cfo, 500 + 300 - 240)              # 560
        self.assertEqual(ttm.capex, 200 + 110 - 100)            # 210
        self.assertIsNone(ttm.interest_exp)                     # 반기에 이자비용 없음 → None (억지 합성 금지)
        self.assertEqual(ttm.total_assets, 5200.0)              # BS 는 최신 분기말
        self.assertEqual(ttm.equity_parent, 3400.0)

    def test_match_missing_returns_none(self):
        v, nm = _match(ANNUAL, "inventories", "thstrm_amount")
        self.assertIsNone(v)


if __name__ == "__main__":
    unittest.main()
