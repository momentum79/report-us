# make_index_kr_150.py
import json
import html
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta, date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trading_day import is_kr_trading_day, last_kr_trading_day  # noqa: E402

BASE = Path(r"D:\py\report-us")
REPORT_JSON = BASE / "report_kr_150.json"
OUT_HTML = BASE / "kor_150.html"
LEADER_TRACKING_JSON = BASE / "leader_tracking_150.json"  # 📊 주도주 트래킹 (kr150 전용)
GANN_FIRE_JSON = BASE / "kr150_gann_fire_set.json"  # 🔥 SGDDEMA 불기둥 신호
CLOSE_FILE    = Path(r"D:\py\0txt\kor_today_close.json")
PCT_FILE      = Path(r"D:\py\0txt\kor_today_pct.json")
INVESTOR_FILE = Path(r"D:\py\0txt\leader_investor_data.json")
HIGH52W_JSON  = BASE / "kr_52w_high.json"  # 52주 신고가 95% 이상 종목

# ── 내장형 인터랙티브 차트 (네이버 PNG 팝업 대체) ──────────────────────
LIB_JS      = BASE / "lib" / "lightweight-charts.standalone.production.js"
YEARS_BACK  = 3          # 주봉 MA120 확보 위해 3년
MAX_WORKERS = 8
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://finance.naver.com/"}


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


def _fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise last


