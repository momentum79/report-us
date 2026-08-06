# make_index_us_finviz.py
import html
from pathlib import Path
from datetime import datetime
import re

BASE = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(BASE))
from chart_popup_v4 import build_chart_popup   # V4 내장형 일/주봉 인터랙티브 팝업
REPORT_TXT = BASE / "report_us_finviz.txt"
OUT_HTML = BASE / "us_finviz.html"

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

CHG_UP_COLOR = "#16a34a"
CHG_DN_COLOR = "#e74c3c"

def chg_cell_content(val):
    s = str(val).strip().replace("%", "").replace("+", "").replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return None
    if f > 0:
        color, sign = CHG_UP_COLOR, "+"
    elif f < 0:
        color, sign = CHG_DN_COLOR, ""
    else:
        color, sign = "#333", ""
    return f'<span style="color:{color};font-weight:600;">{sign}{f:.2f}%</span>'

def text_to_html_table(text, skip_first_row=False, table_id=None):
    if not text or text.strip().startswith("데이터 없음") or text.strip() == "없음":
        return f'<p style="padding-left:10px; color:#777;">{html.escape(text)}</p>'
    
    raw_lines = text.strip().splitlines()
    if not raw_lines: return ""

    valid_lines = [l for l in raw_lines if "【" not in l and not all(c in '-=' for c in l.strip())]
    if not valid_lines or (len(valid_lines) == 1 and ("없음" in valid_lines[0] or not valid_lines[0].strip())):
        return '<p style="padding-left:10px; color:#777;">없음</p>'
    
    if skip_first_row and len(valid_lines) > 0:
        valid_lines = valid_lines[1:]
        
    if not valid_lines: 
        return '<p style="padding-left:10px; color:#777;">없음</p>'

    id_attr = f' id="{table_id}"' if table_id else ''
    cls = "styled-tableWide sortable-table" if table_id else "styled-tableWide"
    html_output = [f'<table class="{cls}"{id_attr}>']

    # Header Detection
    first_line = valid_lines[0].strip()
    is_header = any(k in first_line for k in ["Ticker", "Signal", "Final", "수익률", "Industry", "Type"])

    start_idx = 0
    chg_cols = set()
    if is_header:
        # Determine headers based on content
        if "Type" in first_line:
            headers = ["Ticker", "Type", "Industry", "Amt(M$)"]
        elif "Industry" in first_line and "3M" in first_line:
            # MOM/LIME/GREEN/JUNG format: Ticker, Industry, Price($), 등락률(%), Sig_sco, 3M(%)
            headers = ["Ticker", "Industry", "Price($)", "등락률(%)", "Sig_sco", "3M(%)"]
        else:
            headers = ["Ticker", "Industry", "Price($)", "등락률(%)", "Sig_sco", "3M(%)", "Final_sco", "NewSig"]

        chg_cols = {i for i, h in enumerate(headers) if "등락" in h}

        if table_id:
            html_output.append(
                "<thead><tr>" +
                "".join(f'<th class="sortable" data-col="{i}">{html.escape(h.strip())}</th>' for i, h in enumerate(headers)) +
                "</tr></thead>"
            )
        else:
            html_output.append("<thead><tr>" + "".join(f"<th>{html.escape(h.strip())}</th>" for h in headers) + "</tr></thead>")
        start_idx = 1
    
    html_output.append("<tbody>")
    for line in valid_lines[start_idx:]:
        line = line.strip()
        if not line: continue
        
        # PC Fix: Handle cases where Ticker and Type/Industry are separated by a single space
        for sig in ["MOM", "LIME", "GREEN", "RED", "JUNG"]:
            if f" {sig} " in line:
                line = line.replace(f" {sig} ", f"  {sig}  ")
        
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 2: cols = line.split()

        row_html = "<tr>"
        for i, c in enumerate(cols):
            cls_list = []
            attrs = ""
            if i == 0 and len(c) <= 12: 
                cls_list.append("ticker-col")
                cls_list.append("chart-trigger")
                attrs = f' data-ticker="{html.escape(c)}"'
            
            # NewSig badge 렌더링
            cell_content = html.escape(c)
            if i in chg_cols:
                colored = chg_cell_content(c)
                if colored is not None:
                    cell_content = colored
            sig_map = {
                "🆕LIME": ("🆕LIME", "sig-badge sig-lime"),
                "🆕GRN":  ("🆕GRN",  "sig-badge sig-green"),
                "🆕MOM":  ("🆕MOM",  "sig-badge sig-mom"),
                "🆕RED":  ("🆕RED",  "sig-badge sig-red"),
            }
            for sig_key, (sig_label, sig_cls) in sig_map.items():
                if c.strip() == sig_key:
                    cell_content = f'<span class="{sig_cls}">{html.escape(sig_label)}</span>'
                    break

            cls_str = f' class="{" ".join(cls_list)}"' if cls_list else ''
            row_html += f"<td{cls_str}{attrs}>{cell_content}</td>"
        row_html += "</tr>"
        html_output.append(row_html)
    html_output.append("</tbody></table>")
    return "\n".join(html_output)

