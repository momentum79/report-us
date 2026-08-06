# make_index_us.py
import csv
import html
import json
import re
import sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from chart_popup_v4 import build_chart_popup   # V4 내장형 일/주봉 인터랙티브 팝업
REPORT_TXT = BASE / "report_us.txt"
OUT_HTML_LIST = [BASE / "us_stock.html"]


CHG_UP_COLOR = "#16a34a"
CHG_DN_COLOR = "#e74c3c"

def chg_cell(val):
    """등락률(%) 셀: 상승=lime, 하락=빨간색, 소수점 2자리."""
    s = str(val).strip().replace("%", "").replace("+", "").replace(",", "")
    try:
        f = float(s)
    except (TypeError, ValueError):
        return f'<td>{html.escape(str(val))}</td>'
    if f > 0:
        color, sign = CHG_UP_COLOR, "+"
    elif f < 0:
        color, sign = CHG_DN_COLOR, ""
    else:
        color, sign = "#333", ""
    return f'<td style="color:{color};font-weight:600;">{sign}{f:.2f}%</td>'

def chg_cell_content(val):
    """색상 span만 반환(td 없이). 매칭 실패 시 None."""
    s = str(val).strip().replace("%", "").replace("+", "").replace(",", "")
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    if f > 0:
        color, sign = CHG_UP_COLOR, "+"
    elif f < 0:
        color, sign = CHG_DN_COLOR, ""
    else:
        color, sign = "#333", ""
    return f'<span style="color:{color};font-weight:600;">{sign}{f:.2f}%</span>'

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


def extract_atr_block(text):
    return extract_block(
        text,
        "================================================================================",
        ["Signal_sco 기준 종목 분포"]
    )


def extract_distribution_block(text):
    return extract_block(
        text,
        "Signal_sco 기준 종목 분포",
        ["[실행 시간]"]
    )


def extract_runtime(text):
    for line in text.splitlines():
        if line.strip().startswith("[실행 시간]"):
            return line.strip()
    return ""


import re

def text_to_html_table(text, headers=None, chg_cols=None):
    if not text or text.strip().startswith("데이터 없음"):
        return f'<p>{html.escape(text)}</p>'

    chg_cols = chg_cols or set()
    raw_lines = text.strip().splitlines()
    if not raw_lines: return ""

    data_lines = [line for line in raw_lines if not all(c in '-=' for c in line.strip())]
    if not data_lines: return f'<pre>{html.escape(text)}</pre>'

    html_output = ['<table class="styled-tableWide">']

    # Header Detection with Manual Forced Splitting for PC
    first_line = data_lines[0].strip()
    is_header = any(k in first_line for k in ["Ticker", "Signal", "Final", "수익률"])

    start_idx = 0
    if is_header:
        # User request: Rename columns for US Stock report
        if headers is None:
            headers = ["Ticker", "Sigsco", "3M(%)", "1M(%)", "Earlysco", "Finalsco", "NewSig"]
        html_output.append("<thead><tr>" + "".join(f"<th>{html.escape(h.strip())}</th>" for h in headers) + "</tr></thead>")
        start_idx = 1

    html_output.append("<tbody>")
    for line in data_lines[start_idx:]:
        line = line.strip()
        if not line: continue
        
        # [Fix] Skip footer/meta lines that aren't real data rows
        if any(x in line for x in ["[저장", "완료]", "제외된 종목 수", "===", "---"]):
            continue

        # [Fix] Skip repeated section-header rows (report_us.txt has multiple
        # "Ticker  ..." headers; only the first is stripped above). Otherwise
        # "Ticker" leaks into a data-ticker cell → yfinance 404 on "TICKER".
        if line.split()[0].strip().lower() == "ticker":
            continue

        # [Fix] US data rows are pure ASCII; any Hangul means a prose/meta line
        # (e.g. "ATR 필터로 제외된 종목...") that would otherwise leak its first
        # word as a bogus data-ticker cell.
        if re.search(r'[가-힣]', line):
            continue

        # Aggressive split for data rows too
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 2: cols = line.split()
        
        # Additional check: if first column has spaces or is too long, it might be a sentence
        if len(cols) > 0 and (len(cols[0]) > 15 or " " in cols[0].strip()):
            continue

        row_html = "<tr>"
        for i, c in enumerate(cols):
            cls_list = []
            attrs = ""
            if i == 0 and len(c) <= 10:
                cls_list.append("ticker-col")
                cls_list.append("chart-trigger")
                attrs = f' data-ticker="{html.escape(c)}"'

            cell_content = html.escape(c)
            if i in chg_cols:
                colored = chg_cell_content(c)
                if colored is not None:
                    cell_content = colored

            cls_str = f' class="{" ".join(cls_list)}"' if cls_list else ''
            row_html += f"<td{cls_str}{attrs} style='cursor:pointer;'>{cell_content}</td>"
        row_html += "</tr>"
        html_output.append(row_html)
    html_output.append("</tbody></table>")
    return "\n".join(html_output)


