# make_index_total_top_etf_combined_AI.py  (🤖 AI 전용 대시보드)
# jasantop4_global_softcap_AI.py 출력을 읽어 total_etf_combined_AI.html 생성.
#
# 입력 파일:
#   - D:\py\0txt\total_top30_AI.csv                  : AI 전용 Top30
#   - D:\py\buy_list_total_AI.txt                    : AI Top 보유 후보 (최대 6개)
#   - D:\py\report-us\kr_signal_stats_total_AI.json  : 통계 + AI Core 필드
#   - D:\py\report-us\ai_basket_scores_total_AI.json : AI 30 basket 점수
# 출력:
#   - D:\py\report-us\total_etf_combined_AI.html
#
# ※ 기존 make_index_total_top_etf_combined.py 및 total_etf_combined.html은
#   절대 수정하지 않는다. 본 파일은 AI universe만 표시하는 관찰판이다.

import csv
import io
import json
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from html import escape

# ── 현재가 조회 ────────────────────────────────────────────
USD_KRW = 1450        # 환율 (수동 변경 가능)

def _load_asset_8042() -> int:
    """asset_8042.json에서 추정자산(십만원 절하) 읽기. 없으면 API 직접 호출."""
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

ASSET_8042 = 10_000_000  # AI 관찰판 수량/총액 기준금액 (1천만원 고정)
PENSION_ASSET = 100_000_000  # 연금계좌 기준금액 (1억)

def _get_kor_price(ticker: str) -> float | None:
    """pykrx로 한국 ETF 현재가(당일/전일 종가) 조회"""
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

# ── 미국 현재가: 키움 usa20100 우선(yfinance 라이브바 NaN 회피) + yfinance 폴백 ──
#   정규장 중=cur_prc(현재가) / 정규장 아님=base_close_pric(전일종가, 프리·애프터 왜곡 회피)
#   가이드: D:\py\_260715_nan확대적용.md
_KW_US_TOKEN = None
_KW_US_DISABLED = False

def _us_regular_session() -> bool:
    """미국 정규장(평일 09:30~16:00 ET) 여부. 판정 불가 시 False(=전일종가)."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return False
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 570 <= mins < 960

def _kiwoom_us_token():
    global _KW_US_TOKEN, _KW_US_DISABLED
    if _KW_US_DISABLED:
        return None
    if _KW_US_TOKEN:
        return _KW_US_TOKEN
    try:
        import sys
        root = Path(__file__).resolve().parent.parent
        for d in (str(root), str(root / "0order")):
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
        import sys, requests
        root = Path(__file__).resolve().parent.parent
        for d in (str(root / "0order"), str(root / "0kiwoom_us")):
            if d not in sys.path:
                sys.path.insert(0, d)
        import allone_260712_ypykjw_fx as fx
        from us_symbol_resolver import resolve_kiwoom_us_symbol
        stex_tp, stk_cd = resolve_kiwoom_us_symbol(ticker)
        headers = {"api-id": "usa20100", "Authorization": f"Bearer {tok}",
                   "Content-Type": "application/json;charset=UTF-8"}
        fx._throttle_us()
        r = requests.post(fx.BASE_DOMAIN + fx.US_MARKET_URL, headers=headers,
                          data=json.dumps({"stex_tp": stex_tp, "stk_cd": stk_cd}), timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("return_code") not in (0, "0", None):
            return None
        field = "cur_prc" if _us_regular_session() else "base_close_pric"
        val = fx.as_decimal(str(data.get(field) or "").lstrip("+-"))
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
    # 폴백: yfinance (라이브 NaN 바 제거)
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

# ── 경로 설정 ──────────────────────────────────────────────
BASE         = Path(__file__).resolve().parent
PROJECT_ROOT = BASE.parent

CSV_FILE   = PROJECT_ROOT / "0txt" / "total_top30_AI.csv"
TOP6_FILE  = Path(r"D:\py\buy_list_total_AI.txt")
STATS_FILE       = Path(r"D:\py\report-us\kr_signal_stats_total_AI.json")
AI_BASKET_FILE   = Path(r"D:\py\report-us\ai_basket_scores_total_AI.json")
LOW_HISTORY_FILE = Path(r"D:\py\report-us\low_signal_history_AI.json")
BASKET_SCORE_HISTORY_FILE = Path(r"D:\py\report-us\ai_basket_score_history_total_AI.json")
BOTTLENECK_HISTORY_FILE   = Path(r"D:\py\report-us\ai_bottleneck_history_total_AI.json")
OUT_HTML         = BASE / "total_etf_combined_AI.html"
# AI 전용은 실거래 rebalancing 파일을 생성하지 않는다 (관찰판). 더미 경로 유지.
REBALANCING_TXT  = Path(r"D:\py\0order\00_totaletf_korea_rebalancing_AI.txt")

# ── Top5 CSV 경로 (AI 전용) ────────────────────────────────
# 기존 weekly_top5_global.csv / monthly_top5_global.csv 는 절대 읽거나 쓰지 않는다.
WEEKLY_TOP5_CSV  = BASE / "etf_history" / "weekly_top5_AI.csv"
MONTHLY_TOP5_CSV = BASE / "etf_history" / "monthly_top5_AI.csv"

# 원자재·채권 고정 multiplier=1.0 티커 목록
FIXED_ONE_TICKERS = {
    'GLD', 'SLV', 'DBA', 'DBC', 'PDBC', 'UNG', 'REMX', 'PICK',
    'AGG', 'BND', 'TLT', 'IEF', 'LQD', 'HYG', 'XLE',
    '411060',  # 금현물
}


# ══════════════════════════════════════════════════════════
# AI Basket 한글명 매핑 (jasantop4_global_softcap_AI.py 와 동일)
# ai_basket_scores_total_AI.json 안의 basket_kr / basket_name_kr 필드를
# 우선 사용하지만, total_top30_AI.csv 의 AI_Basket 컬럼처럼 영문 코드만
# 들어 있는 경로에서는 본 매핑을 통해 한글로 치환한다.
# ══════════════════════════════════════════════════════════
BASKET_KR_NAMES = {
    "AI_GPU_ACCELERATOR":              "AI_GPU",
    "AI_CPU_SERVER":                   "AI_CPU서버",
    "AI_ASIC_CUSTOM_CHIP":             "AI_맞춤칩ASIC",
    "AI_INFERENCE_OPTIMIZATION":       "AI_추론최적화",
    "AI_MEMORY_HBM_DRAM":              "AI_메모리",
    "AI_STORAGE_CXL_SSD":              "AI_스토리지",
    "AI_FOUNDRY":                      "AI_파운드리",
    "AI_SEMI_EQUIPMENT":               "AI_반도체장비",
    "AI_ADV_PACKAGING_SUBSTRATE":      "AI_첨단패키징",
    "AI_PASSIVE_COMPONENT_MLCC":        "AI_MLCC수동부품",
    "AI_NETWORKING_SWITCH_DPU":        "AI_네트워크",
    "AI_OPTICAL_PHOTONICS":            "AI_광통신",
    "AI_DATACENTER_REIT_SERVER":       "AI_데이터센터",
    "AI_POWER_GRID_TRANSFORMER":       "AI_전력망",
    "AI_COOLING_THERMAL":              "AI_냉각",
    "AI_ENERGY_NUCLEAR_SMR_GAS":       "AI_에너지",
    "AI_ONSITE_POWER_FUELCELL":         "AI_자가발전",
    "AI_RAW_MATERIALS_COPPER_RAREEARTH": "AI_원자재",
    "AI_CLOUD_HYPERSCALER":            "AI_클라우드",
    "AI_DATA_PIPELINE_DATABASE":       "AI_데이터플랫폼",
    "AI_SOFTWARE_PLATFORM":            "AI_소프트웨어",
    "AI_AGENT_AUTOMATION_RPA":         "AI_에이전트자동화",
    "AI_CYBER_SECURITY":               "AI_사이버보안",
    "AI_DATA_IDENTITY_SECURITY":       "AI_데이터보안",
    "AI_EDGE_DEVICE_ONDEVICE":         "AI_온디바이스",
    "AI_HUMANOID_ROBOT":               "AI_휴머노이드",
    "AI_FACTORY_AUTOMATION":           "AI_공장자동화",
    "AI_AUTONOMOUS_VEHICLE_DRONE":     "AI_자율주행드론",
    "AI_ROBOT_COMPONENT":              "AI_로봇부품",
    "AI_DIGITAL_TWIN_SIMULATION":      "AI_디지털트윈",
    "AI_EDA_DESIGN_TOOLS":             "AI_EDA설계",
    "AI_HEALTHCARE_BIO":               "AI_헬스케어바이오",
    "AI_FINTECH_TRADING":              "AI_핀테크",
    "AI_CONTENT_ADS_MEDIA":            "AI_광고미디어",
}


def basket_to_kr(code: str) -> str:
    """영문 basket 코드 → 한글명. 매핑 없으면 코드 그대로."""
    c = str(code or "").strip()
    return BASKET_KR_NAMES.get(c, c)


def baskets_pipe_to_kr(pipe_str: str, max_show: int = 3) -> str:
    """
    'AI_CYBER_SECURITY|AI_DATA_IDENTITY_SECURITY' →
    'AI_사이버보안 / AI_데이터보안'
    max_show 초과 시 '+N' 추가.
    """
    parts = [p.strip() for p in str(pipe_str or "").split("|") if p.strip()]
    if not parts:
        return "-"
    kr_parts = [basket_to_kr(p) for p in parts]
    shown = kr_parts[:max_show]
    tail = "" if len(kr_parts) <= max_show else f" <span style=\"color:#888;font-weight:normal;\">+{len(kr_parts)-max_show}</span>"
    return " / ".join(shown) + tail


def _is_kr_ticker(ticker: str) -> bool:
    t = str(ticker or "").strip().replace("**", "")
    return len(t) == 6 and t[:2].isdigit()


def _extract_display_ticker(text: str) -> str:
    raw = str(text or "").strip()
    paren_match = re.search(r"\(([A-Za-z0-9.\-]+)\)\s*$", raw)
    if paren_match:
        return paren_match.group(1).strip().replace("**", "")
    parts = raw.split()
    if not parts:
        return ""
    return parts[-1].strip().replace("**", "")


def ticker_chart_span(ticker: str, label: str = None, extra_cls: str = "") -> str:
    """KR은 네이버, US는 TradingView hover/click 팝업용 span."""
    tk = str(ticker or "").strip().replace("**", "")
    if not tk:
        return escape(str(label or ""))
    text = str(label if label is not None else tk)
    classes = extra_cls.strip()
    if _is_kr_ticker(tk):
        cls = f"naver-trigger {classes}".strip()
        return f'<span class="{cls}" data-code="{escape(tk)}">{escape(text)}</span>'
    cls = f"chart-trigger {classes}".strip()
    return f'<span class="{cls}" data-ticker="{escape(tk)}">{escape(text)}</span>'


# ══════════════════════════════════════════════════════════
# ── 🆕 당일/주간/월간 Top5 카드 섹션 (Global ETF) ──────────
# ══════════════════════════════════════════════════════════

MEDALS_G = ["🥇", "🥈", "🥉", "④", "⑤"]

# KR Ticker 이름 매핑 (AI universe + benchmark)
# jasantop4_global_softcap_AI.py 의 KR_TICKER_NAME_MAP 과 동일 의도.
KR_TICKER_TO_NAME = {
    '091160': '반도체ETF',
    '446770': '글로벌반도체TOP4',
    '000660': 'SK하이닉스',
    '005930': '삼성전자',
    '007660': '이수페타시스',
    '353200': '대덕전자',
    '434730': '원자력ETF',
    '0051G0': 'S&P500AI',
    '0038A0': '미국로봇',
    '0048K0': '중국로봇',
    '0023A0': '양자컴퓨팅',
    '195930': '유로존ETF',
    '478150': '우주방위',
    '469070': 'AI로봇ETF',
    '487230': '전력인프라',
    '454910': '두산로보틱스',
    '277810': '레인보우로보틱스',
    '069500': 'KOSPI200',
    '009150': '삼성전기',
    '001820': '삼화콘덴서',
    '064400': 'LG씨엔에스',
    '018260': '삼성에스디에스',
    # ── 1차 확장: 한국 AI 주요 종목 ──
    '267260': 'HD현대일렉트릭',
    '010120': 'LS ELECTRIC',
    '298040': '효성중공업',
    '103590': '일진전기',
    '062040': '산일전기',
    '042700': '한미반도체',
    '007810': '코리아써키트',
    '222800': '심텍',
    '067310': '하나마이크론',
    '403870': 'HPSP',
    '240810': '원익IPS',
    '084370': '유진테크',
    '036930': '주성엔지니어링',
    '058470': '리노공업',
    '095340': 'ISC',
    '117730': '티로보틱스',
    '090360': '로보스타',
    '058610': '에스피지',
    '389500': '에스비비테크',
    '053800': '안랩',
    '042510': '라온시큐어',
    '203650': '드림시큐리티',
    '136540': '윈스',
    '328130': '루닛',
    '338220': '뷰노',
    '315640': '딥노이드',
    '322510': 'JLK',
}


def _format_price(price, is_kr: bool) -> str:
    """현재가 표시 — 한국=#,###원 / 미국=#,###달러 (둘 다 소수점 무시)"""
    try:
        if price is None:
            return "-"
        p = float(price)
        if p <= 0 or p != p:   # 0 이하 / NaN
            return "-"
    except Exception:
        return "-"
    if is_kr:
        return f"{int(round(p)):,}원"
    return f"{int(round(p)):,}달러"
KR_NAME_TO_TICKER = {v: k for k, v in KR_TICKER_TO_NAME.items()}


def _fmt_item(raw: str) -> str:
    """
    항목 문자열 → 표시 형식 통일
    - KR 티커(6자리, 영문/숫자 혼합 포함): '반도체ETF(091160)' 형식
    - 이름만 있는 KR: '반도체ETF(091160)' 로 변환
    - 이미 '이름(티커)' 형식: 그대로
    - US 티커: 그대로
    """
    import re
    raw = raw.strip()
    if not raw:
        return raw
    if re.search(r'\(.+\)$', raw):
        return raw
    # 6자리 코드 (숫자 + 영문 혼합 허용, 예: 0051G0)
    if re.match(r'^[A-Za-z0-9]{6}$', raw) and raw in KR_TICKER_TO_NAME:
        name = KR_TICKER_TO_NAME.get(raw, raw)
        return f"{name}({raw})"
    ticker = KR_NAME_TO_TICKER.get(raw)
    if ticker:
        return f"{raw}({ticker})"
    return raw


def _parse_top5_entry_global(entry: str) -> list:
    """멀티라인 셀 → 최대 5개 항목, 표시 형식 통일"""
    lines = [_fmt_item(l) for l in entry.strip().splitlines() if l.strip()]
    return lines[:5]


