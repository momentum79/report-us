import html
from pathlib import Path
from datetime import datetime, date
import re
import json

BASE = Path(__file__).resolve().parent
REPORT_TXT = BASE / "report_futures.txt"
OUT_HTML   = BASE / "futures.html"
FUTURES_LOW_SIGNAL_FILE = BASE / "futures_low_signals.json"
LOW_HISTORY_FILE = BASE / "futures_low_history.json"

# ── 저점 신호 5일 추적 ────────────────────────────────────
def load_low_history() -> dict:
    if not LOW_HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(LOW_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[경고] 저점 이력 읽기 실패: {e}")
        return {}

def update_low_history(low_signals_dict: dict) -> dict:
    today     = date.today()
    today_str = today.isoformat()
    history   = load_low_history()

    to_delete = []
    for ticker, rec in history.items():
        try:
            first_date = date.fromisoformat(rec["first_date"])
            if (today - first_date).days > 7:
                to_delete.append(ticker)
        except Exception:
            to_delete.append(ticker)
    for t in to_delete:
        del history[t]

    for ticker, (jeo, jeo2) in low_signals_dict.items():
        new_jeo  = (str(jeo).strip()  not in ("", "-", "0", "nan"))
        new_jeo2 = (str(jeo2).strip() not in ("", "-", "0", "nan"))
        if new_jeo or new_jeo2:
            if ticker in history:
                old_jeo  = history[ticker].get("signal_jeo",  False)
                old_jeo2 = history[ticker].get("signal_jeo2", False)
                if new_jeo != old_jeo or new_jeo2 != old_jeo2:
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
        days_elapsed = (date.today() - date.fromisoformat(rec["first_date"])).days
    except Exception:
        return ""
    if days_elapsed == 0:
        if rec.get("signal_jeo") and rec.get("signal_jeo2"):
            return '<span class="low-badge low-both">저1,2</span>'
        elif rec.get("signal_jeo"):
            return '<span class="low-badge low-jeo">저</span>'
        elif rec.get("signal_jeo2"):
            return '<span class="low-badge low-jeo2">저2</span>'
    elif 1 <= days_elapsed <= 5:
        return f'<span class="low-badge low-track">{days_elapsed}저</span>'
    return ""


# ─────────────────────────────────────────────
# 텍스트 블록 추출 헬퍼
# ─────────────────────────────────────────────
def extract_block(text, start_marker, end_markers):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(start_marker):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if any(lines[i].strip().startswith(m) for m in end_markers):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def extract_atr_triggered(text):
    block = extract_block(text, "[ATR 트리거",
        ["[ATR 트레일링", "[실행 시간]", "Signal_sco 기준", "✅ ATR", "================"])
    if not block:
        return ""
    cleaned = [l for l in block.splitlines()
               if not l.strip().startswith("[")
               and "Ticker" not in l
               and "종목 수" not in l and "수:" not in l]
    return "\n".join(cleaned).strip()


def extract_atr_excluded(text):
    block = extract_block(text, "[ATR 트레일링",
        ["[실행 시간]", "Signal_sco 기준", "ATR 과열", "✅ ATR", "================"])
    if not block:
        return ""
    cleaned = [l for l in block.splitlines()
               if not l.strip().startswith("[")
               and "Ticker" not in l
               and "종목 수" not in l and "수:" not in l]
    return "\n".join(cleaned).strip()


def extract_distribution_block(text):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "Signal_sco 기준 종목 분포" in line:
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("[실행 시간]"):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def extract_runtime(text):
    for line in text.splitlines():
        if line.strip().startswith("[실행 시간]"):
            return line.strip()
    return ""


# ─────────────────────────────────────────────
# Momentum Top 테이블 렌더러
# ─────────────────────────────────────────────
def text_to_html_table_momentum(text, held_list=None, low_history=None,
                                table_id="momentum-table", ticker_filter=None,
                                ticker_exclude=None, sort_by_sco=False):
    if low_history is None:
        low_history = {}
    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p style="color:#888;">{html.escape(text)}</p>'

    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return '<p style="color:#888;">없음</p>'

    data_lines = [l for l in lines if not l.startswith("Ticker")]

    def _split(l):
        c = re.split(r'\s{2,}', l)
        if len(c) < 15:
            c = l.split()
        return c

    def _tk(l):
        c = _split(l)
        return c[0].strip().replace("*", "").replace("**", "") if c else ""

    if ticker_filter is not None:
        data_lines = [l for l in data_lines if _tk(l) in ticker_filter]
    if ticker_exclude is not None:
        data_lines = [l for l in data_lines if _tk(l) not in ticker_exclude]

    if sort_by_sco:
        def _sco(l):
            c = _split(l)
            try:
                return float(re.sub(r'[^\d.+-]', '', c[3]))
            except Exception:
                return float('-inf')
        data_lines = sorted(data_lines, key=_sco, reverse=True)

    if not data_lines:
        return '<p style="color:#888;">없음</p>'

    out = [f'<table class="styled-tableWide" id="{table_id}">']
    out.append(
        '<thead><tr>'
        '<th class="sortable" data-col="0">Ticker</th>'
        '<th class="sortable" data-col="1">등락</th>'
        '<th class="sortable" data-col="2">위치</th>'
        '<th class="sortable" data-col="3">Sco</th>'
        '<th class="sortable" data-col="4">정</th>'
        '<th class="sortable" data-col="5">신호</th>'
        '<th class="sortable" data-col="6">5</th>'
        '<th class="sortable" data-col="7">10</th>'
        '<th class="sortable" data-col="8">20</th>'
        '<th class="sortable" data-col="9">60</th>'
        '<th class="sortable" data-col="10">120</th>'
        '<th class="sortable" data-col="11">136평</th>'
        '<th class="sortable" data-col="12">3M(%)</th>'
        '<th class="sortable" data-col="13">Score</th>'
        '<th>저점</th>'
        '</tr></thead>'
    )
    out.append('<tbody>')

    for line in data_lines:
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 15:
            cols = line.split()
        if len(cols) < 15:
            continue

        ticker      = cols[0].strip()
        ticker_clean = ticker.replace("*", "").replace("**", "")

        highlight_class = ""
        if held_list and ticker_clean in held_list:
            idx = held_list.index(ticker_clean)
            highlight_class = "held-bold" if (len(held_list) <= 3 or idx < 3) else "held-plain"

        # 추세 색상 (index 11)
        ticker_style = ""
        trend_val = cols[11].upper() if len(cols) > 11 else ""
        if "LIME"   in trend_val: ticker_style = 'background-color:#2AF527; color:black; font-weight:bold;'
        elif "GREEN" in trend_val: ticker_style = 'background-color:#8DCF8C; color:black; font-weight:bold;'
        elif "RED"   in trend_val: ticker_style = 'background-color:#e74c3c; color:white; font-weight:bold;'
        elif "PURPLE"in trend_val: ticker_style = 'background-color:#9b59b6; color:white; font-weight:bold;'

        ticker_classes = ["ticker-col", "chart-trigger"]
        if highlight_class:
            ticker_classes.append(highlight_class)

        tk_style_attr = f' style="{ticker_style} cursor:pointer;"' if ticker_style else ' style="cursor:pointer;"'
        row_html  = '<tr>'
        row_html += f'<td class="{" ".join(ticker_classes)}" data-ticker="{ticker_clean}" data-name="{ticker_clean}"{tk_style_attr}>{html.escape(ticker)}</td>'

        for i, c in enumerate(cols[1:], 1):
            if i == 11:   # 추세 컬럼 건너뜀
                continue

            cell_class = []
            content = html.escape(c)

            if highlight_class:
                cell_class.append(highlight_class)

            if i == 1:    # 등락
                try:
                    val = float(re.sub(r'[^\d.+-]', '', c))
                    cell_class.append("sig-up" if val > 0 else ("sig-down" if val < 0 else ""))
                except: pass
            elif i == 2:  # 위치 동그라미
                pos_val = c.strip()
                if pos_val in ("1","2","3","4","5"):
                    content = f'<span class="pos-badge pos-{pos_val}">{content}</span>'
            elif i == 4:  # 정배/역배
                if "정배" in c: cell_class.append("sig-jung")
                elif "역배" in c: cell_class.append("sig-yeok")
            elif i == 5:  # 신호 배지
                sig_u = c.upper()
                if c.strip() not in ("-", ""):
                    if "LIME"  in sig_u: content = f'<span class="trend-badge trend-lime">{html.escape(c)}</span>'
                    elif "GRN" in sig_u or "GREEN" in sig_u: content = f'<span class="trend-badge trend-green">{html.escape(c)}</span>'
                    elif "RED" in sig_u: content = f'<span class="trend-badge trend-red">{html.escape(c)}</span>'
            elif 6 <= i <= 10:  # 이평 방향
                if '상' in c: cell_class.append("up")
                elif '하' in c: cell_class.append("down")
            elif i == 12:  # 136평
                try:
                    num_val = float(c.replace('%', ''))
                    cell_class.append("up" if num_val > 0 else ("down" if num_val < 0 else ""))
                except: pass
            elif i == 13:  # 3M(%)
                try:
                    val = float(re.sub(r'[^\d.+-]', '', c))
                    cell_class.append("sig-up" if val > 0 else ("sig-down" if val < 0 else ""))
                except: pass

            cls_str = f' class="{" ".join(cell_class)}"' if cell_class else ''
            row_html += f'<td{cls_str}>{content}</td>'

        row_html += f'<td class="col-low" style="text-align:center;">{get_low_badge(ticker_clean, low_history)}</td>'
        row_html += '</tr>'
        out.append(row_html)

    out.append('</tbody></table>')
    return '\n'.join(out)


# ─────────────────────────────────────────────
# Top4 테이블 렌더러
# ─────────────────────────────────────────────
def text_to_html_table_top4(text, ticker_meta=None):
    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p style="color:#888;">{html.escape(text)}</p>'
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return '<p style="color:#888;">없음</p>'

    out = ['<table class="styled-table">']
    out.append('<thead><tr><th>Ticker</th><th>위치</th><th>Sco</th><th>3M(%)</th><th>Score</th><th>신호</th></tr></thead>')
    out.append('<tbody>')

    for line in lines:
        if line.startswith("Ticker"):
            continue
        toks = line.split()
        if len(toks) < 4:
            continue
        ticker  = toks[0]
        sco     = toks[1]
        rtn     = toks[2]
        score   = toks[3]
        newsig  = toks[4] if len(toks) > 4 else "-"

        ticker_clean = ticker.replace("*", "").replace("**", "")
        meta = (ticker_meta or {}).get(ticker_clean, {})
        ticker_style = meta.get('style', '')

        pos_val  = meta.get('pos', '')
        pos_html = (f'<span class="pos-badge pos-{pos_val}">{html.escape(pos_val)}</span>'
                    if pos_val in ("1","2","3","4","5") else html.escape(pos_val or "-"))

        rtn_class = ""
        try:
            rtn_val = float(re.sub(r'[^\d.+-]', '', rtn))
            rtn_class = "sig-up" if rtn_val > 0 else ("sig-down" if rtn_val < 0 else "")
        except: pass

        sig_html = html.escape(newsig)
        if newsig.strip() not in ("-", ""):
            sig_u = newsig.upper()
            if "LIME"  in sig_u: sig_html = f'<span class="trend-badge trend-lime">{html.escape(newsig)}</span>'
            elif "GRN" in sig_u or "GREEN" in sig_u: sig_html = f'<span class="trend-badge trend-green">{html.escape(newsig)}</span>'
            elif "RED" in sig_u: sig_html = f'<span class="trend-badge trend-red">{html.escape(newsig)}</span>'

        tk_style_attr = f' style="{ticker_style} cursor:pointer;"' if ticker_style else ' style="cursor:pointer;"'

        out.append(
            f'<tr>'
            f'<td class="ticker-col chart-trigger" data-ticker="{ticker_clean}" data-name="{ticker_clean}"{tk_style_attr}>{html.escape(ticker)}</td>'
            f'<td>{pos_html}</td>'
            f'<td>{html.escape(sco)}</td>'
            f'<td class="{rtn_class}">{html.escape(rtn)}</td>'
            f'<td>{html.escape(score)}</td>'
            f'<td>{sig_html}</td>'
            f'</tr>'
        )

    out.append('</tbody></table>')
    return '\n'.join(out)


# ─────────────────────────────────────────────
# ATR 소형 테이블 렌더러
# ─────────────────────────────────────────────
def text_to_html_table_atr(text, header_cols):
    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p style="color:#888; font-size:0.9em;">{html.escape(text)}</p>'
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return '<p style="color:#888; font-size:0.9em;">없음</p>'
    out = ['<table class="styled-table">']
    out.append("<thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in header_cols) + "</tr></thead>")
    out.append("<tbody>")
    for line in lines:
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 2:
            cols = line.split()
        out.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cols) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


# ─────────────────────────────────────────────
# 선물 티커 → 차트 소스 매핑 (PNG 직링크)
# ─────────────────────────────────────────────
#   src="naver": 네이버 세계증시 PNG (일봉+주봉 2개). code=네이버 종목코드(접미사 포함).
#   src="te":    TradingEconomics PNG (단일차트). code=TE 심볼.
#   note:        팝업 제목 옆 대체자산 설명.
#   ※ 라우팅은 PNG 가용성으로 결정됨(검증완료). 어느 티커든 (src, code)만 바꾸면 소스 전환 가능.
#     - 네이버에 없는 ETF: PPLT/PALL/CPER/CORN/WEAT/SOYB/ETHV → TE 실선물로 대체
#     - TE에 없는 자산: 백금/팔라듐은 xptusd/xpdusd, 지수는 ETF로 처리
#     - ZL(콩기름): 네이버·TE 둘 다 PNG 없음 → 매핑 제외 = 차트 안 띄움
CHART_MAP = {
    # 주가지수 → 네이버 ETF
    "ES":  ("naver", "SPY",        "SPY"),
    "NQ":  ("naver", "QQQ.O",      "QQQ"),
    "RTY": ("naver", "IWM",        "IWM"),
    # 귀금속
    "GC":  ("naver", "GLD",        "GLD·금"),
    "SI":  ("naver", "SLV",        "SLV·은"),
    "PL":  ("te",    "xptusd:cur", "Platinum"),
    "PA":  ("te",    "xpdusd:cur", "Palladium"),
    # 산업금속
    "HG":  ("te",    "hg1:com",    "Copper"),
    # 에너지 → 네이버 ETF
    "CL":  ("naver", "USO",        "USO·WTI"),
    "NG":  ("naver", "UNG",        "UNG·천연가스"),
    # 채권 → 네이버 ETF
    "ZB":  ("naver", "TLT.O",      "TLT·美장기채"),
    # 곡물 → TE 실선물 (네이버 ETF 없음)
    "ZC":  ("te",    "c 1:com",    "Corn"),
    "ZO":  ("te",    "o 1:com",    "Oat"),
    "ZW":  ("te",    "w 1:com",    "Wheat"),
    "ZS":  ("te",    "s 1:com",    "Soybean"),
    # 축산물 → 네이버 ETF
    "LE":  ("naver", "COW",        "COW·축산"),
    # FX → TE
    "AUD": ("te", "audusd:cur", "AUD/USD"),
    "GBP": ("te", "gbpusd:cur", "GBP/USD"),
    "EUR": ("te", "eurusd:cur", "EUR/USD"),
    "NZD": ("te", "nzdusd:cur", "NZD/USD"),
    "MXN": ("te", "mxnusd:cur", "MXN/USD"),
    "JPY": ("te", "jpyusd:cur", "JPY/USD"),
    "BRL": ("te", "brlusd:cur", "BRL/USD"),
    # 크립토 → 네이버 ETF
    "BTC": ("naver", "IBIT.O",     "IBIT·비트코인"),
    "ETH": ("naver", "ETHA.O",     "ETHA·이더리움"),
}


# ─────────────────────────────────────────────
# Upbit 코인 신호 리더
# ─────────────────────────────────────────────
def read_upbit_signals(filename: str) -> str:
    path = BASE.parent / "0txt" / filename
    if not path.exists():
        return "없음"
    lines = [x.strip() for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
    if not lines:
        return "없음"
    return " / ".join(lines)

# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────
def main():
    import os
    data_time_str = "알 수 없음 (파일 없음)"
    if REPORT_TXT.exists():
        text = REPORT_TXT.read_text(encoding="utf-8", errors="replace")
        mtime = os.path.getmtime(REPORT_TXT)
        data_time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    else:
        text = ""
        
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    momentum_raw   = extract_block(text, "=== 해외선물 / FX / 암호화폐 Momentum Top ===",
                        ["=== 주문용 Top4", "==="]) or "(Momentum Top 없음)"
    momentum_block = "\n".join([l for l in momentum_raw.splitlines()
                                if "해외선물 / FX" not in l]).strip()

    order_raw  = extract_block(text, "=== 주문용 Top4 (오늘) ===",
                    ["이전 Top4:", "==="]) or "(주문용 Top4 없음)"
    order_top4 = "\n".join([l for l in order_raw.splitlines()
                             if "주문용 Top4" not in l]).strip()

    held_list  = []
    held_match = re.search(r"이전 Top4: \[(.*?)\]", text)
    if held_match:
        held_list = [t.strip().strip("'").strip('"') for t in held_match.group(1).split(',')]

    atr_triggered = extract_atr_triggered(text) or "(ATR 트리거 종목 없음)"
    atr_excluded  = extract_atr_excluded(text)  or "(ATR 제외 종목 없음)"
    dist_block    = extract_distribution_block(text) or "(분포 정보 없음)"
    runtime       = extract_runtime(text)

    # Ticker metadata (추세색, 위치) 추출
    ticker_meta = {}
    for mline in momentum_block.splitlines():
        mcols = re.split(r'\s{2,}', mline.strip())
        if len(mcols) < 15: mcols = mline.strip().split()
        if len(mcols) < 15: continue
        mtk    = mcols[0].strip().replace("*", "").replace("**", "")
        mpos   = mcols[2].strip()
        mtrend = mcols[11].upper() if len(mcols) > 11 else ""
        mstyle = ""
        if "LIME"    in mtrend: mstyle = 'background-color:#2AF527; color:black; font-weight:bold;'
        elif "GREEN" in mtrend: mstyle = 'background-color:#8DCF8C; color:black; font-weight:bold;'
        elif "RED"   in mtrend: mstyle = 'background-color:#e74c3c; color:white; font-weight:bold;'
        elif "PURPLE"in mtrend: mstyle = 'background-color:#9b59b6; color:white; font-weight:bold;'
        ticker_meta[mtk] = {'pos': mpos, 'style': mstyle}

    # 저점 이력 처리
    low_signals_dict = {}
    if FUTURES_LOW_SIGNAL_FILE.exists():
        try:
            raw = json.loads(FUTURES_LOW_SIGNAL_FILE.read_text(encoding='utf-8'))
            for sig in raw.get('signals', []):
                t = sig.get('ticker', '')
                low_signals_dict[t] = (sig.get('jeo', '-'), sig.get('jeo2', '-'))
        except Exception as e:
            print(f"[경고] 해선 저점 신호 읽기 실패: {e}")
    low_history = update_low_history(low_signals_dict)

    # 차트 매핑 JS 직렬화
    chart_map_js = json.dumps(
        {k: {"src": v[0], "code": v[1], "note": v[2]} for k, v in CHART_MAP.items()},
        ensure_ascii=False)
    chart_ver = datetime.now().strftime("%Y%m")  # TE v= 파라미터(월 단위)

    # 통화(FX) 전용 테이블 — 메인 테이블에서 통화만 추려 Sco순 정렬
    FX_TICKERS = {"AUD", "GBP", "EUR", "NZD", "MXN", "JPY", "BRL"}
    momentum_table_html = text_to_html_table_momentum(
        momentum_block, held_list, low_history, ticker_exclude=FX_TICKERS)
    currency_table_html = text_to_html_table_momentum(
        momentum_block, held_list, low_history,
        table_id="currency-table", ticker_filter=FX_TICKERS, sort_by_sco=True)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>해외선물 Report</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 20px;
  margin: 0;
  background-color: #f4f7f6;
}}
h1 {{ margin: 0; font-size: 1.5em; color: #2c3e50; }}
h2 {{
  margin-top: 30px;
  padding-bottom: 10px;
  color: #2c3e50;
  border-bottom: 2px solid #e67e22;
}}
.styled-table {{
  width: auto;
  border-collapse: collapse;
  margin: 10px 0 20px 0;
  font-size: 13px;
  background: white;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  border-radius: 8px;
  overflow: hidden;
}}
.styled-table thead tr {{
  background: linear-gradient(135deg, #e67e22, #d35400);
  color: #ffffff;
  text-align: center;
}}
.styled-table th, .styled-table td {{
  padding: 6px 16px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
  text-align: center;
}}
.styled-table td:nth-child(1) {{ text-align: left; font-weight: bold; color: #2980b9; }}
.styled-tableWide {{
  width: auto;
  border-collapse: collapse;
  margin: 10px 0 20px 0;
  font-size: 13px;
  background: white;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  border-radius: 8px;
  overflow: hidden;
}}
.styled-tableWide thead tr {{
  background: linear-gradient(135deg, #e67e22, #d35400);
  color: #ffffff;
  text-align: center;
}}
.styled-tableWide th, .styled-tableWide td {{
  padding: 6px 10px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
  text-align: center;
  font-size: 12px;
}}
.styled-tableWide td:nth-child(1) {{ text-align: left; font-weight: bold; color: #2980b9; }}
.held-bold {{ font-weight: 700; }}
.held-plain {{}}
.sig-up   {{ color: #00b050; font-weight: 600; }}
.sig-down {{ color: #ff0000; font-weight: 600; }}
.sig-jung {{ background: #fffbea; color: #d68910; font-weight: 600; }}
.sig-yeok {{ background: #e8f4fd; color: #1e6fa8; font-weight: 600; }}
.up   {{ color: #00b050; font-weight: 600; }}
.down {{ color: #ff0000; font-weight: 600; }}
.pos-badge {{
  display: inline-block;
  width: 22px; height: 22px; line-height: 22px;
  border-radius: 50%;
  font-size: 0.75rem; font-weight: bold;
  color: white; text-align: center;
}}
.pos-1 {{ background-color: #16a34a !important; }}
.pos-2 {{ background-color: #65a30d !important; }}
.pos-3 {{ background-color: #d97706 !important; }}
.pos-4 {{ background-color: #ea580c !important; }}
.pos-5 {{ background-color: #dc2626 !important; }}
.trend-badge {{
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85em; font-weight: 700;
}}
.trend-lime   {{ background: #2AF527; color: black; }}
.trend-green  {{ background: #8DCF8C; color: black; }}
.trend-red    {{ background: #e74c3c; color: white; }}
.trend-purple {{ background: #9b59b6; color: white; }}

/* ✅ 저점 신호 뱃지 */
.low-badge {{ display:inline-block; padding:2px 7px; border-radius:10px; font-size:10px; font-weight:bold; color:white; text-align:center; min-width:30px; }}
.low-jeo   {{ background-color:#2ecc71; }}
.low-jeo2  {{ background-color:#3498db; }}
.low-both  {{ background-color:#e74c3c; }}
.low-track {{ background-color:#95a5a6; }}

.ticker-col {{ cursor: pointer; text-decoration: underline dotted; }}
.ticker-col:hover {{ background: #fef3e2; }}
.chart-trigger {{ cursor: pointer; }}
.chart-trigger:hover {{ background-color: #fef3e2 !important; }}
.sortable {{ cursor: pointer; user-select: none; }}
.sortable:hover {{ background: linear-gradient(135deg, #d35400, #c0392b); }}
/* ── Chart Popup (Naver ETF 일/주봉 + TradingEconomics 단일 PNG) ── */
#chartPopup {{
  display: none; position: fixed; z-index: 99999;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  overflow-y: auto; max-height: 90dvh; overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}}
body.chart-open {{ overflow: hidden; }}
.cp-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
#chartPopupClose {{
  display: flex; background: #e74c3c; color: #fff;
  border: none; border-radius: 50%;
  width: 28px; height: 28px; font-size: 18px; line-height: 1;
  cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center; font-weight: bold;
}}
#chartPopupClose:hover {{ background: #c0392b; }}
.cp-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.cp-note  {{ font-size: 12px; color: #7f8c8d; white-space: nowrap; }}
.cp-link  {{ font-size: 12px; color: #2980b9; text-decoration: none; margin-left: auto; white-space: nowrap; }}
.cp-link:hover {{ text-decoration: underline; }}
.cp-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.cp-grid.single {{ grid-template-columns: 1fr; }}
.cp-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }}
.cp-wrap {{ position: relative; width: 100%; height: 300px; background: #fff; }}
.cp-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: #fff; }}
.cp-grid.single .cp-wrap img {{ object-fit: contain; }}
.cp-loading {{
  display: none; position: absolute; inset: 0;
  background: rgba(255,255,255,0.75);
  align-items: center; justify-content: center;
  font-size: 12px; color: #64748b;
}}
.cp-loading.show {{ display: flex; }}
@media (max-width: 767px) {{
  #chartPopup {{
    left: 2vw !important; top: 50% !important; transform: translateY(-50%);
    width: 96vw !important; max-height: 80dvh !important;
    padding: 8px !important; box-sizing: border-box;
  }}
  .cp-grid {{ grid-template-columns: 1fr; gap: 6px; }}
  .cp-wrap {{ height: 230px; }}
}}
@media (min-width: 768px) and (max-width: 1000px) {{
  #chartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
  .cp-grid {{ grid-template-columns: 1fr; }}
  .cp-wrap {{ height: 260px; }}
}}
.small-board {{
  flex: 1; min-width: 280px;
  background: white; padding: 16px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}}
.small-board h3 {{ margin: 0 0 10px 0; font-size: 1em; color: #2c3e50; }}
.meta {{ color: #888; font-size: 0.9em; margin-top: 20px; }}
@media (max-width: 480px) {{
  h1 {{ font-size: 1.0em !important; }}
  h2 {{ font-size: 0.95em !important; margin-top: 18px !important; padding-bottom: 6px !important; }}
}}
@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
</style>
</head>
<body>

<h1>🌍 해외선물 / FX / 암호화폐 Momentum Report</h1>
<div style="font-size: 0.9em; color: #888; margin-bottom: 20px;">
  📡 데이터: <strong>{data_time_str}</strong> &nbsp;|&nbsp; 📄 페이지: {now}
</div>

<h2>🎯 주문용 Top4 (오늘)</h2>
{text_to_html_table_top4(order_top4, ticker_meta)}

<h2>📊 해외선물 Momentum Top</h2>
<div style="display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap;">
  <div>{momentum_table_html}</div>
  <div>{currency_table_html}</div>
</div>

<h2>🚫 ATR 모니터링</h2>
<div style="display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px;">
  <div class="small-board">
    <h3>⚠️ ATR 트리거 (2주)</h3>
    {text_to_html_table_atr(atr_triggered, ["Ticker", "ATR"])}
  </div>
  <div class="small-board">
    <h3>🛡 ATR 제외</h3>
    {text_to_html_table_atr(atr_excluded, ["Ticker", "ATR"])}
  </div>
</div>

<h2>📈 Signal_sco 기준 종목 분포</h2>
<pre style="font-size: 12px; background: white; padding: 10px; border-radius: 4px;">{html.escape(dist_block)}</pre>

<p class="meta">{html.escape(runtime)}</p>

<!-- Chart Popup (Naver ETF 일/주봉 + TradingEconomics 단일 PNG) -->
<div id="chartPopup">
  <div class="cp-header">
    <button id="chartPopupClose" title="닫기">&#215;</button>
    <span class="cp-title" id="cpTitle">-</span>
    <span class="cp-note" id="cpNote"></span>
    <a id="cpLink" class="cp-link" href="#" target="_blank" rel="noopener noreferrer">원본 열기</a>
  </div>
  <div class="cp-grid" id="cpGrid">
    <div class="cp-card">
      <div class="cp-wrap">
        <img id="cpImg1" alt="chart 1">
        <div class="cp-loading" id="cpLoad1">불러오는 중...</div>
      </div>
    </div>
    <div class="cp-card" id="cpCard2">
      <div class="cp-wrap">
        <img id="cpImg2" alt="chart 2">
        <div class="cp-loading" id="cpLoad2">불러오는 중...</div>
      </div>
    </div>
  </div>
</div>

<script>
(function() {{
  // 선물 티커 → 차트 소스 매핑 (Python CHART_MAP 직렬화)
  var CHART_MAP = {chart_map_js};
  var VER = "{chart_ver}";

  var popup   = document.getElementById('chartPopup');
  var titleEl = document.getElementById('cpTitle');
  var noteEl  = document.getElementById('cpNote');
  var linkEl  = document.getElementById('cpLink');
  var grid    = document.getElementById('cpGrid');
  var card2   = document.getElementById('cpCard2');
  var img1    = document.getElementById('cpImg1');
  var img2    = document.getElementById('cpImg2');
  var load1   = document.getElementById('cpLoad1');
  var load2   = document.getElementById('cpLoad2');
  var hoverTimer = null, pinned = false;

  var TS = Date.now();
  function withTs(u) {{ return u + (u.indexOf('?') >= 0 ? '&' : '?') + 't=' + TS; }}
  function naverDay(c)  {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/day/'  + c + '_end.png'); }}
  function naverWeek(c) {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/week/' + c + '_end.png'); }}
  function naverPage(c) {{ return 'https://m.stock.naver.com/worldstock/stock/' + c + '/total'; }}
  function teUrl(sym)   {{ return 'https://d3fy651gv2fhd3.cloudfront.net/charts/embed.png?s=' + encodeURIComponent(sym) + '&v=' + VER + '&h=400&w=720&ref=/x'; }}
  function tePage(sym)  {{ return 'https://tradingeconomics.com/embed/?s=' + encodeURIComponent(sym); }}

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
    var cfg = CHART_MAP[T];
    if (!cfg) return false;   // 매핑 없는 티커(ZL 등) → 팝업 안 띄움
    titleEl.textContent = T;
    noteEl.textContent  = cfg.note ? '→ ' + cfg.note : '';
    if (cfg.src === 'naver') {{
      grid.classList.remove('single'); card2.style.display = '';
      linkEl.href = naverPage(cfg.code);
      loadInto(img1, load1, naverDay(cfg.code));
      loadInto(img2, load2, naverWeek(cfg.code));
    }} else {{
      grid.classList.add('single'); card2.style.display = 'none';
      linkEl.href = tePage(cfg.code);
      loadInto(img1, load1, teUrl(cfg.code));
      img2.removeAttribute('src');
    }}
    return true;
  }}

  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 420 : 380;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
    popup.style.transform = 'none';
  }}

  function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('chart-open'); }}
  function closePopup() {{ popup.style.display = 'none';  pinned = false; document.body.classList.remove('chart-open'); }}

  document.getElementById('chartPopupClose').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

  document.querySelectorAll('td[data-ticker]').forEach(function (el) {{
    var T = (el.getAttribute('data-ticker') || '').replace(/[*]/g, '').toUpperCase();
    if (!CHART_MAP[T]) return;   // 차트 없는 티커는 바인딩 안 함

    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      var cx = e.clientX, cy = e.clientY;
      hoverTimer = setTimeout(function () {{
        if (!loadCharts(T)) return;
        placePopup(cx, cy);
        openPopup();
      }}, 140);
    }});
    el.addEventListener('mousemove', function (e) {{
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    el.addEventListener('mouseleave', function () {{
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    el.addEventListener('click', function (e) {{
      if (window.innerWidth > 767) return;
      e.stopPropagation();
      if (loadCharts(T)) openPopup();
    }});
  }});
  (function () {{
    var seen = {{}}, queue = [];
    document.querySelectorAll('td[data-ticker]').forEach(function (el) {{
      var T = (el.getAttribute('data-ticker') || '').replace(/[*]/g, '').toUpperCase();
      if (!T || seen[T] || !CHART_MAP[T]) return;
      seen[T] = true; queue.push(T);
    }});
    var idx = 0, CONCURRENCY = 3;
    function next() {{
      if (idx >= queue.length) return;
      var cfg = CHART_MAP[queue[idx++]];
      var urls = (cfg.src === 'naver') ? [naverDay(cfg.code), naverWeek(cfg.code)] : [teUrl(cfg.code)];
      var done = 0, need = urls.length;
      function step() {{ if (++done >= need) next(); }}
      urls.forEach(function (u) {{ var im = new Image(); im.onload = step; im.onerror = step; im.src = u; }});
    }}
    setTimeout(function () {{ for (var i = 0; i < CONCURRENCY && i < queue.length; i++) next(); }}, 300);
  }})();

  (function () {{
    var curEl = null;
    var trig = [].slice.call(document.querySelectorAll('td[data-ticker]')).filter(function (el) {{
      var T = (el.getAttribute('data-ticker') || '').replace(/[*]/g, '').toUpperCase();
      return T && CHART_MAP[T];
    }});
    trig.forEach(function (el) {{
      el.addEventListener('mouseenter', function () {{ curEl = el; }});
      el.addEventListener('click', function () {{ curEl = el; }});
    }});
    try {{ popup.setAttribute('tabindex', '-1'); }} catch (e) {{}}
    var _open = openPopup;
    openPopup = function () {{
      _open();
      try {{
        var a = document.activeElement;
        if (a === document.body || a === null || a === document.documentElement) popup.focus({{ preventScroll: true }});
      }} catch (e) {{}}
    }};
    function kbPin() {{ pinned = true; }}
    function unpinOnMove() {{ pinned = false; document.removeEventListener('mousemove', unpinOnMove, true); }}
    function nav(dir) {{
      if (!trig.length || popup.style.display !== 'block') return;
      var i = curEl ? trig.indexOf(curEl) : -1;
      i = (i + dir + trig.length) % trig.length;
      var el = trig[i]; curEl = el;
      var T = (el.getAttribute('data-ticker') || '').replace(/[*]/g, '').toUpperCase();
      if (loadCharts(T)) {{
        var r = el.getBoundingClientRect();
        placePopup(r.left + r.width / 2, r.top + r.height / 2);
        kbPin();
        document.addEventListener('mousemove', unpinOnMove, true);
      }}
    }}
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
    document.addEventListener('keydown', function (e) {{
      if (popup.style.display !== 'block') return;
      var t = e.target, tn = t && t.tagName;
      if (tn === 'INPUT' || tn === 'TEXTAREA' || tn === 'SELECT' || (t && t.isContentEditable)) return;
      var k = e.key ? e.key.toLowerCase() : '';
      if (k === 'd') {{ e.preventDefault(); nav(1); }}
      else if (k === 's') {{ e.preventDefault(); nav(-1); }}
      else if (k === 'escape') {{ closePopup(); }}
    }});
  }})();
}})();
</script>


<script>
(function() {{
  function makeTableSortable(tableId) {{
    var table = document.getElementById(tableId);
    if (!table) return;
    var tbody = table.querySelector('tbody');
    var originalRows = Array.from(tbody.querySelectorAll('tr')).map(function(r) {{ return r.cloneNode(true); }});
    var sortState = {{ col: null, asc: true }};
    function getCellValue(row, col) {{
      var cells = row.querySelectorAll('td');
      if (!cells[col]) return '';
      return cells[col].innerText.trim();
    }}
    function toNum(str) {{
      var n = parseFloat(str.replace(/[^0-9.\x2D]/g, ''));
      return isNaN(n) ? null : n;
    }}
    table.querySelectorAll('th.sortable').forEach(function(th) {{
      th.addEventListener('click', function() {{
        var col = parseInt(th.getAttribute('data-col'));
        if (sortState.col === col) {{
          if (!sortState.asc) {{ resetSort(); return; }}
          sortState.asc = false;
        }} else {{
          sortState.col = col;
          sortState.asc = true;
        }}
        table.querySelectorAll('th.sortable').forEach(function(h) {{ h.classList.remove('asc', 'desc'); }});
        th.classList.add(sortState.asc ? 'asc' : 'desc');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort(function(a, b) {{
          var va = getCellValue(a, col);
          var vb = getCellValue(b, col);
          var na = toNum(va), nb = toNum(vb);
          var cmp = (na !== null && nb !== null) ? na - nb : va.localeCompare(vb, 'ko');
          return sortState.asc ? cmp : -cmp;
        }});
        rows.forEach(function(r) {{ tbody.appendChild(r); }});
      }});
    }});
    function resetSort() {{
      sortState = {{ col: null, asc: true }};
      table.querySelectorAll('th.sortable').forEach(function(h) {{ h.classList.remove('asc', 'desc'); }});
      originalRows.forEach(function(r) {{ tbody.appendChild(r.cloneNode(true)); }});
    }}
  }}
  makeTableSortable('momentum-table');
}})();
</script>

</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] {OUT_HTML.name} updated")


if __name__ == "__main__":
    main()
