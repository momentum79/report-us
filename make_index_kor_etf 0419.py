# make_index_kor_etf.py
import html
import pathlib
import datetime
import re
import json

# ── 현재가 조회 ────────────────────────────────────────────
BUDGET  = 1_000_000   # 백만원 (종목당 투자금액)

def _get_kor_price(ticker: str) -> float | None:
    """pykrx로 한국 ETF 현재가(당일/전일 종가) 조회"""
    try:
        from pykrx import stock as krx
        today = datetime.date.today().strftime("%Y%m%d")
        df = krx.get_market_ohlcv_by_date(today, today, ticker)
        if df.empty:
            # 당일 데이터 없으면 최근 3거래일 fallback
            past = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%Y%m%d")
            df = krx.get_market_ohlcv_by_date(past, today, ticker)
        if df.empty:
            return None
        return float(df["종가"].iloc[-1])
    except Exception as e:
        print(f"[현재가 오류] {ticker}: {e}")
        return None

# 기존 report-web 경로의 report.txt 읽기
REPORT_TXT = pathlib.Path(__file__).resolve().parent / "report_kor_etf.txt"
# 통합 폴더에 kor_etf.html로 저장
OUT_HTML   = pathlib.Path(__file__).resolve().parent / "kor_etf.html"
# 🔥 SGDDEMA 불기둥 신호
GANN_FIRE_JSON = pathlib.Path(__file__).resolve().parent / "kr_etf_gann_fire_set.json"
# 저점 5일 추적 이력
LOW_HISTORY_FILE = pathlib.Path(__file__).resolve().parent / "kor_etf_low_history.json"


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
    today     = datetime.date.today()
    today_str = today.isoformat()
    history   = load_low_history()

    # 1. 7일 초과 항목 삭제
    to_delete = []
    for ticker, rec in history.items():
        try:
            first_date   = datetime.date.fromisoformat(rec["first_date"])
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
        first_date   = datetime.date.fromisoformat(rec["first_date"])
        days_elapsed = (datetime.date.today() - first_date).days
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

def extract_block(lines, start_keys, end_keys=None):
    """start_keys 중 하나로 시작해서 end_keys 중 하나 전까지 블록 추출"""
    start = None
    for i, line in enumerate(lines):
        if any(k in line for k in start_keys):
            start = i
            break
    if start is None:
        return None

    end = len(lines)
    if end_keys:
        for i in range(start + 1, len(lines)):
            if any(lines[i].startswith(k) for k in end_keys):
                end = i
                break

    return "\n".join(lines[start:end]).strip()


import re

