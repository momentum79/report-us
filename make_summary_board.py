# make_summary_board.py
# 요약 게시판 - 카드 레이아웃 (3열), 체결강도 실시간 수집 결합형
# ⚠️ 파이프라인 마지막에 실행

import csv
import html
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
NAVER_TXT          = Path(r"D:\py\0txt\00_1887_naver_thema.txt")
NAVER_DEBUG_CSV    = Path(r"D:\py\0txt\00_1887_naver_thema_debug.csv")
A_GRADE_LEADER_TXT = Path(r"D:\py\0txt\00_1887_a_grade_leader.txt")
B_GRADE_LEADER_TXT = Path(r"D:\py\0txt\00_1887_b_grade_leader.txt")
C_GRADE_LEADER_TXT = Path(r"D:\py\0txt\00_1887_c_grade_leader.txt")  # 🚀 로켓(C그룹) 매수후보 저장
HA_TXT             = Path(r"D:\py\0txt\00_1887_ha.txt")              # 📊 HA 관심종목 (티커만)
KR_CSV             = Path(r"D:\py\korea\kr.csv")                     # 종목명/NXT/선 메타
REPORT_KR_150_JSON = BASE / "report_kr_150.json"
LEADER_TRACK_VOLUME= BASE / "leader_tracking_volume.json"
LEADER_TRACK_150   = BASE / "leader_tracking_150.json"
LEADER_TRACK_ALL   = BASE / "leader_tracking.json"
GANN_FIRE_150      = BASE / "kr150_gann_fire_set.json"
REPORT_KR_SUMMARY  = BASE / "report_kr_summary.txt"
KR_ALL_SNAPSHOT_JSON = BASE / "kr_all_signal_snapshot.json"  # 전체 유니버스 스냅샷(sco/final/pos/color) - TR 오더테이블 조회용
GANN_FIRE_KR       = BASE / "kr_gann_fire_set.json"
REPORT_VOLUME_JSON = BASE / "report_volume.json"
NAVER_LEADER_POOL_JSON = BASE / "naver_leader_pool.json"
YESTERDAY_JSON     = Path(r"D:\py\0txt\theme_yesterday.json")  # make_index_theme.py 가 관리(읽기 전용)
OUT_HTML           = BASE / "summary.html"
OUT_ETF_HTML       = BASE / "etf_summary.html"
TR_BUY_PLAN_JSON    = BASE / "kr_pine_buy_plan.json"      # 0order/tr/0000_kr_buy.bat(kr_pine_buy_1887.py) 이 기록
TR_LOWBUY_PLAN_JSON = BASE / "kr_pine_lowbuy_plan.json"   # 0order/tr/0000_kr_buy.bat(kr_pine_lowbuy_1887.py 순차실행) 이 기록

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
    주어진 티커 목록의 체결강도/등락률/거래대금을 조회 (중복 제거).
    반환: (cs_map, rate_map, tv_map)
      cs_map   { '005930': '105.4', ... }   체결강도(cntr_str)
      rate_map { '005930': '+1.23', ... }   등락률(pre_rt, 부호 포함 문자열)
      tv_map   { '005930': 1234500000000, } 누적거래대금(acc_trde_prica, 원 단위)
    ※ 동일 ka10003 응답에서 셋 다 추출 → 추가 API 호출 없음
    """
    token = get_access_token()
    cs_map = {}
    rate_map = {}
    tv_map = {}
    if not token:
        print("토큰 발급 실패, 체결강도를 기본값으로 처리합니다.")
        return cs_map, rate_map, tv_map

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
                    latest = cntr_list[0]
                    cs_map[t] = latest.get("cntr_str", "-")
                    pr = latest.get("pre_rt", "")
                    if pr not in ("", None):
                        rate_map[t] = pr
                    tv = latest.get("acc_trde_prica", "")
                    if tv not in ("", None):
                        tv_map[t] = tv
        except Exception:
            pass
        time.sleep(0.3)  # API 제한 우회
        if (i+1) % 10 == 0:
            print(f"  ({i+1}/{len(unique_tickers)}) 조회 완료...")

    print("✅ 체결강도 조회 완료.")
    return cs_map, rate_map, tv_map


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

def tv_html(val_str):
    """거래대금 색상 포맷 (억 단위 문자열 입력)
    1조(10,000억)이상 → 빨간색 / 5,000억이상 → 파란색 / 1,000억이상 → 검은색 / 미만 → 회색
    """
    try:
        num = float(str(val_str).replace(',', '').replace('억', '').replace('+', '').strip())
        if num >= 10000:
            color = '#e74c3c'
        elif num >= 5000:
            color = '#e67e22'
        elif num >= 1000:
            color = '#222'
        else:
            color = '#aaa'
        return f'<span style="color:{color};font-size:0.85em;">{num:,.0f}억</span>'
    except Exception:
        return f'<span style="color:#aaa;font-size:0.85em;">{val_str}</span>'

BADGE_CSS = {
    'SPOT':  ('background:#e74c3c', '#c0392b'),
    'MOM':   ('background:#e67e22', '#d35400'),
    'LIME':  ('background:#2ecc71', '#27ae60'),
    'GREEN': ('background:#27ae60', '#1e8449'),
    'GANN':  ('background:#2980b9', '#1a5276'),
    'VOL':   ('background:#9b59b6', '#6c3483'),
    'TOP10': ('background:#27ae60', '#1e8449'),
    'TRACK': ('background:#8e44ad', '#6c3483'),
    'ROCKET':('background:#6c5ce7', '#5641e5'),
}

def sig_header_color(sig_type):
    _, border = BADGE_CSS.get(sig_type, ('background:#2c3e50', '#34495e'))
    return border

def make_card(title, sub_title, total_count, stock_rows_html, sig_type, extra_class='', badge_text=None):
    border_color = sig_header_color(sig_type)
    bg_css, _ = BADGE_CSS.get(sig_type, ('background:#888', '#555'))
    # badge_text=None → sig_type 표시 / badge_text='' → 뱃지 숨김 / 그 외 → 지정 텍스트
    label = sig_type if badge_text is None else badge_text
    badge_html = (f'<span style="display:inline-block;padding:2px 7px;border-radius:4px;'
                  f'font-size:0.72em;font-weight:bold;color:white;{bg_css};">{label}</span>') if label else ''
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

def strip_etf_prefix(name: str) -> str:
    """ETF 종목명의 KODEX/TIGER 접두어 제거 (칸수 절약용)"""
    if not name:
        return name
    for p in ('KODEX', 'TIGER'):
        if name.startswith(p):
            return name[len(p):].lstrip()
    return name


def stock_row(ticker, name, pct_val, cs_val=None, nxt='', extra='', highlight=False):
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
    code6 = ticker_disp if (ticker_disp.isdigit() and len(ticker_disp) == 6) else ''
    ticker_html = f'<span style="font-size:0.7em;color:#2980b9;">{ticker_disp} </span>' if ticker_disp else ''
    extra_html = f'<span style="color:#aaa;padding-left:3px;">{extra}</span>' if extra else ''
    name_disp = strip_etf_prefix(name)[:6] if name else ''
    if code6 and name_disp:
        name_html = f'<span class="naver-trigger" data-code="{code6}" data-name="{html.escape(str(name))}" style="cursor:pointer;text-decoration:underline dotted;">{name_disp}</span>'
    else:
        name_html = name_disp

    # 거래대금 Top30 종목: 티커+종목명에 노란음영
    tn_html = f'{ticker_html}{name_html}'
    if highlight:
        tn_html = f'<span style="background:#fff3b0;border-radius:3px;padding:0 3px;">{tn_html}</span>'

    return f"""
      <div class="stock-row">
        <span class="stock-name">{tn_html}{extra_html}</span>
        {rate_html}
        <span class="stock-cs">{cs_html}</span>
        <span class="stock-nxt">{nxt_html}</span>
      </div>"""


def badged_stock_row(ticker, name, pct_val, cs_val=None, nxt='', tv_str='-', badge_text='S', badge_color='#e74c3c'):
    t = str(ticker).zfill(6)
    badge_label = (
        f'<span style="display:inline-block;padding:1px 5px;border-radius:3px;'
        f'font-size:0.68em;font-weight:bold;color:white;background:{badge_color};'
        f'margin-right:3px;">{badge_text}</span>'
    )
    try:
        pct_f = float(str(pct_val).replace('+', '').replace('%', ''))
        rc = rate_color(pct_f)
        sign = '+' if pct_f > 0 else ''
        rate_html = f'<span class="stock-rate" style="color:{rc};">{sign}{pct_f:.2f}%</span>'
    except Exception:
        rate_html = f'<span class="stock-rate" style="color:#aaa;">{pct_val}</span>'

    nxt_html = ''
    if nxt == 'NXT선':
        nxt_html = f'<span class="nxt-badge-both">{nxt}</span>'
    elif nxt:
        nxt_html = f'<span class="nxt-badge">{nxt}</span>'

    return f"""
      <div class="stock-row">
        <span class="stock-name"><span style="font-size:0.7em;color:#2980b9;">{t} </span>{badge_label}<span class="naver-trigger" data-code="{t}" data-name="{html.escape(str(name))}" style="cursor:pointer;text-decoration:underline dotted;">{strip_etf_prefix(name)[:6]}</span><span style="padding-left:3px;">{tv_html(tv_str)}</span></span>
        {rate_html}
        <span class="stock-cs">{cs_badge(cs_val if cs_val else '-')}</span>
        <span class="stock-nxt">{nxt_html}</span>
      </div>"""


# ── 당일 테마 섹션 ──────────────────────────────────────────────────────────

def _shorten_theme(name: str) -> str:
    return name.split("/")[0].strip()

def _theme_total_tv(theme: dict) -> float:
    return sum(
        float((s.get("contract_strength") or {}).get("acc_trde_prica", 0) or 0)
        for s in theme.get("stocks", [])
    )

def _tv_fmt(val) -> str:
    """raw 원 단위 → 억 변환 후 tv_html 색상 적용"""
    try:
        uk = float(str(val).replace(",", "") or 0) / 100_000_000
        if uk <= 0:
            return '-'
        return tv_html(f'{uk:,.0f}억')
    except Exception:
        return '-'

def _as_float(raw, default=0.0) -> float:
    try:
        if raw is None:
            return default
        return float(str(raw).replace(",", "").replace("%", "").replace("+", "").strip())
    except Exception:
        return default

def _as_bool(raw) -> bool:
    return str(raw).strip().lower() in {"1", "true", "t", "yes", "y"}

def _load_naver_passed_codes() -> set[str]:
    codes: set[str] = set()
    if not NAVER_TXT.exists():
        return codes
    try:
        for line in NAVER_TXT.read_text(encoding="utf-8-sig").splitlines():
            code = line.strip().split()[0] if line.strip() else ""
            code = code.lstrip("A").zfill(6)
            if len(code) == 6 and code.isdigit():
                codes.add(code)
    except Exception:
        pass
    return codes

def load_naver_theme_data() -> dict:
    if not NAVER_DEBUG_CSV.exists():
        return {"daily": {"top_themes": []}}

    passed_codes = _load_naver_passed_codes()
    grouped: dict[str, list[dict]] = {}
    theme_chg_map: dict[str, float] = {}   # 테마군 등락률 (헤더용)
    try:
        with NAVER_DEBUG_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                code = str(row.get("code", "")).strip().lstrip("A").zfill(6)
                if len(code) != 6 or not code.isdigit():
                    continue
                if not (_as_bool(row.get("passed")) or code in passed_codes):
                    continue

                theme_nm = (row.get("theme") or "네이버테마").strip()
                tc_raw = row.get("theme_chg")
                if theme_nm not in theme_chg_map and tc_raw not in (None, "", "-"):
                    try:
                        theme_chg_map[theme_nm] = float(
                            str(tc_raw).replace("+", "").replace("%", "").strip())
                    except Exception:
                        pass
                chg_pct = _as_float(row.get("chg_pct"))
                trade_eok = _as_float(row.get("trade_eok"))
                grouped.setdefault(theme_nm, []).append({
                    "stk_cd": code,
                    "stk_nm": (row.get("name") or code).strip(),
                    "flu_rt": f"{chg_pct:.2f}",
                    "nxt_info": "",
                    "contract_strength": {
                        "cntr_str": "-",
                        "acc_trde_prica": trade_eok * 100_000_000,
                    },
                })
    except Exception:
        return {"daily": {"top_themes": []}}

    themes = []
    sorted_groups = sorted(
        grouped.items(),
        key=lambda item: _theme_total_tv({"stocks": item[1]}),
        reverse=True,
    )
    for rank, (theme_nm, stocks) in enumerate(sorted_groups, start=1):
        stocks.sort(key=lambda s: (s.get("contract_strength") or {}).get("acc_trde_prica", 0), reverse=True)
        avg_chg = sum(_as_float(s.get("flu_rt")) for s in stocks) / len(stocks) if stocks else 0.0
        # 헤더 등락률: 네이버 테마군 등락률 우선, 없으면 구성종목 평균 fallback
        hdr_chg = theme_chg_map.get(theme_nm, avg_chg)
        themes.append({
            "rank": rank,
            "thema_grp_cd": f"NAVER_{rank:02d}",
            "thema_nm": theme_nm,
            "flu_rt": f"{hdr_chg:.2f}",
            "stk_num": str(len(stocks)),
            "stocks": stocks,
        })
    return {"daily": {"top_themes": themes}}

def _render_theme_cards(themes_sorted) -> str:
    """테마 리스트 → 카드 HTML (당일/전일 공통 렌더러).
    헤더 등락률 = theme['flu_rt'] (테마군 등락률) / 종목 등락률 = stock['flu_rt']."""
    MEDALS = ["🥇", "🥈", "🥉"]
    cards_html = ''

    for rank, theme in enumerate(themes_sorted):
        medal = MEDALS[rank] if rank < 3 else f"#{rank+1}"
        short_nm = _shorten_theme(theme.get("thema_nm", ""))
        flu_rt = theme.get("flu_rt", "0")
        stk_num = theme.get("stk_num", "0")
        stocks = theme.get("stocks", [])
        try:
            v = float(str(flu_rt).replace("+", ""))
            hdr_color = "#27ae60" if v > 0 else ("#e74c3c" if v < 0 else "#888")
            sign = "+" if v > 0 else ""
            rate_str = f'{sign}{v:.2f}%'
        except Exception:
            hdr_color = "#888"
            rate_str = str(flu_rt)

        rows_html = ''
        for s in stocks:
            nm = s.get("stk_nm", "")[:6]
            cd = str(s.get("stk_cd", "")).zfill(6)
            fr = s.get("flu_rt", "0")
            cs_obj = s.get("contract_strength") or {}
            cs = cs_obj.get("cntr_str", "-")
            tv_raw = cs_obj.get("acc_trde_prica", 0)
            nxt = s.get("nxt_info", "")
            try:
                fr_v = float(str(fr).replace("+", ""))
                rc = "#27ae60" if fr_v > 0 else ("#e74c3c" if fr_v < 0 else "#888")
                s_r = "+" if fr_v > 0 else ""
                fr_html = f'<span style="color:{rc};font-weight:bold;">{s_r}{fr_v:.2f}%</span>'
            except Exception:
                fr_html = f'<span style="color:#aaa;">{fr}</span>'
            nxt_html = ''
            if nxt:
                bg = "#2c3e50" if nxt == "N선" else ("#8e44ad" if nxt == "N" else "#e67e22")
                nxt_html = f'<span style="display:inline-block;font-size:10px;font-weight:bold;color:#fff;background:{bg};padding:1px 4px;border-radius:3px;">{nxt}</span>'
            ticker_html = f'<span style="font-size:0.7em;color:#2980b9;">{cd} </span>' if cd and cd != '000000' else ''
            if cd and cd != '000000':
                nm_html = f'<span class="naver-trigger" data-code="{cd}" data-name="{html.escape(str(nm))}" style="cursor:pointer;text-decoration:underline dotted;">{nm}</span>'
            else:
                nm_html = nm
            rows_html += f"""
          <div class="stock-row">
            <span class="stock-name" style="flex:1;">{ticker_html}{nm_html}<span style="padding-left:3px;">{_tv_fmt(tv_raw)}</span></span>
            {fr_html}
            <span class="stock-cs">{cs_badge(cs)}</span>
            <span class="stock-nxt">{nxt_html}</span>
          </div>"""

        cards_html += f"""
  <div class="theme-card">
    <div class="card-header" style="border-top:3px solid {hdr_color};">
      <div class="card-title-line">
        <span style="font-size:1em;">{medal}</span>
        <span class="theme-name" title="{theme.get('thema_nm','')}">{short_nm}</span>
        <span class="stk-num">{stk_num}종목</span>
      </div>
      <div class="card-sub" style="font-size:0.95em;font-weight:bold;color:{hdr_color};">{rate_str}</div>
    </div>
    <div class="stock-list">{rows_html}
    </div>
  </div>"""

    return cards_html


def build_daily_theme_section() -> str:
    """Naver crawler outputs -> 당일 테마 카드 HTML (거래대금 순 정렬)"""
    data = load_naver_theme_data()
    themes = data.get("daily", {}).get("top_themes", [])
    if not themes:
        return ''
    themes_sorted = sorted(themes, key=_theme_total_tv, reverse=True)
    cards_html = _render_theme_cards(themes_sorted)
    if not cards_html:
        return ''
    return f'<div class="section"><h3 class="sec-title" style="border-bottom-color:#f39c12;">📅 당일 테마</h3><div class="cards-row">{cards_html}</div></div>'


def build_yesterday_theme_section(cs_dict=None, rate_dict=None, tv_dict=None) -> str:
    """theme_yesterday.json(make_index_theme.py 가 관리)의 yesterday 블록 → 전일 테마 카드.
    헤더=전일 테마군 등락률(스냅샷 저장값), 종목 등락률/체결강도/거래대금=오늘 값으로 보완.
      1차: 오늘 당일(네이버) 테마에 있으면 그 값
      2차: ka10003 실시간 조회결과(rate_dict/cs_dict/tv_dict, 원 단위)로 보완
    전일테마 종목은 오늘 네이버 통과목록에 없는 경우가 많아 2차 보완이 핵심."""
    cs_dict   = cs_dict or {}
    rate_dict = rate_dict or {}
    tv_dict   = tv_dict or {}
    if not YESTERDAY_JSON.exists():
        return ''
    try:
        store = json.loads(YESTERDAY_JSON.read_text(encoding='utf-8'))
    except Exception:
        return ''
    yday = store.get("yesterday") or {}
    ythemes = yday.get("top_themes") or []
    if not ythemes:
        return ''

    # 오늘 값 lookup: 당일 테마 종목 → 오늘 등락률/거래대금
    today_lookup = {}
    daily = load_naver_theme_data().get("daily", {}).get("top_themes", [])
    for th in daily:
        for s in th.get("stocks", []):
            cd = str(s.get("stk_cd", "")).zfill(6)
            if cd and cd not in today_lookup:
                today_lookup[cd] = {
                    "flu_rt": s.get("flu_rt", "-"),
                    "acc_trde_prica": (s.get("contract_strength") or {}).get("acc_trde_prica", 0),
                }

    def _num(raw):
        try:
            return float(str(raw).replace(",", "").replace("%", "").replace("+", "").strip())
        except Exception:
            return None

    # 전일 종목에 오늘 값 입히기 (순위는 스냅샷 순서 유지)
    enriched = []
    for th in ythemes:
        stocks = []
        for s in th.get("stocks", []):
            cd = str(s.get("stk_cd", "")).zfill(6)
            ti = today_lookup.get(cd, {})
            # 등락률: 당일테마 우선, 없으면 ka10003 실시간
            flu = ti.get("flu_rt", "-")
            if flu in ("", "-", None) and rate_dict.get(cd) not in ("", None):
                flu = rate_dict[cd]
            # 거래대금: 당일테마 우선, 없으면 ka10003 실시간(원 단위)
            tv = ti.get("acc_trde_prica", 0) or 0
            if not tv:
                tv = _num(tv_dict.get(cd)) or 0
            # 체결강도: ka10003 실시간(없으면 '-')
            cs = cs_dict.get(cd, "-") or "-"
            stocks.append({
                "stk_cd":   cd,
                "stk_nm":   s.get("stk_nm", ""),
                "nxt_info": s.get("nxt_info", ""),
                "flu_rt":   flu,
                "contract_strength": {"cntr_str": cs, "acc_trde_prica": tv},
            })
        enriched.append({**th, "stocks": stocks})

    cards_html = _render_theme_cards(enriched)
    if not cards_html:
        return ''

    date_label = ''
    try:
        dt = datetime.strptime(yday.get("date_str", ""), "%Y-%m-%d")
        date_label = f' ({dt.month}/{dt.day})'
    except Exception:
        pass
    return (f'<div class="section"><h3 class="sec-title" style="border-bottom-color:#e67e22;">'
            f'📅 전일 테마{date_label} — 오늘 등락률</h3><div class="cards-row">{cards_html}</div></div>')


# ── 한국주식 TR(Pine Screener) 통합 주문 예상표 ────────────────────────────

def _collect_kr_signal_items():
    """report_kr_150.json(top30/signals/red_signals) + report_kr_summary.txt(종합 Top30,
    LIME/GREEN/MOM/RED 섹션)를 종목코드 기준으로 병합한 신호 딕셔너리(sco/Final/Color).
    3M(%)은 KR 개별종목 단위로 제공하는 산출물이 없어 항상 '-'."""
    items = {}

    def set_field(code, **data):
        code = re.sub(r'\*+', '', str(code or '')).strip().zfill(6)
        if not re.fullmatch(r'\d{6}', code):
            return
        rec = items.setdefault(code, {})
        for k, v in data.items():
            if v == 'GRN':
                v = 'GREEN'
            if rec.get(k) in (None, '', '-') and v not in (None, ''):
                rec[k] = v

    try:
        kr150 = json.loads(REPORT_KR_150_JSON.read_text('utf-8'))
    except (OSError, ValueError):
        kr150 = {}

    for row in kr150.get('top30', []) or []:
        set_field(row.get('ticker'), sco=row.get('signal_sco'), final=row.get('final_score'))

    for row in (kr150.get('signals', []) or []) + (kr150.get('red_signals', []) or []):
        set_field(row.get('ticker'), color=row.get('type'))

    try:
        kr_txt = REPORT_KR_SUMMARY.read_text('utf-8', errors='replace')
    except OSError:
        kr_txt = ''

    MARKERS = ['📊 종합 Top30', '【💥 SPOT', '【MOM', '【LIME', '【GREEN', '【RED / PURPLE', '【📊 주도주', '요약:']

    top30_block = extract_block(kr_txt, '📊 종합 Top30', [m for m in MARKERS if m != '📊 종합 Top30'])
    for line in top30_block.splitlines():
        line = line.strip()
        if not line or all(c in '-=' for c in line) or 'Ticker' in line or '종합 Top30' in line:
            continue
        cols = [c.strip() for c in line.split('\t')]
        if len(cols) < 6:
            continue
        color = re.sub(r'[^A-Z]', '', cols[5].upper()) or None
        set_field(cols[0], sco=cols[2], final=cols[4], color=color)

    for marker in ('【MOM', '【LIME', '【GREEN', '【RED / PURPLE'):
        rows = parse_txt_signals(extract_block(kr_txt, marker, [m for m in MARKERS if m != marker]))
        for r in rows:
            set_field(r['ticker'], color=r.get('sig'))

    # 🆕 위 소스에 없는 종목(저장티커는 있으나 Top30/신호 블록엔 안 뜨는 경우) 보강용 전체 유니버스 스냅샷
    try:
        snap = json.loads(KR_ALL_SNAPSHOT_JSON.read_text('utf-8'))
        for code, v in (snap.get('tickers') or {}).items():
            set_field(code, sco=v.get('sco'), final=v.get('final'), color=v.get('color'), pos=v.get('pos'))
    except (OSError, ValueError):
        pass

    return items


def _load_tr_plan(path, source_label):
    """반환: (budget, rows) - 파일 없거나 손상 시 (None, [])."""
    if not path.exists():
        return None, []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None, []
    rows = [{**r, "source": r.get("tag") or source_label} for r in (data.get("rows") or [])]
    return data.get("budget") or 0.0, rows


def build_kr_tr_order() -> str:
    """0000_kr_buy.bat(추세 매수+고점 매도, 저2/MA돌파 매수까지 순차 실행) 이 남긴 스냅샷 → 주문 예상표."""
    buy_budget, buy_rows = _load_tr_plan(TR_BUY_PLAN_JSON, '추세')
    low_budget, low_rows = _load_tr_plan(TR_LOWBUY_PLAN_JSON, '저점')

    if buy_budget is None and low_budget is None:
        return ('<h3 class="sec-title" style="border-bottom-color:#e67e22;">🎯 한국주식 TR 통합 주문 예상표</h3>'
                '<p style="padding-left:6px;color:#999;font-size:12px;">'
                '아직 실행 결과 없음 (0000_kr_buy.bat 실행 필요)</p>')

    budget = (buy_budget or 0.0) + (low_budget or 0.0)
    candidates = buy_rows + low_rows

    signal_items = _collect_kr_signal_items()

    body = ''
    for c in candidates:
        code = str(c.get('ticker', '')).zfill(6)
        name = str(c.get('name', '')) or code
        order_price = c.get('order_price') or 0
        sig = signal_items.get(code) or {}
        try:
            v = float(c.get('chg_pct'))
            chg = f'<span style="color:{rate_color(v)};font-weight:600;">{"+" if v > 0 else ""}{v:.2f}%</span>'
        except (TypeError, ValueError):
            chg = '-'
        name_html = (f'<span class="naver-trigger" data-code="{code}" data-name="{html.escape(name)}" '
                     f'style="cursor:pointer;text-decoration:underline dotted;">{html.escape(name)}</span>')
        body += (
            f'<tr><td class="ticker-col">{code}</td><td>{name_html}</td>'
            f'<td>{html.escape(str(c.get("source", "-")))}</td>'
            f'<td>{c.get("price") or 0:,}</td><td>{chg}</td><td>{order_price:,}</td>'
            f'<td>{html.escape(str(sig.get("sco") or "-"))}</td><td>-</td>'
            f'<td>{html.escape(str(sig.get("final") or "-"))}</td>'
            f'<td>{html.escape(str(sig.get("color") or "-"))}</td>'
            f'<td>{html.escape(str(sig.get("pos") or "-"))}</td></tr>'
        )

    if not body:
        body = '<tr><td colspan="11" style="color:#999;">매수 후보 없음</td></tr>'

    title = f'🎯 한국주식 TR 통합 주문 예상표 - {len(candidates)}종목, {budget:,.0f}원 기준'
    headers = ['종목코드', '종목명', '구분', '현재가(원)', '등락률(%)', '주문가(원)', 'sco', '3M(%)', 'Final', 'Color', '위치']
    head = ''.join(f'<th>{h}</th>' for h in headers)
    return (f'<h3 class="sec-title tr-order-title" style="border-bottom-color:#e67e22;">{title}</h3>'
            f'<table class="styled-tableWide tr-order-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


# ── TR 스크리너 CSV(kr_buy.csv)의 주봉 신호(주M) 1=매집 / 2=vol빵 ─────────────
TR_KR_CSV = Path(r'D:\py\0order\tr\kr_buy.csv')
JUM_LABEL = {'1': '매집', '2': 'vol빵'}


def build_kr_tr_weekly() -> str:
    title = '🎯 한국주식 TR 주봉 - 매집(1), vol빵(2)'
    head_html = f'<h3 class="sec-title tr-order-title" style="border-bottom-color:#e67e22;">{title}</h3>'
    try:
        with TR_KR_CSV.open('r', encoding='utf-8-sig', newline='') as f:
            src = list(csv.DictReader(f))
    except OSError:
        return (head_html + '<p style="padding-left:6px;color:#999;font-size:12px;">'
                f'{html.escape(TR_KR_CSV.name)} 없음</p>')

    picked = []
    for r in src:
        code = (r.get('주M') or '').strip()
        if code not in JUM_LABEL:
            continue
        try:
            sco = float((r.get('sco') or '').strip())
        except ValueError:
            sco = -99.0
        picked.append((code, sco, r))
    picked.sort(key=lambda x: (x[0] != '2', -x[1]))

    body = ''
    for jm, _sco, r in picked:
        code = (r.get('심볼') or '').strip().zfill(6)
        name = (r.get('설명') or '').strip() or code
        try:
            v = float((r.get('등락률(%)') or '').strip())
            chg = f'<span style="color:{rate_color(v)};font-weight:600;">{"+" if v > 0 else ""}{v:.2f}%</span>'
        except ValueError:
            chg = '-'
        try:
            price = f'{int(float((r.get("가격") or "0").strip())):,}'
        except ValueError:
            price = '-'
        name_html = (f'<span class="naver-trigger" data-code="{code}" data-name="{html.escape(name)}" '
                     f'style="cursor:pointer;text-decoration:underline dotted;">{html.escape(name)}</span>')
        body += (
            f'<tr><td class="ticker-col">{code}</td><td>{name_html}</td>'
            f'<td>{JUM_LABEL[jm]}</td><td>{price}</td><td>{chg}</td>'
            f'<td>{html.escape((r.get("sco") or "-").strip())}</td>'
            f'<td>{html.escape((r.get("3M(%)") or "-").strip())}</td>'
            f'<td>{html.escape((r.get("위치") or "-").strip())}</td></tr>'
        )

    if not body:
        body = '<tr><td colspan="8" style="color:#999;">해당 종목 없음</td></tr>'

    headers = ['종목코드', '종목명', '구분', '현재가(원)', '등락률(%)', 'sco', '3M(%)', '위치']
    head = ''.join(f'<th>{h}</th>' for h in headers)
    return (head_html +
            f'<table class="styled-tableWide tr-order-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


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


def parse_leader_signals(block):
    """
    주도주 블록 파싱
    포맷: ticker**\t+15.98%\t종목명\t2,096억\tMA60\t3.2
    """
    rows = []
    for line in block.splitlines():
        line = line.strip()
        if not line or all(c in '-=' for c in line) or '없음' in line or '【' in line: continue
        if line.startswith('요약') or line.startswith('📊'): continue
        cols = [c.strip() for c in line.split('\t')]
        if len(cols) < 4: continue
        ticker_raw = cols[0]
        ticker = re.sub(r'\*+', '', ticker_raw)
        if not re.search(r'\d{6}', ticker): continue
        pct    = cols[1] if len(cols) > 1 else '-'
        name   = cols[2] if len(cols) > 2 else ''
        tv_str = cols[3] if len(cols) > 3 else '-'
        ma     = cols[4] if len(cols) > 4 else ''
        try: tv_int = int(re.sub(r'[^\d]', '', tv_str))
        except: tv_int = 0
        nxt = cols[-1] if cols[-1] in ('NXT', '선', 'NXT선') else ''
        rows.append({
            'ticker': ticker,
            'name': name,
            'pct': pct,
            'tv_str': tv_str,
            'tv_int': tv_int,
            'ma': ma,
            'nxt': nxt,
        })
    return rows


def read_ticker_lines(path):
    tickers = []
    seen = set()
    if not path.exists():
        return tickers
    try:
        lines = path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
    except Exception:
        return tickers
    for line in lines:
        m = re.search(r'\d{6}', line)
        if not m:
            continue
        ticker = m.group(0)
        if ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def load_kr_csv_meta(path=KR_CSV):
    """kr.csv → { '005930': {'name':'삼성전자', 'nxt':'NXT선'}, ... }
    NXT/선 컬럼 조합: 둘다→'NXT선' / NXT만→'NXT' / 선만→'선' / 없음→''"""
    meta = {}
    if not path.exists():
        return meta
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            next(reader, None)  # 헤더(티커,종목명,NXT,선,...)
            for cols in reader:
                if len(cols) < 4:
                    continue
                t = re.sub(r'\D', '', str(cols[0])).zfill(6)
                if not re.fullmatch(r'\d{6}', t):
                    continue
                has_nxt  = bool(str(cols[2]).strip())
                has_seon = bool(str(cols[3]).strip())
                nxt = 'NXT선' if (has_nxt and has_seon) else ('NXT' if has_nxt else ('선' if has_seon else ''))
                meta[t] = {'name': str(cols[1]).strip(), 'nxt': nxt}
    except Exception:
        pass
    return meta


def read_ha_tickers(path=HA_TXT):
    """00_1887_ha.txt 읽기 — 6자리 미만도 zero-pad (예: 13360 → 013360)"""
    out = []
    seen = set()
    if not path.exists():
        return out
    try:
        lines = path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
    except Exception:
        return out
    for line in lines:
        m = re.search(r'\d{4,6}', line)
        if not m:
            continue
        t = m.group(0).zfill(6)
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def latest_pct_from_history(info):
    hist = info.get('pct_history', {}) if isinstance(info, dict) else {}
    if not isinstance(hist, dict) or not hist:
        return ''
    key = sorted(hist.keys())[-1]
    return str(hist.get(key, ''))


def trade_raw_to_eok_str(raw):
    try:
        val = float(str(raw).replace(',', ''))
        if val <= 0:
            return ''
        return f'{val / 100:,.0f}억'
    except Exception:
        return ''


def map_rows_by_ticker(rows):
    mapped = {}
    for row in rows or []:
        ticker = re.sub(r'\*+', '', str(row.get('ticker', ''))).strip().zfill(6)
        if re.fullmatch(r'\d{6}', ticker):
            mapped[ticker] = row
    return mapped


def build_a_leader_rows(codes, spot_rows, leader_rows, sig_rows, top30_rows, vol_rows, pool_items, tracking_volume, tracking_150, tracking_all):
    spot_map = map_rows_by_ticker(spot_rows)
    leader_map = map_rows_by_ticker(leader_rows)
    sig_map = map_rows_by_ticker(sig_rows)
    top30_map = map_rows_by_ticker(top30_rows)
    vol_map = map_rows_by_ticker(vol_rows)
    pool_map = map_rows_by_ticker(pool_items)

    rows = []
    for ticker in codes:
        row = {'ticker': ticker, 'name': ticker, 'pct': '-', 'tv_str': '-', 'nxt': ''}

        def fill(name='', pct='', tv_str='', nxt=''):
            if name and row['name'] == ticker:
                row['name'] = str(name)
            if pct not in ('', None) and row['pct'] == '-':
                row['pct'] = str(pct)
            if tv_str not in ('', None, '-') and row['tv_str'] == '-':
                row['tv_str'] = str(tv_str)
            if nxt and not row['nxt']:
                row['nxt'] = str(nxt)

        # 거래대금 API(ka10023) 추적: 이름/거래대금만 채우고 등락률(pct)은 채우지 않는다.
        # 등락률은 _AL(NXT통합) 기반 소스(leader/spot/sig/top30)를 우선 사용해야
        # KR150/KR전종목 보드와 동일한 규칙값(NXT종목=NXT통합종가 / 비NXT=정규장종가 기준)이 된다.
        tv = tracking_volume.get(ticker, {}) if isinstance(tracking_volume, dict) else {}
        if tv:
            fill(
                name=tv.get('name', ''),
                tv_str=trade_raw_to_eok_str(tv.get('trade_amount')),
            )

        for source in (leader_map, spot_map, sig_map, top30_map):
            s = source.get(ticker, {})
            if s:
                fill(name=s.get('name', ''), pct=s.get('pct', ''), tv_str=s.get('tv_str', ''), nxt=s.get('nxt', ''))

        rv = vol_map.get(ticker, {})
        if rv:
            fill(
                name=rv.get('name', ''),
                pct=rv.get('change', ''),
                tv_str=trade_raw_to_eok_str(rv.get('trade_amount')),
                nxt=rv.get('nxt', ''),
            )

        pool = pool_map.get(ticker, {})
        if pool:
            report_volume = pool.get('report_volume') or {}
            fill(
                name=pool.get('name', ''),
                pct=report_volume.get('change', ''),
                tv_str=trade_raw_to_eok_str(report_volume.get('trade_amount')),
                nxt=report_volume.get('nxt', ''),
            )

        for source in (tracking_150, tracking_all):
            s = source.get(ticker, {}) if isinstance(source, dict) else {}
            if s:
                fill(name=s.get('name', ''), pct=latest_pct_from_history(s), tv_str=s.get('tv_str', ''), nxt=s.get('nxt', ''))

        # _AL 기반 소스에 등락률이 전혀 없을 때만 거래대금 API 추적값을 최후 fallback으로 사용
        if tv and row['pct'] == '-':
            fill(pct=latest_pct_from_history(tv))

        rows.append(row)
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
    leader_kr_rows = parse_leader_signals(extract_block(kr_txt, '【📊 주도주', [m for m in MARKERS if '【📊 주도주' not in m]))
    for r in leader_kr_rows: tickers_to_fetch.add(r['ticker'])
    cards_data['leader_kr'] = leader_kr_rows
    
    spot_kr_rows = parse_txt_signals(extract_block(kr_txt, '【💥 SPOT', [m for m in MARKERS if '【💥 SPOT' not in m]))
    for r in spot_kr_rows: tickers_to_fetch.add(r['ticker'])
    cards_data['spot_kr'] = spot_kr_rows

    mom_rows = parse_txt_signals(extract_block(kr_txt, '【MOM', [m for m in MARKERS if '【MOM' not in m]))
    lime_rows = parse_txt_signals(extract_block(kr_txt, '【LIME', [m for m in MARKERS if '【LIME' not in m]))
    all_kr_sig = mom_rows + lime_rows
    for r in all_kr_sig: tickers_to_fetch.add(r['ticker'])
    
    try: gann_data = json.loads(GANN_FIRE_KR.read_text('utf-8')).get('info', {})
    except: gann_data = {}
    for t in gann_data.keys(): tickers_to_fetch.add(t)
    
    cards_data['kr_sig'] = all_kr_sig
    cards_data['gann'] = gann_data

    # === [KR전종목 종합 Top30] ===
    top30_kr_rows = []
    top30_block_raw = extract_block(kr_txt, '📊 종합 Top30', [m for m in MARKERS if '📊 종합 Top30' not in m])
    for line in top30_block_raw.splitlines():
        line = line.strip()
        if not line or all(c in '-=' for c in line): continue
        if 'Ticker' in line or 'Signal_sco' in line or '종합 Top30' in line: continue
        cols = [c.strip() for c in line.split('\t')]
        if len(cols) < 4: continue
        ticker_clean = re.sub(r'\*+', '', cols[0]).strip()
        if not re.search(r'\d{6}', ticker_clean): continue
        top30_kr_rows.append({
            'ticker': ticker_clean,
            'name': cols[1] if len(cols) > 1 else '',
            'pct': cols[3] if len(cols) > 3 else '-',
            'final_sco': cols[4] if len(cols) > 4 else '',
            'new_sig': cols[5] if len(cols) > 5 else '-',
            'tv_str': cols[7] if len(cols) > 7 else '-',
            'nxt': cols[-1] if cols[-1] in ('NXT', '선', 'NXT선') else ''
        })
        tickers_to_fetch.add(ticker_clean.zfill(6))
    cards_data['top30_kr'] = top30_kr_rows[:10]

    # === [거래대금 Top] ===
    try: vol_all = json.loads(REPORT_VOLUME_JSON.read_text('utf-8')).get('stocks', [])
    except: vol_all = []
    vol_data = vol_all[:10]
    for s in vol_data: tickers_to_fetch.add(re.sub(r'\*+', '', s.get('ticker', '')))
    cards_data['vol'] = vol_data

    # === [🚀 로켓 (C그룹)] =================================================
    # 조건1: KR150 종합Top30 + KR전종목 종합Top30 중 new_sig 에 🚀 있는 종목
    # 조건2: 거래대금 >= 1,000억  /  중복 티커는 하나로 통합
    # 거래대금 Top30 에 든 종목은 티커/종목명에 노란음영 표시
    ROCKET_TV_MIN = 1000  # 억
    rocket_hl_set = {re.sub(r'\*+', '', s.get('ticker', '')).zfill(6) for s in vol_all[:30]}

    def _tv_str_to_eok(s):
        """'1,294억' → 1294.0"""
        try:    return float(re.sub(r'[^\d.]', '', str(s)) or 0)
        except: return 0.0

    rocket_map = {}  # ticker -> row (먼저 들어온 소스 우선)
    for s in kr150.get('top30', []):                       # KR150 종합Top30
        if '🚀' not in str(s.get('new_sig', '')): continue
        tv_eok = (s.get('trade_amount', 0) or 0) / 100_000_000
        if tv_eok < ROCKET_TV_MIN: continue
        t = re.sub(r'\*+', '', s.get('ticker', '')).zfill(6)
        rocket_map.setdefault(t, {'ticker': t, 'name': s.get('name', ''),
                                  'pct': s.get('change', '-'), 'tv_eok': tv_eok,
                                  'nxt': s.get('nxt', '')})
    for r in top30_kr_rows:                                # KR전종목 종합Top30
        if '🚀' not in str(r.get('new_sig', '')): continue
        tv_eok = _tv_str_to_eok(r.get('tv_str', ''))
        if tv_eok < ROCKET_TV_MIN: continue
        t = r['ticker'].zfill(6)
        rocket_map.setdefault(t, {'ticker': t, 'name': r.get('name', ''),
                                  'pct': r.get('pct', '-'), 'tv_eok': tv_eok,
                                  'nxt': r.get('nxt', '')})
    rocket_rows = sorted(rocket_map.values(), key=lambda x: x['tv_eok'], reverse=True)
    for t in rocket_map: tickers_to_fetch.add(t)
    cards_data['rocket'] = rocket_rows
    cards_data['rocket_hl'] = rocket_hl_set

    # === [A 리더] ===
    try: tracking_volume = json.loads(LEADER_TRACK_VOLUME.read_text('utf-8'))
    except: tracking_volume = {}
    try: tracking_all = json.loads(LEADER_TRACK_ALL.read_text('utf-8'))
    except: tracking_all = {}
    try: pool_items = json.loads(NAVER_LEADER_POOL_JSON.read_text('utf-8')).get('items', [])
    except: pool_items = []

    a_leader_codes = read_ticker_lines(A_GRADE_LEADER_TXT)
    for t in a_leader_codes:
        tickers_to_fetch.add(t)
    cards_data['a_leader'] = build_a_leader_rows(
        a_leader_codes,
        spot_kr_rows,
        leader_kr_rows,
        all_kr_sig,
        top30_kr_rows,
        vol_data,
        pool_items,
        tracking_volume,
        track,
        tracking_all,
    )

    b_leader_codes = read_ticker_lines(B_GRADE_LEADER_TXT)
    for t in b_leader_codes:
        tickers_to_fetch.add(t)
    cards_data['b_leader'] = build_a_leader_rows(
        b_leader_codes,
        spot_kr_rows,
        leader_kr_rows,
        all_kr_sig,
        top30_kr_rows,
        vol_data,
        pool_items,
        tracking_volume,
        track,
        tracking_all,
    )

    # === [HA 관심종목] (00_1887_ha.txt) =====================================
    kr_meta  = load_kr_csv_meta()
    ha_codes = read_ha_tickers()
    for t in ha_codes:
        tickers_to_fetch.add(t)

    # === [전일 테마 종목] → ka10003 실시간 보완 대상에 포함 ===================
    # theme_yesterday.json 에는 종목명만 있고 오늘 등락률/체결강도/거래대금이 없어
    # 그대로 두면 전일테마 카드에 종목명만 표시됨 → 티커를 조회목록에 추가
    try:
        _yj = json.loads(YESTERDAY_JSON.read_text(encoding='utf-8')) if YESTERDAY_JSON.exists() else {}
        for _th in (_yj.get("yesterday") or {}).get("top_themes") or []:
            for _s in _th.get("stocks", []):
                _cd = str(_s.get("stk_cd", "")).zfill(6)
                if re.fullmatch(r'\d{6}', _cd):
                    tickers_to_fetch.add(_cd)
    except Exception:
        pass

    # ── 주문용 티커 txt 파일 저장 ──────────────────────────────────────────────
    ORDER_DIR = Path(r"D:\py\0order")
    ORDER_DIR.mkdir(parents=True, exist_ok=True)

    def save_tickers(filepath, tickers):
        """6자리 티커만 추출해서 1줄에 1개씩 저장"""
        clean = []
        for t in tickers:
            t6 = re.sub(r'\*+', '', str(t)).strip()[:6]
            if re.fullmatch(r'\d{6}', t6):
                clean.append(t6)
        Path(filepath).write_text('\n'.join(clean), encoding='utf-8')
        print(f"[ORDER] {filepath} → {len(clean)}종목 저장")

    # 1) SPOT + 주도주 (전종목)
    spot_kr_tickers  = [r['ticker'] for r in cards_data.get('spot_kr', [])]
    leader_kr_tickers = [r['ticker'] for r in cards_data.get('leader_kr', [])]
    # 중복 제거, 순서 유지
    seen = set(); judo_tickers = []
    for t in spot_kr_tickers + leader_kr_tickers:
        if t not in seen: seen.add(t); judo_tickers.append(t)
    save_tickers(ORDER_DIR / "0주도주.txt", judo_tickers)

    # 2) LIME
    lime_tickers = [r['ticker'] for r in lime_rows]
    save_tickers(ORDER_DIR / "0lime.txt", lime_tickers)

    # 3) MOM
    mom_tickers = [r['ticker'] for r in mom_rows]
    save_tickers(ORDER_DIR / "0mom.txt", mom_tickers)

    # 4) KR150 Top10
    kr150_top10_tickers = [re.sub(r'\*+', '', s.get('ticker', '')).strip()[:6]
                           for s in cards_data.get('top10', [])]
    save_tickers(ORDER_DIR / "0kr150_top10.txt", kr150_top10_tickers)

    # 5) 전종목 Top10
    kr_top10_tickers = [r['ticker'] for r in cards_data.get('top30_kr', [])]
    save_tickers(ORDER_DIR / "0kr_top10.txt", kr_top10_tickers)

    # 6) 🚀 로켓 (C그룹) → 매수후보 (거래대금 순) : 00_1887_a_grade_leader.txt 와 동일 형식(끝줄 개행 포함)
    rocket_tickers = [re.sub(r'\*+', '', str(r['ticker'])).strip()[:6]
                      for r in cards_data.get('rocket', [])]
    rocket_tickers = [t for t in rocket_tickers if re.fullmatch(r'\d{6}', t)]
    C_GRADE_LEADER_TXT.write_text(
        '\n'.join(rocket_tickers) + ('\n' if rocket_tickers else ''), encoding='utf-8')
    print(f"[ORDER] {C_GRADE_LEADER_TXT} → {len(rocket_tickers)}종목 저장")
    # ────────────────────────────────────────────────────────────────────────────

    # 2. 체결강도 API 동시요청 (등락률 pre_rt 도 함께 수집)
    cs_dict, rate_dict, tv_dict = get_contract_strength_for_tickers(list(tickers_to_fetch))

    # HA 관심종목 카드 데이터: 기존 소스로 보강 후 kr.csv(종목명/NXT) + ka10003 등락률 fallback
    ha_rows = build_a_leader_rows(
        ha_codes, spot_kr_rows, leader_kr_rows, all_kr_sig,
        top30_kr_rows, vol_data, pool_items, tracking_volume, track, tracking_all,
    )
    for r in ha_rows:
        t6 = str(r['ticker']).zfill(6)
        meta = kr_meta.get(t6, {})
        if r['name'] == r['ticker'] and meta.get('name'):
            r['name'] = meta['name']
        if not r['nxt'] and meta.get('nxt'):
            r['nxt'] = meta['nxt']
        if r['pct'] in ('', '-', None) and rate_dict.get(t6):
            r['pct'] = rate_dict[t6]
    cards_data['ha'] = ha_rows

    # 3. HTML 생성
    html_cards = []

    # ── 1행: KR전종목 신호 (SPOT+주도주 / GANN / LIME·MOM·GREEN) ──

    # 1-0 A 리더: SPOT 카드와 같은 row 포맷
    a_leader_html = ''
    for r in cards_data.get('a_leader', []):
        t = r['ticker'].zfill(6)
        a_leader_html += badged_stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'], r['tv_str'], 'A', '#c0392b')
    if a_leader_html:
        html_cards.append(('krall_row1', make_card('A 리더', '[KR전종목]', len(cards_data.get('a_leader', [])), a_leader_html, 'SPOT', badge_text='')))

    # 1-0b B 리더: A 리더와 같은 row 포맷 (B 뱃지)
    b_leader_html = ''
    for r in cards_data.get('b_leader', []):
        t = r['ticker'].zfill(6)
        b_leader_html += badged_stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'], r['tv_str'], 'B', '#e67e22')
    if b_leader_html:
        html_cards.append(('krall_row1', make_card('B 리더', '[KR전종목]', len(cards_data.get('b_leader', [])), b_leader_html, 'MOM', badge_text='')))

    # 1-1 [📊 SPOT/주도주들] 새 섹션 (group='spot_judo')
    #     1열 SPOT(전종목) / 2열 KR150 주도주(오늘) / 3열 주도주(전종목)
    spot_kr_list = cards_data['spot_kr']
    leader_kr_list = cards_data['leader_kr']

    # 1열: SPOT [KR전종목]
    spot_html = ''
    for r in spot_kr_list:
        t = r['ticker'].zfill(6)
        spot_html += badged_stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'], r['tv_str'], 'S', '#e74c3c')
    if spot_html:
        html_cards.append(('spot_judo', make_card('SPOT', '[KR전종목]', len(spot_kr_list), spot_html, 'SPOT')))

    # 2열: 주도주 (오늘) [KR150]
    kr150_leader = cards_data.get('leader', [])
    leader150_html = ''
    for s in kr150_leader:
        t = re.sub(r'\*+', '', str(s.get('ticker', ''))).zfill(6)
        tv_raw = s.get('trade_amount', 0) or 0
        tv_str = f'{tv_raw/100_000_000:,.0f}억' if isinstance(tv_raw, (int, float)) and tv_raw > 0 else '-'
        leader150_html += badged_stock_row(t, s.get('name', ''), s.get('change', '-'), cs_dict.get(t, '-'), s.get('nxt', ''), tv_str, '150', '#16a085')
    if leader150_html:
        html_cards.append(('spot_judo', make_card('주도주 (오늘)', '[KR150]', len(kr150_leader), leader150_html, 'TRACK')))

    # 3열: 주도주 [KR전종목]
    leaderkr_html = ''
    for r in leader_kr_list:
        t = r['ticker'].zfill(6)
        leaderkr_html += badged_stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'], r['tv_str'], '주', '#8e44ad')
    if leaderkr_html:
        html_cards.append(('spot_judo', make_card('주도주', '[KR전종목]', len(leader_kr_list), leaderkr_html, 'TRACK')))

    # 1-2 KR전종목: LIME, MOM  (별도 행 'krall_limemom' → 4번째 줄)
    for sig in ['LIME', 'MOM']:
        rows = [r for r in cards_data['kr_sig'] if r['sig'].upper() == sig]
        if not rows: continue
        rows.sort(key=lambda x: x['tv_int'], reverse=True)
        r_html = ''
        for r in rows:
            t = r['ticker'].zfill(6)
            r_html += stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'], tv_html(r['tv_str']))
        html_cards.append(('krall_limemom', make_card(f'{sig} 신호', '[KR전종목]', len(rows), r_html, sig)))

    # 1-2b 🚀 로켓 (C그룹): 거래대금 내림차순, 10종목씩 카드 분리 (GANN 방식)
    rocket_list  = cards_data.get('rocket', [])
    rocket_hl    = cards_data.get('rocket_hl', set())
    ROCKET_CHUNK = 10
    rocket_count = len(rocket_list)
    if rocket_list:
        chunks = [rocket_list[i:i+ROCKET_CHUNK] for i in range(0, rocket_count, ROCKET_CHUNK)]
        for idx, chunk in enumerate(chunks):
            r_html = ''
            for r in chunk:
                t = r['ticker'].zfill(6)
                r_html += stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'],
                                    tv_html(f"{r['tv_eok']:,.0f}억"), highlight=(t in rocket_hl))
            sub = 'Top30중 🚀 + 천억 (노랑: vol top30)'
            if len(chunks) > 1:
                start_n = idx * ROCKET_CHUNK + 1
                end_n   = min((idx + 1) * ROCKET_CHUNK, rocket_count)
                sub += f' {start_n}~{end_n}'
            html_cards.append(('krall_row1', make_card('C 리더(150+전종목)', sub, rocket_count, r_html, 'ROCKET', badge_text='C')))

    # 1-2c HA 관심종목 (00_1887_ha.txt) → A/B/C 리더 다음 열
    ha_list = cards_data.get('ha', [])
    if ha_list:
        ha_html = ''
        for r in ha_list:
            t = str(r['ticker']).zfill(6)
            ha_html += badged_stock_row(t, r['name'], r['pct'], cs_dict.get(t, '-'), r['nxt'], r['tv_str'], 'HA', '#34495e')
        html_cards.append(('krall_row1', make_card('HA 관심', '[1887]', len(ha_list), ha_html, 'TRACK', badge_text='HA')))

    # 1-3 KR전종목: GANN (별도 행, 8종목씩 분할)
    # ※ GANN 거래대금 필터 기준: tv_int 단위 = 억. 아래 값을 수정하면 기준 변경 가능
    GANN_TV_MIN = 200  # 200억 미만 제외
    gann_all = sorted(cards_data['gann'].items(), key=lambda x: x[1].get('tv_int', 0), reverse=True)
    gann_items = [(t, v) for t, v in gann_all if v.get('tv_int', 0) >= GANN_TV_MIN]
    gann_count = len(gann_items)
    if gann_items:
        if gann_count <= 8:
            row_html = ''
            for t, v in gann_items:
                t_clean = t.zfill(6)
                row_html += stock_row(t_clean, v.get('name',''), v.get('pct','-'), cs_dict.get(t_clean, '-'), v.get('nxt',''), tv_html(v.get('tv_str','')))
            html_cards.append(('krall_row2', make_card('GANN 신호', '[KR전종목]', gann_count, row_html, 'GANN')))
        else:
            chunks = [gann_items[i:i+8] for i in range(0, gann_count, 8)]
            for idx, chunk in enumerate(chunks):
                start_n = idx * 8 + 1
                end_n   = min((idx + 1) * 8, gann_count)
                row_html = ''
                for t, v in chunk:
                    t_clean = t.zfill(6)
                    row_html += stock_row(t_clean, v.get('name',''), v.get('pct','-'), cs_dict.get(t_clean, '-'), v.get('nxt',''), tv_html(v.get('tv_str','')))
                sub_title = f'[KR전종목] {start_n}~{end_n}'
                html_cards.append(('krall_row2', make_card('GANN 신호', sub_title, gann_count, row_html, 'GANN')))

    # ── 2행: KR150 (거래대금Top10 / 종합Top10 / KR전종목Top10) ──

    # 2-1 거래대금 Top10 (먼저)
    row_html = ''
    for s in cards_data['vol']:
        t = s.get('ticker','').zfill(6)
        v = s.get('trade_amount', 0) / 100
        row_html += stock_row(t, s.get('name',''), s.get('change',0), cs_dict.get(t, '-'), s.get('nxt',''), tv_html(f'{v:,.0f}억'))
    if row_html: html_cards.append(('kr150', make_card('거래대금 Top 10', '[시장전체]', min(10, len(cards_data['vol'])), row_html, 'VOL')))

    # 2-2 KR150 Top10
    row_html = ''
    top10_list = cards_data['top10']
    for i, s in enumerate(top10_list):
        t = re.sub(r'\*+', '', s.get('ticker','')).zfill(6)
        tv_raw = s.get('trade_amount', 0)
        tv_str = f'{tv_raw/100_000_000:,.0f}억' if isinstance(tv_raw, (int, float)) and tv_raw > 0 else '-'
        extra = tv_html(tv_str)
        if s.get("new_sig") and s.get("new_sig") != "-": extra += f' 🆕{s.get("new_sig")}'
        row_html += stock_row(t, s.get('name',''), s.get('change','-'), cs_dict.get(t, '-'), s.get('nxt',''), extra)
    if row_html: html_cards.append(('kr150', make_card('종합 Top 10', '[KR150]', len(top10_list), row_html, 'TOP10')))

    # 2-3 KR전종목 Top10 (report_kr_summary.txt 종합 Top30 기준)
    row_html = ''
    top30_kr_list = cards_data['top30_kr']
    for i, s in enumerate(top30_kr_list):
        t = s['ticker'].zfill(6)
        extra = tv_html(s.get("tv_str", "-"))
        if s.get('new_sig') and s['new_sig'] != '-': extra += f' 🆕{s["new_sig"]}'
        row_html += stock_row(t, s['name'], s['pct'], cs_dict.get(t, '-'), s['nxt'], extra)
    if row_html: html_cards.append(('kr150', make_card('종합 Top 10', '[KR전종목]', len(top30_kr_list), row_html, 'TOP10')))


    def section_wrap(title, cards, color):
        c_html = ''.join([c for g, c in html_cards if g == cards])
        if not c_html: return ''
        return f'<div class="section"><h3 class="sec-title" style="border-bottom-color:{color};">{title}</h3><div class="cards-row">{c_html}</div></div>'

    def section_wrap_2row(title, row1_key, row2_key, color):
        row1_html = ''.join([c for g, c in html_cards if g == row1_key])
        row2_html = ''.join([c for g, c in html_cards if g == row2_key])
        if not row1_html and not row2_html: return ''
        inner = ''
        if row1_html: inner += f'<div class="cards-row" style="margin-bottom:14px;">{row1_html}</div>'
        if row2_html: inner += f'<div class="cards-row">{row2_html}</div>'
        return f'<div class="section"><h3 class="sec-title" style="border-bottom-color:{color};">{title}</h3>{inner}</div>'

    daily_theme_html     = build_daily_theme_section()
    yesterday_theme_html = build_yesterday_theme_section(cs_dict, rate_dict, tv_dict)

    # 1~3줄(주도주/테마주 · 당일/전일 테마 · 거래대금+Top10) 다음에 TR 주문 예상표를 이어서 배치 (단일 컬럼)
    html_content = (
        section_wrap('📊 주도주/테마주', 'krall_row1', '#2980b9') +
        daily_theme_html +
        yesterday_theme_html +
        section_wrap('📊 거래대금 + Top10', 'kr150', '#e74c3c') +
        build_kr_tr_order() +
        build_kr_tr_weekly() +
        # 4줄: SPOT/주도주들 (SPOT전종목 / KR150 주도주(오늘) / 주도주 전종목)
        section_wrap('📊 SPOT/주도주들', 'spot_judo', '#c0392b') +
        # 5줄: LIME/MOM
        section_wrap('📊 LIME/MOM  [KR전종목]', 'krall_limemom', '#2980b9') +
        # 6줄: GANN
        section_wrap('📊 GANN 신호 [KR전종목]', 'krall_row2', '#2980b9')
    )

    def generate_page(nav_html=""):
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
.sec-title {{ font-size: 0.95em; font-weight: bold; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 4px; margin-bottom: 12px; margin-top:20px; max-width: 1134px; }}
.cards-row {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: flex-start; align-items: flex-start; }}

.styled-tableWide {{ width: auto; max-width: 100%; border-collapse: collapse; margin: 5px 0 12px 0; font-size: 12px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 6px; overflow: hidden; }}
.styled-tableWide thead tr {{ background-color: #e67e22; color: #fff; text-align: left; }}
.styled-tableWide th, .styled-tableWide td {{ padding: 4px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
.styled-tableWide td.ticker-col {{ width: 70px; font-weight: 600; color: #2980b9; }}
.styled-tableWide tbody tr:nth-of-type(even) {{ background-color: #fdf8f4; }}
.styled-tableWide tbody tr:last-of-type {{ border-bottom: 2px solid #e67e22; }}
.tr-order-title {{ font-size: 1.08em; }}
.tr-order-table {{ font-size: 15px; }}
.tr-order-table th, .tr-order-table td {{ padding: 7px 12px; }}
.tr-order-table td.ticker-col {{ width: 86px; }}

/* 카드 스타일 */
.theme-card {{
  background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  flex: 0 0 auto; width: 370px;
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
.stock-name {{ font-weight: bold; color: #333; flex: 1; min-width: 120px; white-space: nowrap; overflow: visible; }}
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
  .theme-card {{ width: 330px; }}
}}
@media (max-width: 600px) {{
  .theme-card {{ width: 100%; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}

/* ── 네이버 차트 팝업 ── */
.naver-trigger {{ text-decoration: underline dotted; }}
#naverChartPopup {{
  display: none; position: fixed; z-index: 99999;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; overflow-y: auto; max-height: 90dvh;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex; background: #e74c3c; color: white;
  border: none; border-radius: 50%;
  width: 28px; height: 28px; font-size: 18px; line-height: 1;
  cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center; font-weight: bold;
}}
.popup-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; margin-left: 1em; }}
.popup-link:hover {{ text-decoration: underline; }}
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.chart-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fafafa; }}
.chart-card-header {{ display: none; }}
.chart-card-title {{ font-size: 12px; font-weight: 700; color: #334155; }}
.chart-status {{ font-size: 11px; color: #94a3b8; }}
.chart-wrap {{ position: relative; width: 100%; height: 285px; background: white; }}
.chart-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: white; }}
.chart-loading {{ display: none; position: absolute; inset: 0; background: rgba(255,255,255,0.75); align-items: center; justify-content: center; font-size: 12px; color: #64748b; }}
.chart-loading.show {{ display: flex; }}
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
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
  .charts-grid {{ grid-template-columns: 1fr; }}
  .chart-wrap {{ height: 260px; }}
}}
</style>
</head>
<body>

{"<div class='top-nav-container'><div class='top-nav'>" + nav_html + "</div></div>" if nav_html.strip() else ""}

<div class="update-bar">
  📡 업데이트: {now} (제시된 종목들만 실시간 체결강도 업데이트 완료)
</div>

{html_content}

<div id="naverChartPopup">
  <div class="popup-header">
    <button id="naverPopupClose" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-card-header">
        <div class="chart-card-title">당일 선차트 (1일)</div>
        <div class="chart-status" id="statusIntraday">대기중</div>
      </div>
      <div class="chart-wrap">
        <img id="imgIntraday" alt="당일 차트">
        <div class="chart-loading" id="loadingIntraday">불러오는 중...</div>
      </div>
    </div>
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
  </div>
</div>
<script>
(function () {{ return;
  var popup   = document.getElementById('naverChartPopup');
  var popupTitle  = document.getElementById('popupTitle');
  var popupLink   = document.getElementById('popupLink');
  var imgIntraday = document.getElementById('imgIntraday');
  var imgDaily    = document.getElementById('imgDaily');
  var loadingIntraday = document.getElementById('loadingIntraday');
  var loadingDaily    = document.getElementById('loadingDaily');
  var statusIntraday  = document.getElementById('statusIntraday');
  var statusDaily     = document.getElementById('statusDaily');
  var hoverTimer = null;
  var pinned = false;

  var TS = Date.now();
  function withTs(url) {{ return url + '?t=' + TS; }}
  function intradayUrl(code)    {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/area/day/'   + code + '.png'); }}
  function dailyCandleUrl(code) {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/' + code + '.png'); }}
  function itemPageUrl(code)    {{ return 'https://finance.naver.com/item/main.naver?code=' + code; }}

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

  function loadCharts(code) {{
    popupTitle.textContent = code;
    popupLink.href = itemPageUrl(code);
    loadInto(imgIntraday, loadingIntraday, statusIntraday, intradayUrl(code),    '당일');
    loadInto(imgDaily,    loadingDaily,    statusDaily,    dailyCandleUrl(code), '일봉');
  }}

  function placePopup(cx, cy) {{
    var isMobile = window.innerWidth <= 767;
    if (isMobile) return;
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

  function attachNaverTrigger(el) {{
    var code = el.getAttribute('data-code');
    if (!code) return;
    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 768) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        loadCharts(code);
      }}, 140);
    }});
    el.addEventListener('mousemove', function (e) {{
      if (window.innerWidth <= 768) return;
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    el.addEventListener('mouseleave', function () {{
      if (window.innerWidth <= 768) return;
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    el.addEventListener('click', function (e) {{
      e.stopPropagation();
      clearTimeout(hoverTimer);
      placePopup(e.clientX, e.clientY);
      openPopup();
      loadCharts(code);
    }});
  }}

  document.querySelectorAll('.naver-trigger[data-code]').forEach(attachNaverTrigger);

  (function () {{
    var seen = {{}}, queue = [];
    document.querySelectorAll('.naver-trigger[data-code]').forEach(function (el) {{
      var c = el.getAttribute('data-code');
      if (!c || seen[c]) return;
      seen[c] = true; queue.push(c);
    }});
    var idx = 0, CONCURRENCY = 3;
    function next() {{
      if (idx >= queue.length) return;
      var c = queue[idx++], done = 0;
      function step() {{ if (++done >= 2) next(); }}
      [intradayUrl(c), dailyCandleUrl(c)].forEach(function (u) {{
        var im = new Image(); im.onload = step; im.onerror = step; im.src = u;
      }});
    }}
    setTimeout(function () {{ for (var i = 0; i < CONCURRENCY && i < queue.length; i++) next(); }}, 300);
  }})();

  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767 && popup.style.display === 'block') {{
      if (!popup.contains(e.target)) closePopup();
    }} else if (window.innerWidth > 767) {{
      if (!e.target.closest('#naverChartPopup') && !e.target.closest('.naver-trigger')) {{
        closePopup();
      }}
    }}
  }});
}})();
</script>

</body>
</html>
"""
        import re as _re
        from chart_popup_v4 import build_chart_popup as _bcp_v4
        _codes = sorted(set(_re.findall(r'data-code="([^"]+)"', page)))
        page = page.replace(
            "</body>",
            _bcp_v4(_codes, market="KR", trigger_attr="data-code", include_kospi=False) + "\n</body>",
            1,
        )
        return page

    # 1. Global Summary Page
    nav_global = """    <a href="main_hub.html" class="nav-item">상황판</a>
    <a href="order.html" class="nav-item">주문</a>
    <a href="summary.html" class="nav-item active">요약</a>
    <a href="danta_chart.html" class="nav-item">단타</a>
    <a href="kr_chart.html" class="nav-item">차트</a>
    <a href="us_summary.html" class="nav-item">미국요약</a>"""
    
    page_global = generate_page(nav_global)
    OUT_HTML.write_text(page_global, encoding='utf-8')
    print(f"\n[OK] summary.html 생성 완료: {OUT_HTML}")

    # 2. ETF Summary Page (독립 게시판 - nav 없음)
    page_etf = generate_page("")
    OUT_ETF_HTML.write_text(page_etf, encoding='utf-8')
    print(f"[OK] etf_summary.html 생성 완료: {OUT_ETF_HTML}")

if __name__ == '__main__':
    main()