def fetch_domestic(code, s_ymd, e_ymd):
    """네이버 siseJson 일봉 OHLCV → [[YYYY-MM-DD,o,h,l,c,v], ...]"""
    url = ("https://api.finance.naver.com/siseJson.naver"
           f"?symbol={code}&requestType=1&startTime={s_ymd}&endTime={e_ymd}&timeframe=day")
    raw = _fetch(url)
    pat = re.compile(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*(\d+)')
    out = []
    for m in pat.finditer(raw):
        d, o, h, l, c, v = m.groups()
        out.append([f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
                    float(o), float(h), float(l), float(c), int(v)])
    return out


def collect_ohlcv_kr(codes):
    """KR 6자리 코드 리스트 → {code: rows} 병렬 수집."""
    end = date.today()
    start = end - timedelta(days=365 * YEARS_BACK + 15)
    s_ymd, e_ymd = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def work(code):
        try:
            return code, fetch_domestic(code, s_ymd, e_ymd)
        except Exception as ex:
            print(f"  [ERR] {code}: {ex}")
            return code, []

    res = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for code, rows in ex.map(work, codes):
            res[code] = rows
            print(f"  {code} {len(rows):>4} bars")
    return res


def fetch_kospi_daily_fallback(days_back=60):
    """chart_popup_v2 import가 실패해도 KOSPI 일봉 오버레이는 네이버에서 직접 수집."""
    end = date.today()
    start = end - timedelta(days=days_back)
    rows = fetch_domestic("KOSPI", start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    return {r[0]: r[4] for r in rows}


def build_chart_popup(ohlcv_json, kospi_daily_json="{}", track_json="{}"):
    """네이버 PNG 팝업을 대체할 lightweight-charts 팝업(HTML+JS) 블록 생성."""
    popup_html = """
<div id="naverChartPopup" tabindex="-1">
  <div class="popup-header">
    <button id="naverPopupClose">&#x2715;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 종목 페이지</a>
    <span id="popMs"></span>
    <button id="stBtn" title="Supertrend 토글 (10/3·11/2·12/1) · a키">S</button>
  </div>
  <div id="popBox">
    <div class="col" id="colD">
      <div class="collab"><span class="tfbadge">일</span></div>
      <div class="cchart"></div>
      <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div>
      <div class="rchart"></div>
    </div>
    <div class="col" id="colW">
      <div class="collab"><span class="tfbadge">주</span></div>
      <div class="cchart"></div>
      <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div>
      <div class="rchart"></div>
    </div>
  </div>
</div>"""

    chart_js = r"""
const OHLCV = __OHLCV__;
const KOSPI_D = __KOSPI_D__;   // {'YYYY-MM-DD': 종가} KOSPI 종합 일봉 (오버레이용)
const TRACK_D = __TRACK_D__;   // {code:['YYYY-MM-DD',...]} 트래킹 등록일 → 일봉 세로 배경 띠
// 거래대금게시판과 동일: 회색50% 점선, 종목캔들 뒤(z-order상 먼저 생성)
const KOSPI_STYLE = {color:'rgba(150,150,150,0.5)',lineWidth:2,
  lineStyle:LightweightCharts.LineStyle.Dotted,priceLineVisible:false,
  lastValueVisible:false,crosshairMarkerVisible:false,
  autoscaleInfoProvider:()=>null};
// MA5=빨강 MA10=짙은회색 MA20=주황 MA60=녹색 MA120=검정
const MA_DEFS = [[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a'],[120,'#000000']];
const UP_COLOR='#f23645', DOWN_COLOR='#2962ff';
const VOL_UP='rgba(242,54,69,0.35)', VOL_DOWN='rgba(41,98,255,0.35)';
const RIGHT_PAD = 5;
const krAxisFmt=n=>{
  const v=Math.round(n);
  return Math.abs(v)>=1000000 ? Math.round(v/1000).toLocaleString()+'K' : v.toLocaleString();
};
const KR_PRICE_FORMAT={type:'custom',minMove:1,formatter:krAxisFmt};
KOSPI_STYLE.priceFormat=KR_PRICE_FORMAT;

function sma(closes, p){
  const out=[]; let s=0;
  for(let i=0;i<closes.length;i++){ s+=closes[i]; if(i>=p)s-=closes[i-p];
    if(i>=p-1) out.push({i, value:+(s/p).toFixed(4)}); }
  return out;
}
function mondayOf(dstr){
  const d=new Date(dstr+'T00:00:00');
  const day=(d.getDay()+6)%7;
  d.setDate(d.getDate()-day);
  return d.toISOString().slice(0,10);
}
function toWeekly(raw){
  const map=new Map();
  for(const r of raw){
    const k=mondayOf(r[0]);
    let w=map.get(k);
    if(!w){ map.set(k,[k,r[1],r[2],r[3],r[4],r[5]]); }
    else { w[2]=Math.max(w[2],r[2]); w[3]=Math.min(w[3],r[3]); w[4]=r[4]; w[5]+=r[5]; }
  }
  return [...map.values()].sort((a,b)=>a[0]<b[0]?-1:1);
}
function rsiWilder(closes, p){
  const out=new Array(closes.length).fill(null);
  let gain=0, loss=0;
  for(let i=1;i<closes.length;i++){
    const ch=closes[i]-closes[i-1], g=ch>0?ch:0, l=ch<0?-ch:0;
    if(i<=p){ gain+=g; loss+=l;
      if(i===p){ gain/=p; loss/=p; out[i]=100-100/(1+(loss===0?1e9:gain/loss)); } }
    else { gain=(gain*(p-1)+g)/p; loss=(loss*(p-1)+l)/p;
      out[i]=100-100/(1+(loss===0?1e9:gain/loss)); }
  }
  return out;
}
function smaArr(arr, p){
  const out=new Array(arr.length).fill(null); const buf=[]; let s=0;
  for(let i=0;i<arr.length;i++){
    const v=arr[i];
    if(v==null){ buf.length=0; s=0; continue; }
    buf.push(v); s+=v; if(buf.length>p){ s-=buf.shift(); }
    if(buf.length===p) out[i]=s/p;
  }
  return out;
}
// ── MagicTrend (TradingView @v4 "SL" 동일 공식) — ATR=sma(tr,AP), 색=cci(close,20) 부호(≥0 파랑/<0 빨강)
function cciN(close,length){
  const n=close.length,out=new Array(n).fill(null),ma=smaArr(close,length);
  for(let i=0;i<n;i++){
    if(ma[i]==null)continue;
    let d=0;for(let j=i-length+1;j<=i;j++)d+=Math.abs(close[j]-ma[i]);
    d/=length; out[i]=(d===0)?0:(close[i]-ma[i])/(0.015*d);
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
  let prev=0;
  for(let i=0;i<n;i++){
    const c=cci[i],a=atr[i];
    if(c==null||a==null){mt[i]=null;up[i]=null;prev=0;continue;}
    const upT=low[i]-a*coeff, downT=high[i]+a*coeff;
    const v=(c>=0)?((upT<prev)?prev:upT):((downT>prev)?prev:downT);
    mt[i]=v; up[i]=(c>=0); prev=v;
  }
  return {mt,up};
}

// ── Supertrend (TradingView ta.supertrend(factor, atrPeriod) 동일 공식) ──
// ATR=Wilder RMA(true range, atrPeriod) ; hl2±factor*ATR 밴드를 끌고가며 direction(<0 상승/>0 하락) 전환.
// S버튼 ON 시 MagicTrend 대신 3종(10/3·11/2·12/1)을 선+음영밴드로 표시.
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
    if(!hasPrev)            d=1;
    else if(prevST===prevUpper) d=(close[i]>upper)?-1:1;
    else                   d=(close[i]<lower)? 1:-1;
    const v=(d===-1)?lower:upper;
    st[i]=v; dir[i]=d; prevUpper=upper; prevLower=lower; prevST=v;
  }
  return {st,dir};   // dir<0 상승(초록) / dir>0 하락(빨강)
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
// 캔버스 오버레이로 밴드 채움 — 팬/줌 시에만 rAF 스로틀 재드로우(호버는 트리거 안 함).
function installBandOverlay(el,ch,priceSeries,bands){
  if(!SHOW_BANDS||!bands.length)return;
  el.style.position='relative';
  const canvas=document.createElement('canvas');
  canvas.className='st-band-overlay';
  canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;';
  el.appendChild(canvas);
  let raf=0;
  function queueDraw(){ if(raf)return; raf=requestAnimationFrame(()=>{raf=0;draw();}); }
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

const pop      = document.getElementById('naverChartPopup');
const popTitle = document.getElementById('popupTitle');
const popLink  = document.getElementById('popupLink');
const popMs    = document.getElementById('popMs');
const popBox   = document.getElementById('popBox');
const stBtn    = document.getElementById('stBtn');
let charts=[], openTimer=null, closeTimer=null, pinned=false, curCode=null;
let stMode=false;   // false=기본(MagicTrend) / true=Supertrend 3종. 페이지 변수 → 게시판 나가면(새로고침) 자동 디폴트

function destroyChart(){ charts.forEach(c=>{try{c.remove();}catch(e){}}); charts=[];
  document.querySelectorAll('#popBox .st-band-overlay').forEach(n=>n.remove()); }

function buildColumn(col, raw, isKr, defaultBars, withKospi, trackDates){
  const candleEl = col.querySelector('.cchart');
  const rsiEl    = col.querySelector('.rchart');
  const times  = raw.map(r=>r[0]);
  const closes = raw.map(r=>r[4]);
  const pf = p=> isKr? Math.round(p).toLocaleString(): p.toFixed(2);

  const cChart = LightweightCharts.createChart(candleEl, {
    width:candleEl.clientWidth, height:candleEl.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.08,bottom:0.08}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:0.4,visible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    // 모바일(터치)에서만 차트 가로 드래그 비활성 → 좌우 스와이프를 '종목이동' 제스처로 사용. PC(마우스)는 영향 없음.
    handleScroll:{horzTouchDrag:!(window.matchMedia('(hover: none)').matches)},
    localization:{priceFormatter:isKr?krAxisFmt:(p=>p.toFixed(2))},
  });
  // 트래킹 등록일 세로 배경 띠 — 캔들보다 먼저 생성 → z-order상 가장 뒤 (캔들이 위)
  const trkBand = (trackDates&&trackDates.length) ? cChart.addHistogramSeries({
    priceScaleId:'trkband',base:0,priceLineVisible:false,lastValueVisible:false,
    color:'rgba(50,205,50,0.30)'}) : null;
  if(trkBand) cChart.priceScale('trkband').applyOptions({scaleMargins:{top:0,bottom:0}});
  // KOSPI 점선은 캔들보다 먼저 생성 → z-order상 뒤(종목 캔들이 앞)
  const kospiLine = (withKospi && !stMode) ? cChart.addLineSeries(KOSPI_STYLE) : null;
  const candle = cChart.addCandlestickSeries({
    upColor:UP_COLOR,downColor:DOWN_COLOR,borderUpColor:UP_COLOR,
    borderDownColor:DOWN_COLOR,wickUpColor:UP_COLOR,wickDownColor:DOWN_COLOR,
    priceFormat:isKr?KR_PRICE_FORMAT:{type:'custom',minMove:0.01,formatter:pf}});
  candle.setData(raw.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
  if(trkBand){const st=new Set(trackDates);
    const bd=raw.filter(r=>st.has(r[0])).map(r=>({time:r[0],value:1,color:'rgba(50,205,50,0.30)'}));
    if(bd.length)trkBand.setData(bd);}
  // ── KOSPI 종합 점선 오버레이 (최근 20봉전 기준 rebase, 끝점 회색 사각마커) ──
  if(kospiLine){
    const m=raw.length, aIdx=Math.max(0,m-1-20);
    const K0=KOSPI_D[raw[aIdx][0]], P0=raw[aIdx][4];
    if(K0!=null && K0){
      const kd=[];
      for(let i=aIdx;i<m;i++){
        const K=KOSPI_D[raw[i][0]];
        if(K==null)continue;
        kd.push({time:raw[i][0],value:P0*K/K0});
      }
      if(kd.length>=2){
        kospiLine.setData(kd);
        kospiLine.setMarkers([{time:kd[kd.length-1].time,position:'inBar',
          color:'rgba(150,150,150,0.5)',shape:'square',size:2}]);
      }
    }
  }
  const vol = cChart.addHistogramSeries({priceScaleId:'',
    priceFormat:{type:'custom',minMove:1,formatter:v=>Math.round(v/1000).toLocaleString()+'K'}});
  vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
  vol.setData(raw.map(r=>({time:r[0],value:r[5],
    color:r[4]>=r[1]?VOL_UP:VOL_DOWN})));
  if(!stMode){
    MA_DEFS.forEach(([p,color])=>{
      const ln=cChart.addLineSeries({color,lineWidth:1,priceLineVisible:false,
        priceFormat:KR_PRICE_FORMAT,autoscaleInfoProvider:()=>null,
        lastValueVisible:false,crosshairMarkerVisible:false});
      const mp=new Map(sma(closes,p).map(o=>[times[o.i],o.value]));
      ln.setData(times.map(t=> mp.has(t)? {time:t,value:mp.get(t)} : {time:t}));
    });
    // 기본: MagicTrend(10,3) ATR선 오버레이 — 2px 점선, 점별 색(CCI≥0 파랑/<0 빨강). 거래대금 팝업과 동일
    const _mt=magicTrend(raw,3,10,20);
    const mtData=raw.map((b,i)=> _mt.mt[i]==null? {time:b[0]}
      : {time:b[0],value:+_mt.mt[i].toFixed(2),color:_mt.up[i]?'#0022FC':'#ff5252'});
    const mtLine=cChart.addLineSeries({color:'#0022FC',lineWidth:2,
      lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,
      priceFormat:KR_PRICE_FORMAT,autoscaleInfoProvider:()=>null,
      lastValueVisible:false,crosshairMarkerVisible:false});
    mtLine.setData(mtData);
  } else {
    // Supertrend 3종(10/3·11/2·12/1) — 선 3개 + 음영밴드(bodyMid↔Supertrend, 캔버스 오버레이)
    const STS=ST_PARAMS.map(sp=>supertrend(raw,sp.factor,sp.atr));
    const bodyMid=times.map((t,i)=>({time:t,value:+(((raw[i][1]+raw[i][4])/2).toFixed(2))}));
    const stUp=STS.map(r=>times.map((t,i)=>(r.st[i]!=null&&r.dir[i]<0)?{time:t,value:+r.st[i].toFixed(2)}:{time:t}));
    const stDn=STS.map(r=>times.map((t,i)=>(r.st[i]!=null&&r.dir[i]>0)?{time:t,value:+r.st[i].toFixed(2)}:{time:t}));
    installBandOverlay(candleEl,cChart,candle,ST_PARAMS.flatMap((sp,si)=>[
      {color:sp.bandUp,points:buildFillEnvelope(bodyMid,stUp[si],sp.bandUp)},
      {color:sp.bandDn,points:buildFillEnvelope(bodyMid,stDn[si],sp.bandDn)}
    ]));
    ST_PARAMS.forEach((sp,si)=>{const r=STS[si];
      const ln=cChart.addLineSeries({color:sp.up,lineWidth:sp.w,priceLineVisible:false,
        priceFormat:KR_PRICE_FORMAT,autoscaleInfoProvider:()=>null,
        lastValueVisible:false,crosshairMarkerVisible:false});
      ln.setData(times.map((t,i)=>r.st[i]==null?{time:t}
        :{time:t,value:+r.st[i].toFixed(2),color:r.dir[i]<0?sp.up:sp.dn}));});
  }

  const rChart = LightweightCharts.createChart(rsiEl, {
    width:rsiEl.clientWidth, height:rsiEl.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#888',fontSize:10},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f7f7f7'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.12,bottom:0.12}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:0.4},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    handleScroll:{horzTouchDrag:!(window.matchMedia('(hover: none)').matches)},
  });
  const rsiArr = rsiWilder(closes,14);
  const rsiMa  = smaArr(rsiArr,14);
  const rdata  = times.map((t,i)=> rsiArr[i]==null? {time:t} : {time:t,value:+rsiArr[i].toFixed(2)});
  // 과매수(>70) 녹색 / 과매도(<30) 빨강 — baseline series 음영 (RSI 데이터 재사용)
  const rsiUp = rChart.addBaselineSeries({baseValue:{type:'price',price:70},
    topLineColor:'rgba(0,0,0,0)',
    topFillColor1:'rgba(50,205,50,0.62)',topFillColor2:'rgba(50,205,50,0.30)',
    bottomLineColor:'rgba(0,0,0,0)',
    bottomFillColor1:'rgba(0,0,0,0)',bottomFillColor2:'rgba(0,0,0,0)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  rsiUp.setData(rdata);
  const rsiDn = rChart.addBaselineSeries({baseValue:{type:'price',price:30},
    topLineColor:'rgba(0,0,0,0)',
    topFillColor1:'rgba(0,0,0,0)',topFillColor2:'rgba(0,0,0,0)',
    bottomLineColor:'rgba(0,0,0,0)',
    bottomFillColor1:'rgba(239,68,68,0.30)',bottomFillColor2:'rgba(239,68,68,0.62)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  rsiDn.setData(rdata);
  const rsiLine = rChart.addLineSeries({color:DOWN_COLOR,lineWidth:1,priceLineVisible:false,
    lastValueVisible:true,crosshairMarkerVisible:false});
  rsiLine.setData(rdata);
  const rmaLine = rChart.addLineSeries({color:UP_COLOR,lineWidth:1,priceLineVisible:false,
    lastValueVisible:false,crosshairMarkerVisible:false});
  rmaLine.setData(times.map((t,i)=> rsiMa[i]==null? {time:t} : {time:t,value:+rsiMa[i].toFixed(2)}));
  [70,30].forEach(lv=>rsiLine.createPriceLine({price:lv,color:'#9ca3af',
    lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true}));

  const n=raw.length, from=Math.max(0,n-defaultBars);
  cChart.timeScale().setVisibleLogicalRange({from, to:n-1+RIGHT_PAD});
  rChart.timeScale().setVisibleLogicalRange({from, to:n-1+RIGHT_PAD});

  let lock=false;
  const sync=(src,dst)=>src.timeScale().subscribeVisibleLogicalRangeChange(r=>{
    if(lock||!r)return; lock=true; dst.timeScale().setVisibleLogicalRange(r); lock=false; });
  sync(cChart,rChart); sync(rChart,cChart);

  // 캔들↔RSI 우측 가격축 폭 동기화 → 세로 시간축 정렬 (가격 여러자리 vs RSI 2자리로 축폭이 달라 어긋나던 문제)
  const syncW=()=>{try{
    const w=Math.max(cChart.priceScale('right').width(),rChart.priceScale('right').width());
    cChart.priceScale('right').applyOptions({minimumWidth:w});
    rChart.priceScale('right').applyOptions({minimumWidth:w});
  }catch(e){}};
  requestAnimationFrame(syncW);
  cChart.timeScale().subscribeVisibleLogicalRangeChange(syncW);

  // 캔들↔RSI 크로스헤어(세로선) 동기화 — 한쪽 hover 시 다른쪽도 같은 시각 세로선 표시
  const cMap=new Map(raw.map(b=>[b[0],b[4]]));
  const rMap=new Map(rdata.filter(d=>d.value!=null).map(d=>[d.time,d.value]));
  let xlock=false;
  const xlink=(src,dst,dstS,dstMap)=>src.subscribeCrosshairMove(p=>{
    if(xlock)return;xlock=true;
    if(p.time==null||p.point==null)dst.clearCrosshairPosition();
    else{const v=dstMap.get(p.time);
      if(v==null)dst.clearCrosshairPosition();else dst.setCrosshairPosition(v,p.time,dstS);}
    xlock=false;});
  xlink(cChart,rChart,rsiLine,rMap);xlink(rChart,cChart,candle,cMap);

  charts.push(cChart,rChart);
}

function showChart(code, name){
  const raw = OHLCV[code];
  curCode = code;
  popTitle.textContent = code + '  ' + (name||'');
  popLink.href = 'https://finance.naver.com/item/main.naver?code=' + code;
  destroyChart();
  const colD=document.getElementById('colD'), colW=document.getElementById('colW');
  popBox.querySelector('.empty')?.remove();
  if(!raw || !raw.length){
    colD.style.visibility='hidden'; colW.style.visibility='hidden';
    const e=document.createElement('div'); e.className='empty'; e.textContent='데이터 없음'; popBox.appendChild(e);
    popMs.textContent=''; return;
  }
  colD.style.visibility='visible'; colW.style.visibility='visible';
  const t0=performance.now();
  buildColumn(colD, raw, true, 63, true, TRACK_D[code]||null);
  buildColumn(colW, toWeekly(raw), true, 52, false, null);
  const ms=performance.now()-t0;
  popMs.textContent = 'render ' + (Math.round(ms*10)/10) + ' ms · ' + raw.length + ' bars';
}

function placePop(x,y){
  if(window.innerWidth<=767) return;   // 모바일은 CSS 고정
  const w=Math.min(1500,window.innerWidth-20), h=760;
  let px=x+18, py=y+18;
  if(px+w>window.innerWidth-8) px=x-w-12;
  if(py+h>window.innerHeight-8) py=y-h-12;
  pop.style.left=Math.max(8,px)+'px'; pop.style.top=Math.max(8,py)+'px'; pop.style.transform='none';
}
function openPop(){ pop.style.display='block'; document.body.classList.add('naver-popup-open');
  // iframe 안에서 열릴 때 키보드 포커스를 잡아야 a/s/d 단축키가 첫 호버부터 동작.
  // 단, 게시판 입력창 등에 이미 포커스가 있으면 뺏지 않음(activeElement===body일 때만).
  try{ if(document.activeElement===document.body||document.activeElement===null) pop.focus({preventScroll:true}); }catch(e){} }
function closePop(){ pop.style.display='none'; document.body.classList.remove('naver-popup-open'); pinned=false; destroyChart();
  document.removeEventListener('mousemove',unpinOnMove);
  if(stMode){ stMode=false; stBtn.classList.remove('on'); } }
function cancelClose(){ clearTimeout(closeTimer); closeTimer=null; }
function scheduleClose(){ cancelClose(); closeTimer=setTimeout(()=>{ if(!pinned) closePop(); },220); }
// 키보드(s/d)로 종목 이동 시 임시 고정. 그 뒤 마우스가 팝업 밖에서 움직이면 고정 해제 → 자동닫힘 복구
function unpinOnMove(e){ if(pop.contains(e.target))return;
  document.removeEventListener('mousemove',unpinOnMove); pinned=false; scheduleClose(); }
function kbPin(){ pinned=true; cancelClose();
  document.removeEventListener('mousemove',unpinOnMove);
  document.addEventListener('mousemove',unpinOnMove); }

document.getElementById('naverPopupClose').addEventListener('click',closePop);
// S버튼: Supertrend ↔ 기본(MagicTrend) 토글 후 현재 종목 재렌더 (열려있을 때만)
function toggleST(){
  stMode=!stMode;
  stBtn.classList.toggle('on',stMode);
  if(curCode && pop.style.display==='block'){
    const t=document.querySelector('td[data-code="'+curCode+'"]');
    showChart(curCode, t? (t.dataset.name||''):'');
  }
}
stBtn.addEventListener('click',e=>{ e.stopPropagation(); toggleST(); });
// 키보드(팝업 열렸을 때만): A=Supertrend 토글, S/↑=이전, D/↓=다음, Tab/ESC=닫기
document.addEventListener('keydown',e=>{
  if(pop.style.display!=='block')return;
  const t=e.target, tag=t&&t.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA'||(t&&t.isContentEditable))return;
  const k=e.key;
  if(k==='Tab'||k==='Escape'){ e.preventDefault(); closePop(); return; }
  if(k==='a'||k==='A'){ if(e.repeat)return; e.preventDefault(); toggleST(); return; }
  let dir=0;
  if(k==='s'||k==='S'||k==='ArrowUp') dir=-1;
  else if(k==='d'||k==='D'||k==='ArrowDown') dir=1;
  if(dir===0||!curCode) return;
  e.preventDefault();
  const all=Array.from(document.querySelectorAll('td[data-code]'));
  let i=all.findIndex(td=>td.dataset.code===curCode);
  if(i<0) return;
  i+=dir; if(i<0||i>=all.length) return;
  const nt=all[i];
  kbPin();
  showChart(nt.dataset.code, nt.dataset.name||'');
  nt.scrollIntoView({block:'nearest'});
});
// ── 모바일 전용: 차트 팝업 안에서 좌/우 스와이프로 종목 이동 (PC는 위 keydown 그대로, 여기 영향 없음) ──
// 왼쪽으로 밀기 = 다음 종목 / 오른쪽으로 밀기 = 이전 종목 (키보드 D/S와 동일 방향)
(function(){
  const isTouch = ()=> window.matchMedia('(hover: none)').matches || window.innerWidth<=767;
  let swipeTd = null;   // 마지막으로 연/이동한 종목 셀(요소). 코드 중복(여러 표) 때문에 '코드'가 아닌 '요소'로 추적.
  document.addEventListener('click',e=>{   // 종목 탭 시 기준 셀 기록(캡처). 이름칸을 탭하면 바로 앞 코드칸 사용.
    if(!isTouch()) return;
    const cell=e.target.closest && e.target.closest('td'); if(!cell) return;
    const td = cell.matches('[data-code]') ? cell
             : (cell.previousElementSibling && cell.previousElementSibling.matches && cell.previousElementSibling.matches('[data-code]') ? cell.previousElementSibling : null);
    if(td) swipeTd=td;
  },true);
  function swipeMove(dir){
    let base = swipeTd || (curCode ? document.querySelector('td[data-code="'+curCode+'"]') : null);
    if(!base) return;
    const all = Array.from(document.querySelectorAll('td[data-code]'));  // 전체 표를 가로질러 쭉 순차 이동
    let i = all.indexOf(base);
    if(i<0) return;
    i+=dir; if(i<0||i>=all.length) return;
    const nt=all[i];
    swipeTd=nt;
    pinned=true; cancelClose();
    showChart(nt.dataset.code, nt.dataset.name||'');
  }
  let sx=0, sy=0, st=0, tracking=false;
  pop.addEventListener('touchstart',e=>{
    if(!isTouch() || pop.style.display!=='block' || e.touches.length!==1){ tracking=false; return; }
    const t=e.touches[0]; sx=t.clientX; sy=t.clientY; st=Date.now(); tracking=true;
  },{passive:true});
  pop.addEventListener('touchend',e=>{
    if(!tracking) return; tracking=false;
    const t=e.changedTouches&&e.changedTouches[0]; if(!t) return;
    const dx=t.clientX-sx, dy=t.clientY-sy, dt=Date.now()-st;
    if(dt>800) return;                          // 너무 느린 동작(스크롤/롱프레스)
    if(Math.abs(dx)<55) return;                 // 가로 이동량 부족
    if(Math.abs(dx)<Math.abs(dy)*1.6) return;   // 세로 스크롤이 더 크면 무시
    swipeMove(dx<0 ? 1 : -1);                   // 왼쪽=다음, 오른쪽=이전
  },{passive:true});
})();
pop.addEventListener('mouseenter',()=>{ pinned=true; cancelClose(); document.removeEventListener('mousemove',unpinOnMove); });
pop.addEventListener('mouseleave',()=>{ pinned=false; scheduleClose(); });

document.querySelectorAll('td[data-code]').forEach(td=>{
  const hot=(td.nextElementSibling&&td.nextElementSibling.tagName==='TD')?td.nextElementSibling:td;
  hot.addEventListener('mouseenter',e=>{
    if(window.matchMedia('(hover: none)').matches) return;  // 터치기기만 제외
    cancelClose();
    const x=e.clientX, y=e.clientY, code=td.dataset.code, name=td.dataset.name||'';
    clearTimeout(openTimer);
    openTimer=setTimeout(()=>{ placePop(x,y); openPop(); showChart(code,name); },60);
  });
  hot.addEventListener('mouseleave',()=>{ clearTimeout(openTimer); scheduleClose(); });
  hot.addEventListener('click',e=>{
    if(window.matchMedia('(hover: none)').matches || window.innerWidth<=767){
      e.stopPropagation(); cancelClose(); clearTimeout(openTimer);
      openPop(); pinned=true; showChart(td.dataset.code, td.dataset.name||'');
    }
  });
});
document.addEventListener('click',e=>{
  if((window.matchMedia('(hover: none)').matches||window.innerWidth<=767)
     && pop.style.display==='block' && !pop.contains(e.target)) closePop();
});
window.addEventListener('resize',()=>{
  if(curCode && pop.style.display==='block'){
    const t=document.querySelector('td[data-code="'+curCode+'"]');
    showChart(curCode, t? (t.dataset.name||''):'');
  }
});
"""
    chart_js = (chart_js.replace("__OHLCV__", ohlcv_json)
                        .replace("__KOSPI_D__", kospi_daily_json)
                        .replace("__TRACK_D__", track_json))
    return (popup_html
            + '\n<script src="lib/lightweight-charts.standalone.production.js"></script>\n'
            + '<script>\n(function(){\n' + chart_js + '\n})();\n</script>')


def update_leader_tracking_150(leader_list):
    """
    주도주 리스트(JSON)에서 종목 추출 → leader_tracking_150.json에 누적 저장.
    - 최초 등장 날짜(added_date) 기록
    - 14일(2주) 이상 지난 항목 자동 삭제
    - 동일 ticker 중복 추가 안 함 (최초 날짜 유지)
    - 휴장일에는 갱신하지 않고 직전 거래일 상태를 그대로 반환
      (휴장일엔 주도주 리스트가 비어 나와 트래킹이 통째로 지워지던 문제 방지)
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    if LEADER_TRACKING_JSON.exists():
        try:
            tracking = json.loads(LEADER_TRACKING_JSON.read_text(encoding="utf-8"))
        except Exception:
            tracking = {}
    else:
        tracking = {}

    if not is_kr_trading_day(today_str):
        print(f"[휴장일] {today_str} — KR150 주도주 트래킹 갱신 생략, "
              f"직전 거래일({last_kr_trading_day(today_str)}) 상태 유지 ({len(tracking)}종목)")
        return tracking

    # 14일 지난 항목 제거
    tracking = {k: v for k, v in tracking.items() if v.get("added_date", "") >= cutoff}

    # 오늘 종가 로드 (base_close 저장용)
    today_close_dict = {}
    if CLOSE_FILE.exists():
        try:
            today_close_dict = json.loads(CLOSE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    for item in leader_list:
        ticker = item.get('ticker', '').strip()
        if not ticker:
            continue
        name       = item.get('name', '')
        pct        = f"{item.get('change', 0):+.2f}%"
        closest_ma = item.get('closest_ma', '-')
        nxt_val    = item.get('nxt', '')
        tv_raw     = item.get('trade_amount', 0)
        tv_str     = f"{tv_raw/100_000_000:,.0f}억" if isinstance(tv_raw, (int, float)) and tv_raw > 0 else '-'

        if ticker not in tracking:
            base_close = today_close_dict.get(ticker, None)
            tracking[ticker] = {
                "name": name,
                "added_date": today_str,
                "closest_ma": closest_ma,
                "nxt": nxt_val,
                "tv_str": tv_str,
                "base_close": base_close,
                "pct_history": {},
            }
        tracking[ticker]["pct_history"][today_str] = pct
        tracking[ticker]["tv_str"] = tv_str  # 항상 최신값으로 갱신
        if not tracking[ticker].get("name"):
            tracking[ticker]["name"] = name
        if tracking[ticker].get("nxt", "") == "" and nxt_val:
            tracking[ticker]["nxt"] = nxt_val

    try:
        LEADER_TRACKING_JSON.write_text(
            json.dumps(tracking, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠ leader_tracking_150.json 저장 실패: {e}")

    return tracking


def normalize_tracking_dates_to_ohlcv(tracking: dict, ohlcv: dict) -> bool:
    """
    등록일이 휴장일이면 차트에 존재하는 직전 거래일로 보정한다.
    벽시계 실행일이 아니라 실제 신호 캔들 날짜에 라임 배경을 찍기 위함.
    """
    all_dates = sorted({row[0] for rows in ohlcv.values() for row in rows if row})
    if not all_dates:
        return False

    changed = False
    for ticker, info in tracking.items():
        added_date = info.get("added_date")
        if not added_date or added_date in all_dates:
            continue

        prev_dates = [d for d in all_dates if d <= added_date]
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


def build_leader_tracking_table(tracking: dict) -> str:
    """
    2주 이내 주도주 트래킹 테이블 HTML 생성
    컬럼: Ticker | Name | 이평 | 등록시 등락률 | 오늘 등락률 | 누적 등락률 | 당일합계 | N일합계 | 경과일
    """
    if not tracking:
        return '<p style="color:#95a5a6; margin-left:10px;">(트래킹 종목 없음)</p>'

    today_str = datetime.now().strftime("%Y-%m-%d")
    rows_html = []

    # 오늘 종가 로드 (누적 등락률 계산용)
    today_close_dict = {}
    if CLOSE_FILE.exists():
        try:
            today_close_dict = json.loads(CLOSE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Actual daily percent changes for all Korean tickers.
    today_pct_dict = {}
    if PCT_FILE.exists():
        try:
            today_pct_dict = json.loads(PCT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 외인/기관 합산 데이터 로드
    investor_dict = {}
    if INVESTOR_FILE.exists():
        try:
            investor_dict = json.loads(INVESTOR_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    def investor_cell(val, label=""):
        if val is None:
            return f'<td style="color:#aaa;font-size:11px;">-</td>'
        color = "#c0392b" if val > 0 else ("#2471a3" if val < 0 else "#888")
        sign = "+" if val > 0 else ""
        text = f"{sign}{val:,.0f}억"
        if label:
            text += f'<span style="color:#aaa;font-size:10px;"> ({label})</span>'
        return f'<td style="color:{color};font-size:12px;font-weight:bold;">{text}</td>'

    def cum_pct_cell(base_close, today_close):
        try:
            if base_close and today_close and float(base_close) > 0:
                cum = (float(today_close) / float(base_close) - 1) * 100
                sign = '+' if cum >= 0 else ''
                cls = 'up' if cum > 0 else ('down' if cum < 0 else '')
                return f'<td class="{cls}"><b>{sign}{cum:.2f}%</b></td>'
        except Exception:
            pass
        return '<td style="color:#aaa;">-</td>'

    sorted_items = sorted(tracking.items(), key=lambda x: x[1].get("added_date", ""), reverse=True)

    for ticker, info in sorted_items:
        added_date  = info.get("added_date", "-")
        name        = info.get("name", "")
        closest_ma  = info.get("closest_ma", "-")
        pct_history = info.get("pct_history", {})
        base_close  = info.get("base_close", None)

        try:
            days_passed = (datetime.now() - datetime.strptime(added_date, "%Y-%m-%d")).days
        except Exception:
            days_passed = 0

        if days_passed <= 5:
            days_color = "#27ae60"
        elif days_passed <= 10:
            days_color = "#e67e22"
        else:
            days_color = "#e74c3c"

        first_pct = pct_history.get(added_date, "-")
        today_pct = today_pct_dict.get(ticker, "-")
        if today_pct == "-":
            today_pct = pct_history.get(today_str, "-")
        if today_pct == "-" and pct_history:
            today_pct = pct_history.get(max(pct_history.keys()), "-")
        today_close = today_close_dict.get(ticker, None)

        # 외인/기관 합산
        ticker6 = ticker.zfill(6)
        inv = investor_dict.get(ticker6, {})
        inv_today = inv.get("today")
        inv_ndays = inv.get("ndays")
        inv_days  = inv.get("days", days_passed)

        def pct_cell(pct_str):
            try:
                val = float(pct_str.replace('%', '').replace('+', ''))
                cls = 'up' if val > 0 else ('down' if val < 0 else '')
                return f'<td class="{cls}">{html.escape(pct_str)}</td>'
            except Exception:
                return f'<td style="color:#aaa;">{html.escape(pct_str)}</td>'

        ma_color = {'MA10': '#3498db', 'MA20': '#9b59b6', 'MA60': '#e67e22'}.get(closest_ma, '#555')
        ma_cell = (f'<td><span style="background:{ma_color};color:white;padding:2px 6px;'
                   f'border-radius:4px;font-size:11px;font-weight:bold;">{html.escape(closest_ma)}</span></td>')

        expire_in = 14 - days_passed
        nxt_val = info.get("nxt", "")
        nxt_cls = 'nxt-badge-both' if nxt_val == 'NXT선' else 'nxt-badge'
        nxt_html = f'<span class="{nxt_cls}">{nxt_val}</span>' if nxt_val in ('NXT', '선', 'NXT선') else ''

        tv_str_val = info.get("tv_str", "-")
        try:
            tv_num = int(tv_str_val.replace(',', '').replace('억', '').strip())
            tv_color = '#e74c3c' if tv_num >= 1000 else '#222'
            tv_weight = 'bold' if tv_num >= 1000 else 'normal'
        except Exception:
            tv_color = '#222'
            tv_weight = 'normal'

        short_date = added_date[5:] if len(added_date) == 10 else added_date
        rows_html.append(
            f'<tr>'
            f'<td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker)}</td>'
            f'<td class="name-col">{html.escape(name)}</td>'
            f'<td style="color:#222;font-size:12px;">{html.escape(short_date)}</td>'
            f'{ma_cell}'
            f'{pct_cell(first_pct)}'
            f'{pct_cell(today_pct)}'
            f'{cum_pct_cell(base_close, today_close)}'
            f'{investor_cell(inv_today)}'
            f'{investor_cell(inv_ndays, f"{inv_days}일")}'
            f'<td style="color:{days_color};font-weight:bold;font-size:12px;">{days_passed}일 경과 (D-{expire_in})</td>'
            f'<td style="color:{tv_color};font-size:12px;font-weight:{tv_weight};">{html.escape(tv_str_val)}</td>'
            f'<td class="nxt-cell">{nxt_html}</td>'
            f'</tr>'
        )

    if not rows_html:
        return '<p style="color:#95a5a6; margin-left:10px;">(트래킹 종목 없음)</p>'

    header = (
        '<thead><tr>'
        '<th>Ticker</th><th>Name</th><th>등록일</th>'
        '<th>이평</th><th>등록시 등락률</th><th>오늘 등락률</th><th>누적 등락률</th>'
        '<th>당일합계</th><th>N일합계</th>'
        '<th>경과</th><th>거래대금</th><th class="nxt-header">NXT선</th>'
        '</tr></thead>'
    )
    return (
        f'<table class="styled-table">{header}'
        f'<tbody>{"".join(rows_html)}</tbody></table>'
    )


def build_leader_table(leader_list):
    """주도주 테이블 (오늘 발생분만)"""
    if not leader_list:
        return '<p style="color:#95a5a6; margin-left:10px;">(없음)</p>'

    rows = []
    for item in leader_list:
        ticker     = item.get('ticker', '')
        name       = item.get('name', '')
        change     = item.get('change', 0)
        tv         = item.get('trade_amount', 0)
        intensity  = item.get('intensity', False)
        closest_ma = item.get('closest_ma', '-')
        nxt        = item.get('nxt', '')

        ticker_display = f"{ticker}**" if intensity else ticker
        c_cls    = 'up' if change > 0 else ('down' if change < 0 else '')
        tv_str   = f'{tv/100_000_000:.0f}억'
        nxt_cls = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_html = f'<span class="{nxt_cls}">{nxt}</span>' if nxt in ('NXT', '선', 'NXT선') else ''
        ma_color = {'MA10': '#3498db', 'MA20': '#9b59b6', 'MA60': '#e67e22'}.get(closest_ma, '#555')
        ma_cell  = (f'<td><span style="background:{ma_color};color:white;padding:2px 6px;'
                    f'border-radius:4px;font-size:11px;font-weight:bold;">{html.escape(closest_ma)}</span></td>')

        rows.append(
            f'<tr style="background:#fffde7;">'
            f'<td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker_display)}</td>'
            f'<td class="name-col">{html.escape(name)}</td>'
            f'<td class="{c_cls}">{change:+.2f}%</td>'
            f'{ma_cell}'
            f'<td style="color:#888;font-size:12px;">{tv_str}</td>'
            f'<td class="nxt-cell">{nxt_html}</td>'
            f'</tr>'
        )

    header = ('<thead><tr>'
              '<th>Ticker</th><th>Name</th><th>등락률</th>'
              '<th>이평</th><th>거래대금</th><th class="nxt-header">NXT선</th>'
              '</tr></thead>')
    return (f'<table class="styled-table">{header}'
            f'<tbody>{"".join(rows)}</tbody></table>')


def build_unified_signal_table(signals, gann_fire_set=None, gann_info_dict=None):
    """
    📊 신호 종목 랭킹 (SPOT / MOM / LIME / GREEN / GANN) 통합 테이블
    신호 순서: SPOT > MOM > LIME > GREEN > GANN, 그룹 내 거래대금 내림차순
    """
    if gann_fire_set is None:
        gann_fire_set = set()
    if gann_info_dict is None:
        gann_info_dict = {}

    target_types = {'SPOT', 'MOM', 'LIME', 'GREEN'}
    filtered = [s for s in signals if s.get('type') in target_types]

    sig_order = {'SPOT': 0, 'MOM': 1, 'LIME': 2, 'GREEN': 3, 'GANN': 4}
    filtered = sorted(filtered, key=lambda x: (sig_order.get(x.get('type', ''), 9), -x.get('trade_amount', 0)))

    badge_css = {
        'SPOT':  'background:#e74c3c;color:white;',
        'MOM':   'background:#e67e22;color:white;',
        'LIME':  'background:#2ecc71;color:white;',
        'GREEN': 'background:#27ae60;color:white;',
        'GANN':  'background:#2980b9;color:white;',
    }

    # 기존 신호 행의 티커 목록
    existing_tickers = {s.get('ticker', '').zfill(6) for s in filtered}

    rows = []
    for s in filtered:
        sig_type  = s.get('type', '')
        ticker    = s.get('ticker', '')
        name      = s.get('name', '')
        change    = s.get('change', 0)
        tv        = s.get('trade_amount', 0)
        intensity = s.get('intensity', False)
        nxt       = s.get('nxt', '')

        ticker_display = f"{ticker}**" if intensity else ticker
        bstyle = badge_css.get(sig_type, '')
        badge  = (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                  f'font-size:11px;font-weight:bold;{bstyle}">{html.escape(sig_type)}</span>')

        # 🔥 GANN 신호 병기: 기존 신호 행에 GANN badge 추가
        if ticker.zfill(6) in gann_fire_set:
            gann_bstyle = badge_css['GANN']
            gann_badge = (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                          f'font-size:11px;font-weight:bold;{gann_bstyle}">GANN</span>')
            badge = badge + '&nbsp;' + gann_badge

        c_cls   = 'up' if change > 0 else ('down' if change < 0 else '')
        tv_str  = f'{tv/100_000_000:.0f}억'
        nxt_cls = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_cell = f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt}</span></td>' if nxt in ('NXT', '선', 'NXT선') else '<td class="nxt-cell"></td>'
        row_bg  = ' style="background:#fffde7;"' if sig_type == 'SPOT' else ''

        rows.append(
            f'<tr{row_bg}>'
            f'<td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker_display)}</td>'
            f'<td class="name-col">{html.escape(name)}</td>'
            f'<td>{badge}</td>'
            f'<td class="{c_cls}">{change:+.2f}%</td>'
            f'<td style="color:#888;font-size:12px;">{tv_str}</td>'
            f'{nxt_cell}'
            f'</tr>'
        )

    # 🔥 GANN 단독 종목 (기존 신호에 없는 것) 별도 행 추가 - 상세정보 포함
    for t6 in sorted(gann_fire_set):
        if t6 not in existing_tickers:
            info      = gann_info_dict.get(t6, {})
            tv_val    = info.get('trade_amount', 0)
            tv_str    = f'{tv_val/100_000_000:.0f}억' if tv_val > 0 else '-'
            nxt_val   = info.get('nxt', '')
            nxt_cls   = 'nxt-badge-both' if nxt_val == 'NXT선' else 'nxt-badge'
            nxt_cell  = (f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt_val}</span></td>'
                         if nxt_val in ('NXT', '선', 'NXT선') else '<td class="nxt-cell"></td>')
            bstyle    = badge_css['GANN']
            badge     = (f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                         f'font-size:11px;font-weight:bold;{bstyle}">GANN</span>')
            # GANN gap: 종가/val - 1 (%)
            gann_gap  = info.get('gann_gap', None)
            if gann_gap is not None:
                gap_cls  = 'up' if gann_gap > 0 else ('down' if gann_gap < 0 else '')
                gap_cell = f'<td class="{gap_cls}">{gann_gap:+.1f}%</td>'
            else:
                gap_cell = '<td style="color:#aaa;">-</td>'
            rows.append(
                f'<tr style="background:#eaf4fb;">'
                f'<td class="narrow" data-code="{html.escape(t6)}" data-name="{html.escape(info.get("name", ""))}">{html.escape(t6)}</td>'
                f'<td class="name-col">{html.escape(info.get("name", ""))}</td>'
                f'<td>{badge}</td>'
                f'{gap_cell}'
                f'<td style="color:#888;font-size:12px;">{tv_str}</td>'
                f'{nxt_cell}'
                f'</tr>'
            )

    header = ('<thead><tr>'
              '<th>Ticker</th><th>Name</th><th>신호</th>'
              '<th>등락률(Gap)</th><th>거래대금</th>'
              '<th class="nxt-header">NXT선</th>'
              '</tr></thead>')
    return (f'<table class="styled-table" id="unifiedSignalTable">{header}'
            f'<tbody>{"".join(rows)}</tbody></table>')


def build_red_signal_table(red_signals):
    """RED/PURPLE short candidates: futures-eligible names only, RED first."""
    red_list = [s for s in red_signals if s.get('nxt') in ('선', 'NXT선')]
    sig_order = {'RED': 0, 'PURPLE': 1}
    red_list = sorted(red_list, key=lambda x: (sig_order.get(x.get('type'), 9), -x.get('trade_amount', 0)))

    rows = []
    for s in red_list:
        sig_type = s.get('type', 'RED')
        ticker = s.get('ticker', '')
        name   = s.get('name', '')
        tv     = s.get('trade_amount', 0)
        nxt    = s.get('nxt', '')

        badge_color = '#c0392b' if sig_type == 'RED' else '#8e44ad'
        badge = ('<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                 f'font-size:11px;font-weight:bold;background:{badge_color};color:white;">{html.escape(sig_type)}</span>')
        tv_str = f'{tv/100_000_000:,.0f}억'
        nxt_cls = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_cell = f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt}</span></td>'

        rows.append(
            '<tr>'
            f'<td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker)}</td>'
            f'<td class="name-col">{html.escape(name)}</td>'
            f'<td>{badge}</td>'
            '<td style="color:#aaa;">-</td>'
            f'<td style="color:#888;font-size:12px;">{tv_str}</td>'
            f'{nxt_cell}'
            '</tr>'
        )

    if not rows:
        rows.append('<tr><td colspan="6" style="color:#95a5a6;text-align:center;">RED/PURPLE 선물 가능 종목 없음</td></tr>')

    header = ('<thead><tr>'
              '<th>Ticker</th><th>Name</th><th>신호</th>'
              '<th>등락률(Gap)</th><th>거래대금</th>'
              '<th class="nxt-header">NXT선</th>'
              '</tr></thead>')
    return (f'<table class="styled-table" id="redSignalTable">{header}'
            f'<tbody>{"".join(rows)}</tbody></table>')


def build_spot_table(signals):
    """SPOT 신호 전용 테이블 — 거래대금 내림차순"""
    spot_list = [s for s in signals if s.get('type') == 'SPOT']
    if not spot_list:
        return '<p style="color:#95a5a6; margin-left:10px;">(SPOT 신호 없음)</p>'

    spot_list = sorted(spot_list, key=lambda x: x.get('trade_amount', 0), reverse=True)

    rows = []
    for s in spot_list:
        ticker = s.get('ticker', '')
        name   = s.get('name', '')
        change = s.get('change', 0)
        tv     = s.get('trade_amount', 0)
        nxt    = s.get('nxt', '')

        c_cls    = 'up' if change > 0 else ('down' if change < 0 else '')
        nxt_cls = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_cell = f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt}</span></td>' if nxt in ('NXT', '선', 'NXT선') else '<td class="nxt-cell"></td>'
        tv_str   = f'{tv/100_000_000:.0f}억'

        rows.append(f"""<tr>
          <td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker)}</td>
          <td class="name-col">{html.escape(name)}</td>
          <td class="{c_cls}">{change:+.2f}%</td>
          <td style="color:#888; font-size:12px;">{tv_str}</td>
          {nxt_cell}
        </tr>""")

    return f"""<table class="styled-table" id="spotTable">
