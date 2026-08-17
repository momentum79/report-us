# make_index_main_hub.py
# 첫 화면(index.html)으로 사용할 메인 허브 페이지 생성
# 1. Market Trend 테이블 (sco 4구간 당일 / 전일대비 증감)
# 2. market_regime_total.png 차트 임베딩

import csv
import io
import json
import re
from pathlib import Path
from datetime import datetime, timedelta

BASE       = Path(__file__).resolve().parent
STATS_FILE = BASE / "kr_signal_stats_total.json"
TRACK_FILE = BASE / "top3_etf_track_total.json"
PNG_FILE   = BASE / "market_regime_total.png"
PNG_HIST   = BASE / "market_regime_history_total.png"
OUT_HTML   = BASE / "main_hub.html"
AUTO_TRADE_KPI_FILE = BASE / "auto_trade_execution.json"
AUTO_TRADE_MARKER_FILE = BASE / "auto_trade_allone_marker.json"
TR_RUN_MARKER_FILE = BASE / "tr_run_marker.json"    # KR/US 매수 bat 실행마커 (0order/tr/tr_run_marker.py)
HOLDINGS_DAILY_CSV = BASE / "etf_history" / "holdings_daily.csv"
AI_CORE_FILE = BASE / "total_etf_combined_AI.html"

RECENT_TRADE_DAYS = 20      # 실행이력 표: 롤링 거래일 수
RECENT_TICKER_COLS = 6      # T1~T6

ZONE_LABELS = [
    ("sco ≥ 11",       "sco_zone_strong"),
    ("8 ≤ sco < 11",   "sco_zone_mid"),
    ("0 ≤ sco < 8",    "sco_zone_weak"),
    ("sco < 0",        "sco_zone_neg"),
]

# ── Top3 Leadership Card 설정 (0_top3_leadership_card.md 결정사항) ──
_LC_WEIGHTS  = [3, 2, 1]
_LC_WINDOW   = 16
_LC_SHIFT    = 5
_LC_MAX_PT   = _LC_WINDOW * sum(_LC_WEIGHTS)   # = 96
_LC_CATEGORIES = ['KR', 'US', 'Commodity', 'Metals', 'Bonds', 'Crypto']

_LC_NASDAQ_MULT_KR = {
    '487230', '371160', '0051G0', '0038A0', '0048K0', '0023A0',
    '195930', '478150', '453810', '446770', '449180', '449190', '241180',
}
_LC_FIXED_COMMODITY = {'PDBC', 'XLE', 'UNG', 'REMX', 'PICK', 'DBA'}
_LC_FIXED_METALS    = {'GLD', 'SLV', '411060'}
_LC_FIXED_BONDS     = {'AGG', 'BND', 'TLT', 'IEF', 'LQD', 'HYG'}
_LC_CRYPTO          = {'IBIT', 'ETHA'}

_LC_RE_DIGITS6   = re.compile(r'\d{6}')
_LC_RE_ALNUM6    = re.compile(r'[0-9A-Z]{6}')
_LC_RE_ALPHA     = re.compile(r'[A-Z]+')


def classify_ticker(ticker: str):
    """티커 → 카테고리 (KR/US/Commodity/Metals/Bonds/Crypto/None).
    순서: 자산 클래스 > NASDAQ_MULT_KR > 6자리 숫자(KR) > 알파벳혼합/순수(US)."""
    if not ticker:
        return None
    t = ticker.replace('**', '').replace('X_', '').strip()
    if not t:
        return None
    if t in _LC_FIXED_METALS:    return 'Metals'
    if t in _LC_FIXED_COMMODITY: return 'Commodity'
    if t in _LC_FIXED_BONDS:     return 'Bonds'
    if t in _LC_CRYPTO:          return 'Crypto'
    if t in _LC_NASDAQ_MULT_KR:  return 'US'
    if _LC_RE_DIGITS6.fullmatch(t):
        return 'KR'
    if _LC_RE_ALNUM6.fullmatch(t) and any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
        return 'US'
    if _LC_RE_ALPHA.fullmatch(t):
        return 'US'
    return None


def score_top3_window(track_data: dict, days):
    """days 리스트의 Top3를 카테고리별 점수 합산."""
    scores = {c: 0 for c in _LC_CATEGORIES}
    for d in days:
        row = track_data.get(d) or {}
        raw = (row.get('top3_tickers') or '').split(',')
        tics = [x.strip() for x in raw if x.strip()][:3]
        for i, tic in enumerate(tics):
            cat = classify_ticker(tic)
            if cat is not None:
                scores[cat] += _LC_WEIGHTS[i]
    return scores


def generate_insight(scores_today, scores_prev, flow, fill_today):
    """Money Flow → 인사이트 한 줄 (MD 결정 8 순서 그대로)."""
    kr_f     = flow.get('KR', 0)
    us_f     = flow.get('US', 0)
    comm_f   = flow.get('Commodity', 0)
    metals_f = flow.get('Metals', 0)
    bonds_f  = flow.get('Bonds', 0)
    kr_us_f  = kr_f + us_f
    cm_mt_f  = comm_f + metals_f

    if kr_f < -10 and us_f > 10:
        return "US로 자금 이동"
    if kr_us_f < -10 and cm_mt_f > 10:
        return "위험회피 + 인플레 헤지 모드"
    if kr_us_f < -10 and bonds_f > 5:
        return "Risk-off 채권 회귀"

    bonds_new  = scores_prev.get('Bonds', 0) == 0  and scores_today.get('Bonds', 0)  >= 8
    metals_new = scores_prev.get('Metals', 0) == 0 and scores_today.get('Metals', 0) >= 8
    comm_new   = scores_prev.get('Commodity', 0) == 0 and scores_today.get('Commodity', 0) >= 8
    if bonds_new or metals_new:
        return "🆕 Safe-haven 자금 유입 시작"
    if comm_new:
        return "🆕 Commodity rotation 시작"

    max_abs = max((abs(v) for v in flow.values()), default=0)
    if max_abs < 5:
        return "Leadership 안정 (큰 변화 없음)"
    return "혼합된 흐름"


