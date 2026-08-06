import html
import re
import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

BASE = Path(__file__).resolve().parent
REPORT_TXT = BASE.parent / "report_kr_summary.txt"
OUT_HTML = BASE.parent / "kor_stock.html"
LEADER_TRACKING_JSON = BASE.parent / "leader_tracking.json"  # 📊 주도주 트래킹 파일
GANN_FIRE_JSON = BASE.parent / "kr_gann_fire_set.json"  # 🔥 SGDDEMA 불기둥 신호
HIGH52W_JSON = BASE.parent / "kr_52w_high.json"  # 52주 신고가 95% 이상 종목
INVESTOR_FILE = Path(r"D:\py\0txt\leader_investor_data.json")

# Minervini CSV files
MINERVINI_EARLY = Path("D:/py/minervini_kr_early_stage.csv")
MINERVINI_ENTRY = Path("D:/py/minervini_kr_entry_timing.csv")


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


def extract_block(text, start_marker, end_markers):
    lines = text.splitlines()
    start = None
    # 뒤에서부터 검색하여 마지막 섹션을 찾음 (콘솔 로그와 리포트가 섞였을 때 리포트 우선)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith(start_marker):
            start = i
            break
            
    if start is None:
        return ""

    end = len(lines)
    for i in range(start + 1, len(lines)):
        # Check against all possible end markers
        if any(lines[i].strip().startswith(m) for m in end_markers):
            end = i
            break

    return "\n".join(lines[start:end]).strip()


def format_minervini_table(csv_path: Path, title: str) -> str:
    """Format Minervini CSV data as HTML table"""
    if not csv_path.exists():
        return f"<p>({title} 데이터 없음)</p>"
    
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        
        if df.empty:
            return f"<p>({title} 종목 없음)</p>"
        
        # Select key columns
        display_cols = ['Ticker', 'Name', 'Close', 'Days_passed', 'R3M', 'early_stage_score', 'RS_rating']
        
        # Check if columns exist (sometimes CSV might be empty or different)
        available_cols = [c for c in display_cols if c in df.columns]
        if not available_cols:
             return f"<p>({title} 컬럼 형식 불일치)</p>"

        df_display = df[available_cols].head(20) # Show top 20
        
        html_lines = []
        html_lines.append('<table class="styled-table">')
        html_lines.append('<thead><tr>')
        html_lines.append('<th class="center">Ticker</th><th>Name</th><th class="num">Close</th><th class="num">Days</th><th class="num">R3M(%)</th><th class="num">Early</th><th class="num">RS</th>')
        html_lines.append('</tr></thead>')
        html_lines.append('<tbody>')
        
        for _, row in df_display.iterrows():
            ticker = str(row['Ticker']).zfill(6)
            name = str(row['Name'])
            close = f"{row['Close']:,.0f}"
            days = f"{int(row['Days_passed'])}" if 'Days_passed' in row and pd.notna(row['Days_passed']) else "-"
            r3m = f"{row['R3M']:.1f}" if 'R3M' in row and pd.notna(row['R3M']) else "-"
            early = f"{row['early_stage_score']:.1f}" if 'early_stage_score' in row and pd.notna(row['early_stage_score']) else "-"
            rs = f"{row['RS_rating']:.1f}" if 'RS_rating' in row and pd.notna(row['RS_rating']) else "-"
            
            html_lines.append(f'<tr>')
            html_lines.append(f'<td class="center"><b>{ticker}</b></td>')
            html_lines.append(f'<td>{name}</td>')
            html_lines.append(f'<td class="num">{close}</td>')
            html_lines.append(f'<td class="num">{days}</td>')
            r3m_color = "red" if (float(r3m) > 30 if r3m != "-" else False) else "black"
            html_lines.append(f'<td class="num" style="color:{r3m_color}">{r3m}</td>')
            html_lines.append(f'<td class="num">{early}</td>')
            html_lines.append(f'<td class="num"><b>{rs}</b></td>')
            html_lines.append(f'</tr>')
            
        html_lines.append('</tbody></table>')
        
        return "\n".join(html_lines)
        
    except Exception as e:
        return f"<p>({title} 로드 실패: {str(e)})</p>"


def parse_nxt(raw):
    """마지막 탭/파이프 구분 필드가 NXT/선/NXT선 이면 배지 반환"""
    parts = re.split(r'[\t|]', raw.strip())
    last = parts[-1].strip()
    if last in ('NXT', '선', 'NXT선'):
        return f'<span class="{'nxt-badge-both' if last == 'NXT선' else 'nxt-badge'}\">{last}</span>'
    # 구형식 호환
    match = re.search(r'NXT:(NXT선|NXT|선)', raw)
    if match:
        return f'<span class="{'nxt-badge-both' if match.group(1) == 'NXT선' else 'nxt-badge'}\">{match.group(1)}</span>'
    return ''

def parse_signal_line(line):
    """MOM/LIME/GREEN 형식: ticker | signal | name | 거래대금:xxx | NXT:...
    파이프(|) 구분, 등락률 컬럼 없음"""
    line = line.strip()
    parts = [p.strip() for p in line.split('|')]
    ticker   = parts[0] if len(parts) > 0 else ''
    # parts[1] = signal type (MOM/LIME/GREEN), parts[2] = name
    name     = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else '')
    nxt_html = parse_nxt(line)
    return ticker, name, nxt_html

def parse_red_line(line):
    """RED 형식 (탭구분): ticker\tRED\tname\tx,xxx억\tNXT"""
    line = line.strip()
    parts = [p.strip() for p in line.split('\t')]
    ticker   = parts[0] if len(parts) > 0 else ''
    name     = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else '')
    nxt_html = parse_nxt(line)
    return ticker, name, nxt_html

def make_signal_table(lines, is_spot=False, is_red=False):
    """신호 테이블 생성
    - MOM/LIME/GREEN: ticker | signal | name | x,xxx억 | NXT
    - SPOT: ticker\tpct\tname\tx,xxx억\tNXT
    - RED: ticker\tRED\tname\tx,xxx억  (NXT 컬럼 없음)
    """
    data_lines = [l for l in lines
                  if l.strip()
                  and not all(c in '-=' for c in l.strip())
                  and '없음' not in l
                  and '【' not in l]
    if not data_lines:
        return '<p style="color:#95a5a6; margin-left:10px;">(없음)</p>'

    rows = []
    for line in data_lines:
        if is_spot:
            # SPOT: 탭구분 → ticker / pct / name / x,xxx억 / NXT
            parts = [p.strip() for p in line.strip().split('\t')]
            ticker   = parts[0] if len(parts) > 0 else ''
            pct      = parts[1] if len(parts) > 1 else ''
            name     = parts[2] if len(parts) > 2 else ''
            tv_str   = parts[3] if len(parts) > 3 else ''
            nxt_html = parse_nxt(line)
            try:
                val = float(pct.replace('%','').replace('+',''))
                pct_cls = 'up' if val > 0 else ('down' if val < 0 else '')
            except:
                pct_cls = ''
            rows.append(
                f'<tr>'
                f'<td class="narrow">{html.escape(ticker)}</td>'
                f'<td class="name-col">{html.escape(name)}</td>'
                f'<td class="{pct_cls}">{html.escape(pct)}</td>'
                f'<td style="color:#888; font-size:12px;">{html.escape(tv_str)}</td>'
                f'<td class="nxt-cell">{nxt_html}</td>'
                f'</tr>'
            )
        elif is_red:
            ticker, name, nxt_html = parse_red_line(line)
            rows.append(
                f'<tr>'
                f'<td class="narrow">{html.escape(ticker)}</td>'
                f'<td class="name-col">{html.escape(name)}</td>'
                f'<td class="nxt-cell">{nxt_html}</td>'
                f'</tr>'
            )
        else:
            # MOM/LIME/GREEN: 파이프구분, 등락률 없음
            ticker, name, nxt_html = parse_signal_line(line)
            rows.append(
                f'<tr>'
                f'<td class="narrow">{html.escape(ticker)}</td>'
                f'<td class="name-col">{html.escape(name)}</td>'
                f'<td class="nxt-cell">{nxt_html}</td>'
                f'</tr>'
            )

    if is_spot:
        header = ('<thead><tr>'
                  '<th>Ticker</th><th>Name</th><th>등락률</th><th>거래대금</th>'
                  '<th class="nxt-header">NXT선</th>'
                  '</tr></thead>')
    elif is_red:
        header = ('<thead><tr>'
                  '<th>Ticker</th><th>Name</th>'
                  '<th class="nxt-header">NXT선</th>'
                  '</tr></thead>')
    else:
        header = ('<thead><tr>'
                  '<th>Ticker</th><th>Name</th>'
                  '<th class="nxt-header">NXT선</th>'
                  '</tr></thead>')

    return (f'<table class="styled-table">{header}'
            f'<tbody>{"".join(rows)}</tbody></table>')


