# -*- coding: utf-8 -*-
"""
make_us_chart_display.py
- report_us_etf.txt, report_us_finviz.txt, report_us.txt 에서
  '주문용 Top4' 티커를 파싱하여 us_chart.html 생성
- 4행 x 4열 그리드. 각 셀 = V2 내장형 lightweight-charts (일봉 캔들 + RSI)
  1행: 고정 (SPY, QQQ, IWM, VX1!→VIX)
  2행: report_us_etf.txt Top4
  3행: report_us_finviz.txt Top4
  4행: report_us.txt Top4

V2 차트 = 생성 시 OHLCV(3년치)를 HTML 에 내장 → 즉시 렌더(네트워크 0).
MA 5/10/20/60/120 + 거래량 + RSI(14, Wilder) + 14이평 + 30/70선.
"""

import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "D:/py")
from coloryp_core import check_coloryp_logic

# ── 경로 설정 ────────────────────────────────────────────────────
BASE_DIR      = Path("D:/py/report-us")
OUT_HTML      = BASE_DIR / "us_chart.html"

TXT_ETF       = BASE_DIR / "report_us_etf.txt"
TXT_FINVIZ    = BASE_DIR / "report_us_finviz.txt"
TXT_US        = BASE_DIR / "report_us.txt"

YEARS_BACK    = 3          # 내장 데이터 기간 (MA120 + 휠 확대용)
MAX_WORKERS   = 8

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://finance.naver.com/"}
_SUFFIXES = [".O", ".K", ".P", "", ".N", ".A"]   # 미국 티커 탐색 순서

# ────────────────────────────────────────────────────────────────


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


def _sanitize_ohlc(rows):
    """네이버 피드의 단발성 깨진 값(소수점 오류 등) 보정.
    저가가 시·종가 대비 비정상적으로 낮으면(피드 글리치) 시·종가 최소값으로 클램프.
    고가가 비정상적으로 높으면 시·종가 최대값으로 클램프."""
    for r in rows:
        o, h, l, c = r[1], r[2], r[3], r[4]
        body_lo, body_hi = min(o, c), max(o, c)
        if l <= 0 or l < body_lo * 0.5:
            r[3] = body_lo
        if h > body_hi * 2:
            r[2] = body_hi


def fetch_foreign(ticker, s_ymd, e_ymd):
    """미국 티커: suffix 탐색 후 OHLCV 반환. (rows, resolved_symbol)"""
    for suf in _SUFFIXES:
        sym = ticker + suf
        try:
            data = json.loads(_fetch(
                f"https://api.stock.naver.com/chart/foreign/item/{sym}/day"
                f"?startDateTime={s_ymd}&endDateTime={e_ymd}"))
            if isinstance(data, list) and data:
                rows = [[f"{str(it['localDate'])[0:4]}-{str(it['localDate'])[4:6]}-{str(it['localDate'])[6:8]}",
                         float(it["openPrice"]), float(it["highPrice"]),
                         float(it["lowPrice"]), float(it["closePrice"]),
                         int(it.get("accumulatedTradingVolume", 0))]
                        for it in data]
                rows.sort(key=lambda x: x[0])
                _sanitize_ohlc(rows)
                return rows, sym
        except Exception:
            continue
    return [], ticker


def parse_top4(filepath: Path, section_name: str = "주문용 Top4") -> list[str]:
    """txt 파일에서 지정된 섹션의 티커 4개 추출"""
    tickers = []
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 파일 읽기 실패: {filepath} -> {e}")
        return tickers

    match = re.search(rf'=== {section_name}.*?\n(.*?)(?=\n\n|\n이전|\Z)', text, re.DOTALL)
    if not match:
        print(f"[WARN] '{section_name}' 섹션 없음: {filepath.name}")
        return tickers

    section = match.group(1)
    for line in section.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("Ticker"):
            continue
        token = line.split()[0]
        ticker = token.replace("**", "").replace("*", "").strip()
        if ticker:
            tickers.append(ticker)
        if len(tickers) >= 4:
            break

    print(f"[OK] {filepath.name} -> {tickers}")
    return tickers


