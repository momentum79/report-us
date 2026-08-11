# make_index_volume.py
import json
import html
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from chart_popup_v2 import fetch_daily, fetch_kospi_daily
from chart_popup_v4 import build_chart_popup

BASE = Path(r"D:\py\report-us")
REPORT_JSON       = BASE / "report_volume.json"
THEME_ORDER_JSON  = BASE / "theme_order.json"
OUT_HTML          = BASE / "kor_volume.html"
THEME_CSV         = Path(r"D:\py\korea\theme.csv")
THEME_FILTER_TXT  = Path(r"D:\py\0txt\00_1887_a_grade_leader.txt")
THEME_FILTER_B_TXT = Path(r"D:\py\0txt\00_1887_b_grade_leader.txt")
LEADER_TXT        = Path(r"D:\py\0txt\00_1887_leader.txt")
HA_TXT            = Path(r"D:\py\0txt\00_1887_ha.txt")
JUDO_TXT          = Path(r"D:\py\0txt\00_1887_judo.txt")
CLOSE_FILE        = Path(r"D:\py\0txt\kor_today_close.json")
PCT_FILE          = Path(r"D:\py\0txt\kor_today_pct.json")
LEADER_TRACKING_VOLUME_JSON = BASE / "leader_tracking_volume.json"
INTRADAY_RANK_DIR = Path(r"D:\py\0_당일거래대금\intraday_rank")
TRACKING_DAYS = 14

# 종목별 고정 색 팔레트 (정렬된 ticker 순으로 배정 → 같은 종목 = 같은 색)
INTRADAY_COLORS = [
    "#e74c3c", "#3498db", "#27ae60", "#8e44ad", "#e67e22",
    "#16a085", "#2c3e50", "#d35400", "#2980b9", "#c0392b",
    "#f39c12", "#9b59b6", "#1abc9c", "#34495e", "#e84393",
    "#00b894", "#0984e3", "#6c5ce7", "#a0522d", "#7f8c8d",
]
# raw unit: raw / 100 = 억원. 1조 = 10,000억 → raw threshold = 10,000 * 100
THRESHOLD_TRADE_AMOUNT = 10_000 * 100


# ======================= 테마명 축약 규칙 ==========================
def get_theme_label(thema_nm):
    # #사용자 필터링 - 코스닥_* 는 예외: _ 뒤 부분을 사용
    # 예: 코스닥_히든챔피언 → 히든챔피언, 코스닥_라이징스타 → 라이징스타
    if thema_nm.startswith('코스닥_'):
        return thema_nm.split('_', 1)[1]

    # #사용자 필터링 - _ 가 있으면 _ 앞부분만 사용
    # 예: 바이오_진단/백신 → 바이오, 원자력_기자재 → 원자력
    if '_' in thema_nm:
        return thema_nm.split('_', 1)[0]

    # #사용자 필터링 - _ 없고 / 가 있으면 / 앞부분만 사용
    # 예: 신약개발/기술수출 → 신약개발, 네트워크/광통신 → 네트워크
    if '/' in thema_nm:
        return thema_nm.split('/', 1)[0]

    # #사용자 필터링 - 그 외는 원래 이름 그대로
    # 예: 건강식품, 교육, 화장품
    return thema_nm


MAX_THEME_LEN = 7  # 테마 컬럼 최대 글자 수


def truncate_theme(label):
    """테마명을 MAX_THEME_LEN 글자까지만 표시 (초과 시 … 추가)"""
    if len(label) <= MAX_THEME_LEN:
        return label
    return label[:MAX_THEME_LEN] + '…'