def build_nxt_map(text):
    """MOM/LIME/GREEN/SPOT 블록에서 NXT/선 거래가능 티커들을 dict로 반환"""
    nxt_map = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        
        nxt_val = ""
        # 구형식 호환
        match = re.search(r'NXT:(NXT선|NXT|선)', line)
        if match:
            nxt_val = match.group(1)
        else:
            # 신형식: 마지막 컬럼
            parts = re.split(r'[\t|]', line)
            last = parts[-1].strip()
            if last in ('NXT', '선', 'NXT선'):
                nxt_val = last
                
        if nxt_val:
            ticker = re.split(r'[\t|]', line)[0].strip()
            ticker_clean = re.sub(r'\*+', '', ticker).strip()
            if ticker_clean:
                nxt_map[ticker_clean] = nxt_val
    return nxt_map


def update_leader_tracking(leader_block):
    """
    주도주 블록에서 종목 추출 → leader_tracking.json에 누적 저장.
    - 최초 등장 날짜(added_date) 기록
    - 14일(2주) 이상 지난 항목은 자동 삭제
    - 동일 ticker 중복 추가 안 함 (날짜 갱신 없이 최초 날짜 유지)
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    # 기존 데이터 로드
    if LEADER_TRACKING_JSON.exists():
        try:
            tracking = json.loads(LEADER_TRACKING_JSON.read_text(encoding="utf-8"))
        except Exception:
            tracking = {}
    else:
        tracking = {}

    # 14일 지난 항목 제거
    tracking = {k: v for k, v in tracking.items() if v.get("added_date", "") >= cutoff}

    # 오늘 종가 JSON 로드 (base_close 저장용)
    today_close_dict = {}
    close_file = LEADER_TRACKING_JSON.parent.parent / "0txt" / "kor_today_close.json"
    if close_file.exists():
        try:
            with open(close_file, "r", encoding="utf-8") as f:
                today_close_dict = json.load(f)
        except Exception:
            pass

    # 누적등락률 -15% 이하 항목 제거
    cum_remove = [
        tk for tk, info in tracking.items()
        if (info.get("base_close") and today_close_dict.get(tk)
            and float(info["base_close"]) > 0
            and (float(today_close_dict[tk]) / float(info["base_close"]) - 1) * 100 <= -15.0)
    ]
    for tk in cum_remove:
        del tracking[tk]

    # 오늘 주도주 파싱
    for line in leader_block.splitlines():
        cols = [c.strip() for c in line.split('\t')]
        if len(cols) < 3:
            continue
        ticker = re.sub(r'\*+', '', cols[0]).strip()
        if not ticker or ticker.startswith('Ticker') or all(c in '-=' for c in ticker):
            continue
        name      = cols[2] if len(cols) > 2 else ''
        pct       = cols[1] if len(cols) > 1 else '-'
        tv_str    = cols[3] if len(cols) > 3 else '-'
        # cols[4]=closest_ma, cols[5]=sco, cols[6]=NXT
        sco_val   = cols[5] if len(cols) > 5 else '-'
        nxt_val   = cols[6].strip() if len(cols) > 6 else ''

        if ticker not in tracking:
            # 신규 등록: base_close 저장
            base_close = today_close_dict.get(ticker, None)
            tracking[ticker] = {
                "name": name,
                "sco": sco_val,
                "added_date": today_str,
                "base_close": base_close,   # 등록일 종가 (base)
                "nxt": nxt_val,
                "tv_str": tv_str,
                "pct_history": {},   # 날짜별 등락률 기록
            }
        # 오늘 등락률 업데이트
        tracking[ticker]["pct_history"][today_str] = pct
        # sco, tv_str, nxt 항상 최신값으로 갱신
        tracking[ticker]["sco"] = sco_val
        tracking[ticker]["tv_str"] = tv_str
        tracking[ticker]["nxt"] = nxt_val
        if not tracking[ticker].get("name"):
            tracking[ticker]["name"] = name

    # 저장
    try:
        LEADER_TRACKING_JSON.write_text(
            json.dumps(tracking, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠ leader_tracking.json 저장 실패: {e}")

    return tracking


def make_leader_tracking_table(tracking: dict, high52w_set=None) -> str:
    """
    2주 이내 주도주 트래킹 테이블 HTML 생성.
    컬럼: Ticker | Name | SCO | 등록시 등락률 | 오늘 등락률 | 누적 등락률 | 당일합계 | N일합계 | 경과일
    """
    if not tracking:
        return '<p style="color:#95a5a6; margin-left:10px;">(트래킹 종목 없음)</p>'
    if high52w_set is None:
        high52w_set = set()

    def pct_cell(pct_str):
        try:
            val = float(pct_str.replace('%', '').replace('+', ''))
            cls = 'sig-up' if val > 0 else ('sig-down' if val < 0 else '')
            return f'<td class="{cls}">{html.escape(pct_str)}</td>'
        except Exception:
            return f'<td style="color:#aaa;">{html.escape(pct_str)}</td>'

    def cum_pct_cell(base_close, today_close):
        try:
            if base_close and today_close and float(base_close) > 0:
                cum = (float(today_close) / float(base_close) - 1) * 100
                sign = '+' if cum >= 0 else ''
                cls = 'sig-up' if cum > 0 else ('sig-down' if cum < 0 else '')
                return f'<td class="{cls}"><b>{sign}{cum:.2f}%</b></td>'
        except Exception:
            pass
        return '<td style="color:#aaa;">-</td>'

    def investor_cell(val, label=""):
        if val is None:
            return '<td style="color:#aaa;font-size:11px;">-</td>'
        color = "#c0392b" if val > 0 else ("#2471a3" if val < 0 else "#888")
        sign = "+" if val > 0 else ""
        text = f"{sign}{val:,.0f}억"
        if label:
            text += f'<span style="color:#aaa;font-size:10px;"> ({label})</span>'
        return f'<td style="color:{color};font-size:12px;font-weight:bold;">{text}</td>'

    rows_html = []

    # 등록일 기준 최신순 정렬
    sorted_items = sorted(tracking.items(), key=lambda x: x[1].get("added_date", ""), reverse=True)

    # kor_today_pct.json 로드
    today_pct_dict = {}
    pct_file = LEADER_TRACKING_JSON.parent.parent / "0txt" / "kor_today_pct.json"
    if pct_file.exists():
        try:
            with open(pct_file, "r", encoding="utf-8") as f:
                today_pct_dict = json.load(f)
        except Exception:
            pass

    # kor_today_close.json 로드 (누적 등락률 계산용)
    today_close_dict = {}
    close_file = LEADER_TRACKING_JSON.parent.parent / "0txt" / "kor_today_close.json"
    if close_file.exists():
        try:
            with open(close_file, "r", encoding="utf-8") as f:
                today_close_dict = json.load(f)
        except Exception:
            pass

    # 외인/기관 합산 데이터 로드
    investor_dict = {}
    if INVESTOR_FILE.exists():
        try:
            investor_dict = json.loads(INVESTOR_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    for ticker, info in sorted_items:
        added_date  = info.get("added_date", "-")
        name        = info.get("name", "")
        sco_val     = info.get("sco", "-")
        pct_history = info.get("pct_history", {})
        base_close  = info.get("base_close", None)

        # 경과일
        try:
            days_passed = (datetime.now() - datetime.strptime(added_date, "%Y-%m-%d")).days
        except Exception:
            days_passed = 0

        # 2주 남은 일수 표시용 색상
        if days_passed <= 5:
            days_color = "#27ae60"
        elif days_passed <= 10:
            days_color = "#e67e22"
        else:
            days_color = "#e74c3c"

        # 등록 당일 등락률
        first_pct = pct_history.get(added_date, "-")

        # 오늘 등락률 (1순위: kor_today_pct.json, 2순위: pct_history 최신값)
        today_pct = today_pct_dict.get(ticker, "-")
        if today_pct == "-" and pct_history:
            latest_date = max(pct_history.keys())
            today_pct = pct_history.get(latest_date, "-")

        # 누적 등락률: base_close vs 오늘 종가
        today_close = today_close_dict.get(ticker, None)

        # 외인/기관 합산
        ticker6 = ticker.zfill(6)
        inv = investor_dict.get(ticker6, {})
        inv_today = inv.get("today")
        inv_ndays = inv.get("ndays")
        inv_days  = inv.get("days", days_passed)

        expire_in = 14 - days_passed

        # sco 색상
        try:
            sco_num = float(str(sco_val))
            sco_color = '#27ae60' if sco_num >= 11 else ('#e67e22' if sco_num >= 8 else '#e74c3c')
        except Exception:
            sco_color = '#888'

        nxt_val = info.get("nxt", "")
        nxt_html = f'<span class="{'nxt-badge-both' if nxt_val == 'NXT선' else 'nxt-badge'}\">{nxt_val}</span>' if nxt_val in ('NXT', '선', 'NXT선') else ''

        tv_str_val = info.get("tv_str", "-")
        try:
            tv_num_kr = int(tv_str_val.replace(',', '').replace('억', '').strip())
            tv_color_kr = '#e74c3c' if tv_num_kr >= 1000 else '#222'
            tv_weight_kr = 'bold' if tv_num_kr >= 1000 else 'normal'
        except Exception:
            tv_color_kr = '#222'
            tv_weight_kr = 'normal'

        # 52주 신고가 근접 → 이름 빨간색
        _ticker6 = ticker.zfill(6)
        _name_html = (f'<span style="color:#e74c3c;font-weight:bold;">{html.escape(name)}</span>'
                      if _ticker6 in high52w_set else html.escape(name))

        rows_html.append(
            f'<tr>'
            f'<td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker)}</td>'
            f'<td class="name-col">{_name_html}</td>'
            f'<td style="color:{sco_color};font-weight:bold;text-align:center;">{html.escape(str(sco_val))}</td>'
            f'{pct_cell(first_pct)}'
            f'{pct_cell(today_pct)}'
            f'{cum_pct_cell(base_close, today_close)}'
            f'{investor_cell(inv_today)}'
            f'{investor_cell(inv_ndays, f"{inv_days}일")}'
            f'<td style="color:{days_color};font-weight:bold;font-size:12px;">{days_passed}일 경과 (D-{expire_in})</td>'
            f'<td style="color:{tv_color_kr};font-size:12px;font-weight:{tv_weight_kr};">{html.escape(tv_str_val)}</td>'
            f'<td class="nxt-cell">{nxt_html}</td>'
            f'</tr>'
        )

    if not rows_html:
        return '<p style="color:#95a5a6; margin-left:10px;">(트래킹 종목 없음)</p>'

    header = (
        '<thead><tr>'
        '<th class="sortable" data-col="0">Ticker</th>'
        '<th class="sortable" data-col="1">Name</th>'
        '<th class="sortable" data-col="2">SCO</th>'
        '<th class="sortable" data-col="3">등록시 등락률</th>'
        '<th class="sortable" data-col="4">오늘 등락률</th>'
        '<th class="sortable" data-col="5">누적 등락률</th>'
        '<th class="sortable" data-col="6">당일합계</th>'
        '<th class="sortable" data-col="7">N일합계</th>'
        '<th class="sortable" data-col="8">경과</th>'
        '<th class="sortable" data-col="9">거래대금</th>'
        '<th class="nxt-header">NXT선</th>'
        '</tr></thead>'
    )
    return (
        f'<table class="styled-table" id="leader-tracking-table">{header}'
        f'<tbody>{"".join(rows_html)}</tbody></table>'
    )


def make_leader_table(leader_block, high52w_set=None):
    """
    주도주 블록 파싱 및 HTML 테이블 렌더링.
    출력 포맷: ticker\t등락%\tname\t거래대금(억)\t이평\tNXT
    """
    if high52w_set is None:
        high52w_set = set()
    data_lines = [l for l in leader_block.splitlines()
                  if l.strip()
                  and not all(c in '-=' for c in l.strip())
                  and '없음' not in l
                  and '【' not in l]
    if not data_lines:
        return '<p style="color:#95a5a6; margin-left:10px;">(없음)</p>'

    rows = []
    for line in data_lines:
        cols = [c.strip() for c in line.split('\t')]
        if len(cols) < 3:
            continue
        ticker  = cols[0]
        clean_code = ticker.replace('**', '').strip()
        clean_code6 = clean_code.zfill(6)
        pct     = cols[1] if len(cols) > 1 else '-'
        name    = cols[2] if len(cols) > 2 else ''
        tv_str  = cols[3] if len(cols) > 3 else '-'
        ma_str  = cols[4] if len(cols) > 4 else '-'
        nxt_tag = cols[6].strip() if len(cols) > 6 else ''
        nxt_html = f'<span class="{'nxt-badge-both' if nxt_tag == 'NXT선' else 'nxt-badge'}\">{nxt_tag}</span>' if nxt_tag in ('NXT', '선', 'NXT선') else ''
        try:
            val = float(pct.replace('%', '').replace('+', ''))
            pct_cls = 'sig-up' if val > 0 else ('sig-down' if val < 0 else '')
        except:
            pct_cls = ''
        # 이평 컬럼 색상
        ma_color = {'MA10': '#3498db', 'MA20': '#9b59b6', 'MA60': '#e67e22'}.get(ma_str, '#555')
        ma_cell = (f'<td><span style="background:{ma_color};color:white;padding:2px 6px;'
                   f'border-radius:4px;font-size:11px;font-weight:bold;">{html.escape(ma_str)}</span></td>')
        # 거래대금 색상: 1000억 이상이면 빨강, 기본 검정
        try:
            tv_num_l = int(re.sub(r'[^\d]', '', tv_str))
            tv_color_l = '#e74c3c' if tv_num_l >= 1000 else '#222'
            tv_weight_l = 'bold' if tv_num_l >= 1000 else 'normal'
        except:
            tv_color_l = '#222'
            tv_weight_l = 'normal'
        # 52주 신고가 근접 → 이름 빨간색
        name_html = (f'<span style="color:#e74c3c;font-weight:bold;">{html.escape(name)}</span>'
                     if clean_code6 in high52w_set else html.escape(name))

        rows.append(
            f'<tr style="background:#fffde7;">'
            f'<td class="narrow" data-code="{html.escape(clean_code)}" data-name="{html.escape(name)}">{html.escape(ticker)}</td>'
            f'<td class="name-col">{name_html}</td>'
            f'<td class="{pct_cls}">{html.escape(pct)}</td>'
            f'{ma_cell}'
            f'<td style="color:{tv_color_l};font-size:12px;font-weight:{tv_weight_l};">{html.escape(tv_str)}</td>'
            f'<td class="nxt-cell">{nxt_html}</td>'
            f'</tr>'
        )

    if not rows:
        return '<p style="color:#95a5a6; margin-left:10px;">(없음)</p>'

    header = ('<thead><tr>'
              '<th>Ticker</th><th>Name</th><th>등락률(%)</th>'
              '<th>이평</th><th>거래대금</th><th class="nxt-header">NXT선</th>'
              '</tr></thead>')
    return (f'<table class="styled-table">{header}'
            f'<tbody>{"".join(rows)}</tbody></table>')


def make_unified_signal_table(spot_raw, mom_block, lime_block, green_block, gann_fire_set=None, gann_info_dict=None, high52w_set=None):
    """SPOT/MOM/LIME/GREEN을 kor_etf 스타일 통합 랭킹 테이블로 렌더링.
    새 라인 포맷 (탭구분):
      ticker  sig  name  등락%  거래대금  위치  sco  rsi  ma5  ma10  ma20  ma60  ma120  score  NXT
    """
    if gann_fire_set is None:
        gann_fire_set = set()
    if gann_info_dict is None:
        gann_info_dict = {}
    if high52w_set is None:
        high52w_set = set()
    badge_css = {
        'SPOT': 'background:#e74c3c;color:white;',
        'MOM':  'background:#e67e22;color:white;',
        'LIME': 'background:#2ecc71;color:white;',
        'GREEN':'background:#27ae60;color:white;',
        'GANN': 'background:#2980b9;color:white;',
    }

    def _ma_cell(val):
        cls = 'sig-up' if val == '상' else ('sig-down' if val == '하' else '')
        return f'<td class="{cls}">{html.escape(str(val))}</td>'

    def _pos_cell(val):
        if val == '정배':
            return '<td class="sig-jung">정배</td>'
        elif val == '역배':
            return '<td class="sig-yeok">역배</td>'
        return '<td>-</td>'

    def _parse_block(block, default_sig):
        rows = []
        for line in block.splitlines():
            line = line.strip()
            if not line or all(c in '-=' for c in line) or '없음' in line or '【' in line:
                continue
            cols = [c.strip() for c in line.split('\t')]
            if len(cols) < 3:
                continue
            ticker = cols[0]
            sig    = cols[1] if len(cols) > 1 else default_sig
            name   = cols[2] if len(cols) > 2 else ''
            pct    = cols[3] if len(cols) > 3 else '-'
            tv_str = cols[4] if len(cols) > 4 else '-'
            pos    = cols[5] if len(cols) > 5 else '-'
            sco    = cols[6] if len(cols) > 6 else '-'
            rsi_v  = cols[7] if len(cols) > 7 else '-'
            ma5d   = cols[8] if len(cols) > 8 else '-'
            ma10d  = cols[9] if len(cols) > 9 else '-'
            ma20d  = cols[10] if len(cols) > 10 else '-'
            ma60d  = cols[11] if len(cols) > 11 else '-'
            ma120d = cols[12] if len(cols) > 12 else '-'
            score  = cols[13] if len(cols) > 13 else '-'
            nxt_tag= cols[14] if len(cols) > 14 else ''
            try:
                tv_int = int(re.sub(r'[^\d]', '', tv_str))
            except:
                tv_int = 0
            rows.append({
                'ticker': ticker, 'sig': sig, 'name': name,
                'pct': pct, 'tv_str': tv_str, 'tv_int': tv_int,
                'pos': pos, 'sco': sco, 'rsi': rsi_v,
                'ma5': ma5d, 'ma10': ma10d, 'ma20': ma20d,
                'ma60': ma60d, 'ma120': ma120d,
                'score': score, 'nxt': nxt_tag,
            })
        return rows

    sig_order = {'SPOT': 0, 'MOM': 1, 'LIME': 2, 'GREEN': 3, 'GANN': 4}
    all_rows = []
    spot_block = '\n'.join(spot_raw) if isinstance(spot_raw, list) else spot_raw
    for block, sig in [(spot_block, 'SPOT'), (mom_block, 'MOM'),
                       (lime_block, 'LIME'), (green_block, 'GREEN')]:
        all_rows.extend(_parse_block(block, sig))

    # 🔥 GANN 신호: gann_fire_set에 있는 티커를 기존 행에 GANN 병기 또는 별도 행 추가
    # 기존 신호에 없는 GANN 단독 종목은 별도 행으로 추가 (상세정보 gann_info_dict 활용)
    existing_tickers = {re.sub(r'\*+', '', r['ticker']).strip().zfill(6) for r in all_rows}
    for t6 in sorted(gann_fire_set):
        if t6 not in existing_tickers:
            info = gann_info_dict.get(t6, {})
            all_rows.append({
                'ticker':   t6,
                'sig':      'GANN',
                'name':     info.get('name', ''),
                'pct':      info.get('pct', '-'),
                'gann_gap': info.get('gann_gap', None),
                'tv_str':   info.get('tv_str', '-'),
                'tv_int':   info.get('tv_int', 0),
                'pos': '-', 'sco': '-',
                'rsi': '-', 'ma5': '-', 'ma10': '-', 'ma20': '-',
                'ma60': '-', 'ma120': '-', 'score': '-',
                'nxt':      info.get('nxt', ''),
            })

    if not all_rows:
        return '<p style="color:#95a5a6; margin-left:10px;">(없음)</p>'

    all_rows.sort(key=lambda r: (sig_order.get(r['sig'], 9), -r['tv_int']))

    html_rows = []
    for r in all_rows:
        sig = r['sig']
        bstyle = badge_css.get(sig, '')
        badge = (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                 f'font-size:11px;font-weight:bold;{bstyle}">{sig}</span>')

        # 🔥 현재 행 티커가 GANN 신호이면 GANN badge 병기
        ticker_clean6 = re.sub(r'\*+', '', r['ticker']).strip().zfill(6)
        if ticker_clean6 in gann_fire_set and sig != 'GANN':
            gann_bstyle = badge_css['GANN']
            gann_badge = (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                          f'font-size:11px;font-weight:bold;{gann_bstyle}">GANN</span>')
            badge = badge + '&nbsp;' + gann_badge

        try:
            val = float(r['pct'].replace('%','').replace('+',''))
            pct_cls = 'sig-up' if val > 0 else ('sig-down' if val < 0 else '')
        except:
            pct_cls = ''

        if sig == 'GANN' and r.get('gann_gap') is not None:
            gap = r['gann_gap']
            gap_cls = 'sig-up' if gap > 0 else ('sig-down' if gap < 0 else '')
            pct_cell = f'<td class="{gap_cls}">{gap:+.1f}%</td>'
        else:
            pct_cell = f'<td class="{pct_cls}">{html.escape(r["pct"])}</td>'

        nxt_html = f'<span class="{'nxt-badge-both' if r["nxt"] == 'NXT선' else 'nxt-badge'}\">{r["nxt"]}</span>' if r['nxt'] in ('NXT', '선', 'NXT선') else ''
        if sig == 'SPOT':
            row_bg = ' style="background:#fffde7;"'
        elif sig == 'GANN':
            row_bg = ' style="background:#eaf4fb;"'
        else:
            row_bg = ''

        # 거래대금 색상: 1000억 이상이면 빨강, 기본 검정
        try:
            tv_num = int(re.sub(r'[^\d]', '', r['tv_str']))
            tv_color = '#e74c3c' if tv_num >= 1000 else '#222'
        except:
            tv_color = '#222'
        # 52주 신고가 근접 → 이름 빨간색
        _u_name_html = (f'<span style="color:#e74c3c;font-weight:bold;">{html.escape(r["name"])}</span>'
                        if ticker_clean6 in high52w_set else html.escape(r["name"]))

        html_rows.append(
            f'<tr{row_bg}>'
            f'<td class="narrow" data-code="{html.escape(ticker_clean6)}" data-name="{html.escape(r["name"])}">{html.escape(r["ticker"])}</td>'
            f'<td class="name-col">{_u_name_html}</td>'
            f'<td>{badge}</td>'
            f'{pct_cell}'
            f'<td style="color:{tv_color};font-size:12px;font-weight:{"bold" if tv_num >= 1000 else "normal"};">{html.escape(r["tv_str"])}</td>'
            f'<td class="nxt-cell">{nxt_html}</td>'
            f'</tr>'
        )

    header = ('<thead><tr>'
              '<th class="sortable" data-col="0">Ticker</th>'
              '<th class="sortable" data-col="1">Name</th>'
              '<th class="sortable" data-col="2">신호</th>'
              '<th class="sortable" data-col="3">등락률(Gap)</th>'
              '<th class="sortable" data-col="4">거래대금</th>'
              '<th class="nxt-header">NXT선</th>'
              '</tr></thead>')
    return (f'<table class="styled-table" id="signal-table">{header}'
            f'<tbody>{"".join(html_rows)}</tbody></table>')


def parse_total_count(stats_lines):
    for line in stats_lines:
        match = re.search(r'전체 종목:\s*([\d,]+)개', line)
        if match:
            return int(match.group(1).replace(',', ''))
    return 0


def build_red_purple_signal_table(red_block, total_count=0, nxt_lookup=None):
    """RED/PURPLE short candidates: futures-eligible names only, RED first."""
    if nxt_lookup is None:
        nxt_lookup = {}
    rows = []
    sig_order = {'RED': 0, 'PURPLE': 1}

    for line in red_block.splitlines():
        line = line.strip()
        if not line or all(c in '-=' for c in line) or '없음' in line or '【' in line:
            continue

        cols = [c.strip() for c in line.split('\t')]
        if len(cols) < 4:
            continue

        ticker = cols[0]
        ticker6 = re.sub(r'\*+', '', ticker).strip().zfill(6)
        sig = cols[1].upper()
        name = cols[2]
        tv_str = cols[3]
        nxt = cols[4] if len(cols) > 4 else nxt_lookup.get(ticker6, '')
        if sig not in ('RED', 'PURPLE') or nxt not in ('선', 'NXT선'):
            continue

        try:
            tv_int = int(re.sub(r'[^\d]', '', tv_str))
        except Exception:
            tv_int = 0

        rows.append({
            'ticker': ticker,
            'ticker6': ticker6,
            'sig': sig,
            'name': name,
            'tv_str': tv_str,
            'tv_int': tv_int,
            'nxt': nxt,
        })

    rows.sort(key=lambda r: (sig_order.get(r['sig'], 9), -r['tv_int']))

    red_count = sum(1 for r in rows if r['sig'] == 'RED')
    purple_count = sum(1 for r in rows if r['sig'] == 'PURPLE')
    total_display = f'{total_count:,}' if total_count else '-'
    title = f'📊 신호 종목 랭킹 (RED: {red_count}, PURPLE: {purple_count} / {total_display})'

    html_rows = []
    for r in rows:
        badge_color = '#c0392b' if r['sig'] == 'RED' else '#8e44ad'
        badge = (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                 f'font-size:11px;font-weight:bold;background:{badge_color};color:white;">{r["sig"]}</span>')
        nxt_cls = 'nxt-badge-both' if r['nxt'] == 'NXT선' else 'nxt-badge'
        nxt_html = f'<span class="{nxt_cls}">{r["nxt"]}</span>'
        html_rows.append(
            '<tr>'
            f'<td class="narrow" data-code="{html.escape(r["ticker6"])}" data-name="{html.escape(r["name"])}">{html.escape(r["ticker"])}</td>'
            f'<td class="name-col">{html.escape(r["name"])}</td>'
            f'<td>{badge}</td>'
            '<td style="color:#aaa;">-</td>'
            f'<td style="color:#888;font-size:12px;">{html.escape(r["tv_str"])}</td>'
            f'<td class="nxt-cell">{nxt_html}</td>'
            '</tr>'
        )

    if not html_rows:
        html_rows.append('<tr><td colspan="6" style="color:#95a5a6;text-align:center;">RED/PURPLE 선물 가능 종목 없음</td></tr>')

    header = ('<thead><tr>'
              '<th class="sortable" data-col="0">Ticker</th>'
              '<th class="sortable" data-col="1">Name</th>'
              '<th class="sortable" data-col="2">신호</th>'
              '<th class="sortable" data-col="3">등락률(Gap)</th>'
              '<th class="sortable" data-col="4">거래대금</th>'
              '<th class="nxt-header">NXT선</th>'
              '</tr></thead>')
    table = (f'<table class="styled-table" id="red-purple-signal-table">{header}'
             f'<tbody>{"".join(html_rows)}</tbody></table>')
    return title, table


def parse_top30_table(text, nxt_map=None, gann_fire_set=None, high52w_set=None, mktcap_map=None):
    """Parse the tab-separated Top30 block and produce a proper HTML table.
    nxt_map: NXT 거래 가능 티커 맵
    gann_fire_set: 🔥 GANN 불기둥 신호 티커 집합
    """
    if gann_fire_set is None:
        gann_fire_set = set()
    if high52w_set is None:
        high52w_set = set()
    if mktcap_map is None:
        mktcap_map = {}
    if not text or text.strip().startswith("("):
        return f'<p>{html.escape(text)}</p>'

    lines = text.strip().splitlines()
    data_lines = [l for l in lines if not all(c in '-=' for c in l.strip()) and l.strip()]
    if not data_lines:
        return '<p>(Top30 데이터 없음)</p>'

    html_output = ['<table class="styled-table" id="top30-table">']
    # Fixed header matching kor_150.html
    html_output.append(
        '<thead><tr>'
        '<th class="sortable" data-col="0">Ticker</th>'
        '<th class="sortable" data-col="1">Name</th>'
        '<th class="sortable" data-col="2">Sig_sco</th>'
        '<th class="sortable" data-col="3">등락률</th>'
        '<th class="sortable" data-col="4">Final_sco</th>'
        '<th class="sortable" data-col="5">NewSig</th>'
        '<th class="sortable" data-col="6">거래대금</th>'
        '<th class="sortable" data-col="7">시총(억)</th>'
        '<th class="nxt-header">NXT선</th>'
        '</tr></thead>'
    )
    html_output.append('<tbody>')

    for line in data_lines:
        # Skip the header line from txt
        if 'Ticker' in line or 'Signal_sco' in line or '수익률' in line:
            continue
        # Split by tab
        cols = [c.strip() for c in line.split('\t')]
        # Fallback: split by 2+ spaces
        if len(cols) < 4:
            cols = [c.strip() for c in re.split(r'  +', line)]
        if len(cols) < 4:
            continue

        ticker    = html.escape(cols[0]) if len(cols) > 0 else ''
        name      = html.escape(cols[1]) if len(cols) > 1 else ''
        sig_sco   = html.escape(cols[2]) if len(cols) > 2 else ''
        yield_pct = html.escape(cols[3]) if len(cols) > 3 else ''
        final_sco = html.escape(cols[4]) if len(cols) > 4 else ''
        newsig    = cols[5] if len(cols) > 5 else '-'
        # col[6] = fire (0 or 1), col[7] = 거래대금 (txt에 추가된 컬럼)
        fire_raw  = cols[6].strip() if len(cols) > 6 else '0'
        fire_val  = 1 if fire_raw == '1' else 0
        tv_str_top = cols[7].strip() if len(cols) > 7 else '-'
        try:
            tv_num_top30 = int(tv_str_top.replace(',', '').replace('억', '').strip())
            tv_color_top30 = '#e74c3c' if tv_num_top30 >= 1000 else '#222'
            tv_weight_top30 = 'bold' if tv_num_top30 >= 1000 else 'normal'
        except Exception:
            tv_color_top30 = '#222'
            tv_weight_top30 = 'normal'

        # NXT: Top30 원본 컬럼을 우선 사용하고, 없으면 신호 블록에서 교차 조회한다.
        ticker_clean = re.sub(r'\*+', '', cols[0]).strip() if cols else ''
        ticker_clean6 = ticker_clean.zfill(6)
        nxt_val = cols[8].strip() if len(cols) > 8 else ""
        if nxt_val not in ('NXT', '선', 'NXT선'):
            nxt_val = nxt_map.get(ticker_clean6, "") if nxt_map else ""
        nxt_html = f'<span class="{'nxt-badge-both' if nxt_val == 'NXT선' else 'nxt-badge'}\">{nxt_val}</span>' if nxt_val in ('NXT', '선', 'NXT선') else ''

        # 🔥 GANN 신호 병기: fire 컬럼 또는 gann_fire_set 둘 다 체크
        is_gann = (fire_val == 1) or (ticker_clean6 in gann_fire_set)
        gann_badge = ('<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
                      'font-size:11px;font-weight:bold;background:#2980b9;color:white;">🔥GANN</span>'
                      if is_gann else '')

        # NewSig 배지 스타일 매핑 (신호 유형별 색상)
        _newsig_badge_css = {
            'SPOT':  'background:#e74c3c;color:white;',
            'MOM':   'background:#e67e22;color:white;',
            'LIME':  'background:#2ecc71;color:white;',
            'GREEN': 'background:#27ae60;color:white;',
            'GANN':  'background:#2980b9;color:white;',
            'RED':   'background:#c0392b;color:white;',
        }

        def _make_sig_badges(raw_newsig):
            """NewSig 문자열에서 각 신호 키워드를 찾아 배지 HTML로 변환"""
            # 신호가 없거나 '-'이면 그대로 반환
            raw_stripped = raw_newsig.strip()
            if not raw_stripped or raw_stripped == '-':
                return '<span style="color:#aaa;">-</span>'

            # 여러 신호가 포함될 수 있으므로 순서대로 찾아서 배지 생성
            sig_keys = ['SPOT', 'MOM', 'LIME', 'GREEN', 'GANN', 'RED']
            badges = []
            remaining = raw_stripped
            found_any = False
            for sig_key in sig_keys:
                if sig_key in remaining:
                    bstyle = _newsig_badge_css.get(sig_key, 'background:#888;color:white;')
                    badges.append(
                        f'<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
                        f'font-size:11px;font-weight:bold;{bstyle}">{sig_key}</span>'
                    )
                    found_any = True
            if not found_any:
                # 알 수 없는 신호는 회색 배지
                return (f'<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
                        f'font-size:11px;font-weight:bold;background:#888;color:white;">'
                        f'{html.escape(raw_stripped)}</span>')
            return '&nbsp;'.join(badges)

        newsig_html = _make_sig_badges(newsig) + ('&nbsp;' + gann_badge if is_gann else '')

        # Color-code 등락률
        try:
            val = float(yield_pct.replace('%', ''))
            if val > 0:
                yield_cell = f'<td class="yield-col up">{yield_pct}</td>'
            elif val < 0:
                yield_cell = f'<td class="yield-col down">{yield_pct}</td>'
            else:
                yield_cell = f'<td class="yield-col">{yield_pct}</td>'
        except ValueError:
            yield_cell = f'<td class="yield-col">{yield_pct}</td>'

        ticker_cls = 'narrow'
        # 52주 신고가 근접 → 이름 빨간색
        _t30_name_html = (f'<span style="color:#e74c3c;font-weight:bold;">{name}</span>'
                          if ticker_clean6 in high52w_set else name)
        # 시총 조회 (kr.csv F열 기준, 억 단위 표시)
        mktcap_raw = mktcap_map.get(ticker_clean6, 0)
        try:
            mktcap_uk = int(float(str(mktcap_raw).replace(',', '').strip()) / 100_000_000)
            mktcap_str = f'{mktcap_uk:,}억'
            mktcap_color = '#e74c3c' if mktcap_uk >= 10000 else '#555'
        except Exception:
            mktcap_str = '-'
            mktcap_color = '#aaa'

        row = (
            f'<tr>'
            f'<td class="{ticker_cls}" data-code="{ticker_clean6}" data-name="{name}">{ticker}</td>'
            f'<td class="name-col">{_t30_name_html}</td>'
            f'<td>{sig_sco}</td>'
            f'{yield_cell}'
            f'<td>{final_sco}</td>'
            f'<td>{newsig_html}</td>'
            f'<td style="color:{tv_color_top30};font-size:12px;font-weight:{tv_weight_top30};">{html.escape(tv_str_top)}</td>'
            f'<td style="color:{mktcap_color};font-size:12px;">{mktcap_str}</td>'
            f'<td class="nxt-cell">{nxt_html}</td>'
            f'</tr>'
        )
        html_output.append(row)

    html_output.append('</tbody></table>')
    return '\n'.join(html_output)


def main():
    text = REPORT_TXT.read_text(encoding="utf-8", errors="replace") if REPORT_TXT.exists() else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 🔥 SGDDEMA 불기둥 신호 티커 세트 + 상세정보 로드
    gann_fire_set  = set()
    gann_info_dict = {}   # { '008770': {name, pct, tv_str, tv_int, nxt}, ... }
    if GANN_FIRE_JSON.exists():
        try:
            gann_data = json.loads(GANN_FIRE_JSON.read_text(encoding='utf-8'))
            gann_fire_set  = set(str(t).strip().zfill(6) for t in gann_data.get('tickers', []))
            raw_info = gann_data.get('info', {})
            for t6, v in raw_info.items():
                gann_info_dict[str(t6).strip().zfill(6)] = v
        except Exception:
            gann_fire_set  = set()
            gann_info_dict = {}

    # ✅ 52주 신고가 95% 이상 종목 set 로드 (이름 빨간색 표시용)
    high52w_set = set()
    if HIGH52W_JSON.exists():
        try:
            high52w_set = set(json.loads(HIGH52W_JSON.read_text(encoding='utf-8')))
        except Exception:
            pass

    # ✅ ALL 가능한 섹션 헤더들 (어느 하나라도 나오면 추출 중단)
    ALL_MARKERS = [
        "【💥 SPOT", "【MOM(모멘텀)", "【LIME 신호", "【GREEN 신호", 
        "【RED / PURPLE", "【📊 주도주", "요약:", "✓ 파일 저장 완료!", "📊 SCO 기준 종목 분포"
    ]

    # Clean redundant titles
    top30_raw = extract_block(
        text,
        "📊 종합 Top30 (Final_score 기준)",
        [m for m in ALL_MARKERS if "종합 Top30" not in m]
    ) or "(Top30 데이터 없음)"
    top30_block = "\n".join([l for l in top30_raw.splitlines() if "종합 Top30" not in l]).strip()

    mom_raw = extract_block(
        text,
        "【MOM(모멘텀) 돌파 종목",
        [m for m in ALL_MARKERS if "MOM(모멘텀)" not in m]
    ) or "(MOM 종목 없음)"
    mom_block = "\n".join([l for l in mom_raw.splitlines() if "MOM(모멘텀)" not in l]).strip()

    # 3. LIME
    lime_raw = extract_block(
        text,
        "【LIME 신호 종목 + spot2】",
        [m for m in ALL_MARKERS if "LIME 신호" not in m]
    ) or "(LIME 종목 없음)"
    lime_block = "\n".join([l for l in lime_raw.splitlines() if "LIME 신호" not in l]).strip()

    # 4. GREEN
    green_raw = extract_block(
        text,
        "【GREEN 신호 종목 + spot2】",
        [m for m in ALL_MARKERS if "GREEN 신호" not in m]
    ) or "(GREEN 종목 없음)"
    green_block = "\n".join([l for l in green_raw.splitlines() if "GREEN 신호" not in l]).strip()

    # 5. RED
    red_raw = extract_block(
        text,
        "【RED / PURPLE 신호 종목",
        [m for m in ALL_MARKERS if "RED / PURPLE" not in m]
    ) or "(RED 종목 없음)"
    red_block = "\n".join([l for l in red_raw.splitlines() if "RED / PURPLE" not in l]).strip()

    # 5.3 주도주
    leader_raw = extract_block(
        text,
        "【📊 주도주",
        [m for m in ALL_MARKERS if "주도주" not in m]
    ) or ""
    leader_block = "\n".join([l for l in leader_raw.splitlines()
                               if l.strip() and "【" not in l]).strip()

    # ✅ 주도주 트래킹 업데이트 (2주간 누적)
    tracking_data = update_leader_tracking(leader_block)

    # 5.5 SPOT
    spot_raw = extract_block(
        text,
        "【💥 SPOT 신호 종목",
        [m for m in ALL_MARKERS if "SPOT" not in m]
    ) or ""
    spot_lines = [l for l in spot_raw.splitlines()
                  if l.strip() and "【" not in l]

    
    # 6. Stats — sco 분포 3줄만 추출
    stats_raw = extract_block(
        text,
        "📊 SCO 기준 종목 분포",
        ["[실행 시간]"]
    ) or ""
    # sco >= / 0 <= / sco < 세 줄만 추출
    stats_lines = [l.strip() for l in stats_raw.splitlines()
                   if l.strip().startswith('sco') or l.strip().startswith('0 <=')]
    total_count = parse_total_count([l.strip() for l in stats_raw.splitlines()])
    if stats_lines:
        # 퍼센트 + 개수 추출 (예: "sco >= 12: 387개 (36.6%)" → "36.6%", 387)
        pct_list = []
        cnt_list = []
        for sl in stats_lines:
            m = re.search(r'\((\d+\.?\d*%)\)', sl)
            pct_list.append(m.group(1) if m else '-')
            cm = re.search(r'([\d,]+)개', sl)
            cnt_list.append(int(cm.group(1).replace(',', '')) if cm else None)
        while len(pct_list) < 3:
            pct_list.append('-')
        while len(cnt_list) < 3:
            cnt_list.append(None)
        _cnt_disp = [f'{c:,}' if c is not None else '-' for c in cnt_list]
        stats_block = _sco_dist_bars(
            [
                ("sco ≥ 12", _cnt_disp[0], pct_list[0], "#2ecc71"),
                ("0 ~ 12",   _cnt_disp[1], pct_list[1], "#95a5a6"),
                ("sco < 0",  _cnt_disp[2], pct_list[2], "#e74c3c"),
            ],
            total=total_count,
            title="📊 SCO 기준 종목 분포",
        )
    else:
        stats_block = '<p style="margin: 0 0 10px 0; color:#555; font-size:0.9em;">(통계 정보 없음)</p>'

    # 7. Minervini Early Stage
    minervini_early_block = format_minervini_table(MINERVINI_EARLY, "Minervini Early Stage")
    
    # 8. Minervini Entry Timing
    minervini_entry_block = format_minervini_table(MINERVINI_ENTRY, "Minervini Entry Timing")


    # NXT:NXT 티커 맵 (Top30 교차 조회용)
    nxt_map = build_nxt_map(text)

    # ✅ 시총 맵 로드 (kr.csv F열 = 시총, 원 단위)
    mktcap_map = {}
    nxt_lookup = {}
    kr_csv_path = Path(r"D:\py\korea\kr.csv")
    if not kr_csv_path.exists():
        # 업로드된 파일 fallback
        kr_csv_path = Path(__file__).resolve().parent / "kr.csv"
    try:
        df_kr = pd.read_csv(kr_csv_path, encoding='utf-8-sig')
        for _, row_kr in df_kr.iterrows():
            t6 = str(row_kr.iloc[0]).strip().zfill(6)
            nxt_val = str(row_kr.iloc[2]).strip() if len(df_kr.columns) >= 3 and pd.notna(row_kr.iloc[2]) else ""
            sun_val = str(row_kr.iloc[3]).strip() if len(df_kr.columns) >= 4 and pd.notna(row_kr.iloc[3]) else ""
            is_nxt = (nxt_val == "NXT")
            is_sun = (sun_val == "선")
            if is_nxt and is_sun:
                nxt_lookup[t6] = "NXT선"
            elif is_nxt:
                nxt_lookup[t6] = "NXT"
            elif is_sun:
                nxt_lookup[t6] = "선"
            else:
                nxt_lookup[t6] = ""
            try:
                mktcap_map[t6] = float(str(row_kr.iloc[5]).replace(',', '').strip())
            except Exception:
                mktcap_map[t6] = 0.0
    except Exception as e:
        print(f"⚠ kr.csv 시총 로드 실패: {e}")

    red_purple_title, red_purple_table = build_red_purple_signal_table(
        red_block,
        total_count=total_count,
        nxt_lookup=nxt_lookup,
    )

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>KR 전종목 Report</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 20px;
  margin: 0;
  background-color: #f4f7f6;
}}
h2 {{
  margin-top: 12px;
  margin-bottom: 2px;
  padding-bottom: 4px;
  color: #2c3e50;
  font-size: 0.95em;
  border-bottom: 2px solid #3498db;
}}
.signal-header {{
  margin-top: 8px;
  margin-bottom: 2px;
  padding-bottom: 3px;
  color: #2c3e50;
  font-size: 0.9em;
  border-bottom: 1px solid #3498db;
}}
.minervini {{ background-color: #fff3cd !important; border-bottom: 2px solid #f1c40f !important; }}
pre {{
  font-family: Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  background: white;
  padding: 10px;
  border-radius: 8px;
  box-shadow: 0 2px 5px rgba(0,0,0,0.1);
  font-size: 14px;
}}
@media (max-width: 600px) {{
  pre {{
    font-size: 11px !important;
    padding: 8px !important;
  }}
  .styled-table {{
    font-size: 10px !important;
  }}
  .styled-table th, .styled-table td {{
    padding: 3px 4px !important;
  }}
}}
/* Table Styles */
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
  background: linear-gradient(135deg, #3498db, #2980b9);
  color: #ffffff;
  text-align: center;
}}
.styled-table th, .styled-table td {{
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
  text-align: center;
}}
.styled-table td.narrow {{ font-weight: bold; color: #2980b9; text-align: left; }}
.styled-table td.name-col {{ text-align: left; max-width: 150px; overflow: hidden; text-overflow: ellipsis; }}
.styled-table tbody tr:nth-of-type(even) {{
  background-color: #f9f9f9;
}}
.styled-table tbody tr:last-of-type {{
  border-bottom: 2px solid #3498db;
}}
.up {{ color: #27ae60; font-weight: bold; }}
.down {{ color: #e74c3c; font-weight: bold; }}
.yield-col {{ font-family: Consolas, monospace; }}
.num {{ font-family: Consolas, monospace; text-align: right; }}
.center {{ text-align: center; }}
/* Trend Badges */
.trend-badge {{
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: bold;
    color: white;
    display: inline-block;
    min-width: 50px;
    text-align: center;
}}
.trend-lime {{ background-color: #2ecc71; }}
.trend-green {{ background-color: #27ae60; }}
.trend-red {{ background-color: #e74c3c; }}
.trend-purple {{ background-color: #9b59b6; }}
.nxt-header {{ cursor:default; text-align:center; }}
.sortable {{ cursor:pointer; user-select:none; }}
.sortable:hover {{ background: linear-gradient(135deg, #2980b9, #1a6fa0); }}
.nxt-cell {{ text-align:center; width:50px; }}
.nxt-badge-both {{
  display: inline-block; padding: 2px 6px;
  background-color: #1a1a1a; color: white;
  border-radius: 4px; font-size: 11px; font-weight: bold;
}}
.nxt-badge {{
  display:inline-block; padding:2px 6px;
  background-color:#8e44ad; color:white;
  border-radius:4px; font-size:11px; font-weight:bold;
}}
.top-nav-container {{
    display: flex;
    margin-bottom: 12px;
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
.sig-up {{ color: #27ae60; font-weight: bold; }}
.sig-down {{ color: #e74c3c; font-weight: bold; }}
.sig-jung {{ background-color: #e8f5e9; color: #27ae60 !important; font-weight: bold; }}
.sig-yeok {{ background-color: #ffebee; color: #e74c3c !important; font-weight: bold; }}
/* 주도주 트래킹 테이블 헤더 */
.tracking-header {{
    margin-top: 10px;
    margin-bottom: 2px;
    padding-bottom: 4px;
    color: #8e44ad;
    font-size: 0.95em;
    border-bottom: 2px solid #8e44ad;
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
/* === Naver Chart Popup === */
#naverChartPopup {{
  display: none; position: fixed; z-index: 99999;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; max-height: 90vh; overflow-y: auto;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border: none;
  background: #e74c3c; color: white; border-radius: 50%;
  font-size: 18px; cursor: pointer; flex-shrink: 0;
}}
.popup-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; margin-left: 1em; }}
.popup-link:hover {{ text-decoration: underline; }}
td[data-code], td[data-code] + td {{ cursor: pointer; }}
td[data-code] + td:hover {{ background-color: #e8f4f8 !important; }}
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.chart-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fafafa; }}
.chart-card-header {{ display: none; }}
.chart-card-title {{ font-size: 12px; font-weight: 700; color: #334155; }}
.chart-status {{ font-size: 11px; color: #94a3b8; }}
.chart-wrap {{ position: relative; width: 100%; height: 285px; background: white; }}
.chart-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: white; }}
.chart-loading {{ display: none; position: absolute; inset: 0; background: rgba(255,255,255,0.75); align-items: center; justify-content: center; font-size: 12px; color: #64748b; }}
.chart-loading.show {{ display: flex; }}
/* 스마트폰: 팝업 화면 중앙 고정, 차트 상하 배치 */
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

/* 태블릿 */
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
  .charts-grid {{ grid-template-columns: 1fr; }}
  .chart-wrap {{ height: 260px; }}
}}
</style>
</head>
<body>

<div class="top-nav-container">
    <div class="top-nav">
        <a href="kor_theme.html" class="nav-item">주도테마</a>
        <a href="kor_150.html" class="nav-item">KR150</a>
        <a href="kor_stock.html" class="nav-item active">KR전종목</a>
    </div>
</div>

<p style="margin: 0 0 15px 0; color: #555; font-size: 0.9em;">업데이트: {now}</p>

{stats_block}

<h2 style="margin-top:10px; border-bottom: 2px solid #e67e22; color:#e67e22;">📊 주도주 <span style="font-size:0.67em; color:#000; font-weight:normal; margin-left:8px;">6개월 신고가 98% + 거래량 전일×8 OR 5일평균×2.5 + 거래대금 2000억 + MA10/20/60 위</span></h2>
{make_leader_table(leader_block, high52w_set=high52w_set)}
<p style="margin: 2px 0 2px 0; color: #000; font-size: 0.8em;">*종목명 빨간글씨: 52주 최고가의 95% 이상인 종목</p>

<h2 style="margin-top:10px; border-bottom: 2px solid #8e44ad; color:#8e44ad;">📊 주도주 트래킹 (2주) <span style="font-size:0.8em; font-weight:normal; color:#000;">(<span style="color:#e74c3c;">빨강:신고가근처</span>, 당일/누적등락률 <span style="color:#e74c3c;">-15%</span>이하, 시총<span style="color:#e74c3c;">2000억</span>미만 제외)</span></h2>
{make_leader_tracking_table(tracking_data, high52w_set=high52w_set)}

<h2>📊 신호 종목 랭킹 (SPOT / MOM / LIME / GREEN / GANN)</h2>
{make_unified_signal_table(spot_lines, mom_block, lime_block, green_block, gann_fire_set=gann_fire_set, gann_info_dict=gann_info_dict, high52w_set=high52w_set)}

<h2 style="margin-top:10px;">🏆 종합 Top 30 (Final Score) <span style="font-size:0.6em; font-weight:normal; color:#888;"><span style="color:#e74c3c;">빨강: 신고가근처</span> - 시총2000억 미만, 당일거래대금 500억미만 제외</span></h2>
{parse_top30_table(top30_block, nxt_map=nxt_map, gann_fire_set=gann_fire_set, high52w_set=high52w_set, mktcap_map=mktcap_map)}

<h2 style="margin-top:20px;">{red_purple_title}</h2>
{red_purple_table}

<h2 class="minervini">⭐ Minervini Early Stage (초기 단계)</h2>
{minervini_early_block}

<h2 class="minervini">🎯 Minervini Entry Timing (진입 타이밍)</h2>
{minervini_entry_block}



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
      var n = parseFloat(str.replace(/[^0-9.\\x2D]/g, ''));
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
  makeTableSortable('top30-table');
  makeTableSortable('signal-table');
  makeTableSortable('leader-tracking-table');
}})();
</script>
<div id="naverChartPopup">
  <div class="popup-header">
    <button id="naverPopupClose">&#x2715;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 종목 페이지</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-card-header"><div class="chart-card-title">당일 선차트 (1일)</div><div class="chart-status" id="statusIntraday">대기중</div></div>
      <div class="chart-wrap"><img id="imgIntraday" alt="당일 차트"><div class="chart-loading" id="loadingIntraday">불러오는 중...</div></div>
    </div>
    <div class="chart-card">
      <div class="chart-card-header"><div class="chart-card-title">일봉</div><div class="chart-status" id="statusDaily">대기중</div></div>
      <div class="chart-wrap"><img id="imgDaily" alt="일봉 차트"><div class="chart-loading" id="loadingDaily">불러오는 중...</div></div>
    </div>
  </div>
</div>
<script>
(function () {{ return;
  var popup=document.getElementById('naverChartPopup'),popupTitle=document.getElementById('popupTitle'),popupLink=document.getElementById('popupLink');
  var imgIntraday=document.getElementById('imgIntraday'),imgDaily=document.getElementById('imgDaily');
  var loadingIntraday=document.getElementById('loadingIntraday'),loadingDaily=document.getElementById('loadingDaily');
  var statusIntraday=document.getElementById('statusIntraday'),statusDaily=document.getElementById('statusDaily');
  var closeBtn=document.getElementById('naverPopupClose'),hoverTimer=null,pinned=false,curTd=null;
  function openPopup(){{popup.style.display='block';document.body.classList.add('naver-popup-open');}}
  function closePopup(){{popup.style.display='none';document.body.classList.remove('naver-popup-open');pinned=false;}}
  function withTs(u){{return u+'?t='+Date.now();}}
  function intradayUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/area/day/'+c+'.png');}}
  function dailyCandleUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'+c+'.png');}}
  function itemPageUrl(c){{return 'https://finance.naver.com/item/main.naver?code='+c;}}
  function setStatus(el,t,col){{el.textContent=t;el.style.color=col||'#94a3b8';}}
  function loadInto(img,ld,st,url,lbl){{
    ld.classList.add('show');img.style.opacity='0.35';setStatus(st,'로딩중...','#f59e0b');
    var p=new Image();
    p.onload=function(){{img.src=url;img.style.opacity='1';ld.classList.remove('show');setStatus(st,'로드 성공','#22c55e');}};
    p.onerror=function(){{img.removeAttribute('src');img.style.opacity='1';ld.classList.remove('show');setStatus(st,lbl+' 실패','#ef4444');}};
    p.src=url;
  }}
  function loadCharts(code,name){{popupTitle.textContent=code+'  '+(name||'');popupLink.href=itemPageUrl(code);loadInto(imgIntraday,loadingIntraday,statusIntraday,intradayUrl(code),'당일');loadInto(imgDaily,loadingDaily,statusDaily,dailyCandleUrl(code),'일봉');}}
  function placePopup(cx,cy){{var isMobile=window.innerWidth<=767;if(isMobile)return;var rW=Math.min(860,window.innerWidth-20),rH=window.innerWidth<=900?650:430,x=cx+18,y=cy+18;if(x+rW>window.innerWidth-8)x=cx-rW-12;if(y+rH>window.innerHeight-8)y=cy-rH-12;if(x<8)x=8;if(y<8)y=8;popup.style.left=x+'px';popup.style.top=y+'px';popup.style.transform='none';}}
  if(closeBtn)closeBtn.addEventListener('click',closePopup);
  popup.addEventListener('mouseenter',function(){{pinned=true;}});
  popup.addEventListener('mouseleave',function(){{pinned=false;closePopup();}});
  /* === SWIPE-NAV-INJECTED (KR 전종목): 모바일 좌/우 스와이프 → 종목 이동 === */
  (function(){{
    if(window.__swipeNavInit) return; window.__swipeNavInit=true;
    var isTouch=function(){{ return window.matchMedia('(hover: none)').matches || window.innerWidth<=767; }};
    var curTd=null;
    document.querySelectorAll('td[data-code]').forEach(function(td){{
      var hot=(td.nextElementSibling&&td.nextElementSibling.tagName==='TD')?td.nextElementSibling:td;
      hot.addEventListener('click',function(){{ curTd=td; }});
      hot.addEventListener('mouseenter',function(){{ curTd=td; }});
    }});
    var sx=0,sy=0,st=0,tr=false;
    document.addEventListener('touchstart',function(e){{
      if(!isTouch()||!e.touches||e.touches.length!==1){{ tr=false; return; }}
      var t=e.touches[0]; sx=t.clientX; sy=t.clientY; st=Date.now(); tr=true;
    }},true);
    document.addEventListener('touchend',function(e){{
      if(!tr) return; tr=false;
      if(popup.style.display!=='block') return;
      var t=e.changedTouches&&e.changedTouches[0]; if(!t) return;
      var dx=t.clientX-sx, dy=t.clientY-sy, dt=Date.now()-st;
      if(dt>800||Math.abs(dx)<55||Math.abs(dx)<Math.abs(dy)*1.6) return;
      if(!curTd) return;
      var all=Array.prototype.slice.call(document.querySelectorAll('td[data-code]'));
      var i=all.indexOf(curTd); if(i<0) return;
      i+=(dx<0?1:-1); if(i<0||i>=all.length) return;
      var nt=all[i]; curTd=nt;
      openPopup(); loadCharts(nt.dataset.code, nt.dataset.name||'');
    }},true);
  }})();
  document.querySelectorAll('td[data-code]').forEach(function(td){{
    var hot=(td.nextElementSibling&&td.nextElementSibling.tagName==='TD')?td.nextElementSibling:td;
    hot.addEventListener('mouseenter',function(e){{curTd=td;var code=td.dataset.code,name=td.dataset.name||'';clearTimeout(hoverTimer);hoverTimer=setTimeout(function(){{placePopup(e.clientX,e.clientY);openPopup();loadCharts(code,name);}},140);}});
    hot.addEventListener('mousemove',function(e){{if(popup.style.display==='block'&&!pinned)placePopup(e.clientX,e.clientY);}});
    hot.addEventListener('mouseleave',function(){{clearTimeout(hoverTimer);setTimeout(function(){{if(!pinned)closePopup();}},120);}});
    hot.addEventListener('click',function(e){{curTd=td;if(window.innerWidth>767)return;e.stopPropagation();openPopup();loadCharts(td.dataset.code,td.dataset.name||'');}});
  }});
  document.addEventListener('click',function(e){{if(window.innerWidth<=767&&popup.style.display==='block'){{if(!popup.contains(e.target))closePopup();}}}});
  /* === 키보드(팝업 열렸을 때만): S/↑=이전, D/↓=다음, Tab/ESC=닫기 === */
  function unpinOnMove(e){{ if(popup.contains(e.target))return; document.removeEventListener('mousemove',unpinOnMove); pinned=false; }}
  function kbPin(){{ pinned=true; document.removeEventListener('mousemove',unpinOnMove); document.addEventListener('mousemove',unpinOnMove); }}
  document.addEventListener('keydown',function(e){{
    if(popup.style.display!=='block')return;
    var t=e.target,tag=t&&t.tagName;
    if(tag==='INPUT'||tag==='TEXTAREA'||(t&&t.isContentEditable))return;
    var k=e.key;
    if(k==='Tab'||k==='Escape'){{ e.preventDefault(); closePopup(); return; }}
    var dir=0;
    if(k==='s'||k==='S'||k==='ArrowUp') dir=-1;
    else if(k==='d'||k==='D'||k==='ArrowDown') dir=1;
    if(dir===0) return;
    var base=curTd; if(!base) return;
    e.preventDefault();
    var all=Array.prototype.slice.call(document.querySelectorAll('td[data-code]'));
    var i=all.indexOf(base); if(i<0) return;
    i+=dir; if(i<0||i>=all.length) return;
    var nt=all[i]; curTd=nt;
    kbPin();
    openPopup(); loadCharts(nt.dataset.code, nt.dataset.name||'');
    nt.scrollIntoView({{block:'nearest'}});
  }});
}})();
</script>

</body>
</html>
"""

    import sys as _sys
    _sys.path.insert(0, str(BASE.parent))
    from chart_popup_v4 import build_chart_popup as _bcp_v4, move_kr_trigger_to_name as _mv2name
    page = _mv2name(page)  # 한국종목: 티커 대신 종목명에 hover → 차트
    _codes = sorted(set(re.findall(r'data-code="([^"]+)"', page)))
    page = page.replace(
        "</body>",
        _bcp_v4(_codes, market="KR", trigger_attr="data-code", include_kospi=False) + "\n</body>",
        1,
    )
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] kor_stock.html updated at {OUT_HTML} (V4 차트 {len(_codes)}종목)")


if __name__ == "__main__":
    main()