def _build_final_order_table(held_list, rank_block, s_data, idx_rel_map=None):
    """
    주문용 최종 보유 목록 테이블 생성
    - 헤더 없음
    - 컬럼: 티커 / 종목명 / 등락% / 위치 / Sco / 투자% / 지수대비
    - 0~6개 모두 지원
    - 투자%: internal_weights + kospi_mult/nasdaq_mult 기반 계산
    - 지수대비(%): kr_etf_low_signals.json의 idx_rel 필드 사용
    """
    if not held_list:
        return '<p style="color:#7f8c8d;">보유 종목 없음 (현금 100%)</p>'

    # JSON에서 투자비중 계산 재료 가져오기
    internal_weights = s_data.get('internal_weights', [])   # top3 내부비중 (%)
    top3_k_tickers   = s_data.get('top3_k_tickers', [])    # 한국ETF 티커 목록
    k_mult           = s_data.get('kospi_mult', 0)
    us_mult          = s_data.get('nasdaq_mult', 0)
    total_invest_pct = s_data.get('invest_pct', 0)          # 총 투자비중 %

    # 종목별 실투자% 계산
    # top3(=internal_weights 순서)는 mult 적용, 그 이후 종목(이전 보유 유지)은 별도 처리
    # top3_k_tickers 에 있으면 k_mult, 없으면 us_mult
    alloc_pct = {}
    for i, tk in enumerate(held_list):
        w = internal_weights[i] / 100.0 if i < len(internal_weights) else 0
        mult = k_mult if tk in top3_k_tickers else us_mult
        pct = w * mult * 100
        alloc_pct[tk] = pct

    # ── 현재가 미리 조회 (종목 수 최대 6개라 부담 없음) ──────
    price_map = {}
    for tk in held_list:
        price_map[tk] = _get_kor_price(tk)

    # rank_block에서 각 티커의 행 데이터 파싱
    rank_rows = {}
    for line in rank_block.splitlines():
        line = line.strip()
        if not line or line.startswith('Ticker') or all(c in '-=' for c in line):
            continue
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 5:
            cols = line.split()
        if not cols:
            continue
        raw_ticker = cols[0].strip()
        is_warn_x = raw_ticker.startswith('X_')
        if is_warn_x:
            raw_ticker = raw_ticker[2:]
        ticker_match = re.search(r'(\d{6,}|[0-9A-Z]{6,})', raw_ticker)
        if ticker_match:
            tk = ticker_match.group(1)
            rank_rows[tk] = (cols, is_warn_x)

    rows_html = []
    for tk in held_list:
        data = rank_rows.get(tk)
        cols, is_warn_x = data if data else (None, False)

        if cols is None or len(cols) < 5:
            # 데이터 없으면 티커만 표시
            rows_html.append(f'<tr><td class="narrow held-bold">{html.escape(tk)}</td>'
                             f'<td colspan="5" style="color:#999;">데이터 없음</td></tr>')
            continue

        # 티커 표시 (X_ 제거, ** 유지)
        ticker_disp = cols[0].strip()
        if ticker_disp.startswith('X_'):
            ticker_disp = ticker_disp[2:]

        name_disp = cols[1].strip()
        if name_disp.startswith('X_'):
            name_disp = name_disp[2:]

        chg_str  = cols[2] if len(cols) > 2 else '-'
        pos_str  = cols[3] if len(cols) > 3 else '-'
        sco_str  = cols[4] if len(cols) > 4 else '-'

        # 투자% 셀
        pct_val = alloc_pct.get(tk)
        if pct_val is not None:
            pct_disp = f'{pct_val:.1f}%'
            pct_color_style = 'color:#27ae60;font-weight:bold;' if pct_val >= 20 else 'color:#e67e22;font-weight:bold;'
        else:
            pct_disp = '-'
            pct_color_style = 'color:#999;'

        # 등락률 색상
        try:
            chg_val = float(re.sub(r'[^\d.+-]', '', chg_str))
            chg_cls = 'sig-up' if chg_val > 0 else ('sig-down' if chg_val < 0 else '')
        except:
            chg_cls = ''

        # 위치 색상 및 배지 적용 (1~5)
        pos_badge = f'<span class="pos-badge pos-{pos_str}">{html.escape(pos_str)}</span>' if pos_str in ('1','2','3','4','5') else html.escape(pos_str)

        # 지수대비(%) 셀
        idx_rel_val = (idx_rel_map or {}).get(tk)
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

        # 수량 셀: 백만원 / 종목현재가 (소수점 버림)
        price = price_map.get(tk)
        if price and price > 0:
            qty = int(BUDGET / price)
            qty_disp = f'{qty:,}주'
        else:
            qty_disp = '-'

        row_cls = 'warn-x' if is_warn_x else ''
        rows_html.append(
            f'<tr class="{row_cls}">'
            f'<td class="narrow held-bold" data-code="{html.escape(tk)}" data-name="{html.escape(name_disp)}">{html.escape(ticker_disp)}</td>'
            f'<td class="name-col held-bold">{html.escape(name_disp)}</td>'
            f'<td class="{chg_cls}">{html.escape(chg_str)}</td>'
            f'<td>{pos_badge}</td>'
            f'<td>{html.escape(sco_str)}</td>'
            f'<td style="{pct_color_style}">{pct_disp}</td>'
            f'<td class="{ir_cls}">{ir_disp}</td>'
            f'<td style="font-weight:bold;">{qty_disp}</td>'
            f'</tr>'
        )

    thead_html = (
        '<thead><tr>'
        '<th>ticker</th>'
        '<th>Name</th>'
        '<th>등락</th>'
        '<th>위치</th>'
        '<th>sco</th>'
        '<th>비중</th>'
        '<th>지수대비(%)</th>'
        '<th>수량</th>'
        '</tr></thead>'
    )
    return '<table class="styled-table final-order-table">\n' + thead_html + '\n<tbody>\n' + '\n'.join(rows_html) + '\n</tbody></table>'