def text_to_html_columns(text, skip_first_row=False, max_cols=4, chunk=10, table_id_prefix=None):
    """
    데이터 행을 chunk개씩 끊어 가로 컬럼(최대 max_cols열)으로 배치.
    헤더행이 있으면 각 컬럼 테이블에 동일 헤더를 반복 적용.
    소스 데이터는 이미 sco/Final 내림차순 정렬 상태 → 순서 보존.
    """
    if not text or text.strip().startswith("데이터 없음") or text.strip() == "없음":
        return text_to_html_table(text, skip_first_row=skip_first_row)

    raw_lines = text.strip().splitlines()
    valid_lines = [l for l in raw_lines if "【" not in l and not all(c in '-=' for c in l.strip())]
    if skip_first_row and valid_lines:
        valid_lines = valid_lines[1:]
    valid_lines = [l for l in valid_lines if l.strip()]
    if not valid_lines:
        return '<p style="padding-left:10px; color:#777;">없음</p>'

    # 헤더행 분리
    header_line = None
    if any(k in valid_lines[0] for k in ["Ticker", "Signal", "Final", "수익률", "Industry", "Type"]):
        header_line = valid_lines[0]
        data_lines = valid_lines[1:]
    else:
        data_lines = valid_lines
    if not data_lines:
        return '<p style="padding-left:10px; color:#777;">없음</p>'

    data_lines = data_lines[: max_cols * chunk]
    chunks = [data_lines[i:i + chunk] for i in range(0, len(data_lines), chunk)]

    cols = []
    for idx, ch in enumerate(chunks):
        sub_lines = ([header_line] if header_line else []) + ch
        sub_text = "\n".join(sub_lines)
        tid = f"{table_id_prefix}-{idx}" if table_id_prefix else None
        tbl = text_to_html_table(sub_text, skip_first_row=False, table_id=tid)
        cols.append(f'<div class="col-table">{tbl}</div>')
    return f'<div class="table-columns">{"".join(cols)}</div>'


def parse_pipe_block_order(block_text):
    rows = []
    for line in block_text.splitlines():
        line = line.strip()
        if not line or line.startswith("=") or line.startswith("-"):
            continue
        if "Ticker" in line and "Weight" in line:
            continue
        if line == "None" or "없음" in line:
            continue
        if "|" in line:
            rows.append([p.strip() for p in line.split("|")])
    return rows


def rows_to_html_table_order(rows, table_id="order-a-table"):
    if not rows:
        return '<p style="padding-left:10px; color:#777;">(A급 주문 후보 없음)</p>'
    headers = ["Ticker", "Weight(%)", "Industry", "Price($)", "등락률(%)", "sco", "3M(%)", "Final", "Color", "NewSig"]
    html_out = [f'<table class="styled-tableWide sortable-table" id="{table_id}">']
    html_out.append("<thead><tr>" + "".join(f'<th class="sortable" data-col="{i}">{html.escape(h)}</th>' for i, h in enumerate(headers)) + "</tr></thead>")
    html_out.append("<tbody>")
    for parts in rows:
        if len(parts) < 10:
            continue
        ticker, weight, industry, price, chg, sco, rtn, final, color, newsig = parts[:10]
        ticker_clean = ticker.replace("*", "").strip()
        row_html = f'<tr><td class="ticker-col chart-trigger" data-ticker="{html.escape(ticker_clean)}">{html.escape(ticker)}</td>'
        row_html += f"<td>{html.escape(weight)}</td><td>{html.escape(industry)}</td><td>{html.escape(price)}</td>"
        colored = chg_cell_content(chg)
        row_html += f"<td>{colored if colored is not None else html.escape(chg)}</td>"
        row_html += f"<td>{html.escape(sco)}</td><td>{html.escape(rtn)}</td><td>{html.escape(final)}</td><td>{html.escape(color)}</td><td>{html.escape(newsig)}</td></tr>"
        html_out.append(row_html)
    html_out.append("</tbody></table>")
    return "\n".join(html_out)