def _current_week_label() -> str:
    """오늘이 속한 ISO 주차 → 'YYYY.M월N주' (월 = 해당 주의 목요일 기준)."""
    today = date.today()
    # ISO 주차는 목요일 기준이라 월이 안정적이다
    iso_year, iso_week, _ = today.isocalendar()
    thursday = today + timedelta(days=(3 - today.weekday()))
    month = thursday.month
    # 해당 월의 1일이 속한 ISO week 와의 차이로 N주차 계산
    first = date(thursday.year, month, 1)
    first_thu = first + timedelta(days=(3 - first.weekday()) % 7)
    week_in_month = (thursday - first_thu).days // 7 + 1
    return f"{iso_year}.{month}월{week_in_month}주"


def _current_month_label() -> str:
    """오늘 → 'YYYY.MM'"""
    today = date.today()
    return f"{today.year}.{today.month:02d}"


def _ai_daily_top5_lines(data: list, held_list: list) -> list:
    """
    오늘 AI Top5 라인 리스트 (Top5 카드 weekly/monthly 누적용).
    - 우선순위: held_list(buy_list_total_AI.txt) 상위 5개
    - 그래도 5개 미달이면 total_top30_AI.csv 상위에서 AI investable만 채움
    - 각 라인은 _fmt_item() 규칙으로 통일 (KR=이름(코드) / US=티커)
    """
    seen = set()
    lines = []
    for tk in held_list[:5]:
        if tk in seen:
            continue
        seen.add(tk)
        lines.append(_fmt_item(tk))

    if len(lines) < 5:
        for item in data:
            if not item.get("is_ai", False):
                continue
            if item.get("is_benchmark", False):
                continue
            tk = item["ticker"]
            if tk in seen:
                continue
            seen.add(tk)
            if item.get("is_kr") and item.get("name"):
                # name 안의 '이름(rank-suffix)' 에서 suffix 제거
                import re as _re
                clean = _re.sub(r'\([A-Za-z0-9x\-]{4}\)$', '', item["name"]).strip()
                lines.append(f"{clean}({tk})" if clean and clean != tk else tk)
            else:
                lines.append(tk)
            if len(lines) >= 5:
                break
    return lines[:5]


def _upsert_top5_csv(csv_path, label: str, top5_lines: list) -> None:
    """
    헤더 첫 행(라벨 row) + 두 번째 행(셀 데이터) 구조의 CSV에
    '오늘의 label 컬럼'을 upsert.
    - 라벨이 이미 있으면 그 컬럼 데이터를 오늘 top5로 덮어쓴다
    - 없으면 마지막 컬럼 다음에 추가한다
    - 빈 top5 면 아무것도 하지 않는다
    - 파일/디렉토리가 없으면 새로 만든다
    """
    if not top5_lines:
        return
    cell = "\n".join(top5_lines)
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        if csv_path.exists():
            text = csv_path.read_text(encoding="utf-8-sig")
            rows = list(csv.reader(io.StringIO(text)))
        else:
            rows = []

        if len(rows) < 2:
            # 새 파일 / 깨진 파일 → 헤더 + 데이터 row 1개로 시작
            rows = [[label], [cell]]
        else:
            header = rows[0]
            data_row = rows[1]
            # 길이 맞추기
            if len(data_row) < len(header):
                data_row += [""] * (len(header) - len(data_row))
            if label in header:
                idx = header.index(label)
                data_row[idx] = cell
            else:
                header.append(label)
                data_row.append(cell)
            rows[0] = header
            rows[1] = data_row

        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for r in rows:
            writer.writerow(r)
        csv_path.write_text(buf.getvalue(), encoding="utf-8-sig")
    except Exception as e:
        print(f"[Top5 AI CSV 저장 실패] {csv_path.name}: {e}")


def update_ai_top5_history(data: list, held_list: list) -> None:
    """오늘의 AI Top5 를 weekly/monthly AI CSV 에 누적/갱신."""
    top5 = _ai_daily_top5_lines(data, held_list)
    if not top5:
        return
    _upsert_top5_csv(WEEKLY_TOP5_CSV,  _current_week_label(),  top5)
    _upsert_top5_csv(MONTHLY_TOP5_CSV, _current_month_label(), top5)


def get_weekly_top5_global():
    """주간 CSV(AI 전용) 최신 차수 top5 반환 → (label, [표시문자열, ...])"""
    if not WEEKLY_TOP5_CSV.exists():
        return ("", [])
    try:
        import re
        text = WEEKLY_TOP5_CSV.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        # 2행1쌍 블록들 → 모든 주 컬럼을 시간순(오래된→최신)으로 수집.
        #   블록은 '최신월이 맨 위' 저장 → 블록 역순 + 블록내 좌→우(1주→5주) = 전체 시간순.
        #   월초 첫 월요일처럼 '지난주'가 전월 블록에 있어도 정확히 잡힘.
        blocks = []
        for i in range(0, len(rows) - 1, 2):
            labels = [c.strip() for c in rows[i]]
            data   = list(rows[i + 1])
            pairs  = [(lab, data[j]) for j, lab in enumerate(labels)
                      if lab and j < len(data) and data[j].strip()]
            blocks.append(pairs)
        flat = [p for block in reversed(blocks) for p in block]
        if not flat:
            return ("", [])
        # 월요일: 이번 주 집계는 오늘 하루뿐(당일과 동일) → 지난주(완성된 한 주) 표시.
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
    """월간 CSV 현재 연월 top5 반환 → (label, [표시문자열, ...])"""
    if not MONTHLY_TOP5_CSV.exists():
        return ("", [])
    try:
        today = date.today()
        # 그 달 1주차(1~7일)엔 이번 달 집계가 주간 카드와 겹침 → 지난달(완성된 달) 표시.
        #   2주차(8일~)부터 이번 달.
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
    """
    보유 목록 상위 5개 → '이름  티커' (2칸 공백) 형식으로 변환
    name_map: data에서 추출한 {ticker: 정제된name} (추가 이름 소스)
    """
    result = []
    for tk in held_list[:5]:
        # 1순위: data name_map (순위이력 suffix 제거 완료)
        name = (name_map or {}).get(tk)
        # 2순위: 내장 KR 매핑
        if not name:
            name = KR_TICKER_TO_NAME.get(tk)
        # name이 있고 티커와 다를 때만 "이름  티커" 형식
        if name and name != tk:
            result.append(f"{name}  {tk}")
        else:
            result.append(tk)   # US 티커: 그대로
    return result