<thead><tr>
  <th>Ticker</th><th>Name</th><th>등락률</th><th>거래대금</th>
  <th class="nxt-header" onclick="sortByNXT('spotTable')" title="클릭하여 NXT 정렬">NXT선 ▲▼</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""


def build_signal_table(signals):
    """정배+거래대금 신호 테이블 — SPOT 제외, 거래대금 내림차순 max5"""
    other_list = [s for s in signals if s.get('type') != 'SPOT']
    if not other_list:
        return '<p style="color:#95a5a6; margin-left:10px;">(신호 없음)</p>'

    other_list = sorted(other_list, key=lambda x: x.get('trade_amount', 0), reverse=True)[:5]

    sig_colors = {
        'MOM': 'sig-red', 'LIME': 'sig-green',
        'GREEN': 'sig-green', 'JUNG': 'sig-orange'
    }

    rows = []
    for s in other_list:
        sig_type = s.get('type', '')
        ticker   = s.get('ticker', '')
        name     = s.get('name', '')
        change   = s.get('change', 0)
        tv       = s.get('trade_amount', 0)
        nxt      = s.get('nxt', '')

        sig_cls  = sig_colors.get(sig_type, '')
        c_cls    = 'up' if change > 0 else ('down' if change < 0 else '')
        nxt_cls = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_cell = f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt}</span></td>' if nxt in ('NXT', '선', 'NXT선') else '<td class="nxt-cell"></td>'
        tv_str   = f'{tv/100_000_000:,.0f}억'

        rows.append(f"""<tr>
          <td><b class="{sig_cls}">{html.escape(sig_type)}</b></td>
          <td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker)}</td>
          <td class="name-col">{html.escape(name)}</td>
          <td class="{c_cls}">{change:+.2f}%</td>
          <td style="color:#222; font-size:12px;">{tv_str}</td>
          {nxt_cell}
        </tr>""")

    return f"""<table class="styled-table" id="signalTable">
<thead><tr>
  <th>신호</th><th>Ticker</th><th>Name</th><th>등락률</th><th>거래대금</th>
  <th class="nxt-header" onclick="sortByNXT('signalTable')" title="클릭하여 NXT 정렬">NXT선 ▲▼</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""


def build_top30_table(top30, rank_maps=None, gann_fire_set=None, high52w_set=None, investor_dict=None):
    if not top30:
        return '<p style="color:#95a5a6;">(Top30 데이터 없음)</p>'

    if gann_fire_set is None:
        gann_fire_set = set()
    if high52w_set is None:
        high52w_set = set()
    if investor_dict is None:
        investor_dict = {}

    def investor_cell(val, label=""):
        if val is None:
            return '<td style="color:#aaa;font-size:11px;">-</td>'
        color = "#c0392b" if val > 0 else ("#2471a3" if val < 0 else "#888")
        sign = "+" if val > 0 else ""
        text = f"{sign}{val:,.0f}억"
        if label:
            text += f'<span style="color:#aaa;font-size:10px;"> ({label})</span>'
        return f'<td style="color:{color};font-size:12px;font-weight:bold;">{text}</td>'

    # rank_maps: {'d0': {ticker: rank}, 'd1': ..., 'd2': ..., 'd3': ...}
    rm0 = (rank_maps or {}).get('d0', {})
    rm1 = (rank_maps or {}).get('d1', {})
    rm2 = (rank_maps or {}).get('d2', {})
    rm3 = (rank_maps or {}).get('d3', {})

    def r2c(rank):
        """순위 숫자 → 표시 문자 (1~9, A~H, x)"""
        if rank is None:
            return '-'
        try:
            r = int(rank)
        except:
            return '-'
        if r <= 9:
            return str(r)
        if 10 <= r <= 17:
            return chr(ord('A') + (r - 10))
        return 'x'

    rows = []
    for s in top30:
        ticker     = s.get('ticker', '')
        name       = s.get('name', '')
        sig_sco    = s.get('signal_sco', 0)
        change     = s.get('change', 0)
        final_sco  = s.get('final_score', 0)
        new_sig    = s.get('new_sig', '-')
        high_vol   = s.get('high_vol', False)
        nxt        = s.get('nxt', '')
        tv_raw     = s.get('trade_amount', 0)
        tv_disp    = f"{tv_raw/100_000_000:,.0f}억" if isinstance(tv_raw, (int, float)) and tv_raw > 0 else '-'
        try:
            tv_num_top = int(tv_raw) // 100_000_000
            tv_color_top = '#e74c3c' if tv_num_top >= 1000 else '#222'
            tv_weight_top = 'bold' if tv_num_top >= 1000 else 'normal'
        except Exception:
            tv_color_top = '#222'
            tv_weight_top = 'normal'

        ticker_display = f"{ticker}**" if high_vol else ticker
        c_cls = 'up' if change > 0 else ('down' if change < 0 else '')

        # rank 히스토리 문자열 (d0d1d2d3)
        rr = (
            r2c(rm0.get(ticker)) +
            r2c(rm1.get(ticker)) +
            r2c(rm2.get(ticker)) +
            r2c(rm3.get(ticker))
        )
        name_with_rank = f"{name}({rr})"

        # 52주 신고가 근접 → 이름 빨간색
        ticker6 = ticker.zfill(6)
        name_html = (f'<span style="color:#e74c3c;font-weight:bold;">{html.escape(name_with_rank)}</span>'
                     if ticker6 in high52w_set else html.escape(name_with_rank))

        # 외인/기관 합산
        inv = investor_dict.get(ticker6, {})
        inv_today = inv.get("today")
        inv_ndays = inv.get("ndays")
        inv_days  = inv.get("days", 3)

        # Name 칼럼 녹색 조건 체크
        raw_ranks = [
            rm0.get(ticker),
            rm1.get(ticker),
            rm2.get(ticker),
            rm3.get(ticker),
        ]
        # 숫자로 변환 (없으면 None)
        int_ranks = [int(r) if r is not None else None for r in raw_ranks]

        # 조건1: is_rank_rising 로직
        def is_rank_rising(ranks):
            today_r, d1, d2, d3 = ranks

            # x/None 없어야 함
            if any(r is None for r in ranks):
                return False

            # 오늘 Top3이면 무조건 통과
            if today_r <= 3:
                return True

            # 앞 3자리(오늘, 전날, 전전날) 모두 5이내면 무조건 통과 (밀림 허용)
            if today_r <= 5 and d1 <= 5 and d2 <= 5:
                return True

            # 그 외: 순위 개선/유지 (오늘<=전날<=전전날<=전전전날)
            return today_r <= d1 and d1 <= d2 and d2 <= d3

        cond1 = is_rank_rising(int_ranks)

        # 조건2: 최근 4일 중 3일 이상이 top3(1,2,3)
        top3_count = sum(1 for r in int_ranks if r is not None and r <= 3)
        cond2 = top3_count >= 3

        name_cls = "name-col name-green" if (cond1 or cond2) else "name-col"

        # NewSig 배지
        if 'MOM' in new_sig:
            sig_badge = f'<span class="trend-badge trend-red">{html.escape(new_sig)}</span>'
        elif 'LIME' in new_sig:
            sig_badge = f'<span class="trend-badge trend-lime">{html.escape(new_sig)}</span>'
        elif 'GRN' in new_sig or 'GREEN' in new_sig:
            sig_badge = f'<span class="trend-badge trend-green">{html.escape(new_sig)}</span>'
        elif 'JUNG' in new_sig:
            sig_badge = f'<span class="trend-badge trend-lime">{html.escape(new_sig)}</span>'
        else:
            sig_badge = html.escape(new_sig)

        # 🔥 GANN 신호 병기: fire 필드 또는 gann_fire_set 둘 다 체크
        fire_val = s.get('fire', 0)
        is_gann = (fire_val == 1) or (ticker.zfill(6) in gann_fire_set)
        if is_gann:
            gann_badge = ('<span style="display:inline-block;padding:2px 6px;border-radius:4px;'
                          'font-size:11px;font-weight:bold;background:#2980b9;color:white;">🔥</span>')
            sig_badge = sig_badge + '&nbsp;' + gann_badge

        nxt_cls = 'nxt-badge-both' if nxt == 'NXT선' else 'nxt-badge'
        nxt_cell = f'<td class="nxt-cell"><span class="{nxt_cls}">{nxt}</span></td>' if nxt in ('NXT', '선', 'NXT선') else '<td class="nxt-cell"></td>'

        rows.append(f"""<tr>
          <td class="narrow" data-code="{html.escape(ticker)}" data-name="{html.escape(name)}">{html.escape(ticker_display)}</td>
          <td class="{name_cls}">{name_html}</td>
          <td>{sig_sco:.2f}</td>
          <td class="{c_cls}">{change:+.2f}%</td>
          {investor_cell(inv_today)}
          {investor_cell(inv_ndays, f"{inv_days}일")}
          <td>{round(final_sco * 100)}</td>
          <td>{sig_badge}</td>
          <td style="color:{tv_color_top};font-size:12px;font-weight:{tv_weight_top};">{html.escape(tv_disp)}</td>
          {nxt_cell}
        </tr>""")

    return f"""<table class="styled-table" id="top30Table">