def mark_stage1_to_html(csv_path):
    """미너비니 1차(추세템플릿+RS) 통과 종목 → 8열 그리드(RS 병기).
    us_minervini_2stage.py 가 저장하는 us_minervini_stage1.csv 중 Minervini_pass=True 행만 사용."""
    if not csv_path.exists():
        return "<p>(1차 통과 데이터 없음)</p>"
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return "<p>(1차 통과 데이터 읽기 실패)</p>"

    passed = [r for r in rows if (r.get("Minervini_pass") or "").strip() == "True"]
    if not passed:
        return "<p>(1차 통과 종목 없음)</p>"

    def rs_of(r):
        try:
            return float(r.get("RS_rating") or 0)
        except (TypeError, ValueError):
            return 0.0

    passed.sort(key=rs_of, reverse=True)

    cells = []
    for r in passed:
        tkr = html.escape((r.get("Ticker") or "").strip())
        rs = rs_of(r)
        cells.append(
            f'<td class="chart-trigger" data-ticker="{tkr}" style="cursor:pointer;">'
            f'{tkr} <span style="color:#888;">{rs:.0f}</span></td>'
        )

    # 8개씩 행으로 나누기
    ncol = 8
    rows_html = [cells[i:i + ncol] for i in range(0, len(cells), ncol)]

    html_output = ['<table class="mark-vcp-table"><tbody>']
    for row in rows_html:
        row_html = "<tr>" + "".join(row)
        for _ in range(ncol - len(row)):
            row_html += "<td></td>"
        row_html += "</tr>"
        html_output.append(row_html)
    html_output.append("</tbody></table>")
    return "\n".join(html_output)


