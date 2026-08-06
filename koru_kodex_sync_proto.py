r"""
[프로토타입] KORU(미국 3x 한국 ETF, 야간거래) 5분봉을
KODEX 레버리지(122630, 2x KOSPI) 정규장 5분봉 위에 선차트로 오버레이.

- 정렬: 오전 09:00 기준점 일치(rebase). KODEX 09:00 시가에 KORU도 맞춤.
- 구간: KODEX 정규장 09:00~15:30 만. (그 시간 = 미ET 20:00~02:30 KORU 야간봉)
- 진폭: 정규화 토글(ON=KORU %변동 ×2/3 로 2x에 맞춤 / OFF=원본 3x)
- 목적: 둘의 sync 확인 → 엇박자 시 차익실현/진입·청산.

출력: report-us/koru_kodex_sync_proto.html  (같은 폴더 lib/ 사용)
운영 danta_chart.html 은 건드리지 않음.
"""
import os, sys, json, time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(BASE_DIR))
from chart_popup_v2 import collect_5min   # 키움 ka10080 5분봉 (danta 보드와 동일)

load_dotenv(r"D:\py\.env")
DB_KEY    = os.environ["DBSEC_APP_KEY"]
DB_SECRET = os.environ["DBSEC_APP_SECRET"]
DB_URL    = "https://openapi.dbsec.co.kr:8443"
TOKEN_FILE = os.path.join(os.path.dirname(BASE_DIR), "0_dbinvest", "_token_cache.json")

ET  = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

KODEX_CODE = "122630"
KORU_TICKER = "KORU"
KORU_MARKET = "FA"     # NYSE Arca → DB증권 아멕스(FA)
SESSION_START = "09:00"
SESSION_END   = "15:30"


# ───────── DB증권 KORU 5분봉 ─────────
def db_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            c = json.load(f)
        if c.get("access_token") and time.time() < c["issued_at"] + c["expires_in"] - 3600:
            return c["access_token"]
    r = requests.post(f"{DB_URL}/oauth2/token",
        headers={"content-type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "appkey": DB_KEY,
              "appsecretkey": DB_SECRET, "scope": "oob"}, timeout=10, verify=False)
    r.raise_for_status()
    res = r.json()
    with open(TOKEN_FILE, "w") as f:
        json.dump({"access_token": res["access_token"],
                   "expires_in": int(res.get("expires_in", 86400)),
                   "issued_at": time.time()}, f)
    return res["access_token"]


def fetch_koru(cnt=400):
    tok = db_token()
    body = {"In": {"InputOrgAdjPrc": "1", "dataCnt": str(cnt), "InputPwDataIncuYn": "N",
                   "InputHourClsCode": "0", "InputCondMrktDivCode": KORU_MARKET,
                   "InputIscd1": KORU_TICKER, "InputDate1": "",
                   "InputDate2": datetime.now(ET).strftime("%Y%m%d"),
                   "InputDivXtick": "300"}}
    r = requests.post(f"{DB_URL}/api/v1/quote/overseas-stock/chart/min",
        headers={"content-type": "application/json;charset=utf-8",
                 "authorization": f"Bearer {tok}", "cont_yn": "N", "cont_key": ""},
        json=body, timeout=20, verify=False)
    r.raise_for_status()
    rows = r.json().get("Out") or []
    out = []   # (kst_label 'YYYY-MM-DD HH:MM', close)
    for b in rows:
        dt_et = datetime.strptime(b["Date"] + b["Hour"].zfill(6), "%Y%m%d%H%M%S").replace(tzinfo=ET)
        lbl = dt_et.astimezone(KST).strftime("%Y-%m-%d %H:%M")
        try:
            out.append((lbl, float(b["Prpr"])))
        except (KeyError, ValueError):
            pass
    return out


# ───────── KODEX 오늘 정규장 봉 ─────────
def kodex_today_session():
    min5 = collect_5min([KODEX_CODE], days=2)
    rows = min5.get(KODEX_CODE, [])
    if not rows:
        return None, []
    # 가장 최근 거래일
    last_day = rows[-1][6][:10]
    sess = [r for r in rows
            if r[6][:10] == last_day and SESSION_START <= r[6][11:16] <= SESSION_END]
    return last_day, sess


def main():
    print("[KODEX] 122630 5분봉 수집(키움)...")
    day, kodex = kodex_today_session()
    if not kodex:
        print("  ⚠ KODEX 데이터 없음"); return
    print(f"  거래일 {day} · 정규장 {SESSION_START}~{SESSION_END} · {len(kodex)}봉")

    print("[KORU] 5분봉 수집(DB증권)...")
    koru_all = fetch_koru()
    koru_map = dict(koru_all)   # kst_label -> close
    print(f"  수신 {len(koru_all)}봉")

    # KODEX 라벨 → ts, 그리고 겹치는 KORU 매칭
    kodex_out = [{"time": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4]}
                 for r in kodex]
    base_won = kodex[0][1]   # 09:00 시가 = 기준점

    koru_pts = []            # {time, close}  (라벨매칭된 것만, KODEX ts 차용)
    for r in kodex:
        lbl = r[6]
        if lbl in koru_map:
            koru_pts.append({"time": r[0], "koru": koru_map[lbl], "label": lbl})
    print(f"  KODEX 구간과 매칭된 KORU 봉: {len(koru_pts)}/{len(kodex)}")
    if not koru_pts:
        print("  ⚠ 매칭 KORU 봉 없음 (야간거래 데이터/시간대 확인 필요)")
        return
    koru_base = koru_pts[0]["koru"]
    print(f"  기준: KODEX 09:00 시가={base_won:,.0f}원  KORU 09:00={koru_base:.2f}")
    print(f"  매칭 범위: {koru_pts[0]['label']} ~ {koru_pts[-1]['label']}")

    payload = {
        "day": day, "base_won": base_won, "koru_base": koru_base,
        "kodex": kodex_out,
        "koru": [{"time": p["time"], "koru": p["koru"]} for p in koru_pts],
    }
    html = HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    out_path = os.path.join(BASE_DIR, "koru_kodex_sync_proto.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[OK] {out_path}  ({os.path.getsize(out_path)//1024} KB)")


