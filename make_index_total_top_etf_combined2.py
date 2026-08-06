# -*- coding: utf-8 -*-
"""
make_index_total_top_etf_combined2.py   (TEST 전용 / 기존 파일 절대 미수정)
===========================================================================
목적: 통합ETF 게시판의 "차트 hover 로딩속도" 비교 테스트.

  기존  : total_etf_combined.html
          → hover 시 네이버 PNG(일봉/주봉)를 매번 네트워크로 받아옴
            (+ 미국은 suffix(.O/.P...) 탐색 라운드트립까지)
  이파일: total_etf_combined2.html
          → 생성 시점에 30종목 OHLCV(2년치)를 HTML 에 내장
            hover 시 네트워크 0, lightweight-charts 로 즉시 렌더(~10ms)
            MA 5/10/20/60/120 + 거래량 (RSI 제외)

기존 total_top30.csv 의 동일한 30종목을 그대로 사용 → 공정 비교.

실행:
  python report-us\\make_index_total_top_etf_combined2.py
"""

import csv
import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

BASE         = Path(__file__).resolve().parent          # D:\py\report-us
PROJECT_ROOT = BASE.parent                              # D:\py
CSV_FILE     = PROJECT_ROOT / "0txt" / "total_top30.csv"
OUT_HTML     = BASE / "total_etf_combined2.html"

YEARS_BACK = 3          # 내장 데이터 기간 (주봉 MA120 확보 위해 3년)
MAX_WORKERS = 8

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://finance.naver.com/"}
_SUFFIXES = [".O", ".K", ".P", "", ".N", ".A"]   # 미국 티커 탐색 순서


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


def is_kr(ticker: str) -> bool:
    """6자리 + 숫자 포함 → 한국 ETF (예: 069500, 0038A0)."""
    return len(ticker) == 6 and any(c.isdigit() for c in ticker) and ticker.isalnum()


def fetch_domestic(code, s_ymd, e_ymd):
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
                return rows, sym
        except Exception:
            continue
    return [], ticker


