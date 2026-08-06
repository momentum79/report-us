# make_summary_board.py
# 요약 게시판 - 카드 레이아웃 (3열), 체결강도 실시간 수집 결합형
# ⚠️ 파이프라인 마지막에 실행

import json
import re
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

# 설정 파일 로드 (config.py)
sys.path.append(r"D:\py")
try:
    import config
    APP_KEY = config.APP_KEY
    SECRET_KEY = config.SECRET_KEY
except ImportError:
    APP_KEY = ""
    SECRET_KEY = ""

BASE               = Path(r"D:\py\report-us")
REPORT_KR_150_JSON = BASE / "report_kr_150.json"
LEADER_TRACK_150   = BASE / "leader_tracking_150.json"
GANN_FIRE_150      = BASE / "kr150_gann_fire_set.json"
REPORT_KR_SUMMARY  = BASE / "report_kr_summary.txt"
GANN_FIRE_KR       = BASE / "kr_gann_fire_set.json"
REPORT_VOLUME_JSON = BASE / "report_volume.json"
OUT_HTML           = BASE / "summary.html"

now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── Kiwoom API (체결강도 조회) ──────────────────────────────────────────────

def get_access_token():
    if not APP_KEY: return None
    url = "https://api.kiwoom.com/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "secretkey": SECRET_KEY
    }
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    try:
        res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        res.raise_for_status()
        return res.json().get("token")
    except Exception as e:
        print(f"Token error: {e}")
        return None

def get_contract_strength_for_tickers(tickers):
    """
    주어진 티커 목록의 체결강도를 조회하여 딕셔너리로 반환 (중복 제거)
    { '005930': '105.4', ... }
    """
    token = get_access_token()
    cs_map = {}
    if not token:
        print("토큰 발급 실패, 체결강도를 기본값으로 처리합니다.")
        return cs_map

    unique_tickers = list(set([t.zfill(6) for t in tickers if t]))
    print(f"📦 총 {len(unique_tickers)}개 종목 체결강도 조회 시작...")

    headers = {
        "api-id": "ka10003",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json;charset=UTF-8"
    }
    url = "https://api.kiwoom.com/api/dostk/stkinfo"

    for i, t in enumerate(unique_tickers):
        payload = {"stk_cd": t}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
            data = res.json()
            if data.get("return_code") == 0:
                cntr_list = data.get("cntr_infr", [])
                if cntr_list:
                    cs_map[t] = cntr_list[0].get("cntr_str", "-")
        except Exception:
            pass
        time.sleep(0.3)  # API 제한 우회
        if (i+1) % 10 == 0:
            print(f"  ({i+1}/{len(unique_tickers)}) 조회 완료...")

    print("✅ 체결강도 조회 완료.")
    return cs_map


# ── 공통 HTML 랜더링 유틸 ──────────────────────────────────────────────────

def cs_badge(cs_val):
    try:
        v = float(cs_val)
        color = "#27ae60" if v >= 100 else ("#e67e22" if v >= 70 else "#e74c3c")
        return f'<span style="color:{color};font-weight:bold;">{v:.0f}%</span>'
    except Exception:
        return f'<span style="color:#aaa;">{cs_val}</span>'

def rate_color(v):
    return "#27ae60" if v > 0 else ("#e74c3c" if v < 0 else "#888")

BADGE_CSS = {
    'SPOT':  ('background:#e74c3c', '#c0392b'),
    'MOM':   ('background:#e67e22', '#d35400'),
    'LIME':  ('background:#2ecc71', '#27ae60'),
    'GREEN': ('background:#27ae60', '#1e8449'),
    'GANN':  ('background:#2980b9', '#1a5276'),
    'VOL':   ('background:#9b59b6', '#6c3483'),
    'TOP10': ('background:#27ae60', '#1e8449'),
    'TRACK': ('background:#8e44ad', '#6c3483'),
}

