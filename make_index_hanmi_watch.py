# make_index_hanmi_watch.py
# ─────────────────────────────────────────────────────────────────────────
# 한미관심주 게시판 HTML 생성 (통합ETF flow의 "make"에 해당하는 독립 set)
#
#   입력 : D:\py\0txt\hanmi_watch.csv       (hanmi_watch_scanner.py 산출, total_top30.csv 동일 스키마)
#   출력 : D:\py\report-us\hanmi_watch.html
#
#   구성(요청사양):
#     - 최상단 Updated 시간
#     - 바로 이어서 "ETF 랭킹" 테이블 (통합ETF 본판의 ETF랭킹과 동일 컬럼/스타일)
#     - 차트 호버링: 통합ETF와 동일한 V4 팝업(chart_popup_v4)
#         · 한국종목 → 종목명 셀 hover
#         · 미국종목 → 티커 셀 hover
#     - 상단 서브탭 네비: 통합ETF 4개 + 한미관심주(현재) = 5개, 서로 이동
#
#   ※ 통합ETF의 계좌/리밸런싱/보유목록/Top5 섹션은 관심주와 무관하므로 제외.
# ─────────────────────────────────────────────────────────────────────────
import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

BASE = Path(__file__).resolve().parent
PROJECT_ROOT = BASE.parent
sys.path.insert(0, str(BASE))
from chart_popup_v4 import build_chart_popup   # 통합ETF와 동일한 V4 일/주봉 팝업


# ── 미국 현재가 소스 (guide: _260715_nan확대적용.md 확대적용) ──────────────
#   yfinance 는 미국 정규장 중 마지막(오늘) 바를 OHLC=NaN 라이브 바로 내려줘
#   현재가가 NaN → 표기 공란/왜곡. 이를 회피하기 위해:
#     1순위: 키움 usa20100 (정규장→cur_prc / 아니면 base_close_pric 전일종가)
#     2순위: yfinance 폴백 (라이브 NaN 바는 dropna 로 제거 후 마지막 유효 종가)
#   ※ 신호/위치 계산은 hanmi_watch_scanner.py 가 전체 OHLCV(yfinance+dropna)로 별도 산출.
#     여기서 얻는 건 '표시용 현재가' 한 값뿐(usa20100 은 OHLC 히스토리를 주지 않음).
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
        for d in (str(PROJECT_ROOT / "0order"), str(PROJECT_ROOT / "0kiwoom_us")):
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

CSV_FILE         = Path(r"D:\py\0txt\hanmi_watch.csv")
OUT_HTML         = BASE / "hanmi_watch.html"
LOW_HISTORY_FILE = BASE / "hanmi_watch_low_history.json"   # 통합ETF와 분리된 전용 이력


def classify_market(ticker: str) -> str:
    code = str(ticker or "").strip().upper().lstrip("A")
    if len(code) == 6 and code.isdigit():
        return "KR"
    return "US"


def _stab_color(v) -> str:
    if v is None:
        return "#aaa"
    try:
        f = float(v)
        if f >= 0.7:  return "#27ae60"
        if f >= 0.4:  return "#e67e22"
        return "#e74c3c"
    except Exception:
        return "#aaa"


def _fmt_vol(v, suffix="%", decimals=1) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.{decimals}f}{suffix}"
    except Exception:
        return "-"


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
        return (f'<span style="display:inline-block;padding:2px 7px;border-radius:10px;'
                f'background:{bg};color:{fg};font-size:11px;font-weight:bold;">{label}</span>')
    return '<span style="color:#aaa;">-</span>'