def collect_ohlcv(charts):
    """charts: [{ticker,label,fetch,row}] → ohlcv{display->rows}, resolved{display->sym}"""
    end = date.today()
    start = end - timedelta(days=365 * YEARS_BACK + 15)
    s_ymd, e_ymd = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    # 중복 fetch 심볼 제거
    uniq = {}
    for c in charts:
        uniq.setdefault(c["fetch"], c["ticker"])

    def work(item):
        fetch_sym, _disp = item
        try:
            rows, sym = fetch_foreign(fetch_sym, s_ymd, e_ymd)
            return fetch_sym, rows, sym
        except Exception as e:
            print(f"  [ERR] {fetch_sym}: {e}")
            return fetch_sym, [], fetch_sym

    by_fetch = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for fetch_sym, rows, sym in ex.map(work, uniq.items()):
            by_fetch[fetch_sym] = (rows, sym)
            print(f"  {fetch_sym:<8} {len(rows):>4} bars  ({sym})")

    ohlcv, resolved = {}, {}
    for c in charts:
        rows, sym = by_fetch.get(c["fetch"], ([], c["fetch"]))
        ohlcv[c["ticker"]] = rows
        resolved[c["ticker"]] = sym
    return ohlcv, resolved


def add_trend_states(ohlcv):
    result = {}
    for ticker, rows in ohlcv.items():
        if not rows:
            result[ticker] = rows
            continue
        try:
            df = pd.DataFrame(
                rows, columns=["date", "open", "high", "low", "close", "volume"]
            )
            df["date"] = pd.to_datetime(df["date"])
            calc = check_coloryp_logic(df.set_index("date"))
            angle_all = (calc[[f"m{i}ang" for i in range(5)]] <= 0).all(axis=1)
            angle_4 = (calc[[f"m{i}ang" for i in range(4)]] <= 0).all(axis=1)
            is_lime = calc["lime_final"]
            is_green = (calc["HLv99"] >= 1) & (calc["HLv71"] == 1) & ~is_lime
            is_red = (
                ((calc["HLv99"] <= -1) & (calc["HLv7"] == -1) & (calc["HLv71"] == -1))
                | (calc["ang_sum"] == -5)
                | angle_all
            )
            is_purple = ((calc["HLv99"] <= -1) & (calc["HLv71"] == -1)) | angle_4
            states = np.select(
                [is_lime, is_green, is_red, is_purple],
                ["LIME", "GREEN", "RED", "PURPLE"],
                default="NONE",
            )
            cutoff = calc.index.max() - pd.DateOffset(months=2)
            result[ticker] = [
                list(row)
                + (
                    [str(states[i])]
                    if calc.index[i] >= cutoff and states[i] != "NONE"
                    else []
                )
                for i, row in enumerate(rows)
            ]
        except Exception as e:
            print(f"  [TREND BG] {ticker} calculation failed: {e}")
            result[ticker] = [list(row) for row in rows]
    return result


