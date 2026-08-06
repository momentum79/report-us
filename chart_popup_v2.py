# chart_popup_v2.py ── 내장형 인터랙티브 차트 팝업 빌더 (네이버 PNG 팝업 대체)
# 5분봉(키움 ka10080 _AL, 5일치 NXT통합, X신호 percentrank220 확보용) + 일봉(네이버 siseJson, 3년).
# OHL 호버툴팁 + 일자경계 빈칸/점선. 크기는 V1↔V2 중간(팝업 1020×480, 캔들칸 ~493×350).
# 사용: from chart_popup_v2 import build_chart_popup ;  block = build_chart_popup(codes)
import os, csv, json, time, re, urllib.request
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor
import requests
from dotenv import load_dotenv

BASE_DIR = r"D:\py"
load_dotenv(os.path.join(BASE_DIR, ".env"))
APP_KEY    = os.getenv("KIWOOM_APP_KEY_1887")
SECRET_KEY = os.getenv("KIWOOM_SECRET_KEY_1887")
KIWOOM_DOMAIN = "https://api.kiwoom.com"
KR_CSV_PATH   = os.path.join(BASE_DIR, "korea", "kr.csv")

YEARS_BACK  = 3
MAX_WORKERS = 8
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://finance.naver.com/"}
EXPLICIT_NXT = {"069500", "114800"}

# ───────── 일봉 (네이버 siseJson, 3년) ─────────
def _fetch(url, retries=3):
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e; time.sleep(0.4 * (a + 1))
    raise last

_DAY_PAT = re.compile(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*(\d+)')

def fetch_daily(code, s_ymd, e_ymd):
    url = ("https://api.finance.naver.com/siseJson.naver"
           f"?symbol={code}&requestType=1&startTime={s_ymd}&endTime={e_ymd}&timeframe=day")
    raw = _fetch(url); out = []
    for m in _DAY_PAT.finditer(raw):
        d, o, h, l, c, v = m.groups()
        out.append([f"{d[0:4]}-{d[4:6]}-{d[6:8]}", float(o), float(h), float(l), float(c), int(v)])
    return out

def collect_daily(codes):
    end = date.today(); start = end - timedelta(days=365 * YEARS_BACK + 15)
    s_ymd, e_ymd = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    res = {}
    def work(c):
        try:
            return c, fetch_daily(c, s_ymd, e_ymd)
        except Exception as e:
            print(f"  [일봉ERR] {c}: {e}"); return c, []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for c, rows in ex.map(work, codes):
            res[c] = rows
    return res

# ───────── coloryp 추세배경 (일봉·5분봉 공통, v4 판정식 동일) ─────────
_COLORYP_FN = None
def _coloryp_fn():
    global _COLORYP_FN
    if _COLORYP_FN is None:
        import sys
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (here, os.path.dirname(here)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from coloryp_core import check_coloryp_logic
        _COLORYP_FN = check_coloryp_logic
    return _COLORYP_FN

def _trend_states(times, o, h, l, c, v):
    import numpy as np, pandas as pd
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v},
                      index=pd.to_datetime(list(times)))
    calc = _coloryp_fn()(df)
    angle_all = (calc[[f"m{i}ang" for i in range(5)]] <= 0).all(axis=1)
    angle_4   = (calc[[f"m{i}ang" for i in range(4)]] <= 0).all(axis=1)
    is_lime   = calc["lime_final"]
    is_green  = (calc["HLv99"] >= 1) & (calc["HLv71"] == 1) & ~is_lime
    is_red    = (((calc["HLv99"] <= -1) & (calc["HLv7"] == -1) & (calc["HLv71"] == -1))
                 | (calc["ang_sum"] == -5) | angle_all)
    is_purple = ((calc["HLv99"] <= -1) & (calc["HLv71"] == -1)) | angle_4
    return np.select([is_lime, is_green, is_red, is_purple],
                     ["LIME", "GREEN", "RED", "PURPLE"], default="NONE")

def attach_trend_daily(rows):
    """일봉 rows[date,o,h,l,c,v] → coloryp state를 index[6]에 append (NONE이면 미부착)."""
    if not rows:
        return rows
    try:
        cols = list(zip(*rows))
        st = _trend_states(cols[0], cols[1], cols[2], cols[3], cols[4], cols[5])
        return [list(r) + ([str(st[i])] if st[i] != "NONE" else []) for i, r in enumerate(rows)]
    except Exception as e:
        print(f"  [추세배경-일] 계산 실패: {e}")
        return [list(r) for r in rows]

def attach_trend_5m(rows):
    """5분봉 rows[ts,o,h,l,c,v,'YYYY-MM-DD HH:MM'] → coloryp state를 index[7]에 append."""
    if not rows:
        return rows
    try:
        times = [r[6] for r in rows]
        o = [r[1] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]
        c = [r[4] for r in rows]; v = [r[5] for r in rows]
        st = _trend_states(times, o, h, l, c, v)
        return [list(r) + ([str(st[i])] if st[i] != "NONE" else []) for i, r in enumerate(rows)]
    except Exception as e:
        print(f"  [추세배경-5분] 계산 실패: {e}")
        return [list(r) for r in rows]

