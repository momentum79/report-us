# make_index_total_top_etf_combined.py
# jasantop4_global_softcap.py 출력 기반 HTML 생성 (live flow)
#
# 입력 파일 (원본과 완전히 분리된 원본 경로):
#   - D:\py\0txt\total_top30.csv              : 통합 ETF 랭킹 CSV
#   - D:\py\buy_list_total.txt                : 최종 보유/매수 티커 목록
#   - D:\py\report-us\kr_signal_stats_total.json : 투자비중·통계 정보
#
# 출력:
#   - D:\py\report-us\total_etf_combined.html
#
# 원본(total_etf_combined.html)과 동일 구조,
# 랭킹 테이블에 Base_score / Stability / downside / MDD / VolSpike 컬럼 추가.

import csv
import io
import json
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

def _sco_dist_bars(rows, total=None, analyzed=None, title=""):
    head = ""
    if total is not None:
        a = f' / 분석 <b>{analyzed}</b>개' if analyzed is not None else ""
        head = (f'<div style="font-size:0.72rem;color:#777;margin:0 0 4px;">'
                f'전체 <b>{total}</b>개{a}</div>')
    bars = ""
    for label, cnt, pct, color in rows:
        try:
            w = max(float(str(pct).replace('%', '').strip()), 2)
        except (TypeError, ValueError):
            w = 2
        bars += (
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;font-size:0.78rem;">'
            f'<span style="width:60px;color:#555;flex-shrink:0;">{label}</span>'
            '<span style="flex:1;background:#eef0f1;border-radius:4px;height:11px;overflow:hidden;">'
            f'<span style="display:block;height:100%;border-radius:4px;width:{w}%;background:{color};"></span>'
            '</span>'
            f'<span style="width:96px;text-align:right;flex-shrink:0;color:#555;">{cnt}개 '
            f'<span style="color:#aaa;">({pct})</span></span>'
            '</div>'
        )
    t = (f'<div style="font-weight:bold;color:#000;font-size:0.9em;margin:0 0 4px;">{title}</div>'
         if title else "")
    return f'<div style="margin:0 0 10px;">{t}{head}{bars}</div>'