def minervini2_to_html(csv_path):
    """미너비니 2차 진입 후보 CSV(us_minervini_stage2_final.csv) → HTML 테이블.
    1차(추세템플릿) 통과 종목 중 VCP 피벗 박스 돌파 단계(BREAKOUT_TODAY 등)만."""
    if not csv_path.exists():
        return "<p>(미너비니 2차 데이터 없음)</p>"
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return "<p>(미너비니 2차 데이터 읽기 실패)</p>"
    if not rows:
        return "<p>(미너비니 2차 진입 후보 없음)</p>"

    def fnum(v, nd=2, suffix=""):
        try:
            return f"{float(v):.{nd}f}{suffix}"
        except (TypeError, ValueError):
            return html.escape(str(v or ""))

    def status_of(r):
        return (r.get("status") or "").strip().upper()

    def setup_sort_key(r):
        try:
            setup = float(r.get("setup_score") or 0)
        except (TypeError, ValueError):
            setup = 0.0
        try:
            rs = float(r.get("RS_rating") or 0)
        except (TypeError, ValueError):
            rs = 0.0
        return (-setup, -rs)

    def render_table(title, desc, subset, empty_msg):
        headers = ["Ticker", "Price($)", "등락률(%)", "상태", "등급", "점수", "RS", "피벗", "거리%", "거래량비", "수축"]
        out = [
            f'<h3 style="margin:8px 0 4px 0;color:#2c3e50;font-size:0.98em;">{html.escape(title)}</h3>',
            f'<p style="margin:0 0 6px 0;color:#777;font-size:0.8em;">{html.escape(desc)}</p>',
        ]
        if not subset:
            out.append(f'<p style="margin:0 0 10px 0;color:#999;font-size:0.85em;">{html.escape(empty_msg)}</p>')
            return "\n".join(out)

        out.extend([
            '<table class="styled-tableWide">',
            "<thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>",
            "<tbody>",
        ])
        for r in subset:
            tkr = html.escape((r.get("ticker") or "").strip())
            out.append(
                "<tr>"
                f'<td class="ticker-col chart-trigger" data-ticker="{tkr}" style="cursor:pointer;font-weight:bold;color:#2980b9;">{tkr}</td>'
                f'<td>{fnum(r.get("close_now"))}</td>'
                f'{chg_cell(r.get("chg_pct"))}'
                f'<td>{html.escape((r.get("status") or "").strip())}</td>'
                f'<td>{html.escape((r.get("setup_grade") or "").strip())}</td>'
                f'<td>{fnum(r.get("setup_score"), 1)}</td>'
                f'<td>{fnum(r.get("RS_rating"), 0)}</td>'
                f'<td>{fnum(r.get("pivot"))}</td>'
                f'<td>{fnum(r.get("pivot_dist_pct"))}</td>'
                f'<td>{fnum(r.get("volume_ratio"))}</td>'
                f'<td>{html.escape((r.get("contractions") or "").strip())}</td>'
                "</tr>"
            )
        out.append("</tbody></table>")
        return "\n".join(out)

    breakout_rows = sorted([r for r in rows if status_of(r) == "BREAKOUT_TODAY"], key=setup_sort_key)
    pre_rows = sorted([r for r in rows if status_of(r) == "PRE_BREAKOUT"], key=setup_sort_key)
    other_rows = sorted([r for r in rows if status_of(r) not in ("BREAKOUT_TODAY", "PRE_BREAKOUT")], key=setup_sort_key)

    return "\n".join([
        render_table(
            "① VCP 돌파 매수 후보",
            "BREAKOUT_TODAY만 실제 매수 대상입니다. 점수는 후보 우선순위용입니다.",
            breakout_rows,
            "오늘 돌파 매수 후보가 없습니다.",
        ),
        render_table(
            "② VCP 피벗 대기 후보",
            "PRE_BREAKOUT은 매수 대상이 아니라 피벗 돌파 감시 대상입니다. 한국 V2식 점수로 우선순위를 정렬합니다.",
            pre_rows,
            "오늘 피벗 대기 후보가 없습니다.",
        ),
        render_table(
            "③ VCP 돌파 약함 / 추격주의",
            "BREAKOUT_WEAK 또는 EXTENDED는 주문 대상에서 제외합니다.",
            other_rows,
            "오늘 돌파 약함/추격주의 후보가 없습니다.",
        ),
    ])


