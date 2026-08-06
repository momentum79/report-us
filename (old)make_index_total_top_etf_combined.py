# make_index_total_top_etf_combined.py
# jasantop4_global.py 출력 파일 기반으로 etf_combined.html 생성
#
# jasantop4_global.py 출력 파일:
#   - D:\py\0txt\total_top30.csv               : 티커,산업,수익률(%),Signal_sco,Final_score
#   - D:\py\buy_list_total.txt                 : 최종 보유/매수 티커 목록 (최대 6개)
#   - D:\py\report-us\kr_signal_stats_total.json : 투자비중·통계 정보
#
# ※ 구버전(total_jasantop6_etf.py) 컬럼 변경 사항:
#   종목명 → 산업 / 3M(%) → 수익률(%) / score → Signal_sco / Score → Final_score

import csv
import io
import json
from pathlib import Path
from datetime import datetime, date, timedelta

# ── 현재가 조회 ────────────────────────────────────────────
USD_KRW = 1450        # 환율 (수동 변경 가능)

def _sco_dist_bars(rows, total=None, analyzed=None, title=""):
    """coin게시판 스타일 SCO 분포 막대. rows=[(label, count, pct_str, color), ...]"""
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

ASSET_8042 = _load_asset_8042()
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

def _get_us_price(ticker: str) -> float | None:
    """yfinance로 미국 ETF 현재가 조회"""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="2d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"[현재가 오류] {ticker}: {e}")
        return None

# ── 경로 설정 ──────────────────────────────────────────────
BASE         = Path(__file__).resolve().parent
PROJECT_ROOT = BASE.parent

CSV_FILE   = PROJECT_ROOT / "0txt" / "total_top30.csv"
TOP6_FILE  = Path(r"D:\py\buy_list_total.txt")
STATS_FILE       = Path(r"D:\py\report-us\kr_signal_stats_total.json")
LOW_HISTORY_FILE = Path(r"D:\py\report-us\low_signal_history.json")
OUT_HTML         = BASE / "total_etf_combined.html"
REBALANCING_TXT  = Path(r"D:\py\0order\00_totaletf_korea_rebalancing.txt")

# ── Top5 CSV 경로 (global) ─────────────────────────────────
WEEKLY_TOP5_CSV  = BASE / "etf_history" / "weekly_top5_global.csv"
MONTHLY_TOP5_CSV = BASE / "etf_history" / "monthly_top5_global.csv"

# 원자재·채권 고정 multiplier=1.0 티커 목록
FIXED_ONE_TICKERS = {
    'GLD', 'SLV', 'DBA', 'DBC', 'PDBC', 'UNG', 'REMX', 'PICK',
    'AGG', 'BND', 'TLT', 'IEF', 'LQD', 'HYG', 'XLE',
    '411060',  # 금현물
}


# ══════════════════════════════════════════════════════════
# ── 🆕 당일/주간/월간 Top5 카드 섹션 (Global ETF) ──────────
# ══════════════════════════════════════════════════════════

MEDALS_G = ["🥇", "🥈", "🥉", "④", "⑤"]

# KR ETF 이름 ↔ 티커 쌍방 매핑 (step2_signals.py 와 동일)
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


def _fmt_item(raw: str) -> str:
    """
    항목 문자열 → 표시 형식 통일
    - KR 티커(6자리 숫자): '반도체(091160)' 형식으로 변환
    - 이름만 있는 KR('건설주'): '건설주(117700)' 형식으로 변환
    - 이미 '이름(티커)' 형식: 그대로 반환
    - US 티커: 그대로 반환
    """
    import re
    raw = raw.strip()
    if not raw:
        return raw
    # 이미 (숫자6자리) 또는 (US티커) 포함 → 그대로
    if re.search(r'\(.+\)$', raw):
        return raw
    # 순수 6자리 숫자 티커 → 이름 조회
    if re.match(r'^\d{6}$', raw):
        name = KR_TICKER_TO_NAME.get(raw, raw)
        return f"{name}({raw})"
    # KR 이름으로 등록된 항목 → 티커 조회
    ticker = KR_NAME_TO_TICKER.get(raw)
    if ticker:
        return f"{raw}({ticker})"
    # US 티커 등 → 그대로
    return raw


def _parse_top5_entry_global(entry: str) -> list:
    """멀티라인 셀 → 최대 5개 항목, 표시 형식 통일"""
    lines = [_fmt_item(l) for l in entry.strip().splitlines() if l.strip()]
    return lines[:5]


