import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

# cp949 콘솔에서도 이모지/한글 print 로 죽지 않도록
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 무거운 상위 import 스텁 (import 시 네트워크/차트 로딩 방지)
_cp = types.ModuleType("chart_popup_v4")
_cp.build_chart_popup = lambda *a, **k: ""
sys.modules.setdefault("chart_popup_v4", _cp)

import make_index_total_top_etf_combined as mi


SENTINEL = "OLD_TICKER,999\n"
JSON_SENTINEL = '{"status":"OLD","targets":[]}'


def _item(ticker, name, is_kr, sco=12.0):
    return {
        "ticker": ticker, "name": name, "is_kr": is_kr, "intensity": False,
        "sco": sco, "chg": 1.0, "pos": "1", "idx_rel": 0.5,
    }


class RebalanceFileSafetyTests(unittest.TestCase):
    """레거시 주문파일(REBALANCING_TXT, HTML/legacy 용) 원자적 안전성."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.reb = Path(self._tmp.name) / "reb.txt"
        # 기존 파일 존재 상태(덮어쓰기 금지 검증용 sentinel)
        self.reb.write_text(SENTINEL, encoding="utf-8")
        self._old_reb = mi.REBALANCING_TXT
        self._old_asset = mi.ASSET_8042
        self._old_rate = mi.USD_KRW_EFFECTIVE
        mi.REBALANCING_TXT = self.reb
        mi.ASSET_8042 = 100_000_000
        mi.USD_KRW_EFFECTIVE = 1400.0

    def tearDown(self):
        mi.REBALANCING_TXT = self._old_reb
        mi.ASSET_8042 = self._old_asset
        mi.USD_KRW_EFFECTIVE = self._old_rate
        self._tmp.cleanup()

    def _content(self):
        return self.reb.read_text(encoding="utf-8") if self.reb.exists() else None

    # G-1: 정상 KR 1종목 → 원자적 교체
    def test_valid_kr_writes_atomic(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"final_ratios": {"069500": 30.0}}
        with patch.object(mi, "_get_kor_price", return_value=10000.0):
            mi.build_final_order_table(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertEqual(self._content(), "069500,3000")

    # G-2: 현재가 조회 실패 → 기존 파일 보존
    def test_price_fail_preserves_old(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"final_ratios": {"069500": 30.0}}
        with patch.object(mi, "_get_kor_price", return_value=None):
            mi.build_final_order_table(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertEqual(self._content(), SENTINEL)

    # G-3: 자산 조회 실패(ASSET<=0) → 기존 파일 보존
    def test_asset_fail_preserves_old(self):
        mi.ASSET_8042 = 0
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"final_ratios": {"069500": 30.0}}
        with patch.object(mi, "_get_kor_price", return_value=10000.0):
            mi.build_final_order_table(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertEqual(self._content(), SENTINEL)

    # G-4: 환율 조회 실패(rate None) → 기존 파일 보존
    def test_rate_fail_preserves_old(self):
        mi.USD_KRW_EFFECTIVE = None
        held = ["QQQ"]
        data = [_item("QQQ", "Invesco QQQ", False)]
        s_data = {"final_ratios": {"QQQ": 30.0}}
        with patch.object(mi, "_get_us_price", return_value=10.0):
            mi.build_final_order_table(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertEqual(self._content(), SENTINEL)

    # G-5: 보유목록 파일 없음(FILE_MISSING) → 기존 파일 보존
    def test_held_file_missing_preserves_old(self):
        mi.build_final_order_table([], [], {}, mi.HELD_FILE_MISSING, mi.STATS_OK)
        self.assertEqual(self._content(), SENTINEL)

    # G-5b: 통계 읽기 실패(READ_ERROR) → 기존 파일 보존
    def test_stats_read_error_preserves_old(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        with patch.object(mi, "_get_kor_price", return_value=10000.0):
            mi.build_final_order_table(held, data, {}, mi.HELD_OK, mi.STATS_READ_ERROR)
        self.assertEqual(self._content(), SENTINEL)

    # G-6: 정상 0종목(EMPTY_VALID) → 빈 파일로 청산 신호 기록
    def test_legit_empty_writes_empty_file(self):
        mi.build_final_order_table([], [], {}, mi.HELD_EMPTY_VALID, mi.STATS_OK)
        self.assertEqual(self._content(), "")

    # G-7: 보유 있으나 전 종목 정상 qty=0 → 의도된 청산(빈 파일)
    def test_all_qty_zero_writes_empty_file(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"final_ratios": {"069500": 0.0}}
        with patch.object(mi, "_get_kor_price", return_value=10000.0):
            mi.build_final_order_table(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertEqual(self._content(), "")

    # G-8: tmp 쓰기 실패 → 원본 손상 없이 보존
    def test_tmp_write_failure_preserves_old(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"final_ratios": {"069500": 30.0}}

        def boom(*a, **k):
            raise OSError("disk full")

        with patch.object(mi, "_get_kor_price", return_value=10000.0), \
             patch("pathlib.Path.write_text", side_effect=boom):
            mi.build_final_order_table(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertEqual(self._content(), SENTINEL)


class BuildTargetWeightsTests(unittest.TestCase):
    """(spec #5) 주문기(allone)용 '전략 비중' JSON 생성 — 절대수량 미포함.
    이 JSON 이 3계좌 공통 절대수량 소스를 대체한다."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.jf = Path(self._tmp.name) / "weights.json"
        self.jf.write_text(JSON_SENTINEL, encoding="utf-8")   # 덮어쓰기 금지 sentinel
        self._old = mi.TARGET_WEIGHTS_JSON
        mi.TARGET_WEIGHTS_JSON = self.jf

    def tearDown(self):
        mi.TARGET_WEIGHTS_JSON = self._old
        self._tmp.cleanup()

    def _content(self):
        return self.jf.read_text(encoding="utf-8") if self.jf.exists() else None

    # W-1: 정상 → status=OK, 절대수량 없이 비중만, Σtarget_pct≈invest_pct
    def test_valid_writes_weight_only_json(self):
        held = ["069500", "QQQ"]
        data = [_item("069500", "KODEX200", True), _item("QQQ", "Invesco QQQ", False)]
        s_data = {"invest_pct": 54.1, "final_ratios": {"069500": 30.0, "QQQ": 24.1}}
        ok = mi.build_target_weights(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertTrue(ok)
        payload = json.loads(self._content())
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["invest_pct"], 54.1)
        tks = {t["ticker"]: t for t in payload["targets"]}
        # 절대수량(qty) 키가 없어야 한다
        for t in payload["targets"]:
            self.assertNotIn("qty", t)
            self.assertIn("target_pct", t)
        self.assertEqual(tks["069500"]["target_pct"], 30.0)
        self.assertEqual(tks["069500"]["market"], "KR")
        self.assertEqual(tks["QQQ"]["market"], "US")
        self.assertAlmostEqual(payload["sum_target_pct"], 54.1, places=3)

    # W-2: 입력오류(held FILE_MISSING) → 기존 파일 보존
    def test_input_error_preserves(self):
        ok = mi.build_target_weights([], [], {}, mi.HELD_FILE_MISSING, mi.STATS_OK)
        self.assertFalse(ok)
        self.assertEqual(self._content(), JSON_SENTINEL)

    # W-2b: 통계 READ_ERROR → 기존 파일 보존
    def test_stats_error_preserves(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"invest_pct": 30.0, "final_ratios": {"069500": 30.0}}
        ok = mi.build_target_weights(held, data, s_data, mi.HELD_OK, mi.STATS_READ_ERROR)
        self.assertFalse(ok)
        self.assertEqual(self._content(), JSON_SENTINEL)

    # W-3: 정상 0종목(EMPTY_VALID) → status=EMPTY_TARGET 원자적 기록
    def test_empty_valid_writes_empty_target(self):
        ok = mi.build_target_weights([], [], {"invest_pct": 0}, mi.HELD_EMPTY_VALID, mi.STATS_OK)
        self.assertTrue(ok)
        payload = json.loads(self._content())
        self.assertEqual(payload["status"], "EMPTY_TARGET")
        self.assertEqual(payload["targets"], [])

    # W-4: Σtarget_pct 가 invest_pct 와 크게 어긋남 → fail-closed(보존)
    def test_sum_mismatch_preserves(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        # final_ratio 30% 인데 invest_pct 50% 로 선언 → 20%p 차이 > tolerance
        s_data = {"invest_pct": 50.0, "final_ratios": {"069500": 30.0}}
        ok = mi.build_target_weights(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertFalse(ok)
        self.assertEqual(self._content(), JSON_SENTINEL)

    # W-5: 음수 비중 감지 → fail-closed(보존)
    def test_negative_pct_preserves(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"invest_pct": 30.0, "final_ratios": {"069500": -5.0}}
        ok = mi.build_target_weights(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertFalse(ok)
        self.assertEqual(self._content(), JSON_SENTINEL)

    # W-6: tmp 쓰기 실패 → 원본 보존
    def test_tmp_write_failure_preserves(self):
        held = ["069500"]
        data = [_item("069500", "KODEX200", True)]
        s_data = {"invest_pct": 30.0, "final_ratios": {"069500": 30.0}}

        def boom(*a, **k):
            raise OSError("disk full")

        with patch("pathlib.Path.write_text", side_effect=boom):
            ok = mi.build_target_weights(held, data, s_data, mi.HELD_OK, mi.STATS_OK)
        self.assertFalse(ok)
        self.assertEqual(self._content(), JSON_SENTINEL)


class ReadStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_top6 = mi.TOP6_FILE
        self._old_stats = mi.STATS_FILE

    def tearDown(self):
        mi.TOP6_FILE = self._old_top6
        mi.STATS_FILE = self._old_stats
        self._tmp.cleanup()

    def test_held_file_missing(self):
        mi.TOP6_FILE = Path(self._tmp.name) / "nope.txt"
        status, rows = mi.read_held_list()
        self.assertEqual(status, mi.HELD_FILE_MISSING)
        self.assertEqual(rows, [])

    def test_held_empty_valid(self):
        p = Path(self._tmp.name) / "empty.txt"
        p.write_text("\n\n  \n", encoding="utf-8")
        mi.TOP6_FILE = p
        status, rows = mi.read_held_list()
        self.assertEqual(status, mi.HELD_EMPTY_VALID)
        self.assertEqual(rows, [])

    def test_held_ok(self):
        p = Path(self._tmp.name) / "ok.txt"
        p.write_text("069500\nQQQ\n", encoding="utf-8")
        mi.TOP6_FILE = p
        status, rows = mi.read_held_list()
        self.assertEqual(status, mi.HELD_OK)
        self.assertEqual(rows, ["069500", "QQQ"])

    def test_held_read_error(self):
        # 디렉터리를 파일처럼 읽으면 예외 → READ_ERROR
        d = Path(self._tmp.name) / "adir"
        d.mkdir()
        mi.TOP6_FILE = d
        status, rows = mi.read_held_list()
        self.assertEqual(status, mi.HELD_READ_ERROR)
        self.assertEqual(rows, [])

    def test_stats_missing(self):
        mi.STATS_FILE = Path(self._tmp.name) / "nope.json"
        status, data = mi.read_stats()
        self.assertEqual(status, mi.STATS_FILE_MISSING)
        self.assertEqual(data, {})

    def test_stats_read_error(self):
        p = Path(self._tmp.name) / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        mi.STATS_FILE = p
        status, data = mi.read_stats()
        self.assertEqual(status, mi.STATS_READ_ERROR)
        self.assertEqual(data, {})


if __name__ == "__main__":
    unittest.main()