def minervini_tracker_to_html(json_path):
    """🎯 VCP 돌파 추적 테이블(S:-6%, P:+12%, 21거래일) → HTML.
    BREAKOUT_TODAY 출현일 종가를 기준가로 21거래일간 추적하고,
    1887 실주문 로그가 조인된 종목은 매수가 대비 손익·보유일차·잔여일(D-)을 함께 보여준다."""
    if not json_path.exists():
        return "<p>(추적 데이터 없음)</p>"
    try:
        with open(json_path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return "<p>(추적 데이터 읽기 실패)</p>"
    rows = doc.get("rows", [])
    ledger_path = json_path.with_name("minervini_tracker.json")
    if ledger_path.exists():
        try:
            with open(ledger_path, encoding="utf-8") as f:
                ledger = json.load(f)
            breakout_tickers = {
                t for t, e in ledger.items()
                if isinstance(e, dict) and e.get("entry_status") == "BREAKOUT_TODAY"
            }
            rows = [r for r in rows if (r.get("ticker") or "").strip() in breakout_tickers]
        except Exception:
            pass
    if not rows:
        return "<p>(돌파 추적 종목 없음 — BREAKOUT_TODAY 종목이 출현하면 등록됩니다)</p>"

    def vx_cell(val):
        if val == "V":
            return '<td style="color:#27ae60;font-weight:bold;">V</td>'
        return '<td style="color:#e74c3c;font-weight:bold;">X</td>'

    def hold_cell(r):
        """보유일차 / 잔여(D-) 2칸. 미매수면 '-'."""
        if not r.get("held"):
            return '<td style="color:#95a5a6;">미매수</td><td style="color:#95a5a6;">-</td>'
        hd = int(r.get("hold_days") or 0)
        left = int(r.get("days_left") or 0)
        if left <= 0:
            badge = '<td style="color:#e74c3c;font-weight:bold;">⏰ 청산</td>'
        elif left <= 3:
            badge = f'<td style="color:#e67e22;font-weight:bold;">D-{left}</td>'
        else:
            badge = f'<td>D-{left}</td>'
        return f'<td style="font-weight:bold;">{hd}일차</td>{badge}'

    def pnl_cell(r):
        if not r.get("held"):
            return '<td style="color:#95a5a6;">-</td><td style="color:#95a5a6;">-</td>'
        pnl = r.get("pnl_pct") or 0.0
        color = "#27ae60" if pnl >= 0 else "#e74c3c"
        hit = r.get("hit") or ""
        if hit == "익절":
            hit_html = '<span style="background:#27ae60;color:#fff;border-radius:3px;padding:0 4px;">익절</span>'
        elif hit == "손절":
            hit_html = '<span style="background:#e74c3c;color:#fff;border-radius:3px;padding:0 4px;">손절</span>'
        else:
            hit_html = ""
        return (f'<td>{r.get("buy_price", 0):.2f}</td>'
                f'<td style="color:{color};font-weight:bold;">{pnl:+.2f}% {hit_html}</td>')

    headers = ["Ticker", "등락률", "현재가", "돌파후", "경과",
               "매수가", "손익", "보유", "잔여", "10", "20", "60"]
    out = ['<p style="margin:4px 0;color:#7f8c8d;font-size:12px;">'
           '손절 -6% · 익절 +12% · 21거래일 시간청산 (보유일차는 실주문 로그 기준, 미체결분 포함될 수 있음)</p>',
           '<table class="styled-tableWide">',
           "<thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead>",
           "<tbody>"]
    for r in rows:
        tkr = html.escape((r.get("ticker") or "").strip())
        chg = r.get("chg_pct", 0.0) or 0.0
        ret = r.get("ret_pct", 0.0) or 0.0
        chg_color = "#27ae60" if chg >= 0 else "#e74c3c"
        ret_color = "#27ae60" if ret >= 0 else "#e74c3c"
        out.append(
            "<tr>"
            f'<td class="ticker-col chart-trigger" data-ticker="{tkr}" style="cursor:pointer;font-weight:bold;color:#2980b9;">{tkr}</td>'
            f'<td style="color:{chg_color};font-weight:bold;">{chg:+.2f}%</td>'
            f'<td>{r.get("close", 0):.2f}</td>'
            f'<td style="color:{ret_color};font-weight:bold;">{ret:+.2f}%</td>'
            f'<td>{int(r.get("elapsed", 0))}일째</td>'
            + pnl_cell(r) + hold_cell(r)
            + vx_cell(r.get("v10")) + vx_cell(r.get("v20")) + vx_cell(r.get("v60"))
            + "</tr>"
        )
    out.append("</tbody></table>")
    return "\n".join(out)


def main():
    text = REPORT_TXT.read_text(encoding="utf-8", errors="replace") if REPORT_TXT.exists() else ""
    text_etf = (BASE / "report_us_etf.txt").read_text(encoding="utf-8", errors="replace") if (BASE / "report_us_etf.txt").exists() else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 마크-1차통과 (미너비니 1차 추세템플릿+RS 통과 종목)
    mark_vcp_html = mark_stage1_to_html(BASE / "us_minervini_stage1.csv")

    # 미너비니 2차 진입 (1차 추세템플릿 통과 → VCP 피벗 돌파)
    minervini2_html = minervini2_to_html(BASE / "us_minervini_stage2_final.csv")

    # 🎯 미너비니주 지표 추적 테이블 (P:10%, S:-5%, 2주홀딩)
    minervini_tracker_html = minervini_tracker_to_html(BASE / "minervini_tracker_view.json")

    momentum_raw = extract_block(
        text,
        "=== US Momentum Top (VCP Early Stage) ===",
        ["=== 주문용 Top4", "==="]
    ) or "(US Momentum Top 없음)"
    # Delete internal title
    momentum_block = "\n".join([l for l in momentum_raw.splitlines() if "US Momentum Top" not in l]).strip()

    order_raw = extract_block(
        text,
        "=== 주문용 Top4 (오늘) ===",
        ["이전 Top4:", "==="]
    ) or "(주문용 Top4 없음)"
    order_top4 = "\n".join([l for l in order_raw.splitlines() if "주문용 Top4" not in l]).strip()

    # 주문용 Top4 / VCP Early stage: Ticker | Price($) | 등락률(%) | Sigsco | 3M | 1M | Early | Final | NewSig
    VCP_HEADERS = ["Ticker", "Price($)", "등락률(%)", "Sigsco", "3M(%)", "1M(%)", "Earlysco", "Finalsco", "NewSig"]
    order_top4_html = text_to_html_table(order_top4, headers=VCP_HEADERS, chg_cols={2})
    momentum_block_html = text_to_html_table(momentum_block, headers=VCP_HEADERS, chg_cols={2})

    atr_block = extract_atr_block(text) or "(ATR 제외 종목 없음)"
    dist_block = extract_distribution_block(text) or "(분포 정보 없음)"
    runtime = extract_runtime(text)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>US Stock Report</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 20px;
  margin: 0;
  background-color: #f4f7f6;
}}
h2 {{
  margin-top: 10px;
  margin-bottom: 5px;
  padding-bottom: 5px;
  color: #2c3e50;
  border-bottom: 2px solid #3498db;
  font-size: 1.1em;
}}
h2.small-title {{
  font-size: 0.95em;
  border-bottom: 1px solid #3498db;
}}
.mark-vcp-table {{
  width: auto;
  min-width: 150px;
  border-collapse: collapse;
  margin-bottom: 10px;
  font-size: 12px;
}}
.mark-vcp-table td {{
  padding: 2px 8px;
  border-bottom: 1px solid #eee;
  font-weight: bold;
  color: #2980b9;
}}
.styled-tableWide {{
  width: auto;
  max-width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 13px;
  background: white;
  box-shadow: 0 2px 5px rgba(0,0,0,0.1);
}}
.styled-tableWide thead tr {{
  background-color: #3498db;
  color: #ffffff;
  text-align: left;
}}
.styled-tableWide th, .styled-tableWide td {{
  padding: 6px 10px;
  border-bottom: 1px solid #eee;
  white-space: nowrap;
}}
.styled-tableWide td.ticker-col {{
  width: 80px;
  font-weight: 500;
}}
@media (max-width: 600px) {{
  .styled-tableWide {{
    font-size: 9px;
  }}
  .styled-tableWide th, .styled-tableWide td {{
    padding: 2px 3px;
  }}
  .styled-tableWide td.ticker-col {{ width: 50px; }}
}}
.meta {{
  color: #555;
  margin-top: 8px;
}}

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
</style>
</head>
<body>

