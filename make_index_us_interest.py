# make_index_us_etf.py (Fixed Structure)
import html
from pathlib import Path
from datetime import datetime
import re
import json

BASE = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(BASE))
from chart_popup_v4 import build_chart_popup   # V4 내장형 일/주봉 인터랙티브 팝업
REPORT_TXT = BASE / "report_us_interest.txt"
OUT_HTML_LIST = [BASE / "us_interest.html"]

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
    block = extract_block(text, "[ATR 트리거", ["[ATR 트레일링", "[실행 시간]", "Signal_sco 기준", "✅ ATR", "================"])
    if not block:
        return ""
    cleaned = [l for l in block.splitlines()
               if not l.strip().startswith("[")
               and "Ticker" not in l
               and "종목 수" not in l and "수:" not in l]
    return "\n".join(cleaned).strip()

def extract_atr_excluded(text):
    block = extract_block(text, "[ATR 트레일링", ["[실행 시간]", "Signal_sco 기준", "ATR 과열", "✅ ATR", "================"])
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

def text_to_html_table_momentum(text, held_list=None, low_signals_dict=None, idx_rel_map=None):
    """📊 US Interest Momentum Top 30 전용 파서 (15개 컬럼, Name 제외)"""
    if low_signals_dict is None:
        low_signals_dict = {}
    
    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p style="color:#888;">{html.escape(text)}</p>'
    
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return '<p style="color:#888;">없음</p>'
    
    # Header line 제거
    data_lines = [l for l in lines if not l.startswith("Ticker")]
    
    out = ['<table class="styled-tableWide">']
    # Header (RSI 추가)
    out.append('<thead><tr><th>Ticker</th><th>등락</th><th>위치</th><th>Sco</th><th>RSI</th><th>정</th><th>신호</th><th>5</th><th>10</th><th>20</th><th>60</th><th>120</th><th>136평</th><th>3M(%)</th><th>Score</th><th>저점</th><th>지수대비</th></tr></thead>')
    out.append('<tbody>')
    
    for line in data_lines:
        # 공백 2개 이상으로 split
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 16:  # 공백이 적으면 일반 split
            cols = line.split()
        
        if len(cols) < 16:  # 그래도 16개 미만이면 스킵
            continue
        
        ticker = cols[0].strip()
        ticker_clean = ticker.replace("*", "").replace("**", "")
        
        # held 여부 확인
        highlight_class = ""
        if held_list and ticker_clean in held_list:
            ticker_idx = held_list.index(ticker_clean)
            highlight_class = "held-bold" if (len(held_list) <= 3 or ticker_idx < 3) else "held-plain"
        
        # 추세 색상 미리 파악 (index 12)
        ticker_style = ""
        trend_val = cols[12].upper() if len(cols) > 12 else ""
        if "LIME" in trend_val:
            ticker_style = 'background-color:#2AF527; color:black; font-weight:bold;'
        elif "GREEN" in trend_val:
            ticker_style = 'background-color:#8DCF8C; color:black; font-weight:bold;'
        elif "RED" in trend_val:
            ticker_style = 'background-color:#e74c3c; color:white; font-weight:bold;'
        elif "PURPLE" in trend_val:
            ticker_style = 'background-color:#9b59b6; color:white; font-weight:bold;'

        # Ticker cell
        ticker_classes = ["ticker-col", "chart-trigger"]
        if highlight_class:
            ticker_classes.append(highlight_class)
        
        row_html = '<tr>'
        # Ticker 배경색 적용
        tk_style_attr = f' style="{ticker_style} cursor:pointer;"' if ticker_style else ' style="cursor:pointer;"'
        row_html += f'<td class="{" ".join(ticker_classes)}" data-ticker="{ticker_clean}" data-name="{ticker_clean}"{tk_style_attr}>{html.escape(ticker)}</td>'
        
        for i, c in enumerate(cols[1:], 1):
            if i == 12 or i == 16: continue # 추세, 지수대비 컬럼 건너뛰기

            cell_class = []
            content = html.escape(c)
            
            if highlight_class:
                cell_class.append(highlight_class)
            
            if i == 1:  # 등락
                try:
                    val = float(re.sub(r'[^\d.+-]', '', c))
                    cell_class.append("sig-up" if val > 0 else ("sig-down" if val < 0 else ""))
                except: pass
            elif i == 2:  # 위치 - 동그라미 스타일 적용
                pos_val = c.strip()
                if pos_val in ("1","2","3","4","5"):
                    content = f'<span class="pos-badge pos-{pos_val}">{content}</span>'
                elif c == "5": cell_class.append("pos-5")
                elif c == "4": cell_class.append("pos-4")
            elif i == 4:  # RSI
                m_rsi = re.match(r'(\d+)\((\d+)\)', c.strip())
                if m_rsi:
                    today_rsi = int(m_rsi.group(1))
                    prev_rsi  = int(m_rsi.group(2))
                    cell_class.append("up" if today_rsi >= 50 else "down")
                    if today_rsi >= 30 and prev_rsi < 30:
                        content = f'<span style="background-color:#d5f5e3; font-weight:bold; display:block; padding:2px 0;">{content}</span>'
            elif i == 5:  # 정배/역배
                if "정배" in c: cell_class.append("sig-jung")
                elif "역배" in c: cell_class.append("sig-yeok")
            elif i == 6:  # 신호 배지
                sig_u = c.upper()
                if c.strip() not in ("-", ""):
                    if "LIME" in sig_u:
                        content = f'<span class="trend-badge trend-lime">{html.escape(c)}</span>'
                    elif "GRN" in sig_u or "GREEN" in sig_u:
                        content = f'<span class="trend-badge trend-green">{html.escape(c)}</span>'
                    elif "RED" in sig_u:
                        content = f'<span class="trend-badge trend-red">{html.escape(c)}</span>'
            elif 7 <= i <= 11:  # 5/10/20/60/120 이평 방향
                if '상' in c: cell_class.append("up")
                elif '하' in c: cell_class.append("down")
            elif i == 13:  # 136평
                try:
                    num_val = float(c.replace('%', ''))
                    cell_class.append("up" if num_val > 0 else ("down" if num_val < 0 else ""))
                except: pass
            elif i == 14:  # 3M(%)
                try:
                    val = float(re.sub(r'[^\d.+-]', '', c))
                    cell_class.append("sig-up" if val > 0 else ("sig-down" if val < 0 else ""))
                except: pass
            
            cls_str = f' class="{" ".join(cell_class)}"' if cell_class else ''
            row_html += f'<td{cls_str}>{content}</td>'
        
        # ✅ 저점 신호 뱃지 추가 (맨 끝 컬럼)
        jeo, jeo2 = low_signals_dict.get(ticker_clean, ('-', '-'))
        low_badge = ""
        if jeo != '-' and jeo2 != '-':
            low_badge = '<span class="low-badge low-both">저1,2</span>'
        elif jeo != '-':
            low_badge = '<span class="low-badge low-jeo">저</span>'
        elif jeo2 != '-':
            low_badge = '<span class="low-badge low-jeo2">저2</span>'
        row_html += f'<td>{low_badge}</td>'
        
        # ✅ 지수대비(%) 칌럼 추가
        if idx_rel_map is None:
            idx_rel_map = {}
        idx_rel_val = (idx_rel_map or {}).get(ticker_clean)
        if idx_rel_val is not None:
            try:
                irv = float(idx_rel_val)
                ir_cls = 'sig-up' if irv > 0 else ('sig-down' if irv < 0 else '')
                ir_disp = f'{irv:+.1f}%'
            except:
                ir_cls = ''
                ir_disp = '-'
        else:
            ir_cls = ''
            ir_disp = '-'
        row_html += f'<td class="{ir_cls}">{ir_disp}</td>'
        
        row_html += '</tr>'
        out.append(row_html)
    
    out.append('</tbody></table>')
    return '\n'.join(out)