def compute_leadership(track_data=None):
    """오늘 16d + 5일전 16d 점수 + Money Flow + Fill rate + Insight."""
    if track_data is None:
        if not TRACK_FILE.exists():
            return None
        try:
            track_data = json.loads(TRACK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None

    dates = sorted(track_data.keys())
    needed = _LC_WINDOW + _LC_SHIFT
    if len(dates) < needed:
        return None

    recent_dates  = dates[-_LC_WINDOW:]
    shifted_dates = dates[-(_LC_WINDOW + _LC_SHIFT):-_LC_SHIFT]

    scores_today = score_top3_window(track_data, recent_dates)
    scores_prev  = score_top3_window(track_data, shifted_dates)

    total_today = sum(scores_today.values())
    total_prev  = sum(scores_prev.values())
    fill_today  = (total_today / _LC_MAX_PT) * 100 if _LC_MAX_PT else 0
    fill_prev   = (total_prev  / _LC_MAX_PT) * 100 if _LC_MAX_PT else 0

    flow = {c: scores_today.get(c, 0) - scores_prev.get(c, 0) for c in _LC_CATEGORIES}
    insight = generate_insight(scores_today, scores_prev, flow, fill_today)

    return {
        'scores_today': scores_today,
        'scores_prev':  scores_prev,
        'flow':         flow,
        'fill_today':   fill_today,
        'fill_prev':    fill_prev,
        'total_today':  total_today,
        'total_prev':   total_prev,
        'today_date':   recent_dates[-1],
        'prev_date':    shifted_dates[-1],
        'insight':      insight,
    }


_LC_CAT_LABEL = {
    'KR':        '🇰🇷 KR Direct',
    'US':        '🇺🇸 US Equity',
    'Commodity': '🛢 Commodity / Energy',
    'Metals':    '🥇 Precious Metals',
    'Bonds':     '💵 Bonds',
    'Crypto':    '₿ Crypto',
}


def _lc_fill_visual(rate):
    """fill rate(0~100) → (opacity, weak_label_html)."""
    if rate >= 70:
        return ('1.0', '')
    if rate >= 40:
        return ('0.85', '')
    return ('0.6', '<div class="lc-weak-lbl">⚠️ 신호 약함</div>')


def build_leadership_card_html(leadership):
    """TODAY'S TOP3 LEADERSHIP 카드 HTML."""
    if leadership is None:
        return (
            '<div class="leadership-card-title">'
            '<span class="leadership-card-title-main">TODAY\'S TOP3 LEADERSHIP</span>'
            '</div>'
            '<div style="font-size:12px;color:#95a5a6;padding:6px 2px;">'
            f'데이터 부족 (≥{_LC_WINDOW + _LC_SHIFT}일 필요)'
            '</div>'
        )

    flow         = leadership['flow']
    scores_today = leadership['scores_today']
    scores_prev  = leadership['scores_prev']

    # 양쪽 모두 0인 카테고리는 표에서 제외 (컴팩트화)
    active_cats = [c for c in _LC_CATEGORIES
                   if scores_today.get(c, 0) != 0 or scores_prev.get(c, 0) != 0]
    # |Δ| desc → 큰 변화 위로
    active_cats.sort(key=lambda c: -abs(flow.get(c, 0)))

    rows = []
    for cat in active_cats:
        d       = flow.get(cat, 0)
        today_v = scores_today.get(cat, 0)
        prev_v  = scores_prev.get(cat, 0)
        absd    = abs(d)
        if absd >= 10:
            cls, icon = 'flow-strong', '🚨 '
        elif absd >= 5:
            cls, icon = 'flow-weak', '✦ '
        else:
            cls, icon = 'flow-noise', '· '
        arrow = '▲' if d > 0 else ('▼' if d < 0 else '·')
        sign  = '+' if d > 0 else ''
        rows.append(
            f'<tr class="{cls}">'
            f'<td class="lc-cat">{icon}{_LC_CAT_LABEL[cat]}</td>'
            f'<td class="lc-delta">{sign}{d}pt</td>'
            f'<td class="lc-detail">({prev_v} → {today_v})</td>'
            f'<td class="lc-arrow">{arrow}</td>'
            f'</tr>'
        )
    money_flow_html = '<table class="money-flow-table">' + ''.join(rows) + '</table>'

    insight_html = (
        f'<div class="leadership-insight">'
        f'<span class="lc-insight-tag">📌 Insight</span>'
        f'<span class="lc-insight-text">{leadership["insight"]}</span>'
        f'</div>'
    )

    today_op, today_weak = _lc_fill_visual(leadership['fill_today'])
    prev_op,  prev_weak  = _lc_fill_visual(leadership['fill_prev'])

    doughnut_html = (
        '<div class="doughnut-row">'
        '<div class="doughnut-wrap" style="opacity:' + today_op + ';">'
        f'<div class="doughnut-label">오늘 ({leadership["today_date"]})</div>'
        '<div class="doughnut-canvas-wrap"><canvas id="leadershipTodayChart"></canvas></div>'
        '<div class="doughnut-center">'
        f'<div class="dc-num">{leadership["total_today"]}<span>/{_LC_MAX_PT}</span></div>'
        f'<div class="dc-lbl">Fill {leadership["fill_today"]:.0f}%</div>'
        f'{today_weak}'
        '</div>'
        '</div>'
        '<div class="doughnut-wrap" style="opacity:' + prev_op + ';">'
        f'<div class="doughnut-label">5일 전 ({leadership["prev_date"]})</div>'
        '<div class="doughnut-canvas-wrap"><canvas id="leadershipPrevChart"></canvas></div>'
        '<div class="doughnut-center">'
        f'<div class="dc-num">{leadership["total_prev"]}<span>/{_LC_MAX_PT}</span></div>'
        f'<div class="dc-lbl">Fill {leadership["fill_prev"]:.0f}%</div>'
        f'{prev_weak}'
        '</div>'
        '</div>'
        '</div>'
    )

    card_html = (
        '<div class="leadership-card-title">'
        '<span class="leadership-card-title-main">TODAY\'S TOP3 LEADERSHIP</span>'
        f'<span class="lc-sub">16d window · 5d ago vs today</span>'
        '</div>'
        '<div class="leadership-body">'
        '<div class="lc-flow-section">'
        '<div class="lc-section-title">💸 Money Flow</div>'
        f'{money_flow_html}'
        f'{insight_html}'
        '</div>'
        f'{doughnut_html}'
        '</div>'
    )
    return card_html


def _fmt_invest_pct(v):
    """전략 투자비중 → '24.6%' (소수점 1자리). 값 없으면 '-'."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{f:.1f}%" if f > 0 else "-"


def _fmt_amount_manwon(v):
    """추천금액(만원) → '246만' / 천만 이상은 콤마 '1,234만'. 값 없으면 '-'."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return "-"
    return f"{int(v):,}만"


def _fmt_actual_manwon(v):
    """실투금액(만원). 0은 '하나도 안 담김'이라는 뜻이라 '-'(미상)과 구분해 '0'으로 찍는다."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        return "-"
    return f"{int(v):,}만" if v > 0 else "0"


def _load_tr_run_marker():
    """{날짜: {"KR": {"ran": True, ...}, "US": {...}}} — KR/US 매수 bat 실행마커."""
    try:
        data = json.loads(TR_RUN_MARKER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _tr_run_yn(marker, date_key, market, known_from):
    """그날 그 시장 매수 bat 을 돌렸는지 Y/N.
    마커가 생기기 전 날짜는 판정 근거가 없으므로 N 이 아니라 '-'(미상)."""
    day = marker.get(date_key)
    rec = day.get(market) if isinstance(day, dict) else None
    if isinstance(rec, dict) and rec.get("ran"):
        return "Y"
    if known_from and date_key >= known_from:
        return "N"
    return "-"


def _rate_text(ran, judged):
    return f"{round(ran / judged * 100):.0f}%" if judged else "-"


def build_auto_trade_kpi_html():
    """Compact weekly auto-trade execution KPI."""
    try:
        data = json.loads(AUTO_TRADE_KPI_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    records = data.get("records") if isinstance(data, dict) else []
    if not isinstance(records, list):
        records = []
    by_date = {str(r.get("date")): r for r in records if r.get("date")}

    today = datetime.today()
    week_start = today - timedelta(days=today.weekday())
    rows = []
    for i in range(5):
        d = week_start + timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        rec = by_date.get(key, {})
        yn = "Y" if rec.get("ran") else ("N" if key in by_date else "-")
        pct_text = _fmt_invest_pct(rec.get("invest_pct"))
        amount_text = _fmt_amount_manwon(rec.get("amount_manwon"))
        row_cls = " kpi-yes" if yn == "Y" else (" kpi-no" if yn == "N" else "")
        rows.append(
            f'<tr class="{row_cls}"><td class="kpi-date">{d.month}/{d.day}</td>'
            f'<td class="kpi-run">{yn}</td><td>{pct_text}</td><td>{amount_text}</td></tr>'
        )

    return (
        '<div class="auto-kpi-card">'
        '<table class="auto-kpi-table">'
        '<thead><tr><th class="kpi-date">날짜</th><th class="kpi-run">실행</th>'
        '<th>비중</th><th>금액</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</div>'
    )


_TICKER_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")


def _load_holdings_by_date():
    """날짜 → 그날 '주문용 최종 보유 목록' 티커(랭크순, 최대 6).
       track json의 holdings_tickers 가 정본이고,
       그게 없던 과거일은 holdings_daily.csv(상위 5) 로 메운다."""
    result = {}
    try:
        rows = csv.reader(io.StringIO(HOLDINGS_DAILY_CSV.read_text(encoding="utf-8-sig")))
        ranked = {}
        for r in rows:
            if len(r) < 4 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[0].strip()):
                continue
            try:
                rank = int(r[3])
            except (TypeError, ValueError):
                continue
            tk = r[1].strip()
            if _TICKER_RE.match(tk):
                ranked.setdefault(r[0].strip(), []).append((rank, tk))
        for d, items in ranked.items():
            result[d] = [t for _, t in sorted(items)]
    except Exception:
        pass

    try:
        track = json.loads(TRACK_FILE.read_text(encoding="utf-8"))
    except Exception:
        track = {}
    if isinstance(track, dict):
        for d, rec in track.items():
            tks = rec.get("holdings_tickers") if isinstance(rec, dict) else None
            if isinstance(tks, list) and tks:
                clean = [str(t).strip() for t in tks if _TICKER_RE.match(str(t).strip())]
                if clean:
                    result[str(d)] = clean

    return {d: v[:RECENT_TICKER_COLS] for d, v in result.items()}


def _recent_trade_dates(limit):
    """track json 키(=거래일) 기준 오늘까지의 최근 limit 거래일 오름차순."""
    try:
        track = json.loads(TRACK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(track, dict):
        return []
    today = datetime.today().strftime("%Y-%m-%d")
    dates = sorted(k for k in map(str, track.keys())
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", k) and k <= today)
    return dates[-limit:]


def build_auto_trade_recent_html():
    """최근 20거래일 롤링 실행 이력 표(최신일이 위) + 그날 주문용 최종 보유 티커 T1~T6.

    맨 앞 KR·US 열은 D:\\py\\0order\\tr 매수 bat 을 그날 돌렸는지만 Y/N 으로 남긴다.
      KR = 0000_kr_buy.bat / US = 0000_us_buy.bat 또는 0000_us_buy-회사.bat (둘 중 하나면 Y)
    제목의 비율은 KR / US / 통합ETF 순서."""
    try:
        data = json.loads(AUTO_TRADE_KPI_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    records = data.get("records") if isinstance(data, dict) else []
    if not isinstance(records, list):
        records = []
    by_date = {str(r.get("date")): r for r in records if r.get("date")}

    try:
        marker = json.loads(AUTO_TRADE_MARKER_FILE.read_text(encoding="utf-8"))
    except Exception:
        marker = {}
    if not isinstance(marker, dict):
        marker = {}

    # 실행여부를 판정할 근거가 아예 생기기 전 날짜는 N 이 아니라 '-' (미상)으로 둔다.
    known_from = min([*by_date, *marker], default="")

    tr_marker = _load_tr_run_marker()
    tr_known_from = min(tr_marker, default="")

    dates = _recent_trade_dates(RECENT_TRADE_DAYS)
    if not dates:
        return ""
    holdings = _load_holdings_by_date()

    rows = []
    ran_days = judged_days = 0
    tr_ran = {"KR": 0, "US": 0}
    tr_judged = {"KR": 0, "US": 0}
    for key in reversed(dates):
        try:
            d = datetime.strptime(key, "%Y-%m-%d")
        except Exception:
            continue
        rec = by_date.get(key)
        if rec is not None:
            yn = "Y" if rec.get("ran") else "N"
        elif (marker.get(key) or {}).get("ran"):
            yn = "Y"
        elif known_from and key >= known_from:
            yn = "N"
        else:
            yn = "-"
        if yn != "-":
            judged_days += 1
            ran_days += (yn == "Y")

        rec = rec or {}
        pct_text = _fmt_invest_pct(rec.get("invest_pct"))
        amount_text = _fmt_amount_manwon(rec.get("amount_manwon"))
        actual_text = _fmt_actual_manwon(rec.get("actual_manwon"))
        row_cls = "kpi-yes" if yn == "Y" else ("kpi-no" if yn == "N" else "")

        mkt_cells = ""
        for market in ("KR", "US"):
            m_yn = _tr_run_yn(tr_marker, key, market, tr_known_from)
            if m_yn != "-":
                tr_judged[market] += 1
                tr_ran[market] += (m_yn == "Y")
            m_cls = "mkt-y" if m_yn == "Y" else ("mkt-n" if m_yn == "N" else "mkt-na")
            mkt_cells += f'<td class="kpi-mkt {m_cls}">{m_yn}</td>'

        tks = holdings.get(key, [])
        tk_cells = "".join(
            f'<td class="kpi-tk{" kpi-tk-top" if i < 3 else ""}">'
            f'{tks[i] if i < len(tks) else ""}</td>'
            for i in range(RECENT_TICKER_COLS)
        )
        rows.append(
            f'<tr class="{row_cls}">{mkt_cells}'
            f'<td class="kpi-date">{d.month}/{d.day}</td><td class="kpi-run">{yn}</td>'
            f'<td>{pct_text}</td><td>{amount_text}</td>'
            f'<td class="kpi-actual">{actual_text}</td>{tk_cells}</tr>'
        )

    if not rows:
        return ""

    rate_text = _rate_text(ran_days, judged_days) if judged_days else "-%"
    # 비율 3개 = KR / US / 통합ETF
    rates_text = " / ".join([_rate_text(tr_ran["KR"], tr_judged["KR"]),
                             _rate_text(tr_ran["US"], tr_judged["US"]),
                             rate_text])
    tk_head = "".join(
        f'<th class="kpi-tk{" kpi-tk-top" if i < 3 else ""}">T{i + 1}</th>'
        for i in range(RECENT_TICKER_COLS)
    )

    return (
        '<div class="auto-kpi-card auto-kpi-month">'
        f'<div class="auto-kpi-title">최근 {len(dates)}거래일&nbsp;&nbsp;{ran_days}/{judged_days} · {rates_text}</div>'
        '<table class="auto-kpi-table">'
        f'<thead><tr><th class="kpi-mkt">KR</th><th class="kpi-mkt">US</th>'
        f'<th class="kpi-date">날짜</th><th class="kpi-run">실행</th><th>비중</th><th>금액</th>'
        f'<th class="kpi-actual">실투</th>{tk_head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</div>'
    )


def build_ai_core_html():
    """AI 관찰판(total_etf_combined_AI.html)의 AI Core Regime 카드
    (좌: Regime + 우: 🏆 Top AI Baskets)를 통째로 추출."""
    if not AI_CORE_FILE.exists():
        return ""
    try:
        h = AI_CORE_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    i = h.find('<div class="ai-core-card">')
    if i < 0:
        return ""
    # 카드 다음 형제 블록(basket-flow-card) 직전까지 잘라, 마지막 </div>로 마감
    j = h.find('<div class="basket-flow-card">', i)
    seg = h[i:j] if j > 0 else h[i:]
    k = seg.rfind('</div>')
    return (seg[:k + 6] if k >= 0 else seg).rstrip()


def load_stats() -> dict:
    if not STATS_FILE.exists():
        return {}
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_yesterday_zones() -> dict:
    """top3_etf_track_total.json 에서 전일 sco_zone 4개 값 반환"""
    if not TRACK_FILE.exists():
        return {}
    try:
        data = json.loads(TRACK_FILE.read_text(encoding="utf-8"))
        keys = sorted(data.keys())
        if len(keys) < 2:
            return {}
        yesterday_key = keys[-2]   # 오늘이 마지막이므로 바로 전날
        return data[yesterday_key]
    except Exception:
        return {}


def safe_float(value, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, str) and value.strip() == "":
            return default
        f = float(value)
        if f != f:  # NaN
            return default
        return f
    except Exception:
        return default


def safe_int(value, default=None):
    f = safe_float(value, None)
    if f is None:
        return default
    try:
        return int(round(f))
    except Exception:
        return default


def load_regime_latest():
    """market_regime_track_total.json에서 최신 row, 전일 row 반환.
    데이터 없거나 예외 발생 시 ({}, {}) 반환."""
    track_path = BASE / "market_regime_track_total.json"
    if not track_path.exists():
        return {}, {}
    try:
        data = json.loads(track_path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or len(data) == 0:
            return {}, {}
        data_sorted = sorted(data, key=lambda r: str(r.get("date", "")))
        latest = data_sorted[-1] if len(data_sorted) >= 1 else {}
        prev   = data_sorted[-2] if len(data_sorted) >= 2 else {}
        return (latest or {}), (prev or {})
    except Exception:
        return {}, {}


def fmt_num_delta(today, prev, good_when_up=True):
    """전일대비 변화 표시 + CSS class.
    반환: (표시문자열, css_class)
    """
    t = safe_float(today, None)
    p = safe_float(prev, None)
    if t is None or p is None:
        return "", ""
    diff = t - p
    # 정수처럼 보이는 경우 정수로
    if abs(diff - round(diff)) < 1e-9:
        diff_int = int(round(diff))
        if diff_int == 0:
            return "0", "diff-zero"
        sign = "▲ +" if diff_int > 0 else "▼ "
        body = str(diff_int) if diff_int > 0 else str(diff_int)  # 음수는 부호 포함
        if diff_int > 0:
            text = f"▲ +{diff_int}"
        else:
            text = f"▼ {diff_int}"
    else:
        if abs(diff) < 1e-9:
            return "0", "diff-zero"
        if diff > 0:
            text = f"▲ +{diff:.1f}"
        else:
            text = f"▼ {diff:.1f}"

    if diff > 0:
        cls = "diff-good" if good_when_up else "diff-bad"
    elif diff < 0:
        cls = "diff-bad" if good_when_up else "diff-good"
    else:
        cls = "diff-zero"
    return text, cls


def get_regime_comment(latest, prev):
    """고정 룰 기반 코멘트 생성."""
    score = safe_float(latest.get("regime_map_score"), None)
    if score is None:
        return "Regime 요약 데이터 생성 대기 중입니다."

    prev_score   = safe_float(prev.get("regime_map_score"), None)
    score_delta  = (score - prev_score) if prev_score is not None else 0.0

    strong_today = safe_float(latest.get("strong_zone_cnt"), 0)
    strong_prev  = safe_float(prev.get("strong_zone_cnt"), strong_today)
    strong_delta = strong_today - strong_prev

    risk_today   = safe_float(latest.get("risk_zone_cnt"), 0)
    risk_prev    = safe_float(prev.get("risk_zone_cnt"), risk_today)
    risk_delta   = risk_today - risk_prev

    if score < 15:
        return "약세 구역 비중이 높고 리더십이 부족합니다. 현금 비중을 우선하고 신규 진입은 최소화하는 구간입니다."
    if score < 25 and score_delta < -3:
        return "시장 내부 체력이 빠르게 약화되고 있습니다. 강한 구역 ETF는 감소하고 약세 구역 ETF가 확대되었습니다."
    if strong_delta < 0 and risk_delta > 0:
        return "강한 구역 ETF는 줄고 약세 구역 ETF가 증가했습니다. 신규 매수는 Top 후보 중심으로 제한 접근이 유리합니다."
    if strong_delta > 0 and risk_delta < 0:
        return "리더십 구역이 확대되고 약세 구역이 감소하고 있습니다. 시장 내부 개선 흐름이 나타나고 있습니다."
    if score >= 55:
        return "시장 내부 강도가 양호합니다. 강한 구역 ETF가 유지되고 있어 기존 전략 비중을 유지할 수 있습니다."
    return "시장 방향성이 뚜렷하지 않습니다. 강한 ETF와 약한 ETF가 혼재되어 있어 신규 매수는 선별적으로 접근하세요."


def _regime_state_color(state):
    """시장판정 라벨 색상 (과하지 않게)."""
    mapping = {
        "강세 확산": "#1e7e34",
        "강세 유지": "#27ae60",
        "중립/선별": "#2c3e50",
        "약세 경계": "#d35400",
        "약세 확산": "#c0392b",
        "위험 회피": "#922b21",
    }
    return mapping.get(state, "#7f8c8d")


def build_regime_summary_card():
    """TODAY'S REGIME 카드 HTML 생성."""
    latest, prev = load_regime_latest()

    score_today = safe_float(latest.get("regime_map_score"), None)
    score_prev  = safe_float(prev.get("regime_map_score"), None)
    state       = (latest.get("regime_state") or "").strip()
    total_univ  = safe_int(latest.get("total_universe"), None)

    strong_today = safe_int(latest.get("strong_zone_cnt"), None)
    strong_prev_v = safe_int(prev.get("strong_zone_cnt"), None)
    risk_today   = safe_int(latest.get("risk_zone_cnt"), None)
    risk_prev_v  = safe_int(prev.get("risk_zone_cnt"), None)
    worst_today  = safe_int(latest.get("worst_zone_cnt"), None)
    worst_prev_v = safe_int(prev.get("worst_zone_cnt"), None)

    prev_date = (prev.get("date") or "").strip() if isinstance(prev, dict) else ""

    # Score
    if score_today is None:
        score_main_html = '<div class="regime-score-value">-</div>'
        score_sub_html  = '<div class="regime-score-sub">/ 100</div>'
        score_delta_html = ""
    else:
        # 정수면 정수로, 아니면 소수1자리
        if abs(score_today - round(score_today)) < 1e-9:
            score_disp = str(int(round(score_today)))
        else:
            score_disp = f"{score_today:.1f}"
        score_main_html = f'<div class="regime-score-value">{score_disp}</div>'
        score_sub_html  = '<div class="regime-score-sub">/ 100</div>'
        d_text, d_cls = fmt_num_delta(score_today, score_prev, good_when_up=True)
        if d_text:
            prev_disp = ""
            if score_prev is not None:
                prev_disp = f' <span class="regime-prev-label">(전일 {int(round(score_prev)) if abs(score_prev-round(score_prev))<1e-9 else f"{score_prev:.1f}"})</span>'
            score_delta_html = f'<div class="regime-delta {d_cls}">{d_text}{prev_disp}</div>'
        else:
            score_delta_html = ""

    # 시장판정
    if not state:
        state_disp = "데이터 대기"
        state_color = "#7f8c8d"
    else:
        state_disp = state
        state_color = _regime_state_color(state)

    # zone cards helper
    def _zone_block(label, today_v, prev_v, total, good_up):
        if today_v is None:
            main = "-"
            ratio = ""
            delta_html = ""
        else:
            if total is not None and total > 0:
                main = f"{today_v}개 / {total}개"
            else:
                main = f"{today_v}개"
            d_text, d_cls = fmt_num_delta(today_v, prev_v, good_when_up=good_up)
            if d_text:
                prev_disp = f' <span class="regime-prev-label">(전일 {prev_v}개)</span>' if prev_v is not None else ""
                delta_html = f'<div class="regime-delta {d_cls}">{d_text}{prev_disp}</div>'
            else:
                delta_html = ""
            ratio = ""
        return (
            f'<div class="regime-metric-card">'
            f'  <div class="regime-metric-label">{label}</div>'
            f'  <div class="regime-metric-value">{main}</div>'
            f'  {delta_html}'
            f'</div>'
        )

    strong_html = _zone_block("Strong Zone", strong_today, strong_prev_v, total_univ, good_up=True)
    risk_html   = _zone_block("Risk Zone",   risk_today,   risk_prev_v,   total_univ, good_up=False)
    worst_html  = _zone_block("Worst Zone",  worst_today,  worst_prev_v,  total_univ, good_up=False)

    comment_text = get_regime_comment(latest, prev)

    prev_label_html = f'<span class="regime-prev-date">(전일대비 {prev_date})</span>' if prev_date else ""

    card_html = f"""
    <div class="regime-card-title">
      <span class="regime-card-title-main">TODAY'S REGIME</span>
      {prev_label_html}
    </div>
    <div class="regime-card-grid">
      <div class="regime-metric-card regime-score-card">
        <div class="regime-metric-label">Regime Map Score</div>
        <div class="regime-score-row">
          {score_main_html}
          {score_sub_html}
        </div>
        {score_delta_html}
      </div>
      <div class="regime-metric-card regime-state-card">
        <div class="regime-metric-label">시장판정</div>
        <div class="regime-state-value" style="color:{state_color};">{state_disp}</div>
      </div>
      {strong_html}
      {risk_html}
      {worst_html}
    </div>
    <div class="regime-comment">
      <span class="regime-comment-tag">💬 COMMENT</span>
      <span class="regime-comment-text">{comment_text}</span>
    </div>
    """
    return card_html


def fmt_diff(today_val, yest_val, key):
    """전일 대비 증감 문자열 + CSS 클래스 반환"""
    if yest_val is None:
        return "-", ""
    try:
        diff = int(today_val) - int(yest_val)
        if diff == 0:
            return "0", "diff-zero"
            
        sign_str = f"+{diff}" if diff > 0 else str(diff)
        
        # 구간(key)에 따른 좋고 나쁨 분기
        if key == "sco_zone_strong":      # sco >= 11 (제일 위)
            cls = "diff-good" if diff > 0 else "diff-bad"
        elif key == "sco_zone_neg":       # sco < 0 (제일 아래)
            cls = "diff-bad" if diff > 0 else "diff-good"
        else:                             # 8 <= sco < 11, 0 <= sco < 8 (중간 두 구간)
            cls = "diff-black"
            
        return sign_str, cls
    except Exception:
        return "-", ""


def main():
    stats = load_stats()
    yest  = load_yesterday_zones()
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    update_time = stats.get("update_time", now)

    # --- 데이터 미리 수집 및 하이라이트 대상 선정 ---
    row_data = []
    max_val = -1
    max_idx = -1
    
    for i, (label, key) in enumerate(ZONE_LABELS):
        val = stats.get(key, 0)
        row_data.append((label, key, val))
        if val > max_val:
            max_val = val
            max_idx = i

    # --- Market Trend 테이블 rows 생성 ---
    rows_html = ""
    # 비율 계산을 위한 전체 합계 산출
    total_sum      = sum(val for _, _, val in row_data if val is not None)
    yest_total_sum = sum(yest.get(key, 0) or 0 for _, key, _ in row_data)

    for i, (label, key, today_val) in enumerate(row_data):
        yest_val  = yest.get(key)
        today_str = str(today_val) if today_val is not None else "-"
        diff_str, diff_cls = fmt_diff(today_val, yest_val, key)

        # 오늘 비율 계산
        ratio_val = 0
        ratio_str = "0%"
        if total_sum > 0 and today_val is not None:
            ratio_val = round((today_val / total_sum) * 100)
            ratio_str = f"{ratio_val}%"

        # 전일 비율 계산
        yest_ratio_val = None
        yest_ratio_str = ""
        if yest_total_sum > 0 and yest_val is not None:
            yest_ratio_val = round((int(yest_val) / yest_total_sum) * 100)
            yest_ratio_str = f'<span style="color:#888;font-weight:400;font-size:11px;"> ({yest_ratio_val}%)</span>'

        # 비율 색상: 전일比와 동일한 로직
        if yest_ratio_val is None:
            ratio_color = "#2c3e50"
        else:
            ratio_diff = ratio_val - yest_ratio_val
            if ratio_diff == 0:
                ratio_color = "#95a5a6"
            elif key == "sco_zone_strong":
                ratio_color = "#27ae60" if ratio_diff > 0 else "#e74c3c"
            elif key == "sco_zone_neg":
                ratio_color = "#e74c3c" if ratio_diff > 0 else "#27ae60"
            else:
                ratio_color = "#2c3e50"

        ratio_str = f'<b style="color:{ratio_color};">{ratio_str}</b>{yest_ratio_str}'

        # 당일 개수가 최대인 행에만 강조 클래스 부여
        row_cls = "row-strong" if i == max_idx else ""

        rows_html += (
            f'<tr class="{row_cls}">'
            f'<td class="zone-label">{label}</td>'
            f'<td class="zone-count">{today_str}</td>'
            f'<td class="zone-diff {diff_cls}">{diff_str}</td>'
            f'<td class="zone-ratio" style="white-space:nowrap;">{ratio_str}</td>'
            f'</tr>\n'
        )

    # --- PNG 차트 (base64 임베드 or 상대경로) ---
    # 같은 폴더이므로 상대경로로 참조
    png_src = "market_regime_total.png"
    if not PNG_FILE.exists():
        chart_html = '<p style="color:#999;font-size:12px;">차트 생성 대기 중...</p>'
    else:
        chart_html = (
            f'<img src="{png_src}" alt="Market Regime Map" '
            f'style="width:100%;max-width:900px;height:auto;border-radius:8px;'
            f'box-shadow:0 2px 8px rgba(0,0,0,0.15);">'
        )

    # --- 히스토리 동적 차트 ---
    chart_hist_html = """
    <div class="regime-hist-box" style="background: #fff; padding: 12px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); max-width: 60%;">
        <div style="display: flex; gap: 6px; margin-bottom: 10px; justify-content: flex-end;">
            <button class="hist-btn" data-period="1M">1M</button>
            <button class="hist-btn" data-period="3M">3M</button>
            <button class="hist-btn" data-period="6M">6M</button>
            <button class="hist-btn" data-period="1Y">1Y</button>
            <button class="hist-btn active" data-period="ALL">ALL</button>
        </div>
        <div class="regime-hist-canvas" style="position: relative; height: 420px; width: 100%;">
            <canvas id="regimeHistoryChart"></canvas>
        </div>
    </div>
    """

    # --- JSON 데이터 직접 임베딩 (CORS 방지) ---
    track_file_path = BASE / "market_regime_track_total.json"
    if track_file_path.exists():
        try:
            track_json_str = track_file_path.read_text(encoding="utf-8")
        except Exception:
            track_json_str = "[]"
    else:
        track_json_str = "[]"

    # --- 전체 avg_sco 요약 ---
    avg_sco    = stats.get("avg_sco", "-")
    total_cnt  = stats.get("total_cnt", "-")
    invest_pct = stats.get("invest_pct", "-")

    # --- TODAY'S REGIME 카드 ---
    regime_card_html = build_regime_summary_card()

    # --- TODAY'S TOP3 LEADERSHIP 카드 ---
    leadership_data      = compute_leadership()
    leadership_card_html = build_leadership_card_html(leadership_data)
    leadership_json_str  = json.dumps(leadership_data, ensure_ascii=False) if leadership_data else "null"
    # 주간 5일창 KPI 표는 최근 거래일 표와 중복이라 제거 (build_auto_trade_kpi_html 미사용)
    auto_trade_month_html = build_auto_trade_recent_html()
    ai_core_html         = build_ai_core_html()

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>Market Overview</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Segoe UI', -apple-system, sans-serif;
  background: #f0f2f5;
  color: #2c3e50;
  padding: 10px;
  line-height: 1.3;
}}