<p style="margin: 0 0 10px 0; color: #000; font-size: 0.9em;">Updated: {now} <small style="color: #ccc; font-size: 10px;">v1.6</small></p>

<h2>🎯 미국 VCP 매수 후보 (돌파/대기 분리)</h2>
{minervini2_html}

<h2>🎯 VCP 돌파 추적 (P:+12%, S:-6%, 21거래일)</h2>
<p style="margin:0 0 8px 0;color:#888;font-size:0.82em;">BREAKOUT_TODAY 출현일 종가=기준가 · 21<b>거래일</b> 추적(백테스트 D21 동일) · 보유일차는 1887 실주문 로그 조인 · 10/20/60 = 종가 이평 이탈여부(V 유지 / X 하향이탈 고착)</p>
{minervini_tracker_html}

<div style="display: flex; flex-direction: column; align-items: flex-start;">
  <h2 class="small-title">🏆 마크-1차통과</h2>
  {mark_vcp_html}
</div>

<h2>🧾 주문용 Top4 (오늘)</h2>
{order_top4_html}

<h2>🏆 VCP Early stage</h2>
<p style="margin:0 0 8px 0;color:#888;font-size:0.82em;">Early_sco 50% + Signal_sco 35% + 3개월 수익률 순위 15%</p>
{momentum_block_html}