# ───────── NXT 판정 ─────────
_NXT = None
def _load_nxt():
    global _NXT
    if _NXT is not None:
        return _NXT
    s = set()
    try:
        with open(KR_CSV_PATH, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if str(row.get("NXT", "")).strip() == "NXT":
                    s.add(str(row.get("티커", "")).strip().zfill(6))
    except FileNotFoundError:
        pass
    _NXT = s; return s

def is_nxt(code):
    c = str(code).zfill(6)
    return c in EXPLICIT_NXT or c in _load_nxt()

def _chart_code(code):
    return f"{code}_AL" if is_nxt(code) else code

# ───────── 5분봉 (키움 ka10080, 2일치) ─────────
def _kiwoom_token():
    r = requests.post(KIWOOM_DOMAIN + "/oauth2/token",
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": SECRET_KEY},
        timeout=10)
    r.raise_for_status()
    tok = r.json().get("token")
    if not tok:
        raise RuntimeError("키움 토큰 실패")
    return tok

def fetch_5min(token, code, days=2, max_pages=8):
    api = _chart_code(code); rows = []; nk = ""; cont = "N"
    for _ in range(max_pages):
        h = {"api-id": "ka10080", "Authorization": f"Bearer {token}",
             "Content-Type": "application/json;charset=UTF-8", "cont-yn": cont, "next-key": nk}
        p = {"stk_cd": api, "tic_scope": "5", "upd_stkpc_tp": "1"}
        r = requests.post(KIWOOM_DOMAIN + "/api/dostk/chart", headers=h, data=json.dumps(p), timeout=10)
        d = r.json()
        if d.get("return_code", -1) != 0:
            break
        arr = d.get("stk_min_pole_chart_qry", [])
        if not arr:
            break
        for c in arr:
            tm = str(c.get("cntr_tm", "")).strip()
            if len(tm) < 12:
                continue
            y, mo, dd, hh, mi = tm[0:4], tm[4:6], tm[6:8], tm[8:10], tm[10:12]
            ts = int(datetime(int(y), int(mo), int(dd), int(hh), int(mi)).timestamp())
            rows.append([ts,
                abs(int(str(c.get("open_pric", 0) or 0).replace(",", ""))),
                abs(int(str(c.get("high_pric", 0) or 0).replace(",", ""))),
                abs(int(str(c.get("low_pric",  0) or 0).replace(",", ""))),
                abs(int(str(c.get("cur_prc",   0) or 0).replace(",", ""))),
                abs(int(str(c.get("trde_qty",  0) or 0).replace(",", ""))),
                f"{y}-{mo}-{dd} {hh}:{mi}"])
        if len({x[6][:10] for x in rows}) >= days + 1:
            break
        cont = r.headers.get("cont-yn", "N"); nk = r.headers.get("next-key", "")
        if cont != "Y":
            break
    rows.sort(key=lambda x: x[0])
    keep = sorted({x[6][:10] for x in rows})[-days:]
    rows = [x for x in rows if x[6][:10] in keep]
    for x in rows:
        x[0] += 9 * 3600  # 축 라벨 KST 표기용
    return rows

def _load_json_cache(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_json_cache(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"  [캐시저장 실패] {path}: {e}")

def collect_5min(codes, days=2, cache_path=None, token=None):
    # 캐시 폴백: 평일엔 라이브 수집분을 cache_path에 덮어쓰고, 휴장일(라이브 0개)엔
    # 직전거래일 캐시로 대체. cache_path=None이면 캐시 미사용(기존 동작 100% 동일).
    # token: 외부에서 발급한 토큰 공유(없으면 자체 발급).
    res = {c: [] for c in codes}
    cache = _load_json_cache(cache_path)
    if token is None:
        if not APP_KEY or not SECRET_KEY:
            print("  [5분봉] 키움 키 없음(.env) → 라이브 건너뜀")
        else:
            try:
                token = _kiwoom_token()
            except Exception as e:
                print(f"  [5분봉] 토큰실패: {e}")
    if token:
        for c in codes:
            try:
                res[c] = fetch_5min(token, c, days=days)
            except Exception as e:
                print(f"  [5분봉ERR] {c}: {e}")
            time.sleep(0.22)
    got_any = any(res[c] for c in codes)
    # 라이브가 빈 종목은 직전거래일 캐시로 폴백
    n_fb = 0
    for c in codes:
        if not res[c] and cache.get(c):
            res[c] = cache[c]
            n_fb += 1
    if n_fb:
        print(f"  [5분봉] {n_fb}종목 캐시(직전거래일) 폴백")
    # 라이브를 1종목이라도 받았을 때만 캐시 갱신 (휴장일에 빈값으로 덮어쓰기 방지)
    if got_any and cache_path:
        _save_json_cache(cache_path, res)
    return res

# ───────── KOSPI 종합지수 오버레이 (종목과 무관 → 1회만 수집해 전 팝업 공유) ─────────
def fetch_kospi_daily(days_back=60):
    # 네이버 siseJson (symbol=KOSPI) → {YYYY-MM-DD: 종가}. 주말에도 동작.
    end = date.today(); start = end - timedelta(days=days_back)
    try:
        rows = fetch_daily("KOSPI", start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    except Exception as e:
        print(f"  [KOSPI일봉] 실패: {e}")
        return {}
    return {r[0]: r[4] for r in rows}

def fetch_kospi_5min(token, max_pages=4):
    # 키움 ka20005 업종분봉, 코스피 종합 업종코드 '001'. 최신 1거래일 09:00~15:30만.
    # 지수값은 ×100 정수로 옴(812362=8123.62)이지만 rebase 비율에서 약분되므로 raw 사용.
    rows = {}; nk = ""; cont = "N"
    for _ in range(max_pages):
        h = {"api-id": "ka20005", "Authorization": f"Bearer {token}",
             "Content-Type": "application/json;charset=UTF-8", "cont-yn": cont, "next-key": nk}
        p = {"inds_cd": "001", "tic_scope": "5"}
        r = requests.post(KIWOOM_DOMAIN + "/api/dostk/chart", headers=h, data=json.dumps(p), timeout=10)
        d = r.json()
        if d.get("return_code", -1) != 0:
            break
        arr = d.get("inds_min_pole_qry", [])
        if not arr:
            break
        for c in arr:
            tm = str(c.get("cntr_tm", "")).strip()
            if len(tm) < 12:
                continue
            y, mo, dd, hh, mi = tm[0:4], tm[4:6], tm[6:8], tm[8:10], tm[10:12]
            hm = hh + ":" + mi
            if hm < "09:00" or hm > "15:30":   # 정규장만
                continue
            val = str(c.get("cur_prc", 0) or 0).replace(",", "").replace("+", "").replace("-", "")
            rows[f"{y}-{mo}-{dd} {hh}:{mi}"] = abs(int(val or 0))
        if len({k[:10] for k in rows}) >= 2:
            break
        cont = r.headers.get("cont-yn", "N"); nk = r.headers.get("next-key", "")
        if cont != "Y":
            break
    if rows:   # 최신 1거래일만 유지 (당일단타 비교용)
        last_day = sorted({k[:10] for k in rows})[-1]
        rows = {k: v for k, v in rows.items() if k[:10] == last_day}
    return rows

def collect_kospi_5min(cache_path=None, token=None):
    cache = _load_json_cache(cache_path)
    live = {}
    if token:
        try:
            live = fetch_kospi_5min(token)
        except Exception as e:
            print(f"  [KOSPI5분봉] 실패: {e}")
    if live:
        if cache_path:
            _save_json_cache(cache_path, live)
        return live
    if cache:
        print("  [KOSPI5분봉] 캐시(직전거래일) 폴백")
        return cache
    return {}

# ───────── 팝업 정적 자원 ─────────
POPUP_CSS = """
#naverChartPopup{display:none;position:fixed;z-index:99999;width:min(1020px,96vw);
  background:#fff;border:1px solid #bdc3c7;border-radius:10px;padding:12px;
  box-shadow:0 10px 28px rgba(0,0,0,.22);pointer-events:auto;max-height:90vh;overflow-y:auto;
  overscroll-behavior:contain;-webkit-overflow-scrolling:touch;}
body.naver-popup-open{overflow:hidden;}
#naverPopupClose{display:flex;align-items:center;justify-content:center;width:28px;height:28px;
  border:none;background:#e74c3c;color:#fff;border-radius:50%;font-size:18px;cursor:pointer;flex-shrink:0;}
.popup-header{display:flex;align-items:center;gap:10px;margin-bottom:8px;}
.popup-title{font-weight:700;color:#2c3e50;font-size:14px;white-space:nowrap;}
.popup-link{font-size:12px;color:#2980b9;text-decoration:none;white-space:nowrap;}
.popup-link:hover{text-decoration:underline;}
#popMs{font-size:12px;color:#16a34a;font-weight:700;font-family:monospace;}
#stBtn{position:absolute;left:14px;bottom:12px;z-index:20;width:54px;height:34px;flex-shrink:0;cursor:pointer;
  border:2px solid #7c3aed;background:#f5f3ff;color:#ef4444;font-weight:800;
  font-size:16px;line-height:1;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.16);}
#stBtn.on{background:#7c3aed;color:#fff;}
#popBox{display:grid;grid-template-columns:55fr 45fr;gap:12px;position:relative;}
.col{display:flex;flex-direction:column;min-width:0;position:relative;}
/* 타임프레임 뱃지: 캔들차트 우측 끝 위(가격축 왼쪽)에 오버레이 */
.collab{position:absolute;top:2px;right:64px;z-index:7;font-size:11px;font-weight:700;color:#374151;pointer-events:none;}
.tfbadge{display:inline-block;min-width:16px;padding:1px 6px;border:1px solid #9ca3af;border-radius:4px;background:rgba(255,255,255,.9);font-size:12px;font-weight:700;color:#374151;text-align:center;line-height:1.35;}
.chartbox{position:relative;}
.cchart{width:100%;height:300px;}
.rlab{font-size:10px;color:#94a3b8;padding:3px 0 1px;}
.rchart{width:100%;height:100px;}
.exlab{position:absolute;z-index:7;display:none;white-space:nowrap;font-size:11px;font-weight:700;
  padding:1px 5px;border-radius:4px;pointer-events:none;background:rgba(255,255,255,.93);
  box-shadow:0 1px 4px rgba(0,0,0,.18);}
.exlo{color:#2962ff;border:1px solid #93c5fd;}
.exhi{color:#f23645;border:1px solid #fca5a5;}
.exar{font-size:10px;}
.legend{position:absolute;display:none;z-index:6;background:rgba(255,255,255,.96);
  border:1px solid #e5e7eb;border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.55;
  color:#334155;pointer-events:none;min-width:168px;box-shadow:0 2px 8px rgba(0,0,0,.13);}
.legend b{color:#0f172a;}
.legend .k{display:inline-block;width:42px;color:#64748b;}
.divider{position:absolute;top:0;bottom:0;width:0;display:none;z-index:4;
  border-left:2px dashed rgba(40,40,40,.85);pointer-events:none;}
.tradearrow{position:absolute;z-index:8;width:0;height:0;display:none;pointer-events:none;}
.tradearrow.up{border-left:5px solid transparent;border-right:5px solid transparent;
  border-bottom:11px solid #000;transform:translate(-50%,0);}
.tradearrow.dn{border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:11px solid #000;transform:translate(-50%,-100%);}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#991b1b;font-weight:700;}
td[data-code],td[data-code] + td{cursor:pointer;}
td[data-code] + td:hover{background-color:#e8f4f8 !important;}
@media (max-width:900px){#popBox{grid-template-columns:1fr;}}
.popTabs{display:none;}
@media (max-width:767px){
  #naverChartPopup{left:2vw !important;top:4vh !important;width:96vw;
    max-height:78vh;transform:none !important;}
  .cchart{height:225px;}.rchart{height:62px;}
  #naverPopupClose{display:flex !important;}
  .popup-link,#popMs{display:none;}  /* 모바일에선 헤더 공간 절약 */
  /* 긴 종목명은 말줄임(…) 처리 → 5분봉/일봉 탭 공간 확보 */
  .popup-title{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;}
  .popTabs{display:flex;gap:6px;margin-left:auto;flex-shrink:0;}
  .popTab{padding:5px 11px;border:1px solid #bdc3c7;background:#f5f5f5;border-radius:6px;
    font-size:12px;font-weight:700;color:#34495e;cursor:pointer;line-height:1;}
  .popTab.active{background:#2980b9;color:#fff;border-color:#2980b9;}
  .col.hidden{display:none;}
}
"""

POPUP_HTML = """
<div id="naverChartPopup" tabindex="-1">
  <div class="popup-header">
    <button id="naverPopupClose">&#x2715;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 종목 페이지</a>
    <span id="popMs"></span>
    <button id="stBtn" title="Supertrend 토글 (10/3·11/2·12/1) · a키">S</button>
    <div class="popTabs">
      <button class="popTab active" data-tab="5">5분봉</button>
      <button class="popTab" data-tab="d">일봉</button>
    </div>
  </div>
  <div id="popBox">
    <div class="col" id="col5">
      <div class="collab"><span class="tfbadge">5</span> <span id="mt5"></span></div>
      <div class="chartbox"><div class="legend" id="lg5"></div><div class="cchart" id="chart5"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div><div class="rchart" id="rsi5"></div></div>
    </div>
    <div class="col" id="colD">
      <div class="collab"><span class="tfbadge">일</span> <span id="mtD"></span></div>
      <div class="chartbox"><div class="legend" id="lgD"></div><div class="cchart" id="chartD"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div><div class="rchart" id="rsiD"></div></div>
    </div>
  </div>
</div>
"""

POPUP_JS = r"""
const DAILY = __DAILY__;
const MIN5  = __MIN5__;
const NXTSET = new Set(__NXTSET__);  // 세션선(09:00·15:30)은 NXT 종목에만
const TRADES = __TRADES__;  // {code:[{t:'YYYY-MM-DD HH:MM'(봉시작), s:'B'|'S'}]} 매매일지 진입/청산 마커 (기본 {})
const DAILY_TRADES = __DAILY_TRADES__;  // {code:[{t:'YYYY-MM-DD'(일봉시각), b:진입가|null, s:청산가|null}]} 일봉 가격정확 화살표 (기본 {})
const RESULT_SUMMARY = __RESULT_SUMMARY__;  // {code:{익:n,손:n,청:n}} 매매일지 헤더 익/손/청 카운트 (기본 {})
const KOSPI_D = __KOSPI_D__;  // {'YYYY-MM-DD': 종가} KOSPI 종합 일봉 (오버레이용)
const KOSPI5  = __KOSPI5__;   // {'YYYY-MM-DD HH:MM': 값} KOSPI 종합 5분봉 최신 1거래일 09:00~15:30
const TRACK_D = __TRACK_D__;  // {code:['YYYY-MM-DD',...]} 트래킹 등록일 → 일봉 세로 배경 띠 (기본 {}, 미지정 게시판은 영향 0)
const KOSPI_STYLE = {color:'rgba(150,150,150,0.7)',lineWidth:2,
  lineStyle:LightweightCharts.LineStyle.Dotted,priceLineVisible:false,
  lastValueVisible:false,crosshairMarkerVisible:false,
  autoscaleInfoProvider:()=>null};
const MA_D=[[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a'],[120,'#000000']];
const MA_5=[[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a']];
const UP_COLOR='#f23645', DOWN_COLOR='#2962ff';
const VOL_UP='rgba(242,54,69,.72)', VOL_DOWN='rgba(41,98,255,.72)', VOL_SPOT='rgba(0,0,0,1)';
// coloryp 추세배경 (일봉 index[6] / 5분봉 index[7]) — v4 거래량급증과 동일 팔레트
const TREND_BG_COLORS={
  LIME:'rgba(0,230,118,0.15)',GREEN:'rgba(76,175,80,0.15)',
  PURPLE:'rgba(192,132,252,0.14)',RED:'rgba(251,113,133,0.13)',NONE:'rgba(0,0,0,0)'};
const RIGHT_PAD=5, N_GAP=1;
const fmt=n=>Math.round(n).toLocaleString();
const axisFmt=n=>{
  const v=Math.round(n);
  return Math.abs(v)>=1000000 ? Math.round(v/1000).toLocaleString()+'K' : v.toLocaleString();
};
const PRICE_FORMAT={type:'custom',minMove:1,formatter:axisFmt};
KOSPI_STYLE.priceFormat=PRICE_FORMAT;
function sma(c,p){const o=[];let s=0;for(let i=0;i<c.length;i++){s+=c[i];if(i>=p)s-=c[i-p];
  if(i>=p-1)o.push({i,v:+(s/p).toFixed(2)});}return o;}
function rsiWilder(cl,p){const out=new Array(cl.length).fill(null);let g=0,l=0;
  for(let i=1;i<cl.length;i++){const ch=cl[i]-cl[i-1],gg=ch>0?ch:0,ll=ch<0?-ch:0;
    if(i<=p){g+=gg;l+=ll;if(i===p){g/=p;l/=p;out[i]=100-100/(1+(l===0?1e9:g/l));}}
    else{g=(g*(p-1)+gg)/p;l=(l*(p-1)+ll)/p;out[i]=100-100/(1+(l===0?1e9:g/l));}}
  return out;}
function smaArr(arr,p){const out=new Array(arr.length).fill(null);const buf=[];let s=0;
  for(let i=0;i<arr.length;i++){const v=arr[i];if(v==null){buf.length=0;s=0;continue;}
    buf.push(v);s+=v;if(buf.length>p)s-=buf.shift();if(buf.length===p)out[i]=s/p;}return out;}

// ── MagicTrend (TradingView @v4 "SL" 동일 공식) ──
// ATR=sma(tr,AP) 단순이평 / 밴드=low-ATR*coeff(상승) , high+ATR*coeff(하락)
// 방향(색)=cci(close,20) 부호: ≥0 파랑(상승) , <0 빨강(하락)
function cciN(close,length){
  const n=close.length,out=new Array(n).fill(null),ma=smaArr(close,length);
  for(let i=0;i<n;i++){
    if(ma[i]==null)continue;
    let d=0;for(let j=i-length+1;j<=i;j++)d+=Math.abs(close[j]-ma[i]);
    d/=length; out[i]=(d===0)?0:(close[i]-ma[i])/(0.015*d);   // ta.cci = (src-sma)/(0.015*dev)
  }
  return out;
}
function magicTrend(rows,coeff,ap,cciLen){
  const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);
  const tr=new Array(n);
  for(let i=0;i<n;i++)tr[i]=(i===0)?(high[i]-low[i])
    :Math.max(high[i]-low[i],Math.abs(high[i]-close[i-1]),Math.abs(low[i]-close[i-1]));
  const atr=smaArr(tr,ap), cci=cciN(close,cciLen);
  const mt=new Array(n).fill(null), up=new Array(n).fill(null);
  let prev=0;   // nz(MagicTrend[1]) 기본 0
  for(let i=0;i<n;i++){
    const c=cci[i],a=atr[i];
    if(c==null||a==null){mt[i]=null;up[i]=null;prev=0;continue;}  // na → 다음봉 nz=0
    const upT=low[i]-a*coeff, downT=high[i]+a*coeff;
    const v=(c>=0)?((upT<prev)?prev:upT):((downT>prev)?prev:downT);
    mt[i]=v; up[i]=(c>=0); prev=v;
  }
  return {mt,up};   // 단일 선: 봉별 색(up=파랑 #0022FC / 그외 빨강)을 점별 color로 렌더
}

// ── 저/저2 저점신호 (kr_low_signal.py calculate_tv_signals 와 동일 공식, null-aware rolling) ──
const ST_PARAMS=[
  {atr:10,factor:3,up:'rgba(8,153,129,0.5)',dn:'rgba(242,54,69,0.5)',bandUp:'rgba(8,153,129,0.10)', bandDn:'rgba(242,54,69,0.10)', w:1},
  {atr:11,factor:2,up:'rgba(22,163,74,0.5)',dn:'rgba(239,68,68,0.5)',bandUp:'rgba(22,163,74,0.075)',bandDn:'rgba(239,68,68,0.075)',w:1},
  {atr:12,factor:1,up:'rgba(101,163,13,0.5)',dn:'rgba(249,115,22,0.5)',bandUp:'rgba(101,163,13,0.06)',bandDn:'rgba(249,115,22,0.06)',w:1},
];
const SHOW_BANDS=true;
function atrWilder(rows,p){
  const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);
  const tr=new Array(n),atr=new Array(n).fill(null);
  for(let i=0;i<n;i++)tr[i]=(i===0)?(high[i]-low[i])
    :Math.max(high[i]-low[i],Math.abs(high[i]-close[i-1]),Math.abs(low[i]-close[i-1]));
  let s=0;
  for(let i=0;i<n;i++){
    if(i<p){s+=tr[i];if(i===p-1)atr[i]=s/p;}
    else atr[i]=(atr[i-1]*(p-1)+tr[i])/p;
  }
  return atr;
}
function supertrend(rows,factor,atrPeriod){
  const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);
  const atr=atrWilder(rows,atrPeriod);
  const st=new Array(n).fill(null),dir=new Array(n).fill(null);
  let prevUpper=0,prevLower=0,prevST=0;
  for(let i=0;i<n;i++){
    if(atr[i]==null){st[i]=null;dir[i]=null;continue;}
    const hl2=(high[i]+low[i])/2;
    let upper=hl2+factor*atr[i], lower=hl2-factor*atr[i];
    const hasPrev=(i>0&&atr[i-1]!=null);
    if(hasPrev){
      const pc=close[i-1];
      lower=(lower>prevLower||pc<prevLower)?lower:prevLower;
      upper=(upper<prevUpper||pc>prevUpper)?upper:prevUpper;
    }
    let d;
    if(!hasPrev) d=1;
    else if(prevST===prevUpper) d=(close[i]>upper)?-1:1;
    else d=(close[i]<lower)?1:-1;
    const v=(d===-1)?lower:upper;
    st[i]=v; dir[i]=d; prevUpper=upper; prevLower=lower; prevST=v;
  }
  return {st,dir};
}
function activeValue(p){return p&&p.value!=null?Number(p.value):null;}
function buildFillEnvelope(anchor,line,color){
  if(!anchor.length||!line.length)return [];
  const out=[];
  for(let i=0;i<Math.min(anchor.length,line.length);i++){
    const a=activeValue(anchor[i]),v=activeValue(line[i]);
    if(a==null||v==null||!Number.isFinite(a)||!Number.isFinite(v)){out.push({time:anchor[i].time});continue;}
    out.push({time:anchor[i].time,upper:Math.max(a,v),lower:Math.min(a,v),color});
  }
  return out;
}
function installBandOverlay(el,ch,priceSeries,bands){
  if(!SHOW_BANDS||!bands.length)return;
  el.style.position='relative';
  const canvas=document.createElement('canvas');
  canvas.className='st-band-overlay';
  canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;';
  el.appendChild(canvas);
  let raf=0;
  function queueDraw(){if(raf)return;raf=requestAnimationFrame(()=>{raf=0;draw();});}
  function draw(){
    const dpr=window.devicePixelRatio||1,w=el.clientWidth,h=el.clientHeight;
    if(!w||!h)return;
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){
      canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
      canvas.style.width=w+'px';canvas.style.height=h+'px';
    }
    const ctx=canvas.getContext('2d');
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,w,h);
    bands.forEach(band=>{
      let upper=[],lower=[];
      function flush(){
        if(upper.length<2||lower.length<2){upper=[];lower=[];return;}
        ctx.beginPath();
        ctx.moveTo(upper[0][0],upper[0][1]);
        for(let i=1;i<upper.length;i++)ctx.lineTo(upper[i][0],upper[i][1]);
        for(let i=lower.length-1;i>=0;i--)ctx.lineTo(lower[i][0],lower[i][1]);
        ctx.closePath();
        ctx.fillStyle=band.color;
        ctx.fill();
        upper=[];lower=[];
      }
      band.points.forEach(p=>{
        if(p.upper==null||p.lower==null){flush();return;}
        const x=ch.timeScale().timeToCoordinate(p.time);
        const y1=priceSeries.priceToCoordinate(p.upper);
        const y2=priceSeries.priceToCoordinate(p.lower);
        if(x==null||y1==null||y2==null){flush();return;}
        upper.push([x,y1]);lower.push([x,y2]);
      });
      flush();
    });
  }
  queueDraw();
  ch.timeScale().subscribeVisibleLogicalRangeChange(queueDraw);
}
function addSupertrendOverlay(ch,el,candle,bodyMid,stLines){
  installBandOverlay(el,ch,candle,ST_PARAMS.flatMap((sp,si)=>[
    {color:sp.bandUp,points:buildFillEnvelope(bodyMid,stLines[si].up,sp.bandUp)},
    {color:sp.bandDn,points:buildFillEnvelope(bodyMid,stLines[si].dn,sp.bandDn)}
  ]));
  ST_PARAMS.forEach((sp,si)=>{
    const ln=ch.addLineSeries({color:sp.up,lineWidth:sp.w,priceLineVisible:false,
      priceFormat:PRICE_FORMAT,autoscaleInfoProvider:()=>null,
      lastValueVisible:false,crosshairMarkerVisible:false});
    ln.setData(stLines[si].line);
  });
}

function rollMeanN(arr,n){const out=new Array(arr.length).fill(null);
  for(let i=n-1;i<arr.length;i++){let s=0,ok=true;
    for(let j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}s+=arr[j];}
    out[i]=ok?s/n:null;}return out;}
function rollMaxN(arr,n){const out=new Array(arr.length).fill(null);
  for(let i=n-1;i<arr.length;i++){let m=-Infinity,ok=true;
    for(let j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]>m)m=arr[j];}
    out[i]=ok?m:null;}return out;}
function rollMinN(arr,n){const out=new Array(arr.length).fill(null);
  for(let i=n-1;i<arr.length;i++){let m=Infinity,ok=true;
    for(let j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]<m)m=arr[j];}
    out[i]=ok?m:null;}return out;}
function stochN(close,high,low,n){const out=new Array(close.length).fill(null);
  for(let i=n-1;i<close.length;i++){let lo=Infinity,hi=-Infinity;
    for(let j=i-n+1;j<=i;j++){if(low[j]<lo)lo=low[j];if(high[j]>hi)hi=high[j];}
    out[i]=(hi===lo)?null:(close[i]-lo)/(hi-lo)*100;}return out;}
function computeLowSignals(rows){
  const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);
  // 저: k3=sma10(stoch20), k2=sma5(stoch10) ; k3가 20 상향돌파 & k2 상승
  const k3=rollMeanN(stochN(close,high,low,20),10);
  const k2=rollMeanN(stochN(close,high,low,10),5);
  // 저2: 극심과매도(SMIsignal<=-60 & emasignal<=-60 & RSI<=30) → 탈출
  const hh=rollMaxN(high,10),ll=rollMinN(low,10);
  const diff=new Array(n).fill(null),rdiff=new Array(n).fill(null);
  for(let i=0;i<n;i++){if(hh[i]!=null&&ll[i]!=null){diff[i]=hh[i]-ll[i];rdiff[i]=close[i]-(hh[i]+ll[i])/2;}}
  const avgrel=rollMeanN(rollMeanN(rdiff,3),3);
  const avgdiff=rollMeanN(rollMeanN(diff,3),3);
  const smi=new Array(n).fill(0);
  for(let i=0;i<n;i++){if(avgrel[i]!=null&&avgdiff[i]!=null&&avgdiff[i]!==0)smi[i]=avgrel[i]/(avgdiff[i]/2)*100;}
  const smisig=rollMeanN(smi,3),emasig=rollMeanN(smi,10),rsi1=rsiWilder(close,14);
  const constat=new Array(n).fill(false);
  for(let i=0;i<n;i++){constat[i]=(smisig[i]!=null&&smisig[i]<=-60)&&(emasig[i]!=null&&emasig[i]<=-60)&&(rsi1[i]!=null&&rsi1[i]<=30);}
  const jeo=[],jeo2=[];
  for(let i=1;i<n;i++){
    if(k3[i]!=null&&k3[i-1]!=null&&k2[i]!=null&&k2[i-1]!=null&&k3[i]>=20&&k3[i-1]<20&&k2[i]>=k2[i-1])jeo.push(rows[i][0]);
    if(constat[i-1]&&!constat[i])jeo2.push(rows[i][0]);
  }
  return {jeo,jeo2};
}

// ── X 고점신호 (TV HLv2 동일공식: M0/M2/M3 이격률 percentrank(220) 3개 모두 95↑ 직후 trank 2봉 연속 비상승) ──
function percentRankN(arr,len){const out=new Array(arr.length).fill(null);
  for(let i=len;i<arr.length;i++){if(arr[i]==null)continue;let cnt=0,ok=true;
    for(let j=i-len;j<i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]<=arr[i])cnt++;}
    out[i]=ok?100*cnt/len:null;}return out;}
function computeTopSignals(rows){
  const n=rows.length,close=rows.map(b=>b[4]);
  const m0=rollMeanN(close,5),m2=rollMeanN(close,20),m3=rollMeanN(close,60);
  const xr=m=>close.map((c,i)=>m[i]==null?null:100*(c-m[i])/c);
  const fr=percentRankN(xr(m3),220),sr=percentRankN(xr(m2),220),tr=percentRankN(xr(m0),220);
  const hld=new Array(n).fill(false);
  for(let i=0;i<n;i++)hld[i]=fr[i]!=null&&sr[i]!=null&&tr[i]!=null&&fr[i]>=95&&sr[i]>=95&&tr[i]>=95;
  const out=[];
  for(let i=2;i<n;i++){
    if(hld[i-1]&&tr[i]!=null&&tr[i-1]!=null&&tr[i-2]!=null&&tr[i]<=tr[i-1]&&tr[i-1]<=tr[i-2])out.push(rows[i][0]);
  }
  return out;
}

const pop=document.getElementById('naverChartPopup');
const popTitle=document.getElementById('popupTitle');
const popLink=document.getElementById('popupLink');
const popMs=document.getElementById('popMs');
const stBtn=document.getElementById('stBtn');
let charts=[], extras=[], openTimer=null, closeTimer=null, pinned=false, curCode=null, curTd=null;
let stMode=false;
// 모바일 지연생성용: 현재 종목 데이터 + 각 칼럼 생성여부 (숨겨진 칼럼에서 차트를 만들면 0×0 → 빈화면이 되는 문제 방지)
let curR5=[], curRD=[], built5=false, builtD=false;

function clearBoxes(){
  ['chart5','chartD'].forEach(id=>{
    const box=document.getElementById(id).parentElement;
    box.querySelectorAll('.divider,.exlab,.tradearrow').forEach(d=>d.remove());
  });
  document.getElementById('lg5').style.display='none';
  document.getElementById('lgD').style.display='none';
}
function destroyChart(){charts.forEach(c=>{try{c.remove();}catch(e){}});charts=[];
  document.querySelectorAll('#popBox .st-band-overlay').forEach(n=>n.remove());
  extras=[];built5=false;builtD=false;clearBoxes();}

function paintLegend(lg,b,labelIdx){
  const cu=b[4]>=b[1]?UP_COLOR:DOWN_COLOR;
  lg.innerHTML=
    '<div><span class="k">날짜</span><b>'+b[labelIdx]+'</b></div>'+
    '<div><span class="k">종가</span><b style="color:'+cu+'">'+fmt(b[4])+'</b></div>'+
    '<div><span class="k">거래량</span><b>'+b[5].toLocaleString()+'</b></div>'+
    '<div><span class="k">시가</span>'+fmt(b[1])+'</div>'+
    '<div><span class="k">고가</span><span style="color:'+UP_COLOR+'">'+fmt(b[2])+'</span></div>'+
    '<div><span class="k">저가</span><span style="color:'+DOWN_COLOR+'">'+fmt(b[3])+'</span></div>';
}
function attachTooltip(ch,el,lg,byKey,labelIdx){
  ch.subscribeCrosshairMove(param=>{
    if(!param.time||!param.point||!byKey.has(param.time)){lg.style.display='none';return;}
    paintLegend(lg,byKey.get(param.time),labelIdx);lg.style.display='block';
    const bw=lg.offsetWidth,bh=lg.offsetHeight;
    let lx=param.point.x-bw-14;if(lx<4)lx=param.point.x+14;
    let ly=param.point.y-bh/2;ly=Math.max(2,Math.min(ly,el.clientHeight-bh-2));
    lg.style.left=lx+'px';lg.style.top=ly+'px';
  });
}
function newCandle(el,intraday){
  return LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.08,bottom:0.08}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:intraday?1.2:0.4,visible:false},
    localization:{priceFormatter:axisFmt},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});
}
function newRsi(el,intraday){
  return LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#888',fontSize:10},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f7f7f7'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.12,bottom:0.12}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:intraday?1.2:0.4,
      timeVisible:!!intraday,secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});
}
function addRsi(rel,intraday,rdata,rmdata){
  const rch=newRsi(rel,intraday);
  // 과매수 영역(>70): RSI선과 70 사이 lime — baseline series 활용 (데이터 재사용, 추가비용 거의 0)
  const bUp=rch.addBaselineSeries({baseValue:{type:'price',price:70},
    topLineColor:'rgba(0,0,0,0)',
    topFillColor1:'rgba(50,205,50,0.62)',topFillColor2:'rgba(50,205,50,0.30)',
    bottomLineColor:'rgba(0,0,0,0)',
    bottomFillColor1:'rgba(0,0,0,0)',bottomFillColor2:'rgba(0,0,0,0)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  bUp.setData(rdata);
  // 과매도 영역(<30): RSI선과 30 사이 red
  const bDn=rch.addBaselineSeries({baseValue:{type:'price',price:30},
    topLineColor:'rgba(0,0,0,0)',
    topFillColor1:'rgba(0,0,0,0)',topFillColor2:'rgba(0,0,0,0)',
    bottomLineColor:'rgba(0,0,0,0)',
    bottomFillColor1:'rgba(239,68,68,0.30)',bottomFillColor2:'rgba(239,68,68,0.62)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  bDn.setData(rdata);
  const rl=rch.addLineSeries({color:DOWN_COLOR,lineWidth:1,priceLineVisible:false,
    lastValueVisible:true,crosshairMarkerVisible:false});
  rl.setData(rdata);
  const rm=rch.addLineSeries({color:UP_COLOR,lineWidth:1,priceLineVisible:false,
    lastValueVisible:false,crosshairMarkerVisible:false});
  rm.setData(rmdata);
  [70,30].forEach(lv=>rl.createPriceLine({price:lv,color:'#9ca3af',lineWidth:1,
    lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true}));
  return {rch,rl};
}
function syncPair(a,b){let lock=false;
  const s=(src,dst)=>src.timeScale().subscribeVisibleLogicalRangeChange(r=>{
    if(lock||!r)return;lock=true;dst.timeScale().setVisibleLogicalRange(r);lock=false;});
  s(a,b);s(b,a);}
// 캔들↔RSI 우측 가격축 폭 동기화 → 두 차트 플롯영역 폭을 같게 맞춰 세로 시간축 정렬.
// (가격은 여러자리·RSI는 2자리라 축폭이 달라 세로선이 어긋나던 문제: 좁은 축을 넓은 축에 맞춤)
function syncScaleWidth(a,b){
  const apply=()=>{try{
    const w=Math.max(a.priceScale('right').width(),b.priceScale('right').width());
    a.priceScale('right').applyOptions({minimumWidth:w});
    b.priceScale('right').applyOptions({minimumWidth:w});
  }catch(e){}};
  requestAnimationFrame(apply);
  a.timeScale().subscribeVisibleLogicalRangeChange(apply);
}
// 캔들↔RSI 크로스헤어(세로선) 동기화 — 한쪽에 마우스를 올리면 다른쪽도 같은 시각에 세로선 표시.
// dstMap[time]=대상 시리즈 값(가로선 위치용). lock으로 재진입(무한루프) 방지.
function syncCrosshair(a,aS,aMap,b,bS,bMap){
  let lock=false;
  const link=(src,dst,dstS,dstMap)=>src.subscribeCrosshairMove(p=>{
    if(lock)return;lock=true;
    if(p.time==null||p.point==null)dst.clearCrosshairPosition();
    else{const v=dstMap.get(p.time);
      if(v==null)dst.clearCrosshairPosition();else dst.setCrosshairPosition(v,p.time,dstS);}
    lock=false;});
  link(a,b,bS,bMap);link(b,a,aS,aMap);
}
function addCandleVol(ch){
  const cs=ch.addCandlestickSeries({upColor:UP_COLOR,downColor:DOWN_COLOR,borderUpColor:UP_COLOR,
    borderDownColor:DOWN_COLOR,wickUpColor:UP_COLOR,wickDownColor:DOWN_COLOR,
    priceFormat:PRICE_FORMAT});
  // 거래량 라벨은 #,###K (÷1000) — 몇천만주여도 우측 숫자공간이 커지지 않게
  const vol=ch.addHistogramSeries({priceScaleId:'',
    priceFormat:{type:'custom',minMove:1,formatter:v=>Math.round(v/1000).toLocaleString()+'K'}});
  vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
  return [cs,vol];
}

// KOSPI 점선 끝점 강조: 선의 마지막 점에 회색50% 사각 마커 부착.
// 시리즈 마커라 선과 함께 자동 추적 → 좌표 계산/오토스케일 타이밍 이슈 없음.
function kospiEndMark(series,last){
  series.setMarkers([{time:last.time,position:'inBar',
    color:'rgba(150,150,150,0.7)',shape:'square',size:2}]);
}
function buildIntraday(rows,code){
  const el=document.getElementById('chart5'), lg=document.getElementById('lg5');
  const rel=document.getElementById('rsi5');
  const isNxt=NXTSET.has(code);
  const ch=newCandle(el,true);
  // coloryp 추세배경 — 캔들보다 먼저 추가 → z-order상 가장 뒤 (state는 index[7])
  const trendBand=ch.addHistogramSeries({priceScaleId:'trendbg',base:0,
    priceLineVisible:false,lastValueVisible:false});
  ch.priceScale('trendbg').applyOptions({scaleMargins:{top:0,bottom:0}});
  // KOSPI 점선은 캔들보다 먼저 추가 → z-order상 뒤(종목 캔들이 앞)
  const kospiLine=ch.addLineSeries(KOSPI_STYLE);
  const [cs,vol]=addCandleVol(ch);
  const closes=rows.map(b=>b[4]);
  const vols5=rows.map(b=>b[5]), vsma5v=smaArr(vols5,5);
  const maMaps=MA_5.map(([p])=>new Map(sma(closes,p).map(o=>[rows[o.i][0],o.v])));
  const rsiArr=rsiWilder(closes,14), rsiMa=smaArr(rsiArr,14);
  const stc=magicTrend(rows,3,10,20);   // MagicTrend: 계수3, ATR10, CCI20
  const sts=ST_PARAMS.map(sp=>supertrend(rows,sp.factor,sp.atr));
  const cd=[],vd=[],md=MA_5.map(()=>[]),rd=[],rmd=[],mtd=[],bounds=[],sessPairs=[]; let prev=null;
  const bodyMid=[],stLines=ST_PARAMS.map(()=>({line:[],up:[],dn:[]}));
  for(let i=0;i<rows.length;i++){
    const b=rows[i],day=b[6].slice(0,10);
    if(prev!==null&&day!==prev){const base=rows[i-1][0];
      for(let k=1;k<=N_GAP;k++){const gt=base+k*300;cd.push({time:gt});vd.push({time:gt});
        md.forEach(a=>a.push({time:gt}));rd.push({time:gt});rmd.push({time:gt});
        mtd.push({time:gt});bodyMid.push({time:gt});
        stLines.forEach(s=>{s.line.push({time:gt});s.up.push({time:gt});s.dn.push({time:gt});});}
      bounds.push(base+Math.ceil(N_GAP/2)*300);}
    else if(i>0&&isNxt){const hm=b[6].slice(11,16),phm=rows[i-1][6].slice(11,16);
      // 정규장 시작(09:00)·끝(15:30) 세션선 — NXT 종목에만 (캔들 사이 빈틈에 표시)
      if(phm<'09:00'&&hm>='09:00')  sessPairs.push([rows[i-1][0],b[0]]);
      if(phm<='15:30'&&hm>'15:30')  sessPairs.push([rows[i-1][0],b[0]]);}
    cd.push({time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]});
    vd.push({time:b[0],value:b[5],color:((i>0&&vols5[i]>=vols5[i-1]*10)||(vsma5v[i]!=null&&vols5[i]>=vsma5v[i]*2.5))?VOL_SPOT:(i===0||b[4]>=rows[i-1][4]?VOL_UP:VOL_DOWN)});
    md.forEach((a,mi)=>{const m=maMaps[mi];a.push(m.has(b[0])?{time:b[0],value:m.get(b[0])}:{time:b[0]});});
    rd.push(rsiArr[i]==null?{time:b[0]}:{time:b[0],value:+rsiArr[i].toFixed(2)});
    rmd.push(rsiMa[i]==null?{time:b[0]}:{time:b[0],value:+rsiMa[i].toFixed(2)});
    // MagicTrend: 선 1개 + 봉별 색(cci≥0 파랑 / <0 빨강) — TV plot() 동일. 비정의/일자경계는 빈칸
    mtd.push(stc.mt[i]==null?{time:b[0]}
      :{time:b[0],value:+stc.mt[i].toFixed(2),color:stc.up[i]?'rgba(0,34,252,0.3)':'rgba(255,82,82,0.3)'});
    bodyMid.push({time:b[0],value:+(((b[1]+b[4])/2).toFixed(2))});
    ST_PARAMS.forEach((sp,si)=>{
      const sv=sts[si].st[i],dir=sts[si].dir[i],slot=stLines[si];
      if(sv==null||dir==null){slot.line.push({time:b[0]});slot.up.push({time:b[0]});slot.dn.push({time:b[0]});return;}
      const v=+sv.toFixed(2);
      slot.line.push({time:b[0],value:v,color:dir<0?sp.up:sp.dn});
      slot.up.push(dir<0?{time:b[0],value:v}:{time:b[0]});
      slot.dn.push(dir>0?{time:b[0],value:v}:{time:b[0]});
    });
    prev=day;}
  cs.setData(cd);vol.setData(vd);
  trendBand.setData(rows.filter(b=>b[7]&&TREND_BG_COLORS[b[7]]).map(b=>({time:b[0],value:1,color:TREND_BG_COLORS[b[7]]})));
  if(!stMode){
  MA_5.forEach(([p,color],mi)=>{const ln=ch.addLineSeries({color,lineWidth:1,priceLineVisible:false,
    priceFormat:PRICE_FORMAT,autoscaleInfoProvider:()=>null,
    lastValueVisible:false,crosshairMarkerVisible:false});ln.setData(md[mi]);});
  // MagicTrend(10,3) 오버레이 — 선 1개, 봉별 색만 분기(점별 color). CCI(20)≥0:파랑 / <0:빨강 (TV @v4 "SL" 동일)
  // 이평선(실선)과 구분되게 잔잔한 점선(Dashed)으로 표시
  const mtLine=ch.addLineSeries({color:'rgba(0,34,252,0.3)',lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,
    priceFormat:PRICE_FORMAT,autoscaleInfoProvider:()=>null,
    lastValueVisible:false,crosshairMarkerVisible:false});mtLine.setData(mtd);
  }else{
    addSupertrendOverlay(ch,el,cs,bodyMid,stLines);
  }
  // 저(빨간네모 도형만) / 저2(글자 '저2'만) / X(글자 'X'만) — size:0 → 도형폭 0, 텍스트만 렌더
  const sig=computeLowSignals(rows), marks=[];
  sig.jeo.forEach(t=>marks.push({time:t,position:'belowBar',color:'#e11d1d',shape:'square',text:''}));
  sig.jeo2.forEach(t=>marks.push({time:t,position:'belowBar',color:'#000000',shape:'square',text:'저2',size:0}));
  computeTopSignals(rows).forEach(t=>marks.push({time:t,position:'aboveBar',color:'#000000',shape:'square',text:'X',size:0}));
  // 매매일지 B(진입)/S(청산) — 둘 다 검정화살표로 통일
  //  B(진입): 캔들 아래 검정 위화살표  /  S(청산): 캔들 위 검정 아래화살표
  const lbl2t=new Map(rows.map(b=>[b[6],b[0]]));
  (TRADES[code]||[]).forEach(m=>{
    let t=lbl2t.get(m.t);
    if(t==null){const r=rows.find(b=>b[6].slice(0,10)===m.t.slice(0,10)&&b[6]>=m.t);if(r)t=r[0];}
    if(t==null)return;
    if(m.s==='B') marks.push({time:t,position:'belowBar',color:'#000000',shape:'arrowUp',text:''});
    else          marks.push({time:t,position:'aboveBar',color:'#000000',shape:'arrowDown',text:''});
  });
  marks.sort((a,b)=>a.time-b.time);
  if(marks.length)cs.setMarkers(marks);
  // ── KOSPI 종합 점선 오버레이 (당일 09:00 기준 rebase, 09:00~15:30만) ──
  (function(){
    if(!rows.length)return;
    const lastDay=rows[rows.length-1][6].slice(0,10);
    let aIdx=-1;
    for(let i=0;i<rows.length;i++){
      if(rows[i][6].slice(0,10)!==lastDay)continue;
      const hm=rows[i][6].slice(11,16);
      if(hm>='09:00'&&hm<='15:30'&&KOSPI5[rows[i][6]]!=null){aIdx=i;break;}
    }
    if(aIdx<0)return;
    const K0=KOSPI5[rows[aIdx][6]], P0=rows[aIdx][4];
    if(K0==null||!K0)return;
    const data=[];
    for(let i=aIdx;i<rows.length;i++){
      if(rows[i][6].slice(0,10)!==lastDay)break;
      const hm=rows[i][6].slice(11,16);
      if(hm<'09:00'||hm>'15:30')continue;
      const K=KOSPI5[rows[i][6]];
      if(K==null)continue;
      data.push({time:rows[i][0],value:P0*K/K0});
    }
    if(data.length<2)return;
    kospiLine.setData(data);
    kospiEndMark(kospiLine,data[data.length-1]);
  })();
  const {rch,rl}=addRsi(rel,true,rd,rmd);
  // 디폴트 표시 구간: 현재일 전체 + 직전일 마지막 ~2시간(PREV5_BUF봉)만.
  // (2일치 데이터는 그대로 로드 → 휠/드래그로 더 보기 가능). 우측 여백 RIGHT_PAD 유지.
  const PREV5_BUF=24;
  const lastDay=rows[rows.length-1][6].slice(0,10);
  let curDayBars=0;
  for(let i=rows.length-1;i>=0&&rows[i][6].slice(0,10)===lastDay;i--)curDayBars++;
  const tot=cd.length, from=Math.max(0,tot-(curDayBars+N_GAP+PREV5_BUF)), to=tot-1+RIGHT_PAD;
  ch.timeScale().setVisibleLogicalRange({from,to});
  rch.timeScale().setVisibleLogicalRange({from,to});
  syncPair(ch,rch);
  syncScaleWidth(ch,rch);
  const box=el.parentElement;
  const divs=bounds.map(()=>{const d=document.createElement('div');d.className='divider';box.appendChild(d);return d;});
  const sdivs=sessPairs.map(()=>{const d=document.createElement('div');d.className='divider sessline';box.appendChild(d);return d;});
  function placeDivs(){const tsc=ch.timeScale();
    bounds.forEach((bt,i)=>{const x=tsc.timeToCoordinate(bt);
      if(x==null)divs[i].style.display='none';else{divs[i].style.display='block';divs[i].style.left=x+'px';}});
    sessPairs.forEach((pr,i)=>{const xa=tsc.timeToCoordinate(pr[0]),xb=tsc.timeToCoordinate(pr[1]);
      if(xa==null||xb==null)sdivs[i].style.display='none';
      else{sdivs[i].style.display='block';sdivs[i].style.left=((xa+xb)/2)+'px';}});}
  placeDivs();ch.timeScale().subscribeVisibleLogicalRangeChange(placeDivs);
  syncCrosshair(ch,cs,new Map(rows.map(b=>[b[0],b[4]])),
                rch,rl,new Map(rd.filter(d=>d.value!=null).map(d=>[d.time,d.value])));
  attachTooltip(ch,el,lg,new Map(rows.map(b=>[b[0],b])),6);
  charts.push(ch,rch);
}
function buildDaily(rows){
  const el=document.getElementById('chartD'), lg=document.getElementById('lgD');
  const rel=document.getElementById('rsiD');
  const ch=newCandle(el,false);
  // coloryp 추세배경 — 가장 먼저 추가 → z-order상 최하단 (state는 index[6])
  const trendBand=ch.addHistogramSeries({priceScaleId:'trendbg',base:0,
    priceLineVisible:false,lastValueVisible:false});
  ch.priceScale('trendbg').applyOptions({scaleMargins:{top:0,bottom:0}});
  // 트래킹 등록일 세로 배경 띠 — 캔들보다 먼저 추가 → z-order상 가장 뒤 (캔들이 위)
  const trkBand=ch.addHistogramSeries({priceScaleId:'trkband',base:0,
    priceLineVisible:false,lastValueVisible:false,color:'rgba(50,205,50,0.30)'});
  ch.priceScale('trkband').applyOptions({scaleMargins:{top:0,bottom:0}});
  // KOSPI 점선은 캔들보다 먼저 추가 → z-order상 뒤(종목 캔들이 앞)
  const kospiLine=ch.addLineSeries(KOSPI_STYLE);
  const [cs,vol]=addCandleVol(ch);
  cs.setData(rows.map(b=>({time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]})));
  (function(){const td=TRACK_D[curCode];if(!td||!td.length)return;
    const st=new Set(td);
    const bd=rows.filter(b=>st.has(b[0])).map(b=>({time:b[0],value:1,color:'rgba(50,205,50,0.30)'}));
    if(bd.length)trkBand.setData(bd);})();
  const volsD=rows.map(b=>b[5]), vsma5D=smaArr(volsD,5);
  vol.setData(rows.map((b,i)=>({time:b[0],value:b[5],color:((i>0&&volsD[i]>=volsD[i-1]*10)||(vsma5D[i]!=null&&volsD[i]>=vsma5D[i]*2.5))?VOL_SPOT:(i===0||b[4]>=rows[i-1][4]?VOL_UP:VOL_DOWN)})));
  trendBand.setData(rows.filter(b=>b[6]&&TREND_BG_COLORS[b[6]]).map(b=>({time:b[0],value:1,color:TREND_BG_COLORS[b[6]]})));
  const times=rows.map(b=>b[0]),closes=rows.map(b=>b[4]);
  const bodyMid=rows.map(b=>({time:b[0],value:+(((b[1]+b[4])/2).toFixed(2))}));
  const stLines=ST_PARAMS.map(sp=>{
    const r=supertrend(rows,sp.factor,sp.atr);
    return {
      line:times.map((t,i)=>r.st[i]==null?{time:t}:{time:t,value:+r.st[i].toFixed(2),color:r.dir[i]<0?sp.up:sp.dn}),
      up:times.map((t,i)=>(r.st[i]!=null&&r.dir[i]<0)?{time:t,value:+r.st[i].toFixed(2)}:{time:t}),
      dn:times.map((t,i)=>(r.st[i]!=null&&r.dir[i]>0)?{time:t,value:+r.st[i].toFixed(2)}:{time:t})
    };
  });
  if(!stMode){
  MA_D.forEach(([p,color])=>{const ln=ch.addLineSeries({color,lineWidth:1,priceLineVisible:false,
    priceFormat:PRICE_FORMAT,autoscaleInfoProvider:()=>null,
    lastValueVisible:false,crosshairMarkerVisible:false});
    const mp=new Map(sma(closes,p).map(o=>[times[o.i],o.v]));
    ln.setData(times.map(t=>mp.has(t)?{time:t,value:mp.get(t)}:{time:t}));});
  // MagicTrend(10,3) 점선 오버레이 — 5분봉과 동일 (일봉엔 일자갭 없음). 점별 색 파/적
  const mtcD=magicTrend(rows,3,10,20);
  const mtdD=times.map((t,i)=>mtcD.mt[i]==null?{time:t}
    :{time:t,value:+mtcD.mt[i].toFixed(2),color:mtcD.up[i]?'rgba(0,34,252,0.3)':'rgba(255,82,82,0.3)'});
  const mtLineD=ch.addLineSeries({color:'rgba(0,34,252,0.3)',lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,
    priceFormat:PRICE_FORMAT,autoscaleInfoProvider:()=>null,
    lastValueVisible:false,crosshairMarkerVisible:false});mtLineD.setData(mtdD);
  }else{
    addSupertrendOverlay(ch,el,cs,bodyMid,stLines);
  }
  // ── KOSPI 종합 점선 오버레이 (20봉 전 기준 rebase → 거기서 현재까지) ──
  (function(){
    const n=rows.length;if(n<2)return;
    let aIdx=Math.max(0,n-1-20);   // 20봉 전이 비교 시작점
    while(aIdx<n&&KOSPI_D[rows[aIdx][0]]==null)aIdx++;
    if(aIdx>=n)return;
    const K0=KOSPI_D[rows[aIdx][0]], P0=rows[aIdx][4];
    if(K0==null||!K0)return;
    const data=[];
    for(let i=aIdx;i<n;i++){
      const K=KOSPI_D[rows[i][0]];
      if(K==null)continue;
      data.push({time:rows[i][0],value:P0*K/K0});
    }
    if(data.length<2)return;
    kospiLine.setData(data);
    kospiEndMark(kospiLine,data[data.length-1]);
  })();
  const rsiArr=rsiWilder(closes,14), rsiMa=smaArr(rsiArr,14);
  const rd =times.map((t,i)=>rsiArr[i]==null?{time:t}:{time:t,value:+rsiArr[i].toFixed(2)});
  const rmd=times.map((t,i)=>rsiMa[i] ==null?{time:t}:{time:t,value:+rsiMa[i].toFixed(2)});
  const {rch,rl}=addRsi(rel,false,rd,rmd);
  const n=rows.length, from=Math.max(0,n-84), to=n-1+RIGHT_PAD;
  ch.timeScale().setVisibleLogicalRange({from,to});
  rch.timeScale().setVisibleLogicalRange({from,to});
  syncPair(ch,rch);
  syncScaleWidth(ch,rch);
  syncCrosshair(ch,cs,new Map(rows.map(b=>[b[0],b[4]])),
                rch,rl,new Map(rd.filter(d=>d.value!=null).map(d=>[d.time,d.value])));
  attachTooltip(ch,el,lg,new Map(rows.map(b=>[b[0],b])),0);
  // ── 매매일지 일봉 진입(↑)/청산(↓) 화살표 — 끝점이 체결가에 정확히 닿는 div 오버레이 ──
  //  진입=검정 위화살표(끝점 위), 청산=검정 아래화살표(끝점 아래). 당일진입·청산이 겹치면 좌우로 분리(첨부3).
  (function(){
    const dts=DAILY_TRADES[curCode]||[];
    if(!dts.length)return;
    const box=el.parentElement, items=[];
    dts.forEach(d=>{
      if(d.b!=null){const a=document.createElement('div');a.className='tradearrow up';box.appendChild(a);
        items.push({el:a,t:d.t,price:d.b,side:'B'});}
      if(d.s!=null){const a=document.createElement('div');a.className='tradearrow dn';box.appendChild(a);
        items.push({el:a,t:d.t,price:d.s,side:'S'});}
    });
    function place(){
      const tsc=ch.timeScale();
      items.forEach(o=>{o.x=tsc.timeToCoordinate(o.t);o.y=cs.priceToCoordinate(o.price);});
      const byT={};items.forEach(o=>{(byT[o.t]=byT[o.t]||[]).push(o);});
      items.forEach(o=>{
        if(o.x==null||o.y==null){o.el.style.display='none';return;}
        let dx=0;const g=byT[o.t];
        if(g.length>1){const b=g.find(z=>z.side==='B'),s=g.find(z=>z.side==='S');
          if(b&&s&&b.y!=null&&s.y!=null&&Math.abs(b.y-s.y)<16)dx=(o.side==='B'?-7:7);}
        o.el.style.display='block';o.el.style.left=(o.x+dx)+'px';o.el.style.top=o.y+'px';
      });
    }
    place();ch.timeScale().subscribeVisibleLogicalRangeChange(place);extras.push(place);
    setTimeout(place,0);
  })();
  charts.push(ch,rch);
}

function popBoxEmpty(show){
  document.getElementById('col5').style.visibility=show?'hidden':'visible';
  document.getElementById('colD').style.visibility=show?'hidden':'visible';
  let e=document.querySelector('#popBox .empty');
  if(show){if(!e){e=document.createElement('div');e.className='empty';e.textContent='데이터 없음';document.getElementById('popBox').appendChild(e);}}
  else if(e)e.remove();
}
// 각 칼럼 차트는 "보이는 상태"에서만 생성 (숨김 상태 생성 시 0×0 빈화면). → 지연생성.
function ensureBuilt5(){if(!built5&&curR5.length){buildIntraday(curR5,curCode);built5=true;}}
function ensureBuiltD(){if(!builtD&&curRD.length){buildDaily(curRD);builtD=true;}}
// 매매일지: 헤더의 MagicTrend(10,3) 라벨 자리를 익/손/청 카운트로 교체. (RESULT_SUMMARY 미지정 게시판은 원복)
let MT5_DEF=null, MTD_DEF=null;
function updateCollab(code){
  const e5=document.getElementById('mt5'), eD=document.getElementById('mtD');
  if(!e5||!eD)return;
  if(MT5_DEF===null){MT5_DEF=e5.innerHTML;MTD_DEF=eD.innerHTML;}
  const s=RESULT_SUMMARY[code];
  if(!s){e5.innerHTML=MT5_DEF;eD.innerHTML=MTD_DEF;return;}
  const parts=[];
  if(s['익'])parts.push('<span style="color:#2e7d32;font-weight:700">익'+s['익']+'</span>');
  if(s['손'])parts.push('<span style="color:#ff5252;font-weight:700">손'+s['손']+'</span>');
  if(s['청'])parts.push('<span style="color:#9e9e9e;font-weight:700">청'+s['청']+'</span>');
  const html=parts.length?parts.join(' '):'<span style="color:#9e9e9e">기록</span>';
  e5.innerHTML=html;eD.innerHTML=html;
}
function showChart(code,name){
  curCode=code;
  updateCollab(code);
  popTitle.textContent=code+'  '+(name||'');
  popLink.href='https://finance.naver.com/item/main.naver?code='+code;
  destroyChart();
  curR5=MIN5[code]||[]; curRD=DAILY[code]||[];
  if(!curR5.length&&!curRD.length){popBoxEmpty(true);popMs.textContent='';return;}
  popBoxEmpty(false);
  const t0=performance.now();
  applyMobileTab();   // 보이는 칼럼만 생성 (PC는 둘 다)
  const ms=performance.now()-t0;
  popMs.textContent='render '+(Math.round(ms*10)/10)+' ms · 5분 '+curR5.length+' / 일 '+curRD.length;
}
// 모바일(≤767px)에서만 동작: 5분봉/일봉 둘 중 하나만 표시. 선택은 세션 내 기억.
function applyMobileTab(which){
  const c5=document.getElementById('col5'), cd=document.getElementById('colD');
  if(!c5||!cd) return;
  if(window.innerWidth>767){
    c5.classList.remove('hidden');cd.classList.remove('hidden');
    ensureBuilt5();ensureBuiltD();
    return;
  }
  const tab=which||pop.dataset.tab||'5';
  if(tab==='5'){c5.classList.remove('hidden');cd.classList.add('hidden');ensureBuilt5();}
  else{c5.classList.add('hidden');cd.classList.remove('hidden');ensureBuiltD();}
  pop.dataset.tab=tab;
  document.querySelectorAll('.popTab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  // 라벨 위치 재계산
  setTimeout(()=>{extras.forEach(fn=>{try{fn();}catch(e){}});},0);
}

function placePop(x,y){if(window.innerWidth<=767)return;
  const w=Math.min(1020,window.innerWidth-20),h=560;let px=x+18,py=y+18;
  if(px+w>window.innerWidth-8)px=x-w-12;if(py+h>window.innerHeight-8)py=y-h-12;
  pop.style.left=Math.max(8,px)+'px';pop.style.top=Math.max(8,py)+'px';pop.style.transform='none';}
function openPop(){pop.style.display='block';document.body.classList.add('naver-popup-open');
  // iframe 안에서 열릴 때 키보드 포커스를 잡아야 a/s/d 단축키가 첫 호버부터 동작.
  // 단, 게시판 입력창 등에 이미 포커스가 있으면 뺏지 않음(activeElement===body일 때만).
  try{if(document.activeElement===document.body||document.activeElement===null)pop.focus({preventScroll:true});}catch(e){}}
function closePop(){pop.style.display='none';document.body.classList.remove('naver-popup-open');pinned=false;destroyChart();
  document.removeEventListener('mousemove',unpinOnMove);
  if(stMode){stMode=false;stBtn.classList.remove('on');}}
function cancelClose(){clearTimeout(closeTimer);closeTimer=null;}
function scheduleClose(){cancelClose();closeTimer=setTimeout(()=>{if(!pinned)closePop();},220);}
// 키보드(s/d)로 종목 이동 시 임시 고정. 그 뒤 마우스가 팝업 밖에서 움직이면 고정 해제 → 자동닫힘 복구
function unpinOnMove(e){if(pop.contains(e.target))return;
  document.removeEventListener('mousemove',unpinOnMove);pinned=false;scheduleClose();}
function kbPin(){pinned=true;cancelClose();
  document.removeEventListener('mousemove',unpinOnMove);
  document.addEventListener('mousemove',unpinOnMove);}

document.getElementById('naverPopupClose').addEventListener('click',closePop);
// 모바일 탭 버튼
document.querySelectorAll('.popTab').forEach(b=>{
  b.addEventListener('click',e=>{e.stopPropagation();applyMobileTab(b.dataset.tab);});
});
function toggleST(){
  stMode=!stMode;
  stBtn.classList.toggle('on',stMode);
  if(curCode&&pop.style.display==='block'){
    const t=curTd||document.querySelector('td[data-code="'+curCode+'"], .chart-hover[data-code="'+curCode+'"]');
    showChart(curCode,t?(t.dataset.name||''):'');
  }
}
stBtn.addEventListener('click',e=>{e.stopPropagation();toggleST();});
pop.addEventListener('mouseenter',()=>{pinned=true;cancelClose();document.removeEventListener('mousemove',unpinOnMove);});
pop.addEventListener('mouseleave',()=>{pinned=false;scheduleClose();});
document.querySelectorAll('td[data-code], .chart-hover[data-code]').forEach(td=>{
  const hot=(td.tagName==='TD'&&td.nextElementSibling&&td.nextElementSibling.tagName==='TD')?td.nextElementSibling:td;
  hot.addEventListener('mouseenter',e=>{
    if(window.matchMedia('(hover: none)').matches)return;
    cancelClose();
    const x=e.clientX,y=e.clientY,code=(td.dataset.code||'').padStart(6,'0'),name=td.dataset.name||'';
    clearTimeout(openTimer);
    openTimer=setTimeout(()=>{placePop(x,y);openPop();showChart(code,name);curTd=td;},60);});
  hot.addEventListener('mouseleave',()=>{clearTimeout(openTimer);scheduleClose();});
  hot.addEventListener('click',e=>{
    if(window.matchMedia('(hover: none)').matches||window.innerWidth<=767){
      e.stopPropagation();cancelClose();clearTimeout(openTimer);
      openPop();pinned=true;showChart((td.dataset.code||'').padStart(6,'0'),td.dataset.name||'');curTd=td;}});
});
// 팝업 바깥 클릭 → 닫기 (PC/모바일 공통). td[data-code] 클릭은 제외(차트 유지)
document.addEventListener('click',e=>{
  if(pop.style.display!=='block')return;
  if(pop.contains(e.target))return;
  if(e.target.closest&&e.target.closest('td[data-code]'))return;
  closePop();});
// 키보드(팝업 열렸을 때만): A=Supertrend 토글, S/↑=이전, D/↓=다음, Tab/ESC=닫기
/* === SWIPE-NAV-INJECTED: 모바일 좌/우 스와이프 → 키보드 D/S 재사용 (PC 무영향) === */
(function(){
  if(window.__swipeNavInit) return; window.__swipeNavInit=true;
  function isTouch(){ return window.matchMedia('(hover: none)').matches || window.innerWidth<=767; }
  var sx=0, sy=0, st=0, tr=false;
  document.addEventListener('touchstart', function(e){
    if(!isTouch() || !e.touches || e.touches.length!==1){ tr=false; return; }
    var t=e.touches[0]; sx=t.clientX; sy=t.clientY; st=Date.now(); tr=true;
  }, true);
  document.addEventListener('touchend', function(e){
    if(!tr) return; tr=false;
    var t=e.changedTouches && e.changedTouches[0]; if(!t) return;
    var dx=t.clientX-sx, dy=t.clientY-sy, dt=Date.now()-st;
    if(dt>800 || Math.abs(dx)<55 || Math.abs(dx)<Math.abs(dy)*1.6) return;
    var key = dx<0 ? 'd' : 's';
    try{ document.dispatchEvent(new KeyboardEvent('keydown', {key:key, bubbles:true, cancelable:true})); }catch(err){}
  }, true);
})();
document.addEventListener('keydown',e=>{
  if(pop.style.display!=='block')return;
  const tg=e.target,tag=tg&&tg.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA'||(tg&&tg.isContentEditable))return;
  const k=e.key;
  if(k==='Tab'||k==='Escape'){e.preventDefault();closePop();return;}
  if(k==='a'||k==='A'){if(e.repeat)return;e.preventDefault();toggleST();return;}
  let dir=0;
  if(k==='s'||k==='S'||k==='ArrowUp')dir=-1;
  else if(k==='d'||k==='D'||k==='ArrowDown')dir=1;
  if(dir===0||!curTd)return;
  e.preventDefault();
  const all=Array.from(document.querySelectorAll('td[data-code], .chart-hover[data-code]'));
  let i=all.indexOf(curTd);
  if(i<0)return;
  i+=dir;
  if(i<0||i>=all.length)return;
  const nt=all[i];
  kbPin();
  showChart((nt.dataset.code||'').padStart(6,'0'),nt.dataset.name||'');
  curTd=nt;
  nt.scrollIntoView({block:'nearest'});});
window.addEventListener('resize',()=>{if(curCode&&pop.style.display==='block'){
  const t=document.querySelector('td[data-code="'+curCode+'"]');showChart(curCode,t?(t.dataset.name||''):'');}});
"""

# ───────── 진입점 ─────────
def build_chart_popup(codes, days5=5, trade_marks=None, cache_key=None, track_dates=None,
                      daily_trades=None, result_summary=None):
    """codes(6자리 리스트) → 팝업 <style>+HTML+<script> 블록 문자열 반환.
    네이버 PNG 팝업 자리에 그대로 끼워넣으면 됨.
    trade_marks: {code: [{"t":"YYYY-MM-DD HH:MM"(5분봉 시작), "s":"B"|"S"}]} —
      매매일지 게시판 전용 진입/청산 마커. 생략(None)하면 기존 게시판과 100% 동일 동작.
    cache_key: 지정 시 5분봉을 0txt/min5_cache_{key}.json에 덮어쓰고, 휴장일엔
      직전거래일 캐시로 폴백. None이면 캐시 미사용(기존 동작 동일)."""
    codes = sorted({str(c).zfill(6) for c in codes if str(c).strip()})
    if not codes:
        return "<!-- chart_popup_v2: no codes -->"
    print(f"  [chart_popup_v2] {len(codes)}종목 OHLCV 수집 (일봉+5분봉)...")
    t0 = time.time()
    cache5 = (os.path.join(BASE_DIR, "0txt", f"min5_cache_{cache_key}.json")
              if cache_key else None)
    cachek = (os.path.join(BASE_DIR, "0txt", f"kospi5_cache_{cache_key}.json")
              if cache_key else None)
    # 키움 토큰 1회 발급 → 종목 5분봉 + KOSPI 5분봉이 공유
    token = None
    if APP_KEY and SECRET_KEY:
        try:
            token = _kiwoom_token()
        except Exception as e:
            print(f"  [chart_popup_v2] 키움 토큰실패: {e}")
    daily = collect_daily(codes)
    daily = {c: attach_trend_daily(r) for c, r in daily.items()}   # coloryp 추세배경 → 일봉 index[6]
    min5  = collect_5min(codes, days=days5, cache_path=cache5, token=token)
    min5  = {c: attach_trend_5m(r) for c, r in min5.items()}       # coloryp 추세배경 → 5분봉 index[7]
    kospi_daily = fetch_kospi_daily()              # {date: 종가} (네이버, 주말도 OK)
    kospi5      = collect_kospi_5min(cachek, token) # {label: 값} 최신 1거래일 09:00~15:30
    nD = sum(1 for c in codes if daily.get(c))
    n5 = sum(1 for c in codes if min5.get(c))
    print(f"  [chart_popup_v2] 완료 {time.time()-t0:.1f}s · 일봉 {nD}/{len(codes)} · 5분봉 {n5}/{len(codes)}"
          f" · KOSPI(일 {len(kospi_daily)}/5분 {len(kospi5)})")
    nxt_codes = [c for c in codes if is_nxt(c)]
    js = (POPUP_JS
          .replace("__DAILY__", json.dumps(daily, ensure_ascii=False))
          .replace("__MIN5__",  json.dumps(min5,  ensure_ascii=False))
          .replace("__NXTSET__", json.dumps(nxt_codes))
          .replace("__TRADES__", json.dumps(trade_marks or {}, ensure_ascii=False))
          .replace("__DAILY_TRADES__", json.dumps(daily_trades or {}, ensure_ascii=False))
          .replace("__RESULT_SUMMARY__", json.dumps(result_summary or {}, ensure_ascii=False))
          .replace("__KOSPI_D__", json.dumps(kospi_daily, ensure_ascii=False))
          .replace("__KOSPI5__",  json.dumps(kospi5, ensure_ascii=False))
          .replace("__TRACK_D__", json.dumps(track_dates or {}, ensure_ascii=False)))
    return ("<style>" + POPUP_CSS + "</style>\n"
            + POPUP_HTML.replace("__DAYS5__", str(days5))
            + '\n<script src="lib/lightweight-charts.standalone.production.js"></script>\n'
            + "<script>\n(function(){\n" + js + "\n})();\n</script>")