<thead><tr>
  <th class="sortable" data-col="0">Ticker</th>
  <th class="sortable" data-col="1">Name</th>
  <th class="sortable" data-col="2">Sig_sco</th>
  <th class="sortable" data-col="3">등락률</th>
  <th class="sortable" data-col="4">당일합계</th>
  <th class="sortable" data-col="5">3일합계</th>
  <th class="sortable" data-col="6">Final_sco</th>
  <th class="sortable" data-col="7">NewSig</th>
  <th class="sortable" data-col="8">거래대금</th>
  <th class="nxt-header" onclick="sortByNXT('top30Table')" title="클릭하여 NXT 정렬">NXT선 ▲▼</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""


def build_market_temp_section(mt_data):
    """
    시장 온도 섹션 HTML 생성
    - 상단: 판정 뱃지 + 온도 게이지 + 수치
    - 하단 좌측: EMA5/EMA20 수치
    - 하단 우측: 60일 미니 스파크라인
    """
    if not mt_data:
        return '<p style="color:#95a5a6; font-size:0.85em;">(시장 온도 데이터 없음)</p>'

    today   = mt_data.get('today', 50)
    ema5    = mt_data.get('ema5', 50)
    ema20   = mt_data.get('ema20', 50)
    status  = mt_data.get('status', '-')
    dist    = mt_data.get('distribution', {})
    history = mt_data.get('history', [])

    H = dist.get('H', 0)
    W = dist.get('W', 0)
    N = dist.get('N', 0)
    C = dist.get('C', 0)
    T = dist.get('total', 1) or 1

    # 판정별 색상
    status_colors = {
        '상승 중':   ('#27ae60', '#eafaf1'),
        '회복 중':   ('#2980b9', '#eaf4fb'),
        '중립':      ('#7f8c8d', '#f2f3f4'),
        '하락 중':   ('#e67e22', '#fef9e7'),
        '침체 심화': ('#e74c3c', '#fdedec'),
    }
    s_color, s_bg = status_colors.get(status, ('#7f8c8d', '#f2f3f4'))

    # 게이지 색상 (온도에 따라)
    if today >= 55:
        gauge_color = '#27ae60'
    elif today >= 45:
        gauge_color = '#f39c12'
    elif today >= 35:
        gauge_color = '#e67e22'
    else:
        gauge_color = '#e74c3c'

    gauge_pct = round(today, 1)

    # 스파크라인 SVG (60일 히스토리)
    sparkline_svg = ''
    if len(history) >= 2:
        sw, sh = 260, 60
        mt_vals   = [h['MT']   for h in history]
        ema5_vals = [h['ema5'] for h in history]
        ema20_vals= [h['ema20']for h in history]

        all_vals = mt_vals + ema5_vals + ema20_vals
        vmin, vmax = min(all_vals), max(all_vals)
        vrange = (vmax - vmin) or 1

        def to_x(i, n): return round(sw * i / (n - 1), 1)
        def to_y(v):    return round(sh - (v - vmin) / vrange * (sh - 6) - 3, 1)

        n = len(history)

        def make_path(vals):
            pts = ' '.join(f'{to_x(i,n)},{to_y(v)}' for i, v in enumerate(vals))
            return f'<polyline points="{pts}" fill="none" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'

        # 중심선 50
        y50 = to_y(50) if vmin <= 50 <= vmax else -1
        center_line = f'<line x1="0" y1="{y50}" x2="{sw}" y2="{y50}" stroke="#bdc3c7" stroke-width="0.8" stroke-dasharray="3,3"/>' if y50 >= 0 else ''

        path_mt   = make_path(mt_vals).replace('<polyline', '<polyline stroke="#3498db"')
        path_ema5 = make_path(ema5_vals).replace('<polyline', '<polyline stroke="#27ae60"')
        path_ema20= make_path(ema20_vals).replace('<polyline', '<polyline stroke="#e74c3c"')

        sparkline_svg = f'''<svg width="{sw}" height="{sh}" viewBox="0 0 {sw} {sh}" style="display:block;">
  {center_line}
  {path_ema20}
  {path_ema5}
  {path_mt}
</svg>
<div style="font-size:10px; color:#999; margin-top:2px; display:flex; gap:10px;">
  <span style="color:#3498db;">● MT</span>
  <span style="color:#27ae60;">● EMA5</span>
  <span style="color:#e74c3c;">● EMA20</span>
  <span style="color:#bdc3c7;">— 50선</span>
</div>'''

    return f'''<div style="
      background:white; border-radius:8px; padding:12px 16px;
      box-shadow:0 4px 6px rgba(0,0,0,0.1); margin-bottom:14px;
      max-width:600px;">

  <!-- 1행: 타이틀 + 판정 뱃지 + 온도 수치 -->
  <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px; flex-wrap:wrap;">
    <span style="font-weight:bold; color:#2c3e50; font-size:0.95em;">🌡 시장 온도</span>
    <span style="background:{s_bg}; color:{s_color}; font-weight:bold;
                 padding:2px 10px; border-radius:12px; font-size:0.85em;
                 border:1px solid {s_color};">{html.escape(status)}</span>
    <span style="font-size:1.3em; font-weight:bold; color:{gauge_color};">{today:.1f}</span>
    <span style="color:#aaa; font-size:0.8em;">/ 100</span>
  </div>

  <!-- 게이지 바 -->
  <div style="background:#ecf0f1; border-radius:4px; height:8px; margin-bottom:10px; position:relative;">
    <div style="background:{gauge_color}; width:{gauge_pct}%; height:100%;
                border-radius:4px; transition:width 0.4s;"></div>
    <!-- 35, 45, 55 마커 -->
    <div style="position:absolute; left:35%; top:-3px; width:1px; height:14px; background:#bdc3c7;"></div>
    <div style="position:absolute; left:45%; top:-3px; width:1px; height:14px; background:#bdc3c7;"></div>
    <div style="position:absolute; left:55%; top:-3px; width:1px; height:14px; background:#bdc3c7;"></div>
  </div>

  <!-- 2행: 좌=EMA/분포, 우=스파크라인 -->
  <div style="display:flex; gap:20px; align-items:flex-start; flex-wrap:wrap;">

    <!-- 좌측 -->
    <div style="font-size:0.82em; color:#555; line-height:1.8; min-width:160px;">
      <div>EMA5 <b style="color:#27ae60;">{ema5:.1f}</b>
           &nbsp; EMA20 <b style="color:#e74c3c;">{ema20:.1f}</b></div>
      <div style="color:#999; font-size:0.95em;">
        H:<b>{H}</b>({H/T*100:.0f}%)
        W:<b>{W}</b>({W/T*100:.0f}%)
        N:<b>{N}</b>({N/T*100:.0f}%)
        C:<b>{C}</b>({C/T*100:.0f}%)
      </div>
    </div>

    <!-- 우측: 스파크라인 -->
    <div>
      {sparkline_svg if sparkline_svg else '<span style="font-size:0.8em;color:#aaa;">히스토리 누적 중...</span>'}
    </div>

  </div>
</div>'''