<h2>🚫 ATR 필터로 제외된 종목</h2>
{text_to_html_table(atr_block)}

<h2>📈 Signal_sco 기준 종목 분포</h2>
<pre style="font-size: 11px; margin-top: 5px;">{html.escape(dist_block)}</pre>

<p class="meta">{html.escape(runtime)}</p>


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

    <!-- V4 interactive chart popup (일/주봉 · Supertrend 토글) — replaces Naver PNG -->
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

    <!-- Naver Chart Popup script (DISABLED — replaced by V4 embedded popup) -->
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
      var curEl = null;   // 현재 차트가 가리키는 행 (D/S 단축키 이동 기준)

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

      function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('naver-popup-open');
        // iframe 안에서 열릴 때 키보드 포커스를 잡아야 s/d 단축키가 첫 호버부터 동작.
        // 단, 입력창 등에 이미 포커스가 있으면 뺏지 않음(activeElement===body일 때만).
        try {{ if (document.activeElement === document.body || document.activeElement === null) popup.focus({{preventScroll:true}}); }} catch (e) {{}} }}
      function closePopup() {{ popup.style.display = 'none';  pinned = false; document.body.classList.remove('naver-popup-open');
        document.removeEventListener('mousemove', unpinOnMove); }}
      // 키보드(s/d) 이동 시 임시 고정. 그 뒤 마우스가 팝업 밖에서 움직이면 고정 해제 → 자동닫힘 복구
      function unpinOnMove(e) {{ if (popup.contains(e.target)) return;
        document.removeEventListener('mousemove', unpinOnMove); pinned = false;
        setTimeout(function () {{ if (!pinned) closePopup(); }}, 120); }}
      function kbPin() {{ pinned = true; clearTimeout(hoverTimer);
        document.removeEventListener('mousemove', unpinOnMove);
        document.addEventListener('mousemove', unpinOnMove); }}

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
            curEl = el;
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
          curEl = el;
          loadCharts(el.getAttribute('data-ticker') || '');
        }});
      }});

      // 키보드(팝업 열렸을 때만): S/↑=이전, D/↓=다음, Tab/ESC=닫기 (A=슈퍼트렌드는 PNG에 없음)
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
        var tg = e.target, tag = tg && tg.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || (tg && tg.isContentEditable)) return;
        var k = e.key;
        if (k === 'Tab' || k === 'Escape') {{ e.preventDefault(); closePopup(); return; }}
        var dir = 0;
        if (k === 's' || k === 'S' || k === 'ArrowUp') dir = -1;
        else if (k === 'd' || k === 'D' || k === 'ArrowDown') dir = 1;
        if (dir === 0 || !curEl) return;
        e.preventDefault();
        var all = Array.prototype.slice.call(document.querySelectorAll('td[data-ticker]'));
        var i = all.indexOf(curEl);
        if (i < 0) return;
        i += dir;
        if (i < 0 || i >= all.length) return;
        var nt = all[i];
        kbPin();
        curEl = nt;
        loadCharts(nt.getAttribute('data-ticker') || '');
        nt.scrollIntoView({{block:'nearest'}});
      }});
    }})();
    </script>

</body>
</html>
"""

    _us_tickers = sorted({t.upper().replace('*', '') for t in re.findall(r'data-ticker="([^"]+)"', page)})
    _us_tickers = [t for t in _us_tickers if t and t != "TICKER"]
    page = page.replace('__V4_BLOCK__', build_chart_popup(_us_tickers))

    for out_path in OUT_HTML_LIST:
        out_path.write_text(page, encoding="utf-8")
        print(f"[OK] {out_path.name} updated")


if __name__ == "__main__":
    main()