# ── 저점 신호 배지 이력 (통합ETF와 동일 로직, 전용 파일) ────────────────────
def load_low_history() -> dict:
    if not LOW_HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(LOW_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_low_history(data: list) -> dict:
    today     = datetime.now().date()
    today_str = today.isoformat()
    history   = load_low_history()

    to_delete = []
    for ticker, rec in history.items():
        try:
            first_date = datetime.fromisoformat(rec["first_date"]).date()
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
        if new_jeo or new_jeo2:
            rec = history.get(ticker)
            if not rec or new_jeo != rec.get("signal_jeo", False) or new_jeo2 != rec.get("signal_jeo2", False):
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
        sig_jeo, sig_jeo2 = rec.get("signal_jeo", False), rec.get("signal_jeo2", False)
        if sig_jeo and sig_jeo2:
            return '<span class="low-badge low-both">저1,2</span>'
        if sig_jeo:
            return '<span class="low-badge low-jeo">저</span>'
        if sig_jeo2:
            return '<span class="low-badge low-jeo2">저2</span>'
    elif 1 <= days_elapsed <= 5:
        return f'<span class="low-badge low-track">{days_elapsed}저</span>'
    return ""


def build_name_cell(item: dict) -> str:
    name  = item["name"]
    color = "#2c3e50"
    if item["is_kr"]:
        # 한국종목: 종목명 셀에 V4 차트 hover 트리거 부여
        tk = item["ticker"]
        dn = str(name).replace('"', "&quot;")
        return (f'<td class="name-col chart-trigger" data-v4-code="{tk}" data-v4-market="KR" '
                f'data-name="{dn}" style="color:{color};cursor:pointer;">{name}</td>')
    # 미국종목: 이름은 텍스트만(hover 는 티커 셀에서)
    return f'<td class="name-col" style="color:{color}">{name}</td>'


def read_data() -> list:
    if not CSV_FILE.exists():
        print(f"[경고] CSV 파일 없음: {CSV_FILE}")
        return []
    data = []
    try:
        with open(CSV_FILE, mode="r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                raw_ticker = str(row.get("티커", "")).strip()
                if not raw_ticker:
                    continue
                is_intensity = "**" in raw_ticker
                ticker = raw_ticker.replace("**", "")
                is_kr  = classify_market(ticker) == "KR"

                def _f(v):
                    try:    return float(v)
                    except: return None

                data.append({
                    "ticker":      ticker,
                    "name":        str(row.get("산업", "")).strip(),
                    "rtn":         _f(row.get("수익률(%)")) or 0.0,
                    "rtn1m":       _f(row.get("수익률20(%)")),
                    "sco":         _f(row.get("Signal_sco")) or 0.0,
                    "score_final": _f(row.get("Final_score")) or 0.0,
                    "base_score":  _f(row.get("Base_score")),
                    "stability":   _f(row.get("Stability_score")),
                    "downside_vol":_f(row.get("downside_vol63")),
                    "mdd126":      _f(row.get("mdd126")),
                    "vol_spike":   _f(row.get("vol_spike")),
                    "chg":         _f(row.get("당일등락률(%)")),
                    "price":       _f(row.get("당일종가")),
                    "pos":         str(row.get("위치", "")).strip(),
                    "jeo":         str(row.get("저", "-")).strip(),
                    "jeo2":        str(row.get("저2", "-")).strip(),
                    "inv3":        int(row["inv3"]) if str(row.get("inv3", "")).strip() in ("0", "1") else 0,
                    "fire":        int(row["fire"]) if str(row.get("fire", "")).strip() in ("0", "1") else 0,
                    "idx_rel":     _f(row.get("지수대비(%)")),
                    "rsi":         str(row.get("RSI_str", "-")).strip(),
                    "trend":       str(row.get("추세", "")).strip(),
                    "avg136":      _f(row.get("평균136")),
                    "type":        "KR" if is_kr else "US",
                    "is_kr":       is_kr,
                    "intensity":   is_intensity,
                })
    except Exception as e:
        print(f"[오류] CSV 읽기 실패: {e}")
    return data


def build_rows(data: list, low_history: dict) -> str:
    rows_html = ""
    for item in data:
        type_cls   = "kr" if item["type"] == "KR" else "us"
        type_label = f'<span class="type-{type_cls}">[{item["type"]}]</span>'

        row_style = ' style="background-color: #CCFFFF;"' if item["sco"] >= 11 else ""

        price = item.get("price")
        if price is None:
            price_str = "-"
        elif item["is_kr"]:
            price_str = f"{price:,.0f}"
        else:
            price_str = f"{price:.2f}"

        chg = item.get("chg")
        chg_str = f"{chg:+.1f}%" if chg is not None else "-"
        chg_cls = ("sig-up" if chg and chg > 0 else ("sig-down" if chg and chg < 0 else ""))

        pos_str = item.get("pos", "-")
        pos_html = (f'<span class="pos-badge pos-{pos_str}">{pos_str}</span>'
                    if pos_str in ("1", "2", "3", "4", "5") else pos_str or "-")

        low_badge = get_low_badge(item["ticker"], low_history)

        idx_rel = item.get("idx_rel")
        idx_rel_str = f"{idx_rel:+.1f}%" if idx_rel is not None else "-"
        idx_rel_cls = ("sig-up" if idx_rel and idx_rel > 0 else ("sig-down" if idx_rel and idx_rel < 0 else ""))

        rsi_str_val = item.get("rsi", "-")
        rsi_class, rsi_style = "", ""
        m_rsi = re.match(r"(\d+)\((\d+)\)", rsi_str_val)
        if m_rsi:
            tdy_rsi, prv_rsi = int(m_rsi.group(1)), int(m_rsi.group(2))
            rsi_class = "sig-up" if tdy_rsi >= 50 else "sig-down"
            if tdy_rsi >= 30 and prv_rsi < 30:
                rsi_style = ' style="background-color:#d5f5e3; font-weight:bold;"'

        trend_badge = build_trend_badge(item.get("trend", ""))
        signal_cell = ('🚀' if item.get("inv3") == 1 else '') + ('🔥' if item.get("fire") == 1 else '')

        rtn1m = item.get("rtn1m")
        rtn1m_color = "#e74c3c" if rtn1m and rtn1m > 0 else "#3498db"
        rtn1m_str   = f"{rtn1m:.1f}%" if rtn1m is not None else "-"

        avg136 = item.get("avg136")
        avg136_color = "#e74c3c" if avg136 and avg136 > 0 else "#3498db"
        avg136_str   = f"{avg136:.1f}%" if avg136 is not None else "-"

        score_display = item["score_final"] * 100
        base_score_v  = item.get("base_score")
        base_display  = f"{base_score_v * 100:.1f}" if base_score_v is not None else "-"

        stab_v   = item.get("stability")
        stab_str = f"{stab_v:.2f}" if stab_v is not None else "-"
        stab_col = _stab_color(stab_v)

        dwn_str   = _fmt_vol(item.get("downside_vol"), "%", 1)
        mdd_str   = _fmt_vol(item.get("mdd126"), "%", 1)
        spike_str = _fmt_vol(item.get("vol_spike"), "x", 2)

        ticker_display = item["ticker"] + ("**" if item.get("intensity") else "")
        if item["is_kr"]:
            ticker_td = f'<td data-code="{item["ticker"]}">{type_label} {ticker_display}</td>'
        else:
            ticker_td = (f'<td class="chart-trigger" data-ticker="{item["ticker"]}" '
                         f'data-v4-code="{item["ticker"]}" data-v4-market="US" '
                         f'style="cursor:pointer;">{type_label} {ticker_display}</td>')

        name_cell = build_name_cell(item)
        rows_html += (
            f'\n            <tr{row_style}>'
            + ticker_td + name_cell
            + f'<td style="font-weight:bold;color:#2c3e50">{price_str}</td>'
            + f'<td class="{chg_cls}">{chg_str}</td>'
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
    return rows_html


def fill_us_current_price(data: list) -> None:
    """미국 종목 '현재가'를 키움 usa20100 우선으로 채운다(장중=cur_prc/그외=전일종가).
       실패 시 CSV 당일종가(yfinance+dropna 마지막 유효 종가)를 그대로 유지."""
    for item in data:
        if item.get("is_kr"):
            continue
        p = _get_us_price(item["ticker"])
        if p and p > 0:
            item["price"] = p


def main():
    data = read_data()
    fill_us_current_price(data)
    low_history = update_low_history(
        [{"ticker": d["ticker"], "jeo": d["jeo"], "jeo2": d["jeo2"]} for d in data])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_html = build_rows(data, low_history)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>한미관심주</title>
<style>
.container-all {{ max-width: 1400px; margin: 0; padding-bottom: 20px; }}
.top-nav-container {{ display: flex; margin-bottom: 10px; }}
.top-nav {{ display: flex; background-color: #2c3e50; border-radius: 8px; overflow: hidden; width: fit-content; }}
.nav-item {{ padding: 8px 15px; color: #bdc3c7; text-align: center; cursor: pointer; font-weight: bold; text-decoration: none; transition: all 0.3s; font-size: 0.9em; }}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}
body {{ font-family: 'Segoe UI', sans-serif; padding: 15px; background-color: #f4f7f6; margin: 0; line-height: 1.3; }}
h1 {{ font-size: 1.3rem; color: #2c3e50; margin: 0 0 6px 0; }}
h3 {{ margin: 8px 0 4px 0; padding-bottom: 3px; color: #2c3e50; border-bottom: 2px solid #3498db; font-size: 1.0em; }}
.meta {{ color: #7f8c8d; font-size: 0.85rem; margin-bottom: 8px; }}
.styled-table {{ width: auto; min-width: 400px; max-width: 100%; border-collapse: collapse; margin: 4px 0 12px 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 13px; border-radius: 8px; overflow: hidden; }}
.styled-table thead tr {{ background: linear-gradient(135deg, #8e44ad, #6c3483); color: #ffffff; text-align: center; }}
.styled-table th, .styled-table td {{ padding: 5px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
.styled-table td {{ text-align: center; }}
.styled-table td.name-col {{ max-width: 150px; overflow: hidden; text-overflow: ellipsis; text-align: left; }}
.type-kr {{ color: #e74c3c; font-weight: bold; font-size: 0.75rem; }}
.type-us {{ color: #3498db; font-weight: bold; font-size: 0.75rem; }}
.sig-up {{ color: #27ae60; font-weight: bold; }}
.sig-down {{ color: #e74c3c; font-weight: bold; }}
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
.chart-trigger {{ cursor: pointer; text-decoration: underline dotted; }}
.chart-trigger:hover {{ background-color: #e8f4f8 !important; }}
@media (max-width: 600px) {{
    .styled-table {{ font-size: 11px; }}
    .styled-table th, .styled-table td {{ padding: 4px 5px; }}
    .pc-only {{ display: none !important; }}
}}
/* 모바일: Name 열 숨김 (좁은 화면에서 다른 지표를 더 보기 위함, PC는 그대로) */
@media (max-width: 767px) {{
    .styled-table th.name-col, .styled-table td.name-col {{ display: none !important; }}
}}
</style>
</head>
<body>
<div class="container-all">
    <div class="top-nav-container">
        <div class="top-nav">
            <a href="total_etf_combined.html" class="nav-item">통합 ETF</a>
            <a href="total_etf_combined_AI.html" class="nav-item">🤖 AI 관찰판</a>
            <a href="top3_etf_daily_result_total.html" class="nav-item">Top3 추세</a>
            <a href="etf_usa_status.html" class="nav-item">ETF현황</a>
            <a href="hanmi_watch.html" class="nav-item active">한미관심주</a>
        </div>
    </div>
    <h1>🎯 한미관심주 (000_한미주.txt)</h1>
    <p class="meta">Updated: {now}</p>

    <h3>📊 관심주랭킹 &nbsp;<span style="font-size:0.8em;font-weight:normal;color:#555;">(파랑: sco&ge;11 | Score=Final×100, Base=기본점수×100, Stab=안정성0~1 · 한국=종목명 hover / 미국=티커 hover 차트 · 단축키 d다음/s이전/a슈퍼트렌드)</span></h3>
    <table class="styled-table">
        <thead>
            <tr>
                <th>Ticker</th>
                <th class="name-col">Name</th>
                <th>현재가</th>
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
    var targetTitle = titles.find(t => t.innerText.includes('랭킹'));
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

__V4_BLOCK__

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
    print(f"[OK] {OUT_HTML.name} 생성 완료 ({len(data)}종목)")


if __name__ == "__main__":
    main()