def sig_header_color(sig_type):
    _, border = BADGE_CSS.get(sig_type, ('background:#2c3e50', '#34495e'))
    return border

def make_card(title, sub_title, total_count, stock_rows_html, sig_type, extra_class=''):
    border_color = sig_header_color(sig_type)
    bg_css, _ = BADGE_CSS.get(sig_type, ('background:#888', '#555'))
    badge_html = (f'<span style="display:inline-block;padding:2px 7px;border-radius:4px;'
                  f'font-size:0.72em;font-weight:bold;color:white;{bg_css};">{sig_type}</span>')
    count_html = f'<span class="stk-num">{total_count}종목</span>' if total_count else ''

    return f"""
  <div class="theme-card {extra_class}">
    <div class="card-header" style="border-top:3px solid {border_color};">
      <div class="card-title-line">
        {badge_html}
        <span class="theme-name" title="{title}">{title}</span>
        {count_html}
      </div>
      <div class="card-sub">{sub_title}</div>
    </div>
    <div class="stock-list">
      {stock_rows_html if stock_rows_html else '<div style="color:#aaa;font-size:0.8em;padding:4px 0;">(종목 없음)</div>'}
    </div>
  </div>"""

def stock_row(ticker, name, pct_val, cs_val=None, nxt='', extra=''):
    try:
        v = float(str(pct_val).replace('+', '').replace('%', ''))
        rc = rate_color(v)
        sign = '+' if v > 0 else ''
        rate_html = f'<span class="stock-rate" style="color:{rc};">{sign}{v:.2f}%</span>'
    except Exception:
        rate_html = f'<span class="stock-rate" style="color:#aaa;">{pct_val}</span>'

    cs_html = cs_badge(cs_val) if cs_val else cs_badge('-')

    nxt_html = ''
    if nxt in ('NXT', '선', 'NXT선'):
        nxt_cls = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_html = f'<span class="{nxt_cls}">{nxt}</span>'

    ticker_disp = str(ticker).replace('**', '') if ticker else ''
    ticker_html = f'<span style="font-size:0.7em;color:#2980b9;">{ticker_disp} </span>' if ticker_disp else ''
    extra_html = f'<span style="font-size:0.7em;color:#aaa;padding-left:3px;">{extra}</span>' if extra else ''

    return f"""
      <div class="stock-row">
        <span class="stock-name">{ticker_html}{name}{extra_html}</span>
        {rate_html}
        <span class="stock-cs">{cs_html}</span>
        <span class="stock-nxt">{nxt_html}</span>
      </div>"""


# ── 데이터 파싱 및 체결강도 요청 ───────────────────────────────────────────

def extract_block(text, start_marker, end_markers):
    lines = text.splitlines()
    start = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith(start_marker):
            start = i; break
    if start is None: return ''
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if any(lines[i].strip().startswith(m) for m in end_markers):
            end = i; break
    return '\n'.join(lines[start:end]).strip()

def parse_txt_signals(block):
    rows = []
    for line in block.splitlines():
        line = line.strip()
        if not line or all(c in '-=' for c in line) or '없음' in line or '【' in line: continue
        cols = [c.strip() for c in line.split('\t')]
        if len(cols) < 3: continue
        try: tv_int = int(re.sub(r'[^\d]', '', cols[4]))
        except: tv_int = 0
        rows.append({
            'ticker': re.sub(r'\*+', '', cols[0]),
            'sig': cols[1] if len(cols) > 1 else '',
            'name': cols[2] if len(cols) > 2 else '',
            'pct': cols[3] if len(cols) > 3 else '-',
            'tv_str': cols[4] if len(cols) > 4 else '-',
            'tv_int': tv_int,
            'nxt': cols[-1] if cols[-1] in ('NXT', '선', 'NXT선') else ''
        })
    return rows