def main():
    text = REPORT_TXT.read_text(encoding="utf-8", errors="replace") if REPORT_TXT.exists() else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Extraction with separate variables
    mom_block_raw = extract_block(
        text,
        "【MOM(모멘텀) 돌파】",
        ["【LIME", "【GREEN", "=== 주문용 Top4"]
    )
    mom_html = text_to_html_columns(mom_block_raw, skip_first_row=True, max_cols=4, chunk=10)

    lime_block_raw = extract_block(
        text,
        "【LIME 신호 (매수)】",
        ["【GREEN", "=== 주문용 Top4"]
    )
    lime_html = text_to_html_columns(lime_block_raw, skip_first_row=True, max_cols=4, chunk=10)

    green_block_raw = extract_block(
        text,
        "【GREEN 신호 (관심)】",
        ["【🔥 JUNG 정배열 돌파", "=== 주문용 Top4"]
    )
    green_html = text_to_html_columns(green_block_raw, skip_first_row=True, max_cols=4, chunk=10)

    jung_block_raw = extract_block(
        text,
        "【🔥 JUNG 정배열 돌파】",
        ["=== US Stock Momentum Top", "=== 주문용 Top4"]
    )
    jung_html = text_to_html_columns(jung_block_raw, skip_first_row=True, max_cols=4, chunk=10)

    momentum_raw = extract_block(
        text,
        "=== US Stock Momentum Top ===",
        ["【MOM", "【LIME", "=== 주문용 Top4", "==="]
    ) or "(US Momentum Top 없음)"
    momentum_block = "\n".join([l for l in momentum_raw.splitlines() if "US Stock Momentum Top" not in l]).strip()

    order_raw = extract_block(
        text,
        "=== 주문용 Top4 (오늘) ===",
        ["이전 Top4:", "==="]
    ) or "(주문용 Top4 없음)"
    order_top4 = "\n".join([l for l in order_raw.splitlines() if "주문용 Top4" not in l]).strip()

    order_a_raw = extract_block(
        text,
        "=== ORDER A max10",
        ["=== 주문용", "==="]
    )
    order_a_rows = parse_pipe_block_order(order_a_raw)
    order_a_html = rows_to_html_table_order(order_a_rows)

    atr_raw = extract_block(
        text,
        "🚫 ATR 필터로 제외된 종목",
        ["✅ ATR 필터로 제외된 종목 없음", "Signal_sco 기준 종목 분포", "="]
    ) or "(ATR 제외 종목 없음)"
    atr_block = "\n".join([l for l in atr_raw.splitlines() if "ATR 필터" not in l]).strip()

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>US Finviz Sector Report</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 15px;
  margin: 0;
  background-color: #f4f7f6;
  line-height: 1.4;
}}
h2 {{
  margin-top: 15px;
  margin-bottom: 10px;
  padding-bottom: 5px;
  color: #2c3e50;
  border-bottom: 2px solid #e67e22;
  font-size: 1.4em;
}}
.signal-header {{
  margin-top: 10px;
  margin-bottom: 5px;
  padding-bottom: 3px;
  color: #2c3e50;
  font-size: 1.1em;
  border-bottom: 1px solid #e67e22;
}}
.styled-tableWide {{
  width: auto;
  min-width: 300px;
  max-width: 100%;
  border-collapse: collapse;
  margin: 5px 0 15px 0;
  font-size: 12px;
  background: white;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  border-radius: 6px;
  overflow: hidden;
}}
.styled-tableWide thead tr {{
  background-color: #e67e22;
  color: #ffffff;
  text-align: left;
}}
.styled-tableWide th, .styled-tableWide td {{
  padding: 4px 10px;
  border-bottom: 1px solid #eee;
  white-space: nowrap;
}}
.styled-tableWide td.ticker-col {{
  width: 70px;
  font-weight: 600;
}}
.styled-tableWide tbody tr:nth-of-type(even) {{
  background-color: #fdf8f4;
}}
.styled-tableWide tbody tr:last-of-type {{
  border-bottom: 2px solid #e67e22;
}}
@media (max-width: 600px) {{
  .styled-tableWide {{
    font-size: 10px;
  }}
  .styled-tableWide th, .styled-tableWide td {{
    padding: 3px 4px;
  }}
  .styled-tableWide td.ticker-col {{ width: 50px; }}
}}
.header {{
  background: #2c3e50;
  color: white;
  padding: 15px;
  border-radius: 6px;
  margin-bottom: 15px;
  border-left: 8px solid #e67e22;
}}
.header h1 {{ margin: 0; font-size: 1.6em; }}
.meta {{
  color: #555;
  margin-top: 5px;
  font-size: 0.85em;
}}
.sig-badge {{
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}}
.sig-lime  {{ background: #c8f77a; color: #2a5000; }}
.sig-green {{ background: #b6eac4; color: #1a4a28; }}
.sig-mom   {{ background: #c9a8f7; color: #3a006f; }}
.sig-red   {{ background: #f7b8b8; color: #7a0000; }}
        /* ── TRADINGVIEW BACKUP (commented out for Naver migration; restore by removing surrounding comment markers and re-enabling inner * / markers) ──
        ── TradingView Chart Popup ── (legacy)
        #chart-popup {{
            position: fixed; z-index: 10000;
            width: 820px; height: 560px;
            background: #fcfbf7; border: 1px solid #ddd8ce;
            border-radius: 10px; box-shadow: 0 20px 60px rgba(0,0,0,.55);
            display: none; flex-direction: column;
            overflow: hidden; opacity: 0;
            transition: opacity .15s ease; pointer-events: none;
        }}
        #chart-popup.visible {{ display: flex; opacity: 1; pointer-events: auto; }}
        .chart-ph {{
            display: flex; align-items: center; gap: 8px;
            padding: 8px 12px; border-bottom: 1px solid #ddd8ce;
            background: #f0ece3; flex-shrink: 0;
        }}
        #btn-close-popup {{
            width: 28px; height: 28px; min-width: 28px;
            background: #e5e0d8; border: none; border-radius: 4px;
            color: #555; cursor: pointer; font-size: 18px;
            display: flex; align-items: center; justify-content: center;
            transition: background .12s;
        }}
        #btn-close-popup:hover {{ background: #c84040; color: #fff; }}
        .chart-tb-group {{ display: flex; gap: 4px; }}
        .chart-tb {{
            padding: 4px 10px; font-size: 12px; font-family: monospace;
            cursor: pointer; border: 1px solid #ddd8ce; background: transparent;
            color: #6b7280; border-radius: 3px; transition: all .12s;
            white-space: nowrap; min-width: 36px; text-align: center;
        }}
        .chart-tb:hover {{ border-color: #aaa; color: #333; }}
        .chart-tb.on {{ background: #c84b00; border-color: #c84b00; color: #fff; }}
        #tv-container {{ flex: 1; min-height: 0; width: 100%; position: relative; }}
        #tv-container .tradingview-widget-container,
        #tv-container .tradingview-widget-container__widget {{
            width: 100% !important; height: 100% !important;
        }}
        (legacy) 세로모드 - 현재 그대로
        @media (max-width: 1024px) and (orientation: portrait) {{
            #chart-popup {{
                width: 96vw !important; height: 72vh !important;
                left: 2vw !important; top: 14vh !important;
                right: auto !important; bottom: auto !important;
            }}
            .chart-tb {{ padding: 5px 10px; font-size: 13px; min-width: 40px; }}
            #btn-close-popup {{ width: 32px; height: 32px; min-width: 32px; font-size: 20px; }}
        }}
        (legacy) 가로모드 - 전체화면
        @media (max-width: 1024px) and (orientation: landscape) {{
            .chart-tb {{ padding: 5px 10px; font-size: 13px; min-width: 40px; }}
            #btn-close-popup {{ width: 36px; height: 36px; min-width: 36px; font-size: 22px; }}
        }}
        #chart-popup.landscape-mode {{
            position: fixed !important;
            width: 100vw !important; height: 100dvh !important;
            left: 0 !important; top: 0 !important;
            margin: 0 !important;
            border-radius: 0 !important;
            border: none !important;
            z-index: 999999 !important;
        }}
        (legacy) 가로모드: 버튼바를 차트 위에 overlay로 띄워서 tv-container가 100% 차지 → 날짜 짤림 해결
        #chart-popup.landscape-mode .chart-ph {{
            position: absolute !important;
            top: 0 !important; left: 0 !important; right: 0 !important;
            z-index: 10 !important;
            background: rgba(240,236,227,0.88) !important;
            border-bottom: none !important;
        }}
        #chart-popup.landscape-mode #tv-container {{
            position: absolute !important;
            top: 0 !important; left: 0 !important;
            width: 100% !important; height: 100% !important;
        }}
        ── TRADINGVIEW BACKUP END ── */

        /* ── Naver Chart Popup (active) ── */
        #naverChartPopup {{
            display: none; position: fixed; z-index: 99999;
            width: 860px; background: #fff;
            border: 1px solid #bdc3c7; border-radius: 10px;
            padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
            pointer-events: auto; overflow-y: auto;
            max-height: 90dvh; overscroll-behavior: contain;
            -webkit-overflow-scrolling: touch;
        }}
        body.naver-popup-open {{ overflow: hidden; }}
        #naverPopupClose {{
            display: flex; background: #e74c3c; color: white;
            border: none; border-radius: 50%;
            width: 28px; height: 28px;
            font-size: 18px; line-height: 1;
            cursor: pointer; flex-shrink: 0;
            align-items: center; justify-content: center;
            font-weight: bold;
        }}
        .naver-popup-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
        .naver-popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
        .naver-popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; margin-left: 1em; }}
        .naver-popup-link:hover {{ text-decoration: underline; }}
        .naver-charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .naver-chart-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }}
        .naver-chart-wrap {{ position: relative; width: 100%; height: 300px; background: white; }}
        .naver-chart-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: white; }}
        .naver-chart-loading {{
            display: none; position: absolute; inset: 0;
            background: rgba(255,255,255,0.75);
            align-items: center; justify-content: center;
            font-size: 12px; color: #64748b;
        }}
        .naver-chart-loading.show {{ display: flex; }}
        @media (max-width: 767px) {{
            #naverChartPopup {{
                position: fixed !important; left: 2vw !important;
                top: 50% !important; transform: translateY(-50%);
                width: 96vw !important; max-height: 80dvh !important;
                overflow-y: auto !important; padding: 8px !important;
                box-sizing: border-box;
            }}
            .naver-charts-grid {{ grid-template-columns: 1fr; gap: 6px; }}
            .naver-chart-wrap {{ height: 220px; }}
        }}
        @media (min-width: 768px) and (max-width: 1000px) {{
            #naverChartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
            .naver-charts-grid {{ grid-template-columns: 1fr; }}
            .naver-chart-wrap {{ height: 260px; }}
        }}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
