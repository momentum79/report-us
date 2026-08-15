# make_index_us_etf.py (Fixed Structure)
import html
from pathlib import Path
from datetime import datetime, date
import re
import json
import csv
import io

# ── 현재가 조회 ────────────────────────────────────────────
BUDGET  = 1_000_000   # 백만원 (종목당 투자금액)
# 환율은 fx_rate.json(= bat 앞단 `fx_rate.py --save` 산출물) 에서 읽는다. API 무호출.
#   캐시가 없거나 24시간 넘게 묵으면 1450 폴백 + 경고.
from fx_rate import get_usdkrw   # noqa: E402
USD_KRW = get_usdkrw(1450)

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

BASE = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(BASE))
from chart_popup_v4 import build_chart_popup   # V4 내장형 일/주봉 인터랙티브 팝업
REPORT_TXT = BASE / "report_us_etf.txt"
OUT_HTML_LIST = [BASE / "us_etf.html"]
# 저점 5일 추적 이력
LOW_HISTORY_FILE = BASE / "us_etf_low_history.json"

# ── Top3 CSV 경로 ──────────────────────────────────────────
WEEKLY_TOP3_CSV  = BASE / "etf_history" / "weekly_top3_usonly.csv"
MONTHLY_TOP3_CSV = BASE / "etf_history" / "monthly_top3_usonly.csv"


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


def update_low_history(low_signals_dict: dict) -> dict:
    """
    저점 신호 이력 업데이트 및 저장
    - 7일 초과 항목 자동 삭제
    - 새 신호 감지 시 리셋 (first_date 갱신)
    - 같은 신호 패턴 지속 시 날짜 유지 (카운팅 계속)
    low_signals_dict: {ticker: (jeo, jeo2)}
    Returns: 업데이트된 history dict
    """
    today     = date.today()
    today_str = today.isoformat()
    history   = load_low_history()

    # 1. 7일 초과 항목 삭제
    to_delete = []
    for ticker, rec in history.items():
        try:
            first_date   = date.fromisoformat(rec["first_date"])
            days_elapsed = (today - first_date).days
            if days_elapsed > 7:
                to_delete.append(ticker)
        except Exception:
            to_delete.append(ticker)
    for ticker in to_delete:
        del history[ticker]

    # 2. 현재 신호로 이력 업데이트
    for ticker, (jeo, jeo2) in low_signals_dict.items():
        new_jeo  = (jeo  != "-" and str(jeo).strip()  not in ("", "-", "0", "nan"))
        new_jeo2 = (jeo2 != "-" and str(jeo2).strip() not in ("", "-", "0", "nan"))
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
        first_date   = date.fromisoformat(rec["first_date"])
        days_elapsed = (date.today() - first_date).days
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
    return f'<div style="margin:0 0 10px;max-width:520px;">{t}{head}{bars}</div>'


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

def text_to_html_table_momentum(text, held_list=None, low_signals_dict=None, idx_rel_map=None, low_history=None):
    """📊 US ETF Momentum Top 30 전용 파서 (15개 컬럼, Name 제외)"""
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
        
        # ✅ 저점 신호 뱃지 추가 (이력 기반 5일 추적)
        if low_history is not None:
            low_badge = get_low_badge(ticker_clean, low_history)
        else:
            # fallback: low_history 없으면 기존 방식
            jeo, jeo2 = (low_signals_dict or {}).get(ticker_clean, ('-', '-'))
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


# ══════════════════════════════════════════════════════════
# ── 🆕 당일/주간/월간 Top3 카드 섹션 (US ETF) ─────────────
# ══════════════════════════════════════════════════════════

MEDALS_US = ["🥇", "🥈", "🥉"]


def _parse_top3_entry_us(entry: str) -> list:
    """멀티라인 셀 → 최대 3개 항목 리스트"""
    lines = [l.strip() for l in entry.strip().splitlines() if l.strip()]
    return lines[:3]


def get_weekly_top3_us():
    """주간 CSV 최신 차수 top3 반환 → (label, ['TICKER', ...])"""
    if not WEEKLY_TOP3_CSV.exists():
        return ("", [])
    try:
        text = WEEKLY_TOP3_CSV.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 2:
            return ("", [])
        header_cells = [c.strip() for c in rows[0] if c.strip()]
        data_cells   = [c.strip() for c in rows[1]]
        valid_pairs  = [(header_cells[i], data_cells[i])
                        for i in range(min(len(header_cells), len(data_cells)))
                        if data_cells[i].strip()]
        if not valid_pairs:
            return ("", [])
        label_raw, entry = valid_pairs[-1]
        label = re.sub(r'^\d{4}\.', '', label_raw)
        return (label, _parse_top3_entry_us(entry))
    except Exception as e:
        print(f"[US 주간 Top3 파싱 오류] {e}")
        return ("", [])