def _top5_mini_card_global(title: str, label: str, items: list,
                            border_color: str, bg_color: str = "#ffffff") -> str:
    """Global ETF Top5 카드 (5줄)"""
    if not items:
        body = '<div class="t5-empty">데이터 없음</div>'
    else:
        body = ""
        for i, item in enumerate(items[:5]):
            medal = MEDALS_G[i] if i < len(MEDALS_G) else f"#{i+1}"
            item_label = item.strip()
            item_ticker = _extract_display_ticker(item_label)
            item_html = ticker_chart_span(item_ticker, item_label, "t5-name")
            body += (
                f'<div class="t5-row">'
                f'<span class="t5-medal">{medal}</span>'
                f'{item_html}'
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
    """🧾 당일/주간/월간 Top5 카드 섹션 HTML (AI 전용 누적 CSV 사용)"""
    today = date.today()
    # data → ticker:name 맵, 4자리 순위이력 suffix 제거 (당일 이름 조회용)
    # 예: '반도체(1388)' → '반도체', 'PTF(4423)' → 'PTF'
    import re as _re
    name_map = {}
    for item in (data or []):
        clean = _re.sub(r'\([A-Za-z0-9x\-]{4}\)$', '', item["name"]).strip()
        name_map[item["ticker"]] = clean

    # 1) 오늘 AI Top5 를 weekly/monthly AI 전용 CSV에 누적/갱신
    update_ai_top5_history(data or [], held_list)

    # 2) 카드 데이터 로드
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

# ══════════════════════════════════════════════════════════


# ── 유틸 ───────────────────────────────────────────────────
def read_held_list() -> list:
    """buy_list_total.txt → 티커 리스트 (최대 6개)"""
    if not TOP6_FILE.exists():
        return []
    try:
        tickers = TOP6_FILE.read_text(encoding="utf-8").splitlines()
        return [t.strip() for t in tickers if t.strip()]
    except Exception:
        return []


def read_stats() -> dict:
    if not STATS_FILE.exists():
        return {}
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[경고] 통계 JSON 읽기 실패: {e}")
        return {}


def read_ai_basket() -> dict:
    """ai_basket_scores_total_AI.json 읽기"""
    if not AI_BASKET_FILE.exists():
        return {}
    try:
        return json.loads(AI_BASKET_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[경고] AI Basket JSON 읽기 실패: {e}")
        return {}


def _as_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _snapshot_date_from_ai_doc(ai_doc: dict) -> str:
    update_time = str(ai_doc.get("update_time") or "").strip()
    if len(update_time) >= 10:
        head = update_time[:10]
        try:
            datetime.strptime(head, "%Y-%m-%d")
            return head
        except Exception:
            pass
    return date.today().strftime("%Y-%m-%d")


def _extract_basket_score_snapshot(ai_doc: dict) -> dict:
    baskets = {}
    for b in ai_doc.get("baskets", []) or []:
        code = str(b.get("basket") or "").strip()
        score = _as_float(b.get("score"))
        if not code or score is None:
            continue
        baskets[code] = {
            "basket_name_kr": b.get("basket_name_kr") or b.get("basket_kr") or basket_to_kr(code),
            "score": round(score, 2),
            "valid_count": int(b.get("valid_count") or 0),
        }
    return baskets


def update_basket_score_history(ai_doc: dict) -> list:
    """AI basket score를 날짜별로 누적. 같은 날짜는 최신 값으로 덮어쓴다."""
    baskets = _extract_basket_score_snapshot(ai_doc)
    if not baskets:
        return []

    today_key = _snapshot_date_from_ai_doc(ai_doc)
    snapshot = {
        "date": today_key,
        "update_time": ai_doc.get("update_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ai_core_score": _as_float(ai_doc.get("ai_core_score")),
        "ai_core_dedup_score": _as_float(ai_doc.get("ai_core_dedup_score")),
        "ai_breadth_state": ai_doc.get("ai_breadth_state", "-"),
        "baskets": baskets,
    }

    history_doc = {"snapshots": []}
    try:
        if BASKET_SCORE_HISTORY_FILE.exists():
            loaded = json.loads(BASKET_SCORE_HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history_doc["snapshots"] = loaded
            elif isinstance(loaded, dict):
                history_doc["snapshots"] = loaded.get("snapshots", []) or []
    except Exception as e:
        print(f"[경고] AI Basket score history 읽기 실패: {e}")

    by_date = {}
    for old in history_doc.get("snapshots", []):
        d = str(old.get("date") or "").strip()
        if d:
            by_date[d] = old
    by_date[today_key] = snapshot

    snapshots = sorted(by_date.values(), key=lambda x: str(x.get("date", "")))
    snapshots = snapshots[-80:]
    out_doc = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_note": "Compare today with 5 stored snapshots ago when available.",
        "snapshots": snapshots,
    }
    try:
        BASKET_SCORE_HISTORY_FILE.write_text(
            json.dumps(out_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[경고] AI Basket score history 저장 실패: {e}")
    return snapshots


def _fmt_score(value) -> str:
    num = _as_float(value)
    return f"{num:.2f}" if num is not None else "-"


def _fmt_delta(delta) -> tuple[str, str]:
    if delta > 0:
        return f"+{delta:.2f}pt ▲", "flow-up"
    if delta < 0:
        return f"{delta:.2f}pt ▼", "flow-down"
    return "0.00pt", "flow-flat"


def _build_flow_rows(changes: list, direction: str, limit: int = 5) -> str:
    if direction == "up":
        selected = [c for c in changes if c["delta"] > 0][:limit]
    else:
        selected = [c for c in changes if c["delta"] < 0][:limit]

    if not selected:
        return '<div class="flow-empty">변화 없음</div>'

    rows = []
    for c in selected:
        delta_txt, cls = _fmt_delta(c["delta"])
        rows.append(
            '<div class="flow-row">'
            f'<span class="flow-name" title="{escape(c["basket"])}">{escape(c["basket_name_kr"])}</span>'
            f'<span class="flow-delta {cls}">{delta_txt}</span>'
            f'<span class="flow-score">({c["prev_score"]:.2f} → {c["curr_score"]:.2f})</span>'
            '</div>'
        )
    return "\n".join(rows)


def build_ai_basket_weekly_flow(ai_doc: dict) -> str:
    """5개 스냅샷 전 대비 AI basket score 변화 카드."""
    snapshots = update_basket_score_history(ai_doc)
    if not ai_doc:
        return ""
    if len(snapshots) < 2:
        snap_date = _snapshot_date_from_ai_doc(ai_doc)
        return f'''
<div class="basket-flow-card">
  <div class="flow-head">
    <div class="flow-title">📈 AI Basket Weekly Flow</div>
    <div class="flow-window">history starts {escape(snap_date)}</div>
  </div>
  <div class="flow-empty flow-empty-wide">주간 변화 비교용 basket score 이력을 오늘부터 수집합니다.</div>
</div>
'''

    current = snapshots[-1]
    baseline = snapshots[-6] if len(snapshots) >= 6 else snapshots[0]
    current_scores = current.get("baskets", {}) or {}
    prev_scores = baseline.get("baskets", {}) or {}

    changes = []
    for code, cur in current_scores.items():
        curr_score = _as_float(cur.get("score"))
        prev = prev_scores.get(code) or {}
        prev_score = _as_float(prev.get("score"))
        if curr_score is None or prev_score is None:
            continue
        changes.append({
            "basket": code,
            "basket_name_kr": cur.get("basket_name_kr") or basket_to_kr(code),
            "curr_score": curr_score,
            "prev_score": prev_score,
            "delta": round(curr_score - prev_score, 2),
        })

    if not changes:
        return ""

    up_sorted = sorted(changes, key=lambda x: (-x["delta"], x["basket"]))
    down_sorted = sorted(changes, key=lambda x: (x["delta"], x["basket"]))
    up_cnt = sum(1 for c in changes if c["delta"] > 0)
    down_cnt = sum(1 for c in changes if c["delta"] < 0)
    flat_cnt = len(changes) - up_cnt - down_cnt
    core_delta = None
    curr_core = _as_float(current.get("ai_core_score"))
    prev_core = _as_float(baseline.get("ai_core_score"))
    if curr_core is not None and prev_core is not None:
        core_delta = round(curr_core - prev_core, 2)
    core_delta_txt, core_cls = _fmt_delta(core_delta or 0.0)

    if len(snapshots) >= 6:
        window_txt = "5 snapshots ago vs today"
    else:
        window_txt = f"{len(snapshots) - 1} snapshots ago vs today"

    return f'''
<div class="basket-flow-card">
  <div class="flow-head">
    <div class="flow-title">📈 AI Basket Weekly Flow</div>
    <div class="flow-window">{escape(window_txt)}</div>
  </div>
  <div class="flow-meta">
    <span>오늘 {escape(str(current.get("date", "-")))}</span>
    <span>기준 {escape(str(baseline.get("date", "-")))}</span>
    <span>Core <b class="{core_cls}">{core_delta_txt}</b></span>
    <span>상승 {up_cnt} · 하락 {down_cnt} · 보합 {flat_cnt}</span>
  </div>
  <div class="flow-cols">
    <div class="flow-col">
      <div class="flow-subtitle flow-up">상승 Basket</div>
      {_build_flow_rows(up_sorted, "up")}
    </div>
    <div class="flow-col">
      <div class="flow-subtitle flow-down">하락 Basket</div>
      {_build_flow_rows(down_sorted, "down")}
    </div>
  </div>
</div>
'''


def _extract_bottleneck_snapshot(ai_doc: dict) -> dict:
    """ai_doc['ai_bottleneck'] 에서 일일 누적용 스냅샷 추출.

    레이어별 score / state / market_read 헤드라인만 보관 (top_members 같은 큰 필드는 제외).
    """
    bdoc = (ai_doc or {}).get("ai_bottleneck") or {}
    layers_raw = bdoc.get("layers") or []
    layers = {}
    for l in layers_raw:
        code = str(l.get("layer") or "").strip()
        if not code:
            continue
        layers[code] = {
            "name_kr": l.get("name_kr") or code,
            "score":   _as_float(l.get("score")),
            "state":   l.get("state") or "NO_DATA",
        }
    read = bdoc.get("market_read") or {}
    return {
        "layers": layers,
        "headline":   read.get("headline"),
        "location":   read.get("location"),
        "confidence": read.get("confidence"),
    }


def update_bottleneck_history(ai_doc: dict) -> list:
    """AI 병목 레이어 score를 날짜별로 누적. 같은 날짜는 최신 값으로 덮어쓴다.

    반환: 정렬된 snapshots 리스트 (날짜 오름차순, 최대 80개 유지).
    """
    snap_payload = _extract_bottleneck_snapshot(ai_doc)
    if not snap_payload.get("layers"):
        return []

    today_key = _snapshot_date_from_ai_doc(ai_doc)
    snapshot = {
        "date":        today_key,
        "update_time": ai_doc.get("update_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "headline":    snap_payload.get("headline"),
        "location":    snap_payload.get("location"),
        "confidence":  snap_payload.get("confidence"),
        "layers":      snap_payload["layers"],
    }

    history_doc = {"snapshots": []}
    try:
        if BOTTLENECK_HISTORY_FILE.exists():
            loaded = json.loads(BOTTLENECK_HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history_doc["snapshots"] = loaded
            elif isinstance(loaded, dict):
                history_doc["snapshots"] = loaded.get("snapshots", []) or []
    except Exception as e:
        print(f"[경고] AI Bottleneck history 읽기 실패: {e}")

    by_date = {}
    for old in history_doc.get("snapshots", []):
        d = str(old.get("date") or "").strip()
        if d:
            by_date[d] = old
    by_date[today_key] = snapshot

    snapshots = sorted(by_date.values(), key=lambda x: str(x.get("date", "")))
    # AI 사이클 장기관찰용으로 5년치(1825일) 보관. 1 snapshot ≈ 1.3KB → 5년 ≈ 2.4MB.
    snapshots = snapshots[-1825:]
    out_doc = {
        "updated_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_note": "Compare today with 5 stored snapshots ago when available. Retains up to 5 years.",
        "snapshots":   snapshots,
    }
    try:
        BOTTLENECK_HISTORY_FILE.write_text(
            json.dumps(out_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[경고] AI Bottleneck history 저장 실패: {e}")
    return snapshots


def _bottleneck_layer_deltas(snapshots: list) -> tuple[dict, dict, str, str]:
    """현재 vs 5 snapshots 전(없으면 가장 오래된 것) 의 레이어별 score 변화 계산.

    반환: (current_scores, deltas, current_date, baseline_date)
      - current_scores : {layer_code: score}
      - deltas         : {layer_code: round(curr - prev, 2)} (양쪽 다 있을 때만)
    """
    if not snapshots:
        return {}, {}, "-", "-"
    current = snapshots[-1]
    baseline = snapshots[-6] if len(snapshots) >= 6 else snapshots[0]
    cur_layers = current.get("layers", {}) or {}
    prev_layers = baseline.get("layers", {}) or {}

    current_scores = {}
    deltas = {}
    for code, cur in cur_layers.items():
        cs = _as_float(cur.get("score"))
        if cs is not None:
            current_scores[code] = cs
        ps = _as_float((prev_layers.get(code) or {}).get("score"))
        if cs is not None and ps is not None:
            deltas[code] = round(cs - ps, 2)
    return current_scores, deltas, str(current.get("date") or "-"), str(baseline.get("date") or "-")


def _bottleneck_state_class(state: str) -> str:
    state = str(state or "").strip().lower().replace("_", "-")
    return state if state else "no-data"


def build_ai_bottleneck_board(ai_doc: dict) -> str:
    """AI bottleneck map: price/score based layer read, not a news-confirmed diagnosis."""
    if not ai_doc:
        return ""
    doc = ai_doc.get("ai_bottleneck") or {}
    layers = doc.get("layers") or []
    if not layers:
        return ""

    read = doc.get("market_read") or {}
    headline = read.get("headline") or "병목 데이터 부족"
    location = read.get("location") or ""
    interpretation = read.get("interpretation") or ""
    confidence = read.get("confidence") or "LOW"
    confidence_gap = read.get("confidence_gap")
    gap_txt = f"{confidence_gap:+.2f}pt" if isinstance(confidence_gap, (int, float)) else "-"
    note = doc.get("note") or "가격/score 기반 판독입니다."

    # ── 시계열 누적 + 5d Δ 계산 ──
    bneck_snapshots = update_bottleneck_history(ai_doc)
    _, layer_deltas, hist_today, hist_base = _bottleneck_layer_deltas(bneck_snapshots)
    if len(bneck_snapshots) >= 2:
        if len(bneck_snapshots) >= 6:
            hist_window_txt = f"Δ 기준: {hist_base} → {hist_today} (5 snapshots)"
        else:
            hist_window_txt = f"Δ 기준: {hist_base} → {hist_today} ({len(bneck_snapshots)-1} snapshots)"
    else:
        hist_window_txt = f"이력 수집 시작: {hist_today}"

    layer_by_code = {str(l.get("layer")): l for l in layers}
    flow_order = [
        "DEMAND_CAPEX",
        "SILICON_COMPUTE",
        "MEMORY_PACKAGING",
        "NETWORK_OPTICS",
        "POWER_COOLING",
        "DATACENTER_DEPLOY",
    ]
    table_order = flow_order + ["SOFTWARE_ADOPTION"]

    flow_chunks = []
    for i, code in enumerate(flow_order):
        layer = layer_by_code.get(code, {})
        score = _as_float(layer.get("score"))
        score_txt = f"{score:.2f}" if score is not None else "-"
        state = layer.get("state") or "NO_DATA"
        state_kr = layer.get("state_kr") or "-"
        active_cls = " bneck-active" if code == location else ""
        flow_chunks.append(
            '<div class="bneck-node{active_cls}">'
            '<div class="bneck-node-name">{name}</div>'
            '<div class="bneck-node-score">{score}</div>'
            '<div class="bneck-pill bneck-{state_cls}">{state_kr}</div>'
            '</div>'.format(
                active_cls=active_cls,
                name=escape(str(layer.get("name_kr") or code)),
                score=escape(score_txt),
                state_cls=_bottleneck_state_class(state),
                state_kr=escape(str(state_kr)),
            )
        )
        if i < len(flow_order) - 1:
            flow_chunks.append('<div class="bneck-arrow">→</div>')

    rows = []
    for code in table_order:
        layer = layer_by_code.get(code)
        if not layer:
            continue
        score = _as_float(layer.get("score"))
        score_txt = f"{score:.2f}" if score is not None else "-"
        state = layer.get("state") or "NO_DATA"
        state_kr = layer.get("state_kr") or "-"
        top_basket = layer.get("top_basket_kr") or "-"
        top_basket_score = _as_float(layer.get("top_basket_score"))
        if top_basket_score is not None:
            top_basket = f"{top_basket} ({top_basket_score:.2f})"

        # 5d Δ 셀 (history 가 충분히 쌓였을 때만 표시)
        delta_val = layer_deltas.get(code)
        if delta_val is None:
            delta_html = '<span style="color:#bbb;">-</span>'
        elif delta_val > 0:
            delta_html = f'<span class="bneck-delta bneck-delta-up">+{delta_val:.2f} ▲</span>'
        elif delta_val < 0:
            delta_html = f'<span class="bneck-delta bneck-delta-down">{delta_val:.2f} ▼</span>'
        else:
            delta_html = '<span class="bneck-delta bneck-delta-flat">0.00</span>'

        leaders = []
        for m in (layer.get("leaders") or [])[:4]:
            tk = str(m.get("ticker") or "").strip()
            if not tk:
                continue
            label = str(m.get("display") or m.get("name") or tk)
            sco = _as_float(m.get("Signal_sco"))
            if sco is not None:
                label = f"{label}({sco:.1f})"
            leaders.append(ticker_chart_span(tk, label, "bneck-member"))
        leaders_html = " ".join(leaders) if leaders else '<span style="color:#aaa;">-</span>'
        active_row = ' class="bneck-table-active"' if code == location else ""
        rows.append(
            f'<tr{active_row}>'
            f'<td><b>{escape(str(layer.get("name_kr") or code))}</b><div class="bneck-layer-code">{escape(code)}</div></td>'
            f'<td style="text-align:right;font-weight:bold;">{score_txt}</td>'
            f'<td style="text-align:right;">{delta_html}</td>'
            f'<td><span class="bneck-pill bneck-{_bottleneck_state_class(state)}">{escape(str(state_kr))}</span></td>'
            f'<td>{escape(str(top_basket))}</td>'
            f'<td>{leaders_html}</td>'
            f'<td class="bneck-note-cell">{escape(str(layer.get("note") or ""))}</td>'
            '</tr>'
        )

    return f'''
<div class="bneck-card">
  <div class="bneck-head">
    <div>
      <div class="bneck-eyebrow">AI Bottleneck Map</div>
      <div class="bneck-title">오늘의 병목 추정: {escape(str(headline))}</div>
      <div class="bneck-sub">{escape(str(interpretation))}</div>
    </div>
    <div class="bneck-confidence">
      <span>신뢰도 {escape(str(confidence))}</span>
      <b>{escape(gap_txt)}</b>
    </div>
  </div>
  <div class="bneck-footnote">{escape(str(note))} &nbsp;·&nbsp; <span style="color:#5f6b76;">{escape(hist_window_txt)}</span></div>
  <div class="bneck-flow">{''.join(flow_chunks)}</div>
  <table class="styled-table bneck-table">
    <thead><tr><th>Layer</th><th>Score</th><th>5d Δ</th><th>상태</th><th>Top Basket</th><th>Top Members</th><th>해석</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>
'''


def build_ai_core_card(ai_doc: dict) -> str:
    """AI Core Regime 요약 카드 HTML 생성 (Raw/Dedup/Gap + Breadth state + Duplicate Impact)"""
    if not ai_doc:
        return ('<div class="ai-core-card" style="background:#fff5f5;border:1px solid #e57373;'
                'padding:10px;border-radius:8px;margin:10px 0;">'
                '<b style="color:#c0392b;">⚠️ AI Basket 데이터 없음</b> '
                '<span style="color:#777;font-size:0.85em;">— '
                'ai_basket_scores_total_AI.json을 찾을 수 없습니다.</span>'
                '</div>')

    core_score      = ai_doc.get("ai_core_score")
    core_dedup      = ai_doc.get("ai_core_dedup_score")
    core_gap        = ai_doc.get("ai_core_gap")
    core_state      = ai_doc.get("ai_core_state", "-")
    breadth_state   = ai_doc.get("ai_breadth_state", "-")
    breadth_s       = ai_doc.get("ai_breadth_strong", 0)
    breadth_m       = ai_doc.get("ai_breadth_mid", 0)
    breadth_w       = ai_doc.get("ai_breadth_weak", 0)
    breadth_n       = ai_doc.get("ai_breadth_negative", 0)
    valid_cnt       = ai_doc.get("valid_basket_count", 0)
    basket_cnt      = ai_doc.get("basket_count", 32)
    top_baskets     = ai_doc.get("top_ai_baskets", [])
    dup             = ai_doc.get("duplicate_impact", {}) or {}
    dup_ratio       = dup.get("duplicate_ratio")
    dup_level       = dup.get("duplicate_level", "-")
    unique_cnt      = dup.get("unique_ticker_count", 0)
    top_contribs    = dup.get("top_contributors", []) or []
    top_contrib_lead = dup.get("top_contributor")
    top_contrib_cnt  = dup.get("top_contributor_count", 0)

    # Core 상태 색상
    if   core_state == "AI Very Strong":   core_bg = "#16a34a"
    elif core_state == "AI Strong":        core_bg = "#2ecc71"
    elif core_state == "AI Constructive":  core_bg = "#3498db"
    elif core_state == "AI Weak":          core_bg = "#e67e22"
    elif core_state == "AI Risk-Off":      core_bg = "#e74c3c"
    else:                                  core_bg = "#95a5a6"

    # Breadth 상태 색상
    if   breadth_state == "Healthy":  breadth_bg = "#16a34a"
    elif breadth_state == "Mixed":    breadth_bg = "#d97706"
    elif breadth_state == "Negative": breadth_bg = "#dc2626"
    else:                              breadth_bg = "#95a5a6"

    # Duplicate 레벨 색상
    if   dup_level == "낮음":      dup_color = "#16a34a"
    elif dup_level == "보통":      dup_color = "#d97706"
    elif dup_level == "높음":      dup_color = "#e67e22"
    elif dup_level == "매우높음":  dup_color = "#dc2626"
    else:                          dup_color = "#95a5a6"

    core_score_txt = f"{core_score:.2f}" if isinstance(core_score, (int, float)) else "-"
    core_dedup_txt = f"{core_dedup:.2f}" if isinstance(core_dedup, (int, float)) else "-"
    core_gap_txt   = f"{core_gap:+.2f}"  if isinstance(core_gap, (int, float))   else "-"
    dup_pct_txt    = f"{dup_ratio*100:.1f}%" if isinstance(dup_ratio, (int, float)) else "-"

    # Top contributors 요약 (최대 3명)
    if top_contribs:
        contrib_chunks = []
        for c in top_contribs[:3]:
            tk_v  = c.get("ticker", "?")
            cnt_v = int(c.get("count", 0))
            contrib_chunks.append(f"{tk_v}×{cnt_v}")
        contrib_summary = " / ".join(contrib_chunks)
    else:
        contrib_summary = "-"

    # Top AI Baskets — 한글명만 표시 (영문 코드는 hover title로만 유지)
    top_basket_html = ""
    for i, b in enumerate(top_baskets[:5]):
        bname_en = b.get("basket", "?")
        bname_kr = b.get("basket_name_kr") or b.get("basket_kr") or basket_to_kr(bname_en)
        bs    = b.get("score")
        bcnt  = b.get("valid_count", 0)
        bs_txt = f"{bs:.2f}" if isinstance(bs, (int, float)) else "-"
        # display:contents 로 row wrapper 를 투명화 → 부모 grid 의 컬럼 폭이 통일됨
        top_basket_html += (
            f'<div class="ai-top-row" title="{bname_en}">'
            f'<span class="ai-top-rank">#{i+1}</span>'
            f'<span class="ai-top-name">{bname_kr}</span>'
            f'<span class="ai-top-score">{bs_txt}</span>'
            f'<span class="ai-top-cnt">{bcnt}</span>'
            f'</div>'
        )
    if not top_basket_html:
        top_basket_html = '<div style="color:#888;font-size:0.85em;">basket 데이터 없음</div>'

    return f'''
<div class="ai-core-card">
  <div class="ai-core-left">
    <div class="ai-core-label">🤖 AI Core Regime</div>
    <div class="ai-core-score" style="color:{core_bg};">{core_score_txt}</div>
    <div class="ai-core-state-row">
      <span class="ai-core-state" style="background:{core_bg};">{core_state}</span>
      <span class="ai-core-state ai-breadth-state" style="background:{breadth_bg};">Breadth {breadth_state}</span>
    </div>
    <div class="ai-core-rdg" title="Raw = Top10 basket 평균 / Dedup = 중복 ticker 1회만 카운트한 보정 / Gap이 클수록 특정 종목 의존">
      <span class="ai-rdg-cell"><span class="ai-rdg-lbl">Raw</span><span class="ai-rdg-val">{core_score_txt}</span></span>
      <span class="ai-rdg-cell"><span class="ai-rdg-lbl">Dedup</span><span class="ai-rdg-val">{core_dedup_txt}</span></span>
      <span class="ai-rdg-cell"><span class="ai-rdg-lbl">Gap</span><span class="ai-rdg-val">{core_gap_txt}</span></span>
    </div>
    <div class="ai-core-breadth">
      <span class="ai-b-strong">강 {breadth_s}</span>
      <span class="ai-b-mid">중 {breadth_m}</span>
      <span class="ai-b-weak">약 {breadth_w}</span>
      <span class="ai-b-neg">음 {breadth_n}</span>
    </div>
    <div class="ai-core-dup" title="Top10 basket의 top members 펼쳐서 ticker 등장횟수 분석">
      <span style="color:#555;">중복영향</span>
      <span class="ai-dup-pill" style="background:{dup_color};">{dup_level} {dup_pct_txt}</span>
      <span class="ai-core-dup-meta">고유 {unique_cnt}</span>
    </div>
    <div class="ai-core-dup-contrib" title="가장 많이 등장한 ticker (Top10 basket 기준)">
      핵심기여: <b>{contrib_summary}</b>
    </div>
    <div class="ai-core-meta">유효 basket {valid_cnt} / {basket_cnt}</div>
  </div>
  <div class="ai-core-right">
    <div class="ai-top-title">🏆 Top AI Baskets</div>
    <div class="ai-top-list">{top_basket_html}</div>
    <div class="ai-core-help">
      <b>Raw</b> 핵심 AI 주도주 강도 ·
      <b>Dedup</b> AI 생태계 확산 강도 ·
      <b>Gap</b> 소수 핵심 종목 의존도
    </div>
  </div>
</div>
'''


def build_ai_basket_table(ai_doc: dict):
    """AI Basket 32개 랭킹 표

    반환: (html, hot_member_count, total_member_count)
      - hot_member_count : Top Members 칸에 표시된 Signal_sco ≥ 12 종목 수 (빨간색)
      - total_member_count : Top Members 칸에 표시된 전체 종목 수
    """
    if not ai_doc:
        return '<p style="color:#7f8c8d;">AI Basket 데이터 없음</p>', 0, 0
    baskets = ai_doc.get("baskets", [])
    if not baskets:
        return '<p style="color:#7f8c8d;">basket 없음</p>', 0, 0

    rows = []
    rank = 0
    hot_member_total = 0
    member_total = 0
    for b in baskets:
        bname_en  = b.get("basket", "?")
        bname_kr  = b.get("basket_name_kr") or b.get("basket_kr") or basket_to_kr(bname_en)
        score     = b.get("score")
        top3_avg  = b.get("top3_avg")
        all_avg   = b.get("all_avg")
        valid_cnt = b.get("valid_count", 0)
        members   = b.get("top_members", [])

        if isinstance(score, (int, float)):
            rank += 1
            score_txt    = f"{score:.2f}"
            top3_txt     = f"{top3_avg:.2f}" if isinstance(top3_avg, (int, float)) else "-"
            all_txt      = f"{all_avg:.2f}"  if isinstance(all_avg, (int, float))  else "-"
            if   score >= 14: row_bg = "#d5f5e3"  # very strong
            elif score >= 11: row_bg = "#fef9e7"  # strong
            elif score >= 8:  row_bg = "#fff4e0"  # mid
            elif score >= 0:  row_bg = "#fafafa"  # weak
            else:             row_bg = "#fadbd8"  # neg
            rank_txt = str(rank)
        else:
            score_txt = top3_txt = all_txt = "-"
            row_bg = "#f4f4f4"
            rank_txt = "-"

        # Top member 표시 (max 5) — Signal_sco >= 12 는 빨간색 강조 (핵심 AI 종목 식별용)
        member_chunks = []
        for m in members[:5]:
            mtk    = m.get("ticker", "")
            mname  = m.get("name", mtk)
            msco   = m.get("Signal_sco")
            sco_txt = f"{msco:.1f}" if isinstance(msco, (int, float)) else "-"
            is_hot = isinstance(msco, (int, float)) and msco >= 12
            cls = "ai-member ai-member-hot" if is_hot else "ai-member"
            member_label = f"{mname}({sco_txt})"
            member_chunks.append(ticker_chart_span(mtk, member_label, cls))
            member_total += 1
            if is_hot:
                hot_member_total += 1
        members_html = " ".join(member_chunks) if member_chunks else '<span style="color:#aaa;">데이터 없음</span>'

        # 한글명 메인 + 영문 코드 보조(작게 괄호)
        basket_cell = (
            f'<div class="ai-basket-name">'
            f'<span class="ai-basket-kr">{bname_kr}</span>'
            f'<span class="ai-basket-en">({bname_en})</span>'
            f'</div>'
        )

        rows.append(
            f'<tr style="background:{row_bg};">'
            f'<td style="text-align:center;font-weight:bold;">{rank_txt}</td>'
            f'<td>{basket_cell}</td>'
            f'<td style="text-align:right;font-weight:bold;">{score_txt}</td>'
            f'<td style="text-align:right;">{top3_txt}</td>'
            f'<td style="text-align:right;">{all_txt}</td>'
            f'<td style="text-align:center;">{valid_cnt}</td>'
            f'<td>{members_html}</td>'
            f'</tr>'
        )

    html = (
        '<table class="styled-table ai-basket-table">'
        '<thead><tr>'
        '<th>Rank</th><th>Basket</th><th>Score</th><th>Top3 Avg</th>'
        '<th>All Avg</th><th>Valid</th><th>Top Members (Signal_sco)</th>'
        '</tr></thead>'
        '<tbody>'
        + '\n'.join(rows)
        + '</tbody></table>'
    )
    return html, hot_member_total, member_total


def read_low_signals() -> dict:
    """저점 신호 JSON 읽기 (AI 전용 파일에서만; 기존 파일은 읽지 않음)"""
    low_signal_file = Path(r"D:\py\report-us\global_etf_low_signals_AI.json")
    if not low_signal_file.exists():
        return {}
    try:
        data = json.loads(low_signal_file.read_text(encoding="utf-8"))
        result = {}
        for sig in data.get('signals', []):
            ticker = sig.get('ticker', '')
            jeo = sig.get('jeo', '-')
            jeo2 = sig.get('jeo2', '-')
            result[ticker] = (jeo, jeo2)
        return result
    except Exception as e:
        print(f"[경고] 저점 신호 JSON 읽기 실패: {e}")
        return {}


# ── 저점 신호 5일 추적 ────────────────────────────────────
def load_low_history() -> dict:
    """저점 이력 JSON 읽기"""
    if not LOW_HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(LOW_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[경고] 저점 이력 JSON 읽기 실패: {e}")
        return {}


def update_low_history(data: list) -> dict:
    """
    저점 신호 이력 업데이트 및 저장
    - 7일 초과 항목 자동 삭제
    - 새 신호 감지 시 리셋 (first_date 갱신)
    - 같은 신호 패턴 지속 시 날짜 유지 (카운팅 계속)
    Returns: 업데이트된 history dict
    """
    today     = datetime.now().date()
    today_str = today.isoformat()
    history   = load_low_history()

    # 1. 7일 초과 항목 삭제
    to_delete = []
    for ticker, rec in history.items():
        try:
            first_date    = datetime.fromisoformat(rec["first_date"]).date()
            days_elapsed  = (today - first_date).days
            if days_elapsed > 7:
                to_delete.append(ticker)
        except Exception:
            to_delete.append(ticker)
    for ticker in to_delete:
        del history[ticker]

    # 2. 현재 CSV 신호로 이력 업데이트
    for item in data:
        ticker    = item["ticker"]
        jeo       = item.get("jeo", "-")
        jeo2      = item.get("jeo2", "-")
        new_jeo   = (jeo  != "-" and str(jeo).strip()  not in ("", "-", "0", "nan"))
        new_jeo2  = (jeo2 != "-" and str(jeo2).strip() not in ("", "-", "0", "nan"))
        has_signal = new_jeo or new_jeo2

        if has_signal:
            if ticker in history:
                rec      = history[ticker]
                old_jeo  = rec.get("signal_jeo",  False)
                old_jeo2 = rec.get("signal_jeo2", False)
                # 신호 패턴이 달라지면 리셋 (새 신호)
                if new_jeo != old_jeo or new_jeo2 != old_jeo2:
                    history[ticker] = {
                        "first_date":  today_str,
                        "signal_jeo":  new_jeo,
                        "signal_jeo2": new_jeo2,
                    }
                # 같은 패턴 → 날짜 유지 (카운팅 계속)
            else:
                # 신규 신호 추가
                history[ticker] = {
                    "first_date":  today_str,
                    "signal_jeo":  new_jeo,
                    "signal_jeo2": new_jeo2,
                }

    # 3. 저장
    LOW_HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return history


def get_low_badge(ticker: str, history: dict) -> str:
    """
    이력 기반 저점 뱃지 반환
    - Day 0 : 저(초록) / 저2(파랑) / 저1,2(빨강)
    - Day 1~5: N저(회색)
    - Day 6+ : 빈 문자열
    """
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

    return ""  # 6일 이상 → 표시 안 함


def char_to_rank(c: str):
    """rank_to_char 역변환: 문자 → 순위 정수. x/-이면 None 반환"""
    if c in ('x', '-'):
        return None
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return 10 + (ord(c.upper()) - ord('A'))
    return None


def is_rank_rising(name: str) -> bool:
    """
    name 칼럼의 (xxxx) 4자리 순위 이력 조건 체크.
    순서: [0]=오늘, [1]=전날, [2]=전전날, [3]=전전전날
    조건1) x 없을 것
    조건2) 오늘 <= 전날 <= 전전날 <= 전전전날 (숫자 작을수록 순위 높음)
    조건3) 오늘/전날/전전날 중 5위 이내인 날은 순위 밀림 허용
    조건4) 오늘 순위가 1~3이면 무조건 OK
    """
    import re
    m = re.search(r'\(([A-Za-z0-9x\-]{4})\)$', name)
    if not m:
        return False
    code = m.group(1)
    ranks = [char_to_rank(c) for c in code]  # [오늘, 전날, 전전날, 전전전날]

    # 조건1: x 없을 것
    if any(r is None for r in ranks):
        return False

    today, d1, d2, d3 = ranks

    # 조건4: 오늘 top3이면 무조건 OK
    if today <= 3:
        return True

    # 조건2+3 체크
    # 조건3: 당일/전날/전전날 (앞 3자리) 모두 5위 이내일 때만 밀림 허용
    top3days_all_in_top5 = (today <= 5 and d1 <= 5 and d2 <= 5)

    pairs = [
        (today, d1),   # 오늘 vs 전날
        (d1,    d2),   # 전날 vs 전전날
        (d2,    d3),   # 전전날 vs 전전전날
    ]
    for cur, prev in pairs:
        if cur <= prev:
            continue                      # 순위 개선 or 유지 → OK
        if top3days_all_in_top5:
            continue                      # 조건3: 앞 3자리 모두 5이하면 밀림 허용
        return False                      # 순위 밀림 + 조건3 미해당 → 탈락
    return True


def build_name_cell(item: dict) -> str:
    """
    Name 칼럼 HTML 생성.
    - 미국 ETF: 순위 4자리만 표시
    - 한국 ETF: name 그대로 표시
    - 조건 만족 시 빨간색, 아니면 검은색
    """
    import re
    name = item["name"]
    rising = is_rank_rising(name)
    color = "#e74c3c" if rising else "#2c3e50"

    if not item["is_kr"]:
        # 미국 ETF: 괄호 안 순위 4자리만 추출
        m = re.search(r'\(([A-Za-z0-9x\-]{4})\)$', name)
        display = m.group(1) if m else name
    else:
        display = name

    if rising:
        display = display + "★"

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
                # KR 코드: 6자리, 첫 2자리는 숫자 (예: 091160, 0051G0)
                is_kr = (len(ticker) == 6 and ticker[:2].isdigit())
                rtn_raw    = row.get("수익률(%)") or row.get("3M(%)", "0")
                rtn1m_raw  = row.get("수익률20(%)", "")
                sco_raw    = row.get("Signal_sco") or row.get("score", "0")
                score_raw  = row.get("Final_score") or row.get("Score", "0")
                name_raw   = row.get("산업") or row.get("종목명", "")
                # 추가 컬럼 (있으면 읽기, 없으면 빈 문자열)
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
                # AI 전용 신규 컬럼
                ai_basket_raw   = row.get("AI_Basket", "")
                is_ai_raw       = row.get("Is_AI", "")
                is_bench_raw    = row.get("Is_Benchmark", "")
                # 당일종가 (현재가 표시용; scanner 가 채워준 csv 컬럼)
                close_raw       = row.get("당일종가", "")
                try:    rtn         = float(rtn_raw)
                except: rtn         = 0.0
                try:    rtn1m       = float(rtn1m_raw)
                except: rtn1m       = None
                try:    sco         = float(sco_raw)
                except: sco         = 0.0
                try:    score_final = float(score_raw)
                except: score_final = 0.0
                try:    chg         = float(str(chg_raw).replace('%','').strip())
                except: chg         = None
                try:    idx_rel     = float(idx_rel_raw)
                except: idx_rel     = None
                try:    fire        = int(fire_raw) if str(fire_raw).strip() in ("0","1") else 0
                except: fire        = 0
                try:    avg136      = float(avg136_raw)
                except: avg136      = None
                try:    close_today = float(close_raw)
                except: close_today = None
                # Is_AI / Is_Benchmark: bool 문자열 → bool
                _is_ai_bool   = str(is_ai_raw).strip().lower() in ("true", "1", "yes")
                _is_bench_bool = str(is_bench_raw).strip().lower() in ("true", "1", "yes")
                data.append({
                    "ticker":      ticker,
                    "name":        name_raw.strip(),
                    "rtn":         rtn,
                    "rtn1m":       rtn1m,
                    "sco":         sco,
                    "score_final": score_final,
                    "chg":         chg,
                    "pos":         str(pos_raw).strip(),
                    "jeo":         str(jeo_raw).strip(),
                    "jeo2":        str(jeo2_raw).strip(),
                    "inv3":        int(inv3_raw) if str(inv3_raw).strip() in ("0","1") else 0,
                    "fire":        fire,
                    "idx_rel":     idx_rel,
                    "rsi":         str(rsi_raw).strip(),
                    "trend":       str(trend_raw).strip(),
                    "avg136":      avg136,
                    "type":        "KR" if is_kr else "US",
                    "is_kr":       is_kr,
                    "intensity":   is_intensity,
                    "ai_basket":   str(ai_basket_raw).strip(),
                    "is_ai":       _is_ai_bool,
                    "is_benchmark": _is_bench_bool,
                    "close_today": close_today,
                })
    except Exception as e:
        print(f"[오류] CSV 읽기 실패: {e}")
    return data


# ── multiplier 타입 판별 ──────────────────────────────────
def get_mult_type(ticker: str, is_kr: bool) -> str:
    """KOSPI / FIXED / NASDAQ 중 하나 반환"""
    if is_kr:
        return "KOSPI"
    if ticker.upper() in FIXED_ONE_TICKERS:
        return "FIXED"
    return "NASDAQ"


# ── 주문용 최종 보유 목록 테이블 생성 ─────────────────────
def build_final_order_table(held_list: list, data: list, s_data: dict) -> str:
    """
    컬럼: 티커 / 산업 / 등락% / 위치 / Sco / 비중%
    - data: read_data() 결과 (dict list)
    - s_data: kr_signal_stats_total.json
    """
    if not held_list:
        return '<p style="color:#7f8c8d;">보유 종목 없음 (현금 100%)</p>'

    # CSV 데이터를 ticker 키로 인덱싱
    data_map = {item["ticker"]: item for item in data}

    # 비중 계산 재료
    internal_weights = s_data.get("internal_weights", [])   # top3 내부비중 (%, 합=100)
    final_ratios     = s_data.get("final_ratios", {})       # (신규 softcap) 실 투자비중 딕셔너리
    top3_tickers     = s_data.get("top3_tickers", [])       # top3 티커 목록
    k_mult           = s_data.get("kospi_mult", 0)
    us_mult          = s_data.get("nasdaq_mult", 0)

    alloc_pct = {}
    for i, tk in enumerate(held_list):
        if final_ratios and tk in final_ratios:
            alloc_pct[tk] = final_ratios[tk]
        else:
            w    = internal_weights[i] / 100.0 if i < len(internal_weights) else 0
            item = data_map.get(tk, {})
            mtype = get_mult_type(tk, item.get("is_kr", tk.isdigit() and len(tk) == 6))
            if   mtype == "KOSPI":  mult = float(k_mult) if k_mult != "-" else 0.0
            elif mtype == "FIXED":  mult = 1.0
            else:                   mult = float(us_mult) if us_mult != "-" else 0.0
            alloc_pct[tk] = w * mult * 100

    # ── 현재가 미리 조회 (한국 상장이면 pykrx, 아니면 yfinance) ──
    # 분류(is_kr)와 별개로, 한국증시 상장(6자리 + 앞2자리 숫자) 티커는 pykrx로 조회
    # 예: 0048K0(중로봇), 0051G0(에셈알) 등 — 구성종목은 해외지만 한국 상장
    price_map = {}
    for tk in held_list:
        use_krx_price = len(tk) == 6 and tk[:2].isdigit()
        live_price = _get_kor_price(tk) if use_krx_price else _get_us_price(tk)
        if live_price is None:
            live_price = data_map.get(tk, {}).get("close_today")
        price_map[tk] = live_price

    rows_html = []
    rebalancing_rows = []
    for tk in held_list:
        item = data_map.get(tk)

        if item is None:
            rows_html.append(
                f'<tr>'
                f'<td class="narrow held-bold">{tk}</td>'
                f'<td colspan="9" style="color:#999;">데이터 없음</td>'
                f'</tr>'
            )
            continue

        # 등락% 셀
        chg     = item.get("chg")
        if chg is not None:
            chg_str = f"{chg:+.1f}%"
            chg_cls = "sig-up" if chg > 0 else ("sig-down" if chg < 0 else "")
        else:
            chg_str = "-"
            chg_cls = ""

        # 위치 뱃지
        pos_str = item.get("pos", "-")
        if pos_str in ("1","2","3","4","5"):
            pos_html = f'<span class="pos-badge pos-{pos_str}">{pos_str}</span>'
        else:
            pos_html = pos_str or "-"

        # sco
        sco_str = f"{item['sco']:.1f}"

        # 비중%
        pct_val = alloc_pct.get(tk, 0)
        if pct_val >= 25:
            pct_color = "#27ae60"
        elif pct_val >= 15:
            pct_color = "#e67e22"
        else:
            pct_color = "#e74c3c"

        # 기본비중 계산 (allocation_map_used 기반)
        alloc_map    = s_data.get("allocation_map_used", [])
        tk_index     = list(held_list).index(tk) if tk in held_list else -1
        base_pct_val = alloc_map[tk_index] if (alloc_map and 0 <= tk_index < len(alloc_map)) else None

        # 실비중 vs 기본비중 비교 표시
        if base_pct_val is not None and abs(pct_val - float(base_pct_val)) >= 0.1:
            pct_display = (
                f'{pct_val:.1f}% '
                f'<span style="color:#aaa;font-size:0.82em;font-weight:normal;">({base_pct_val}%)</span>'
            )
        else:
            pct_display = f'{pct_val:.1f}%'

        # 지수대비%
        idx_rel = item.get("idx_rel")
        if idx_rel is not None:
            idx_rel_str = f"{idx_rel:+.1f}%"
            idx_rel_cls = "sig-up" if idx_rel > 0 else ("sig-down" if idx_rel < 0 else "")
        else:
            idx_rel_str = "-"
            idx_rel_cls = ""

        ticker_display = tk + ("**" if item.get("intensity") else "")

        # 수량 셀: 기준금액 × 종목비중% / 현재가 (소수점 버림)
        is_kr = item.get("is_kr", tk.isdigit() and len(tk) == 6)
        # 가격 단위는 가격 조회 출처(pykrx=KRW / yfinance=USD)를 따라가야 한다
        use_krx_price = len(tk) == 6 and tk[:2].isdigit()
        price = price_map.get(tk)
        pct_for_qty = alloc_pct.get(tk, 0)
        if ASSET_8042 > 0 and price and price > 0 and pct_for_qty > 0:
            if use_krx_price:
                qty = int(ASSET_8042 * pct_for_qty / 100 / price)
                pension_qty = int(PENSION_ASSET * pct_for_qty / 100 / price)
                qty_krw = qty * price
                pension_krw = pension_qty * price
            else:
                qty = int(ASSET_8042 * pct_for_qty / 100 / USD_KRW / price)
                pension_qty = int(PENSION_ASSET * pct_for_qty / 100 / USD_KRW / price)
                qty_krw = qty * price * USD_KRW
                pension_krw = pension_qty * price * USD_KRW
            qty_disp = f'{qty:,}주' if qty > 0 else '-'
            pension_qty_disp = f'{pension_qty:,}주' if pension_qty > 0 else '-'
            qty_amt_disp = f'{int(qty_krw / 10000):,}만원' if qty > 0 else '-'
            pension_amt_disp = f'{int(pension_krw / 10000):,}만원' if pension_qty > 0 else '-'
            if qty > 0:
                rebalancing_rows.append(f"{tk},{qty}")
        else:
            qty_disp = '-'
            pension_qty_disp = '-'
            qty_amt_disp = '-'
            pension_amt_disp = '-'

        if is_kr:
            # 한국 ticker: 코드(이름) 형식으로 가독성 강화 (요청 4번)
            kr_name = KR_TICKER_TO_NAME.get(tk, "")
            tk_display = f"{tk}({kr_name})" if kr_name else tk
            if item.get("intensity"):
                tk_display += "**"
            order_ticker_td = (
                f'<td class="narrow held-bold naver-trigger" data-code="{tk}" '
                f'style="cursor:pointer;">{tk_display}</td>'
            )
        else:
            order_ticker_td = (
                f'<td class="narrow held-bold chart-trigger" data-ticker="{tk}" '
                f'style="cursor:pointer;">{ticker_display}</td>'
            )

        # Name 컬럼 → Basket 컬럼 (요청 4번)
        basket_kr_str = baskets_pipe_to_kr(item.get("ai_basket", ""), max_show=3)

        # 현재가 셀 (등락률 왼쪽). price_map[live] 우선 → 없으면 CSV 당일종가 fallback.
        live_price = price_map.get(tk)
        if live_price is None or (isinstance(live_price, float) and (live_price != live_price)):
            live_price = item.get("close_today")
        price_disp = _format_price(live_price, is_kr=is_kr)

        rows_html.append(
            f'<tr>'
            + order_ticker_td +
            f'<td class="basket-col held-bold">{basket_kr_str}</td>'
            f'<td style="font-weight:bold;color:#2c3e50;">{price_disp}</td>'
            f'<td class="{chg_cls}">{chg_str}</td>'
            f'<td>{pos_html}</td>'
            f'<td>{sco_str}</td>'
            f'<td style="color:{pct_color};font-weight:bold;">{pct_display}</td>'
            f'<td class="{idx_rel_cls}">{idx_rel_str}</td>'
            f'<td style="font-weight:bold;">{qty_disp}</td>'
            f'<td class="pc-only" style="color:#555;">{qty_amt_disp}</td>'
            f'<td style="font-weight:bold;color:#8e44ad;">{pension_qty_disp}</td>'
            f'<td class="pc-only" style="color:#8e44ad;">{pension_amt_disp}</td>'
            f'</tr>'
        )

    try:
        REBALANCING_TXT.write_text("\n".join(rebalancing_rows), encoding="utf-8")
        print(f"[리밸런싱] 저장: {REBALANCING_TXT} ({len(rebalancing_rows)}개 종목)")
    except Exception as e:
        print(f"[리밸런싱 저장 실패] {e}")

    table_html = (
        '<table class="styled-table final-order-table">'
        '<thead><tr>'
        '<th>Ticker</th>'
        '<th>Basket</th>'
        '<th>현재가</th>'
        '<th>등락률(%)</th>'
        '<th>위치</th>'
        '<th>Sco</th>'
        '<th>비중</th>'
        '<th>지수대비(%)</th>'
        '<th>수량</th>'
        '<th class="pc-only">총액</th>'
        '<th>연금</th>'
        '<th class="pc-only">총액</th>'
        '</tr></thead>'
        '<tbody>\n'
        + '\n'.join(rows_html)
        + '\n</tbody></table>\n'
    )
    return table_html


# ── 벤치마크 표시 + 통계 박스 생성 ────────────────────────
def build_stats_html(s_data: dict) -> str:
    """
    컬럼:
      - 코스피, 코스닥, S&P500, 나스닥, 닉케이, 유로, 인도
      - 투자비중, top3 평균 sco/pos, multiplier 등 통계
    """
    k_trend      = s_data.get("kospi_trend", "-")
    kd_trend     = s_data.get("kosdaq_trend", "-")
    sp_trend     = s_data.get("sp500_trend", "-")
    us_trend     = s_data.get("nasdaq_trend", "-")
    nikkei_trend = s_data.get("nikkei_trend", "-")
    euro_trend   = s_data.get("euro_trend", "-")
    india_trend  = s_data.get("india_trend", "-")
    k_mult       = s_data.get("kospi_mult", "-")
    us_mult      = s_data.get("nasdaq_mult", "-")
    invest_pct   = s_data.get("invest_pct", 0)
    t_sco        = s_data.get("top3_avg_sco", 0)
    t_pos        = s_data.get("top3_avg_pos", 0)
    avg_sco      = s_data.get("avg_sco", 0)
    total_cnt    = s_data.get("total_cnt", 0)
    valid_cnt    = s_data.get("valid_cnt", 0)
    atr_excl_cnt = s_data.get("atr_excl_cnt", 0)
    sco_pos      = s_data.get("sco_pos", 0)
    sco_neg      = s_data.get("sco_neg", 0)
    sco_strong   = s_data.get("sco_strong", 0)

    # 색상 맵핑
    color_map = {
        "RED":    "#e74c3c",
        "PURPLE": "#9b59b6",
        "LIME":   "#2ecc71",
        "GREEN":  "#27ae60",
        "-":      "#95a5a6",
    }

    def bench_cell(label, trend):
        c = color_map.get(trend, "#95a5a6")
        return (
            f'<td title="{label}: {trend}" '
            f'style="background:{c};color:white;font-weight:bold;padding:3px 8px;'
            f'text-align:center;border-radius:4px;font-size:0.95em;white-space:nowrap;">'
            f'{label}</td>'
        )

    t_sco_str  = f"{t_sco:.2f}" if isinstance(t_sco, (int, float)) else str(t_sco)
    t_pos_str  = f"{t_pos:.2f}" if isinstance(t_pos, (int, float)) else str(t_pos)
    k_mult_str = f"x{k_mult}" if k_mult != "-" else "-"
    us_mult_str = f"x{us_mult}" if us_mult != "-" else "-"

    if invest_pct >= 67:       pct_color = "#e67e22"
    elif invest_pct >= 33:     pct_color = "#2c3e50"
    else:                      pct_color = "#7f8c8d"

    # AI 관찰판: 상단 지역 추세 버튼(코/닥/미/나/일/유/인) 제거 (요청 1번)
    # AI 페이지에서는 AI Core / Basket 흐름이 더 중요하므로 별도 표시 안 함.
    bench_table = ""

    stats_box = (
        '<div class="stats-box">'
        f'<p>📊 &nbsp;<b style="color:{pct_color};">총 투자비중={invest_pct:.1f}%</b>'
        f' &nbsp;/&nbsp; <span class="lbl">top3_avg_sco=</span><b>{t_sco_str}</b>'
        f' &nbsp;/&nbsp; <span class="lbl">top3_avg_pos=</span><b>{t_pos_str}</b>'
        f' &nbsp;&nbsp;<span class="sub">(코스피 {k_mult_str} / 나스닥 {us_mult_str})</span></p>'
        f'<p><span class="lbl">전체 Signal_sco 평균:</span> <b>{avg_sco}</b>'
        f' <span class="sub">(전체 {total_cnt}개 / 유효 {valid_cnt}개 / ATR제외 {atr_excl_cnt}개)</span></p>'
        f'<p>&nbsp;&nbsp;<span class="lbl">sco &ge; 0:</span> {sco_pos}개 &nbsp;/&nbsp;'
        f' <span class="lbl">sco &lt; 0:</span> {sco_neg}개 &nbsp;/&nbsp;'
        f' <span class="lbl">sco &ge; 11:</span> <b>{sco_strong}개</b></p>'
        '</div>'
    )

    return bench_table + stats_box


# ── 추세 badge 생성 ────────────────────────────────────────
def build_trend_badge(trend: str) -> str:
    """
    추세값 → 컬러 badge HTML 반환
    LIME  → 3  (연두색 배경, 검정 글자)
    GREEN → 2  (초록 배경, 흰 글자)
    PURPLE→ -2 (보라 배경, 흰 글자)
    RED   → -3 (빨간 배경, 흰 글자)
    """
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


# ── 메인 ───────────────────────────────────────────────────
def main():
    data       = read_data()
    low_history = update_low_history(data)
    held_list  = read_held_list()
    s_data     = read_stats()
    ai_doc     = read_ai_basket()
    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats_html = build_stats_html(s_data)

    # AI Core Regime 요약 카드 + Basket 30 랭킹 표
    ai_core_html    = build_ai_core_card(ai_doc)
    ai_weekly_flow_html = build_ai_basket_weekly_flow(ai_doc)
    ai_bottleneck_html = build_ai_bottleneck_board(ai_doc)
    ai_basket_html, ai_basket_hot_cnt, ai_basket_total_cnt = build_ai_basket_table(ai_doc)
    ai_basket_count = ai_doc.get("basket_count", 32) if isinstance(ai_doc, dict) else 32

    # 당일/주간/월간 Top5 카드 섹션
    top5_section_html = build_top5_section_global(held_list, data)

    # 주문용 최종 보유 목록 테이블
    final_order_html = build_final_order_table(held_list, data, s_data)

    # 랭킹 테이블 (상위 30개만 표시)
    rows_html = ""
    top30_data = data[:30]  # 상위 30개만 처리
    
    for idx, item in enumerate(top30_data, 1):
        type_cls   = "kr" if item["type"] == "KR" else "us"
        type_label = f'<span class="type-{type_cls}">[{item["type"]}]</span>'
        if idx <= 6:
            row_style = ' style="background-color: #FFFF99;"'
        elif item["sco"] >= 11:
            row_style = ' style="background-color: #CCFFFF;"'
        else:
            row_style = ""
        
        # 등락률 셀
        chg = item.get("chg")
        if chg is not None:
            chg_str = f"{chg:+.1f}%"
            chg_cls = "sig-up" if chg > 0 else ("sig-down" if chg < 0 else "")
        else:
            chg_str = "-"
            chg_cls = ""
        
        # 위치 뱃지
        pos_str = item.get("pos", "-")
        if pos_str in ("1","2","3","4","5"):
            pos_html = f'<span class="pos-badge pos-{pos_str}">{pos_str}</span>'
        else:
            pos_html = pos_str or "-"
        
        # 저점 신호 뱃지 (이력 기반 추적)
        low_badge = get_low_badge(item["ticker"], low_history)
        
        # 지수대비%
        idx_rel = item.get("idx_rel")
        if idx_rel is not None:
            idx_rel_str = f"{idx_rel:+.1f}%"
            idx_rel_cls = "sig-up" if idx_rel > 0 else ("sig-down" if idx_rel < 0 else "")
        else:
            idx_rel_str = "-"
            idx_rel_cls = ""
        
        # RSI 신규 로직
        rsi_str_val = item.get("rsi", "-")
        rsi_style = ""
        rsi_class = ""
        import re
        m_rsi = re.match(r'(\d+)\((\d+)\)', rsi_str_val)
        if m_rsi:
            tdy_rsi = int(m_rsi.group(1))
            prv_rsi = int(m_rsi.group(2))
            rsi_class = "sig-up" if tdy_rsi >= 50 else "sig-down"
            if tdy_rsi >= 30 and prv_rsi < 30:
                rsi_style = ' style="background-color:#d5f5e3; font-weight:bold;"'
        
        # 추세 badge
        trend_badge = build_trend_badge(item.get("trend", ""))

        # 1M 수익률 표시
        rtn1m = item.get("rtn1m")
        if rtn1m is not None:
            rtn1m_color = "#e74c3c" if rtn1m > 0 else "#3498db"
            rtn1m_str = f'{rtn1m:.1f}%'
        else:
            rtn1m_color = "#aaa"
            rtn1m_str = "-"

        # 136 평균 표시
        avg136 = item.get("avg136")
        if avg136 is not None:
            avg136_color = "#e74c3c" if avg136 > 0 else "#3498db"
            avg136_str = f'{avg136:.1f}%'
        else:
            avg136_color = "#aaa"
            avg136_str = "-"

        # KR ticker: 코드(이름) 형식으로 가독성 강화 (요청 5번)
        if item["is_kr"]:
            kr_name = KR_TICKER_TO_NAME.get(item["ticker"], "")
            ticker_display = (
                f"{item['ticker']}({kr_name})" if kr_name else item["ticker"]
            )
        else:
            ticker_display = item["ticker"]
        if item.get("intensity"):
            ticker_display += "**"

        # 🚀/🔥 신호 셀
        inv3_icon = '🚀' if item.get("inv3") == 1 else ''
        fire_icon = '🔥' if item.get("fire") == 1 else ''
        signal_cell = f"{inv3_icon}{fire_icon}"

        # Score × 100
        score_display = item["score_final"] * 100

        # 티커 셀: KR → 네이버차트, US → TradingView 차트
        if item["is_kr"]:
            ticker_td = f'<td class="naver-trigger" data-code="{item["ticker"]}" style="cursor:pointer;">{type_label} {ticker_display}</td>'
        else:
            ticker_td = f'<td class="chart-trigger" data-ticker="{item["ticker"]}" style="cursor:pointer;">{type_label} {ticker_display}</td>'

        # Basket 셀 (요청 5번: Name 컬럼 → Basket 컬럼, 한글명)
        basket_kr_str = baskets_pipe_to_kr(item.get("ai_basket", ""), max_show=3)
        basket_cell = f'<td class="basket-col">{basket_kr_str}</td>'

        # 현재가 셀 (등락률 왼쪽; scanner CSV 의 당일종가 사용)
        price_disp = _format_price(item.get("close_today"), is_kr=item["is_kr"])
        price_cell = f'<td style="font-weight:bold;color:#2c3e50;white-space:nowrap;">{price_disp}</td>'

        rows_html += (
            f'\n            <tr{row_style}>'
            + ticker_td
            + basket_cell
            + price_cell +
            f'<td class="{chg_cls}">{chg_str}</td>'
            f'<td>{pos_html}</td>'
            f'<td style="text-align:center">{trend_badge}</td>'
            f'<td>{item["sco"]:.1f}</td>'
            f'<td class="{rsi_class}"{rsi_style}>{rsi_str_val}</td>'
            f'<td style="font-weight:bold">{score_display:.1f}</td>'
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
<title>🤖 AI Theme Momentum Board (관찰판)</title>
<style>
.container-all {{ max-width: none; margin: 0; padding-bottom: 20px; }}
.ai-board-split {{ display:flex; gap:18px; align-items:flex-start; }}
.ai-board-left {{ flex:0 0 1060px; min-width:0; }}
.ai-board-right {{ flex:1 1 auto; min-width:520px; padding-top:0; }}
.ai-side-panel {{ position:sticky; top:10px; }}
.ai-side-panel h2 {{ margin-top: 10px; }}
.ai-side-panel .final-order-table {{ font-size:14px; }}
.ai-side-panel .final-order-table th, .ai-side-panel .final-order-table td {{ padding:6px 9px; }}
@media (max-width: 1650px) {{ .ai-board-split {{ flex-direction:column; }} .ai-board-left, .ai-board-right {{ flex:1 1 auto; width:100%; min-width:0; }} .ai-side-panel {{ position:static; }} }}
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
.styled-table {{ width: auto; min-width: 400px; max-width: 100%; border-collapse: collapse; margin: 4px 0 12px 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 13px; border-radius: 8px; overflow: hidden; }}
.styled-table thead tr {{ background: linear-gradient(135deg, #3498db, #2980b9); color: #ffffff; text-align: center; }}
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
/* ✅ 저점 신호 뱃지 스타일 */
.low-badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 10px; font-weight: bold; color: white; text-align: center; min-width: 35px; }}
.low-jeo   {{ background-color: #2ecc71; }}    /* 초록 - 저 (Day 0) */
.low-jeo2  {{ background-color: #3498db; }}    /* 파랑 - 저2 (Day 0) */
.low-both  {{ background-color: #e74c3c; }}    /* 빨강 - 저1,2 (Day 0) */
.low-track {{ background-color: #95a5a6; }}    /* 회색 - 1저~5저 (Day 1~5) */
.final-order-table {{ min-width: unset; }}

/* ── 차트 트리거 (TradingView / 네이버) ── */
.chart-trigger {{ cursor: pointer; text-decoration: underline dotted; }}
.chart-trigger:hover {{ background-color: #e8f4f8 !important; }}
.naver-trigger {{ cursor: pointer; text-decoration: underline dotted; }}
.naver-trigger:hover {{ background-color: #fff3cd !important; }}

/* ── TRADINGVIEW BACKUP (US ETF was on TV; switched to Naver worldstock — restore by removing surrounding comment markers) ──
#chart-popup {{
  position: fixed; background: white; border: 2px solid #2c3e50;
  border-radius: 8px; box-shadow: 0 8px 16px rgba(0,0,0,0.3);
  z-index: 99999; display: none; overflow: hidden;
}}
#chart-popup.visible {{ display: flex; flex-direction: column; }}
#chart-popup.landscape-mode {{
  position: fixed !important; top: 0 !important; left: 0 !important;
  width: 100vw !important; height: 100dvh !important;
  border-radius: 0 !important; border: none !important;
}}
.chart-ph {{
  background: #34495e; color: white; padding: 8px 12px;
  display: flex; align-items: center; justify-content: space-between; flex-shrink: 0;
}}
#btn-close-popup {{
  background: #e74c3c; color: white; border: none;
  padding: 4px 12px; cursor: pointer; border-radius: 4px; font-size: 18px; font-weight: bold;
}}
#btn-close-popup:hover {{ background: #c0392b; }}
.chart-tb-group {{ display: flex; gap: 4px; }}
.chart-tb {{ background: #7f8c8d; color: white; border: none; padding: 4px 10px; cursor: pointer; border-radius: 4px; font-size: 13px; }}
.chart-tb.on {{ background: #27ae60; font-weight: bold; }}
#tv-container {{ flex: 1; min-height: 0; }}
body.chart-open {{ overflow: hidden; }}
   ── TRADINGVIEW BACKUP END ── */

/* 네이버 팝업 (US worldstock — 미국 ETF용) */
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
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopupUS {{ width: min(96vw, 860px); left: 2vw !important; }}
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
  #naverPopupClose {{ display: flex !important; }}
}}
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
  .charts-grid {{ grid-template-columns: 1fr; }}
  .chart-wrap {{ height: 260px; }}
}}

@media (max-width: 600px) {{
    .styled-table {{ font-size: 12px; }}
    .styled-table th, .styled-table td {{ padding: 4px 6px; }}
    .stats-box {{ font-size: 11px; min-width: unset; width: 100%; box-sizing: border-box; }}
    .pc-only {{ display: none !important; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
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
/* ══ End Top5 카드 ════════════════════════════════════════ */

/* ══ 🤖 AI Core Regime 카드 & Basket 표 ═════════════════════ */
.ai-core-card {{
  display: flex; gap: 14px;
  background: linear-gradient(135deg, #fffbea, #fff5e1);
  border: 1px solid #f0b400;
  padding: 12px 14px; border-radius: 10px;
  margin: 10px 0 14px 0;
  box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  flex-wrap: wrap;
  max-width: 760px;
}}
.ai-core-left  {{ flex: 0 0 180px; min-width: 170px; }}
.ai-core-right {{ flex: 1 1 360px; min-width: 240px; max-width: 520px; }}
.ai-core-label {{ font-size: 0.76em; color: #7f8c8d; margin-bottom: 1px; }}
.ai-core-score {{ font-size: 2.1em; font-weight: 800; line-height: 1.05; margin-bottom: 3px; }}
.ai-core-state {{
  display: inline-block; padding: 2px 9px; border-radius: 12px;
  color: white; font-weight: bold; font-size: 0.82em; margin-bottom: 5px;
}}
.ai-core-state-row {{
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-bottom: 4px;
}}
.ai-breadth-state {{ font-size: 0.78em; }}
.ai-core-rdg {{
  display: flex; gap: 6px; margin: 3px 0 4px 0; flex-wrap: wrap;
}}
.ai-rdg-cell {{
  display: inline-flex; align-items: baseline; gap: 3px;
  background: #fff; border: 1px solid #f1c40f;
  border-radius: 6px; padding: 1px 7px;
  font-size: 0.78em; line-height: 1.2;
}}
.ai-rdg-lbl {{ color: #888; font-weight: 600; }}
.ai-rdg-val {{ color: #2c3e50; font-weight: 700; }}
.ai-core-dup {{
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 0.78em; margin-top: 4px;
}}
.ai-dup-pill {{
  display: inline-block; padding: 1px 7px; border-radius: 8px;
  color: white; font-weight: bold; font-size: 0.92em;
}}
.ai-core-dup-meta {{ color: #888; }}
.ai-core-dup-contrib {{
  font-size: 0.78em; color: #555; margin: 2px 0 4px 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.ai-core-breadth {{ font-size: 0.82em; margin: 3px 0; }}
.ai-core-breadth span {{
  display: inline-block; padding: 1px 7px; margin-right: 3px;
  border-radius: 8px; font-weight: bold;
}}
.ai-b-strong {{ background: #d5f5e3; color: #1d8348; }}
.ai-b-mid    {{ background: #fef9e7; color: #b7950b; }}
.ai-b-weak   {{ background: #ebebeb; color: #555; }}
.ai-b-neg    {{ background: #fadbd8; color: #c0392b; }}
.ai-core-meta {{ font-size: 0.76em; color: #888; }}
.ai-top-title {{ font-size: 0.82em; font-weight: bold; color: #2c3e50; margin-bottom: 4px; }}
/* Top AI Baskets — 단일 grid container 로 모든 row 컬럼 폭 통일 */
.ai-top-list {{
  display: grid;
  grid-template-columns: 24px auto 1fr auto;   /* rank | name | spacer | score+cnt 그룹 */
  align-items: baseline;
  column-gap: 10px; row-gap: 2px;
  width: max-content;
  max-width: 100%;
  font-size: 0.86em;
}}
.ai-top-row {{
  display: contents;   /* row wrapper 투명화 → 자식 span 4개가 직접 grid cell 이 됨 */
}}
.ai-top-rank  {{ font-weight: bold; color: #7f8c8d; text-align: left; white-space: nowrap; padding: 1px 0; }}
.ai-top-name  {{ font-weight: 700; color: #2c3e50; white-space: nowrap; padding: 1px 0; }}
.ai-top-score {{
  grid-column: 3 / 4;
  justify-self: end;
  font-weight: bold; color: #d35400;
  text-align: right; white-space: nowrap;
  padding: 1px 0; padding-right: 10px;
  min-width: 3.5em;
}}
.ai-top-cnt   {{
  grid-column: 4 / 5;
  justify-self: end;
  color: #888; font-size: 0.82em;
  text-align: right; white-space: nowrap;
  padding: 1px 0;
  min-width: 1.5em;
}}

.ai-core-help {{
  margin-top: 8px; padding-top: 6px;
  border-top: 1px dashed #f1c40f;
  font-size: 0.72em; color: #95a5a6; line-height: 1.35;
}}
.ai-core-help b {{ color: #7f8c8d; font-weight: 700; }}

.ai-basket-table th {{ font-size: 0.85em; }}
.ai-basket-table td {{ font-size: 0.82em; }}
.ai-member-hot {{
  background: #fdecea !important;
  color: #c0392b !important;
  font-weight: 700;
  border: 1px solid #f5b7b1;
}}
.ai-basket-name {{ line-height: 1.15; }}
.ai-basket-kr   {{ font-weight: 700; color: #2c3e50; display: block; }}
.ai-basket-en   {{ color: #95a5a6; font-size: 0.82em; font-weight: 400; display: block; }}
.ai-member {{
  display: inline-block; padding: 1px 6px; margin: 1px 2px;
  background: #ecf0f1; border-radius: 8px; font-size: 0.92em;
  color: #2c3e50;
}}
/* Basket 컬럼 (AI Top 후보 / Top30 랭킹) */
.basket-col {{
  text-align: left !important;
  max-width: 260px;
  white-space: normal;
  font-size: 0.85em;
  color: #2c3e50;
  line-height: 1.25;
}}
.basket-flow-card {{
  background: #fff;
  border: 1px solid #d7e6f3;
  border-radius: 8px;
  padding: 10px 12px;
  margin: 8px 0 12px 0;
  max-width: 760px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}}
.flow-head {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
  border-bottom: 1px solid #edf2f7;
  padding-bottom: 5px;
  margin-bottom: 7px;
}}
.flow-title {{ font-weight: 800; color: #2c3e50; font-size: 0.96em; }}
.flow-window {{ color: #7f8c8d; font-size: 0.78em; white-space: nowrap; }}
.flow-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  color: #5f6b76;
  font-size: 0.78em;
  margin-bottom: 8px;
}}
.flow-cols {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
}}
.flow-col {{
  background: #fbfdff;
  border: 1px solid #edf2f7;
  border-radius: 7px;
  padding: 7px 8px;
  min-width: 0;
}}
.flow-subtitle {{ font-weight: 800; font-size: 0.82em; margin-bottom: 4px; }}
.flow-row {{
  display: grid;
  grid-template-columns: minmax(95px, 1fr) auto auto;
  gap: 7px;
  align-items: baseline;
  font-size: 0.82em;
  padding: 2px 0;
}}
.flow-name {{
  font-weight: 700;
  color: #2c3e50;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.flow-delta {{ font-weight: 800; white-space: nowrap; text-align: right; }}
.flow-score {{ color: #8a98a8; font-size: 0.9em; white-space: nowrap; }}
.flow-up {{ color: #c0392b; }}
.flow-down {{ color: #1f78c8; }}
.flow-flat {{ color: #7f8c8d; }}
.flow-empty {{
  color: #95a5a6;
  font-size: 0.82em;
  padding: 4px 0;
}}
.flow-empty-wide {{
  background: #fbfdff;
  border: 1px dashed #d7e6f3;
  border-radius: 7px;
  padding: 10px;
}}
.bneck-card {{
  background: #ffffff;
  border: 1px solid #cfe2f3;
  border-radius: 8px;
  padding: 11px 12px;
  margin: 8px 0 14px 0;
  max-width: 920px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}}
.bneck-head {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  border-bottom: 1px solid #edf2f7;
  padding-bottom: 7px;
  margin-bottom: 7px;
}}
.bneck-eyebrow {{
  color: #7f8c8d;
  font-size: 0.75em;
  font-weight: 700;
  letter-spacing: 0;
}}
.bneck-title {{
  color: #2c3e50;
  font-size: 1.02em;
  font-weight: 850;
  margin-top: 1px;
}}
.bneck-sub {{
  color: #5f6b76;
  font-size: 0.82em;
  margin-top: 3px;
  line-height: 1.35;
}}
.bneck-confidence {{
  flex: 0 0 auto;
  min-width: 96px;
  text-align: right;
  background: #f8fbff;
  border: 1px solid #d7e6f3;
  border-radius: 7px;
  padding: 5px 8px;
  color: #5f6b76;
  font-size: 0.78em;
}}
.bneck-confidence b {{
  display: block;
  color: #2c3e50;
  font-size: 1.08em;
  margin-top: 1px;
}}
.bneck-footnote {{
  color: #8a98a8;
  font-size: 0.76em;
  margin: 0 0 8px 0;
}}
.bneck-flow {{
  display: flex;
  align-items: stretch;
  gap: 5px;
  overflow-x: auto;
  padding-bottom: 6px;
  margin-bottom: 8px;
}}
.bneck-node {{
  flex: 0 0 118px;
  background: #fbfdff;
  border: 1px solid #e4eef8;
  border-radius: 7px;
  padding: 7px 8px;
  min-height: 66px;
}}
.bneck-node.bneck-active {{
  border-color: #e67e22;
  box-shadow: inset 0 0 0 1px #f5c16c;
  background: #fff8ea;
}}
.bneck-node-name {{
  font-size: 0.78em;
  font-weight: 800;
  color: #2c3e50;
  white-space: nowrap;
}}
.bneck-node-score {{
  font-size: 1.15em;
  font-weight: 850;
  color: #d35400;
  margin: 2px 0;
}}
.bneck-arrow {{
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  color: #9aa9b8;
  font-weight: 900;
  padding: 0 1px;
}}
.bneck-pill {{
  display: inline-block;
  padding: 1px 7px;
  border-radius: 10px;
  color: #fff;
  font-size: 0.72em;
  font-weight: 800;
  white-space: nowrap;
}}
.bneck-very-hot {{ background: #c0392b; }}
.bneck-hot {{ background: #e67e22; }}
.bneck-watch {{ background: #3498db; }}
.bneck-soft {{ background: #95a5a6; }}
.bneck-weak {{ background: #5d6d7e; }}
.bneck-no-data {{ background: #bdc3c7; }}
.bneck-delta {{
  display: inline-block;
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 0.78em;
  font-weight: 800;
  white-space: nowrap;
}}
.bneck-delta-up   {{ background: #fde2e2; color: #c0392b; }}
.bneck-delta-down {{ background: #e3f0fb; color: #2471a3; }}
.bneck-delta-flat {{ background: #ecf0f1; color: #5f6b76; }}
.bneck-table {{
  margin-top: 4px;
  font-size: 12px;
}}
.bneck-table td {{
  text-align: left;
  vertical-align: top;
  white-space: normal;
}}
.bneck-table th {{
  font-size: 0.82em;
}}
.bneck-table-active {{
  background: #fff4d9 !important;
}}
.bneck-layer-code {{
  color: #9aa9b8;
  font-size: 0.74em;
  margin-top: 1px;
}}
.bneck-member {{
  display: inline-block;
  background: #eef5fb;
  border-radius: 8px;
  padding: 1px 6px;
  margin: 1px 2px;
  color: #2c3e50;
  font-size: 0.88em;
}}
.bneck-note-cell {{
  color: #5f6b76;
  max-width: 260px;
  line-height: 1.3;
}}
@media (max-width: 600px) {{
  .ai-core-card {{ padding: 10px 11px; gap: 8px; }}
  .ai-core-left {{ flex: 0 0 100%; }}
  .ai-core-right {{ flex: 1 1 100%; max-width: 100%; }}
  .ai-top-row {{ grid-template-columns: 22px 1fr auto auto; font-size: 0.82em; }}
  .basket-col {{ max-width: 160px; font-size: 0.78em; }}
  .flow-head {{ flex-direction: column; gap: 2px; align-items: flex-start; }}
  .flow-cols {{ grid-template-columns: 1fr; gap: 7px; }}
  .flow-row {{ grid-template-columns: minmax(88px, 1fr) auto; }}
  .flow-score {{ grid-column: 1 / -1; }}
  .bneck-head {{ flex-direction: column; gap: 6px; }}
  .bneck-confidence {{ text-align: left; }}
  .bneck-node {{ flex-basis: 110px; }}
  .bneck-note-cell {{ max-width: 180px; }}
}}
/* ══ End AI Core ═══════════════════════════════════════════ */
</style>
</head>
<body>
<div class="container-all">
    <div class="top-nav-container">
        <div class="top-nav">
            <a href="total_etf_combined.html" class="nav-item">통합 ETF</a>
            <a href="total_etf_combined_AI.html" class="nav-item active">🤖 AI 관찰판</a>
            <a href="top3_etf_daily_result_total.html" class="nav-item">Top3 추세</a>
            <a href="etf_usa_status.html" class="nav-item">ETF현황</a>
            <a href="hanmi_watch.html" class="nav-item">한미관심주</a>
        </div>
    </div>
    <h1>🤖 AI Theme Momentum Board <span style="font-size:0.65em; color:#888; font-weight:normal;">({ai_basket_count} basket 관찰판 · 실거래 미연동)</span></h1>
    <p class="meta">Updated: {now}</p>
    {stats_html}

    <div class="ai-board-split">
      <div class="ai-board-left">
        {ai_core_html}

        {ai_weekly_flow_html}

        {ai_bottleneck_html}

        <h2>🤖 AI Basket Ranking ({ai_basket_hot_cnt}/{ai_basket_total_cnt}) &nbsp;<span style="font-size:0.78em;font-weight:normal;color:#555;">basket_score = Top3 평균*0.7 + 전체 평균*0.3 (Signal_sco 기준) &nbsp;/&nbsp; <span style="color:#c0392b;font-weight:600;">Red: sco&lt;2</span></span></h2>
        {ai_basket_html}

        <h3>📊 AI 종목 Top30 랭킹 &nbsp;<span style="font-size:0.8em;font-weight:normal;color:#555;">(AI investable universe만 표시 · benchmark 제외 · Basket 컬럼은 한글화)</span></h3>
        <table class="styled-table">
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Basket</th>
                <th>현재가</th>
                <th>등락률(%)</th>
                <th>위치</th>
                <th>추세</th>
                <th>sco</th>
                <th>RSI</th>
                <th>Score</th>
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
      <div class="ai-board-right">
        <div class="ai-side-panel">
          {top5_section_html}
          <h2>🎯 AI Top 후보 (관찰용, 실거래 미연동) <span style="font-size:0.7em; color:#888; font-weight:normal;">- buy_list_total_AI.txt</span></h2>
          {final_order_html}
        </div>
      </div>
    </div>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {{
    var titles = Array.from(document.querySelectorAll('h2, h3'));
    var targetTitle = titles.find(t => t.innerText.includes('종목 랭킹') || t.innerText.includes('ETF 랭킹') || t.innerText.includes('Momentum Top 30'));
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

<!-- TRADINGVIEW BACKUP (US ETF was on TV; switched to Naver worldstock — restore by removing this wrapper)
<div id="chart-popup">
    <div class="chart-ph">
        <button id="btn-close-popup">&#215;</button>
        <div class="chart-tb-group">
            <button class="chart-tb" data-iv="5">5분</button>
            <button class="chart-tb on" data-iv="D">일</button>
            <button class="chart-tb" data-iv="W">주</button>
            <button class="chart-tb" data-iv="M">월</button>
        </div>
    </div>
    <div id="tv-container"></div>
</div>
<script>
(function() {{
    var currentTicker = "";
    var currentInterval = "D";
    var hoverTimer = null;
    var popup    = document.getElementById('chart-popup');
    var tvCont   = document.getElementById('tv-container');
    var closeBtn = document.getElementById('btn-close-popup');

    var STUDIES = [
        {{ "id": "MASimple@tv-basicstudies", "inputs": {{ "length": 5   }}, "styles": {{ "plot.color": "#e8a020", "plot.linewidth": 1 }} }},
        {{ "id": "MASimple@tv-basicstudies", "inputs": {{ "length": 10  }}, "styles": {{ "plot.color": "#3b9ddd", "plot.linewidth": 1 }} }},
        {{ "id": "MASimple@tv-basicstudies", "inputs": {{ "length": 20  }}, "styles": {{ "plot.color": "#e84040", "plot.linewidth": 2 }} }},
        {{ "id": "MASimple@tv-basicstudies", "inputs": {{ "length": 60  }}, "styles": {{ "plot.color": "#7ac97a", "plot.linewidth": 1 }} }},
        {{ "id": "MASimple@tv-basicstudies", "inputs": {{ "length": 120 }}, "styles": {{ "plot.color": "#b07fcc", "plot.linewidth": 1 }} }}
    ];

    function loadChart(sym, iv) {{
        tvCont.innerHTML = '';
        var wrap = document.createElement('div');
        wrap.className = 'tradingview-widget-container';
        wrap.style.cssText = 'height:100%;width:100%';
        var inner = document.createElement('div');
        inner.className = 'tradingview-widget-container__widget';
        inner.style.cssText = 'height:100%;width:100%';
        wrap.appendChild(inner);
        var sc = document.createElement('script');
        sc.type = 'text/javascript';
        sc.src  = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
        sc.async = true;
        sc.innerHTML = JSON.stringify({{
            symbol: sym, interval: iv,
            timezone: "America/New_York", theme: "light",
            backgroundColor: "rgba(252,251,247,1)",
            style: "1", locale: "en", autosize: true,
            withdateranges: false, hide_top_toolbar: true,
            hide_side_toolbar: true, allow_symbol_change: false,
            save_image: false, hide_volume: false,
            studies: STUDIES,
            overrides: {{ "paneProperties.legendProperties.showLegend": false }}
        }});
        wrap.appendChild(sc);
        tvCont.appendChild(wrap);
    }}

    function showChart(sym, x, y) {{
        var clean = sym.replace(/[*]/g, '');
        currentTicker = clean;
        popup.classList.remove('landscape-mode');
        if (window.innerWidth > 768) {{
            var pw = 820, ph = 560;
            var px = x + 24, py = y - 280;
            var W = window.innerWidth, H = window.innerHeight;
            if (px + pw > W) px = W - pw - 10;
            if (px < 10) px = 10;
            if (py + ph > H) py = H - ph - 10;
            if (py < 10) py = 10;
            popup.style.cssText = '';
            popup.style.left = px + 'px'; popup.style.top = py + 'px';
            popup.style.width = pw + 'px'; popup.style.height = ph + 'px';
        }} else if (window.matchMedia('(orientation: landscape)').matches) {{
            popup.style.cssText = '';
            popup.classList.add('landscape-mode');
        }} else {{
            popup.style.cssText = '';
            popup.style.width = '96vw'; popup.style.height = '72dvh';
            popup.style.left = '2vw'; popup.style.top = '14dvh';
        }}
        popup.classList.add('visible');
        document.body.classList.add('chart-open');
        loadChart(clean, currentInterval);
    }}

    function hideChart() {{
        popup.classList.remove('visible', 'landscape-mode');
        document.body.classList.remove('chart-open');
        tvCont.innerHTML = '';
        currentTicker = '';
    }}

    closeBtn.addEventListener('click', function(e) {{ e.stopPropagation(); hideChart(); }});

    document.querySelectorAll('.chart-trigger').forEach(function(el) {{
        el.addEventListener('mouseenter', function(e) {{
            if (window.innerWidth > 768) {{
                clearTimeout(hoverTimer);
                hoverTimer = setTimeout(function() {{
                    showChart(el.getAttribute('data-ticker'), e.clientX, e.clientY);
                }}, 300);
            }}
        }});
        el.addEventListener('mouseleave', function() {{
            if (window.innerWidth > 768) clearTimeout(hoverTimer);
        }});
        el.addEventListener('click', function(e) {{
            e.stopPropagation(); clearTimeout(hoverTimer);
            showChart(el.getAttribute('data-ticker'), e.clientX, e.clientY);
        }});
    }});

    document.addEventListener('mousemove', function(e) {{
        if (window.innerWidth <= 768) return;
        if (!popup.classList.contains('visible')) return;
        if (!e.target.closest('.chart-trigger') && !e.target.closest('#chart-popup')) {{
            clearTimeout(hoverTimer); hideChart();
        }}
    }});

    document.addEventListener('click', function(e) {{
        if (window.innerWidth > 768) return;
        if (!popup.classList.contains('visible')) return;
        if (!e.target.closest('#chart-popup') && !e.target.closest('.chart-trigger')) hideChart();
    }});

    document.querySelectorAll('.chart-tb').forEach(function(btn) {{
        btn.addEventListener('click', function(e) {{
            e.stopPropagation();
            currentInterval = btn.getAttribute('data-iv');
            document.querySelectorAll('.chart-tb').forEach(function(b) {{ b.classList.remove('on'); }});
            btn.classList.add('on');
            if (currentTicker) loadChart(currentTicker, currentInterval);
        }});
    }});
}})();
</script>
TRADINGVIEW BACKUP END -->

<!-- 네이버 차트 팝업 (US ETF - worldstock) -->
<div id="naverChartPopupUS">
  <div class="popup-header">
    <button id="naverPopupCloseUS" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitleUS">-</div>
    <a id="popupLinkUS" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-wrap">
        <img id="imgDailyUS" alt="일봉 차트">
        <div class="chart-loading" id="loadingDailyUS">불러오는 중...</div>
      </div>
    </div>
    <div class="chart-card">
      <div class="chart-wrap">
        <img id="imgWeeklyUS" alt="주봉 차트">
        <div class="chart-loading" id="loadingWeeklyUS">불러오는 중...</div>
      </div>
    </div>
  </div>
</div>
<script>
(function () {{
  var NAVER_CODES = {{ QQQ: 'QQQ.O', SMH: 'SMH.O' }};
  var SUFFIX_TRY = ['.O', '.P', '', '.N', '.A', '.K'];
  var resolvedCode = {{}};
  var popup       = document.getElementById('naverChartPopupUS');
  var popupTitle  = document.getElementById('popupTitleUS');
  var popupLink   = document.getElementById('popupLinkUS');
  var imgDaily    = document.getElementById('imgDailyUS');
  var imgWeekly   = document.getElementById('imgWeeklyUS');
  var loadingDaily   = document.getElementById('loadingDailyUS');
  var loadingWeekly  = document.getElementById('loadingWeeklyUS');
  var hoverTimer = null;
  var pinned = false;

  function withTs(u) {{ return u + '?t=' + Date.now(); }}
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
      probe.onload  = function () {{ resolvedCode[T] = code; cb(code); }};
      probe.onerror = tryNext;
      probe.src = withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/day/' + code + '_end.png');
    }}
    tryNext();
  }}

  function loadInto(imgEl, loadingEl, url) {{
    loadingEl.classList.add('show');
    imgEl.style.opacity = '0.35';
    var p = new Image();
    p.onload  = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.src = url;
  }}

  function loadCharts(ticker) {{
    var T = String(ticker || '').replace(/[*]/g, '').toUpperCase();
    popupTitle.textContent = T + ' (resolving...)';
    popupLink.href = '#';
    loadingDaily.classList.add('show');
    loadingWeekly.classList.add('show');
    imgDaily.removeAttribute('src');
    imgWeekly.removeAttribute('src');
    resolveCode(T, function (code) {{
      if (!code) {{
        popupTitle.textContent = T + '  (all suffixes failed)';
        loadingDaily.classList.remove('show');
        loadingWeekly.classList.remove('show');
        return;
      }}
      popupTitle.textContent = T + '  [' + code + ']';
      popupLink.href = pageUrl(code);
      loadInto(imgDaily,  loadingDaily,  dailyUrl(code));
      loadInto(imgWeekly, loadingWeekly, weeklyUrl(code));
    }});
  }}

  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    popup.style.transform = 'none';
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
  }}

  function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('naver-popup-open'); }}
  function closePopup() {{ popup.style.display = 'none';  pinned = false; document.body.classList.remove('naver-popup-open'); }}

  document.getElementById('naverPopupCloseUS').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

  document.querySelectorAll('.chart-trigger[data-ticker]').forEach(function (el) {{
    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        loadCharts(el.getAttribute('data-ticker') || '');
      }}, 140);
    }});
    el.addEventListener('mousemove', function (e) {{
      if (window.innerWidth <= 767) return;
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    el.addEventListener('mouseleave', function () {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    el.addEventListener('click', function (e) {{
      e.stopPropagation();
      clearTimeout(hoverTimer);
      placePopup(e.clientX, e.clientY);
      openPopup();
      loadCharts(el.getAttribute('data-ticker') || '');
    }});
  }});

  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767) {{
      if (!e.target.closest('#naverChartPopupUS')) closePopup();
    }} else {{
      if (!e.target.closest('#naverChartPopupUS') && !e.target.closest('.chart-trigger')) closePopup();
    }}
  }});
  // === D/S 단축키 (D/↓=다음, S/↑=이전, Tab/ESC=닫기) · PNG라 A(슈퍼트렌드)는 제외 ===
  (function(){{
    var SEL = '.chart-trigger[data-ticker]';
    var curEl = null;
    document.querySelectorAll(SEL).forEach(function(el){{
      el.addEventListener('mouseenter', function(){{ curEl = el; }});
      el.addEventListener('click', function(){{ curEl = el; }});
    }});
    try {{ popup.setAttribute('tabindex','-1'); }} catch(e){{}}
    var _open = openPopup;
    openPopup = function(){{ _open.apply(this, arguments);
      try {{ if (document.activeElement === document.body || document.activeElement === null) popup.focus({{preventScroll:true}}); }} catch(e){{}} }};
    function unpinOnMove(e){{ if (popup.contains(e.target)) return;
      document.removeEventListener('mousemove', unpinOnMove); pinned = false;
      setTimeout(function(){{ if (!pinned) closePopup(); }}, 120); }}
    function kbPin(){{ pinned = true;
      document.removeEventListener('mousemove', unpinOnMove);
      document.addEventListener('mousemove', unpinOnMove); }}
    /* === SWIPE-NAV-INJECTED: 모바일 좌/우 스와이프 → 키보드 D/S 재사용 (PC 무영향) === */
    (function(){{
      if(window.__swipeNavInit) return; window.__swipeNavInit=true;
      function isTouch(){{ return window.matchMedia('(hover: none)').matches || window.innerWidth<=767; }}
      var sx=0, sy=0, st=0, tr=false;
      document.addEventListener('touchstart', function(e){{
        if(!isTouch() || !e.touches || e.touches.length!==1){{ tr=false; return; }}
        var t=e.touches[0]; sx=t.clientX; sy=t.clientY; st=Date.now(); tr=true;
      }}, true);
      document.addEventListener('touchend', function(e){{
        if(!tr) return; tr=false;
        var t=e.changedTouches && e.changedTouches[0]; if(!t) return;
        var dx=t.clientX-sx, dy=t.clientY-sy, dt=Date.now()-st;
        if(dt>800 || Math.abs(dx)<55 || Math.abs(dx)<Math.abs(dy)*1.6) return;
        var key = dx<0 ? 'd' : 's';
        try{{ document.dispatchEvent(new KeyboardEvent('keydown', {{key:key, bubbles:true, cancelable:true}})); }}catch(err){{}}
      }}, true);
    }})();
    document.addEventListener('keydown', function(e){{
      if (popup.style.display !== 'block') return;
      var tg = e.target, tag = tg && tg.tagName;
      if (tag==='INPUT'||tag==='TEXTAREA'||(tg&&tg.isContentEditable)) return;
      var k = e.key;
      if (k==='Tab'||k==='Escape'){{ e.preventDefault(); closePopup(); return; }}
      var dir = 0;
      if (k==='s'||k==='S'||k==='ArrowUp') dir=-1;
      else if (k==='d'||k==='D'||k==='ArrowDown') dir=1;
      if (dir===0 || !curEl) return;
      e.preventDefault();
      var all = Array.prototype.slice.call(document.querySelectorAll(SEL));
      var i = all.indexOf(curEl);
      if (i<0) return;
      i += dir;
      if (i<0||i>=all.length) return;
      var nt = all[i];
      kbPin(); curEl = nt;
      loadCharts(nt.getAttribute('data-ticker') || '');
      nt.scrollIntoView({{block:'nearest'}});
    }});
  }})();
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
    <div class="chart-card">
      <div class="chart-card-header">
        <div class="chart-card-title">일봉</div>
        <div class="chart-status" id="statusDaily">대기중</div>
      </div>
      <div class="chart-wrap">
        <img id="imgDaily" alt="일봉 차트">
        <div class="chart-loading" id="loadingDaily">불러오는 중...</div>
      </div>
    </div>
    <div class="chart-card">
      <div class="chart-card-header">
        <div class="chart-card-title">주봉</div>
        <div class="chart-status" id="statusWeekly">대기중</div>
      </div>
      <div class="chart-wrap">
        <img id="imgWeekly" alt="주봉 차트">
        <div class="chart-loading" id="loadingWeekly">불러오는 중...</div>
      </div>
    </div>
  </div>
</div>
<script>
(function () {{
  var popup      = document.getElementById('naverChartPopup');
  var popupTitle = document.getElementById('popupTitle');
  var popupLink  = document.getElementById('popupLink');
  var imgDaily    = document.getElementById('imgDaily');
  var imgWeekly   = document.getElementById('imgWeekly');
  var loadingDaily    = document.getElementById('loadingDaily');
  var loadingWeekly   = document.getElementById('loadingWeekly');
  var statusDaily     = document.getElementById('statusDaily');
  var statusWeekly    = document.getElementById('statusWeekly');
  var hoverTimer = null;
  var pinned = false;

  function withTs(url) {{ return url + '?t=' + Date.now(); }}
  function dailyCandleUrl(code)  {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'  + code + '.png'); }}
  function weeklyCandleUrl(code) {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/week/' + code + '.png'); }}
  function itemPageUrl(code)     {{ return 'https://finance.naver.com/item/main.naver?code=' + code; }}

  function setStatus(el, text, color) {{ el.textContent = text; el.style.color = color || '#94a3b8'; }}

  function loadInto(imgEl, loadingEl, statusEl, url, label) {{
    loadingEl.classList.add('show');
    imgEl.style.opacity = '0.35';
    setStatus(statusEl, '로딩중...', '#f59e0b');
    var probe = new Image();
    probe.onload = function () {{
      imgEl.src = url; imgEl.style.opacity = '1';
      loadingEl.classList.remove('show');
      setStatus(statusEl, '로드 성공', '#22c55e');
    }};
    probe.onerror = function () {{
      imgEl.removeAttribute('src'); imgEl.style.opacity = '1';
      loadingEl.classList.remove('show');
      setStatus(statusEl, label + ' 실패', '#ef4444');
    }};
    probe.src = url;
  }}

  function loadCharts(code) {{
    popupTitle.textContent = code;
    popupLink.href = itemPageUrl(code);
    loadInto(imgDaily,   loadingDaily,   statusDaily,   dailyCandleUrl(code),  '일봉');
    loadInto(imgWeekly,  loadingWeekly,  statusWeekly,  weeklyCandleUrl(code), '주봉');
  }}

  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    popup.style.transform = 'none';
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
  }}

  function openPopup() {{
    popup.style.display = 'block';
    document.body.classList.add('naver-popup-open');
  }}

  function closePopup() {{
    popup.style.display = 'none';
    pinned = false;
    document.body.classList.remove('naver-popup-open');
  }}

  document.getElementById('naverPopupClose').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

  function attachNaverTrigger(el) {{
    var code = el.getAttribute('data-code');
    if (!code) return;
    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        loadCharts(code);
      }}, 140);
    }});
    el.addEventListener('mousemove', function (e) {{
      if (window.innerWidth <= 767) return;
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    el.addEventListener('mouseleave', function () {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    el.addEventListener('click', function (e) {{
      e.stopPropagation();
      clearTimeout(hoverTimer);
      placePopup(e.clientX, e.clientY);
      openPopup();
      loadCharts(code);
    }});
  }}

  document.querySelectorAll('.naver-trigger[data-code]').forEach(attachNaverTrigger);

  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767) {{
      if (!e.target.closest('#naverChartPopup')) closePopup();
    }} else {{
      if (!e.target.closest('#naverChartPopup') && !e.target.closest('.naver-trigger')) closePopup();
    }}
  }});
  // === D/S 단축키 (D/↓=다음, S/↑=이전, Tab/ESC=닫기) · PNG라 A(슈퍼트렌드)는 제외 ===
  (function(){{
    var SEL = '.naver-trigger[data-code]';
    var curEl = null;
    document.querySelectorAll(SEL).forEach(function(el){{
      el.addEventListener('mouseenter', function(){{ curEl = el; }});
      el.addEventListener('click', function(){{ curEl = el; }});
    }});
    try {{ popup.setAttribute('tabindex','-1'); }} catch(e){{}}
    var _open = openPopup;
    openPopup = function(){{ _open.apply(this, arguments);
      try {{ if (document.activeElement === document.body || document.activeElement === null) popup.focus({{preventScroll:true}}); }} catch(e){{}} }};
    function unpinOnMove(e){{ if (popup.contains(e.target)) return;
      document.removeEventListener('mousemove', unpinOnMove); pinned = false;
      setTimeout(function(){{ if (!pinned) closePopup(); }}, 120); }}
    function kbPin(){{ pinned = true;
      document.removeEventListener('mousemove', unpinOnMove);
      document.addEventListener('mousemove', unpinOnMove); }}
    document.addEventListener('keydown', function(e){{
      if (popup.style.display !== 'block') return;
      var tg = e.target, tag = tg && tg.tagName;
      if (tag==='INPUT'||tag==='TEXTAREA'||(tg&&tg.isContentEditable)) return;
      var k = e.key;
      if (k==='Tab'||k==='Escape'){{ e.preventDefault(); closePopup(); return; }}
      var dir = 0;
      if (k==='s'||k==='S'||k==='ArrowUp') dir=-1;
      else if (k==='d'||k==='D'||k==='ArrowDown') dir=1;
      if (dir===0 || !curEl) return;
      e.preventDefault();
      var all = Array.prototype.slice.call(document.querySelectorAll(SEL));
      var i = all.indexOf(curEl);
      if (i<0) return;
      i += dir;
      if (i<0||i>=all.length) return;
      var nt = all[i];
      kbPin(); curEl = nt;
      loadCharts(nt.getAttribute('data-code') || '');
      nt.scrollIntoView({{block:'nearest'}});
    }});
  }})();
}})();
</script>

</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] {OUT_HTML.name} 생성 완료 (상위 30개 표시, 보유 {len(held_list)}개)")


if __name__ == "__main__":
    main()