HTML = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KORU × KODEX 레버리지 sync (프로토타입)</title>
<script src="lib/lightweight-charts.standalone.production.js"></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#f0f2f5;font-family:-apple-system,'Malgun Gothic',sans-serif;padding:18px;color:#1f2937}
  h1{font-size:16px;margin-bottom:6px}
  .sub{font-size:12px;color:#666;margin-bottom:10px}
  .bar{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
  .toggle{display:inline-flex;align-items:center;gap:6px;background:#fff;border:1px solid #ddd;
    border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer;user-select:none}
  .toggle input{cursor:pointer}
  .lg{font-size:12px;color:#444}
  .lg b.kd{color:#f23645} .lg b.kr{color:#7c3aed}
  .card{background:#fff;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.08);padding:10px 8px 4px}
  #chart{width:100%;height:460px}
  .foot{font-size:11px;color:#888;margin-top:8px;line-height:1.6}
</style></head><body>
<h1>KORU × KODEX 레버리지 — 09:00 rebase sync</h1>
<div class="sub" id="sub"></div>
<div class="bar">
  <label class="toggle"><input type="checkbox" id="norm">
    진폭 정규화 (KORU %×2/3 → 2x에 맞춤)</label>
  <span class="lg">캔들 <b class="kd">KODEX 레버리지(2x)</b> · 선 <b class="kr">KORU(3x, 야간거래)</b></span>
</div>
<div class="card"><div id="chart"></div></div>
<div class="foot" id="foot"></div>
<script>
const D = __DATA__;
const UP='#f23645', DOWN='#2962ff', KORU_COLOR='#7c3aed';
const won=n=>Math.round(n).toLocaleString();

const chart = LightweightCharts.createChart(document.getElementById('chart'),{
  width:document.getElementById('chart').clientWidth, height:460,
  layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
  grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
  rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.1,bottom:0.08}},
  timeScale:{borderColor:'#ddd',timeVisible:true,secondsVisible:false,rightOffset:3,minBarSpacing:2},
  crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});

const cs = chart.addCandlestickSeries({upColor:UP,downColor:DOWN,borderUpColor:UP,
  borderDownColor:DOWN,wickUpColor:UP,wickDownColor:DOWN,
  priceFormat:{type:'custom',minMove:1,formatter:won}});
cs.setData(D.kodex);

const kl = chart.addLineSeries({color:KORU_COLOR,lineWidth:2,priceLineVisible:false,
  lastValueVisible:true,crosshairMarkerVisible:true,
  priceFormat:{type:'custom',minMove:1,formatter:won}});

// 09:00 기준선(0%) — KODEX 09:00 시가
cs.createPriceLine({price:D.base_won,color:'#9ca3af',lineWidth:1,
  lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:'09:00'});

function koruData(normalize){
  const b = D.koru_base, factor = normalize ? (2/3) : 1;
  return D.koru.map(p=>{
    const pct = (p.koru / b - 1) * factor;      // 09:00 대비 %변동 (정규화 시 ×2/3)
    return {time:p.time, value:D.base_won*(1+pct)};  // KODEX 09:00 시가에 rebase
  });
}
function redraw(){ kl.setData(koruData(document.getElementById('norm').checked)); }
document.getElementById('norm').addEventListener('change',redraw);
redraw();
chart.timeScale().fitContent();

// 요약 정보
const kdC = D.kodex[D.kodex.length-1].close, kdO = D.kodex[0].open;
const kdPct = ((kdC/kdO-1)*100).toFixed(2);
const krC = D.koru[D.koru.length-1].koru, krO = D.koru_base;
const krPct = ((krC/krO-1)*100).toFixed(2);
document.getElementById('sub').textContent =
  D.day+' 정규장 09:00~15:30 · KODEX '+(kdPct>=0?'+':'')+kdPct+'% · KORU '+(krPct>=0?'+':'')+krPct+'% (원본3x)';
document.getElementById('foot').innerHTML =
  '· 회색 점선 = 09:00 기준(0%). 캔들=KODEX 레버리지, 보라선=KORU(야간거래) 를 09:00 시가에 맞춰 rebase.<br>'+
  '· 정규화 ON: KORU %변동×2/3 로 2x 진폭에 맞춤(엇박자/타이밍 비교). OFF: 원본 3x 진폭.<br>'+
  '· 선이 캔들보다 먼저 꺾이면 야간거래(미국) 선행 → 진입/청산 참고. 벌어지면 sync 이탈.';

new ResizeObserver(()=>chart.applyOptions({width:document.getElementById('chart').clientWidth}))
  .observe(document.getElementById('chart'));
</script></body></html>"""


if __name__ == "__main__":
    main()