def build_html(rows_meta, ohlcv, resolved,
               title="시황 차트 (V2)",
               heading="📊 시황 차트 (V2 · 데이터 내장)",
               nav_html="", trend_background=False) -> str:
    """rows_meta: [{label, charts:[{ticker,label,fetch}]}, ...]
    title/heading/nav_html — make_kr_chart_display.py 등 다른 게시판에서 재사용용"""
    ohlcv_json = json.dumps(ohlcv, separators=(",", ":"))

    # 카드 그리드 HTML + 차트 렌더 순서 메타
    chart_order = []
    rows_html = []
    for row in rows_meta:
        cells = []
        for c in row["charts"]:
            idx = len(chart_order)
            sym = resolved.get(c["ticker"], c["ticker"])
            sub = f" [{sym}]" if sym and sym != c["ticker"] else ""
            fetch = str(c.get("fetch", c["ticker"]))
            is_kr = bool(fetch in ("KOSPI", "KOSDAQ") or re.fullmatch(r"\d{5}[0-9A-Z]", fetch))
            chart_order.append({"idx": idx, "ticker": c["ticker"], "isKr": is_kr})
            cells.append(
                f'<div class="chart-card">'
                f'<div class="chart-title">{c["label"]}'
                f'<span class="sub">{sub}</span>'
                f'<span class="ms" id="ms-{idx}"></span></div>'
                f'<div class="cwrap" id="card-{idx}">'
                f'<div class="chartbox"><div class="legend"></div><div class="cchart"></div></div>'
                f'<div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div>'
                f'<div class="rchart"></div>'
                f'</div></div>'
            )
        rows_html.append(
            f'<div class="row-label">{row["label"]}</div>'
            f'<div class="chart-grid">{"".join(cells)}</div>'
        )
    rows_html = "\n".join(rows_html)
    order_json = json.dumps(chart_order, separators=(",", ":"))

    js = r"""
const OHLCV = __OHLCV__;
const ORDER = __ORDER__;
const TREND_BG_ENABLED = __TREND_BG_ENABLED__;
const TREND_BG_COLORS={
  LIME:'rgba(0,230,118,0.15)',GREEN:'rgba(76,175,80,0.15)',
  PURPLE:'rgba(192,132,252,0.14)',RED:'rgba(251,113,133,0.13)',
  NONE:'rgba(255,255,255,0)'};

// 터치 기기에서는 세로 터치드래그를 차트가 가로채지 않게 해 페이지 스크롤이 되게 한다
const IS_TOUCH = window.matchMedia('(pointer: coarse)').matches;

// MA5=빨강 MA10=짙은회색 MA20=주황 MA60=녹색 MA120=검정
const MA_DEFS = [[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a'],[120,'#000000']];
const UP_COLOR='#f23645', DOWN_COLOR='#2962ff';
const VOL_UP='rgba(242,54,69,0.35)', VOL_DOWN='rgba(41,98,255,0.35)';
const RIGHT_PAD = 5;     // 차트 우측 여백(최근 캔들이 세로축에 붙지 않게)
const DEFAULT_BARS = 110; // 기본 표시 구간 (일봉 약 6개월 — 월 라벨 6개)
const ALL_CHARTS = [];    // [chart, el] — 윈도우 리사이즈 시 폭/높이 재적용
const ALL_PRIMS  = [];    // primitive requestUpdate 함수들 — 로드 후 일괄 강제 redraw
const krAxisFmt=p=>{
  const v=Math.round(p);
  return Math.abs(v)>=1000000 ? Math.round(v/1000).toLocaleString()+'K' : v.toLocaleString();
};
// 백만 이상은 38.4M 처럼 축약 — 가격축 라벨 폭이 줄어 차트 그리는 영역이 넓어진다
const millFmt=v=>{const s=(v/1e6).toFixed(1);return (s.endsWith('.0')?s.slice(0,-2):s)+'M';};
const usAxisFmt=p=>Math.abs(p)>=1e6 ? millFmt(p) : p.toFixed(2);
const krPriceFormat={type:'custom',minMove:1,formatter:krAxisFmt};
const usPriceFormat={type:'custom',minMove:0.01,formatter:usAxisFmt};

function sma(closes, p){
  const out=[]; let s=0;
  for(let i=0;i<closes.length;i++){ s+=closes[i]; if(i>=p)s-=closes[i-p];
    if(i>=p-1) out.push({i, value:+(s/p).toFixed(4)}); }
  return out;
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

// ── 캔들 옆 범례(날짜/종가/거래량/시가/고가/저가) — 거래대금 게시판과 동일 ──
const fmt = n => n.toFixed(2);
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
    if(!param.time||!param.point||!byKey.has(param.time)){ lg.style.display='none'; return; }
    paintLegend(lg,byKey.get(param.time),labelIdx); lg.style.display='block';
    const bw=lg.offsetWidth,bh=lg.offsetHeight;
    let lx=param.point.x-bw-14; if(lx<4)lx=param.point.x+14;
    let ly=param.point.y-bh/2; ly=Math.max(2,Math.min(ly,el.clientHeight-bh-2));
    lg.style.left=lx+'px'; lg.style.top=ly+'px';
  });
}

// ── 월 첫 거래일에 회색 세로 구분선을 캔버스에 직접 그리는 primitive ──
//    (줌/스크롤해도 매 프레임 다시 그려져 위치가 따라온다. 진하지 않은 회색)
function monthSeparator(chart, monthTimes){
  const view = {
    zOrder(){ return 'bottom'; },            // 캔들 뒤에 깔아 캔들 가림 최소화
    renderer(){
      return { draw(target){
        target.useBitmapCoordinateSpace(scope=>{
          const ctx=scope.context, ts=chart.timeScale();
          ctx.save();
          ctx.strokeStyle='rgba(150,150,150,0.40)';   // 적당히 연한 회색
          ctx.lineWidth=Math.max(1,Math.floor(scope.horizontalPixelRatio));
          for(const t of monthTimes){
            const x=ts.timeToCoordinate(t);
            if(x===null) continue;                     // 화면 밖이면 스킵
            const px=Math.round(x*scope.horizontalPixelRatio)+0.5;
            ctx.beginPath(); ctx.moveTo(px,0); ctx.lineTo(px,scope.bitmapSize.height); ctx.stroke();
          }
          ctx.restore();
        });
      }};
    }
  };
  let _req=null;
  return {
    // attach 직후엔 차트가 자동 redraw를 안 해 선이 안 보인다.
    // requestUpdate 를 모아뒀다가(ALL_PRIMS) 전체 로드 후 일괄 강제 갱신한다.
    attached(param){ _req=param.requestUpdate;
      if(_req){ ALL_PRIMS.push(_req); requestAnimationFrame(()=>_req&&_req()); } },
    detached(){ _req=null; },
    updateAllViews(){},
    paneViews(){ return [view]; }
  };
}
function firstOfMonthTimes(raw){
  const out=[]; let prev=null;
  for(const r of raw){ const m=String(r[0]).slice(0,7); if(m!==prev){ out.push(r[0]); prev=m; } }
  return out;
}

// 한 셀 = 일봉 캔들차트 + RSI차트, 시간축 동기화
function renderCard(card, raw, isKr){
  const candleEl = card.querySelector('.cchart');
  const rsiEl    = card.querySelector('.rchart');
  const times  = raw.map(r=>r[0]);
  const closes = raw.map(r=>r[4]);
  const priceFormat = isKr ? krPriceFormat : usPriceFormat;

  // ★ 디폴트 표시 구간(6개월)은 생성시 barSpacing 으로 고정해야 먹힌다.
  //   (생성 후 setVisibleLogicalRange/applyOptions 는 barSpacing 을 6 밑으로 못 줄여 ~40바에서 클램프됨)
  const initBS = Math.max(0.4, candleEl.clientWidth/(DEFAULT_BARS+RIGHT_PAD));

  const cChart = LightweightCharts.createChart(candleEl, {
    width:candleEl.clientWidth, height:candleEl.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.08,bottom:0.08}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,barSpacing:initBS,minBarSpacing:0.4,visible:false,
               timeVisible:false,secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    localization:{priceFormatter:isKr?krAxisFmt:usAxisFmt},
    handleScroll:{vertTouchDrag:!IS_TOUCH},
  });
  if(TREND_BG_ENABLED){
    const trendBand=cChart.addHistogramSeries({
      priceScaleId:'trendbg',base:0,priceLineVisible:false,lastValueVisible:false});
    cChart.priceScale('trendbg').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
    trendBand.setData(raw.filter(r=>(r[6]||'NONE')!=='NONE').map(r=>({
      time:r[0],value:1,color:TREND_BG_COLORS[r[6]]})));
  }
  const candle = cChart.addCandlestickSeries({
    upColor:UP_COLOR,downColor:DOWN_COLOR,borderUpColor:UP_COLOR,
    borderDownColor:DOWN_COLOR,wickUpColor:UP_COLOR,wickDownColor:DOWN_COLOR,
    priceFormat});
  candle.setData(raw.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
  const vol = cChart.addHistogramSeries({priceScaleId:'',
    priceFormat:{type:'custom',minMove:1,
      formatter:v=>Math.abs(v)>=1e6?millFmt(v):Math.round(v/1000).toLocaleString()+'K'}});
  vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
  vol.setData(raw.map(r=>({time:r[0],value:r[5],
    color:r[4]>=r[1]?VOL_UP:VOL_DOWN})));
  MA_DEFS.forEach(([p,color])=>{
    const ln=cChart.addLineSeries({color,lineWidth:1,priceLineVisible:false,
      priceFormat,autoscaleInfoProvider:()=>null,
      lastValueVisible:false,crosshairMarkerVisible:false});
    const mp=new Map(sma(closes,p).map(o=>[times[o.i],o.value]));
    ln.setData(times.map(t=> mp.has(t)? {time:t,value:mp.get(t)} : {time:t}));
  });

  // MagicTrend(10,3) ATR선 오버레이 — 2px 점선, 점별 색(CCI≥0 파랑/<0 빨강). 거래대금 팝업과 동일
  const _mt=magicTrend(raw,3,10,20);
  const mtData=raw.map((b,i)=> _mt.mt[i]==null? {time:b[0]}
    : {time:b[0],value:+_mt.mt[i].toFixed(2),color:_mt.up[i]?'#0022FC':'#ff5252'});
  const mtLine=cChart.addLineSeries({color:'#0022FC',lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,
    priceFormat,autoscaleInfoProvider:()=>null,
    lastValueVisible:false,crosshairMarkerVisible:false});
  mtLine.setData(mtData);

  // 월 구분선(회색 세로선) — 캔들/RSI 두 차트 모두
  const monthTimes = firstOfMonthTimes(raw);
  candle.attachPrimitive(monthSeparator(cChart, monthTimes));

  // 캔들 옆 범례 (날짜/OHLC/거래량) — 크로스헤어 이동 시 표시
  const lg = card.querySelector('.legend');
  if(lg) attachTooltip(cChart, candleEl, lg, new Map(raw.map(b=>[b[0],b])), 0);

  const rChart = LightweightCharts.createChart(rsiEl, {
    width:rsiEl.clientWidth, height:rsiEl.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#888',fontSize:10},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f7f7f7'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.12,bottom:0.12}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,barSpacing:initBS,minBarSpacing:0.4,
               timeVisible:false,secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    handleScroll:{vertTouchDrag:!IS_TOUCH},
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
  rsiLine.attachPrimitive(monthSeparator(rChart, monthTimes));

  // 기본 6개월 구간. setData 직후 동기 호출은 레이아웃 전이라 무시될 수 있어
  // requestAnimationFrame 으로 레이아웃 후 한 번 더 확정 적용한다.
  const n=raw.length, from=Math.max(0,n-DEFAULT_BARS), to=n-1+RIGHT_PAD;
  const applyRange=()=>{
    cChart.timeScale().setVisibleLogicalRange({from, to});
    rChart.timeScale().setVisibleLogicalRange({from, to});
  };
  applyRange();
  requestAnimationFrame(applyRange);

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

  ALL_CHARTS.push([cChart,candleEl],[rChart,rsiEl]);
}

function renderAll(){
  const t0=performance.now();
  let ok=0;
  ORDER.forEach(o=>{
    const card=document.getElementById('card-'+o.idx);
    const raw=OHLCV[o.ticker];
    const msEl=document.getElementById('ms-'+o.idx);
    if(!raw || !raw.length){
      card.innerHTML='<div class="empty">데이터 없음</div>';
      if(msEl) msEl.textContent='';
      return;
    }
    const c0=performance.now();
    renderCard(card, raw, !!o.isKr);
    if(msEl) msEl.textContent=(Math.round((performance.now()-c0)*10)/10)+'ms · '+raw.length+'bars';
    ok++;
  });
  document.getElementById('status').textContent=
    '✅ '+ok+'개 차트 즉시 렌더 ('+(Math.round((performance.now()-t0))) +'ms) · 휠=확대 드래그=이동';
  // 레이아웃 완전히 잡힌 뒤 월 구분선 primitive 일괄 강제 redraw (로드 직후 미표시 방지)
  const repaintPrims=()=>ALL_PRIMS.forEach(f=>{ try{ f&&f(); }catch(e){} });
  requestAnimationFrame(()=>requestAnimationFrame(repaintPrims));
  setTimeout(repaintPrims, 60);
  setTimeout(repaintPrims, 200);
}

window.addEventListener('load', renderAll);

// 윈도우 리사이즈 시에만 폭/높이 재적용 (로드 시점 visible range는 건드리지 않음)
let __rt=null;
window.addEventListener('resize', ()=>{
  clearTimeout(__rt);
  __rt=setTimeout(()=>{
    ALL_CHARTS.forEach(([ch,el])=>{ try{ch.applyOptions({width:el.clientWidth,height:el.clientHeight});}catch(e){} });
  },150);
});
"""
    js = (js.replace("__OHLCV__", ohlcv_json)
            .replace("__ORDER__", order_json)
            .replace("__TREND_BG_ENABLED__", "true" if trend_background else "false"))

    html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>__TITLE__</title>