def text_to_html_table(text, held_list=None, add_header=False, header_cols=None, low_signals_dict=None, idx_rel_map=None, lime_thresh_map=None, gann_fire_set=None, low_history=None):
    """
    text(table) → HTML 변환
    - held_list: 보유 종목 리스트 (노란색 강조)
    - low_signals_dict: {ticker: (jeo, jeo2)} 저점 신호 딕셔너리
    - lime_thresh_map: {ticker: (label, price)} 추세 전환가 딕셔너리
    - gann_fire_set: 🔥 GANN 불기둥 신호 티커 세트
    """
    if low_signals_dict is None:
        low_signals_dict = {}
    if lime_thresh_map is None:
        lime_thresh_map = {}
    if gann_fire_set is None:
        gann_fire_set = set()
    
    # 만약 텍스트 전체가 짧고(2줄 이하) '없음' 이 있으면 표 렌더링 생략
    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p>{html.escape(text)}</p>'
    
    raw_lines = text.strip().splitlines()
    if not raw_lines: return ""

    SKIP_PATTERNS = ['투자금액 배분된', '시간']
    data_lines = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped: continue
        if all(c in '-=' for c in stripped): continue
        if any(p in stripped for p in SKIP_PATTERNS): continue
        data_lines.append(stripped)
    if not data_lines: return f'<pre>{html.escape(text)}</pre>'

    html_output = ['<table class="styled-table">']
    
    # 헤더 감지
    first_line = data_lines[0].strip()
    is_header = first_line.startswith("Ticker")
    
    start_idx = 0
    if is_header:
        # "추세" 제거, "저점" 추가
        headers = header_cols or ["Ticker", "Name", "등락", "위치", "Sco", "RSI", "정", "5", "10", "20", "60", "120", "136평", "3M(%)", "Score", "저점", "지수대비"]
        html_output.append("<thead><tr>" + "".join(f"<th>{html.escape(h.strip())}</th>" for h in headers) + "</tr></thead>")
        start_idx = 1
    elif add_header and header_cols:
        html_output.append("<thead><tr>" + "".join(f"<th>{html.escape(h.strip())}</th>" for h in header_cols) + "</tr></thead>")
        
    html_output.append("<tbody>")
    for line in data_lines[start_idx:]:
        line = line.strip()
        if not line: continue
        
        # 공백 2개 이상으로 분리
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 5: cols = line.split()

        # 티커 추출 및 보유 종목 강조
        current_ticker = ""
        is_warn_x = False  # X_ 벤치마크 경고 여부
        if len(cols) > 0:
            raw_ticker = cols[0].strip()
            if raw_ticker.startswith("X_"):
                is_warn_x = True
                cols[0] = raw_ticker[2:]  # X_ 제거 후 표시
            if len(cols) > 1 and cols[1].strip().startswith("X_"):
                cols[1] = cols[1].strip()[2:]  # 종목명 X_ 제거
            ticker_match = re.search(r'([0-9A-Z]{6,})', cols[0])
            if ticker_match:
                current_ticker = ticker_match.group(1)
        
        highlight_class = ""
        if held_list and current_ticker in held_list:
            ticker_idx = held_list.index(current_ticker)
            highlight_class = "held-bold" if (len(held_list) <= 3 or ticker_idx < 3) else "held-plain"
        
        # 추세 색상 및 스타일 미리 파악 (index 11)
        name_style = ""
        trend_val = cols[12].upper() if len(cols) > 12 else ""
        if "LIME" in trend_val or trend_val == "3":
            name_style = 'style="background-color:#2ecc71; color:black; font-weight:bold;"'
        elif "GREEN" in trend_val or trend_val == "2" or trend_val == "1":
            # 1 (LIGHT GREEN) 도 GREEN 계열로 처리 (검은 글씨)
            color = "#27ae60" if (trend_val == "2" or "GREEN" in trend_val) else "#a5d6a7"
            name_style = f'style="background-color:{color}; color:black; font-weight:bold;"'
        elif "RED" in trend_val or trend_val == "-3" or trend_val == "-1":
            color = "#e74c3c" if (trend_val == "-3" or "RED" in trend_val) else "#ef9a9a"
            # 진한 빨강계열은 흰색, 연한 빨강은 검정 (사용자 요청: purple/red는 흰색)
            text_color = "white" if (trend_val == "-3" or "RED" in trend_val) else "black"
            name_style = f'style="background-color:{color}; color:{text_color}; font-weight:bold;"'
        elif "PURPLE" in trend_val or trend_val == "-2":
            name_style = 'style="background-color:#9b59b6; color:white; font-weight:bold;"'

        row_html = f'<tr class="warn-x">' if is_warn_x else "<tr>"

        # lime_thresh_map에서 이 ticker의 label 미리 파악 (sco 셀 색상용)
        lt_pre = lime_thresh_map.get(current_ticker)
        sco_bg = ""
        if lt_pre:
            ll_pre, _ = lt_pre
            if ll_pre.startswith('▲'):
                sco_bg = 'background-color:#fff176;'   # 노란색 - 진입 근접
            else:
                sco_bg = 'background-color:#ffe0b2;'   # 옅은 주황 - 이탈 근접

        for i, c in enumerate(cols):
            # 추세 컬럼(index 12), 지수대비 컬럼(index 16), 전환가 텍스트(index 17) 렌더링 배제
            # (지수대비·전환가는 아래에서 map 기반으로 별도 렌더링)
            if i == 12 or i == 16 or i >= 17: continue

            cell_class = []
            content = html.escape(c)
            extra_style = ""
            data_attrs = ""

            if i == 0:
                cell_class.append("narrow")
                if highlight_class: cell_class.append(highlight_class)
                if current_ticker:
                    _nm = html.escape(cols[1].strip() if len(cols) > 1 else "")
                    data_attrs = f' data-code="{html.escape(current_ticker)}" data-name="{_nm}"'
            elif i == 1:
                cell_class.append("name-col")
                if highlight_class: cell_class.append(highlight_class)
                extra_style = name_style
            elif i == 2:
                # 등락률 색상
                try:
                    val = float(re.sub(r'[^\d.+-]', '', c))
                    cell_class.append("sig-up" if val > 0 else ("sig-down" if val < 0 else ""))
                except: pass

            # 위치 (index 3) - 동그라미 뱃지 적용
            elif i == 3:
                pos_val = c.strip()
                if pos_val in ("1","2","3","4","5"):
                    content = f'<span class="pos-badge pos-{pos_val}">{content}</span>'
                elif c == "5": cell_class.append("pos-5")
                elif c == "4": cell_class.append("pos-4")

            # Sco (index 4) - 추세전환 근접 시 배경색
            elif i == 4:
                if sco_bg:
                    extra_style = f'style="{sco_bg}font-weight:bold;"'

            # RSI (index 5) - 당일(전일) 형식, 30선 돌파 시 연한 녹색 배경 + 글자색
            elif i == 5:
                m_rsi = re.match(r'(\d+)\((\d+)\)', c.strip())
                if m_rsi:
                    today_rsi = int(m_rsi.group(1))
                    prev_rsi  = int(m_rsi.group(2))
                    # 글자색: >=50 녹색, <50 빨간색
                    cell_class.append("up" if today_rsi >= 50 else "down")
                    # 30선 돌파(전일<30→당일>=30) 시 연한 녹색 배경 추가
                    if today_rsi >= 30 and prev_rsi < 30:
                        extra_style = 'style="background-color:#d5f5e3; font-weight:bold;"'

            # 정/역배 (index 6)
            elif i == 6:
                if "정배" in c: cell_class.append("sig-jung")
                elif "역배" in c: cell_class.append("sig-yeok")

            # 이평 방향 (index 7, 8, 9, 10, 11)
            elif 7 <= i <= 11:
                if c.strip() == '상': cell_class.append("up")
                elif c.strip() == '하': cell_class.append("down")

            # 136평균 (index 13)
            elif i == 13:
                try:
                    num_val = float(c.replace('%', ''))
                    cell_class.append("up" if num_val > 0 else ("down" if num_val < 0 else ""))
                except: pass

            cls_str = f' class="{" ".join(cell_class)}"' if cell_class else ''
            style_str = f' {extra_style}' if extra_style else ''
            row_html += f"<td{cls_str}{style_str}{data_attrs}>{content}</td>"
        
        # ✅ 저점 신호 뱃지 추가 (이력 기반 5일 추적)
        if low_history is not None:
            low_badge = get_low_badge(current_ticker, low_history)
        else:
            # fallback: low_history 없으면 기존 방식
            jeo, jeo2 = (low_signals_dict or {}).get(current_ticker, ('-', '-'))
            low_badge = ""
            if jeo != '-' and jeo2 != '-':
                low_badge = '<span class="low-badge low-both">저1,2</span>'
            elif jeo != '-':
                low_badge = '<span class="low-badge low-jeo">저</span>'
            elif jeo2 != '-':
                low_badge = '<span class="low-badge low-jeo2">저2</span>'

        # 🔥 GANN 불기둥 배지
        if current_ticker.zfill(6) in gann_fire_set:
            low_badge += ' <span style="display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:bold;background:#2980b9;color:white;">🔥</span>'

        row_html += f"<td>{low_badge}</td>"
        
        # ✅ 지수대비(%) 컬럼 추가
        if idx_rel_map is None:
            idx_rel_map = {}
        idx_rel_val = idx_rel_map.get(current_ticker)
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

        # ✅ 추세 전환가 컬럼 추가
        lt = lime_thresh_map.get(current_ticker)
        if lt:
            ll, lp = lt
            is_entry = ll.startswith('▲')
            lt_color = '#27ae60' if is_entry else '#e74c3c'
            lt_disp  = f'{ll} {lp:,}'
            row_html += f'<td style="color:{lt_color};font-weight:bold;white-space:nowrap;">{lt_disp}</td>'
        else:
            row_html += '<td></td>'
        
        row_html += "</tr>"
        html_output.append(row_html)
    html_output.append("</tbody></table>")
    return "\n".join(html_output)