# ======================= theme.csv 로드 → {종목코드: 첫번째테마 축약명} ==========================
def load_theme_map():
    theme_map = defaultdict(list)
    try:
        with open(THEME_CSV, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stk_cd   = row["종목코드"].strip()
                thema_nm = row["테마명"].strip()
                theme_map[stk_cd].append(thema_nm)
    except Exception as e:
        print(f"⚠ theme.csv 로드 실패: {e}")
    # 첫번째 테마명을 축약 규칙 적용해서 반환
    return {k: get_theme_label(v[0]) for k, v in theme_map.items()}


# ======================= 00theme_filter.txt 로드 → {종목코드: 소스명} dict ==========================
def load_theme_filter(path=THEME_FILTER_TXT):
    """포맷: '010170 당일테마' 또는 '010170' (소스명 없는 구버전도 호환)"""
    ticker_map = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(None, 1)  # 최대 2개로 분리
                if not parts:
                    continue
                t = parts[0].zfill(6)
                source = parts[1] if len(parts) > 1 else ""
                ticker_map[t] = source
    except Exception as e:
        print(f"⚠ 00theme_filter.txt 로드 실패: {e}")
    return ticker_map


def load_plain_tickers(path, label):
    tickers = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                ticker = parts[0].zfill(6)
                if ticker.isdigit() and len(ticker) == 6:
                    tickers.add(ticker)
    except FileNotFoundError:
        print(f"⚠ {label} 파일 없음: {path}")
    except Exception as e:
        print(f"⚠ {label} 로드 실패: {e}")
    return tickers


def load_nxt_dict(csv_path=r"D:\py\korea\kr.csv"):
    """kr.csv에서 ticker → 'NXT선'/'NXT'/'선'/'' 매핑 로드"""
    nxt_dict = {}
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = (row.get("티커") or "").strip().zfill(6)
                if not ticker:
                    continue
                is_nxt = (row.get("NXT") or "").strip() == "NXT"
                is_sun = (row.get("선") or "").strip() == "선"
                if is_nxt and is_sun:
                    nxt_dict[ticker] = "NXT선"
                elif is_nxt:
                    nxt_dict[ticker] = "NXT"
                elif is_sun:
                    nxt_dict[ticker] = "선"
                else:
                    nxt_dict[ticker] = ""
    except Exception as e:
        print(f"⚠ kr.csv NXT 로드 실패: {e}")
    return nxt_dict


def build_signal_marks(theme_filter):
    marks = {}

    def add_mark(ticker, text, css_class):
        marks.setdefault(ticker, [])
        if not any(existing_text == text for existing_text, _ in marks[ticker]):
            marks[ticker].append((text, css_class))

    for ticker in theme_filter:
        add_mark(ticker, "O", "mark-theme")
    for ticker in load_plain_tickers(JUDO_TXT, "00_1887_judo"):
        add_mark(ticker, "★", "mark-judo")
    for ticker in load_plain_tickers(HA_TXT, "00_1887_ha"):
        add_mark(ticker, "●", "mark-ha")

    return {
        ticker: "".join(f'<span class="{css_class}">{html.escape(text)}</span>' for text, css_class in values)
        for ticker, values in marks.items()
    }


def build_signal_marks(theme_filter, tracking_tickers=None):
    marks = {}

    def add_mark(ticker, text, css_class):
        marks.setdefault(ticker, [])
        if not any(existing_text == text for existing_text, _ in marks[ticker]):
            marks[ticker].append((text, css_class))

    for ticker in theme_filter:
        add_mark(ticker, "O", "mark-theme")
    for ticker in load_plain_tickers(JUDO_TXT, "00_1887_judo"):
        add_mark(ticker, "&#9733;", "mark-judo")
    for ticker in load_plain_tickers(HA_TXT, "00_1887_ha"):
        add_mark(ticker, "&#9679;", "mark-ha")
    if tracking_tickers:
        for ticker in tracking_tickers:
            add_mark(ticker, "T", "mark-tracking")

    return {
        ticker: "".join(f'<span class="{css_class}">{text}</span>' for text, css_class in values)
        for ticker, values in marks.items()
    }


def fmt_amt(val):
    if val is None:
        return "-"
    return f"{val:+,.0f}억"


# ======================= theme_order.json → {ticker: cntr_str} 캐시 ==========================
def load_cntr_cache():
    cache = {}
    try:
        with open(THEME_ORDER_JSON, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            ticker = str(item.get("ticker", "")).zfill(6)
            cntr   = item.get("cntr_str")
            if ticker and cntr is not None:
                try:
                    cache[ticker] = float(cntr)
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        print(f"⚠ theme_order.json 로드 실패: {e}")
    return cache


def format_overlap_list(overlap_list):
    """겹침 리스트를 3개씩 끊어서 줄바꿈 (굵게 + 마우스 호버 시 V2 차트)"""
    if not overlap_list:
        return '없음'

    def render(entry):
        m = re.match(r'^\s*(\d{6})\s*\((.*)\)\s*$', str(entry))
        if m:
            code, name = m.group(1), m.group(2).strip()
            label = f'{code} ({name})'
            return (f'<span class="chart-hover" data-code="{html.escape(code)}" '
                    f'data-name="{html.escape(name)}" '
                    f'style="cursor:pointer;font-weight:bold;">{html.escape(label)}</span>')
        return f'<b>{html.escape(str(entry))}</b>'

    lines = []
    for i in range(0, len(overlap_list), 3):
        chunk = overlap_list[i:i+3]
        lines.append(', '.join(render(c) for c in chunk))

    return '<br>'.join(lines)


# ======================= 주도테마 요약 (3개 이상만) ==========================
def get_lead_theme_summary(stocks, theme_map):
    counter = defaultdict(int)
    for s in stocks:
        ticker   = s.get('ticker', '').zfill(6)
        theme_nm = theme_map.get(ticker, '')
        if theme_nm:
            counter[theme_nm] += 1

    # 3개 이상 먼저 시도
    filtered = {k: v for k, v in counter.items() if v >= 3}
    # 3개 이상 없으면 2개 이상으로 fallback
    if not filtered:
        filtered = {k: v for k, v in counter.items() if v >= 2}
    if not filtered:
        return ''

    # 많은 순으로 정렬
    sorted_themes = sorted(filtered.items(), key=lambda x: -x[1])
    parts = [f"{nm}:{cnt}개" for nm, cnt in sorted_themes]
    return ' / '.join(parts)


def tv_color(billion):
    """거래대금(억 단위) → 색상 hex"""
    if billion >= 10000: return '#e74c3c'   # 1조 이상 빨간색
    if billion >= 5000:  return '#8e44ad'   # 5천억 이상 보라색
    if billion >= 1000:  return '#222'      # 1천억 이상 검은색
    return '#aaa'                           # 1천억 미만 회색


def build_table(stocks, theme_map, theme_filter, signal_marks):
    if not stocks:
        return '<p style="color:#95a5a6;">조건 충족 종목이 없습니다.</p>'

    rows = []
    for s in stocks:
        change = s.get('change', 0)
        c_cls = "sig-green" if change > 0 else ("sig-red" if change < 0 else "")
        nxt = s.get('nxt', '')

        # 거래대금을 억 단위로 변환
        trade_amt_raw = s.get('trade_amount', 0)
        trade_amt_billion = trade_amt_raw / 100  # 거래대금을 100으로 나누면 억 단위
        trade_amt_str = f'<span style="color:{tv_color(trade_amt_billion)}">{trade_amt_billion:,.0f}억</span>'

        today_str   = fmt_amt(s.get('today'))
        today_cls   = "sig-green" if s.get('today') and s['today'] > 0 else ("sig-red" if s.get('today') and s['today'] < 0 else "")
        total_str   = fmt_amt(s.get('total'))
        total_cls   = "sig-green" if s.get('total') and s['total'] > 0 else ("sig-red" if s.get('total') and s['total'] < 0 else "")

        nxt_cls  = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_cell = f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt}</span></td>' if nxt in ('NXT', '선', 'NXT선') else '<td class="nxt-cell"></td>'

        ticker = s.get('ticker', '').zfill(6)
        theme_nm = theme_map.get(ticker, '')
        theme_short = truncate_theme(theme_nm)
        theme_title = f' title="{html.escape(theme_nm)}"' if theme_short != theme_nm else ''
        theme_cell = f'<td class="theme-cell"{theme_title}>{html.escape(theme_short)}</td>'

        # O 컬럼: theme_filter(dict)에 포함되면 O, 아니면 빈칸
        o_mark = signal_marks.get(ticker, '')
        o_cell = f'<td class="o-cell">{o_mark}</td>'

        # 스냅샷 컬럼
        snap_price = s.get('snap_price')
        snap_pct   = s.get('snap_pct')
        high_pct   = s.get('high_pct')
        low_pct    = s.get('low_pct')

        def _fmt_pct(v):
            if v is None: return '-'
            return f"{v:+.2f}%"

        # snap_pct가 있으면 수익률, 없고 snap_price 있으면 가격 표시
        if snap_pct is not None:
            snap_val = _fmt_pct(snap_pct)
            snap_cls = "sig-green" if snap_pct > 0 else ("sig-red" if snap_pct < 0 else "")
        elif snap_price:
            snap_val = f"{snap_price:,}"
            snap_cls = ""
        else:
            snap_val = "-"
            snap_cls = ""

        high_val = _fmt_pct(high_pct)
        high_cls = "sig-green" if high_pct and high_pct > 0 else ""
        low_val  = _fmt_pct(low_pct)
        low_cls  = "sig-red"   if low_pct  and low_pct  < 0 else ""

        pred_rank_val = s.get('pred_rank', '')
        pred_rank_str = str(pred_rank_val) if pred_rank_val is not None else ''

        snap_rank_val = s.get('snap_rank')
        snap_rank_str = str(snap_rank_val) if snap_rank_val is not None else '-'

        rows.append(f"""<tr>
            <td class="narrow">{s.get('rank','')}</td>
            <td class="snap-rank-cell">{snap_rank_str}</td>
            <td class="pred-rank-cell">{pred_rank_str}</td>
            <td class="code-col" data-code="{html.escape(s.get('ticker','').zfill(6))}" data-name="{html.escape(s.get('name',''))}">{html.escape(s.get('ticker',''))}</td>
            <td>{html.escape(s.get('name',''))}</td>
            <td class="{c_cls}">{change:+.2f}%</td>
            {o_cell}
            <td>{trade_amt_str}</td>
            <td class="{today_cls}">{today_str}</td>
            <td class="{total_cls}">{total_str}</td>
            {nxt_cell}
            {theme_cell}
            <td class="{snap_cls}">{snap_val}</td>
            <td class="{high_cls}">{high_val}</td>
            <td class="{low_cls}">{low_val}</td>
        </tr>""")

    return f"""<table class="styled-tableWide" id="volTable">
<thead><tr>
  <th onclick="sortTable(0)">순위</th><th class="snap-rank-header" onclick="sortTable(1)">스샷</th><th onclick="sortTable(2)">전일</th><th onclick="sortTable(3)">종목코드</th><th onclick="sortTable(4)">종목명</th><th onclick="sortTable(5)">등락률</th>
  <th class="o-header" onclick="sortTable(6)">O</th>
  <th onclick="sortTable(7)">거래대금</th><th onclick="sortTable(8)">당일합계</th><th onclick="sortTable(9)">3일합계</th>
  <th class="nxt-header" onclick="sortTable(10)">NXT선</th>
  <th onclick="sortTable(11)">테마</th>
  <th onclick="sortTable(12)">스냅샷</th>
  <th onclick="sortTable(13)">최고(%)</th>
  <th onclick="sortTable(14)">최저(%)</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>"""


def save_leader_txt(stocks, theme_filter, tracking_tickers=None):
    """O 종목(theme_filter) + G 종목(tracking_tickers) 티커를 00_1887_leader.txt에 저장"""
    tracking_tickers = tracking_tickers or set()
    seen = set()
    leader_tickers = []
    for s in stocks:
        t = s.get('ticker', '').zfill(6)
        if t in seen:
            continue
        if t in theme_filter or t in tracking_tickers:
            leader_tickers.append(t)
            seen.add(t)
    try:
        LEADER_TXT.parent.mkdir(parents=True, exist_ok=True)
        with open(LEADER_TXT, 'w', encoding='utf-8') as f:
            for t in leader_tickers:
                f.write(f"{t}\n")
        print(f"✅ 00_1887_leader.txt 저장 완료 ({len(leader_tickers)}개) → {LEADER_TXT}")
    except Exception as e:
        print(f"⚠ 00_1887_leader.txt 저장 실패: {e}")
    return leader_tickers


def build_leader_table(stocks, theme_map, theme_filter, cntr_cache):
    """🎯 주도주 테이블 — O 종목만, 마지막 컬럼에 소스명 표시"""
    leader_stocks = [s for s in stocks if s.get('ticker', '').zfill(6) in theme_filter]
    if not leader_stocks:
        return '<p style="color:#95a5a6;">(해당 종목 없음)</p>'

    rows = []
    for s in leader_stocks:
        change = s.get('change', 0)
        c_cls = "sig-green" if change > 0 else ("sig-red" if change < 0 else "")
        nxt = s.get('nxt', '')

        trade_amt_raw = s.get('trade_amount', 0)
        trade_amt_b = trade_amt_raw / 100
        trade_amt_str = f'<span style="color:{tv_color(trade_amt_b)}">{trade_amt_b:,.0f}억</span>'

        today_str = fmt_amt(s.get('today'))
        today_cls = "sig-green" if s.get('today') and s['today'] > 0 else ("sig-red" if s.get('today') and s['today'] < 0 else "")
        total_str = fmt_amt(s.get('total'))
        total_cls = "sig-green" if s.get('total') and s['total'] > 0 else ("sig-red" if s.get('total') and s['total'] < 0 else "")

        nxt_cls  = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_cell = f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt}</span></td>' if nxt in ('NXT', '선', 'NXT선') else '<td class="nxt-cell"></td>'

        ticker = s.get('ticker', '').zfill(6)
        theme_nm = theme_map.get(ticker, '')
        theme_short = truncate_theme(theme_nm)
        theme_title = f' title="{html.escape(theme_nm)}"' if theme_short != theme_nm else ''
        theme_cell = f'<td class="theme-cell"{theme_title}>{html.escape(theme_short)}</td>'

        # 소스명 컬럼: 00theme_filter.txt의 2번째 열
        source_nm = theme_filter.get(ticker, '')
        source_cell = f'<td class="source-cell">{html.escape(source_nm)}</td>'

        # 스냅샷 컬럼
        snap_price = s.get('snap_price')
        snap_pct   = s.get('snap_pct')
        high_pct   = s.get('high_pct')
        low_pct    = s.get('low_pct')

        def _fmt_pct(v):
            if v is None: return '-'
            return f"{v:+.2f}%"

        if snap_pct is not None:
            snap_val = _fmt_pct(snap_pct)
            snap_cls = "sig-green" if snap_pct > 0 else ("sig-red" if snap_pct < 0 else "")
        elif snap_price:
            snap_val = f"{snap_price:,}"
            snap_cls = ""
        else:
            snap_val = "-"
            snap_cls = ""

        high_val = _fmt_pct(high_pct)
        high_cls = "sig-green" if high_pct and high_pct > 0 else ""
        low_val  = _fmt_pct(low_pct)
        low_cls  = "sig-red"   if low_pct  and low_pct  < 0 else ""

        # 체결강도 컬럼
        cntr = cntr_cache.get(ticker)
        if cntr is not None:
            cntr_cls  = "sig-green" if cntr >= 100 else "sig-red"
            cntr_str  = f"{cntr:.1f}%"
            cntr_cell = f'<td class="cntr-cell {cntr_cls}">{cntr_str}</td>'
        else:
            cntr_cell = '<td class="cntr-cell">-</td>'

        pred_rank_val = s.get('pred_rank', '')
        pred_rank_str = str(pred_rank_val) if pred_rank_val is not None else ''

        snap_rank_val = s.get('snap_rank')
        snap_rank_str = str(snap_rank_val) if snap_rank_val is not None else '-'

        rows.append(f"""<tr>
            <td class="narrow">{s.get('rank','')}</td>
            <td class="snap-rank-cell">{snap_rank_str}</td>
            <td class="pred-rank-cell">{pred_rank_str}</td>
            <td class="code-col" data-code="{html.escape(s.get('ticker','').zfill(6))}" data-name="{html.escape(s.get('name',''))}">{html.escape(s.get('ticker',''))}</td>
            <td>{html.escape(s.get('name',''))}</td>
            <td class="{c_cls}">{change:+.2f}%</td>
            {cntr_cell}
            <td>{trade_amt_str}</td>
            <td class="{today_cls}">{today_str}</td>
            <td class="{total_cls}">{total_str}</td>
            {nxt_cell}
            {theme_cell}
            {source_cell}
            <td class="{snap_cls}">{snap_val}</td>
            <td class="{high_cls}">{high_val}</td>
            <td class="{low_cls}">{low_val}</td>
        </tr>""")

    return f"""<table class="styled-tableWide">
<thead><tr>
  <th>순위</th><th class="snap-rank-header">스샷</th><th>전일</th><th>종목코드</th><th>종목명</th><th>등락률</th>
  <th>체결강도</th>
  <th>거래대금</th><th>당일합계</th><th>3일합계</th>
  <th class="nxt-header">NXT선</th>
  <th>테마</th>
  <th>소스</th>
  <th>스냅샷</th>
  <th>최고(%)</th>
  <th>최저(%)</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>"""