def _load_asset_8042() -> int:
    f = Path(__file__).resolve().parent / "asset_8042.json"
    try:
        if f.exists():
            val = int(json.loads(f.read_text(encoding="utf-8")).get("estimated_asset", 0))
            if val > 0:
                return val
    except Exception:
        pass
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fetch_asset_8042",
            str(Path(__file__).resolve().parent.parent / "fetch_asset_8042.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.fetch_and_save()
        if f.exists():
            return int(json.loads(f.read_text(encoding="utf-8")).get("estimated_asset", 0))
    except Exception:
        pass
    return 0

def _load_combined_asset_8042() -> tuple[int, float]:
    try:
        order_dir = Path(__file__).resolve().parent.parent / "0order"
        if str(order_dir) not in sys.path:
            sys.path.insert(0, str(order_dir))
        import allone_260712_ypykjw_fx as fx_order

        acct = next(a for a in fx_order.ACCOUNTS if a["label"] == "8042")
        token = fx_order.get_access_token(acct)
        if not token:
            raise RuntimeError("token issue failed")
        snap = fx_order.get_combined_asset_snapshot(token, "8042")
        raw_us = snap.get("raw_us") or {}
        # 9-9: USD 환율은 ust21120(crnc_rt) → ust31301(기준환율) 순으로만 확보한다.
        #      하드코딩 폴백(1450) 제거. 둘 다 실패하면 파일 생성을 중단한다.
        usd_rate = None
        for row in raw_us.get("result_list") or []:
            if row.get("crnc_code") == "USD":
                val = fx_order.as_decimal(row.get("crnc_rt"))
                if val and val > 0:
                    usd_rate = float(val)
                    break
        if usd_rate is None:
            try:
                r1 = fx_order.call_exchange_api(token, "ust31301", {"exch_tp": "1"})
                r2 = fx_order.call_exchange_api(token, "ust31301", {"exch_tp": "2"})
                base = fx_order.get_market_base_rate(r1, r2)
                if base and base > 0:
                    usd_rate = float(base)
            except Exception:
                usd_rate = None
        if usd_rate is None:
            raise RuntimeError("USD rate unavailable from ust21120/ust31301; stop rebalancing file generation")
        return int(snap["combined_total_krw"]), float(usd_rate)
    except Exception as e:
        raise RuntimeError(f"combined asset lookup failed; stop rebalancing file generation: {e}") from e

# 9-12: 모듈 임포트 시 네트워크/API 호출 금지. 실제 값은 main() 에서 채운다.
ASSET_8042 = 0
USD_KRW_EFFECTIVE = None

# 통합증거금 자산액은 API 조회로만 얻어지므로, 이 값을 쓰는 다른 스크립트(auto_trade_kpi 등)를
# 위해 파일로 남긴다. 여기가 유일한 writer.
COMBINED_ASSET_JSON = Path(__file__).resolve().parent / "asset_combined_8042.json"


def _save_combined_asset_snapshot() -> None:
    if not ASSET_8042 or ASSET_8042 <= 0:
        return
    payload = {
        "combined_asset_krw": int(ASSET_8042),
        "usd_krw": float(USD_KRW_EFFECTIVE) if USD_KRW_EFFECTIVE else None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = COMBINED_ASSET_JSON.with_suffix(COMBINED_ASSET_JSON.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(COMBINED_ASSET_JSON)
        print(f"[통합자산] 저장: {COMBINED_ASSET_JSON.name} ({ASSET_8042:,}원)")
    except Exception as e:
        print(f"[통합자산] 저장 실패(무시): {e}")
# YP(8042) 계좌 실잔고. make_holdings_json.py가 Kiwoom 잔고 API로 채운다.
# holdings/us_holdings 항목 중 tag=="통합ETF"인 것만 이 전략이 실제로 산 종목이다.
HOLDINGS_8042_JSON = Path(__file__).resolve().parent / "holdings_8042.json"


def _load_actual_8042_positions() -> dict:
    """holdings_8042.json에서 tag=='통합ETF'인 실제 보유수량을 티커별로 반환."""
    qty_map: dict[str, int] = {}
    if not HOLDINGS_8042_JSON.exists():
        return qty_map
    try:
        with open(HOLDINGS_8042_JSON, encoding="utf-8") as f:
            d = json.load(f)
        for row in d.get("holdings", []):
            if row.get("tag") == "통합ETF":
                code = str(row.get("stock_code", "")).strip()
                if code:
                    qty_map[code] = qty_map.get(code, 0) + int(row.get("quantity", 0))
        for row in d.get("us_holdings", []):
            if row.get("tag") == "통합ETF":
                tk = str(row.get("ticker", "")).strip()
                if tk:
                    qty_map[tk] = qty_map.get(tk, 0) + int(row.get("quantity", 0))
    except Exception as e:
        print(f"[연금(YP)실잔고] 읽기 실패(무시): {e}")
    return qty_map

def _get_kor_price(ticker: str) -> float | None:
    try:
        from pykrx import stock as krx
        today = date.today().strftime("%Y%m%d")
        df = krx.get_market_ohlcv_by_date(today, today, ticker)
        if df.empty:
            past = (date.today() - timedelta(days=3)).strftime("%Y%m%d")
            df = krx.get_market_ohlcv_by_date(past, today, ticker)
        if df.empty:
            return None
        return float(df["종가"].iloc[-1])
    except Exception as e:
        print(f"[현재가 오류] {ticker}: {e}")
        return None

# ── 미국 현재가 소스 ────────────────────────────────────────────────
#   1순위: 키움 usa20100 (yfinance 가 라이브 바를 OHLC 없이 NaN 으로 내려주는 문제 회피)
#          · 미국 정규장 중  → cur_prc(현재가)
#          · 정규장 아닐 때  → base_close_pric(전일종가)  ← 프리/애프터 저유동성 왜곡 회피
#   2순위: yfinance 폴백 (키움 토큰/네트워크 실패 시). 라이브 NaN 바는 dropna 로 제거.
#   둘 다 실패 → None → 호출부에서 '-' + order_build_failed (몰래 낡은 값 쓰지 않음).
_KW_US_TOKEN = None        # 지연 발급·프로세스 캐시
_KW_US_DISABLED = False    # 토큰/리졸버 실패 시 이후엔 바로 yfinance 폴백

def _us_regular_session() -> bool:
    """미국 정규장(평일 09:30~16:00 ET) 여부. DST 는 zoneinfo 가 자동 처리.
       판정 불가 시 False(=전일종가 사용)로 보수 처리."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return False
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 570 <= mins < 960  # 09:30 ~ 16:00

def _kiwoom_us_token():
    global _KW_US_TOKEN, _KW_US_DISABLED
    if _KW_US_DISABLED:
        return None
    if _KW_US_TOKEN:
        return _KW_US_TOKEN
    try:
        for d in (str(PROJECT_ROOT), str(PROJECT_ROOT / "0order")):
            if d not in sys.path:
                sys.path.insert(0, d)
        import allone_260712_ypykjw_fx as fx
        acct = next(a for a in fx.ACCOUNTS if a["label"] == "8042")
        tok = fx.get_access_token(acct)
        if not tok:
            raise RuntimeError("빈 토큰")
        _KW_US_TOKEN = tok
        return tok
    except Exception as e:
        print(f"[키움US] 토큰 실패 → yfinance 폴백: {e}")
        _KW_US_DISABLED = True
        return None

def _get_us_price_kiwoom(ticker: str) -> float | None:
    tok = _kiwoom_us_token()
    if not tok:
        return None
    try:
        import requests
        order_dir = str(PROJECT_ROOT / "0order")
        us_dir = str(PROJECT_ROOT / "0kiwoom_us")
        for d in (order_dir, us_dir):
            if d not in sys.path:
                sys.path.insert(0, d)
        import allone_260712_ypykjw_fx as fx
        from us_symbol_resolver import resolve_kiwoom_us_symbol
        stex_tp, stk_cd = resolve_kiwoom_us_symbol(ticker)
        headers = {
            "api-id": "usa20100",
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        payload = {"stex_tp": stex_tp, "stk_cd": stk_cd}
        fx._throttle_us()
        r = requests.post(fx.BASE_DOMAIN + fx.US_MARKET_URL,
                          headers=headers, data=json.dumps(payload), timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("return_code") not in (0, "0", None):
            return None
        field = "cur_prc" if _us_regular_session() else "base_close_pric"
        val = fx.as_decimal(str(data.get(field) or "").lstrip("+-"))
        # 정규장인데 cur_prc 가 비면 전일종가로 보정
        if (val is None or val <= 0) and field == "cur_prc":
            val = fx.as_decimal(str(data.get("base_close_pric") or "").lstrip("+-"))
        if val is None or val <= 0:
            return None
        return float(val)
    except Exception as e:
        print(f"[키움US 현재가 오류] {ticker}: {e}")
        return None

def _get_us_price(ticker: str) -> float | None:
    p = _get_us_price_kiwoom(ticker)
    if p and p > 0:
        return p
    # 폴백: yfinance (라이브 NaN 바 제거 후 마지막 유효 종가)
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty:
            return None
        close = hist["Close"].dropna()
        if close.empty:
            return None
        return float(close.iloc[-1])
    except Exception as e:
        print(f"[현재가 오류] {ticker}: {e}")
        return None

def _build_price_map(held_list: list, extra: list | None = None) -> dict:
    """보유 본주 + (있으면) 2x 주문 티커의 현재가. 2x도 본주와 같은 경로로 조회한다."""
    price_map = {}
    for tk in list(held_list) + list(extra or []):
        if tk in price_map:
            continue
        use_krx_price = classify_market(tk) == "KR"
        price_map[tk] = _get_kor_price(tk) if use_krx_price else _get_us_price(tk)
    return price_map


# ── F4_B_safe 2x 레버리지 주문 오버레이 ──────────
# Top6 선정·비중·점수·순위·연금은 본주 기준 그대로. 실제 주문 티커만 2x로 바뀐다.
def build_lev2_overlay(held_list: list) -> dict:
    """실패해도 전 종목 본주로 떨어지며 예외를 올리지 않는다."""
    empty = {"asof": "", "index": {}, "decisions": {},
             "orders": {t: t for t in held_list}, "swapped": [], "error": ""}
    if not held_list:
        return empty
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from lev2_order_overlay import resolve_lev2_orders
        return resolve_lev2_orders(held_list)
    except Exception as e:
        print(f"[2x오버레이] 실패 → 전 종목 본주 유지: {e}")
        empty["error"] = str(e)
        return empty


def _lev2_order_ticker(overlay: dict, tk: str) -> str:
    return (overlay or {}).get("orders", {}).get(tk, tk)


def apply_lev2_price_fallback(overlay: dict, price_map: dict) -> dict:
    """2x 현재가를 못 구하면 그 종목만 본주로 되돌린다.

    주문txt·비중JSON·HTML·스왑로그가 서로 다른 티커를 갖는 일을 막으려면
    되돌림이 overlay 자체에 반영돼야 한다."""
    if not overlay:
        return overlay
    for base, order_tk in list(overlay.get("orders", {}).items()):
        if order_tk == base:
            continue
        p = (price_map or {}).get(order_tk)
        if p and p > 0:
            continue
        print(f"[2x오버레이] {base}→{order_tk} 현재가 조회 실패 → 본주 fallback")
        overlay["orders"][base] = base
        row = overlay.get("decisions", {}).get(base)
        if row:
            row.update({
                "final_order_ticker": base,
                "final_order_market": row.get("base_market", ""),
                "is_lev2": False,
                "lev_reason": "",
                "fallback_reason": f"2x 현재가 조회 실패({order_tk})",
            })
        overlay["swapped"] = [d for d in overlay.get("swapped", []) if d.get("base") != base]
    return overlay

# ── 경로 설정 (live 원본 경로) ─────────────────
BASE         = Path(__file__).resolve().parent
PROJECT_ROOT = BASE.parent
import sys, re
sys.path.insert(0, str(BASE))
from chart_popup_v4 import build_chart_popup   # V4 내장형 일/주봉 인터랙티브 팝업 (US 셀 전용)

CSV_FILE         = PROJECT_ROOT / "0txt" / "total_top30.csv"
TOP6_FILE        = Path(r"D:\py\buy_list_total.txt")
STATS_FILE       = Path(r"D:\py\report-us\kr_signal_stats_total.json")
LOW_HISTORY_FILE = Path(r"D:\py\report-us\low_signal_history.json")
OUT_HTML         = BASE / "total_etf_combined.html"
REBALANCING_TXT  = Path(r"D:\py\0order\00_totaletf_korea_rebalancing.txt")

# 계좌별 목표수량 산출용 '전략 비중' 파일(절대수량 아님).
#   allone(주문기) 는 이 파일에서 종목·최종비중만 읽고, 각 계좌 통합총자산으로 목표수량을 자체 계산한다.
#   (기존 REBALANCING_TXT 는 8042 기준 HTML 표시/호환용으로만 유지한다.)
TARGET_WEIGHTS_JSON = Path(r"D:\py\0order\00_totaletf_target_weights.json")
# final_ratios 합계 vs invest_pct 허용오차(비중 반올림 정도). 초과 시 fail-closed(기존 파일 보존).
WEIGHTS_SUM_TOLERANCE_PCT = 1.0

# 보유목록/통계 읽기 상태값 (정상 공백 vs 입력오류 구분)
HELD_OK           = "OK"
HELD_EMPTY_VALID  = "EMPTY_VALID"    # 파일 존재+정상, 종목 0개(정상 100% 현금)
HELD_FILE_MISSING = "FILE_MISSING"   # 파일 자체가 없음(입력오류)
HELD_READ_ERROR   = "READ_ERROR"     # 읽기/파싱 예외(입력오류)
STATS_OK          = "OK"
STATS_FILE_MISSING = "FILE_MISSING"
STATS_READ_ERROR  = "READ_ERROR"

WEEKLY_TOP5_CSV  = BASE / "etf_history" / "weekly_top5_global.csv"
MONTHLY_TOP5_CSV = BASE / "etf_history" / "monthly_top5_global.csv"

FIXED_ONE_TICKERS = {
    'GLD', 'SLV', 'DBA', 'DBC', 'PDBC', 'UNG', 'REMX', 'PICK',
    'AGG', 'BND', 'TLT', 'IEF', 'LQD', 'HYG', 'XLE',
    '411060',
}

MEDALS_G = ["🥇", "🥈", "🥉", "④", "⑤"]

_KR_ETFS = [
    '091160', '091180', '305720', '117460', '244580', '091170',
    '102970', '117680', '117700', '139230', '228790', '495050',
    '069500', '229200', '487230', '449450', '475050', '371160',
    '455850', '0051G0', '0038A0', '0048K0', '0023A0', '195930',
    '377990', '411060', '478150', '453810', '446770', '434730',
    '469070', '449180', '449190', '241180', '147970', '325020',
]
_KR_NAMES = [
    '반도체', '자동차', '이차전', '에너지', '바이오', '은행주',
    '증권주', '철강주', '건설주', '조선주', '화장품', '밸류업',
    '코스피', '코스닥', '전력인', '방산주', 'K팝', '항셈테',
    '반소부', '에셈알', '미로봇', '중로봇', '양자컴', '유로스',
    '신재생', '금현물', '우주방', '인디아', '톱반도', '원자력',
    'ai로봇', '에센피', '나스닥', '니케이', '티모멘', '케모멘',
]
KR_TICKER_TO_NAME = dict(zip(_KR_ETFS, _KR_NAMES))
KR_NAME_TO_TICKER = {v: k for k, v in KR_TICKER_TO_NAME.items()}


def classify_market(ticker: str) -> str:
    code = str(ticker or "").strip().upper().lstrip("A")
    if code in KR_TICKER_TO_NAME:
        return "KR"
    if len(code) == 6 and code.isdigit():
        return "KR"
    # KRX 신형 6자리 영숫자 혼합 코드(0080Y0, 0100K0 …). 미국 티커는 숫자로 시작하지 않는다.
    if len(code) == 6 and code[0].isdigit() and code.isalnum():
        return "KR"
    return "US"


def _fmt_item(raw: str) -> str:
    import re
    raw = raw.strip()
    if not raw:
        return raw
    if re.search(r'\(.+\)$', raw):
        return raw
    if re.match(r'^\d{6}$', raw):
        name = KR_TICKER_TO_NAME.get(raw, raw)
        return f"{name}({raw})"
    ticker = KR_NAME_TO_TICKER.get(raw)
    if ticker:
        return f"{raw}({ticker})"
    return raw


def _parse_top5_entry_global(entry: str) -> list:
    lines = [_fmt_item(l) for l in entry.strip().splitlines() if l.strip()]
    return lines[:5]


def get_weekly_top5_global():
    if not WEEKLY_TOP5_CSV.exists():
        return ("", [])
    try:
        import re
        text = WEEKLY_TOP5_CSV.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        # 2행1쌍(라벨행/데이터행) 블록들 → 모든 주 컬럼을 시간순(오래된→최신)으로 수집.
        #   블록은 '최신월이 맨 위'로 저장되므로 블록을 역순 순회하고,
        #   블록 내부는 좌→우(1주→5주)가 시간순이라 그대로 이어붙인다.
        #   → 월초 첫 월요일처럼 '지난주'가 다른(전월) 블록에 있어도 정확히 잡힘.
        blocks = []  # 위(최신월)→아래(오래된월) 순서의 블록 리스트
        for i in range(0, len(rows) - 1, 2):
            labels = [c.strip() for c in rows[i]]
            data   = list(rows[i + 1])
            pairs  = [(lab, data[j]) for j, lab in enumerate(labels)
                      if lab and j < len(data) and data[j].strip()]
            blocks.append(pairs)
        # 블록 역순(오래된 월 먼저) + 블록내 좌→우(1주→5주) = 전체 시간순
        flat = [p for block in reversed(blocks) for p in block]
        if not flat:
            return ("", [])
        # 월요일: 이번 주 집계는 오늘(월) 하루뿐이라 '당일'과 똑같음 →
        #         지난주(완성된 한 주) 집계를 대신 보여준다. 화요일부터 이번 주.
        idx = -1
        if date.today().weekday() == 0 and len(flat) >= 2:
            idx = -2
        label_raw, entry = flat[idx]
        label = re.sub(r'^\d{4}\.', '', label_raw)
        return (label, _parse_top5_entry_global(entry))
    except Exception as e:
        print(f"[Global 주간 Top5 파싱 오류] {e}")
        return ("", [])


def get_monthly_top5_global():
    if not MONTHLY_TOP5_CSV.exists():
        return ("", [])
    try:
        today = date.today()
        # 그 달 1주차(1~7일)엔 이번 달 집계가 아직 하루~며칠뿐이라 주간 카드와 겹침 →
        #   지난달(완성된 한 달)을 대신 보여준다. 2주차(8일~)부터 이번 달.
        if today.day <= 7:
            ref = today.replace(day=1) - timedelta(days=1)   # 지난달의 말일
        else:
            ref = today
        target_key = f"{ref.year}.{ref.month:02d}"
        text = MONTHLY_TOP5_CSV.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        i = 0
        while i < len(rows):
            header_row = rows[i]
            data_row   = rows[i + 1] if i + 1 < len(rows) else []
            headers = [c.strip() for c in header_row]
            for j, hdr in enumerate(headers):
                if hdr == target_key and j < len(data_row):
                    entry = data_row[j].strip()
                    if entry:
                        label = f"{ref.month}월"
                        return (label, _parse_top5_entry_global(entry))
            i += 2
        return ("", [])
    except Exception as e:
        print(f"[Global 월간 Top5 파싱 오류] {e}")
        return ("", [])


def get_daily_top5_global(held_list: list, name_map: dict = None) -> list:
    result = []
    for tk in held_list[:5]:
        name = (name_map or {}).get(tk)
        if not name:
            name = KR_TICKER_TO_NAME.get(tk)
        if name and name != tk:
            result.append(f"{name}  {tk}")
        else:
            result.append(tk)
    return result


def _top5_mini_card_global(title: str, label: str, items: list,
                            border_color: str, bg_color: str = "#ffffff") -> str:
    if not items:
        body = '<div class="t5-empty">데이터 없음</div>'
    else:
        body = ""
        for i, item in enumerate(items[:5]):
            medal = MEDALS_G[i] if i < len(MEDALS_G) else f"#{i+1}"
            body += (
                f'<div class="t5-row">'
                f'<span class="t5-medal">{medal}</span>'
                f'<span class="t5-name">{item.strip()}</span>'
                f'</div>'
            )
    label_html = f'<span class="t5-label">{label}</span>' if label else ""
    return (
        f'<div class="t5-card" style="border-top:3px solid {border_color};background:{bg_color};">'
        f'<div class="t5-header" style="background:{bg_color};">'
        f'<span class="t5-title">{title}</span>{label_html}'
        f'</div>'
        f'<div class="t5-body">{body}</div>'
        f'</div>'
    )


def build_top5_section_global(held_list: list, data: list = None) -> str:
    today = date.today()
    import re as _re
    name_map = {}
    for item in (data or []):
        clean = _re.sub(r'\([A-Za-z0-9x\-]{4}\)$', '', item["name"]).strip()
        name_map[item["ticker"]] = clean

    daily_label  = f"{today.month}/{today.day}"
    daily_items  = get_daily_top5_global(held_list, name_map)
    weekly_label,  weekly_items  = get_weekly_top5_global()
    monthly_label, monthly_items = get_monthly_top5_global()

    daily_card   = _top5_mini_card_global("📅 당일",  daily_label,   daily_items,   "#3498db", "#e8f5e9")
    weekly_card  = _top5_mini_card_global("📆 주간",  weekly_label,  weekly_items,  "#27ae60", "#dfffff")
    monthly_card = _top5_mini_card_global("📊 월간",  monthly_label, monthly_items, "#e67e22", "#ffffdf")

    return (
        '<div class="t5-section">'
        '<div class="t5-section-title">🧾 당일/주간/월간 Top5</div>'
        '<div class="t5-cards-row">'
        + daily_card + weekly_card + monthly_card +
        '</div></div>'
    )


def read_held_list() -> tuple:
    """(status, list) 반환. 파일없음/읽기실패(입력오류)와 정상 빈목록을 구분한다."""
    if not TOP6_FILE.exists():
        print(f"[경고] 보유목록 파일 없음: {TOP6_FILE}")
        return HELD_FILE_MISSING, []
    try:
        tickers = TOP6_FILE.read_text(encoding="utf-8").splitlines()
        cleaned = [t.strip() for t in tickers if t.strip()]
    except Exception as e:
        print(f"[경고] 보유목록 읽기 실패: {e}")
        return HELD_READ_ERROR, []
    if not cleaned:
        return HELD_EMPTY_VALID, []
    return HELD_OK, cleaned


def read_stats() -> tuple:
    """(status, dict) 반환. 파일없음/읽기실패(입력오류)를 정상과 구분한다."""
    if not STATS_FILE.exists():
        print(f"[경고] 통계 JSON 파일 없음: {STATS_FILE}")
        return STATS_FILE_MISSING, {}
    try:
        return STATS_OK, json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[경고] 통계 JSON 읽기 실패: {e}")
        return STATS_READ_ERROR, {}


def load_low_history() -> dict:
    if not LOW_HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(LOW_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[경고] 저점 이력 JSON 읽기 실패: {e}")
        return {}


def update_low_history(data: list) -> dict:
    today     = datetime.now().date()
    today_str = today.isoformat()
    history   = load_low_history()

    to_delete = []
    for ticker, rec in history.items():
        try:
            first_date   = datetime.fromisoformat(rec["first_date"]).date()
            if (today - first_date).days > 7:
                to_delete.append(ticker)
        except Exception:
            to_delete.append(ticker)
    for ticker in to_delete:
        del history[ticker]

    for item in data:
        ticker   = item["ticker"]
        jeo      = item.get("jeo", "-")
        jeo2     = item.get("jeo2", "-")
        new_jeo  = (jeo  != "-" and str(jeo).strip()  not in ("", "-", "0", "nan"))
        new_jeo2 = (jeo2 != "-" and str(jeo2).strip() not in ("", "-", "0", "nan"))
        has_signal = new_jeo or new_jeo2

        if has_signal:
            if ticker in history:
                rec = history[ticker]
                if new_jeo != rec.get("signal_jeo", False) or new_jeo2 != rec.get("signal_jeo2", False):
                    history[ticker] = {"first_date": today_str, "signal_jeo": new_jeo, "signal_jeo2": new_jeo2}
            else:
                history[ticker] = {"first_date": today_str, "signal_jeo": new_jeo, "signal_jeo2": new_jeo2}

    LOW_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history


def get_low_badge(ticker: str, history: dict) -> str:
    if ticker not in history:
        return ""
    rec = history[ticker]
    try:
        first_date   = datetime.fromisoformat(rec["first_date"]).date()
        days_elapsed = (datetime.now().date() - first_date).days
    except Exception:
        return ""

    if days_elapsed == 0:
        sig_jeo  = rec.get("signal_jeo",  False)
        sig_jeo2 = rec.get("signal_jeo2", False)
        if sig_jeo and sig_jeo2:
            return '<span class="low-badge low-both">저1,2</span>'
        elif sig_jeo:
            return '<span class="low-badge low-jeo">저</span>'
        elif sig_jeo2:
            return '<span class="low-badge low-jeo2">저2</span>'
    elif 1 <= days_elapsed <= 5:
        return f'<span class="low-badge low-track">{days_elapsed}저</span>'
    return ""


def char_to_rank(c: str):
    if c in ('x', '-'):
        return None
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return 10 + (ord(c.upper()) - ord('A'))
    return None


def is_rank_rising(name: str) -> bool:
    import re
    m = re.search(r'\(([A-Za-z0-9x\-]{4})\)$', name)
    if not m:
        return False
    code = m.group(1)
    ranks = [char_to_rank(c) for c in code]
    if any(r is None for r in ranks):
        return False
    today, d1, d2, d3 = ranks
    if today <= 3:
        return True
    top3days_all_in_top5 = (today <= 5 and d1 <= 5 and d2 <= 5)
    for cur, prev in [(today, d1), (d1, d2), (d2, d3)]:
        if cur <= prev:
            continue
        if top3days_all_in_top5:
            continue
        return False
    return True


def build_name_cell(item: dict) -> str:
    import re
    name = item["name"]
    rising = is_rank_rising(name)
    color = "#e74c3c" if rising else "#2c3e50"

    if not item["is_kr"]:
        m = re.search(r'\(([A-Za-z0-9x\-]{4})\)$', name)
        display = m.group(1) if m else name
    else:
        display = name

    if rising:
        display = display + "★"

    if item["is_kr"]:
        # 한국종목: 종목명 셀에 차트 hover 트리거 부여 (티커 대신 종목명 hover)
        tk = item["ticker"]
        dn = str(name).replace('"', "&quot;")
        return (f'<td class="name-col chart-trigger" data-v4-code="{tk}" data-v4-market="KR" '
                f'data-name="{dn}" style="color:{color};cursor:pointer;">{display}</td>')
    return f'<td class="name-col" style="color:{color}">{display}</td>'


def read_data() -> list:
    if not CSV_FILE.exists():
        print(f"[경고] CSV 파일 없음: {CSV_FILE}")
        return []
    data = []
    try:
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_ticker = str(row.get("티커", "")).strip()
                if not raw_ticker:
                    continue
                is_intensity = "**" in raw_ticker
                ticker = raw_ticker.replace("**", "")
                is_kr      = classify_market(ticker) == "KR"
                rtn_raw    = row.get("수익률(%)") or row.get("3M(%)", "0")
                rtn1m_raw  = row.get("수익률20(%)", "")
                sco_raw    = row.get("Signal_sco") or row.get("score", "0")
                score_raw  = row.get("Final_score") or row.get("Score", "0")
                base_raw   = row.get("Base_score", "")
                stab_raw   = row.get("Stability_score", "")
                down_raw   = row.get("downside_vol63", "")
                mdd_raw    = row.get("mdd126", "")
                spike_raw  = row.get("vol_spike", "")
                name_raw   = row.get("산업") or row.get("종목명", "")
                chg_raw    = row.get("당일등락률(%)") or row.get("등락률(%)") or row.get("등락", "")
                pos_raw    = row.get("위치", "")
                jeo_raw    = row.get("저", "-")
                jeo2_raw   = row.get("저2", "-")
                inv3_raw   = row.get("inv3", "0")
                rsi_raw    = row.get("RSI_str", "-")
                idx_rel_raw = row.get("지수대비(%)", "")
                fire_raw   = row.get("fire", "0")
                trend_raw  = row.get("추세", "")
                avg136_raw = row.get("평균136", "")

                def _f(v):
                    try: return float(v)
                    except: return None

                data.append({
                    "ticker":      ticker,
                    "name":        name_raw.strip(),
                    "rtn":         _f(rtn_raw) or 0.0,
                    "rtn1m":       _f(rtn1m_raw),
                    "sco":         _f(sco_raw) or 0.0,
                    "score_final": _f(score_raw) or 0.0,
                    "base_score":  _f(base_raw),
                    "stability":   _f(stab_raw),
                    "downside_vol":_f(down_raw),
                    "mdd126":      _f(mdd_raw),
                    "vol_spike":   _f(spike_raw),
                    "chg":         _f(chg_raw),
                    "pos":         str(pos_raw).strip(),
                    "jeo":         str(jeo_raw).strip(),
                    "jeo2":        str(jeo2_raw).strip(),
                    "inv3":        int(inv3_raw) if str(inv3_raw).strip() in ("0","1") else 0,
                    "fire":        int(fire_raw) if str(fire_raw).strip() in ("0","1") else 0,
                    "idx_rel":     _f(idx_rel_raw),
                    "rsi":         str(rsi_raw).strip(),
                    "trend":       str(trend_raw).strip(),
                    "avg136":      _f(avg136_raw),
                    "type":        "KR" if is_kr else "US",
                    "is_kr":       is_kr,
                    "intensity":   is_intensity,
                })
    except Exception as e:
        print(f"[오류] CSV 읽기 실패: {e}")
    return data


def get_mult_type(ticker: str, is_kr: bool) -> str:
    if is_kr:
        return "KOSPI"
    if ticker.upper() in FIXED_ONE_TICKERS:
        return "FIXED"
    return "NASDAQ"


def _atomic_write_rebalancing(rows: list) -> bool:
    """rebalancing 파일을 tmp+replace 로 원자적 교체. 빈 리스트면 빈 파일(청산 신호).
    실패 시 tmp 정리 후 False (기존 파일은 그대로 보존됨)."""
    tmp_path = REBALANCING_TXT.with_suffix(REBALANCING_TXT.suffix + ".tmp")
    try:
        tmp_path.write_text("\n".join(rows), encoding="utf-8")
        tmp_path.replace(REBALANCING_TXT)
        print(f"[리밸런싱] 저장: {REBALANCING_TXT} ({len(rows)}개)"
              + (" ← 빈 파일(청산 모드)" if not rows else ""))
        return True
    except Exception as e:
        print(f"[리밸런싱 저장 실패] {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def _compute_alloc_pct(held_list: list, data: list, s_data: dict) -> dict:
    """보유 종목별 '최종 비중(%)' 계산.
    - final_ratios(전체자산 대비 최종 비중)가 있으면 그대로 사용.
    - 없으면 internal_weights × (시장별 multiplier) 로 재구성.
    반환값의 합계는 invest_pct 와 근사해야 한다(호출측에서 검증)."""
    data_map         = {item["ticker"]: item for item in data}
    internal_weights = s_data.get("internal_weights", [])
    final_ratios     = s_data.get("final_ratios", {})
    k_mult           = s_data.get("kospi_mult", 0)
    us_mult          = s_data.get("nasdaq_mult", 0)

    alloc_pct = {}
    for i, tk in enumerate(held_list):
        if final_ratios and tk in final_ratios:
            alloc_pct[tk] = final_ratios[tk]
        else:
            w     = internal_weights[i] / 100.0 if i < len(internal_weights) else 0
            item  = data_map.get(tk, {})
            mtype = get_mult_type(tk, item.get("is_kr", classify_market(tk) == "KR"))
            if   mtype == "KOSPI":  mult = float(k_mult) if k_mult != "-" else 0.0
            elif mtype == "FIXED":  mult = 1.0
            else:                   mult = float(us_mult) if us_mult != "-" else 0.0
            alloc_pct[tk] = w * mult * 100
    return alloc_pct


def _atomic_write_target_weights(payload: dict) -> bool:
    """전략 비중 JSON 을 tmp+replace 로 원자적 교체.
    실패 시 tmp 정리 후 False (기존 파일은 그대로 보존됨). 절대수량은 담지 않는다."""
    tmp_path = TARGET_WEIGHTS_JSON.with_suffix(TARGET_WEIGHTS_JSON.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(TARGET_WEIGHTS_JSON)
        print(f"[목표비중] 저장: {TARGET_WEIGHTS_JSON} "
              f"(status={payload.get('status')}, targets={len(payload.get('targets', []))})")
        return True
    except Exception as e:
        print(f"[목표비중 저장 실패] {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return False


def build_target_weights(held_list: list, data: list, s_data: dict,
                         held_status: str = HELD_OK,
                         stats_status: str = STATS_OK,
                         price_map: dict | None = None,
                         lev_overlay: dict | None = None) -> bool:
    """주문기(allone)용 '전략 비중' JSON 생성. 절대수량은 담지 않는다.
    - 입력오류(보유목록/통계 파일 없음/읽기오류) → 기존 파일 보존(미갱신).
    - 정상 보유 0개(EMPTY_VALID/빈 목록) → status=EMPTY_TARGET 원자적 기록(청산 신호).
    - 정상 → targets=[{market,ticker,target_pct}] 기록. 단 Σtarget_pct 가 invest_pct 와
      허용오차(WEIGHTS_SUM_TOLERANCE_PCT) 초과로 어긋나면 fail-closed(기존 파일 보존)."""
    input_error = (
        held_status in (HELD_FILE_MISSING, HELD_READ_ERROR)
        or stats_status in (STATS_FILE_MISSING, STATS_READ_ERROR)
    )
    if input_error:
        print(f"[목표비중] 입력 오류 → 기존 파일 유지(미갱신). "
              f"held={held_status}, stats={stats_status}")
        return False

    if held_status == HELD_EMPTY_VALID or not held_list:
        return _atomic_write_target_weights({
            "status": "EMPTY_TARGET",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "invest_pct": float(s_data.get("invest_pct", 0) or 0),
            "targets": [],
        })

    invest_pct = float(s_data.get("invest_pct", 0) or 0)
    alloc_pct  = _compute_alloc_pct(held_list, data, s_data)
    price_map = price_map or {}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    targets = []
    for tk in held_list:
        pct = float(alloc_pct.get(tk, 0) or 0)
        if pct < 0:
            print(f"[목표비중] 음수 비중 감지({tk}={pct}) → 기존 파일 보존")
            return False
        # 비중(target_pct)은 본주 기준 그대로. 주문 티커만 2x로 바뀐다.
        order_tk = _lev2_order_ticker(lev_overlay, tk)
        target = {
            "market": classify_market(order_tk),   # 'KR' | 'US'
            "ticker": order_tk,
            "target_pct": round(pct, 4),
        }
        if order_tk != tk:
            target["base_ticker"] = tk
            target["is_lev2"] = True
        ref_price = price_map.get(order_tk)
        if ref_price and ref_price > 0:
            target["ref_price"] = round(float(ref_price), 6)
            target["ref_price_source"] = "generated_close"
            target["ref_price_time"] = generated_at
        targets.append(target)

    sum_pct = round(sum(t["target_pct"] for t in targets), 4)
    if invest_pct > 0 and abs(sum_pct - invest_pct) > WEIGHTS_SUM_TOLERANCE_PCT:
        print(f"[목표비중] 합계 불일치 → fail-closed(기존 파일 보존). "
              f"Σtarget_pct={sum_pct} vs invest_pct={invest_pct} "
              f"(허용오차 {WEIGHTS_SUM_TOLERANCE_PCT})")
        return False

    return _atomic_write_target_weights({
        "status": "OK",
        "generated_at": generated_at,
        "invest_pct": invest_pct,
        "sum_target_pct": sum_pct,
        "targets": targets,
    })


def build_final_order_table(held_list: list, data: list, s_data: dict,
                            held_status: str = HELD_OK,
                            stats_status: str = STATS_OK,
                            price_map: dict | None = None,
                            lev_overlay: dict | None = None,
                            qty_out: dict | None = None) -> str:
    # ── 입력 오류 판정: 하나라도 걸리면 기존 파일 절대 덮어쓰지 않음 ──
    input_error = (
        held_status in (HELD_FILE_MISSING, HELD_READ_ERROR)
        or stats_status in (STATS_FILE_MISSING, STATS_READ_ERROR)
        or ASSET_8042 is None or ASSET_8042 <= 0
        or USD_KRW_EFFECTIVE is None
    )
    if input_error:
        print(f"[리밸런싱] 입력 오류 → 기존 파일 유지(덮어쓰기 안 함). "
              f"held={held_status}, stats={stats_status}, "
              f"asset={ASSET_8042}, rate={USD_KRW_EFFECTIVE}")
        if not held_list:
            return '<p style="color:#e74c3c;">보유목록/자산 조회 실패 → 리밸런싱 파일 미갱신</p>'
        # 오류지만 목록은 있음 → 아래 표는 그려주되 파일은 건드리지 않음(order_build_failed 강제)

    # 정상적으로 보유 0개(EMPTY_VALID) → 청산 신호로 빈 파일 원자적 교체
    if not input_error and (held_status == HELD_EMPTY_VALID or not held_list):
        _atomic_write_rebalancing([])
        return '<p style="color:#7f8c8d;">보유 종목 없음 (현금 100%) → 청산 신호 기록</p>'

    if not held_list:
        # 여기 도달 = input_error True + 빈 목록 (위에서 이미 반환됨) 이므로 방어적 처리
        return '<p style="color:#7f8c8d;">보유 종목 없음</p>'

    data_map  = {item["ticker"]: item for item in data}
    alloc_pct = _compute_alloc_pct(held_list, data, s_data)

    if price_map is None:
        price_map = _build_price_map(held_list)

    rows_html = []
    rebalancing_rows = []
    lev_qty_map = qty_out if qty_out is not None else {}
    actual_8042_qty = _load_actual_8042_positions()
    # 입력오류(자산/환율/파일)면 표는 그리되 파일은 절대 안 씀
    order_build_failed = bool(input_error)
    failed_tickers = []
    for tk in held_list:
        item = data_map.get(tk)
        if item is None:
            rows_html.append(
                f'<tr><td class="narrow held-bold">{tk}</td>'
                f'<td colspan="11" style="color:#999;">데이터 없음</td></tr>'
            )
            order_build_failed = True
            failed_tickers.append(tk)
            continue

        chg = item.get("chg")
        chg_str = f"{chg:+.1f}%" if chg is not None else "-"
        chg_cls = ("sig-up" if chg and chg > 0 else ("sig-down" if chg and chg < 0 else ""))

        pos_str = item.get("pos", "-")
        pos_html = (f'<span class="pos-badge pos-{pos_str}">{pos_str}</span>'
                    if pos_str in ("1","2","3","4","5") else pos_str or "-")

        sco_str = f"{item['sco']:.1f}"
        pct_val = alloc_pct.get(tk, 0)
        pct_color = "#27ae60" if pct_val >= 25 else ("#e67e22" if pct_val >= 15 else "#e74c3c")

        alloc_map    = s_data.get("allocation_map_used", [])
        tk_index     = list(held_list).index(tk) if tk in held_list else -1
        base_pct_val = alloc_map[tk_index] if (alloc_map and 0 <= tk_index < len(alloc_map)) else None

        if base_pct_val is not None and abs(pct_val - float(base_pct_val)) >= 0.1:
            pct_display = (
                f'{pct_val:.1f}% '
                f'<span style="color:#aaa;font-size:0.82em;font-weight:normal;">({base_pct_val}%)</span>'
            )
        else:
            pct_display = f'{pct_val:.1f}%'

        idx_rel = item.get("idx_rel")
        idx_rel_str = f"{idx_rel:+.1f}%" if idx_rel is not None else "-"
        idx_rel_cls = ("sig-up" if idx_rel and idx_rel > 0 else ("sig-down" if idx_rel and idx_rel < 0 else ""))

        ticker_display = tk + ("**" if item.get("intensity") else "")
        use_krx_price = classify_market(tk) == "KR"
        is_kr = item.get("is_kr", use_krx_price)
        price = price_map.get(tk)
        pct_for_qty = alloc_pct.get(tk, 0)

        # 2x 치환 여부. 일반 주문만 2x 가격 기준, 연금은 항상 본주 기준.
        order_tk = _lev2_order_ticker(lev_overlay, tk)
        is_lev2 = (order_tk != tk)
        order_price = price_map.get(order_tk) if is_lev2 else price
        order_is_kr = classify_market(order_tk) == "KR"
        if is_lev2 and not (order_price and order_price > 0):
            # 2x 현재가 조회 실패 → 본주로 되돌린다(주문 누락보다 안전)
            print(f"[2x오버레이] {tk}→{order_tk} 현재가 조회 실패 → 본주 fallback")
            order_tk, is_lev2 = tk, False
            order_price, order_is_kr = price, use_krx_price

        # 입력오류(자산/환율 등)면 수량계산 자체를 건너뛴다(None 환율 나눗셈 방지, 어차피 파일 미기록)
        need_qty = (not input_error and ASSET_8042 > 0 and pct_for_qty > 0)
        if need_qty and price and price > 0 and order_price and order_price > 0:
            # 일반 주문 = 실제 주문 티커(2x일 수 있음) 가격 기준
            if order_is_kr:
                qty = int(ASSET_8042 * pct_for_qty / 100 / order_price)
                qty_krw = qty * order_price
            else:
                qty = int(ASSET_8042 * pct_for_qty / 100 / USD_KRW_EFFECTIVE / order_price)
                qty_krw = qty * order_price * USD_KRW_EFFECTIVE
            qty_disp     = f'{qty:,}주' if qty > 0 else '-'
            qty_amt_disp = f'{int(qty_krw / 10000):,}만원' if qty > 0 else '-'
            if qty > 0:
                rebalancing_rows.append(f"{order_tk},{qty}")
                lev_qty_map[tk] = (qty, int(qty_krw))
        else:
            qty_disp = qty_amt_disp = '-'
            if need_qty:
                # 9-11: 수량 산출이 필요한 종목인데 현재가 조회 실패 → 전체 파일 생성 중단
                order_build_failed = True
                failed_tickers.append(tk)

        # 연금 = YP(8042) 계좌 실잔고(holdings_8042.json, tag=="통합ETF"). 목표수량 계산과
        # 무관하게 실제 산 수량을 그대로 보여준다(2x 대체와 무관 → 항상 본주 티커 기준).
        pension_qty = actual_8042_qty.get(tk, 0)
        if pension_qty > 0 and price and price > 0:
            pension_krw = pension_qty * price if use_krx_price else pension_qty * price * USD_KRW_EFFECTIVE
            pension_qty_disp = f'{pension_qty:,}주'
            pension_amt_disp = f'{int(pension_krw / 10000):,}만원'
        else:
            pension_qty_disp = pension_amt_disp = '-'

        if is_kr:
            # 한국종목: 티커 대신 종목명에 hover → 차트 (트리거 attr을 종목명 셀로 이동)
            order_ticker_td = f'<td class="narrow held-bold" data-code="{tk}">{ticker_display}</td>'
            order_name_td = (f'<td class="name-col held-bold chart-trigger" data-v4-code="{tk}" '
                             f'data-v4-market="KR" data-name="{item["name"].replace(chr(34), "&quot;")}" '
                             f'style="cursor:pointer;">{item["name"]}</td>')
        else:
            order_ticker_td = f'<td class="narrow held-bold chart-trigger" data-ticker="{tk}" data-v4-code="{tk}" data-v4-market="US" style="cursor:pointer;">{ticker_display}</td>'
            order_name_td = f'<td class="name-col held-bold">{item["name"]}</td>'

        if is_lev2:
            lev_td = (f'<td class="narrow chart-trigger" data-v4-code="{order_tk}" '
                      f'data-v4-market="{"KR" if order_is_kr else "US"}" '
                      f'style="cursor:pointer;font-weight:bold;color:#c0392b;">{order_tk}</td>')
        else:
            lev_td = '<td></td>'

        rows_html.append(
            f'<tr>'
            + order_ticker_td
            + order_name_td +
            f'<td class="{chg_cls}">{chg_str}</td>'
            f'<td>{pos_html}</td>'
            f'<td>{sco_str}</td>'
            f'<td style="color:{pct_color};font-weight:bold;">{pct_display}</td>'
            f'<td class="{idx_rel_cls}">{idx_rel_str}</td>'
            + lev_td +
            f'<td style="font-weight:bold;">{qty_disp}</td>'
            f'<td class="pc-only" style="color:#555;">{qty_amt_disp}</td>'
            f'<td style="font-weight:bold;color:#8e44ad;">{pension_qty_disp}</td>'
            f'<td class="pc-only" style="color:#8e44ad;">{pension_amt_disp}</td>'
            f'</tr>'
        )

    # 오류(자산/환율/데이터/현재가)면 기존 파일 보존.
    # 오류가 없으면 산출행이 비어도(전 종목 정상 qty=0) 빈 파일로 교체 = 의도된 청산.
    if order_build_failed:
        print(f"[리밸런싱] 산출 중 오류 → 기존 파일 유지(덮어쓰기 안 함). "
              f"실패티커={failed_tickers}, 산출행={len(rebalancing_rows)}")
    else:
        _atomic_write_rebalancing(rebalancing_rows)

    return (
        '<table class="styled-table final-order-table">'
        '<thead><tr>'
        '<th>Ticker</th><th>Name</th><th>등락률(%)</th><th>위치</th>'
        '<th>Sco</th><th>비중</th><th>지수대비(%)</th>'
        '<th>2x</th>'
        '<th>수량</th><th class="pc-only">총액</th>'
        '<th>연금</th><th class="pc-only">총액</th>'
        '</tr></thead>'
        '<tbody>\n'
        + '\n'.join(rows_html)
        + '\n</tbody></table>\n'
    )


def build_stats_html(s_data: dict, data: list = None) -> str:
    k_trend      = s_data.get("kospi_trend", "-")
    kd_trend     = s_data.get("kosdaq_trend", "-")
    sp_trend     = s_data.get("sp500_trend", "-")
    us_trend     = s_data.get("nasdaq_trend", "-")
    nikkei_trend = s_data.get("nikkei_trend", "-")
    euro_trend   = s_data.get("euro_trend", "-")
    inda_trend     = s_data.get("india_trend", "-")
    shanghai_trend = s_data.get("shanghai_trend", "-")
    hongkong_trend = s_data.get("hongkong_trend", "-")
    brazil_trend   = s_data.get("brazil_trend", "-")

    k_mult      = s_data.get("kospi_mult", "-")
    us_mult     = s_data.get("nasdaq_mult", "-")
    invest_pct  = s_data.get("invest_pct", 0)
    t_sco       = s_data.get("top3_avg_sco", 0)
    t_pos       = s_data.get("top3_avg_pos", 0)
    avg_sco     = s_data.get("avg_sco", 0)
    total_cnt   = s_data.get("total_cnt", 0)
    valid_cnt   = s_data.get("valid_cnt", 0)
    atr_excl_cnt = s_data.get("atr_excl_cnt", 0)
    sco_pos     = s_data.get("sco_pos", 0)
    sco_neg     = s_data.get("sco_neg", 0)
    sco_strong  = s_data.get("sco_strong", 0)

    color_map = {
        "RED":    "#e74c3c", "PURPLE": "#9b59b6",
        "LIME":   "#2ecc71", "GREEN":  "#27ae60", "-": "#95a5a6",
    }

    def bench_cell(label, trend, code, scope, outline=False):
        if outline:
            style = ('background:#fff;color:#34495e;border:1px solid #bdc3c7;'
                     'padding:3px 8px;text-align:center;border-radius:4px;'
                     'font-size:0.95em;font-weight:bold;white-space:nowrap;cursor:pointer;')
        else:
            c = color_map.get(trend, "#95a5a6")
            style = (f'background:{c};color:white;font-weight:bold;padding:3px 8px;'
                     f'text-align:center;border-radius:4px;font-size:0.95em;'
                     f'white-space:nowrap;cursor:pointer;')
        return (
            f'<td class="index-trigger" data-index-code="{code}" data-index-scope="{scope}" '
            f'title="{label}: {trend}" style="{style}">{label}</td>'
        )

    t_sco_str  = f"{t_sco:.2f}" if isinstance(t_sco, (int, float)) else str(t_sco)
    t_pos_str  = f"{t_pos:.2f}" if isinstance(t_pos, (int, float)) else str(t_pos)
    k_mult_str = f"x{k_mult}" if k_mult != "-" else "-"
    us_mult_str = f"x{us_mult}" if us_mult != "-" else "-"

    if invest_pct >= 67:    pct_color = "#e67e22"
    elif invest_pct >= 33:  pct_color = "#2c3e50"
    else:                   pct_color = "#7f8c8d"

    bench_table = (
        '<table style="border-collapse:separate;border-spacing:3px;margin-bottom:6px;width:auto;"><tr>'
        + bench_cell("코", k_trend,      "KOSPI",      "kr")
        + bench_cell("닥", kd_trend,     "KOSDAQ",     "kr")
        + bench_cell("미", sp_trend,     "SPI@SPX",    "world")
        + bench_cell("나", us_trend,     "NAS@IXIC",   "world")
        + bench_cell("일", nikkei_trend, "NII@NI225",  "world")
        + bench_cell("유", euro_trend,   "STX@SX5E",   "world")
        + bench_cell("인", inda_trend,     "INI@BSE30",  "world", outline=(inda_trend     == "-"))
        + bench_cell("상", shanghai_trend, "SHS@000001", "world", outline=(shanghai_trend == "-"))
        + bench_cell("홍", hongkong_trend, "HSI@HSCE",   "world", outline=(hongkong_trend == "-"))
        + bench_cell("브", brazil_trend,   "BRI@BVSP",   "world", outline=(brazil_trend   == "-"))
        + '</tr></table>'
    )

    _sco_mid = sco_pos - sco_strong
    _sco_den = sco_pos + sco_neg
    def _scopct(n):
        return f'{n / _sco_den * 100:.1f}%' if _sco_den else '0%'
    sco_bars_html = _sco_dist_bars(
        [
            ("sco ≥ 11", f'{sco_strong}', _scopct(sco_strong), "#2ecc71"),
            ("0 ~ 11",   f'{_sco_mid}',   _scopct(_sco_mid),   "#95a5a6"),
            ("sco < 0",  f'{sco_neg}',    _scopct(sco_neg),    "#e74c3c"),
        ],
        total=_sco_den,
        title="📊 SCO 기준 종목 분포",
    )

    stats_box = (
        '<div class="stats-box">'
        f'<p>📊 &nbsp;<b style="color:{pct_color};">총 투자비중={invest_pct:.1f}%</b>'
        f' &nbsp;/&nbsp; <span class="lbl">top3_avg_sco=</span><b>{t_sco_str}</b>'
        f' &nbsp;/&nbsp; <span class="lbl">top3_avg_pos=</span><b>{t_pos_str}</b>'
        f' &nbsp;&nbsp;<span class="sub">(코스피 {k_mult_str} / 나스닥 {us_mult_str})</span></p>'
        f'<p><span class="lbl">전체 Signal_sco 평균:</span> <b>{avg_sco}</b>'
        f' <span class="sub">(전체 {total_cnt}개 / 유효 {valid_cnt}개 / ATR제외 {atr_excl_cnt}개)</span></p>'
        f'{sco_bars_html}'
        '</div>'
    )

    return bench_table + stats_box


def build_trend_badge(trend: str) -> str:
    t = str(trend).strip().upper()
    mapping = {
        "LIME":   ("3",  "#00c853", "#000"),
        "GREEN":  ("2",  "#27ae60", "#fff"),
        "PURPLE": ("-2", "#8e44ad", "#fff"),
        "RED":    ("-3", "#e74c3c", "#fff"),
    }
    if t in mapping:
        label, bg, fg = mapping[t]
        return (
            f'<span style="display:inline-block;padding:2px 7px;border-radius:10px;'
            f'background:{bg};color:{fg};font-size:11px;font-weight:bold;">{label}</span>'
        )
    return '<span style="color:#aaa;">-</span>'


def _fmt_vol(v, suffix="%", decimals=1) -> str:
    if v is None:
        return '-'
    try:
        return f'{float(v):.{decimals}f}{suffix}'
    except Exception:
        return '-'


def _stab_color(v) -> str:
    """Stability_score 0~1 → 색상 (높을수록 초록)"""
    if v is None:
        return "#aaa"
    try:
        f = float(v)
        if f >= 0.7:  return "#27ae60"
        if f >= 0.4:  return "#e67e22"
        return "#e74c3c"
    except Exception:
        return "#aaa"


def main():
    global ASSET_8042, USD_KRW_EFFECTIVE
    # 9-12: 통합자산·환율 조회를 여기(main)에서 수행. 실패 시 예외로 중단(파일 미생성).
    ASSET_8042, USD_KRW_EFFECTIVE = _load_combined_asset_8042()
    _save_combined_asset_snapshot()
    data        = read_data()
    low_history = update_low_history(data)
    held_status, held_list = read_held_list()
    stats_status, s_data   = read_stats()
    now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats_html  = build_stats_html(s_data, data)

    top5_section_html = build_top5_section_global(held_list, data)
    lev_overlay = build_lev2_overlay(held_list)
    lev_order_tickers = [
        v for k, v in (lev_overlay.get("orders", {}) if lev_overlay else {}).items()
        if v and v != k
    ]
    price_map = _build_price_map(held_list, lev_order_tickers)
    apply_lev2_price_fallback(lev_overlay, price_map)
    lev_qty_map = {}
    final_order_html  = build_final_order_table(held_list, data, s_data,
                                                held_status, stats_status, price_map,
                                                lev_overlay=lev_overlay,
                                                qty_out=lev_qty_map)
    # 주문기(allone)용 '전략 비중' JSON 생성(절대수량 아님). 각 계좌가 자체 총자산으로 수량 산출.
    build_target_weights(held_list, data, s_data, held_status, stats_status, price_map,
                         lev_overlay=lev_overlay)
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from lev2_order_overlay import write_artifacts
        write_artifacts(lev_overlay, held_list, lev_qty_map)
    except Exception as e:
        print(f"[2x오버레이] 산출물 저장 실패(주문 파일 생성은 계속): {e}")

    rows_html = ""
    top30_data = data[:30]
    held_set = set(held_list)

    for idx, item in enumerate(top30_data, 1):
        type_cls   = "kr" if item["type"] == "KR" else "us"
        type_label = f'<span class="type-{type_cls}">[{item["type"]}]</span>'

        if item["ticker"] in held_set:
            row_style = ' style="background-color: #FFFF99;"'
        elif item["sco"] >= 11:
            row_style = ' style="background-color: #CCFFFF;"'
        else:
            row_style = ""

        chg = item.get("chg")
        chg_str = f"{chg:+.1f}%" if chg is not None else "-"
        chg_cls = ("sig-up" if chg and chg > 0 else ("sig-down" if chg and chg < 0 else ""))

        pos_str = item.get("pos", "-")
        pos_html = (f'<span class="pos-badge pos-{pos_str}">{pos_str}</span>'
                    if pos_str in ("1","2","3","4","5") else pos_str or "-")

        low_badge = get_low_badge(item["ticker"], low_history)

        idx_rel = item.get("idx_rel")
        idx_rel_str = f"{idx_rel:+.1f}%" if idx_rel is not None else "-"
        idx_rel_cls = ("sig-up" if idx_rel and idx_rel > 0 else ("sig-down" if idx_rel and idx_rel < 0 else ""))

        rsi_str_val = item.get("rsi", "-")
        rsi_class = ""
        rsi_style = ""
        import re
        m_rsi = re.match(r'(\d+)\((\d+)\)', rsi_str_val)
        if m_rsi:
            tdy_rsi = int(m_rsi.group(1))
            prv_rsi = int(m_rsi.group(2))
            rsi_class = "sig-up" if tdy_rsi >= 50 else "sig-down"
            if tdy_rsi >= 30 and prv_rsi < 30:
                rsi_style = ' style="background-color:#d5f5e3; font-weight:bold;"'

        trend_badge  = build_trend_badge(item.get("trend", ""))
        inv3_icon    = '🚀' if item.get("inv3") == 1 else ''
        fire_icon    = '🔥' if item.get("fire") == 1 else ''
        signal_cell  = f"{inv3_icon}{fire_icon}"

        rtn1m = item.get("rtn1m")
        rtn1m_color = "#e74c3c" if rtn1m and rtn1m > 0 else "#3498db"
        rtn1m_str   = f'{rtn1m:.1f}%' if rtn1m is not None else "-"

        avg136 = item.get("avg136")
        avg136_color = "#e74c3c" if avg136 and avg136 > 0 else "#3498db"
        avg136_str   = f'{avg136:.1f}%' if avg136 is not None else "-"

        score_display = item["score_final"] * 100
        base_score_v  = item.get("base_score")
        base_display  = f'{base_score_v * 100:.1f}' if base_score_v is not None else '-'

        stab_v   = item.get("stability")
        stab_str = f'{stab_v:.2f}' if stab_v is not None else '-'
        stab_col = _stab_color(stab_v)

        dwn_str   = _fmt_vol(item.get("downside_vol"), "%", 1)
        mdd_str   = _fmt_vol(item.get("mdd126"), "%", 1)
        spike_str = _fmt_vol(item.get("vol_spike"), "x", 2)

        ticker_display = item["ticker"] + ("**" if item.get("intensity") else "")
        if item["is_kr"]:
            # 한국종목: 티커 셀에서 v4 트리거 제거 → 종목명 셀(build_name_cell)이 담당
            ticker_td = f'<td data-code="{item["ticker"]}">{type_label} {ticker_display}</td>'
        else:
            ticker_td = f'<td class="chart-trigger" data-ticker="{item["ticker"]}" data-v4-code="{item["ticker"]}" data-v4-market="US" style="cursor:pointer;">{type_label} {ticker_display}</td>'

        name_cell = build_name_cell(item)
        rows_html += (
            f'\n            <tr{row_style}>'
            + ticker_td
            + name_cell +
            f'<td class="{chg_cls}">{chg_str}</td>'
            f'<td>{pos_html}</td>'
            f'<td style="text-align:center">{trend_badge}</td>'
            f'<td>{item["sco"]:.1f}</td>'
            f'<td class="{rsi_class}"{rsi_style}>{rsi_str_val}</td>'
            f'<td style="font-weight:bold">{score_display:.1f}</td>'
            f'<td style="color:#555">{base_display}</td>'
            f'<td style="font-weight:bold;color:{stab_col}">{stab_str}</td>'
            f'<td style="color:#888;font-size:0.85em">{dwn_str}</td>'
            f'<td style="color:#888;font-size:0.85em">{mdd_str}</td>'
            f'<td style="color:#888;font-size:0.85em">{spike_str}</td>'
            f'<td style="font-weight:bold;color:{rtn1m_color}">{rtn1m_str}</td>'
            f'<td style="font-weight:bold;color:{avg136_color}">{avg136_str}</td>'
            f'<td>{low_badge}</td>'
            f'<td style="text-align:center;font-size:1.1em">{signal_cell}</td>'
            f'<td class="{idx_rel_cls}">{idx_rel_str}</td>'
            f'</tr>'
        )

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>ETF 수익률 상위 (통합 ETF)</title>
<style>
.container-all {{ max-width: 1400px; margin: 0; padding-bottom: 20px; }}
.top-nav-container {{ display: flex; margin-bottom: 10px; }}
.top-nav {{ display: flex; background-color: #2c3e50; border-radius: 8px; overflow: hidden; width: fit-content; }}
.nav-item {{ padding: 8px 15px; color: #bdc3c7; text-align: center; cursor: pointer; font-weight: bold; text-decoration: none; transition: all 0.3s; font-size: 0.9em; }}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}
body {{ font-family: 'Segoe UI', sans-serif; padding: 15px; background-color: #f4f7f6; margin: 0; line-height: 1.3; }}
h1 {{ font-size: 1.3rem; color: #2c3e50; margin: 0 0 6px 0; }}
h2 {{ margin: 10px 0 4px 0; padding-bottom: 3px; color: #2c3e50; border-bottom: 2px solid #e67e22; font-size: 1.0em; }}
h3 {{ margin: 8px 0 4px 0; padding-bottom: 3px; color: #2c3e50; border-bottom: 2px solid #3498db; font-size: 1.0em; }}
.meta {{ color: #7f8c8d; font-size: 0.85rem; margin-bottom: 8px; }}
.stats-box {{ background: #fffde7; border: 1px solid #fbc02d; padding: 8px 14px; border-radius: 8px; margin-bottom: 10px; font-size: 13px; color: #34495e; display: inline-block; min-width: 300px; }}
.stats-box p {{ margin: 2px 0; }}
.stats-box .lbl {{ font-weight: bold; color: #2c3e50; }}
.stats-box .sub {{ font-size: 0.85em; color: #7f8c8d; }}
.vol-legend {{ background: #f0f8ff; border: 1px solid #aed6f1; border-radius: 6px; padding: 6px 12px; margin-bottom: 8px; font-size: 12px; color: #34495e; display: inline-block; }}
.styled-table {{ width: auto; min-width: 400px; max-width: 100%; border-collapse: collapse; margin: 4px 0 12px 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 13px; border-radius: 8px; overflow: hidden; }}
.styled-table thead tr {{ background: linear-gradient(135deg, #8e44ad, #6c3483); color: #ffffff; text-align: center; }}
.styled-table th, .styled-table td {{ padding: 5px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
.styled-table td {{ text-align: center; }}
.styled-table td.narrow {{ font-weight: bold; color: #2980b9; text-align: left; }}
.styled-table td.name-col {{ max-width: 150px; overflow: hidden; text-overflow: ellipsis; text-align: left; }}
.type-kr {{ color: #e74c3c; font-weight: bold; font-size: 0.75rem; }}
.type-us {{ color: #3498db; font-weight: bold; font-size: 0.75rem; }}
.sig-up {{ color: #27ae60; font-weight: bold; }}
.sig-down {{ color: #e74c3c; font-weight: bold; }}
.held-bold {{ background-color: #fff9c4 !important; color: #d32f2f !important; font-weight: bold !important; }}
.pos-badge {{ display: inline-block; width: 22px; height: 22px; line-height: 22px; border-radius: 50%; font-size: 0.75rem; font-weight: bold; color: white; text-align: center; }}
.pos-1 {{ background-color: #16a34a !important; }}
.pos-2 {{ background-color: #65a30d !important; }}
.pos-3 {{ background-color: #d97706 !important; }}
.pos-4 {{ background-color: #ea580c !important; }}
.pos-5 {{ background-color: #dc2626 !important; }}
.low-badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: bold; color: white; text-align: center; min-width: 35px; }}
.low-jeo   {{ background-color: #2ecc71; }}
.low-jeo2  {{ background-color: #3498db; }}
.low-both  {{ background-color: #e74c3c; }}
.low-track {{ background-color: #95a5a6; }}
.final-order-table {{ min-width: unset; }}
.chart-trigger {{ cursor: pointer; text-decoration: underline dotted; }}
.chart-trigger:hover {{ background-color: #e8f4f8 !important; }}
.naver-trigger {{ cursor: pointer; text-decoration: underline dotted; }}
.naver-trigger:hover {{ background-color: #fff3cd !important; }}
/* 네이버 팝업 (US worldstock) */
#naverChartPopupUS {{
  display: none; position: fixed; z-index: 99998;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; overflow-y: auto; max-height: 90dvh;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
#naverPopupCloseUS {{
  display: flex; background: #e74c3c; color: white;
  border: none; border-radius: 50%; width: 28px; height: 28px;
  font-size: 18px; line-height: 1; cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center; font-weight: bold;
}}
@media (max-width: 767px) {{
  #naverChartPopupUS {{
    position: fixed !important; left: 2vw !important; top: 50% !important;
    transform: translateY(-50%); width: 96vw !important;
    max-height: 80dvh !important; overflow-y: auto !important;
    padding: 8px !important; box-sizing: border-box;
  }}
}}
/* 네이버 팝업 (지수) */
#naverChartPopupIndex {{
  display: none; position: fixed; z-index: 99998;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; overflow-y: auto; max-height: 90dvh;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
#naverPopupCloseIndex {{
  display: flex; background: #e74c3c; color: white;
  border: none; border-radius: 50%; width: 28px; height: 28px;
  font-size: 18px; line-height: 1; cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center; font-weight: bold;
}}
.index-trigger {{ cursor: pointer; }}
@media (max-width: 767px) {{
  #naverChartPopupIndex {{
    position: fixed !important; left: 2vw !important; top: 50% !important;
    transform: translateY(-50%); width: 96vw !important;
    max-height: 80dvh !important; overflow-y: auto !important;
    padding: 8px !important; box-sizing: border-box;
  }}
}}
/* 네이버 팝업 (KR) */
#naverChartPopup {{
  display: none; position: fixed; z-index: 99998;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; overflow-y: auto; max-height: 90dvh;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex; background: #e74c3c; color: white;
  border: none; border-radius: 50%; width: 28px; height: 28px;
  font-size: 18px; line-height: 1; cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center; font-weight: bold;
}}
.popup-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; margin-left: 1em; }}
.popup-link:hover {{ text-decoration: underline; }}
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.chart-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }}
.chart-card-header {{ display: none; }}
.chart-wrap {{ position: relative; width: 100%; height: 300px; background: white; }}
.chart-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: white; }}
.chart-loading {{ display: none; position: absolute; inset: 0; background: rgba(255,255,255,0.75); align-items: center; justify-content: center; font-size: 12px; color: #64748b; }}
.chart-loading.show {{ display: flex; }}
@media (max-width: 767px) {{
  #naverChartPopup {{
    position: fixed !important; left: 2vw !important; top: 50% !important;
    transform: translateY(-50%); width: 96vw !important;
    max-height: 80dvh !important; overflow-y: auto !important;
    padding: 8px !important; box-sizing: border-box;
  }}
  .charts-grid {{ grid-template-columns: 1fr; gap: 6px; }}
  .chart-wrap {{ height: 220px; }}
}}
@media (max-width: 600px) {{
    .styled-table {{ font-size: 11px; }}
    .styled-table th, .styled-table td {{ padding: 4px 5px; }}
    .stats-box {{ font-size: 11px; min-width: unset; width: 100%; box-sizing: border-box; }}
    .pc-only {{ display: none !important; }}
}}
/* ══ Top5 카드 섹션 ═══════════════════════════════════════ */
.t5-section {{ margin: 0 0 14px 0; }}
.t5-section-title {{
  font-size: 0.92em; font-weight: bold; color: #2c3e50;
  border-bottom: 2px solid #8e44ad;
  padding-bottom: 4px; margin-bottom: 8px;
}}
.t5-cards-row {{
  display: flex; gap: 8px;
  flex-wrap: nowrap; align-items: flex-start;
}}
.t5-card {{
  background: white; border-radius: 7px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.09);
  min-width: 110px; max-width: 160px;
  flex: 0 0 auto; overflow: hidden;
}}
.t5-header {{
  display: flex; align-items: center;
  justify-content: space-between;
  padding: 5px 9px 4px 9px;
  border-bottom: 1px solid #eee; gap: 4px;
}}
.t5-title {{ font-size: 0.8em; font-weight: bold; color: #2c3e50; white-space: nowrap; }}
.t5-label {{
  font-size: 0.72em; color: #888; white-space: nowrap;
  background: #f0f0f0; border-radius: 3px; padding: 1px 5px;
}}
.t5-body {{ padding: 5px 9px 6px 9px; }}
.t5-row {{
  display: flex; align-items: center; gap: 5px;
  padding: 2px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.82em;
}}
.t5-row:last-child {{ border-bottom: none; }}
.t5-medal {{ font-size: 0.88em; flex-shrink: 0; min-width: 16px; text-align: center; }}
.t5-name {{
  flex: 1; color: #2c3e50; font-weight: 700;
  white-space: nowrap; font-size: 0.93em; letter-spacing: 0.02em;
}}
.t5-empty {{ font-size: 0.78em; color: #aaa; padding: 6px 0; }}
@media (max-width: 600px) {{
  .t5-cards-row {{ overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 4px; }}
  .t5-card {{ min-width: 100px; max-width: 140px; }}
}}
</style>
</head>
<body>
<div class="container-all">
    <div class="top-nav-container">
        <div class="top-nav">
            <a href="total_etf_combined.html" class="nav-item active">통합 ETF</a>
            <a href="total_etf_combined_AI.html" class="nav-item">🤖 AI 관찰판</a>
            <a href="top3_etf_daily_result_total.html" class="nav-item">Top3 추세</a>
            <a href="etf_usa_status.html" class="nav-item">ETF현황</a>
            <a href="hanmi_watch.html" class="nav-item">한미관심주</a>
        </div>
    </div>
    <h1>📈 ETF 수익률 상위 (통합 ETF — KR/US 통합)</h1>
    <p class="meta">Updated: {now}</p>
    <div class="vol-legend">
        📉 <b>통합 ETF flow</b> &nbsp;|&nbsp;
        Final = Base × (0.80 + 0.20×Stab) × ATR벌점 &nbsp;|&nbsp;
        Stab = 하방변동성×45% + MDD×35% + VolSpike×20% (역방향, 높을수록 안정)
    </div>
    {stats_html}

    {top5_section_html}

    <h2>🧾 주문용 최종 보유 목록 ({s_data.get('invest_pct', 0):.1f}%) <span style="font-size:0.7em; color:#000; font-weight:normal;">- {int(ASSET_8042 / 10000):,}만원 기준 {int(ASSET_8042 * s_data.get('invest_pct', 0) / 100 / 10000):,}만원</span></h2>
    {final_order_html}

    <h3>📊 ETF 랭킹 &nbsp;<span style="font-size:0.8em;font-weight:normal;color:#555;">(노랑: 주문용 보유, 파랑: sco&ge;11 | Score=Final×100, Base=기본점수×100, Stab=안정성0~1)</span></h3>
    <table class="styled-table">
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Name</th>
                <th>등락률(%)</th>
                <th>위치</th>
                <th>추세</th>
                <th>sco</th>
                <th>RSI</th>
                <th>Score</th>
                <th>Base</th>
                <th>Stab</th>
                <th>하방%</th>
                <th>MDD%</th>
                <th>Spike</th>
                <th>1M</th>
                <th>136</th>
                <th>저점</th>
                <th>🚀</th>
                <th>지수대비(%)</th>
            </tr>
        </thead>
        <tbody>{rows_html}
        </tbody>
    </table>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {{
    var titles = Array.from(document.querySelectorAll('h2, h3'));
    var targetTitle = titles.find(t => t.innerText.includes('ETF 랭킹'));
    if (!targetTitle) return;
    var table = targetTitle.nextElementSibling;
    while (table && table.tagName !== 'TABLE' && !table.querySelector('table')) {{
        table = table.nextElementSibling;
    }}
    if (table && table.tagName !== 'TABLE') table = table.querySelector('table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    if (!tbody) return;
    var originalRows = Array.from(tbody.querySelectorAll('tr')).map(function(r) {{ return r.cloneNode(true); }});
    var sortState = {{ col: null, asc: true }};
    function getCellValue(row, col) {{
        var cells = row.querySelectorAll('td');
        if (!cells[col]) return '';
        return cells[col].innerText.trim();
    }}
    function toNum(str) {{
        var n = parseFloat(str.replace(/[^0-9.\\x2D]/g, ''));
        if (isNaN(n) || str.trim() === '-' || str.trim() === '') return null;
        return n;
    }}
    table.querySelectorAll('th').forEach(function(th, index) {{
        th.style.cursor = 'pointer';
        th.addEventListener('click', function() {{
            if (sortState.col === index) {{
                if (!sortState.asc) {{
                    sortState = {{ col: null, asc: true }};
                    tbody.innerHTML = '';
                    originalRows.forEach(function(r) {{ tbody.appendChild(r.cloneNode(true)); }});
                    return;
                }}
                sortState.asc = false;
            }} else {{
                sortState.col = index;
                sortState.asc = true;
            }}
            var rows = Array.from(tbody.querySelectorAll('tr'));
            rows.sort(function(a, b) {{
                var va = getCellValue(a, index);
                var vb = getCellValue(b, index);
                var na = toNum(va), nb = toNum(vb);
                if (na !== null && nb !== null) {{
                    return sortState.asc ? na - nb : nb - na;
                }}
                var cmp = va.localeCompare(vb, 'ko');
                return sortState.asc ? cmp : -cmp;
            }});
            tbody.innerHTML = '';
            rows.forEach(function(r) {{ tbody.appendChild(r); }});
        }});
    }});
}});
</script>

<!-- 네이버 차트 팝업 (US ETF - worldstock) -->
__V4_BLOCK__
<script>
(function () {{
  return;   // V4 팝업으로 대체됨 (US 셀은 V4, KR/지수는 네이버 PNG 유지)
  var NAVER_CODES = {{ QQQ: 'QQQ.O', SMH: 'SMH.O' }};
  var SUFFIX_TRY = ['.O', '.P', '', '.N', '.A', '.K'];
  var NAVER_LS_KEY = 'naverCodeMap_v1';
  var resolvedCode = (function () {{
    var m = {{}};
    try {{ m = JSON.parse(localStorage.getItem(NAVER_LS_KEY) || '{{}}') || {{}}; }} catch (e) {{ m = {{}}; }}
    for (var k in NAVER_CODES) {{ if (!m[k]) m[k] = NAVER_CODES[k]; }}
    return m;
  }})();
  function persistCode(T, code) {{ resolvedCode[T] = code; try {{ localStorage.setItem(NAVER_LS_KEY, JSON.stringify(resolvedCode)); }} catch (e) {{}} }}
  function forgetCode(T) {{ if (resolvedCode[T]) {{ delete resolvedCode[T]; try {{ localStorage.setItem(NAVER_LS_KEY, JSON.stringify(resolvedCode)); }} catch (e) {{}} }} }}
  var popup = document.getElementById('naverChartPopupUS');
  var popupTitle = document.getElementById('popupTitleUS');
  var popupLink = document.getElementById('popupLinkUS');
  var imgDaily = document.getElementById('imgDailyUS');
  var imgWeekly = document.getElementById('imgWeeklyUS');
  var loadingDaily = document.getElementById('loadingDailyUS');
  var loadingWeekly = document.getElementById('loadingWeeklyUS');
  var hoverTimer = null; var pinned = false;
  function withTs(u) {{ return u + '?t=' + Math.floor(Date.now() / 60000); }}
  function dailyUrl(c)  {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/day/'  + c + '_end.png'); }}
  function weeklyUrl(c) {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/week/' + c + '_end.png'); }}
  function pageUrl(c)   {{ return 'https://m.stock.naver.com/worldstock/stock/' + c + '/total'; }}
  function resolveCode(ticker, cb) {{
    var T = String(ticker || '').replace(/[*]/g, '').toUpperCase();
    if (!T) {{ cb(null); return; }}
    if (resolvedCode[T]) {{ cb(resolvedCode[T]); return; }}
    var candidates = NAVER_CODES[T] ? [NAVER_CODES[T]] : SUFFIX_TRY.map(function (s) {{ return T + s; }});
    var i = 0;
    function tryNext() {{
      if (i >= candidates.length) {{ cb(null); return; }}
      var code = candidates[i++];
      var probe = new Image();
      probe.onload  = function () {{ persistCode(T, code); cb(code); }};
      probe.onerror = tryNext;
      probe.src = withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/day/' + code + '_end.png');
    }}
    tryNext();
  }}
  function loadInto(imgEl, loadingEl, url, onErr) {{
    loadingEl.classList.add('show'); imgEl.style.opacity = '0.35';
    var p = new Image();
    p.onload  = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); if (onErr) onErr(); }};
    p.src = url;
  }}
  function loadCharts(ticker) {{
    var T = String(ticker || '').replace(/[*]/g, '').toUpperCase();
    popupTitle.textContent = T + ' (resolving...)';
    popupLink.href = '#';
    loadingDaily.classList.add('show'); loadingWeekly.classList.add('show');
    imgDaily.removeAttribute('src'); imgWeekly.removeAttribute('src');
    resolveCode(T, function (code) {{
      if (!code) {{ popupTitle.textContent = T + '  (all suffixes failed)'; loadingDaily.classList.remove('show'); loadingWeekly.classList.remove('show'); return; }}
      popupTitle.textContent = T + '  [' + code + ']';
      popupLink.href = pageUrl(code);
      loadInto(imgDaily,  loadingDaily,  dailyUrl(code), function () {{ forgetCode(T); }});
      loadInto(imgWeekly, loadingWeekly, weeklyUrl(code));
    }});
  }}
  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
  }}
  function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('naver-popup-open'); }}
  function closePopup() {{ popup.style.display = 'none'; pinned = false; document.body.classList.remove('naver-popup-open'); }}
  document.getElementById('naverPopupCloseUS').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});
  document.querySelectorAll('.chart-trigger[data-ticker]').forEach(function (el) {{
    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{ placePopup(e.clientX, e.clientY); openPopup(); loadCharts(el.getAttribute('data-ticker') || ''); }}, 140);
    }});
    el.addEventListener('mousemove', function (e) {{ if (window.innerWidth <= 767) return; if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY); }});
    el.addEventListener('mouseleave', function () {{ if (window.innerWidth <= 767) return; clearTimeout(hoverTimer); setTimeout(function () {{ if (!pinned) closePopup(); }}, 120); }});
    el.addEventListener('click', function (e) {{ e.stopPropagation(); clearTimeout(hoverTimer); placePopup(e.clientX, e.clientY); openPopup(); loadCharts(el.getAttribute('data-ticker') || ''); }});
  }});
  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767) {{ if (!e.target.closest('#naverChartPopupUS')) closePopup(); }}
    else {{ if (!e.target.closest('#naverChartPopupUS') && !e.target.closest('.chart-trigger')) closePopup(); }}
  }});
}})();
</script>

<!-- 네이버 차트 팝업 (지수) -->
<div id="naverChartPopupIndex">
  <div class="popup-header">
    <button id="naverPopupCloseIndex" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitleIndex">-</div>
    <a id="popupLinkIndex" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><div class="chart-wrap">
      <img id="imgDailyIndex" alt="일봉 차트">
      <div class="chart-loading" id="loadingDailyIndex">불러오는 중...</div>
    </div></div>
    <div class="chart-card"><div class="chart-wrap">
      <img id="imgWeeklyIndex" alt="주봉 차트">
      <div class="chart-loading" id="loadingWeeklyIndex">불러오는 중...</div>
    </div></div>
  </div>
</div>
<script>
(function () {{
  var popup = document.getElementById('naverChartPopupIndex');
  var popupTitle = document.getElementById('popupTitleIndex');
  var popupLink = document.getElementById('popupLinkIndex');
  var imgDaily = document.getElementById('imgDailyIndex');
  var imgWeekly = document.getElementById('imgWeeklyIndex');
  var loadingDaily = document.getElementById('loadingDailyIndex');
  var loadingWeekly = document.getElementById('loadingWeeklyIndex');
  var hoverTimer = null; var pinned = false;
  function withTs(u) {{ return u + '?t=' + Math.floor(Date.now() / 60000); }}
  function chartUrl(code, scope, period) {{
    if (scope === 'kr') return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/candle/' + period + '/' + code + '_end.png');
    return withTs('https://ssl.pstatic.net/imgfinance/chart/world/candle/' + period + '/' + code + '.png');
  }}
  function pageUrl(code, scope) {{
    if (scope === 'kr') return 'https://finance.naver.com/sise/sise_index.naver?code=' + code;
    return 'https://finance.naver.com/world/sise.naver?symbol=' + code;
  }}
  function loadInto(imgEl, loadingEl, url) {{
    loadingEl.classList.add('show'); imgEl.style.opacity = '0.35';
    var p = new Image();
    p.onload  = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.src = url;
  }}
  function loadCharts(code, scope) {{
    popupTitle.textContent = code; popupLink.href = pageUrl(code, scope);
    loadInto(imgDaily,  loadingDaily,  chartUrl(code, scope, 'day'));
    loadInto(imgWeekly, loadingWeekly, chartUrl(code, scope, 'week'));
  }}
  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
  }}
  function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('naver-popup-open'); }}
  function closePopup() {{ popup.style.display = 'none'; pinned = false; document.body.classList.remove('naver-popup-open'); }}
  document.getElementById('naverPopupCloseIndex').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});
  document.querySelectorAll('.index-trigger[data-index-code]').forEach(function (el) {{
    var code  = el.getAttribute('data-index-code');
    var scope = el.getAttribute('data-index-scope') || 'world';
    el.addEventListener('mouseenter', function (e) {{ if (window.innerWidth <= 767) return; clearTimeout(hoverTimer); hoverTimer = setTimeout(function () {{ placePopup(e.clientX, e.clientY); openPopup(); loadCharts(code, scope); }}, 140); }});
    el.addEventListener('mousemove', function (e) {{ if (window.innerWidth <= 767) return; if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY); }});
    el.addEventListener('mouseleave', function () {{ if (window.innerWidth <= 767) return; clearTimeout(hoverTimer); setTimeout(function () {{ if (!pinned) closePopup(); }}, 120); }});
    el.addEventListener('click', function (e) {{ e.stopPropagation(); clearTimeout(hoverTimer); placePopup(e.clientX, e.clientY); openPopup(); loadCharts(code, scope); }});
  }});
  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767) {{ if (!e.target.closest('#naverChartPopupIndex')) closePopup(); }}
    else {{ if (!e.target.closest('#naverChartPopupIndex') && !e.target.closest('.index-trigger')) closePopup(); }}
  }});
}})();
</script>

<!-- 네이버 차트 팝업 (한국 ETF) -->
<div id="naverChartPopup">
  <div class="popup-header">
    <button id="naverPopupClose" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><div class="chart-card-header"><div class="chart-status" id="statusDaily">대기중</div></div>
      <div class="chart-wrap"><img id="imgDaily" alt="일봉 차트"><div class="chart-loading" id="loadingDaily">불러오는 중...</div></div></div>
    <div class="chart-card"><div class="chart-card-header"><div class="chart-status" id="statusWeekly">대기중</div></div>
      <div class="chart-wrap"><img id="imgWeekly" alt="주봉 차트"><div class="chart-loading" id="loadingWeekly">불러오는 중...</div></div></div>
  </div>
</div>
<script>
(function () {{
  var popup      = document.getElementById('naverChartPopup');
  var popupTitle = document.getElementById('popupTitle');
  var popupLink  = document.getElementById('popupLink');
  var imgDaily   = document.getElementById('imgDaily');
  var imgWeekly  = document.getElementById('imgWeekly');
  var loadingDaily  = document.getElementById('loadingDaily');
  var loadingWeekly = document.getElementById('loadingWeekly');
  var statusDaily   = document.getElementById('statusDaily');
  var statusWeekly  = document.getElementById('statusWeekly');
  var hoverTimer = null; var pinned = false;
  function withTs(url) {{ return url + '?t=' + Math.floor(Date.now() / 60000); }}
  function dailyCandleUrl(code)  {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'  + code + '.png'); }}
  function weeklyCandleUrl(code) {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/week/' + code + '.png'); }}
  function itemPageUrl(code)     {{ return 'https://finance.naver.com/item/main.naver?code=' + code; }}
  function setStatus(el, text, color) {{ el.textContent = text; el.style.color = color || '#94a3b8'; }}
  function loadInto(imgEl, loadingEl, statusEl, url, label) {{
    loadingEl.classList.add('show'); imgEl.style.opacity = '0.35'; setStatus(statusEl, '로딩중...', '#f59e0b');
    var probe = new Image();
    probe.onload = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); setStatus(statusEl, '로드 성공', '#22c55e'); }};
    probe.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); setStatus(statusEl, label + ' 실패', '#ef4444'); }};
    probe.src = url;
  }}
  function loadCharts(code) {{
    popupTitle.textContent = code; popupLink.href = itemPageUrl(code);
    loadInto(imgDaily,  loadingDaily,  statusDaily,  dailyCandleUrl(code),  '일봉');
    loadInto(imgWeekly, loadingWeekly, statusWeekly, weeklyCandleUrl(code), '주봉');
  }}
  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
  }}
  function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('naver-popup-open'); }}
  function closePopup() {{ popup.style.display = 'none'; pinned = false; document.body.classList.remove('naver-popup-open'); }}
  document.getElementById('naverPopupClose').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});
  function attachNaverTrigger(el) {{
    var code = el.getAttribute('data-code');
    if (!code) return;
    el.addEventListener('mouseenter', function (e) {{ if (window.innerWidth <= 767) return; clearTimeout(hoverTimer); hoverTimer = setTimeout(function () {{ placePopup(e.clientX, e.clientY); openPopup(); loadCharts(code); }}, 140); }});
    el.addEventListener('mousemove', function (e) {{ if (window.innerWidth <= 767) return; if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY); }});
    el.addEventListener('mouseleave', function () {{ if (window.innerWidth <= 767) return; clearTimeout(hoverTimer); setTimeout(function () {{ if (!pinned) closePopup(); }}, 120); }});
    el.addEventListener('click', function (e) {{ e.stopPropagation(); clearTimeout(hoverTimer); placePopup(e.clientX, e.clientY); openPopup(); loadCharts(code); }});
  }}
  document.querySelectorAll('.naver-trigger[data-code]').forEach(attachNaverTrigger);
  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767) {{ if (!e.target.closest('#naverChartPopup')) closePopup(); }}
    else {{ if (!e.target.closest('#naverChartPopup') && !e.target.closest('.naver-trigger')) closePopup(); }}
  }});
}})();
</script>

</body>
</html>
"""
    _v4_pairs = re.findall(r'data-v4-code="([^"]+)"\s+data-v4-market="([^"]+)"', page)
    _market_map = {
        (c.upper().replace('*', '').zfill(6) if m.upper() == "KR" else c.upper().replace('*', '')): m.upper()
        for c, m in _v4_pairs
    }
    page = page.replace(
        '__V4_BLOCK__',
        build_chart_popup(
            list(_market_map),
            market_map=_market_map,
            trigger_attr="data-v4-code",
            include_kospi=True,
        ),
    )
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] {OUT_HTML.name} 생성 완료 (상위 30개 표시, 보유 {len(held_list)}개)")


if __name__ == "__main__":
    main()