def get_monthly_top3_us():
    """월간 CSV 현재 연월 top3 반환 → (label, ['TICKER', ...])"""
    if not MONTHLY_TOP3_CSV.exists():
        return ("", [])
    try:
        import datetime as _dt
        today = _dt.date.today()
        target_key = f"{today.year}.{today.month:02d}"
        text = MONTHLY_TOP3_CSV.read_text(encoding="utf-8-sig")
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
                        return (label, _parse_top3_entry_us(entry))
            i += 2
        return ("", [])
    except Exception as e:
        print(f"[US 월간 Top3 파싱 오류] {e}")
        return ("", [])


def get_daily_top3_us(order_text: str) -> list:
    """주문 목록 텍스트 상위 3티커 파싱 → ['TICKER', ...]"""
    result = []
    for line in order_text.splitlines():
        line = line.strip()
        if not line or line.startswith("Ticker") or all(c in "-=" for c in line):
            continue
        toks = line.split()
        if not toks:
            continue
        tk = toks[0].replace("*", "").replace("**", "").strip()
        if tk:
            result.append(tk)
        if len(result) >= 3:
            break
    return result


def _top3_mini_card_us(title: str, label: str, items: list, border_color: str, bg_color: str = "#ffffff") -> str:
    """US ETF 컴팩트 Top3 카드 (티커만, 링크 없음)"""
    if not items:
        body = '<div class="t3-empty">데이터 없음</div>'
    else:
        body = ""
        for i, item in enumerate(items[:3]):
            medal = MEDALS_US[i] if i < 3 else f"#{i+1}"
            ticker = item.strip()
            body += f"""
      <div class="t3-row">
        <span class="t3-medal">{medal}</span>
        <span class="t3-name-us">{html.escape(ticker)}</span>
      </div>"""
    label_html = f'<span class="t3-label">{html.escape(label)}</span>' if label else ""
    return f"""
<div class="t3-card" style="border-top:3px solid {border_color}; background:{bg_color};">
  <div class="t3-header" style="background:{bg_color};">
    <span class="t3-title">{title}</span>
    {label_html}
  </div>
  <div class="t3-body">{body}
  </div>
</div>"""


def build_top3_section_us(order_text: str) -> str:
    """🧾 당일/주간/월간 Top3 카드 섹션 HTML"""
    import datetime as _dt
    today = _dt.date.today()
    daily_label  = f"{today.month}/{today.day}"
    daily_items  = get_daily_top3_us(order_text)
    weekly_label, weekly_items   = get_weekly_top3_us()
    monthly_label, monthly_items = get_monthly_top3_us()

    daily_card   = _top3_mini_card_us("📅 당일",  daily_label,   daily_items,   "#3498db", "#e8f5e9")
    weekly_card  = _top3_mini_card_us("📆 주간",  weekly_label,  weekly_items,  "#27ae60", "#dfffff")
    monthly_card = _top3_mini_card_us("📊 월간",  monthly_label, monthly_items, "#e67e22", "#ffffdf")

    return f"""
<div class="t3-section">
  <div class="t3-section-title">🧾 당일/주간/월간 Top3</div>
  <div class="t3-cards-row">
    {daily_card}
    {weekly_card}
    {monthly_card}
  </div>
</div>"""

# ══════════════════════════════════════════════════════════