def update_leader_tracking_volume(stocks, theme_filter):
    """
    거래대금 1조 이상 + 주도주 신호 종목을 leader_tracking_volume.json에 누적 저장.
    - 최초 등장 날짜(added_date) 기록, 이후 last_seen_date 갱신
    - TRACKING_DAYS일 이상 지난 항목 자동 삭제
    - reburst_today: 하루 이상 공백 후 재등장 시 True
    """
    today_str     = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff        = (datetime.now() - timedelta(days=TRACKING_DAYS)).strftime("%Y-%m-%d")

    if LEADER_TRACKING_VOLUME_JSON.exists():
        try:
            tracking = json.loads(LEADER_TRACKING_VOLUME_JSON.read_text(encoding="utf-8"))
        except Exception:
            tracking = {}
    else:
        tracking = {}

    tracking = {k: v for k, v in tracking.items() if v.get("added_date", "") >= cutoff}

    close_dict = {}
    if CLOSE_FILE.exists():
        try:
            close_dict = json.loads(CLOSE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 편입 조건: 거래대금 상위 30 (+4% 이상) 중 거래대금 1조 이상
    eligible = [
        s for s in stocks
        if s.get('trade_amount', 0) >= THRESHOLD_TRADE_AMOUNT
    ]

    for s in eligible:
        ticker       = s.get('ticker', '').zfill(6)
        name         = s.get('name', '')
        trade_amount = s.get('trade_amount', 0)
        change_pct   = s.get('change', 0)

        if ticker not in tracking:
            base_price = close_dict.get(ticker) or s.get('snap_price')
            entry_open = s.get('open_price')  # topvolume30.py가 ohlc_map에서 채워줌
            tracking[ticker] = {
                "name":           name,
                "added_date":     today_str,
                "last_seen_date": today_str,
                "base_price":     base_price,
                "entry_open":     entry_open,
                "trade_amount":   trade_amount,
                "reburst_today":  False,
                "pct_history":    {today_str: f"{change_pct:+.2f}%"},
            }
        else:
            prev_last_seen = tracking[ticker].get("last_seen_date",
                                                   tracking[ticker].get("added_date", ""))
            tracking[ticker]["reburst_today"]  = (prev_last_seen < yesterday_str)
            tracking[ticker]["last_seen_date"] = today_str
            tracking[ticker]["trade_amount"]   = trade_amount
            tracking[ticker]["pct_history"][today_str] = f"{change_pct:+.2f}%"
            # 등록 당일에는 장중 가격이 계속 바뀌므로 최신 종가 파일 값으로 갱신한다.
            # 날짜가 지나면 최초 등록일 종가를 고정해 누적수익률 기준가로 사용한다.
            if tracking[ticker].get("added_date") == today_str and close_dict.get(ticker):
                tracking[ticker]["base_price"] = close_dict[ticker]
            if not tracking[ticker].get("name"):
                tracking[ticker]["name"] = name

    try:
        LEADER_TRACKING_VOLUME_JSON.write_text(
            json.dumps(tracking, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠ leader_tracking_volume.json 저장 실패: {e}")

    return tracking


def backfill_tracking_base_prices(tracking):
    """비어 있는 기준가를 최초 등록일의 실제 종가로 한 번 보충한다."""
    changed = False
    today_str = datetime.now().strftime("%Y-%m-%d")

    for ticker, info in tracking.items():
        if info.get("base_price"):
            continue

        added_date = info.get("added_date", "")
        if not added_date or added_date >= today_str:
            continue

        ymd = added_date.replace("-", "")
        try:
            rows = fetch_daily(ticker, ymd, ymd)
            base_price = next(
                (row[4] for row in rows if row[0] == added_date and row[4] > 0),
                None,
            )
        except Exception as e:
            print(f"⚠ [TRACK] {ticker} 등록 종가 조회 실패: {e}")
            continue

        if base_price:
            info["base_price"] = base_price
            changed = True
            print(f"  [TRACK] {ticker} 등록 종가 보충: {added_date} {base_price:,.0f}원")

    return changed


def normalize_tracking_volume_dates(tracking):
    """
    등록일이 휴장일이면 차트에 존재하는 직전 거래일로 보정한다.
    거래대금 트래킹의 라임 배경이 실제 등록 캔들에 찍히도록 한다.
    """
    try:
        kospi_daily = fetch_kospi_daily(days_back=TRACKING_DAYS + 30)
    except Exception as e:
        print(f"⚠ 거래일 캘린더 로드 실패(등록일 보정 생략): {e}")
        return False

    trading_dates = sorted(kospi_daily.keys())
    if not trading_dates:
        return False

    changed = False
    for ticker, info in tracking.items():
        added_date = info.get("added_date")
        if not added_date or added_date in trading_dates:
            continue

        prev_dates = [d for d in trading_dates if d <= added_date]
        if not prev_dates:
            continue

        fixed_date = prev_dates[-1]
        pct_history = info.get("pct_history", {})
        if isinstance(pct_history, dict) and added_date in pct_history:
            pct_history.setdefault(fixed_date, pct_history[added_date])
            pct_history.pop(added_date, None)

        info["added_date"] = fixed_date
        changed = True
        print(f"  [TRACK] {ticker} 등록일 {added_date} → 거래일 {fixed_date} 보정")

    return changed


def build_leader_tracking_volume_table(tracking, stocks):
    """
    📊 거래대금 트래킹 (2주) 테이블 (KR150 주도주 트래킹 스타일)
    컬럼: Ticker | Name | 등록일 | 등록시 등락률 | 오늘 등락률 | 누적 등락률 | 경과 | 거래대금 | NXT선
    """
    if not tracking:
        return '<p style="color:#95a5a6; margin-left:10px;">(트래킹 종목 없음)</p>'

    today_str = datetime.now().strftime("%Y-%m-%d")

    close_dict = {}
    if CLOSE_FILE.exists():
        try:
            close_dict = json.loads(CLOSE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    pct_dict = {}
    if PCT_FILE.exists():
        try:
            pct_dict = json.loads(PCT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    nxt_dict = load_nxt_dict()

    def pct_cell(pct_str):
        try:
            val = float(str(pct_str).replace('%', '').replace('+', ''))
            cls  = 'sig-green' if val > 0 else ('sig-red' if val < 0 else '')
            sign = '+' if val >= 0 else ''
            return f'<td class="{cls}">{sign}{val:.2f}%</td>'
        except Exception:
            return '<td style="color:#aaa;">-</td>'

    def cum_pct_cell(base_price, today_close):
        # 실제 종가 기반: 최초 등록일 종가 → 오늘 종가
        try:
            if base_price and today_close and float(base_price) > 0:
                cum  = (float(today_close) / float(base_price) - 1) * 100
                sign = '+' if cum >= 0 else ''
                cls  = 'sig-green' if cum > 0 else ('sig-red' if cum < 0 else '')
                return f'<td class="{cls}"><b>{sign}{cum:.2f}%</b></td>'
        except Exception:
            pass
        return '<td style="color:#aaa;">-</td>'

    sorted_items = sorted(tracking.items(), key=lambda x: x[1].get("added_date", ""), reverse=True)

    rows = []
    for ticker, info in sorted_items:
        name        = info.get("name", "")
        added_date  = info.get("added_date", "-")
        base_price  = info.get("base_price")
        trade_raw   = info.get("trade_amount", 0)
        pct_history = info.get("pct_history", {})

        try:
            days_passed = (datetime.now() - datetime.strptime(added_date, "%Y-%m-%d")).days
        except Exception:
            days_passed = 0

        expire_in  = TRACKING_DAYS - days_passed
        short_date = added_date[5:] if len(added_date) == 10 else added_date

        if days_passed <= 5:
            days_color = "#27ae60"
        elif days_passed <= 10:
            days_color = "#e67e22"
        else:
            days_color = "#e74c3c"

        first_pct = pct_history.get(added_date, "-")

        today_pct = pct_dict.get(ticker)
        if not today_pct:
            today_pct = pct_history.get(today_str, "-")
            if today_pct == "-" and pct_history:
                today_pct = pct_history.get(max(pct_history.keys()), "-")

        today_close = close_dict.get(ticker)

        trade_b   = trade_raw / 100 if trade_raw else 0
        tv_col    = tv_color(trade_b)
        tv_weight = 'bold' if trade_b >= 10000 else 'normal'
        tv_cell   = (f'<td style="color:{tv_col};font-weight:{tv_weight};">'
                     f'{trade_b:,.0f}억</td>')

        nxt_val  = nxt_dict.get(ticker, '')
        nxt_cls  = 'nxt-badge-both' if nxt_val == 'NXT선' else 'nxt-badge'
        nxt_html = f'<span class="{nxt_cls}">{nxt_val}</span>' if nxt_val in ('NXT', '선', 'NXT선') else ''

        rows.append(
            f'<tr>'
            f'<td class="narrow" data-code="{html.escape(ticker)}" '
            f'data-name="{html.escape(name)}">{html.escape(ticker)}</td>'
            f'<td>{html.escape(name)}</td>'
            f'<td style="font-size:12px;color:#555;">{html.escape(short_date)}</td>'
            f'{pct_cell(first_pct)}'
            f'{pct_cell(today_pct)}'
            f'{cum_pct_cell(base_price, today_close)}'
            f'<td style="color:{days_color};font-weight:bold;font-size:12px;">'
            f'{days_passed}일 경과 (D-{expire_in})</td>'
            f'{tv_cell}'
            f'<td class="nxt-cell">{nxt_html}</td>'
            f'</tr>'
        )

    if not rows:
        return '<p style="color:#95a5a6; margin-left:10px;">(트래킹 종목 없음)</p>'

    header = (
        '<thead><tr>'
        '<th>Ticker</th><th>Name</th><th>등록일</th>'
        '<th>등록시 등락률</th><th>오늘 등락률</th><th>누적 등락률</th>'
        '<th>경과</th><th>거래대금</th>'
        '<th class="nxt-header">NXT선</th>'
        '</tr></thead>'
    )
    return (
        f'<table class="styled-tableWide">{header}'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


INTRADAY_TOP_RANK = 30   # 추적 등록 기준: 거래대금 순위 TOP30 진입
# 거래대금 강조 박스 임계값 (raw 단위: trade_amount/100 = 억원)
INTRADAY_AMT_BOX  = 500_000     # 5천억 이상 → 빨간 네모 박스
INTRADAY_AMT_FILL = 1_000_000   # 1조  이상 → 빨간 박스 + 노란 채움


def build_intraday_rank_chart():
    """
    📈 거래대금 순위 변화 (오늘, 시간대별) — bump chart.
    - X축: 슬롯 시각 / Y축: 그 시각 추적종목을 순위순으로 줄세운 레인(맨 위=1등)
    - 각 점: 절대 거래대금 순위 숫자 / 맨 오른쪽 점: 티커(종목명) / 같은 종목=같은 색
    - 추적 대상: (기존 +4% 조건) AND 거래대금 TOP30 진입.
      한 번 TOP30에 진입(등록)하면 그 시점부터 마감까지 추적 → 이후 순위가
      30위 밖(70·80위)으로 밀려도 그 변화를 계속 표시. 끝까지 TOP30 못 든
      +4% 종목은 차트에서 제외. 등록 이전 슬롯의 점도 그리지 않음.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    path = INTRADAY_RANK_DIR / f"{today_str}.json"
    if not path.exists():
        return '<p style="color:#95a5a6; margin-left:10px;">(오늘 순위 변화 데이터 없음)</p>'
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f'<p style="color:#95a5a6; margin-left:10px;">(데이터 로드 실패: {html.escape(str(e))})</p>'

    slots = [sl for sl in data.get("slots", []) if sl.get("stocks")]
    slots.sort(key=lambda x: x.get("time", ""))
    if not slots:
        return '<p style="color:#95a5a6; margin-left:10px;">(오늘 순위 변화 데이터 없음)</p>'

    n_slots = len(slots)

    # 등록(enrollment): 각 종목이 처음으로 TOP30에 진입한 슬롯 인덱스
    #   - 첫 슬롯부터 TOP30이면 si=0부터 추적
    #   - 중간에 신규로 TOP30 진입하면 그 슬롯부터 추적
    enroll_si = {}   # ticker -> 최초 TOP30 진입 슬롯 인덱스
    for si, sl in enumerate(slots):
        for s in sl["stocks"]:
            if s["rank"] <= INTRADAY_TOP_RANK and s["ticker"] not in enroll_si:
                enroll_si[s["ticker"]] = si

    if not enroll_si:
        return '<p style="color:#95a5a6; margin-left:10px;">(오늘 TOP30 진입 종목 없음)</p>'

    # 등록 종목 색 배정 (정렬된 ticker 순 → 고정색)
    color_map = {t: INTRADAY_COLORS[i % len(INTRADAY_COLORS)]
                 for i, t in enumerate(sorted(enroll_si))}

    # 슬롯별 레인(상대순위) 계산 — 등록된 종목을 등록시점 이후 슬롯에서만 표시
    series   = defaultdict(list)   # ticker -> [(slot_idx, lane, rank, trade_amount, change), ...]
    name_map = {}
    max_lanes = 1
    for si, sl in enumerate(slots):
        visible = [s for s in sl["stocks"]
                   if s["ticker"] in enroll_si and si >= enroll_si[s["ticker"]]]
        visible.sort(key=lambda s: s["rank"])
        max_lanes = max(max_lanes, len(visible))
        for lane, s in enumerate(visible):
            series[s["ticker"]].append((si, lane, s["rank"], s.get("trade_amount", 0), s.get("change")))
            name_map[s["ticker"]] = s["name"]

    # 레이아웃
    m_left, m_right, m_top, m_bot = 46, 180, 22, 34
    slot_gap, lane_gap = 60, 38
    plot_w = slot_gap * max(n_slots - 1, 1)
    plot_h = lane_gap * max(max_lanes - 1, 1)
    width  = m_left + plot_w + m_right

    def X(si):   return m_left + si * slot_gap
    def Y(lane): return m_top + lane * lane_gap

    def _est_w(txt):
        return sum(11.0 if ord(c) > 0x2e80 else 6.4 for c in txt)

    # 종목명 라벨(티커(종목명) 등락률%) 사전 계산 + 겹침 보정(겹치면 한 줄씩 아래로)
    label_items = []
    for ticker, pts in series.items():
        pts.sort(key=lambda p: p[0])
        name = name_map.get(ticker, "")
        last_si, last_lane, _lr, _la, last_ch = pts[-1]
        ch_txt = f" {last_ch:+.1f}%" if isinstance(last_ch, (int, float)) else ""
        txt = f"{ticker}({name}){ch_txt}"
        label_items.append({
            "x": X(last_si) + 9, "y": Y(last_lane), "w": _est_w(txt),
            "text": txt, "color": color_map[ticker], "code": ticker, "name": name,
        })
    label_items.sort(key=lambda L: (L["x"], L["y"]))
    placed = []
    for L in label_items:
        ly, guard = L["y"], 0
        while guard < 8 and any(
            abs(py - ly) < 12 and not (L["x"] + L["w"] < px or px + pw < L["x"])
            for px, pw, py in placed
        ):
            ly += 13
            guard += 1
        L["draw_y"] = ly
        placed.append((L["x"], L["w"], ly))

    max_label_y = max((L["draw_y"] for L in label_items), default=m_top)
    height = max(m_top + plot_h + m_bot, max_label_y + 16)
    axis_y = m_top + plot_h + 22

    svg = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'style="font-family:Segoe UI,sans-serif; min-width:{width}px;">']

    # 가로 그리드(레인) + 좌측 레인 번호
    for lane in range(max_lanes):
        y = Y(lane)
        svg.append(f'<line x1="{m_left}" y1="{y}" x2="{m_left + plot_w}" y2="{y}" '
                   f'stroke="#eee" stroke-width="1"/>')
        svg.append(f'<text x="{m_left - 10}" y="{y + 4}" font-size="10" fill="#bbb" '
                   f'text-anchor="end">{lane + 1}</text>')

    # 세로 그리드 + X축 시간 라벨
    for si, sl in enumerate(slots):
        x = X(si)
        svg.append(f'<line x1="{x}" y1="{m_top}" x2="{x}" y2="{m_top + plot_h}" '
                   f'stroke="#f6f6f6" stroke-width="1"/>')
        svg.append(f'<text x="{x}" y="{axis_y}" font-size="11" fill="#7f8c8d" '
                   f'text-anchor="middle">{html.escape(sl["time"])}</text>')

    # 종목별 선 + 점 + 순위숫자
    for ticker, pts in series.items():
        color = color_map[ticker]
        name = name_map.get(ticker, "")
        coords = " ".join(f"{X(si)},{Y(lane)}" for si, lane, _r, _a, _c in pts)
        svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" '
                   f'stroke-width="2.5" opacity="0.85"><title>{html.escape(ticker)} '
                   f'{html.escape(name)}</title></polyline>')
        for si, lane, rank, amt, _c in pts:
            x, y = X(si), Y(lane)
            svg.append(f'<circle cx="{x}" cy="{y}" r="3.6" fill="{color}">'
                       f'<title>{html.escape(ticker)} {html.escape(name)} | 순위 {rank}</title></circle>')
            # 거래대금 강조 박스 (숫자 뒤에 먼저 그려 숫자를 가리지 않음)
            ty = y - 7
            if amt >= INTRADAY_AMT_BOX:
                box_fill = "#ffe600" if amt >= INTRADAY_AMT_FILL else "none"
                bw = len(str(rank)) * 7 + 6
                svg.append(f'<rect x="{x - bw / 2:.1f}" y="{ty - 10}" width="{bw}" height="13" '
                           f'rx="2" fill="{box_fill}" stroke="#e60000" stroke-width="1.5"/>')
            svg.append(f'<text x="{x}" y="{ty}" font-size="10" fill="{color}" '
                       f'text-anchor="middle" font-weight="bold">{rank}</text>')

    # 종목명 라벨 (겹침 보정 위치, 마우스 호버 → 차트 팝업)
    for L in label_items:
        svg.append(f'<text x="{L["x"]}" y="{L["draw_y"] + 4}" font-size="11" '
                   f'fill="{L["color"]}" font-weight="bold" class="chart-hover" '
                   f'data-code="{html.escape(L["code"])}" data-name="{html.escape(L["name"])}" '
                   f'style="cursor:pointer;">{html.escape(L["text"])}</text>')

    svg.append('</svg>')
    return (f'<div style="overflow-x:auto; background:white; border-radius:8px; '
            f'box-shadow:0 2px 5px rgba(0,0,0,0.1); padding:12px 8px;">{"".join(svg)}</div>')


def main():
    data = {}
    if REPORT_JSON.exists():
        try:
            data = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠ JSON 읽기 실패: {e}")

    stocks       = data.get('stocks', [])
    overlap_list = data.get('overlap', [])
    update_time  = data.get('update_time', '')
    now          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    theme_map    = load_theme_map()
    print(f"✅ theme.csv 로드 완료: {len(theme_map)}개 종목")
    theme_filter = load_theme_filter()

    # G 마크: update 전에 로드 → 이전 세션부터 추적 중이던 종목에만 표시
    existing_tracking = {}
    if LEADER_TRACKING_VOLUME_JSON.exists():
        try:
            existing_tracking = json.loads(LEADER_TRACKING_VOLUME_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    tracking_tickers = set(existing_tracking.keys())

    signal_marks = build_signal_marks(theme_filter, tracking_tickers)
    print(f"✅ 매수후보 표시 로드 완료: {len(signal_marks)}개 종목 (트래킹 G: {len(tracking_tickers)}개)")
    print(f"✅ 00theme_filter.txt 로드 완료: {len(theme_filter)}개 종목")
    cntr_cache   = load_cntr_cache()
    print(f"✅ theme_order.json 체결강도 캐시: {len(cntr_cache)}개 종목")
    lead_summary = get_lead_theme_summary(stocks, theme_map)

    overlap_html = format_overlap_list(overlap_list)
    save_leader_txt(stocks, theme_filter, tracking_tickers)
    leader_table_html = build_leader_table(stocks, theme_map, theme_filter, cntr_cache)

    theme_filter_b = load_theme_filter(THEME_FILTER_B_TXT)
    print(f"✅ 00_1887_b_grade_leader.txt 로드 완료: {len(theme_filter_b)}개 종목")
    leader_table_b_html = build_leader_table(stocks, theme_map, theme_filter_b, cntr_cache)

    tracking_volume      = update_leader_tracking_volume(stocks, theme_filter)
    tracking_changed = normalize_tracking_volume_dates(tracking_volume)
    tracking_changed = backfill_tracking_base_prices(tracking_volume) or tracking_changed
    if tracking_changed:
        try:
            LEADER_TRACKING_VOLUME_JSON.write_text(
                json.dumps(tracking_volume, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"⚠ leader_tracking_volume.json 보정 저장 실패: {e}")
    tracking_volume_html = build_leader_tracking_volume_table(tracking_volume, stocks)
    print(f"✅ 주도주 트래킹(거래대금) 업데이트 완료: {len(tracking_volume)}개 종목")

    intraday_chart_html = build_intraday_rank_chart()

    main_table_html = build_table(stocks, theme_map, theme_filter, signal_marks)

    # 호버 가능한 모든 종목코드(data-code) 수집 → V4 인터랙티브 차트 팝업 빌드
    codes = set(re.findall(r'data-code="([0-9A-Za-z]{1,6})"',
                           leader_table_html + leader_table_b_html + tracking_volume_html + main_table_html + intraday_chart_html + overlap_html))
    track_dates = {str(t).zfill(6): [v["added_date"]]
                   for t, v in tracking_volume.items() if v.get("added_date")}
    popup_block = build_chart_popup(sorted(codes), market="KR",
                                    trigger_attr="data-code",
                                    include_kospi=False,
                                    track_dates=track_dates)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Korea Volume (+4% 이상)</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 20px; margin: 0; background-color: #f4f7f6;
}}
h2 {{
  margin-top: 30px; padding-bottom: 10px; color: #2c3e50;
  border-bottom: 2px solid #3498db;
}}
.styled-tableWide {{
  width: auto; max-width: 100%; border-collapse: collapse;
  margin: 10px 0; font-size: 13px; background: white;
  box-shadow: 0 2px 5px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden;
}}
.styled-tableWide thead tr {{ background-color: #3498db; color: #ffffff; text-align: left; }}
.styled-tableWide th {{
  cursor: pointer; user-select: none;
}}
.styled-tableWide th:hover {{ background-color: #2980b9; }}
.styled-tableWide th.sort-asc::after {{ content: ' ▲'; font-size: 10px; }}
.styled-tableWide th.sort-desc::after {{ content: ' ▼'; font-size: 10px; }}
.styled-tableWide th, .styled-tableWide td {{
  padding: 6px 10px; border-bottom: 1px solid #eee; white-space: nowrap;
}}
.styled-tableWide td.narrow {{ width: 40px; color: #7f8c8d; font-weight: bold; text-align: center; }}
.styled-tableWide td.code-col {{ width: 80px; font-weight: 500; }}
.sig-green {{ color: #27ae60; font-weight: bold; }}
.sig-red   {{ color: #e74c3c; font-weight: bold; }}

/* NXT */
.nxt-header {{
  cursor: pointer; background-color: #2980b9 !important;
  user-select: none; text-align: center;
}}
.nxt-header:hover {{ background-color: #1a6a9a !important; }}
.nxt-cell {{ text-align: center; width: 55px; }}
.nxt-badge {{
  display: inline-block; padding: 2px 6px;
  background-color: #8e44ad; color: white;
  border-radius: 4px; font-size: 11px; font-weight: bold;
}}
.nxt-badge-both {{
  display: inline-block; padding: 2px 6px;
  background-color: #1a1a1a; color: white;
  border-radius: 4px; font-size: 11px; font-weight: bold;
}}
.theme-cell {{ color: #2c3e50; font-size: 12px; }}
.o-header {{ cursor: pointer; user-select: none; text-align: center; width: 28px; padding: 6px 4px !important; }}
.o-cell {{ text-align: center; width: 34px; padding: 6px 4px !important; font-weight: bold; letter-spacing: 1px; white-space: nowrap; }}
.mark-theme {{ color: #e67e22; }}
.mark-judo {{ color: #f1c40f; text-shadow: 0 0 1px #7f6200; }}
.mark-ha {{ color: #111; }}
.mark-tracking {{ color: #27ae60; font-weight: bold; }}
.source-cell {{ color: #8e44ad; font-size: 11px; white-space: nowrap; }}
.cntr-cell {{ text-align: right; font-size: 12px; font-weight: bold; white-space: nowrap; }}
.pred-rank-cell {{ text-align: center; width: 30px; color: #7f8c8d; font-size: 12px; }}
.snap-rank-header {{ cursor: pointer; user-select: none; text-align: center; width: 34px; padding: 6px 4px !important; }}
.snap-rank-cell {{ text-align: center; width: 34px; color: #8e44ad; font-size: 12px; font-weight: bold; padding: 6px 4px !important; }}

.overlap-box {{
  background: white; padding: 10px 15px; border-radius: 8px;
  box-shadow: 0 2px 5px rgba(0,0,0,0.1); font-size: 14px;
  color: #000000; margin-bottom: 20px; border-left: 5px solid #e74c3c;
}}
.top-nav-container {{ display: flex; margin-bottom: 15px; }}
.top-nav {{
  display: flex; background-color: #2c3e50;
  border-radius: 8px; overflow: hidden; width: fit-content;
}}
.nav-item {{
  padding: 8px 15px; color: #bdc3c7; text-align: center;
  cursor: pointer; font-weight: bold; text-decoration: none;
  transition: all 0.3s; font-size: 0.9em;
}}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}

@media (max-width: 600px) {{
  .styled-tableWide {{ font-size: 11px; margin: 0; }}
  .styled-tableWide th, .styled-tableWide td {{ padding: 3px 4px; }}
  .mobile-hide {{ display: none !important; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
/* === Chart Popup (V4) CSS는 build_chart_popup()이 주입 === */
</style>
</head>
<body>

<div class="top-nav-container">
  <div class="top-nav">
    <a href="kor_volume.html" class="nav-item active">거래대금</a>
    <a href="danta_journal.html" class="nav-item">매매일지</a>
    <a href="kor_volume_spike.html" class="nav-item">거래량 급증</a>
    <a href="kor_condition.html" class="nav-item">한국조건검색</a>
    <a href="us_condition.html" class="nav-item">미국조건검색</a>
  </div>
</div>

<p style="margin: 0 0 15px 0; color: #555; font-size: 0.9em;">
  데이터: {html.escape(update_time)} &nbsp;|&nbsp; 페이지: {now}
</p>

<h2 style="font-size: 1.1em; margin-top: 10px; border-bottom: 1px solid #27ae60; padding-bottom: 5px; color: #27ae60;">
  🎯 주도주(A 그룹) <span style="font-size:0.6em; color:#111; font-weight:normal;">당일 거래대금 1조↑ 실시간 주도 + (네이버테마·KR전종목·KR150) 1개↑ 확인 · 종합점수 60↑ · 급락(누적-7%/당일-5%)·외인기관 동시매도 제외</span>
</h2>
<div>{leader_table_html}</div>

<h2 style="font-size: 1.1em; margin-top: 10px; border-bottom: 1px solid #e67e22; padding-bottom: 5px; color: #e67e22;">
  🎯 주도주(B 그룹) <span style="font-size:0.6em; color:#111; font-weight:normal;">거래대금 주도(당일 1조↑ 또는 거래대금 트래킹) · 점수 45↑ 또는 당일 거래대금 유효 · 급락(누적-7%/당일-5%) 제외 — 확인소스·수급 미충족으로 A 미달</span>
</h2>
<div>{leader_table_b_html}</div>

<h2 style="font-size: 1.1em; margin-top: 10px; border-bottom: 1px solid #3498db; padding-bottom: 5px;">
  🎯 관심종목(MOM/LIME) 겹침 (+4% 이상)
</h2>
<div class="overlap-box">{overlap_html}</div>

<hr style="border:0; height:3px; background:#f1c40f; margin:25px 0;">

<h2>💰 거래대금 (+4% 이상) <span style="font-size:0.5em; font-weight:normal; margin-left:10px;"><span style="color:#e67e22;">O</span>주도주 <span style="color:#f1c40f;">★</span>judo <span style="color:#111;">●</span>ha <span style="color:#27ae60;">T</span>트래킹</span> <span style="font-size:0.5em; color:#e74c3c; font-weight:normal; margin-left:10px;">{html.escape(lead_summary)}</span></h2>
{main_table_html}

<h2 style="font-size: 1.1em; margin-top: 24px; border-bottom: 1px solid #8e44ad; padding-bottom: 5px; color: #8e44ad;">
  📊거래대금 트래킹(2주) <span style="font-size:0.75em; color:#aaa; font-weight:normal;">거래대금 1조↑ 종목, 등록 후 14일 추적</span>
</h2>
<div>{tracking_volume_html}</div>

<h2 style="font-size: 1.1em; margin-top: 24px; border-bottom: 1px solid #e67e22; padding-bottom: 5px; color: #e67e22;">
  📈 거래대금 순위 변화 (오늘) <span style="font-size:0.7em; color:#000; font-weight:normal; margin-left:8px;">+4% & TOP30 진입 종목, 빨간박스:5천억, 빨강노랑: 1조</span>
</h2>
<div>{intraday_chart_html}</div>

<script>
let sortCol = -1;
let sortAsc = true;

function sortTable(col) {{
  const table = document.getElementById('volTable');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const ths = table.querySelectorAll('thead th');

  if (sortCol === col) {{
    sortAsc = !sortAsc;
  }} else {{
    sortCol = col;
    sortAsc = true;
  }}

  // 모든 헤더 표시 초기화
  ths.forEach(th => th.classList.remove('sort-asc', 'sort-desc'));
  ths[col].classList.add(sortAsc ? 'sort-asc' : 'sort-desc');

  rows.sort((a, b) => {{
    const aCell = a.querySelectorAll('td')[col];
    const bCell = b.querySelectorAll('td')[col];
    const aText = aCell ? aCell.innerText.trim() : '';
    const bText = bCell ? bCell.innerText.trim() : '';

    // O 컬럼 (인덱스 6): O 있으면 1, 없으면 0
    if (col === 6) {{
      const aV = aText === 'O' ? 1 : 0;
      const bV = bText === 'O' ? 1 : 0;
      return sortAsc ? aV - bV : bV - aV;
    }}

    // NXT 컬럼 (인덱스 10): NXT 있으면 1, 없으면 0
    if (col === 10) {{
      const aV = aText === 'NXT' ? 1 : 0;
      const bV = bText === 'NXT' ? 1 : 0;
      return sortAsc ? aV - bV : bV - aV;
    }}

    // 숫자 파싱 (콤마, +, %, 억 제거)
    const aNum = parseFloat(aText.replace(/[,+%억]/g, ''));
    const bNum = parseFloat(bText.replace(/[,+%억]/g, ''));
    if (!isNaN(aNum) && !isNaN(bNum)) {{
      return sortAsc ? aNum - bNum : bNum - aNum;
    }}

    // 문자열 정렬
    return sortAsc ? aText.localeCompare(bText, 'ko') : bText.localeCompare(aText, 'ko');
  }});

  rows.forEach(r => tbody.appendChild(r));
}}
</script>
{popup_block}
</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] kor_volume.html updated at {OUT_HTML}")


if __name__ == "__main__":
    main()