/* ── 상단 네비 ── */
.top-nav {{
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  background: #2c3e50;
  border-radius: 8px;
  padding: 6px 8px;
  margin-bottom: 10px;
}}
.nav-item {{
  padding: 5px 12px;
  color: #bdc3c7;
  text-decoration: none;
  font-weight: bold;
  font-size: 0.82em;
  border-radius: 5px;
  transition: all 0.2s;
  white-space: nowrap;
}}
.nav-item:hover {{ background: #34495e; color: #fff; }}
.nav-item.active {{ background: #e67e22; color: #fff; }}

/* ── 히스토리 차트 버튼 ── */
.hist-btn {{
  background: #ecf0f1; border: none; padding: 4px 12px; border-radius: 4px;
  cursor: pointer; font-weight: bold; font-size: 11px; color: #7f8c8d;
  transition: all 0.2s;
}}
.hist-btn:hover {{ background: #bdc3c7; color: #2c3e50; }}
.hist-btn.active {{ background: #e67e22; color: #fff; }}

/* ── 본문 레이아웃: 세로 배치 ── */
.main-layout {{
  display: flex;
  flex-direction: column;
  gap: 12px;
}}
.left-panel {{
  flex: 0 0 auto;
  min-width: 200px;
}}
.right-panel {{
  flex: 1 1 300px;
  min-width: 280px;
}}

/* ── 섹션 헤더 ── */
.section-title {{
  font-size: 0.82em;
  font-weight: 700;
  color: #7f8c8d;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 5px;
}}

/* ── Market Trend 테이블 ── */
.trend-table {{
  width: auto;
  min-width: 300px;
  border-collapse: collapse;
  font-size: 13px;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,0.1);
}}
.trend-table th {{
  background: #2c3e50;
  color: #fff;
  padding: 5px 10px;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
}}
.trend-table td {{
  padding: 4px 10px;
  border-bottom: 1px solid #f0f0f0;
  text-align: center;
}}
.trend-table td.zone-label {{
  text-align: left;
  font-family: monospace;
  font-size: 12px;
  color: #555;
  white-space: nowrap;
  font-weight: 600;
}}
.trend-table td.zone-count {{
  font-weight: 700;
  font-size: 14px;
  color: #2c3e50;
}}
.trend-table td.zone-ratio {{
  color: #7f8c8d;
  font-size: 12px;
}}
.trend-table .row-strong {{
  background: #fffde7;
}}
.trend-table .row-strong td.zone-count {{
  color: #e67e22;
}}
.diff-good  {{ color: #27ae60; font-weight: 600; }} /* 녹색: 좋음 */
.diff-bad   {{ color: #e74c3c; font-weight: 600; }} /* 빨간색: 나쁨 */
.diff-black {{ color: #2c3e50; font-weight: 600; }} /* 검은색: 중립 */
.diff-zero  {{ color: #95a5a6; }}

/* ── 요약 뱃지 ── */
.summary-row {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 7px;
}}
.badge {{
  background: #ecf0f1;
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 14px;
  color: #555;
}}
.badge b {{ color: #2c3e50; }}

/* ── 업데이트 시간 ── */
.meta {{
  font-size: 11px;
  color: #aaa;
  margin-top: 5px;
}}

/* ── 상단 2열 (Market Trend + TODAY'S REGIME) ── */
.top-summary-row {{
  display: flex;
  flex-direction: row;
  gap: 14px;
  align-items: stretch;
  flex-wrap: wrap;
}}
.top-summary-row .left-panel {{
  flex: 0 0 auto;
  min-width: 280px;
}}
.regime-summary-card {{
  flex: 0 0 auto;
  min-width: 320px;
  background: #fff;
  border-radius: 10px;
  padding: 12px 14px 14px 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.10);
  border: 1px solid #f0e6da;
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.regime-card-title {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid #f3e7d6;
  padding-bottom: 6px;
}}
.regime-card-title-main {{
  font-size: 14px;
  font-weight: 700;
  color: #2c3e50;
  letter-spacing: 0.04em;
}}
.regime-prev-date {{
  font-size: 11px;
  color: #95a5a6;
}}
.regime-card-grid {{
  display: grid;
  grid-template-columns: repeat(5, auto);
  gap: 8px;
}}
.regime-metric-card {{
  background: #fafbfc;
  border: 1px solid #ececec;
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}}
.regime-score-card {{
  background: #fffaf3;
  border-color: #f1d9b1;
}}
.regime-state-card {{
  background: #fff5f0;
  border-color: #f1c8b8;
  align-items: center;
  justify-content: center;
  text-align: center;
}}
.regime-metric-label {{
  font-size: 11px;
  color: #7f8c8d;
  font-weight: 600;
  letter-spacing: 0.02em;
}}
.regime-metric-value {{
  font-size: 15px;
  font-weight: 700;
  color: #2c3e50;
}}
.regime-score-row {{
  display: flex;
  align-items: baseline;
  gap: 6px;
}}
.regime-score-value {{
  font-size: 32px;
  font-weight: 800;
  color: #e67e22;
  line-height: 1;
}}
.regime-score-sub {{
  font-size: 12px;
  color: #95a5a6;
  font-weight: 600;
}}
.regime-state-value {{
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.02em;
}}
.regime-delta {{
  font-size: 11px;
  font-weight: 700;
}}
.regime-prev-label {{
  color: #95a5a6;
  font-weight: 500;
  font-size: 10.5px;
}}
.regime-comment {{
  background: #fff8ee;
  border: 1px solid #f5d9a8;
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 12px;
  color: #5a4630;
  line-height: 1.5;
  display: flex;
  gap: 8px;
  align-items: flex-start;
}}
.regime-comment-tag {{
  font-weight: 700;
  color: #b9772b;
  white-space: nowrap;
}}
.regime-comment-text {{
  color: #5a4630;
}}

@media (max-width: 900px) {{
  .top-summary-row {{ flex-direction: column; }}
  .regime-card-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .regime-state-card {{ grid-column: span 2; }}
}}
@media (max-width: 600px) {{
  .trend-table {{ font-size: 12px; }}
  .trend-table td {{ padding: 4px 8px; }}
  .regime-score-value {{ font-size: 26px; }}
}}
@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
/* 모바일: Market Regime History 를 화면폭에 꽉 채움 (PC 60% 유지) */
@media (max-width: 767px) {{
  .regime-hist-box {{ max-width: 100% !important; padding: 8px !important; }}
  .regime-hist-canvas {{ height: 300px !important; }}
}}

/* ── Top3 Leadership 카드 (컴팩트) ── */
.leadership-card {{
  background: #fff;
  border-radius: 10px;
  padding: 10px 12px 12px 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.10);
  border: 1px solid #f0e6da;
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-self: flex-start;
  width: fit-content;
  min-width: 320px;
}}
.leadership-kpi-row {{
  display: flex;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}}
/* 리더십 카드 + AI Core를 세로로 쌓아 우측 누적표 옆 좌측 하단 공백을 채움 */
.leadership-left-col {{
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-self: flex-start;
  min-width: 0;
}}
.auto-kpi-card {{
  background: #fff;
  border-radius: 8px;
  padding: 10px 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  border: 1px solid #edf0f2;
  width: max-content;
}}
.auto-kpi-table {{
  width: max-content;
  border-collapse: collapse;
  table-layout: auto;
  font-size: 15px;
  line-height: 1.35;
  font-variant-numeric: tabular-nums;
}}
.auto-kpi-table th,
.auto-kpi-table td {{
  padding: 4px 11px;
  white-space: nowrap;
  text-align: right;
  border-bottom: 1px solid #f0f2f4;
}}
/* 열 위치가 아니라 클래스로 잡는다 - 표 앞에 KR·US 열이 붙어도 어긋나지 않게. */
.auto-kpi-table th.kpi-date,
.auto-kpi-table td.kpi-date {{ text-align: left; }}
.auto-kpi-table th.kpi-run,
.auto-kpi-table td.kpi-run {{
  text-align: center;
  padding-left: 2px;
  padding-right: 2px;
}}
.auto-kpi-table th.kpi-mkt,
.auto-kpi-table td.kpi-mkt {{
  text-align: center;
  padding-left: 5px;
  padding-right: 5px;
  font-weight: 800;
}}
.auto-kpi-table th.kpi-mkt {{ font-size: 13px; color: #7f8c8d; font-weight: 700; }}
.auto-kpi-table td.mkt-y  {{ color: #1f8f4d; }}
.auto-kpi-table td.mkt-n  {{ color: #c0392b; }}
.auto-kpi-table td.mkt-na {{ color: #b9c2c9; font-weight: 600; }}
.auto-kpi-table th {{
  color: #2c3e50;
  font-weight: 800;
  font-size: 15px;
  border-bottom: 1px solid #d9dee4;
}}
.auto-kpi-table th.kpi-tk,
.auto-kpi-table td.kpi-tk {{
  text-align: center;
  padding: 4px 6px;
  font-size: 12.5px;
  color: #34495e;
}}
.auto-kpi-table th.kpi-tk {{ font-size: 12.5px; color: #7f8c8d; }}
/* Top3(T1~T3)만 살짝 강조 */
.auto-kpi-table td.kpi-tk-top {{ font-weight: 700; color: #1f2d3d; }}
.auto-kpi-table th.kpi-tk-top {{ font-weight: 700; color: #566573; }}
.auto-kpi-table td.kpi-actual {{ color: #2c3e50; font-weight: 700; }}
.auto-kpi-table th.kpi-actual,
.auto-kpi-table td.kpi-actual {{ border-right: 1px solid #e6eaee; }}
.auto-kpi-table th.kpi-mkt:nth-child(2),
.auto-kpi-table td.kpi-mkt:nth-child(2) {{ border-right: 1px solid #e6eaee; }}
.auto-kpi-table tr:last-child td {{ border-bottom: none; }}
.auto-kpi-table tr.kpi-yes td.kpi-run {{ color: #1f8f4d; font-weight: 800; }}
.auto-kpi-table tr.kpi-no td.kpi-run {{ color: #c0392b; font-weight: 800; }}
.auto-kpi-title {{
  font-size: 13px;
  font-weight: 700;
  color: #34495e;
  margin-bottom: 6px;
  white-space: nowrap;
  letter-spacing: -0.2px;
}}
.auto-kpi-month {{ align-self: flex-start; }}
.leadership-card-title {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid #f3e7d6;
  padding-bottom: 4px;
}}
.leadership-card-title-main {{
  font-size: 13px;
  font-weight: 700;
  color: #2c3e50;
  letter-spacing: 0.04em;
}}
.lc-sub {{
  font-size: 10.5px;
  color: #95a5a6;
  font-weight: 500;
}}
.leadership-body {{
  display: flex;
  gap: 18px;
  align-items: flex-start;
  flex-wrap: wrap;
  justify-content: flex-start;
}}
.lc-flow-section {{
  flex: 0 1 auto;
  max-width: 360px;
  min-width: 240px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}}
.lc-section-title {{
  font-size: 11.5px;
  font-weight: 700;
  color: #5a4630;
}}
.money-flow-table {{
  width: auto;
  border-collapse: collapse;
  font-size: 12px;
}}
.money-flow-table td {{
  padding: 2.5px 10px 2.5px 4px;
  border-bottom: 1px solid #f6f1ea;
  line-height: 1.3;
}}
.money-flow-table td:last-child {{ padding-right: 4px; }}
.money-flow-table tr:last-child td {{ border-bottom: none; }}
.money-flow-table td.lc-cat   {{ text-align: left; color: #2c3e50; white-space: nowrap; }}
.money-flow-table td.lc-delta {{ text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.money-flow-table td.lc-detail{{ text-align: right; color: #95a5a6; font-size: 10.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.money-flow-table td.lc-arrow {{ text-align: center; width: 18px; }}
.money-flow-table tr.flow-strong td {{ background: #fff3f0; }}
.money-flow-table tr.flow-strong td.lc-cat   {{ color: #c0392b; font-weight: 700; }}
.money-flow-table tr.flow-strong td.lc-delta {{ color: #c0392b; }}
.money-flow-table tr.flow-weak td.lc-cat   {{ color: #2c3e50; }}
.money-flow-table tr.flow-weak td.lc-delta {{ color: #2c3e50; }}
.money-flow-table tr.flow-noise td {{ color: #b5b5b5; font-size: 10.5px; }}
.leadership-insight {{
  background: #fff8ee;
  border: 1px solid #f5d9a8;
  border-radius: 5px;
  padding: 5px 8px;
  font-size: 11.5px;
  color: #5a4630;
  display: flex;
  gap: 6px;
  align-items: flex-start;
  line-height: 1.4;
}}
.lc-insight-tag  {{ font-weight: 700; color: #b9772b; white-space: nowrap; font-size: 11px; }}
.lc-insight-text {{ color: #5a4630; }}
.doughnut-row {{
  display: flex;
  gap: 10px;
  flex: 0 1 auto;
  justify-content: flex-start;
}}
.doughnut-wrap {{
  flex: 0 0 180px;
  max-width: 200px;
  position: relative;
}}
.doughnut-label {{
  text-align: center;
  font-size: 10.5px;
  color: #7f8c8d;
  margin-bottom: 2px;
  font-weight: 600;
}}
.doughnut-canvas-wrap {{
  position: relative;
  height: 150px;
}}
.doughnut-center {{
  position: absolute;
  top: calc(50% + 7px);
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  pointer-events: none;
}}
.dc-num {{
  font-size: 15px;
  font-weight: 800;
  color: #2c3e50;
  line-height: 1;
}}
.dc-num span {{
  font-size: 10px;
  color: #95a5a6;
  font-weight: 500;
}}
.dc-lbl {{
  font-size: 9.5px;
  color: #7f8c8d;
  margin-top: 1px;
}}
.lc-weak-lbl {{
  font-size: 9.5px;
  color: #c0392b;
  margin-top: 2px;
  font-weight: 600;
}}
@media (max-width: 780px) {{
  .leadership-body {{ flex-direction: column; }}
  .lc-flow-section {{ max-width: 100%; }}
  .doughnut-row {{ width: 100%; justify-content: space-around; }}
  /* T1~T6 6열이 붙어 폭이 늘어난 실행이력 표: 카드 안에서만 가로 스크롤 */
  .auto-kpi-card {{ width: 100%; overflow-x: auto; }}
  .auto-kpi-table th.kpi-tk,
  .auto-kpi-table td.kpi-tk {{ padding: 4px 4px; font-size: 11px; }}
  .auto-kpi-table th.kpi-mkt,
  .auto-kpi-table td.kpi-mkt {{ padding: 4px 3px; font-size: 13px; }}
}}

/* ── AI Core Regime 박스 (미국요약/AI 관찰판에서 이동) ── */
.ai-core-section {{ margin: 0; }}
.ai-core-card {{ display:flex; gap:14px; background:linear-gradient(135deg,#fffbea,#fff5e1); border:1px solid #f0b400; padding:12px 14px; border-radius:10px; margin:6px 0 10px 0; box-shadow:0 2px 6px rgba(0,0,0,0.08); flex-wrap:wrap; width:fit-content; max-width:760px; align-self:flex-start; }}
.ai-core-left {{ flex:0 0 180px; min-width:170px; }}
.ai-core-right {{ flex:0 1 auto; min-width:220px; max-width:520px; }}
.ai-top-title {{ font-size:0.82em; font-weight:bold; color:#2c3e50; margin-bottom:4px; }}
.ai-top-list {{ display:grid; grid-template-columns:24px auto 1fr auto; align-items:baseline; column-gap:10px; row-gap:2px; width:max-content; max-width:100%; font-size:0.86em; }}
.ai-top-row {{ display:contents; }}
.ai-top-rank {{ font-weight:bold; color:#7f8c8d; text-align:left; white-space:nowrap; padding:1px 0; }}
.ai-top-name {{ font-weight:700; color:#2c3e50; white-space:nowrap; padding:1px 0; }}
.ai-top-score {{ grid-column:3/4; justify-self:end; font-weight:bold; color:#d35400; text-align:right; white-space:nowrap; padding:1px 0; padding-right:10px; min-width:3.5em; }}
.ai-top-cnt {{ grid-column:4/5; justify-self:end; color:#888; font-size:0.82em; text-align:right; white-space:nowrap; padding:1px 0; min-width:1.5em; }}
.ai-core-help {{ margin-top:8px; padding-top:6px; border-top:1px dashed #f1c40f; font-size:0.72em; color:#95a5a6; line-height:1.35; }}
.ai-core-help b {{ color:#7f8c8d; font-weight:700; }}
.ai-core-label {{ font-size:0.76em; color:#7f8c8d; margin-bottom:1px; }}
.ai-core-score {{ font-size:2.1em; font-weight:800; line-height:1.05; margin-bottom:3px; }}
.ai-core-state {{ display:inline-block; padding:2px 9px; border-radius:12px; color:#fff; font-weight:bold; font-size:0.82em; margin-bottom:5px; }}
.ai-core-state-row {{ display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin-bottom:4px; }}
.ai-breadth-state {{ font-size:0.78em; }}
.ai-core-rdg {{ display:flex; gap:6px; margin:3px 0 4px 0; flex-wrap:wrap; }}
.ai-rdg-cell {{ display:inline-flex; align-items:baseline; gap:3px; background:#fff; border:1px solid #f1c40f; border-radius:6px; padding:1px 7px; font-size:0.78em; line-height:1.2; }}
.ai-rdg-lbl {{ color:#888; font-weight:600; }}
.ai-rdg-val {{ color:#2c3e50; font-weight:700; }}
.ai-core-dup {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; font-size:0.78em; margin-top:4px; }}
.ai-dup-pill {{ display:inline-block; padding:1px 7px; border-radius:8px; color:#fff; font-weight:bold; font-size:0.92em; }}
.ai-core-dup-meta {{ color:#888; }}
.ai-core-dup-contrib {{ font-size:0.78em; color:#555; margin:2px 0 4px 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.ai-core-breadth {{ font-size:0.82em; margin:3px 0; }}
.ai-core-breadth span {{ display:inline-block; padding:1px 7px; margin-right:3px; border-radius:8px; font-weight:bold; }}
.ai-b-strong {{ background:#d5f5e3; color:#1d8348; }} .ai-b-mid {{ background:#fef9e7; color:#b7950b; }}
.ai-b-weak {{ background:#ebebeb; color:#555; }} .ai-b-neg {{ background:#fadbd8; color:#c0392b; }}
.ai-core-meta {{ font-size:0.76em; color:#888; }}
</style>
</head>
<body>

<nav class="top-nav">
  <a href="main_hub.html" class="nav-item active">상황판</a>
  <a href="order.html" class="nav-item">주문</a>
  <a href="summary.html" class="nav-item">요약</a>
  <a href="danta_chart.html" class="nav-item">단타</a>
  <a href="kr_chart.html" class="nav-item">차트</a>
  <a href="us_summary.html" class="nav-item">미국요약</a>
</nav>

<div class="main-layout">

  <!-- 상단 2열: 왼쪽 Market Trend + 오른쪽 TODAY'S REGIME 카드 -->
  <div class="top-summary-row">
    <div class="left-panel">
      <div class="meta" style="margin-bottom: 5px;">Updated: {update_time}</div>
      <div class="section-title">Market Trend</div>
      <table class="trend-table">
        <thead>
          <tr>
            <th>구간</th>
            <th>당일</th>
            <th>전일比</th>
            <th>비율</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
      <div class="summary-row">
        <span class="badge">avg sco <b>{avg_sco}</b></span>
        <span class="badge">유니버스 <b>{total_cnt}개</b></span>
        <span class="badge">투자비중 <b>{invest_pct}%</b></span>
      </div>
    </div>

    <div class="regime-summary-card">
      {regime_card_html}
    </div>
  </div>

  <!-- TODAY'S TOP3 LEADERSHIP 카드 (16d window) -->
  <div class="leadership-kpi-row">
    <div class="leadership-left-col">
      <div class="leadership-card">
        {leadership_card_html}
      </div>
      <!-- AI Core Regime (미국요약/AI 관찰판에서 이동) — 좌측 하단 공백 채움 -->
      <div class="ai-core-section">
        {ai_core_html}
      </div>
    </div>
    {auto_trade_month_html}
  </div>

  <!-- 하단: Market Regime 차트 + 히스토리 -->
  <div class="chart-section">
    <div class="section-title">Market Regime Map</div>
    {chart_html}
    <div class="section-title" style="margin-top:14px;">Market Regime History</div>
    {chart_hist_html}
  </div>

</div>

<!-- Chart.js 및 동적 렌더링 스크립트 -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0"></script>
<script>
// chartjs-plugin-datalabels 명시적 등록 (Chart.js 4.x)
if (typeof Chart !== 'undefined' && typeof ChartDataLabels !== 'undefined') {{
    Chart.register(ChartDataLabels);
    // 다른 차트(라인 등)에는 datalabels 기본 비활성화 — 도넛에서만 켬
    Chart.defaults.plugins.datalabels = Chart.defaults.plugins.datalabels || {{}};
    Chart.defaults.plugins.datalabels.display = false;
}}
</script>
<script>
(function() {{
    const allData = {track_json_str};
    let chartInstance = null;

    if(!allData || allData.length === 0) {{
        console.warn("차트 데이터가 없습니다.");
        return;
    }}

    const ctxHistory = document.getElementById('regimeHistoryChart').getContext('2d');

    const cQqq = '#1f3b73';

    // (테스트) Worst 카운트는 하루단위 노이즈가 커서 3/4일 단순이동평균을 겹쳐 QQQ와 상관관계 확인용으로 병합
    const sma = (arr, win) => arr.map((_, i) => {{
        if (i < win - 1) return null;
        let sum = 0;
        for (let k = i - win + 1; k <= i; k++) sum += arr[k];
        return sum / win;
    }});

    function drawCharts(data) {{
        const labels   = data.map(d => d.date);
        const worstRaw = data.map(d => d.Worst);

        // ── Worst Count(좌) + QQQ Price(우) 단일 차트 ─────────────
        const datasets1 = [
            {{ type: 'line', label: 'QQQ Close',  data: data.map(d => d.QQQ_close), yAxisID: 'yQQQ',   borderColor: cQqq, borderWidth: 2, pointRadius: 0, fill: false, tension: 0.1, z: 10 }},
            {{ type: 'line', label: 'Worst (raw)', data: worstRaw,       yAxisID: 'yCount', borderColor: 'rgba(194,59,59,0.35)', backgroundColor: 'rgba(194,59,59,0.35)', borderWidth: 1, pointRadius: 0, fill: false }},
            {{ type: 'line', label: 'Worst MA3',   data: sma(worstRaw, 3), yAxisID: 'yCount', borderColor: '#7a2ed6', backgroundColor: '#7a2ed6', borderWidth: 2, pointRadius: 0, fill: false, spanGaps: true }}
        ];

        if(chartInstance) {{
            chartInstance.data.labels   = labels;
            chartInstance.data.datasets = datasets1;
            chartInstance.update();
        }} else {{
            chartInstance = new Chart(ctxHistory, {{
                type: 'line',
                data: {{ labels: labels, datasets: datasets1 }},
                options: {{
                    responsive: true, maintainAspectRatio: false,
                    interaction: {{ mode: 'index', intersect: false }},
                    plugins: {{
                        title: {{ display: true, text: 'Worst Count [Inverted] (raw/MA3) & QQQ Price', font: {{size: 11}} }},
                        legend: {{ position: 'bottom', labels: {{ boxWidth: 10, font: {{size: 10}} }} }},
                        tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': ' + c.parsed.y.toFixed(1) + (c.dataset.yAxisID==='yQQQ'?'':'개') }} }}
                    }},
                    scales: {{
                        x: {{ grid: {{ display: false }}, ticks: {{ maxTicksLimit: 8, font: {{size: 9}} }} }},
                        yCount: {{ position: 'left', beginAtZero: true, reverse: true, grid: {{ display: false }}, ticks: {{ font: {{size: 9}} }} }},
                        yQQQ:   {{ position: 'right', grid: {{ display: false }}, ticks: {{ font: {{size: 9}} }} }}
                    }}
                }}
            }});
        }}
    }}

    // 초기 렌더
    drawCharts(allData);

    // 기간 필터 (3개 차트 동시 연동)
    const filterData = (months) => {{
        if(months === 'ALL') return allData;
        const lastDate = new Date(allData[allData.length - 1].date);
        lastDate.setMonth(lastDate.getMonth() - months);
        const cutoff = lastDate.toISOString().split('T')[0];
        return allData.filter(d => d.date >= cutoff);
    }};

    document.querySelectorAll('.hist-btn').forEach(btn => {{
        btn.addEventListener('click', (e) => {{
            document.querySelectorAll('.hist-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const p = btn.getAttribute('data-period');
            let m = 'ALL';
            if(p==='1M') m = 1; else if(p==='3M') m = 3;
            else if(p==='6M') m = 6; else if(p==='1Y') m = 12;
            drawCharts(filterData(m));
        }});
    }});
}})();

// ── TODAY'S TOP3 LEADERSHIP 도넛 2개 ──
(function() {{
    const LEADERSHIP = {leadership_json_str};
    if (!LEADERSHIP) return;

    // 색상: KR(큰 비중)은 차분한 파랑, US는 빨강(작은 비중일 때 강조),
    //       Commodity는 갈색(원자재), Metals는 금색, Bonds는 다크그레이, Crypto는 보라
    const CAT_COLORS = {{
        'KR':        '#4a7ac7',
        'US':        '#e74c3c',
        'Commodity': '#8e6e3a',
        'Metals':    '#f1c40f',
        'Bonds':     '#34495e',
        'Crypto':    '#9b59b6'
    }};
    const CAT_LABELS_KO = {{
        'KR':'KR', 'US':'US', 'Commodity':'Comm',
        'Metals':'Metals', 'Bonds':'Bonds', 'Crypto':'Crypto'
    }};
    const CAT_ORDER = ['KR','US','Commodity','Metals','Bonds','Crypto'];

    function makeLeadershipDoughnut(canvasId, scores) {{
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;
        const entries = CAT_ORDER
            .map(k => [k, (scores && scores[k]) || 0])
            .filter(e => e[1] > 0);
        if (entries.length === 0) return null;
        const labels = entries.map(e => CAT_LABELS_KO[e[0]]);
        const data   = entries.map(e => e[1]);
        const colors = entries.map(e => CAT_COLORS[e[0]]);
        const total  = data.reduce((a,b) => a+b, 0) || 1;
        const hasDataLabels = (typeof ChartDataLabels !== 'undefined');
        return new Chart(canvas.getContext('2d'), {{
            type: 'doughnut',
            data: {{
                labels: labels,
                datasets: [{{
                    data: data,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                cutout: '52%',
                layout: {{ padding: 8 }},
                plugins: {{
                    legend: {{ display: false }},
                    datalabels: {{
                        display: hasDataLabels,
                        color: '#fff',
                        textAlign: 'center',
                        textStrokeColor: 'rgba(0,0,0,0.55)',
                        textStrokeWidth: 3,
                        font: {{ weight: 'bold', size: 11 }},
                        anchor: 'center',
                        align: 'center',
                        clamp: true,
                        formatter: function(v, ctx) {{
                            const pct = (v / total) * 100;
                            const label = ctx.chart.data.labels[ctx.dataIndex];
                            // 비중이 너무 작으면 카테고리명만 1줄로 (sector 잘림 방지)
                            if (pct < 5) return label;
                            return label + '\\n' + pct.toFixed(0) + '%';
                        }}
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(c) {{
                                return c.label + ': ' + c.parsed + 'pt (' + (c.parsed/total*100).toFixed(1) + '%)';
                            }}
                        }}
                    }}
                }}
            }}
        }});
    }}

    makeLeadershipDoughnut('leadershipTodayChart', LEADERSHIP.scores_today);
    makeLeadershipDoughnut('leadershipPrevChart',  LEADERSHIP.scores_prev);
}})();
</script>
</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] main_hub.html 생성 완료 → {OUT_HTML}")


if __name__ == "__main__":
    main()