def text_to_html_table_top4(text, ticker_meta=None, idx_rel_map=None):
    """주문용 Top4 전용 렌더러 (pandas 5컬럼 포맷)"""
    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p style="color:#888;">{html.escape(text)}</p>'
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return '<p style="color:#888;">없음</p>'

    # ── 현재가 미리 조회 (최대 6개, yfinance) ──────────────
    all_tickers = []
    for line in lines:
        if line.startswith("Ticker"):
            continue
        toks = line.split()
        if toks:
            all_tickers.append(toks[0].replace("*", "").replace("**", ""))
    price_map = {}
    for tk in all_tickers:
        price_map[tk] = _get_us_price(tk)

    out = ['<table class="styled-table">']
    out.append('<thead><tr><th>Ticker</th><th>등락(%)</th><th>위치</th><th>Sco</th><th>RSI</th><th>3M(%)</th><th>Score</th><th>신호</th><th>투자비중</th><th>지수대비</th><th>수량</th><th class="pc-only">총액</th><th class="pc-only">총액</th></tr></thead>')
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
        invest_pct_for_qty = None
        try:
            val = float(invest_amt.replace(',', ''))
            pct = (val / 10000) * 100
            invest_amt_str = f"{pct:.1f}%"
            invest_pct_for_qty = pct
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

        # 수량 셀: $10,000 × 투자비중% / 현재가(USD)
        price = price_map.get(ticker_clean)
        if price and price > 0 and invest_pct_for_qty is not None:
            qty = int(10000 * invest_pct_for_qty / 100 / price)
            qty_disp = f'{qty:,}주'
            qty_usd_disp = f'${int(qty * price):,}' if qty > 0 else '-'
            qty_krw_disp = f'{int(qty * price * USD_KRW / 10000):,}만원' if qty > 0 else '-'
        else:
            qty_disp = '-'
            qty_usd_disp = '-'
            qty_krw_disp = '-'

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
            f'<td style="font-weight:bold;">{qty_disp}</td>'
            f'<td class="pc-only" style="color:#555;">{qty_usd_disp}</td>'
            f'<td class="pc-only" style="color:#555;">{qty_krw_disp}</td>'
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

    momentum_raw = extract_block(text, "=== US ETF Momentum Top ===", ["=== 최종 리스트", "이전 보유 종목", "==="]) or "(US ETF Momentum Top 없음)"
    momentum_block = "\n".join([l for l in momentum_raw.splitlines() if "US ETF Momentum" not in l]).strip()

    order_raw = extract_block(text, "=== 최종 리스트", ["[나스닥 단계적 비중]", "[Holdings 투자비중 배분]", "[ATR 트리거"]) or "(주문용 Top4 없음)"
    order_top4 = "\n".join([l for l in order_raw.splitlines() if "최종 리스트" not in l]).strip()

    held_list = []
    held_match = re.search(r"최종 보유 종목.*?:\s*\[(.*?)\]", text)
    if held_match:
        held_list = [t.strip().strip("'").strip('"') for t in held_match.group(1).split(',')]

    atr_triggered = extract_atr_triggered(text) or "(ATR 트리거 종목 없음)"
    atr_excluded  = extract_atr_excluded(text)  or "(ATR 제외 종목 없음)"
    dist_block = extract_distribution_block(text) or "(분포 정보 없음)"
    # 📊 SCO 분포 막대 (coin게시판 스타일) — sco≥12 / 0~12 / <0
    _dm_total = re.search(r'전체[^:]*:\s*([\d,]+)\s*개', dist_block)
    _dm_rows  = re.findall(r':\s*([\d,]+)\s*개\s*\(([\d.]+%)\)', dist_block)
    if _dm_rows:
        _dm_labels = ["sco ≥ 12", "0 ~ 12", "sco < 0"]
        _dm_colors = ["#2ecc71", "#95a5a6", "#e74c3c"]
        sco_dist_html_us = _sco_dist_bars(
            [(_dm_labels[i], c, p, _dm_colors[i]) for i, (c, p) in enumerate(_dm_rows[:3])],
            total=(_dm_total.group(1) if _dm_total else None),
        )
    else:
        sco_dist_html_us = (
            f'<pre style="font-size: 12px; background: white; padding: 10px; '
            f'border-radius: 4px;">{html.escape(dist_block)}</pre>'
        )
    runtime = extract_runtime(text)

    # ✅ 저점 신호 JSON 읽기
    low_signals_dict = {}
    idx_rel_map = {}  # 지수대비(%) 데이터
    low_signal_file = BASE / "us_etf_low_signals.json"
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

    # Top 30 ticker 목록 추출 (momentum 텍스트 기준)
    top30_tickers = set()
    for mline in momentum_block.splitlines():
        mline = mline.strip()
        if not mline or mline.startswith('Ticker'):
            continue
        mcols = re.split(r'\s{2,}', mline)
        if len(mcols) < 5:
            mcols = mline.split()
        if mcols:
            tk = mcols[0].replace('*', '').replace('**', '').strip()
            if tk:
                top30_tickers.add(tk)

    # ✅ 저점 이력: Top 30에 실제 표시되는 종목만 추적
    low_signals_top30 = {t: v for t, v in low_signals_dict.items() if t in top30_tickers}
    low_history = update_low_history(low_signals_top30)

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
    _pct_part = f" ({top4_total_pct:.1f}%)" if top4_total_pct > 0 else ""
    title_str = f'🎯 주문 목록{_pct_part} <span style="font-size:0.7em; color:#000; font-weight:normal;">- $10,000불 기준</span>'

    # ── 🆕 Top3 카드 섹션 생성
    top3_section_html = build_top3_section_us(order_top4)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>US ETF Report</title>
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
.low-jeo   {{ background-color: #2ecc71; }}    /* 초록 - 저 (Day 0) */
.low-jeo2  {{ background-color: #3498db; }}    /* 파랑 - 저2 (Day 0) */
.low-both  {{ background-color: #e74c3c; }}    /* 빨강 - 저1,2 (Day 0) */
.low-track {{ background-color: #95a5a6; }}    /* 회색 - 1저~5저 (Day 1~5) */

@media (max-width: 480px) {{
  h1 {{ font-size: 1.0em !important; }}
  h2 {{ font-size: 0.95em !important; margin-top: 18px !important; padding-bottom: 6px !important; }}
}}
@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}

/* ══ Top3 카드 섹션 ═══════════════════════════════════════ */
.t3-section {{ margin: 0 0 14px 0; }}
.t3-section-title {{
  font-size: 0.92em; font-weight: bold; color: #2c3e50;
  border-bottom: 2px solid #8e44ad;
  padding-bottom: 4px; margin-bottom: 8px;
}}
.t3-cards-row {{
  display: flex; gap: 8px;
  flex-wrap: nowrap; align-items: flex-start;
}}
.t3-card {{
  background: white; border-radius: 7px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.09);
  min-width: 110px; max-width: 160px;
  flex: 0 0 auto; overflow: hidden;
}}
.t3-header {{
  display: flex; align-items: center;
  justify-content: space-between;
  padding: 5px 9px 4px 9px;
  border-bottom: 1px solid #eee; gap: 4px;
}}
.t3-title {{ font-size: 0.8em; font-weight: bold; color: #2c3e50; white-space: nowrap; }}
.t3-label {{
  font-size: 0.72em; color: #888; white-space: nowrap;
  background: #f0f0f0; border-radius: 3px; padding: 1px 5px;
}}
.t3-body {{ padding: 5px 9px 6px 9px; }}
.t3-row {{
  display: flex; align-items: center; gap: 5px;
  padding: 3px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.82em;
}}
.t3-row:last-child {{ border-bottom: none; }}
.t3-medal {{ font-size: 0.9em; flex-shrink: 0; }}
.t3-name-us {{
  flex: 1; color: #2c3e50; font-weight: 700;
  white-space: nowrap; font-size: 0.95em; letter-spacing: 0.02em;
}}
.t3-empty {{ font-size: 0.78em; color: #aaa; padding: 6px 0; }}
@media (max-width: 600px) {{
  .t3-cards-row {{ overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 4px; }}
  .t3-card {{ min-width: 100px; max-width: 140px; }}
  .pc-only {{ display: none !important; }}
}}
/* ══ End Top3 카드 ════════════════════════════════════════ */
</style>
</head>
<body>
<div id="top-nav-wrap"></div>

<div id="tab-report" class="tab-panel active">
<h1>📊 US ETF Momentum Report</h1>
<p class="meta">Updated: {now}</p>

<h2>📈 Signal_sco 기준 종목 분포</h2>
{sco_dist_html_us}

{top3_section_html}

<h2>{title_str}</h2>
{text_to_html_table_top4(order_top4, ticker_meta, idx_rel_map)}

<h2>📊 US ETF Momentum Top 30</h2>
{text_to_html_table_momentum(momentum_block, held_list, low_signals_dict, idx_rel_map, low_history)}

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

<p class="meta">{html.escape(runtime)}</p>

</div><!-- /#tab-report -->

<!-- 탭2: 시황 차트 (PC 전용, 클릭 시에만 로딩) -->
<div id="tab-chart" class="tab-panel">
  <iframe id="chart-frame" src="" allowfullscreen></iframe>
</div>

    <!-- TRADINGVIEW BACKUP (commented out for Naver migration; restore by removing this comment wrapper)
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

    <!-- Naver Chart Popup script (active) -->
    <script>
    (function () {{
      return;   // V4 팝업으로 대체됨 (아래 네이버 PNG 로직 비활성)
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
      var popup     = document.getElementById('naverChartPopup');
      var titleEl   = document.getElementById('naverPopupTitle');
      var linkEl    = document.getElementById('naverPopupLink');
      var imgDaily  = document.getElementById('naverImgDaily');
      var imgWeekly = document.getElementById('naverImgWeekly');
      var loadDaily = document.getElementById('naverLoadingDaily');
      var loadWeekly= document.getElementById('naverLoadingWeekly');
      var hoverTimer = null;
      var pinned = false;

      function withTs(u) {{ return u + '?t=' + Math.floor(Date.now() / 60000); }}  // 60s bucket (matches Naver max-age=60): probe→display & re-hover hit browser cache
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
          loadInto(imgDaily,  loadDaily,  dailyUrl(code), function () {{ forgetCode(T); }});  // bad/changed code -> re-probe next hover
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
    `<div id="nav-etf" class="nav-item active" onclick="switchTab('report')">미ETF</div>` +
    `<div id="nav-interest" class="nav-item" onclick="location.href='us_interest.html'">미관심주</div>` +
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
      document.getElementById('nav-etf').classList.add('active');
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