def get_weekly_top5_global():
    """주간 CSV 최신 차수 top5 반환 → (label, [표시문자열, ...])"""
    if not WEEKLY_TOP5_CSV.exists():
        return ("", [])
    try:
        import re
        text = WEEKLY_TOP5_CSV.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 2:
            return ("", [])
        header_cells = [c.strip() for c in rows[0] if c.strip()]
        data_cells   = [c.strip() for c in rows[1]]
        valid_pairs  = [
            (header_cells[i], data_cells[i])
            for i in range(min(len(header_cells), len(data_cells)))
            if data_cells[i].strip()
        ]
        if not valid_pairs:
            return ("", [])
        label_raw, entry = valid_pairs[-1]
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
        target_key = f"{today.year}.{today.month:02d}"
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
                        label = f"{today.month}월"
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
    """🧾 당일/주간/월간 Top5 카드 섹션 HTML"""
    today = date.today()
    # data → ticker:name 맵, 4자리 순위이력 suffix 제거 (당일 이름 조회용)
    # 예: '반도체(1388)' → '반도체', 'PTF(4423)' → 'PTF'
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


def read_low_signals() -> dict:
    """저점 신호 JSON 읽기"""
    low_signal_file = Path(r"D:\py\report-us\global_etf_low_signals.json")
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
                is_kr     = ticker.isdigit() and len(ticker) == 6
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
        price_map[tk] = _get_kor_price(tk) if use_krx_price else _get_us_price(tk)

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

        # 수량 셀: 추정자산 × 종목비중% / 현재가 (소수점 버림)
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
            order_ticker_td = f'<td class="narrow held-bold naver-trigger" data-code="{tk}" style="cursor:pointer;">{ticker_display}</td>'
        else:
            order_ticker_td = f'<td class="narrow held-bold chart-trigger" data-ticker="{tk}" style="cursor:pointer;">{ticker_display}</td>'
        rows_html.append(
            f'<tr>'
            + order_ticker_td +
            f'<td class="name-col held-bold">{item["name"]}</td>'
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
        '<th>Name</th>'
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
def build_stats_html(s_data: dict, data: list = None) -> str:
    """
    컬럼:
      - 코스피, 코스닥, S&P500, 나스닥, 닉케이, 유로, 인도
      - 투자비중, top3 평균 sco/pos, multiplier 등 통계
    상/홍/인/브 박스 추세는 jasantop4가 계산한 US ETF 결과(data, total_top30.csv)에서
    FXI/EWH/INDA/EWZ의 '추세' 컬럼을 직접 조회.
    """
    k_trend      = s_data.get("kospi_trend", "-")
    kd_trend     = s_data.get("kosdaq_trend", "-")
    sp_trend     = s_data.get("sp500_trend", "-")
    us_trend     = s_data.get("nasdaq_trend", "-")
    nikkei_trend = s_data.get("nikkei_trend", "-")
    euro_trend   = s_data.get("euro_trend", "-")
    india_trend  = s_data.get("india_trend", "-")

    # CSV(total_top30.csv)에서 US ETF 추세 조회 → 인/상/홍/브 박스 색깔
    # top30 안에 들면 색깔, 밖이면 outline (회색 테두리)
    trend_by_ticker = {row.get("ticker", ""): (row.get("trend") or "-") for row in (data or [])}
    inda_trend     = trend_by_ticker.get("INDA", "-")
    shanghai_trend = trend_by_ticker.get("FXI",  "-")
    hongkong_trend = trend_by_ticker.get("EWH",  "-")
    brazil_trend   = trend_by_ticker.get("EWZ",  "-")
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

    def bench_cell(label, trend, code, scope, outline=False):
        if outline:
            # 상/홍/브 — 무배경 + 회색 테두리
            style = (
                'background:#fff;color:#34495e;border:1px solid #bdc3c7;'
                'padding:3px 8px;text-align:center;border-radius:4px;'
                'font-size:0.95em;font-weight:bold;white-space:nowrap;cursor:pointer;'
            )
        else:
            c = color_map.get(trend, "#95a5a6")
            style = (
                f'background:{c};color:white;font-weight:bold;padding:3px 8px;'
                f'text-align:center;border-radius:4px;font-size:0.95em;'
                f'white-space:nowrap;cursor:pointer;'
            )
        return (
            f'<td class="index-trigger" data-index-code="{code}" data-index-scope="{scope}" '
            f'title="{label}: {trend}" style="{style}">{label}</td>'
        )

    t_sco_str  = f"{t_sco:.2f}" if isinstance(t_sco, (int, float)) else str(t_sco)
    t_pos_str  = f"{t_pos:.2f}" if isinstance(t_pos, (int, float)) else str(t_pos)
    k_mult_str = f"x{k_mult}" if k_mult != "-" else "-"
    us_mult_str = f"x{us_mult}" if us_mult != "-" else "-"

    if invest_pct >= 67:       pct_color = "#e67e22"
    elif invest_pct >= 33:     pct_color = "#2c3e50"
    else:                      pct_color = "#7f8c8d"

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

    # 📊 SCO 분포 막대 (coin게시판 스타일) — sco≥11 / 0~11 / <0
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
    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats_html = build_stats_html(s_data, data)

    # 당일/주간/월간 Top5 카드 섹션
    top5_section_html = build_top5_section_global(held_list, data)

    # 주문용 최종 보유 목록 테이블
    final_order_html = build_final_order_table(held_list, data, s_data)

    # 랭킹 테이블 (상위 30개만 표시)
    rows_html = ""
    top30_data = data[:30]  # 상위 30개만 처리
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

        ticker_display = item["ticker"] + ("**" if item.get("intensity") else "")

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

        # Ticker, Name, 등락률(%), 위치, 추세, sco, rsi, Score, 1M, 136, 저점, 🚀, 지수대비(%)
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
<title>ETF 수익률 상위</title>
<style>
.container-all {{ max-width: 1200px; margin: 0; padding-bottom: 20px; }}
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

/* 네이버 팝업 (지수 — KOSPI/KOSDAQ/S&P/NASDAQ/Nikkei/Euro/India/Shanghai/HangSeng/Brazil) */
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
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopupIndex {{ width: min(96vw, 860px); left: 2vw !important; }}
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
</style>
</head>
<body>
<div class="container-all">
    <div class="top-nav-container">
        <div class="top-nav">
            <a href="main_hub.html" class="nav-item">상황판</a>
            <a href="total_etf_combined_AI.html" class="nav-item">🤖 AI 관찰판</a>
            <a href="total_etf_combined.html" class="nav-item active">통합 ETF</a>
            <a href="total_etf_combined_vol.html" class="nav-item">📉 변동성 조정</a>
            <a href="top3_etf_daily_result_total.html" class="nav-item">Top3 추세</a>
        </div>
    </div>
    <h1>📈 ETF 수익률 상위 (KR/US 통합)</h1>
    <p class="meta">Updated: {now}</p>
    {stats_html}

    {top5_section_html}

    <h2>🧾 주문용 최종 보유 목록 ({s_data.get('invest_pct', 0):.1f}%) <span style="font-size:0.7em; color:#000; font-weight:normal;">- {int(ASSET_8042 / 10000):,}만원 기준 {int(ASSET_8042 * s_data.get('invest_pct', 0) / 100 / 10000):,}만원</span></h2>
    {final_order_html}

    <h3>📊 ETF 랭킹 &nbsp;<span style="font-size:0.8em;font-weight:normal;color:#555;">(노랑: 주문용 보유, 파랑: sco&ge;11, 🚀: 당일 sco&ge;8, 🔥: GANN)</span></h3>
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
  var NAVER_LS_KEY = 'naverCodeMap_v1';
  var resolvedCode = (function () {{
    var m = {{}};
    try {{ m = JSON.parse(localStorage.getItem(NAVER_LS_KEY) || '{{}}') || {{}}; }} catch (e) {{ m = {{}}; }}
    for (var k in NAVER_CODES) {{ if (!m[k]) m[k] = NAVER_CODES[k]; }}  // pre-seed known codes
    return m;
  }})();
  function persistCode(T, code) {{ resolvedCode[T] = code; try {{ localStorage.setItem(NAVER_LS_KEY, JSON.stringify(resolvedCode)); }} catch (e) {{}} }}
  function forgetCode(T) {{ if (resolvedCode[T]) {{ delete resolvedCode[T]; try {{ localStorage.setItem(NAVER_LS_KEY, JSON.stringify(resolvedCode)); }} catch (e) {{}} }} }}
  var popup       = document.getElementById('naverChartPopupUS');
  var popupTitle  = document.getElementById('popupTitleUS');
  var popupLink   = document.getElementById('popupLinkUS');
  var imgDaily    = document.getElementById('imgDailyUS');
  var imgWeekly   = document.getElementById('imgWeeklyUS');
  var loadingDaily   = document.getElementById('loadingDailyUS');
  var loadingWeekly  = document.getElementById('loadingWeeklyUS');
  var hoverTimer = null;
  var pinned = false;

  function withTs(u) {{ return u + '?t=' + Math.floor(Date.now() / 60000); }}  // 60s bucket (matches Naver max-age=60)
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
    loadingEl.classList.add('show');
    imgEl.style.opacity = '0.35';
    var p = new Image();
    p.onload  = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); if (onErr) onErr(); }};
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
      loadInto(imgDaily,  loadingDaily,  dailyUrl(code), function () {{ forgetCode(T); }});  // bad/changed code -> re-probe next hover
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