def fetch_minute5_kr(code):
    """국내 분봉(1분) → 5분봉 리샘플. (TEST: KR 당일 5분봉용)
    네이버는 당일치 1분봉만 제공(~381개), volume 은 분당(누적아님).
    시간은 KST localDateTime 을 그대로 UTC unix 초로 (차트 라벨 09:00~15:30).
    반환: [[unix_ts, o, h, l, c, v], ...] (5분 버킷, 시간오름차순)
    """
    url = f"https://api.stock.naver.com/chart/domestic/item/{code}/minute"
    try:
        data = json.loads(_fetch(url))
    except Exception:
        return []
    if not isinstance(data, list) or not data:
        return []
    buckets = {}  # bucket_ts -> [o,h,l,c,v]
    for it in data:
        s = str(it.get("localDateTime", ""))
        if len(s) < 12:
            continue
        try:
            Y, Mo, D = int(s[0:4]), int(s[4:6]), int(s[6:8])
            h, mi = int(s[8:10]), int(s[10:12])
            o = float(it["openPrice"]); hi = float(it["highPrice"])
            lo = float(it["lowPrice"]);  c = float(it.get("closePrice", it.get("currentPrice")))
            v = int(it.get("accumulatedTradingVolume", 0))
        except (KeyError, TypeError, ValueError):
            continue
        m5 = (mi // 5) * 5
        ts = int(datetime(Y, Mo, D, h, m5, tzinfo=timezone.utc).timestamp())
        b = buckets.get(ts)
        if not b:
            buckets[ts] = [o, hi, lo, c, v]
        else:
            b[1] = max(b[1], hi); b[2] = min(b[2], lo); b[3] = c; b[4] += v
    out = [[ts, b[0], b[1], b[2], b[3], b[4]] for ts, b in buckets.items()]
    out.sort(key=lambda x: x[0])
    return out


def load_rows():
    """total_top30.csv → [{ticker, name, chg, ret, trend, sco, final, rsi, is_kr}]"""
    out = []
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw = str(row.get("티커", "")).strip()
            if not raw:
                continue
            ticker = raw.replace("**", "")
            name = re.sub(r"\(.*\)$", "", str(row.get("산업", ""))).strip()
            out.append({
                "ticker": ticker,
                "name":   name or ticker,
                "chg":    row.get("당일등락률(%)", ""),
                "ret":    row.get("수익률(%)", ""),
                "trend":  row.get("추세", ""),
                "sco":    row.get("Signal_sco", ""),
                "final":  row.get("Final_score", ""),
                "rsi":    row.get("RSI_str", ""),
                "is_kr":  is_kr(ticker),
            })
    return out


def collect_ohlcv(items):
    end = date.today()
    start = end - timedelta(days=365 * YEARS_BACK + 15)
    s_ymd, e_ymd = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def work(it):
        tk = it["ticker"]
        try:
            if it["is_kr"]:
                rows = fetch_domestic(tk, s_ymd, e_ymd); sym = tk
                m5 = fetch_minute5_kr(tk)          # KR: 당일 5분봉(테스트)
            else:
                rows, sym = fetch_foreign(tk, s_ymd, e_ymd)
                m5 = []                            # US: 분봉 없음 → 주봉 유지
            return tk, rows, sym, m5
        except Exception as e:
            print(f"  [ERR] {tk}: {e}")
            return tk, [], tk, []

    result = {}
    resolved = {}
    min5 = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for tk, rows, sym, m5 in ex.map(work, items):
            result[tk] = rows
            resolved[tk] = sym
            min5[tk] = m5
            tag = "KR" if is_kr(tk) else "US"
            extra = f"  +{len(m5):>3} m5" if m5 else ""
            print(f"  {tag} {tk:<8} {len(rows):>4} bars  ({sym}){extra}")
    return result, resolved, min5


def build_html(items, ohlcv, resolved, min5):
    ohlcv_json = json.dumps(ohlcv, separators=(",", ":"))
    min5_json = json.dumps(min5, separators=(",", ":"))
    meta = [{"ticker": it["ticker"], "name": it["name"], "is_kr": it["is_kr"],
             "sym": resolved.get(it["ticker"], it["ticker"])} for it in items]
    meta_json = json.dumps(meta, ensure_ascii=False)

    # ── 표 행 ─────────────────────────────────────────
    trs = []
    for i, it in enumerate(items, 1):
        tag = "KR" if it["is_kr"] else "US"
        trs.append(
            "<tr>"
            f'<td class="num">{i}</td>'
            f'<td class="trig" data-ticker="{it["ticker"]}">'
            f'<span class="tk">{it["ticker"]}</span> '
            f'<span class="nm">{it["name"]}</span>'
            f'<span class="tag tag-{tag.lower()}">{tag}</span></td>'
            f'<td class="r">{it["chg"]}</td>'
            f'<td class="r">{it["ret"]}</td>'
            f'<td class="c">{it["trend"]}</td>'
            f'<td class="r">{it["sco"]}</td>'
            f'<td class="r">{it["final"]}</td>'
            f'<td class="c">{it["rsi"]}</td>'
            "</tr>"
        )
    rows_html = "\n".join(trs)

    js = r"""
const OHLCV = __OHLCV__;
const MIN5  = __MIN5__;
const META  = __META__;

// MA5=빨강 MA10=짙은회색 MA20=주황 MA60=녹색 MA120=검정
const MA_DEFS = [[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a'],[120,'#000000']];
const UP_COLOR='#f23645', DOWN_COLOR='#2962ff';
const VOL_UP='rgba(242,54,69,0.35)', VOL_DOWN='rgba(41,98,255,0.35)';
const RIGHT_PAD = 5;   // 차트 우측 여백(최근 캔들이 세로축에 붙지 않게)
const krAxisFmt=p=>{
  const v=Math.round(p);
  return Math.abs(v)>=1000000 ? Math.round(v/1000).toLocaleString()+'K' : v.toLocaleString();
};
const usAxisFmt=p=>p.toFixed(2);
const krPriceFormat={type:'custom',minMove:1,formatter:krAxisFmt};
const usPriceFormat={type:'custom',minMove:0.01,formatter:usAxisFmt};

function sma(closes, p){
  const out=[]; let s=0;
  for(let i=0;i<closes.length;i++){ s+=closes[i]; if(i>=p)s-=closes[i-p];
    if(i>=p-1) out.push({i, value:+(s/p).toFixed(4)}); }
  return out;
}

// 일봉 → 주봉 (월요일 기준 주 버킷)
function mondayOf(dstr){
  const d=new Date(dstr+'T00:00:00');
  const day=(d.getDay()+6)%7;            // 월=0
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

// Wilder RSI = TradingView ta.rsi(close,14)
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
// null 선행 허용 SMA (ta.sma(rsi,14))
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

const pop      = document.getElementById('pop');
const popTitle = document.getElementById('popTitle');
const popMs    = document.getElementById('popMs');
const popBox   = document.getElementById('popBox');
let charts=[], hoverTimer=null, pinned=false, curTicker=null;

function destroyChart(){ charts.forEach(c=>{try{c.remove();}catch(e){}}); charts=[]; }

// 한 컬럼(일봉/주봉/5분봉) = 캔들차트 + RSI차트, 시간축 동기화
// intraday=true → 시간축에 시:분 표시(timeVisible), time 은 unix 초
function buildColumn(col, raw, isKr, defaultBars, intraday){
  const candleEl = col.querySelector('.cchart');
  const rsiEl    = col.querySelector('.rchart');
  const times  = raw.map(r=>r[0]);
  const closes = raw.map(r=>r[4]);
  const priceFormat = isKr ? krPriceFormat : usPriceFormat;

  // 캔들 차트
  const cChart = LightweightCharts.createChart(candleEl, {
    width:candleEl.clientWidth, height:candleEl.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
    rightPriceScale:{borderColor:'#ddd'},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:0.4,visible:false,
               timeVisible:!!intraday,secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    localization:{priceFormatter:isKr?krAxisFmt:usAxisFmt},
  });
  const candle = cChart.addCandlestickSeries({
    upColor:UP_COLOR,downColor:DOWN_COLOR,borderUpColor:UP_COLOR,
    borderDownColor:DOWN_COLOR,wickUpColor:UP_COLOR,wickDownColor:DOWN_COLOR,
    priceFormat});
  candle.setData(raw.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
  const vol = cChart.addHistogramSeries({priceScaleId:'',
    priceFormat:{type:'custom',minMove:1,formatter:v=>Math.round(v/1000).toLocaleString()+'K'}});
  vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
  vol.setData(raw.map(r=>({time:r[0],value:r[5],
    color:r[4]>=r[1]?VOL_UP:VOL_DOWN})));
  MA_DEFS.forEach(([p,color])=>{
    const ln=cChart.addLineSeries({color,lineWidth:1,priceLineVisible:false,
      priceFormat,
      lastValueVisible:false,crosshairMarkerVisible:false});
    // 전구간 시간축(whitespace)으로 캔들과 로컬인덱스 정렬
    const mp=new Map(sma(closes,p).map(o=>[times[o.i],o.value]));
    ln.setData(times.map(t=> mp.has(t)? {time:t,value:mp.get(t)} : {time:t}));
  });
  // MagicTrend(10,3) ATR선 오버레이 — 2px 점선, 점별 색(CCI≥0 파랑/<0 빨강). 거래대금 팝업과 동일
  const _mt=magicTrend(raw,3,10,20);
  const mtData=raw.map((b,i)=> _mt.mt[i]==null? {time:b[0]}
    : {time:b[0],value:+_mt.mt[i].toFixed(2),color:_mt.up[i]?'#0022FC':'#ff5252'});
  const mtLine=cChart.addLineSeries({color:'#0022FC',lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,
    priceFormat,
    lastValueVisible:false,crosshairMarkerVisible:false});
  mtLine.setData(mtData);

  // RSI 차트 (파랑 RSI + 빨강 14이평 + 30/70 점선)
  const rChart = LightweightCharts.createChart(rsiEl, {
    width:rsiEl.clientWidth, height:rsiEl.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#888',fontSize:10},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f7f7f7'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.12,bottom:0.12}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:0.4,
               timeVisible:!!intraday,secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
  });
  const rsiArr = rsiWilder(closes,14);
  const rsiMa  = smaArr(rsiArr,14);
  // whitespace 포함 → 캔들과 시간축 정렬
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

  // 기본 구간 (우측 RIGHT_PAD 만큼 여백)
  const n=raw.length, from=Math.max(0,n-defaultBars);
  cChart.timeScale().setVisibleLogicalRange({from, to:n-1+RIGHT_PAD});
  rChart.timeScale().setVisibleLogicalRange({from, to:n-1+RIGHT_PAD});

  // 시간축 동기화 (캔들 ↔ RSI)
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

function setLab(colId, text){ document.getElementById(colId).querySelector('.collab').textContent = text; }
function clearCol(colId){
  const c=document.getElementById(colId);
  c.querySelector('.cchart').innerHTML='';
  c.querySelector('.rchart').innerHTML='';
}

function showChart(ticker){
  const raw = OHLCV[ticker];
  const m = META.find(x=>x.ticker===ticker) || {};
  curTicker = ticker;
  popTitle.textContent = ticker + (m.name? '  '+m.name:'') + (m.sym && m.sym!==ticker? '  ['+m.sym+']':'');
  destroyChart();
  clearCol('colD'); clearCol('colW');
  if(!raw || !raw.length){
    document.getElementById('colD').style.visibility='hidden';
    document.getElementById('colW').style.visibility='hidden';
    popBox.querySelector('.empty')?.remove();
    const e=document.createElement('div'); e.className='empty'; e.textContent='데이터 없음'; popBox.appendChild(e);
    popMs.textContent=''; return;
  }
  popBox.querySelector('.empty')?.remove();
  document.getElementById('colD').style.visibility='visible';
  document.getElementById('colW').style.visibility='visible';

  const t0=performance.now();
  if(m.is_kr){
    // 한국: 5분봉(당일) + 일봉  ★테스트
    const m5 = MIN5[ticker] || [];
    if(m5.length){
      setLab('colD', '5분봉 (당일)');
      buildColumn(document.getElementById('colD'), m5, true, m5.length, true);
    } else {
      setLab('colD', '5분봉 (당일) · 데이터 없음');
    }
    setLab('colW', '일봉(6개월)');
    buildColumn(document.getElementById('colW'), raw, true, 126, false);
  } else {
    // 미국: 기존 그대로 일봉 + 주봉
    setLab('colD', '일봉(6개월)');
    buildColumn(document.getElementById('colD'), raw, false, 126, false);
    setLab('colW', '주봉(1년)');
    buildColumn(document.getElementById('colW'), toWeekly(raw), false, 52, false);
  }
  const ms=performance.now()-t0;
  popMs.textContent = 'render ' + (Math.round(ms*10)/10) + ' ms · ' + raw.length + ' bars';
}

function placePop(x,y){
  const w=Math.min(1180,window.innerWidth-20), h=600;
  let px=x+18, py=y+18;
  if(px+w>window.innerWidth-8) px=x-w-12;
  if(py+h>window.innerHeight-8) py=y-h-12;
  pop.style.left=Math.max(8,px)+'px'; pop.style.top=Math.max(8,py)+'px';
}
function openPop(){ pop.style.display='block'; }
function closePop(){ pop.style.display='none'; pinned=false; destroyChart(); }

// 열기/닫기 타이머를 각각 변수로 관리 → 이전 닫기타이머가 새 팝업을 닫는 버그 방지
let openTimer=null, closeTimer=null;
function cancelClose(){ clearTimeout(closeTimer); closeTimer=null; }
function scheduleClose(){ cancelClose(); closeTimer=setTimeout(()=>{ if(!pinned) closePop(); },220); }

document.getElementById('popClose').addEventListener('click',closePop);
pop.addEventListener('mouseenter',()=>{ pinned=true; cancelClose(); });
pop.addEventListener('mouseleave',()=>{ pinned=false; scheduleClose(); });

document.querySelectorAll('.trig[data-ticker]').forEach(el=>{
  el.addEventListener('mouseenter',e=>{
    if(window.matchMedia('(hover: none)').matches) return;  // 터치기기만 제외
    cancelClose();                       // 핵심: 직전 티커의 닫기예약 취소
    const x=e.clientX, y=e.clientY, tk=el.getAttribute('data-ticker');
    clearTimeout(openTimer);
    openTimer=setTimeout(()=>{ placePop(x,y); openPop(); showChart(tk); },60);
  });
  el.addEventListener('mouseleave',()=>{ clearTimeout(openTimer); scheduleClose(); });
  el.addEventListener('click',e=>{ cancelClose(); clearTimeout(openTimer);
    placePop(e.clientX,e.clientY); openPop(); pinned=true;
    showChart(el.getAttribute('data-ticker')); });
});

window.addEventListener('resize',()=>{ if(curTicker && pop.style.display==='block') showChart(curTicker); });
"""
    js = (js.replace("__OHLCV__", ohlcv_json)
            .replace("__MIN5__", min5_json)
            .replace("__META__", meta_json))

    html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>통합ETF [TEST2] — 데이터내장 인터랙티브 차트 (로딩속도 비교)</title>
<script src="lib/lightweight-charts.standalone.production.js"></script>
<style>
  body{font-family:-apple-system,'Malgun Gothic',sans-serif;margin:0;padding:16px;background:#f4f5f7;color:#1f2937;}
  h1{font-size:18px;margin:0 0 4px;}
  .sub{color:#6b7280;font-size:12.5px;margin-bottom:12px;line-height:1.5;}
  .sub b{color:#b91c1c;}
  table{border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;}
  th,td{padding:5px 10px;font-size:13px;border-bottom:1px solid #eef0f2;text-align:left;white-space:nowrap;}
  th{background:#f8fafc;font-size:11px;color:#475569;font-weight:700;}
  td.num{color:#94a3b8;text-align:right;}
  td.r{text-align:right;font-variant-numeric:tabular-nums;}
  td.c{text-align:center;}
  .trig{cursor:pointer;text-decoration:underline dotted;}
  .trig:hover{background:#e8f4f8;}
  .tk{font-family:monospace;font-weight:700;}
  .nm{color:#475569;}
  .tag{font-size:9px;font-weight:700;padding:1px 5px;border-radius:999px;margin-left:5px;}
  .tag-kr{background:#fee2e2;color:#991b1b;} .tag-us{background:#dbeafe;color:#1e40af;}
  #pop{display:none;position:fixed;z-index:9999;width:min(1180px,96vw);background:#fff;
       border:1px solid #cbd5e1;border-radius:10px;box-shadow:0 10px 40px rgba(0,0,0,.18);padding:10px;}
  .pophead{display:flex;align-items:center;gap:10px;margin-bottom:6px;}
  #popTitle{font-weight:700;font-size:14px;}
  #popMs{font-size:12px;color:#16a34a;font-weight:700;font-family:monospace;}
  #popClose{margin-left:auto;border:0;background:#e5e7eb;border-radius:5px;cursor:pointer;font-size:14px;padding:2px 9px;}
  #popBox{display:grid;grid-template-columns:1fr 1fr;gap:12px;position:relative;}
  .col{display:flex;flex-direction:column;min-width:0;}
  .collab{font-size:11px;font-weight:700;color:#374151;padding:2px 0 3px;text-align:right;}
  .rlab{font-size:10px;color:#6b7280;padding:3px 0 1px;}
  .cchart{width:100%;height:400px;}
  .rchart{width:100%;height:120px;}
  .empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;height:520px;color:#991b1b;}
  @media(max-width:900px){ #popBox{grid-template-columns:1fr;} }
</style>
</head>
<body>
  <h1>통합ETF [TEST2] — 데이터 내장 인터랙티브 차트</h1>
  <div class="sub">
    <b>로딩속도 비교 테스트.</b> 종목명에 마우스를 올리면(hover) 차트가 뜹니다.
    이 페이지는 30종목 OHLCV(2년치)를 HTML에 내장 → <b>hover 시 네트워크 0, 즉시 렌더</b>(우상단 render ms 확인).
    기존 <code>total_etf_combined.html</code>(네이버 PNG, hover마다 네트워크)와 비교해 보세요.
    <b>[TEST] KR=5분봉(당일)+일봉, 미국=일봉+주봉</b> · MA 5/10/20/60/120 + 거래량 + RSI(14) · 휠=확대 · 드래그=이동.
  </div>
  <table>
    <thead><tr>
      <th>#</th><th>종목 (hover)</th><th>당일%</th><th>수익%</th><th>추세</th><th>sco</th><th>final</th><th>RSI</th>
    </tr></thead>
    <tbody>
__ROWS__
    </tbody>
  </table>

  <div id="pop">
    <div class="pophead">
      <span id="popTitle">-</span><span id="popMs"></span>
      <button id="popClose" title="닫기">&#215;</button>
    </div>
    <div id="popBox">
      <div class="col" id="colD">
        <div class="collab">일봉(6개월)</div>
        <div class="cchart"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div>
        <div class="rchart"></div>
      </div>
      <div class="col" id="colW">
        <div class="collab">주봉(1년)</div>
        <div class="cchart"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div>
        <div class="rchart"></div>
      </div>
    </div>
  </div>
<script>
__JS__
</script>
</body>
</html>
""".replace("__ROWS__", rows_html).replace("__JS__", js)
    return html


def main():
    print("[1/3] CSV 읽기")
    items = load_rows()
    print(f"   {len(items)}종목")
    print("[2/3] OHLCV 수집 (병렬)")
    ohlcv, resolved, min5 = collect_ohlcv(items)
    # 데이터 누락(빈 차트) 종목 점검 — 조용한 누락 방지
    empties = [it["ticker"] for it in items if not ohlcv.get(it["ticker"])]
    if empties:
        print(f"  [경고] 데이터 누락 {len(empties)}종목: {', '.join(empties)}")
    else:
        print("  [확인] 30종목 전부 데이터 정상 (누락 0)")

    # 로컬 차트 라이브러리 존재 확인 — 없으면 전체 차트 안뜸
    lib = BASE / "lib" / "lightweight-charts.standalone.production.js"
    if not lib.exists():
        print(f"  [경고] 차트 라이브러리 없음: {lib}")

    n_m5 = sum(1 for it in items if it["is_kr"] and min5.get(it["ticker"]))
    print(f"  [5분봉] KR {n_m5}종목 당일 분봉 수집")

    print("[3/3] HTML 생성")
    html = build_html(items, ohlcv, resolved, min5)
    OUT_HTML.write_text(html, encoding="utf-8")
    kb = len(html.encode("utf-8")) / 1024
    status = "누락 0" if not empties else f"누락 {len(empties)}"
    print(f"[OK] {OUT_HTML.name}  ({kb:.0f} KB, {len(items)}종목, {status})")


if __name__ == "__main__":
    main()