def text_to_html_table_top4(text, ticker_meta=None, idx_rel_map=None):
    """주문용 Top4 전용 렌더러 (pandas 5컬럼 포맷)"""
    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p style="color:#888;">{html.escape(text)}</p>'
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return '<p style="color:#888;">없음</p>'
    out = ['<table class="styled-table">']
    out.append('<thead><tr><th>Ticker</th><th>등락(%)</th><th>위치</th><th>Sco</th><th>RSI</th><th>3M(%)</th><th>Score</th><th>신호</th><th>투자비중</th><th>지수대비</th></tr></thead>')
    out.append('<tbody>')
    
    for line in lines:
        if line.startswith("Ticker"):  # header skip
            continue

        # 실제 Top4 포맷: " Ticker 등락 Sco 3M% Score 신호 투자금액" (수정됨)
        # toks: 0:Ticker, 1:등락, 2:Sco, 3:3M%, 4:Score, 5:신호, 6:투자금액
        toks = line.split()
        if len(toks) < 5:
            continue
        ticker = toks[0]
        chg    = toks[1]
        sco    = toks[2]
        rtn    = toks[3]
        score  = toks[4]
        invest_amt = toks[-1] if len(toks) > 5 else "-"
        newsig = " ".join(toks[5:-1]) if len(toks) > 6 else (toks[5] if len(toks) > 5 else "-")
        
        invest_amt_str = invest_amt
        try:
            val = float(invest_amt.replace(',', ''))
            pct = (val / 10000) * 100
            invest_amt_str = f"{pct:.1f}%"
        except:
            pass

        ticker_clean = ticker.replace("*", "").replace("**", "")

        # Metadata lookup (Position & Trend) - momentum 테이블에서 가져옴
        meta = (ticker_meta or {}).get(ticker_clean, {})
        ticker_style = meta.get('style', '')

        # 위치 badge: momentum 테이블 meta에서 pos 조회
        pos_val = meta.get('pos', '')
        pos_html = (f'<span class="pos-badge pos-{pos_val}">{html.escape(pos_val)}</span>'
                    if pos_val in ("1","2","3","4","5") else html.escape(pos_val or "-"))
        
        # RSI 파싱 및 스타일링
        rsi_val = meta.get('rsi', '-')
        rsi_html = html.escape(rsi_val)
        rsi_class = ""
        m_rsi = re.match(r'(\d+)\((\d+)\)', rsi_val)
        if m_rsi:
            today_rsi = int(m_rsi.group(1))
            prev_rsi  = int(m_rsi.group(2))
            rsi_class = "sig-up" if today_rsi >= 50 else "sig-down"
            if today_rsi >= 30 and prev_rsi < 30:
                rsi_html = f'<span style="background-color:#d5f5e3; font-weight:bold; display:block; padding:2px 0;">{rsi_html}</span>'

        chg_class = ""
        try:
            chg_val = float(re.sub(r'[^\d.+-]', '', chg))
            chg_class = "sig-up" if chg_val > 0 else ("sig-down" if chg_val < 0 else "")
        except:
            pass

        rtn_class = ""
        try:
            rtn_val = float(re.sub(r'[^\d.+-]', '', rtn))
            rtn_class = "sig-up" if rtn_val > 0 else ("sig-down" if rtn_val < 0 else "")
        except:
            pass

        sig_html = html.escape(newsig)
        if newsig.strip() not in ("-", ""):
            sig_u = newsig.upper()
            if "LIME" in sig_u:
                sig_html = f'<span class="trend-badge trend-lime">{html.escape(newsig)}</span>'
            elif "GRN" in sig_u or "GREEN" in sig_u:
                sig_html = f'<span class="trend-badge trend-green">{html.escape(newsig)}</span>'
            elif "RED" in sig_u:
                sig_html = f'<span class="trend-badge trend-red">{html.escape(newsig)}</span>'
            elif "PPL" in sig_u or "PURPLE" in sig_u:
                sig_html = f'<span class="trend-badge trend-purple">{html.escape(newsig)}</span>'

        tk_style_attr = f' style="{ticker_style} cursor:pointer;"' if ticker_style else ' style="cursor:pointer;"'

        # 지수대비(%) 칌럼
        if idx_rel_map is None:
            idx_rel_map = {}
        idx_rel_val = (idx_rel_map or {}).get(ticker_clean)
        if idx_rel_val is not None:
            try:
                irv = float(idx_rel_val)
                ir_cls = 'sig-up' if irv > 0 else ('sig-down' if irv < 0 else '')
                ir_disp = f'{irv:+.1f}%'
            except:
                ir_cls = ''
                ir_disp = '-'
        else:
            ir_cls = ''
            ir_disp = '-'

        out.append(
            f'<tr>'
            f'<td class="ticker-col chart-trigger" data-ticker="{ticker_clean}" data-name="{ticker_clean}"{tk_style_attr}>{html.escape(ticker)}</td>'
            f'<td class="{chg_class}">{html.escape(chg)}</td>'
            f'<td>{pos_html}</td>'
            f'<td>{html.escape(sco)}</td>'
            f'<td class="{rsi_class}">{rsi_html}</td>'
            f'<td class="{rtn_class}">{html.escape(rtn)}</td>'
            f'<td>{html.escape(score)}</td>'
            f'<td>{sig_html}</td>'
            f'<td>{html.escape(invest_amt_str)}</td>'
            f'<td class="{ir_cls}">{ir_disp}</td>'
            f'</tr>'
        )
    out.append('</tbody></table>')
    return '\n'.join(out)