<!-- 네이버 차트 팝업 (지수: KOSPI/KOSDAQ/S&P/NASDAQ/Nikkei/Euro/India/Shanghai/HangSeng/Brazil) -->
<div id="naverChartPopupIndex">
  <div class="popup-header">
    <button id="naverPopupCloseIndex" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitleIndex">-</div>
    <a id="popupLinkIndex" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-wrap">
        <img id="imgDailyIndex" alt="일봉 차트">
        <div class="chart-loading" id="loadingDailyIndex">불러오는 중...</div>
      </div>
    </div>
    <div class="chart-card">
      <div class="chart-wrap">
        <img id="imgWeeklyIndex" alt="주봉 차트">
        <div class="chart-loading" id="loadingWeeklyIndex">불러오는 중...</div>
      </div>
    </div>
  </div>
</div>
<script>
(function () {{
  var popup       = document.getElementById('naverChartPopupIndex');
  var popupTitle  = document.getElementById('popupTitleIndex');
  var popupLink   = document.getElementById('popupLinkIndex');
  var imgDaily    = document.getElementById('imgDailyIndex');
  var imgWeekly   = document.getElementById('imgWeeklyIndex');
  var loadingDaily   = document.getElementById('loadingDailyIndex');
  var loadingWeekly  = document.getElementById('loadingWeeklyIndex');
  var hoverTimer = null;
  var pinned = false;

  function withTs(u) {{ return u + '?t=' + Math.floor(Date.now() / 60000); }}  // 60s bucket (matches Naver max-age=60)
  function chartUrl(code, scope, period) {{
    if (scope === 'kr') {{
      return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/candle/' + period + '/' + code + '_end.png');
    }}
    return withTs('https://ssl.pstatic.net/imgfinance/chart/world/candle/' + period + '/' + code + '.png');
  }}
  function pageUrl(code, scope) {{
    if (scope === 'kr') {{
      return 'https://finance.naver.com/sise/sise_index.naver?code=' + code;
    }}
    return 'https://finance.naver.com/world/sise.naver?symbol=' + code;
  }}

  function loadInto(imgEl, loadingEl, url, onErr) {{
    loadingEl.classList.add('show');
    imgEl.style.opacity = '0.35';
    var p = new Image();
    p.onload  = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); if (onErr) onErr(); }};
    p.src = url;
  }}

  function loadCharts(code, scope) {{
    popupTitle.textContent = code;
    popupLink.href = pageUrl(code, scope);
    loadInto(imgDaily,  loadingDaily,  chartUrl(code, scope, 'day'));
    loadInto(imgWeekly, loadingWeekly, chartUrl(code, scope, 'week'));
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

  document.getElementById('naverPopupCloseIndex').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

  document.querySelectorAll('.index-trigger[data-index-code]').forEach(function (el) {{
    var code  = el.getAttribute('data-index-code');
    var scope = el.getAttribute('data-index-scope') || 'world';
    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        loadCharts(code, scope);
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
      loadCharts(code, scope);
    }});
  }});

  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767) {{
      if (!e.target.closest('#naverChartPopupIndex')) closePopup();
    }} else {{
      if (!e.target.closest('#naverChartPopupIndex') && !e.target.closest('.index-trigger')) closePopup();
    }}
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

  function withTs(url) {{ return url + '?t=' + Math.floor(Date.now() / 60000); }}  // 60s bucket (matches Naver max-age=60)
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