def main():
    text = REPORT_TXT.read_text(encoding="utf-8", errors="replace") if REPORT_TXT.exists() else ""
    lines = text.splitlines()
    lines = [
        line for line in lines
        if "매매용 티커 목록이" not in line
        and "점수 순위대로 정렬" not in line
    ]


    # 1️⃣ 랭킹 (출력 형식: '전체 종목 (투자금액 배분 순):')
    rank_block = extract_block(
        lines,
        start_keys=["전체 종목 (투자금액 배분 순)", "투자금액 배분된 종목"],
        end_keys=["이전 보유 종목:", "현재 Top 3:", "현재 Top3", "✅", "최종 보유 종목"]
    ) or "(랭킹 없음)"

    # 2️⃣ 최종 보유 종목 (형식: '최종 보유 종목 (N개): [...]')
    final_hold = extract_block(
        lines,
        start_keys=["최종 보유 종목"],
        end_keys=["[ATR 트리거", "[ATR 트레일링", "✅ 매매용", "\n\n"]
    ) or "(최종 보유 종목 없음)"

    # Extract held list BEFORE stripping title line
    held_list = []
    if final_hold:
        # 형식: 최종 보유 종목 (3개): ['455850', '478150', '449450']
        held_match = re.search(r"최종 보유 종목.*?:\s*\[(.+?)\]", final_hold)
        if held_match:
            held_list = [t.strip().strip("'").strip('"') for t in held_match.group(1).split(',')]
        else:
            # 기존 fallback
            held_match2 = re.search(r'\[(.*?)\]', final_hold)
            if held_match2:
                held_list = [t.strip().strip("'").strip('"') for t in held_match2.group(1).split(',')]

    # Clean redundant titles after extraction
    if rank_block and rank_block != "(랭킹 없음)":
        first = rank_block.splitlines()[0]
        if "투자금액 배분" in first or "전체 종목" in first:
            rank_block = "\n".join(rank_block.splitlines()[1:]).strip()
    # Clear titles and define other blocks
    atr_trigger = extract_block(
        lines,
        start_keys=["[ATR 트리거"],
        end_keys=["[ATR 트레일링"]
    )
    if atr_trigger and "[" in atr_trigger:
        # 제목줄, 헤더줄, 합계줄 제거
        tr_lines = [l for l in atr_trigger.splitlines() 
                    if not l.strip().startswith("[") 
                    and "Ticker" not in l 
                    and "종목 수" not in l and "수:" not in l]
        atr_trigger = "\n".join(tr_lines).strip()
    atr_trigger = atr_trigger or "[ATR 트리거 종목] 없음"

    atr_exclude = extract_block(
        lines,
        start_keys=["[ATR 트레일링"],
        end_keys=["[실행 소요 시간]", "========================================"]
    )
    if atr_exclude and "[" in atr_exclude:
        ex_lines = [l for l in atr_exclude.splitlines() 
                    if not l.strip().startswith("[") 
                    and "Ticker" not in l 
                    and "종목 수" not in l and "수:" not in l]
        atr_exclude = "\n".join(ex_lines).strip()
    atr_exclude = atr_exclude or "[ATR 트레일링] 없음"

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 3️⃣ 투자자 매매 동향 읽기
    investor_html = ""
    investor_file = pathlib.Path(__file__).resolve().parent / "investor_data.json"
    if investor_file.exists():
        try:
            inv_data = json.loads(investor_file.read_text(encoding="utf-8"))
            kpi = inv_data.get('KOSPI', {})
            kdq = inv_data.get('KOSDAQ', {})
            investor_html = f"""
<p style="margin: 0; font-size: 0.9em; color: #34495e;">Kospi200 ({kpi.get('change_rate','0%')}) : 외국인 {kpi.get('foreigner','0')}억 / 연기금 {kpi.get('pension','0')}억</p>
<p style="margin: 0; font-size: 0.9em; color: #34495e;">Kosdaq150 ({kdq.get('change_rate','0%')}): 외국인 {kdq.get('foreigner','0')}억 / 연기금 {kdq.get('pension','0')}억</p>
"""
        except:
            pass

    # 4️⃣-pre: adv_momentum.html에서 PAA 투자비중 읽기
    paa_invest_pct_str = ""
    adv_html_file = pathlib.Path(__file__).resolve().parent / "adv_momentum.html"
    if adv_html_file.exists():
        try:
            adv_text = adv_html_file.read_text(encoding="utf-8")
            paa_match = re.search(r'투자비중\s*(\d+(?:\.\d+)?%)', adv_text)
            if paa_match:
                paa_invest_pct_str = paa_match.group(1)
        except:
            pass

    # 4️⃣ Signal_sco 통계 읽기
    stats_html = ""
    stats_file = pathlib.Path(__file__).resolve().parent / "kr_signal_stats.json"

    # ✅ 저점 신호 JSON 읽기
    low_signals_dict = {}
    idx_rel_map = {}  # 지수대비(%) 데이터
    lime_thresh_map = {}  # 추세 전환가 데이터
    low_signal_file = pathlib.Path(__file__).resolve().parent / "kr_etf_low_signals.json"
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
                if sig.get('lime_label') and sig.get('lime_price') is not None:
                    lime_thresh_map[ticker] = (sig['lime_label'], sig['lime_price'])
        except:
            pass

    # 🔥 SGDDEMA 불기둥 신호 티커 세트 로드
    gann_fire_set = set()
    if GANN_FIRE_JSON.exists():
        try:
            gann_data = json.loads(GANN_FIRE_JSON.read_text(encoding='utf-8'))
            gann_fire_set = set(str(t).strip().zfill(6) for t in gann_data.get('tickers', []))
        except Exception:
            gann_fire_set = set()

    # 벤치마크 추세 파싱 ([벤치마크 추세] 2줄)
    def parse_trend(val):
        """추세 값을 색상 포함 HTML span으로 변환"""
        COLOR = {
            'LIME':   '#2ecc71',
            'GREEN':  '#27ae60',
            'PURPLE': '#9b59b6',
            'RED':    '#e74c3c',
        }
        v = (val or '-').strip()
        color = COLOR.get(v.upper(), '#7f8c8d')
        return f'<b style="color:{color};">{v}</b>'

    bench_html = ""
    bench_line1 = next((l for l in lines if '[벤치마크 추세]' in l), None)
    bench_line2 = None
    if bench_line1:
        idx = lines.index(bench_line1)
        if idx + 1 < len(lines) and '에센피' in lines[idx + 1]:
            bench_line2 = lines[idx + 1]

    def extract_trend(line, key):
        m = re.search(rf'{key}:\s*(\S+)', line)
        return m.group(1) if m else '-'

    if bench_line1:
        kospi  = extract_trend(bench_line1, '코스피')
        kosdaq = extract_trend(bench_line1, '코스닥')
        sp500  = extract_trend(bench_line2, '에센피') if bench_line2 else '-'
        nasdaq = extract_trend(bench_line2, '나스닥') if bench_line2 else '-'
        bench_html = f"""
<p style="margin:0; font-size:0.95em;">
    🌐 &nbsp;
    <span class="label">코스피:</span> {parse_trend(kospi)} &nbsp;/&nbsp;
    <span class="label">코스닥:</span> {parse_trend(kosdaq)} &nbsp;&nbsp;|&nbsp;&nbsp;
    <span class="label">에센피:</span> {parse_trend(sp500)} &nbsp;/&nbsp;
    <span class="label">나스닥:</span> {parse_trend(nasdaq)}
</p>"""

    s_data = {}
    if stats_file.exists():
        try:
            s_data = json.loads(stats_file.read_text(encoding="utf-8"))
            invest_pct  = s_data.get('invest_pct', 0)
            strong_cnt  = s_data.get('strong_count', 0)
            t_sco       = s_data.get('top3_avg_sco')
            t_pos       = s_data.get('top3_avg_pos')
            t_sco_str   = f"{t_sco:.2f}" if t_sco is not None else "-"
            t_pos_str   = f"{t_pos:.2f}" if t_pos is not None else "-"

            # 벤치마크 multiplier (새 로직)
            k_trend   = s_data.get('kospi_trend',  '-')
            kd_trend  = s_data.get('kosdaq_trend', '-')
            sp_trend  = s_data.get('sp500_trend',  '-')
            us_trend  = s_data.get('nasdaq_trend', '-')
            euro_trend  = s_data.get('euro_trend',  '-')
            india_trend = s_data.get('india_trend', '-')
            nikkei_trend = s_data.get('nikkei_trend', '-')
            k_mult    = s_data.get('kospi_mult',  '-')
            us_mult   = s_data.get('nasdaq_mult', '-')
            k_mult_str  = f"×{k_mult}"  if k_mult  != '-' else '-'
            us_mult_str = f"×{us_mult}" if us_mult != '-' else '-'

            TREND_COLOR = {
                'LIME':   '#2ecc71',
                'GREEN':  '#27ae60',
                'PURPLE': '#9b59b6',
                'RED':    '#e74c3c',
            }

            def bench_cell(label, trend):
                color = TREND_COLOR.get((trend or '').upper(), '#95a5a6')
                return (
                    f'<td title="{label}: {trend or "-"}" '
                    f'style="background:{color};color:white;font-weight:bold;'
                    f'padding:4px 10px;text-align:center;border-radius:4px;'
                    f'font-size:1.0em;white-space:nowrap;">'
                    f'{label}</td>'
                )

            bench_table_html = f"""
<table style="border-collapse:separate;border-spacing:3px;margin-bottom:6px;width:auto;">
<tr>
  {bench_cell('코', k_trend)}
  {bench_cell('닥', kd_trend)}
  {bench_cell('미', sp_trend)}
  {bench_cell('나', us_trend)}
  {bench_cell('일', nikkei_trend)}
  {bench_cell('유', euro_trend)}
  {bench_cell('인', india_trend)}
</tr>
</table>"""

            # 투자비중 색상
            if invest_pct >= 80:
                pct_color = "#27ae60"
            elif invest_pct >= 50:
                pct_color = "#e67e22"
            elif invest_pct > 0:
                pct_color = "#c0392b"
            else:
                pct_color = "#7f8c8d"

            paa_suffix = f' &nbsp;<span style="color:#2c3e50;font-size:0.9em;">/ 연금 {paa_invest_pct_str}</span>' if paa_invest_pct_str else ''

            stats_html = f"""
{bench_table_html}
<div class="stats-summary-box">
    <p style="margin:0; font-size:1.05em; margin-bottom:4px;">
        📊 &nbsp;<b style="color:{pct_color};">총 투자비중={invest_pct:.1f}%</b>{paa_suffix} &nbsp;/&nbsp;
        <span class="label">top3_avg_sco=</span><b>{t_sco_str}</b> &nbsp;/&nbsp;
        <span class="label">top3_avg_pos=</span><b>{t_pos_str}</b>
    </p>
    <p style="margin:0; font-size:0.95em; margin-bottom:4px; color:#7f8c8d;">
        &nbsp;&nbsp;&nbsp; 📉 <span class="label">Top3 vol63 중앙값:</span>
        <b style="color:#e67e22;">{f"{s_data['vol63_median']:.1f}%" if s_data.get('vol63_median') is not None else "-"}</b>
    </p>
    <p style="margin:0; font-size:1.0em; margin-bottom:3px;">
        <span class="label">전체 종목 Signal_sco 평균:</span> <b>{s_data.get('avg_sco', '0.0')}</b>
        <span style="font-size:0.85em; color: #7f8c8d;"> (전체 {s_data.get('total_cnt')}개 / 유효 {s_data.get('valid_cnt')}개 / ATR제외 {s_data.get('atr_excl_cnt')}개 포함)</span>
    </p>
    <p style="margin:0; margin-bottom:3px;">
        &nbsp;&nbsp;&nbsp; <span class="label">sco &gt;= 0 :</span> {s_data.get('sco_pos')}개 /
        <span class="label">sco &lt; 0 :</span> {s_data.get('sco_neg')}개 /
        <span class="label">sco &gt;= 11 :</span> <b>{s_data.get('sco_strong')}개</b>
    </p>
</div>
<div class="stats-summary-mobile" style="display:none; font-size:0.9em; color:#34495e; margin:8px 0;">
  📊 &nbsp;<b style="color:{pct_color};">총 투자비중={invest_pct:.1f}%</b>{paa_suffix} &nbsp;/&nbsp;
  <span style="font-weight:bold; color:#2c3e50;">top3_avg_sco=</span><b>{t_sco_str}</b> &nbsp;/&nbsp;
  <span style="font-weight:bold; color:#2c3e50;">top3_avg_pos=</span><b>{t_pos_str}</b>
</div>
"""
        except:
            pass

    # 저점 이력 업데이트 (low_signals_dict 기준)
    low_history = update_low_history(low_signals_dict)

    rank_html = text_to_html_table(rank_block, held_list,
        add_header=True,
        header_cols=["Ticker", "Name", "등락", "위치", "Sco", "RSI", "정", "5", "10", "20", "60", "120", "136평", "3M(%)", "Score", "저점", "지수대비", "전환가"],
        low_signals_dict=low_signals_dict,
        idx_rel_map=idx_rel_map,
        lime_thresh_map=lime_thresh_map,
        gann_fire_set=gann_fire_set,
        low_history=low_history
    )

    # 최종 보유 종목용 테이블 생성 (0~6개, 헤더 없음)
    # 컬럼: 티커 / 종목명 / 등락% / 위치 / Sco / 투자% / 지수대비
    final_order_html = _build_final_order_table(held_list, rank_block, s_data, idx_rel_map)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Korea ETF Report</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 15px;
  margin: 0;
  background-color: #f4f7f6;
}}
.container-all {{ max-width: 1200px; margin: 0; }}
h1 {{ margin: 0 0 4px 0; padding: 0; font-size: 1.2em; color: #2c3e50; }}
h2 {{
  margin: 10px 0 4px 0;
  padding-bottom: 3px;
  color: #2c3e50;
  border-bottom: 2px solid #3498db;
  font-size: 1.0em;
}}
.styled-table {{
  width: auto;
  min-width: 400px;
  max-width: 100%;
  border-collapse: collapse;
  margin: 4px 0 12px 0;
  font-size: 12px;
  background: white;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  border-radius: 8px;
  overflow: hidden;
}}
.styled-table thead tr {{
  background: linear-gradient(135deg, #3498db, #2980b9);
  color: #ffffff;
  text-align: center;
}}
.styled-table th, .styled-table td {{
  padding: 6px 10px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
}}
.styled-table td.narrow {{ font-weight: bold; color: #2980b9; text-align: left; }}
.styled-table td.name-col {{ max-width: 150px; overflow: hidden; text-overflow: ellipsis; text-align: left; }}
.styled-table td {{ text-align: center; }}

.up, .sig-up {{ color: #27ae60; font-weight: bold; }}
.down, .sig-down {{ color: #e74c3c; font-weight: bold; }}

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

.sig-jung {{ background-color: #e8f5e9; color: #27ae60 !important; font-weight: bold; }}
.sig-yeok {{ background-color: #ffebee; color: #e74c3c !important; font-weight: bold; }}

.held-bold {{ background-color: #fff9c4 !important; color: #d32f2f !important; font-weight: bold !important; }}
.held-plain {{ background-color: #fff9c4 !important; }}

/* X_ 벤치마크 경고 행 */
.warn-x td {{ opacity: 0.55; }}
.warn-x td.narrow, .warn-x td.name-col {{ text-decoration: line-through; color: #999 !important; }}

/* 요약 통계 박스 */
.stats-summary-box {{
    background-color: #fffde7; /* 연한 노란색 */
    border: 1px solid #fbc02d;
    padding: 12px 18px;
    border-radius: 10px;
    margin: 15px 0;
    font-size: 14px;
    line-height: 1.6;
    color: #34495e;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    display: inline-block;
    min-width: 400px;
}}
.stats-summary-box b {{ color: #d32f2f; }}
.stats-summary-box span.label {{ font-weight: bold; color: #2c3e50; }}

/* Trend Badges */
.trend-badge {{
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: bold;
    color: white;
    display: inline-block;
    min-width: 45px;
    text-align: center;
}}
.trend-lime {{ background-color: #2ecc71; }}
.trend-green {{ background-color: #27ae60; }}
.trend-green-light {{ background-color: #a5d6a7; color: #1b5e20; }}
.trend-red {{ background-color: #e74c3c; }}
.trend-red-light {{ background-color: #ef9a9a; color: #b71c1c; }}
.trend-purple {{ background-color: #9b59b6; }}

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

.top-layout {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 20px;
    margin-bottom: 10px;
}}
.left-content {{ flex: 0 1 auto; }}
.right-sidebar {{
    display: flex;
    flex-direction: row;
    gap: 10px;
    flex-wrap: wrap;
}}
.small-board {{
    background: white;
    padding: 8px;
    border-radius: 8px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    min-width: 200px;
}}
.small-board h3 {{
    margin: 0 0 5px 0;
    font-size: 0.9em;
    color: #2c3e50;
    border-bottom: 1px solid #3498db;
    padding-bottom: 2px;
}}

.top-nav-container {{
    display: flex;
    margin-bottom: 10px;
}}
.top-nav {{
    display: flex;
    background-color: #2c3e50;
    border-radius: 8px;
    overflow: hidden;
    width: fit-content;
}}
.nav-item {{
    padding: 8px 15px;
    color: #bdc3c7;
    text-align: center;
    cursor: pointer;
    font-weight: bold;
    text-decoration: none;
    transition: all 0.3s;
    font-size: 0.9em;
}}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{
    background-color: #3498db;
    color: white;
}}
@media (max-width: 800px) {{
  .top-layout {{ flex-direction: column; }}
  .right-sidebar {{ width: 100%; }}
  .final-order-table {{
    min-width: unset;
    width: 100%;
  }}
  .final-order-table td {{
    padding: 5px 4px;
    font-size: 11px;
  }}
  .final-order-table td.name-col {{
    max-width: 80px;
  }}
  .stats-summary-box {{
    font-size: 11px;
    padding: 7px 10px;
    min-width: unset;
    width: 100%;
    box-sizing: border-box;
    line-height: 1.5;
  }}
  .stats-summary-box p:first-child {{
    font-size: 1.05em;
  }}
  .stats-summary-box p {{
    font-size: 0.95em;
  }}
}}
@media (max-width: 480px) {{
  .stats-summary-box {{ display: none !important; }}
  .stats-summary-mobile {{ display: block !important; }}
}}

@media screen and (max-width: 767px) and (orientation: landscape) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}

/* ── 네이버 차트 팝업 ── */
#naverChartPopup {{
  display: none;
  position: fixed;
  z-index: 99999;
  width: 860px;
  background: #fff;
  border: 1px solid #bdc3c7;
  border-radius: 10px;
  padding: 12px;
  box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto;
  overflow-y: auto;
  max-height: 90dvh;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex;
  background: #e74c3c; color: white;
  border: none; border-radius: 50%;
  width: 28px; height: 28px;
  font-size: 18px; line-height: 1;
  cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center;
  font-weight: bold;
}}
.popup-header {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}}
.popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; margin-left: 1em; }}
.popup-link:hover {{ text-decoration: underline; }}
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.chart-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }}
.chart-card-header {{ display: none; }}
.chart-wrap {{ position: relative; width: 100%; height: 300px; background: white; }}
.chart-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: white; }}
.chart-loading {{
  display: none; position: absolute; inset: 0;
  background: rgba(255,255,255,0.75);
  align-items: center; justify-content: center;
  font-size: 12px; color: #64748b;
}}
.chart-loading.show {{ display: flex; }}

/* ── 스마트폰: 팝업 고정, 차트 상하 배치 ── */
@media (max-width: 767px) {{
  #naverChartPopup {{
    position: fixed !important;
    left: 2vw !important;
    top: 50% !important;
    transform: translateY(-50%);
    width: 96vw !important;
    max-height: 80dvh !important;
    overflow-y: auto !important;
    padding: 8px !important;
    box-sizing: border-box;
  }}
  .charts-grid {{ grid-template-columns: 1fr; gap: 6px; }}
  .chart-wrap {{ height: 220px; }}
  #naverPopupClose {{ display: flex !important; }}
}}

/* 데스크탑(1000px 이상)에서도 적절히 */
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
  .charts-grid {{ grid-template-columns: 1fr; }}
  .chart-wrap {{ height: 260px; }}
}}
</style>
</head>
<body>
<div class="container-all">
    <div class="top-nav-container">
        <div class="top-nav">
            <a href="kor_etf.html" class="nav-item active">한국 ETF</a>
            <a href="top3_etf_daily_result.html" class="nav-item">Top3추세</a>
            <a href="adv_momentum.html" class="nav-item">연금 ETF</a>
        </div>
    </div>

    <div class="top-layout">
        <div class="left-content">
            <h1>🇰🇷 Korea ETF Report</h1>
            <p style="margin: 0 0 2px 0; padding: 0; font-size: 0.85em; color: #7f8c8d;">최종 업데이트: {now}</p>
            {investor_html}
        </div>
    </div>

    {stats_html}

    <h2 style="border-bottom: 2px solid #e67e22;">🧾 주문용 최종 보유 목록 (오늘)</h2>
    {final_order_html}

    <h2>📊 종목 랭킹</h2>
    {rank_html}

    <div class="right-sidebar" style="margin-top: 20px;">
        <div class="small-board">
            <h3>⚠️ ATR 트리거 (2주)</h3>
            {text_to_html_table(atr_trigger, add_header=True, header_cols=["Ticker", "산업", "ATR"])}
        </div>
        <div class="small-board">
            <h3>🛡 ATR 제외</h3>
            {text_to_html_table(atr_exclude, add_header=True, header_cols=["Ticker", "산업", "ATR"])}
        </div>
    </div>
</div>
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
  var popup   = document.getElementById('naverChartPopup');
  var popupTitle  = document.getElementById('popupTitle');
  var popupLink   = document.getElementById('popupLink');
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

  function loadCharts(code, name) {{
    popupTitle.textContent = code + '  ' + (name || '');
    popupLink.href = itemPageUrl(code);
    loadInto(imgDaily,   loadingDaily,   statusDaily,   dailyCandleUrl(code),  '일봉');
    loadInto(imgWeekly,  loadingWeekly,  statusWeekly,  weeklyCandleUrl(code), '주봉');
  }}

  function placePopup(cx, cy) {{
    var isMobile = window.innerWidth <= 767;
    if (isMobile) return;  // 모바일은 CSS fixed 중앙 고정
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
    popup.style.transform = 'none';
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

  document.querySelectorAll('td[data-code]').forEach(function (td) {{
    td.addEventListener('mouseenter', function (e) {{
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        loadCharts(td.dataset.code, td.dataset.name || '');
      }}, 140);
    }});
    td.addEventListener('mousemove', function (e) {{
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    td.addEventListener('mouseleave', function () {{
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    // 📱 스마트폰 탭 지원
    td.addEventListener('click', function (e) {{
      if (window.innerWidth > 767) return; // 데스크탑은 hover만
      e.stopPropagation();
      openPopup();
      loadCharts(td.dataset.code, td.dataset.name || '');
    }});
  }});
  // 📱 팝업 바깥 터치하면 닫기
  document.addEventListener('click', function(e) {{
    if (window.innerWidth <= 767 && popup.style.display === 'block') {{
      if (!popup.contains(e.target)) closePopup();
    }}
  }});
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

    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] kor_etf.html updated at {OUT_HTML}")



if __name__ == "__main__":
    main()