def text_to_html_table_atr(text, header_cols):
    """ATR 트리거/제외 전용 소형 테이블 렌더러"""
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


def main():
    text = REPORT_TXT.read_text(encoding="utf-8", errors="replace") if REPORT_TXT.exists() else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    momentum_raw = extract_block(text, "=== US Interest Momentum Top ===", ["=== 최종 리스트", "이전 보유 종목", "==="]) or "(US Interest Momentum Top 없음)"
    momentum_block = "\n".join([l for l in momentum_raw.splitlines() if "US Interest Momentum" not in l]).strip()

    order_raw = extract_block(text, "=== 최종 리스트", ["[나스닥 단계적 비중]", "[Holdings 투자비중 배분]", "[ATR 트리거"]) or "(주문용 Top4 없음)"
    order_top4 = "\n".join([l for l in order_raw.splitlines() if "최종 리스트" not in l]).strip()

    held_list = []
    held_match = re.search(r"최종 보유 종목.*?:\s*\[(.*?)\]", text)
    if held_match:
        held_list = [t.strip().strip("'").strip('"') for t in held_match.group(1).split(',')]

    atr_triggered = extract_atr_triggered(text) or "(ATR 트리거 종목 없음)"
    atr_excluded  = extract_atr_excluded(text)  or "(ATR 제외 종목 없음)"
    dist_block = extract_distribution_block(text) or "(분포 정보 없음)"
    runtime = extract_runtime(text)

    # ✅ 저점 신호 JSON 읽기
    low_signals_dict = {}
    idx_rel_map = {}  # 지수대비(%) 데이터
    low_signal_file = BASE / "us_interest_low_signals.json"
    if low_signal_file.exists():
        try:
            low_data = json.loads(low_signal_file.read_text(encoding="utf-8"))
            for sig in low_data.get('signals', []):
                ticker = sig.get('ticker', '')
                jeo = sig.get('jeo', '-')
                jeo2 = sig.get('jeo2', '-')
                low_signals_dict[ticker] = (jeo, jeo2)
                if sig.get('idx_rel') is not None:
                    idx_rel_map[ticker] = sig['idx_rel']
        except:
            pass

    # Ticker metadata extraction for Top4 styling
    ticker_meta = {}
    momentum_lines = momentum_block.splitlines()
    for mline in momentum_lines:
        mcols = re.split(r'\s{2,}', mline.strip())
        if len(mcols) < 15: mcols = mline.strip().split()
        if len(mcols) < 15: continue
        
        mtk = mcols[0].strip().replace("*", "").replace("**", "")
        mpos = mcols[2].strip()
        mrsi = mcols[4].strip() if len(mcols) > 4 else "-"
        mtrend = mcols[12].upper() if len(mcols) > 12 else ""
        
        mstyle = ""
        if "LIME" in mtrend:
            mstyle = 'background-color:#2AF527; color:black; font-weight:bold;'
        elif "GREEN" in mtrend:
            mstyle = 'background-color:#8DCF8C; color:black; font-weight:bold;'
        elif "RED" in mtrend:
            mstyle = 'background-color:#e74c3c; color:white; font-weight:bold;'
        elif "PURPLE" in mtrend:
            mstyle = 'background-color:#9b59b6; color:white; font-weight:bold;'
        
        ticker_meta[mtk] = {'pos': mpos, 'rsi': mrsi, 'style': mstyle}

    # Calculate top4_total_pct for display in title
    top4_total_pct = 0.0
    for l in order_top4.strip().splitlines():
        if l.strip() and not l.startswith("Ticker"):
            toks = l.split()
            if len(toks) >= 5:
                try:
                    val = float(toks[-1].replace(',', ''))
                    top4_total_pct += (val / 10000) * 100
                except:
                    pass
    title_str = f"🎯 주문 목록 ({top4_total_pct:.1f}%)" if top4_total_pct > 0 else "🎯 주문 목록"

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>US Interest Report</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 20px;
  margin: 0;
  background-color: #f4f7f6;
}}
/* PC 전용 상단 탭 */
.top-nav {{
  display: flex;
  background-color: #2c3e50;
  position: sticky;
  top: 0;
  z-index: 9999;
  box-shadow: 0 2px 5px rgba(0,0,0,0.2);
  width: fit-content;
  margin: 0 0 12px 0;
  border-radius: 0 0 8px 0;
}}
.nav-item {{
  padding: 10px 25px;
  color: #bdc3c7;
  text-align: center;
  cursor: pointer;
  font-weight: bold;
  font-size: 1rem;
  border-bottom: 3px solid transparent;
  user-select: none;
}}
.nav-item.active {{
  color: #fff;
  background-color: #34495e;
  border-bottom-color: #3498db;
}}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}
#chart-frame {{
  width: 100%;
  height: calc(100vh - 60px);
  border: none;
  display: block;
}}
h1 {{
  margin: 0;
  font-size: 1.5em;
  color: #2c3e50;
}}
h2 {{
  margin-top: 30px;
  padding-bottom: 10px;
  color: #2c3e50;
  border-bottom: 2px solid #3498db;
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
  background: linear-gradient(135deg, #3498db, #2980b9);
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
.held-bold {{
  font-weight: 700;
}}
.held-plain {{
}}
.sig-up {{ color: #27ae60; font-weight: 600; }}
.sig-down {{ color: #e74c3c; font-weight: 600; }}
.sig-jung {{ background: #fffbea; color: #d68910; font-weight: 600; }}
.sig-yeok {{ background: #e8f4fd; color: #1e6fa8; font-weight: 600; }}
.up {{ color: #27ae60; font-weight: 600; }}
.down {{ color: #e74c3c; font-weight: 600; }}
.pos-5 {{ background: #ffe6e6; font-weight: 700; }}
.pos-4 {{ background: #fff4e6; font-weight: 600; }}

.pos-badge {{
  display: inline-block;
  width: 22px;
  height: 22px;
  line-height: 22px;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: bold;
  color: white;
  text-align: center;
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
  font-size: 0.85em;
  font-weight: 700;
}}
.trend-lime {{ background: #2AF527; color: black; }}
.trend-green {{ background: #8DCF8C; color: black; }}
.trend-red {{ background: #e74c3c; color: white; }}
.trend-purple {{ background: #9b59b6; color: white; }}
.ticker-col {{ cursor: pointer; text-decoration: underline dotted; }}
.ticker-col:hover {{ background: #e8f4f8; }}
.name-col {{ font-size: 11px; color: #555; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }}
.chart-trigger {{ cursor: pointer; }}
.chart-trigger:hover {{ background-color: #e8f4f8 !important; }}

/* ── TRADINGVIEW BACKUP (commented out for Naver migration; restore by removing surrounding comment markers) ──
#chart-popup {{
  position: fixed;
  background: white;
  border: 2px solid #2c3e50;
  border-radius: 8px;
  box-shadow: 0 8px 16px rgba(0,0,0,0.3);
  z-index: 99999;
  display: none;
  overflow: hidden;
}}
#chart-popup.visible {{ display: flex; flex-direction: column; }}
#chart-popup.landscape-mode {{
  position: fixed !important;
  top: 0 !important;
  left: 0 !important;
  width: 100vw !important;
  height: 100dvh !important;
  border-radius: 0 !important;
  border: none !important;
}}
.chart-ph {{
  background: #34495e;
  color: white;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}}
#btn-close-popup {{
  background: #e74c3c;
  color: white;
  border: none;
  padding: 4px 12px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 18px;
  font-weight: bold;
}}
#btn-close-popup:hover {{ background: #c0392b; }}
.chart-tb-group {{ display: flex; gap: 4px; }}
.chart-tb {{
  background: #7f8c8d;
  color: white;
  border: none;
  padding: 4px 10px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
}}
.chart-tb.on {{ background: #27ae60; font-weight: bold; }}
#tv-container {{ flex: 1; min-height: 0; }}
body.chart-open {{ overflow: hidden; }}
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

.small-board {{
  flex: 1;
  min-width: 280px;
  background: white;
  padding: 16px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}}
.small-board h3 {{
  margin: 0 0 10px 0;
  font-size: 1em;
  color: #2c3e50;
}}
.meta {{
  color: #888;
  font-size: 0.9em;
  margin-top: 20px;
}}

/* ✅ 저점 신호 뱃지 스타일 */
.low-badge {{
    display: inline-block;
    padding: 3px 8px;
    border-radius: 12px;
    font-size: 10px;
    font-weight: bold;
    color: white;
    text-align: center;
    min-width: 35px;
}}
.low-jeo {{ background-color: #2ecc71; }}      /* 초록 - 저 */
.low-jeo2 {{ background-color: #3498db; }}     /* 파란 - 저2 */
.low-both {{ background-color: #e74c3c; }}     /* 빨강 - 저1,2 */

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
<div id="top-nav-wrap"></div>

<div id="tab-report" class="tab-panel active">
<h1>📊 US Interest Momentum Report</h1>
<p class="meta">Updated: {now}</p>

<h2>{title_str}</h2>
{text_to_html_table_top4(order_top4, ticker_meta, idx_rel_map)}

<h2>📊 US Interest Momentum Top 30</h2>
{text_to_html_table_momentum(momentum_block, held_list, low_signals_dict, idx_rel_map)}

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

</div><!-- /#tab-report -->

<!-- 탭2: 시황 차트 (PC 전용, 클릭 시에만 로딩) -->
<div id="tab-chart" class="tab-panel">
  <iframe id="chart-frame" src="" allowfullscreen></iframe>
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
                // Notify parent iframe (dashboard.html / index.html) to hide sidebar
                if (window.parent && window.parent !== window) {{
                    window.parent.postMessage({{action: 'openChart'}}, '*');
                }}
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
            var wasLandscape = popup.classList.contains('landscape-mode');
            popup.classList.remove('visible');
            popup.classList.remove('landscape-mode');
            document.body.classList.remove('chart-open');
            tvCont.innerHTML = '';
            currentTicker = '';
            // 가로모드로 열었을 때만 부모에게 복구 신호 전송
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

    <!-- Naver Chart Popup (active) -->
    __V4_BLOCK__

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
// 상단 탭 초기화
(function() {{
  // 탭 메뉴 DOM 삽입
  var nav = document.createElement('div');
  nav.className = 'top-nav';
  nav.style.cssText = 'border-radius:0; margin-bottom:12px;';
  nav.innerHTML =
    `<div id="nav-etf" class="nav-item" onclick="location.href='us_etf.html'">미ETF</div>` +
    `<div id="nav-interest" class="nav-item active" onclick="switchTab('report')">미관심주</div>` +
    `<div id="nav-chart" class="nav-item" onclick="switchTab('chart')">차트</div>`;
  document.getElementById('top-nav-wrap').appendChild(nav);

  var chartLoaded = false;

  function switchTab(tab) {{
    // 모든 탭 패널 숨기기
    document.querySelectorAll('.tab-panel').forEach(function(p) {{ p.classList.remove('active'); }});
    // 모든 탭 메뉴 비활성화
    document.querySelectorAll('.nav-item').forEach(function(n) {{ n.classList.remove('active'); }});

    if (tab === 'report') {{
      document.getElementById('tab-report').classList.add('active');
      document.getElementById('nav-interest').classList.add('active');
    }} else if (tab === 'chart') {{
      document.getElementById('tab-chart').classList.add('active');
      document.getElementById('nav-chart').classList.add('active');
      // 지연 로딩: 차트 탭 클릭 시 최초 1회만 iframe src 설정
      if (!chartLoaded) {{
        document.getElementById('chart-frame').src = 'us_chart.html';
        chartLoaded = true;
      }}
    }}
  }}

  window.switchTab = switchTab;
}})();
</script>

</body>
</html>
"""
    _us_tickers = sorted({t.upper().replace('*', '') for t in re.findall(r'data-ticker="([^"]+)"', page)})
    page = page.replace('__V4_BLOCK__', build_chart_popup(_us_tickers))
    for out_path in OUT_HTML_LIST:
        out_path.write_text(page, encoding="utf-8")
        print(f"[OK] {out_path.name} updated")

if __name__ == "__main__":
    main()