def main():
    data = {}
    if REPORT_JSON.exists():
        try:
            data = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠ JSON 읽기 실패: {e}")

    # ✅ 52주 신고가 95% 이상 종목 set 로드
    high52w_set = set()
    if HIGH52W_JSON.exists():
        try:
            high52w_set = set(json.loads(HIGH52W_JSON.read_text(encoding='utf-8')))
        except Exception:
            pass

    # ✅ 외인/기관 투자자 합산 데이터 로드
    investor_dict = {}
    if INVESTOR_FILE.exists():
        try:
            investor_dict = json.loads(INVESTOR_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass

    # 🔥 SGDDEMA 불기둥 신호 티커 세트 + 상세정보 로드
    gann_fire_set  = set()
    gann_info_dict = {}
    if GANN_FIRE_JSON.exists():
        try:
            gann_data = json.loads(GANN_FIRE_JSON.read_text(encoding='utf-8'))
            gann_fire_set  = set(str(t).strip().zfill(6) for t in gann_data.get('tickers', []))
            for t6, v in gann_data.get('info', {}).items():
                gann_info_dict[str(t6).strip().zfill(6)] = v
        except Exception:
            gann_fire_set  = set()
            gann_info_dict = {}

    signals     = data.get('signals', [])
    red_signals = data.get('red_signals', [])
    top30       = data.get('top30', [])
    leader_list = data.get('leader', [])
    summary     = data.get('summary', {})
    update_time = data.get('update_time', '')
    market_temp = data.get('market_temp', None)
    rank_maps   = data.get('rank_maps', {})
    now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    summary_text = (f"LIME:{summary.get('lime',0)} MOM:{summary.get('mom',0)} "
                    f"GREEN:{summary.get('green',0)} JUNG:{summary.get('jung',0)} "
                    f"SPOT:{summary.get('spot',0)} 주도주:{summary.get('leader',0)}")

    # 📊 SCO 기준 종목 분포 (KR전종목과 동일 포맷)
    sco_dist = data.get('sco_distribution', None)
    if sco_dist:
        _sd_total = sco_dist.get('total', 0)
        sco_dist_html = _sco_dist_bars(
            [
                ("sco ≥ 12", f'{sco_dist.get("strong", 0):,}',  f'{sco_dist.get("strong_pct", 0)}%',  "#2ecc71"),
                ("0 ~ 12",   f'{sco_dist.get("neutral", 0):,}', f'{sco_dist.get("neutral_pct", 0)}%', "#95a5a6"),
                ("sco < 0",  f'{sco_dist.get("weak", 0):,}',    f'{sco_dist.get("weak_pct", 0)}%',    "#e74c3c"),
            ],
            total=_sd_total,
            title="📊 SCO 기준 종목 분포",
        )
    else:
        sco_dist_html = ''

    # f-string 바깥에서 미리 계산 (내부 중괄호 충돌 방지)
    market_temp_html   = build_market_temp_section(market_temp)
    # 모바일 한 줄용
    _mt = market_temp or {}
    _mt_status = _mt.get('status', '-')
    _mt_today  = _mt.get('today')
    today_for_mobile  = f"{_mt_today:.1f}" if _mt_today is not None else "-"
    status_for_mobile = _mt_status
    _status_colors = {
        '상승 중':   ('#27ae60', '#eafaf1'),
        '회복 중':   ('#2980b9', '#eaf4fb'),
        '중립':      ('#7f8c8d', '#f2f3f4'),
        '하락 중':   ('#e67e22', '#fef9e7'),
        '침체 심화': ('#e74c3c', '#fdedec'),
    }
    _sc, _sbg = _status_colors.get(_mt_status, ('#7f8c8d', '#f2f3f4'))
    _gauge_color = '#27ae60' if (_mt_today or 0) >= 55 else ('#f39c12' if (_mt_today or 0) >= 45 else ('#e67e22' if (_mt_today or 0) >= 35 else '#e74c3c'))
    signal_table_html       = build_signal_table(signals)
    spot_table_html         = build_spot_table(signals)
    top30_table_html        = build_top30_table(top30, rank_maps=rank_maps, gann_fire_set=gann_fire_set, high52w_set=high52w_set, investor_dict=investor_dict)
    unified_signal_html     = build_unified_signal_table(signals, gann_fire_set=gann_fire_set, gann_info_dict=gann_info_dict)
    red_signal_html         = build_red_signal_table(red_signals)
    leader_table_html       = build_leader_table(leader_list)
    # 주도주 트래킹 업데이트 & 테이블
    tracking_data           = update_leader_tracking_150(leader_list)
    leader_tracking_html    = build_leader_tracking_table(tracking_data)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>KR 150 Report</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 20px; margin: 0; background-color: #f4f7f6;
}}
h2 {{
  margin-top: 30px; padding-bottom: 10px; color: #2c3e50;
  border-bottom: 2px solid #3498db;
}}
.signal-header {{
  margin-top: 15px; padding-bottom: 5px; color: #2c3e50;
  font-size: 1.1em; border-bottom: 1px solid #3498db;
}}
.styled-table {{
  width: auto; border-collapse: collapse; margin: 10px 0 20px 0;
  font-size: 13px; background: white;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden;
}}
.styled-table thead tr {{
  background: linear-gradient(135deg, #3498db, #2980b9);
  color: #ffffff; text-align: center;
}}
.styled-table th, .styled-table td {{
  padding: 8px 12px; border-bottom: 1px solid #f0f0f0;
  white-space: nowrap; text-align: center;
}}
.styled-table td.narrow {{ font-weight: bold; color: #2980b9; text-align: left; }}
.styled-table td.name-col {{ text-align: left; max-width: 150px; overflow: hidden; text-overflow: ellipsis; }}
.styled-table td.name-green {{ background-color: #eafaf1; color: #1e8449; font-weight: bold; }}
.rank-hist {{
  font-family: monospace; font-size: 12px; font-weight: bold;
  color: #8e44ad; letter-spacing: 1px; text-align: center;
}}

.up   {{ color: #27ae60; font-weight: bold; }}
.down {{ color: #e74c3c; font-weight: bold; }}
.sig-red    {{ color: #e74c3c; font-weight: bold; }}
.sig-green  {{ color: #27ae60; font-weight: bold; }}
.sig-orange {{ color: #f39c12; font-weight: bold; }}

.trend-badge {{
  padding: 2px 6px; border-radius: 4px; font-size: 10px;
  font-weight: bold; color: white; display: inline-block;
  min-width: 50px; text-align: center;
}}
.trend-lime  {{ background-color: #2ecc71; }}
.trend-green {{ background-color: #27ae60; }}
.trend-red   {{ background-color: #e74c3c; }}

/* 주도주 트래킹 헤더 */
.tracking-header {{
    margin-top: 10px;
    margin-bottom: 2px;
    padding-bottom: 4px;
    color: #8e44ad;
    font-size: 0.95em;
    border-bottom: 2px solid #8e44ad;
}}

/* NXT */
.nxt-header {{
  cursor: pointer; background-color: #2980b9 !important;
  user-select: none; text-align: center;
}}
.nxt-header:hover {{ background-color: #1a6a9a !important; }}
.nxt-cell {{ text-align: center; width: 50px; }}
.nxt-badge-both {{
  display: inline-block; padding: 2px 6px;
  background-color: #1a1a1a; color: white;
  border-radius: 4px; font-size: 11px; font-weight: bold;
}}
.nxt-badge {{
  display: inline-block; padding: 2px 6px;
  background-color: #8e44ad; color: white;
  border-radius: 4px; font-size: 11px; font-weight: bold;
}}

.top-nav-container {{ display: flex; margin-bottom: 12px; }}
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

@media (max-width: 480px) {{
  .mt-box-pc {{ display: none !important; }}
  .mt-box-mobile {{ display: block !important; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
/* === Naver Chart Popup (interactive / lightweight-charts) === */
#naverChartPopup {{
  display: none; position: fixed; z-index: 99999;
  width: min(1500px, 98vw); background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; max-height: 92vh; overflow-y: auto;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border: none;
  background: #e74c3c; color: white; border-radius: 50%;
  font-size: 18px; cursor: pointer; flex-shrink: 0;
}}
.popup-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
.popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; }}
.popup-link:hover {{ text-decoration: underline; }}
#popMs {{ font-size: 12px; color: #16a34a; font-weight: 700; font-family: monospace; }}
#stBtn {{ position: absolute; left: 14px; bottom: 12px; z-index: 20;
  width: 54px; height: 34px; flex-shrink: 0; cursor: pointer;
  border: 2px solid #7c3aed; background: #f5f3ff; color: #ef4444; font-weight: 800;
  font-size: 16px; line-height: 1; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.16); }}
#stBtn.on {{ background: #7c3aed; color: #fff; }}
#popBox {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; position: relative; }}
.col {{ display: flex; flex-direction: column; min-width: 0; position: relative; }}
/* 타임프레임 뱃지: 캔들차트 우측 끝 위(가격축 왼쪽)에 오버레이 */
.collab {{ position: absolute; top: 2px; right: 64px; z-index: 6; pointer-events: none; }}
.tfbadge {{ display: inline-block; min-width: 16px; padding: 1px 6px; border: 1px solid #9ca3af; border-radius: 4px; background: rgba(255,255,255,0.9); font-size: 12px; font-weight: 700; color: #374151; text-align: center; line-height: 1.35; }}
.rlab {{ font-size: 10px; color: #6b7280; padding: 3px 0 1px; }}
.cchart {{ width: 100%; height: 300px; }}
#colD .cchart {{ height: 300px; }}
.rchart {{ width: 100%; height: 100px; }}
.empty {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #991b1b; }}
td[data-code], td[data-code] + td.name-col {{ cursor: pointer; }}
td[data-code] + td.name-col:hover {{ background-color: #e8f4f8 !important; }}
@media (max-width: 900px) {{ #popBox {{ grid-template-columns: 1fr; }} }}
@media (max-width: 767px) {{
  #naverChartPopup {{ left: 2vw !important; top: 6vh !important; width: 96vw; max-height: 86vh; transform: none !important; }}
  #naverPopupClose {{ display: flex !important; }}
  .cchart {{ height: 225px; }} .rchart {{ height: 62px; }}
  #colD .cchart {{ height: 225px; }}
}}
</style>
</head>
<body>

<div class="top-nav-container">
  <div class="top-nav">
    <a href="kor_theme.html" class="nav-item">주도테마</a>
    <a href="kor_150.html" class="nav-item active">KR150</a>
    <a href="kor_stock.html" class="nav-item">KR전종목</a>
  </div>
</div>

<p style="margin: 0 0 5px 0; color: #555; font-size: 0.9em;">
  데이터: {html.escape(update_time)} &nbsp;|&nbsp; 페이지: {now}
</p>
<p style="margin: 0 0 15px 0; color: #7f8c8d; font-size: 0.85em;">{html.escape(summary_text)}</p>
{sco_dist_html}
<!-- PC: 기존 박스 그대로 -->
<div class="mt-box-pc">
{market_temp_html}
</div>
<!-- 모바일: 한 줄만 -->
<div class="mt-box-mobile" style="display:none; margin-bottom:10px;">
  <span style="font-weight:bold; color:#2c3e50; font-size:0.95em;">🌡 시장 온도</span>
  <span style="background:{_sbg}; color:{_sc}; font-weight:bold; padding:2px 8px; border-radius:10px; font-size:0.85em; border:1px solid {_sc}; margin-left:6px;">{html.escape(status_for_mobile)}</span>
  <span style="font-size:1.1em; font-weight:bold; color:{_gauge_color}; margin-left:6px;">{today_for_mobile}</span>
</div>
<h3 class="signal-header">🚀 SPOT 신호 <span style="font-size:0.67em; color:#000; font-weight:normal; margin-left:8px;">9개월 신고가 98% + 거래량 전일×10 & 5일평균×2.5 + 거래대금 1000억 + MA10/20/60 위</span></h3>
{spot_table_html}

<h2 style="margin-top:10px; border-bottom: 2px solid #e67e22; color:#e67e22;">📊 주도주 (오늘) <span style="font-size:0.67em; color:#000; font-weight:normal; margin-left:8px;">6개월 신고가 98% + 거래량 전일×8 OR 5일평균×2.5 + 거래대금 1000억 + MA10/20/60 위</span></h2>
{leader_table_html}

<h2 style="margin-top:10px; border-bottom: 2px solid #8e44ad; color:#8e44ad;">📊 주도주 트래킹 (2주) <span style="font-size:0.67em; color:#000; font-weight:normal; margin-left:8px;">오늘 주도주 발생 종목을 2주간 누적 추적</span></h2>
{leader_tracking_html}

<h2>📊 신호 종목 랭킹 (SPOT / MOM / LIME / GREEN / GANN)</h2>
{unified_signal_html}

<h3 class="signal-header">🚀 정배+거래대금 (Top5)</h3>
{signal_table_html}

<h2 style="margin-top:20px;">🏆 종합 Top 30 (Final Score) <span style="font-size:0.6em; font-weight:normal; color:#888;"><span style="color:#e74c3c;">빨강: 신고가근처</span> / <span style="color:#1e8449;">녹색배경: 순위 상승·상위권 유지</span></span></h2>
{top30_table_html}

<h2 style="margin-top:20px;">📊 신호 종목 랭킹 (RED / PURPLE)</h2>
{red_signal_html}

<script>
const nxtSortState = {{}};
function sortByNXT(tableId) {{
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  nxtSortState[tableId] = !nxtSortState[tableId];
  const asc = nxtSortState[tableId];
  rows.sort((a, b) => {{
    const aCells = a.querySelectorAll('td');
    const bCells = b.querySelectorAll('td');
    const aHas = aCells[aCells.length-1].innerText.trim() === 'NXT' ? 1 : 0;
    const bHas = bCells[bCells.length-1].innerText.trim() === 'NXT' ? 1 : 0;
    return asc ? aHas - bHas : bHas - aHas;
  }});
  rows.forEach(r => tbody.appendChild(r));
  const th = table.querySelector('.nxt-header');
  if (th) th.textContent = 'NXT ' + (asc ? '▲' : '▼');
}}
</script>
<script>
(function() {{
  var table = document.getElementById('top30Table');
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
    var n = parseFloat(str.replace(/[^0-9.\x2D]/g, ''));
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
}})();
</script>
__CHART_POPUP__

</body>
</html>
"""
    # ── 차트 데이터 내장 (네이버 PNG 팝업 → 인터랙티브 차트) ──────────
    codes = sorted(set(re.findall(r'data-code="([^"]+)"', page)))
    print(f"[CHART] hover 대상 {len(codes)}종목 OHLCV 수집 (병렬)")
    ohlcv = collect_ohlcv_kr(codes)
    empties = [c for c in codes if not ohlcv.get(c)]
    print("  누락:", (", ".join(empties) if empties else "0"))
    if normalize_tracking_dates_to_ohlcv(tracking_data, ohlcv):
        try:
            LEADER_TRACKING_JSON.write_text(
                json.dumps(tracking_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            fixed_tracking_html = build_leader_tracking_table(tracking_data)
            page = page.replace(leader_tracking_html, fixed_tracking_html)
            leader_tracking_html = fixed_tracking_html
        except Exception as e:
            print(f"  [TRACK] 등록일 보정 저장 실패: {e}")
    if not LIB_JS.exists():
        print(f"  [경고] 차트 라이브러리 없음: {LIB_JS}")
    ohlcv_json = json.dumps(ohlcv, separators=(",", ":"))
    try:
        from chart_popup_v2 import fetch_kospi_daily
        kospi_daily = fetch_kospi_daily()
        print(f"  [KOSPI일봉] {len(kospi_daily)}건 오버레이")
    except Exception as e:
        print(f"  [KOSPI일봉] chart_popup_v2 실패, fallback 시도: {e}")
        try:
            kospi_daily = fetch_kospi_daily_fallback()
            print(f"  [KOSPI일봉] {len(kospi_daily)}건 오버레이(fallback)")
        except Exception as e2:
            print(f"  [KOSPI일봉] 수집 실패(오버레이 생략): {e2}")
            kospi_daily = {}
    kospi_d_json = json.dumps(kospi_daily, ensure_ascii=False, separators=(",", ":"))
    track_dates = {str(t).zfill(6): [v["added_date"]]
                   for t, v in tracking_data.items() if v.get("added_date")}
    track_json = json.dumps(track_dates, ensure_ascii=False, separators=(",", ":"))
    from chart_popup_v4 import build_chart_popup as build_chart_popup_v4, move_kr_trigger_to_name as _mv2name
    page = _mv2name(page)  # 한국종목: 티커 대신 종목명에 hover → 차트
    page = page.replace(
        "__CHART_POPUP__",
        build_chart_popup_v4(
            codes,
            market="KR",
            trigger_attr="data-code",
            include_kospi=True,
            track_dates=track_dates,
        ),
    )

    OUT_HTML.write_text(page, encoding="utf-8")
    kb = len(page.encode("utf-8")) / 1024
    print(f"[OK] kor_150.html updated at {OUT_HTML}  ({kb:.0f} KB, 차트 {len(codes)}종목, 누락 {len(empties)})")


if __name__ == "__main__":
    main()