def main():
    print("🚀 요약용 데이터 취합 시작...")
    # 1. 모든 데이터 소스 읽기 및 종목 수집
    tickers_to_fetch = set()
    cards_data = {}

    # === [KR150] ===
    try: kr150 = json.loads(REPORT_KR_150_JSON.read_text('utf-8'))
    except: kr150 = {}

    spots = kr150.get('signals', [])
    spots = [s for s in spots if s.get('type') == 'SPOT']
    spots.sort(key=lambda x: x.get('trade_amount', 0), reverse=True)
    for s in spots: tickers_to_fetch.add(re.sub(r'\*+', '', s.get('ticker', '')))
    cards_data['spot'] = spots

    leader = kr150.get('leader', [])
    for s in leader: tickers_to_fetch.add(re.sub(r'\*+', '', s.get('ticker', '')))
    cards_data['leader'] = leader

    top10 = kr150.get('top30', [])[:10]
    for s in top10: tickers_to_fetch.add(re.sub(r'\*+', '', s.get('ticker', '')))
    cards_data['top10'] = top10

    # === [KR150 트래킹] ===
    try: track = json.loads(LEADER_TRACK_150.read_text('utf-8'))
    except: track = {}
    for t in track.keys(): tickers_to_fetch.add(re.sub(r'\*+', '', t))
    cards_data['track'] = track

    # === [KR 전종목 신호] ===
    try: kr_txt = REPORT_KR_SUMMARY.read_text('utf-8', errors='replace')
    except: kr_txt = ''
    MARKERS = ['【💥 SPOT', '【MOM', '【LIME', '【GREEN', '【RED', '【📊 주도주', '요약:', '📊 SCO', '📊 종합 Top30']
    
    mom_rows = parse_txt_signals(extract_block(kr_txt, '【MOM', [m for m in MARKERS if '【MOM' not in m]))
    lime_rows = parse_txt_signals(extract_block(kr_txt, '【LIME', [m for m in MARKERS if '【LIME' not in m]))
    green_rows = parse_txt_signals(extract_block(kr_txt, '【GREEN', [m for m in MARKERS if '【GREEN' not in m]))
    all_kr_sig = mom_rows + lime_rows + green_rows
    for r in all_kr_sig: tickers_to_fetch.add(r['ticker'])
    
    try: gann_data = json.loads(GANN_FIRE_KR.read_text('utf-8')).get('info', {})
    except: gann_data = {}
    for t in gann_data.keys(): tickers_to_fetch.add(t)
    
    cards_data['kr_sig'] = all_kr_sig
    cards_data['gann'] = gann_data

    # === [거래대금 Top] ===
    try: vol_data = json.loads(REPORT_VOLUME_JSON.read_text('utf-8')).get('stocks', [])[:10]
    except: vol_data = []
    for s in vol_data: tickers_to_fetch.add(re.sub(r'\*+', '', s.get('ticker', '')))
    cards_data['vol'] = vol_data

    # 2. 체결강도 API 동시요청
    cs_dict = get_contract_strength_for_tickers(list(tickers_to_fetch))

    # 3. HTML 생성
    html_cards = []

    # 3-1 SPOT
    row_html = ''
    for s in cards_data['spot']:
        t = re.sub(r'\*+', '', s.get('ticker','')).zfill(6)
        tv_v = s.get('trade_amount', 0) / 100_000_000
        row_html += stock_row(t, s.get('name',''), s.get('change','-'), cs_dict.get(t, '-'), s.get('nxt',''), f'{tv_v:,.0f}억')
    if row_html: html_cards.append(('kr150', make_card('SPOT 신호', '[KR150]', len(cards_data['spot']), row_html, 'SPOT')))

    # 3-2 Leader
    row_html = ''
    for s in cards_data['leader']:
        t = re.sub(r'\*+', '', s.get('ticker','')).zfill(6)
        tv_v = s.get('trade_amount', 0) / 100_000_000
        ma_icon = {'MA10':'🔵', 'MA20':'🟣', 'MA60':'🟠'}.get(s.get('closest_ma',''), '')
        row_html += stock_row(t, s.get('name',''), s.get('change','-'), cs_dict.get(t, '-'), s.get('nxt',''), f'{ma_icon}{s.get("closest_ma","")} {tv_v:.0f}억')
    if row_html: html_cards.append(('kr150', make_card('주도주 (오늘)', '[KR150]', len(cards_data['leader']), row_html, 'SPOT')))

    # 3-3 Track
    row_html = ''
    today = datetime.now().strftime('%Y-%m-%d')
    sorted_trk = sorted(cards_data['track'].items(), key=lambda x: x[1].get('added_date',''), reverse=True)
    for t, v in sorted_trk:
        t_clean = re.sub(r'\*+', '', t).zfill(6)
        try:
            days = (datetime.now() - datetime.strptime(v.get('added_date','-'), '%Y-%m-%d')).days
            ex = 14 - days
        except: days, ex = 0, 0
        pct = v.get('pct_history', {}).get(today, '-')
        row_html += stock_row(t_clean, v.get('name',''), pct, cs_dict.get(t_clean, '-'), v.get('nxt',''), f'D-{ex}')
    if row_html: html_cards.append(('kr150', make_card('주도주 (2주)', '[KR150]', len(sorted_trk), row_html, 'TRACK')))

    # 3-4 Top10
    row_html = ''
    top10_list = cards_data['top10']
    for i, s in enumerate(top10_list):
        t = re.sub(r'\*+', '', s.get('ticker','')).zfill(6)
        extra = f'#{i+1} fs={s.get("final_score",0):.2f}'
        if s.get("new_sig") and s.get("new_sig") != "-": extra += f' 🆕{s.get("new_sig")}'
        row_html += stock_row(t, s.get('name',''), s.get('change','-'), cs_dict.get(t, '-'), s.get('nxt',''), extra)
    if row_html: html_cards.append(('kr150', make_card('종합 Top 10', '[KR150]', len(top10_list), row_html, 'TOP10')))

    # 3-5 KR전종목: GANN
    row_html = ''
    gann_items = sorted(cards_data['gann'].items(), key=lambda x: x[1].get('tv_int', 0), reverse=True)
    for t, v in gann_items:
        t_clean = t.zfill(6)
        row_html += stock_row(t_clean, v.get('name',''), v.get('pct','-'), cs_dict.get(t_clean, '-'), v.get('nxt',''), v.get('tv_str',''))
    if row_html: html_cards.append(('krall', make_card('GANN 신호', '[KR전종목]', len(gann_items), row_html, 'GANN')))

    # 3-5 KR전종목: LIME, MOM, GREEN
    for sig in ['LIME', 'MOM', 'GREEN']:
        rows = [r for r in cards_data['kr_sig'] if r['sig'].upper() == sig]
        if not rows: continue
        rows.sort(key=lambda x: x['tv_int'], reverse=True)
        r_html = ''
        for r in rows:
            t = r['ticker'].zfill(6)
            r_html += stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'], r['tv_str'])
        html_cards.append(('krall', make_card(f'{sig} 신호', '[KR전종목]', len(rows), r_html, sig)))

    # 3-6 거래대금 Top10
    row_html = ''
    for s in cards_data['vol']:
        t = s.get('ticker','').zfill(6)
        v = s.get('trade_amount', 0) / 100
        row_html += stock_row(t, s.get('name',''), s.get('change',0), cs_dict.get(t, '-'), s.get('nxt',''), f'{v:,.0f}억')
    if row_html: html_cards.append(('kr150', make_card('거래대금 Top 10', '[시장전체]', min(10, len(cards_data['vol'])), row_html, 'VOL')))


    def section_wrap(title, cards, color):
        c_html = ''.join([c for g, c in html_cards if g == cards])
        if not c_html: return ''
        return f'<div class="section"><h3 class="sec-title" style="border-bottom-color:{color};">{title}</h3><div class="cards-row">{c_html}</div></div>'

    html_content = (
        section_wrap('📊 KR150 요약 (+거래대금 Top)', 'kr150', '#e74c3c') +
        section_wrap('📊 KR전종목 신호', 'krall', '#2980b9')
    )

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>요약 게시판 (체결강도 포함)</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: #f4f7f6; padding: 14px; color: #2c3e50;
}}
.top-nav-container {{ display: flex; margin-bottom: 10px; }}
.top-nav {{ display: flex; background: #2c3e50; border-radius: 8px; overflow: hidden; }}
.nav-item {{ padding: 7px 14px; color: #bdc3c7; cursor: pointer; text-decoration:none; font-size: 0.85em; font-weight: bold; transition:0.2s; }}
.nav-item:hover {{ background: #34495e; color: #fff; }}
.nav-item.active {{ background: #3498db; color: white; }}
.update-bar {{ font-size: 0.82em; color: #888; margin-bottom: 12px; }}

.section {{ margin-bottom: 14px; }}
.sec-title {{ font-size: 0.95em; font-weight: bold; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 4px; margin-bottom: 12px; margin-top:20px; }}
.cards-row {{ display: flex; flex-wrap: wrap; gap: 12px; }}

/* 카드 스타일 */
.theme-card {{
  background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  flex: 1 1 calc(33.33% - 12px); max-width: calc(33.33% - 12px); min-width: 280px; 
  padding-bottom:6px; margin-bottom:4px;
}}
.card-header {{ padding: 10px 12px; background: #fafafa; border-bottom: 1px solid #eee; }}
.card-title-line {{ display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }}
.theme-name {{ font-size: 0.9em; font-weight: bold; flex: 1; }}
.stk-num {{ font-size: 0.72em; color: #999; }}
.card-sub {{ font-size: 0.75em; color: #7f8c8d; font-weight: 500; }}

/* 종목 로우 스타일 */
.stock-list {{ padding: 6px 12px; }}
.stock-row {{ display: flex; align-items: center; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.85em; }}
.stock-row:last-child {{ border-bottom: none; }}
.stock-name {{ font-weight: bold; color: #333; flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.stock-rate {{ font-weight: bold; width: 62px; text-align:right; flex-shrink: 0; }}
.stock-cs {{ font-weight: bold; width: 50px; text-align:right; flex-shrink: 0; margin-left: 10px; }}
.stock-nxt {{ width: 45px; text-align: right; flex-shrink: 0; margin-left: 6px; white-space: nowrap; }}

/* 뱃지 */
.nxt-badge, .nxt-badge-both {{
  display: inline-block; padding: 1px 4px; border-radius: 3px; font-size: 0.7em; font-weight: bold; color: white;
}}
.nxt-badge-both {{ background-color: #1a1a1a; }}
.nxt-badge {{ background-color: #8e44ad; }}

@media (max-width: 1000px) {{
  .theme-card {{ flex: 1 1 calc(50% - 12px); max-width: calc(50% - 12px); }}
}}
@media (max-width: 600px) {{
  .theme-card {{ flex: 1 1 100%; max-width: 100%; min-width: unset; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
</style>
</head>
<body>

<div class="top-nav-container">
  <div class="top-nav">
    <a href="summary.html" class="nav-item active">요약</a>
    <a href="kor_150.html" class="nav-item">KR150</a>
    <a href="kor_stock.html" class="nav-item">KR전종목</a>
    <a href="kor_theme.html" class="nav-item">주도테마</a>
    <a href="total_etf_combined.html" class="nav-item">통합ETF</a>
  </div>
</div>

<div class="update-bar">
  📡 업데이트: {now} (제시된 종목들만 실시간 체결강도 업데이트 완료)
</div>

{html_content}

</body>
</html>
"""

    OUT_HTML.write_text(page, encoding='utf-8')
    print(f"\n[OK] summary.html 생성 완료: {OUT_HTML}")

if __name__ == '__main__':
    main()