<script src="lib/lightweight-charts.standalone.production.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background:#f0f2f5; font-family:-apple-system,'Malgun Gothic',sans-serif; padding:16px; color:#1f2937; }
  .top-nav-container { display:flex; margin-bottom:10px; }
  .top-nav { display:flex; background:#2c3e50; border-radius:8px; overflow:hidden; }
  .nav-item { padding:7px 14px; color:#bdc3c7; cursor:pointer; text-decoration:none; font-size:0.85em; font-weight:bold; transition:0.2s; }
  .nav-item:hover { background:#34495e; color:#fff; }
  .nav-item.active { background:#3498db; color:white; }
  h1 { margin-bottom:4px; font-size:16px; color:#333; }
  #status { font-size:12px; color:#16a34a; font-weight:700; margin-bottom:12px; }

  .row-label {
    font-size:12px; font-weight:bold; color:#555;
    margin:14px 0 6px 2px; padding-left:6px; border-left:3px solid #3498db;
  }
  .chart-grid {
    display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-bottom:4px;
  }
  /* 1열과 2열 사이만 살짝 더 벌림 (세로 스크롤 보기 편하게) */
  .chart-grid > .chart-card:nth-child(4n+2) { margin-left:22px; }
  .chart-card {
    background:#fff; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.08);
    overflow:hidden; min-width:0;
  }
  .chart-title {
    padding:7px 10px; font-size:13px; font-weight:bold; color:#444;
    border-bottom:1px solid #eee; display:flex; align-items:center; gap:6px; white-space:nowrap;
  }
  .chart-title .sub { font-size:10px; font-weight:normal; color:#999; }
  .chart-title .ms  { margin-left:auto; font-size:10px; font-weight:normal; color:#16a34a; font-family:monospace; }

  .cwrap { width:100%; }
  .chartbox { position:relative; }
  .legend { position:absolute; display:none; z-index:6; background:rgba(255,255,255,.96);
            border:1px solid #e5e7eb; border-radius:6px; padding:5px 8px; font-size:11px;
            line-height:1.5; color:#334155; pointer-events:none; min-width:150px;
            box-shadow:0 2px 8px rgba(0,0,0,.13); }
  .legend b { color:#0f172a; }
  .legend .k { display:inline-block; width:38px; color:#64748b; }
  .cchart { width:100%; height:300px; }
  .rlab   { font-size:10px; color:#6b7280; padding:3px 10px 1px; }
  .rchart { width:100%; height:150px; }
  .empty  { height:300px; display:flex; align-items:center; justify-content:center; color:#991b1b; font-size:12px; }

  /* 태블릿: 가로(열 개수)는 유지 — 가로 스크롤 */
  @media (max-width:1100px) and (min-width:769px) { body{overflow-x:auto;} .chart-grid{min-width:1000px;} }
  /* 스마트폰: 종목당 1개씩 세로 나열 + 우측 여백(차트 밖 터치로 페이지 스크롤) */
  @media (max-width:768px) {
    body { padding:10px 36px 10px 8px; }
    .chart-grid { grid-template-columns:1fr; min-width:0; gap:10px; }
    .chart-grid > .chart-card:nth-child(4n+2) { margin-left:0; }
    .cchart { height:260px; }
    .rchart { height:120px; }
  }
</style>
</head>
<body>
__NAV__
<h1>__HEADING__</h1>
<div id="status">렌더링 준비 중...</div>
__ROWS__

<script>
__JS__
</script>
</body>
</html>
""".replace("__ROWS__", rows_html).replace("__JS__", js)
    nav_block = (f"<div class='top-nav-container'><div class='top-nav'>{nav_html}</div></div>"
                 if nav_html.strip() else "")
    html = (html.replace("__TITLE__", title)
                .replace("__HEADING__", heading)
                .replace("__NAV__", nav_block))
    return html


def main():
    print("=" * 60)
    print("make_us_chart_display.py 실행 (V2 내장 차트)")
    print("=" * 60)

    # 1행: 고정 (VX1!은 네이버 VIX 미제공으로 제외)
    row1 = [
        {"ticker": "SPY",  "label": "SPY",  "fetch": "SPY",  "tv": None},
        {"ticker": "QQQ",  "label": "QQQ",  "fetch": "QQQ",  "tv": None},
        {"ticker": "IWM",  "label": "IWM",  "fetch": "IWM",  "tv": None},
    ]

    def to_charts(tickers):
        return [{"ticker": t, "label": t, "fetch": t, "tv": None} for t in tickers]

    row2 = to_charts(parse_top4(TXT_ETF, "US ETF Momentum Top"))
    row3 = to_charts(parse_top4(TXT_FINVIZ))
    row4 = to_charts(parse_top4(TXT_US))

    placeholder = {"ticker": "-", "label": "(없음)", "fetch": "-", "tv": None}
    for row in [row2, row3, row4]:
        while len(row) < 4:
            row.append(dict(placeholder))

    rows_meta = [
        {"label": "📌 주요 지수 / 변동성", "charts": row1},
        {"label": "🇺🇸 US ETF Top4",     "charts": row2},
        {"label": "📊 US Finviz Top4",    "charts": row3},
        {"label": "📈 US Stock Top4",     "charts": row4},
    ]

    all_charts = [c for row in rows_meta for c in row["charts"]
                  if c.get("fetch") and c["fetch"] != "-"]
    print("\n[OHLCV 수집]")
    ohlcv, resolved = collect_ohlcv(all_charts)
    ohlcv = add_trend_states(ohlcv)

    empties = [c["ticker"] for c in all_charts if not ohlcv.get(c["ticker"])]
    if empties:
        print(f"  [경고] 데이터 누락: {', '.join(empties)}")
    else:
        print("  [확인] 전 종목 데이터 정상 (누락 0)")

    lib = BASE_DIR / "lib" / "lightweight-charts.standalone.production.js"
    if not lib.exists():
        print(f"  [경고] 차트 라이브러리 없음: {lib}")

    html = build_html(rows_meta, ohlcv, resolved, trend_background=True)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    kb = len(html.encode("utf-8")) / 1024
    print(f"\n[OK] 저장 완료: {OUT_HTML}  ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