.sortable {{ cursor: pointer; user-select: none; }}
.sortable:hover {{ background-color: #d35400; }}
.table-columns {{
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: flex-start;
  margin-bottom: 15px;
}}
.table-columns .col-table {{ flex: 0 0 auto; }}
.table-columns .col-table .styled-tableWide {{ margin: 5px 0; }}
@media (max-width: 600px) {{
  .table-columns {{ gap: 8px; }}
}}
</style>
</head>
<body>

<p style="margin: 0 0 10px 0; color: #000; font-size: 0.9em;">공식 업데이트: {now} <small style="color: #ccc; font-size: 10px;">v1.6</small></p>

<h2>🧾 주문용 A급 max10 (동일비중)</h2>
{order_a_html}

<h3 class="signal-header">🚀 MOM (모멘텀) 돌파</h3>
{mom_html}

<h3 class="signal-header">🟢 LIME 신호 (매수)</h3>
{lime_html}

<h3 class="signal-header">🌱 GREEN 신호 (관심)</h3>
{green_html}

<h2>🏆 US Sector 우량주 Top 30</h2>
{text_to_html_columns(momentum_block, max_cols=4, chunk=10, table_id_prefix='top30-table')}

<h2>🚫 ATR 필터로 제외된 종목</h2>
{text_to_html_table(atr_block)}

<h3 class="signal-header">🔥 JUNG 정배열 돌파</h3>
{jung_html}

<div class="meta" style="text-align:center; margin-top:30px; padding-bottom: 40px;">
    Analysis Source: usa_jasantop4_stocks.py <br>
    Selected based on Finviz Map Sectors
</div>


    <!-- TRADINGVIEW BACKUP (commented out for Naver migration; restore by removing this wrapper)
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
    TRADINGVIEW BACKUP END -->

    <!-- Naver Chart Popup (active) -->
    __V4_BLOCK__

    <!-- TRADINGVIEW BACKUP (commented out for Naver migration; restore by removing this wrapper)
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
            var isLandscape = window.matchMedia('(orientation: landscape)').matches;
            var isSmall = window.innerWidth <= 768;
            popup.classList.remove('landscape-mode');
            popup.style.cssText = '';
            if (!isSmall) {{
                var pw = 820, ph = 560;
                var px = x + 24, py = y - 280;
                var W = window.innerWidth, H = window.innerHeight;
                if (px + pw > W) px = W - pw - 10;
                if (px < 10) px = 10;
                if (py + ph > H) py = H - ph - 10;
                if (py < 10) py = 10;
                popup.style.left = px + 'px'; popup.style.top = py + 'px';
                popup.style.width = pw + 'px'; popup.style.height = ph + 'px';
            }} else if (isLandscape) {{
                popup.classList.add('landscape-mode');
                if (window.parent && window.parent !== window) {{
                    window.parent.postMessage({{action: 'openChart'}}, '*');
                }}
            }} else {{
                popup.style.width = '96vw'; popup.style.height = '72dvh';
                popup.style.left = '2vw'; popup.style.top = '14dvh';
            }}
            popup.classList.add('visible');
            loadChart(clean, currentInterval);
        }}

        function hideChart() {{
            var wasLandscape = popup.classList.contains('landscape-mode');
            popup.classList.remove('visible');
            popup.classList.remove('landscape-mode');
            tvCont.innerHTML = '';
            currentTicker = '';
            if (wasLandscape && window.parent && window.parent !== window) {{
                window.parent.postMessage({{action: 'closeChart'}}, '*');
            }}
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

    <!-- Naver Chart Popup script (active) -->
    <script>
    (function () {{
      return;   // V4 팝업으로 대체됨 (아래 네이버 PNG 로직 비활성)
      var NAVER_CODES = {{ QQQ: 'QQQ.O', SMH: 'SMH.O' }};
      var SUFFIX_TRY = ['.O', '.P', '', '.N', '.A', '.K'];
      var resolvedCode = {{}};
      var popup     = document.getElementById('naverChartPopup');
      var titleEl   = document.getElementById('naverPopupTitle');
      var linkEl    = document.getElementById('naverPopupLink');
      var imgDaily  = document.getElementById('naverImgDaily');
      var imgWeekly = document.getElementById('naverImgWeekly');
      var loadDaily = document.getElementById('naverLoadingDaily');
      var loadWeekly= document.getElementById('naverLoadingWeekly');
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
        titleEl.textContent = T + ' (resolving...)';
        linkEl.href = '#';
        loadDaily.classList.add('show');
        loadWeekly.classList.add('show');
        imgDaily.removeAttribute('src');
        imgWeekly.removeAttribute('src');
        resolveCode(T, function (code) {{
          if (!code) {{
            titleEl.textContent = T + '  (all suffixes failed)';
            loadDaily.classList.remove('show');
            loadWeekly.classList.remove('show');
            return;
          }}
          titleEl.textContent = T + '  [' + code + ']';
          linkEl.href = pageUrl(code);
          loadInto(imgDaily,  loadDaily,  dailyUrl(code));
          loadInto(imgWeekly, loadWeekly, weeklyUrl(code));
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
        popup.style.transform = 'none';
      }}

      function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('naver-popup-open'); }}
      function closePopup() {{ popup.style.display = 'none';  pinned = false; document.body.classList.remove('naver-popup-open'); }}

      document.getElementById('naverPopupClose').addEventListener('click', closePopup);
      popup.addEventListener('mouseenter', function () {{ pinned = true; }});
      popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

      document.querySelectorAll('td[data-ticker]').forEach(function (el) {{
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
          if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
        }});
        el.addEventListener('mouseleave', function () {{
          clearTimeout(hoverTimer);
          setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
        }});
        el.addEventListener('click', function (e) {{
          if (window.innerWidth > 767) return;
          e.stopPropagation();
          openPopup();
          loadCharts(el.getAttribute('data-ticker') || '');
        }});
      }});

      // === D/S 단축키 (D/↓=다음, S/↑=이전, Tab/ESC=닫기) · PNG라 A(슈퍼트렌드)는 제외 ===
      (function(){{
        var SEL = 'td[data-ticker]';
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

<script>
(function() {{
  function makeTableSortable(tableOrId) {{
    var table = (typeof tableOrId === 'string') ? document.getElementById(tableOrId) : tableOrId;
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
  document.querySelectorAll('table.sortable-table').forEach(function(t) {{ makeTableSortable(t); }});
}})();
</script>

</body>
</html>
"""
    _us_tickers = sorted({t.upper().replace('*', '') for t in re.findall(r'data-ticker="([^"]+)"', page)})
    page = page.replace('__V4_BLOCK__', build_chart_popup(_us_tickers))
    OUT_HTML.write_text(page, encoding="utf-8")
    print("[OK] us_finviz.html updated")

if __name__ == "__main__":
    main()
