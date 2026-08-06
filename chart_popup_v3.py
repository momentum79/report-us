# chart_popup_v3.py ── [TEST] Supertrend 오버레이 차트 (chart_popup_v2 데이터층 재사용)
# V2와 동일한 팝업 구조이되, MagicTrend(10,3) 대신 Supertrend 3종(10/3, 11/2, 12/1)을 올린다.
#   - 데이터 수집(일봉/5분봉/KOSPI)은 chart_popup_v2 의 함수를 그대로 import → V2 원본은 절대 수정 안 함.
#   - 단일 supertrend() 함수를 3개 파라미터로 호출 → 선 3개(+선택적 음영밴드).
#   - 색: 상승(direction<0)=초록 / 하락(direction>0)=빨강 (TradingView ta.supertrend 동일).
# 실행:  python chart_popup_v3.py        →  report-us/chart_v3_test.html (005930 삼성전자 자동표시)
import os, json, time, webbrowser

# ── V2 데이터층 재사용 (원본 무수정) ──
import chart_popup_v2 as v2
from chart_popup_v2 import (
    BASE_DIR, APP_KEY, SECRET_KEY,
    collect_daily, collect_5min, fetch_kospi_daily, collect_kospi_5min,
    is_nxt, _kiwoom_token,
)

# ───────── 팝업 CSS (V2와 동일 + 밴드 무관) ─────────
POPUP_CSS = v2.POPUP_CSS

# ───────── 팝업 HTML (라벨만 Supertrend로 교체) ─────────
POPUP_HTML = """
<div id="naverChartPopup" tabindex="-1">
  <div class="popup-header">
    <button id="naverPopupClose">&#x2715;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 종목 페이지</a>
    <span id="popMs"></span>
    <div class="popTabs">
      <button class="popTab active" data-tab="5">5분봉</button>
      <button class="popTab" data-tab="d">일봉</button>
    </div>
  </div>
  <div id="popBox">
    <div class="col" id="col5">
      <div class="collab">5분봉 (__DAYS5__일)</div>
      <div class="chartbox"><div class="legend" id="lg5"></div><div class="cchart" id="chart5"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div><div class="rchart" id="rsi5"></div></div>
    </div>
    <div class="col" id="colD">
      <div class="collab">일봉(4개월)</div>
      <div class="chartbox"><div class="legend" id="lgD"></div><div class="cchart" id="chartD"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div><div class="rchart" id="rsiD"></div></div>
    </div>
  </div>
</div>
"""

# ───────── 팝업 JS (V2 기반, MagicTrend → Supertrend 3종) ─────────
POPUP_JS = r"""
const DAILY = __DAILY__;
const MIN5  = __MIN5__;
const NXTSET = new Set(__NXTSET__);
const TRADES = __TRADES__;
const KOSPI_D = __KOSPI_D__;
const KOSPI5  = __KOSPI5__;
const TRACK_D = __TRACK_D__;
const KOSPI_STYLE = {color:'rgba(150,150,150,0.7)',lineWidth:2,
  lineStyle:LightweightCharts.LineStyle.Dotted,priceLineVisible:false,
  lastValueVisible:false,crosshairMarkerVisible:false};
const RIGHT_PAD=5, N_GAP=1;
const fmt=n=>Math.round(n).toLocaleString();
const axisFmt=n=>{
  const v=Math.round(n);
  return Math.abs(v)>=1000000 ? Math.round(v/1000).toLocaleString()+'K' : v.toLocaleString();
};
const PRICE_FORMAT={type:'custom',minMove:1,formatter:axisFmt};
KOSPI_STYLE.priceFormat=PRICE_FORMAT;

// ── Supertrend 3종 설정 (ATR Length / Factor) ──
const ST_PARAMS=[
  {atr:10,factor:3,up:'rgba(8,153,129,0.5)',dn:'rgba(242,54,69,0.5)',bandUp:'rgba(8,153,129,0.10)', bandDn:'rgba(242,54,69,0.10)', w:1},
  {atr:11,factor:2,up:'rgba(22,163,74,0.5)',dn:'rgba(239,68,68,0.5)',bandUp:'rgba(22,163,74,0.075)',bandDn:'rgba(239,68,68,0.075)',w:1},
  {atr:12,factor:1,up:'rgba(101,163,13,0.5)',dn:'rgba(249,115,22,0.5)',bandUp:'rgba(101,163,13,0.06)',bandDn:'rgba(249,115,22,0.06)',w:1},
];
const SHOW_BANDS=true;   // 음영밴드 on/off (성능부담 없음 · 시각만 복잡)

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

// ── Supertrend (TradingView ta.supertrend(factor, atrPeriod) 동일 공식) ──
// ATR = ta.atr = Wilder RMA(true range, atrPeriod)
// hl2 ± factor*ATR 의 밴드를 끈끈하게 끌고가며, direction(<0 상승 / >0 하락) 전환.
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
    if(!hasPrev)            d=1;                                   // 첫 유효봉: 상승 시작 가정
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
function installBandOverlay(el,ch,priceSeries,bands){
  if(!SHOW_BANDS||!bands.length)return;
  el.style.position='relative';
  const canvas=document.createElement('canvas');
  canvas.className='st-band-overlay';
  canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;';
  el.appendChild(canvas);
  let raf=0;
  function queueDraw(){
    if(raf)return;
    raf=requestAnimationFrame(()=>{raf=0;draw();});
  }
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
  extras.push(queueDraw);
}

// ── 저/저2 저점신호 ──
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
  const k3=rollMeanN(stochN(close,high,low,20),10);
  const k2=rollMeanN(stochN(close,high,low,10),5);
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
let charts=[], extras=[], openTimer=null, closeTimer=null, pinned=false, curCode=null, curTd=null;
let curR5=[], curRD=[], built5=false, builtD=false;

function clearBoxes(){
  ['chart5','chartD'].forEach(id=>{
    const box=document.getElementById(id).parentElement;
    box.querySelectorAll('.divider,.exlab,.st-band-overlay').forEach(d=>d.remove());
  });
  document.getElementById('lg5').style.display='none';
  document.getElementById('lgD').style.display='none';
}
function destroyChart(){charts.forEach(c=>{try{c.remove();}catch(e){}});charts=[];extras=[];built5=false;builtD=false;clearBoxes();}

function paintLegend(lg,b,labelIdx){
  const cu=b[4]>=b[1]?'#d32f2f':'#1565c0';
  lg.innerHTML=
    '<div><span class="k">날짜</span><b>'+b[labelIdx]+'</b></div>'+
    '<div><span class="k">종가</span><b style="color:'+cu+'">'+fmt(b[4])+'</b></div>'+
    '<div><span class="k">거래량</span><b>'+b[5].toLocaleString()+'</b></div>'+
    '<div><span class="k">시가</span>'+fmt(b[1])+'</div>'+
    '<div><span class="k">고가</span><span style="color:#d32f2f">'+fmt(b[2])+'</span></div>'+
    '<div><span class="k">저가</span><span style="color:#1565c0">'+fmt(b[3])+'</span></div>';
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
    rightPriceScale:{borderColor:'#ddd'},
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
  const bUp=rch.addBaselineSeries({baseValue:{type:'price',price:70},
    topLineColor:'rgba(0,0,0,0)',
    topFillColor1:'rgba(50,205,50,0.62)',topFillColor2:'rgba(50,205,50,0.30)',
    bottomLineColor:'rgba(0,0,0,0)',
    bottomFillColor1:'rgba(0,0,0,0)',bottomFillColor2:'rgba(0,0,0,0)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  bUp.setData(rdata);
  const bDn=rch.addBaselineSeries({baseValue:{type:'price',price:30},
    topLineColor:'rgba(0,0,0,0)',
    topFillColor1:'rgba(0,0,0,0)',topFillColor2:'rgba(0,0,0,0)',
    bottomLineColor:'rgba(0,0,0,0)',
    bottomFillColor1:'rgba(239,68,68,0.30)',bottomFillColor2:'rgba(239,68,68,0.62)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  bDn.setData(rdata);
  const rl=rch.addLineSeries({color:'#1565c0',lineWidth:1,priceLineVisible:false,
    lastValueVisible:true,crosshairMarkerVisible:false});
  rl.setData(rdata);
  const rm=rch.addLineSeries({color:'#e11d1d',lineWidth:1,priceLineVisible:false,
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
function syncScaleWidth(a,b){
  const apply=()=>{try{
    const w=Math.max(a.priceScale('right').width(),b.priceScale('right').width());
    a.priceScale('right').applyOptions({minimumWidth:w});
    b.priceScale('right').applyOptions({minimumWidth:w});
  }catch(e){}};
  requestAnimationFrame(apply);
  a.timeScale().subscribeVisibleLogicalRangeChange(apply);
}
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
  const cs=ch.addCandlestickSeries({upColor:'#d32f2f',downColor:'#1565c0',borderUpColor:'#d32f2f',
    borderDownColor:'#1565c0',wickUpColor:'#d32f2f',wickDownColor:'#1565c0',
    priceFormat:PRICE_FORMAT});
  const vol=ch.addHistogramSeries({priceScaleId:'',
    priceFormat:{type:'custom',minMove:1,formatter:v=>Math.round(v/1000).toLocaleString()+'K'}});
  vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
  return [cs,vol];
}
function kospiEndMark(series,last){
  series.setMarkers([{time:last.time,position:'inBar',
    color:'rgba(150,150,150,0.7)',shape:'square',size:2}]);
}
function buildIntraday(rows,code){
  const el=document.getElementById('chart5'), lg=document.getElementById('lg5');
  const rel=document.getElementById('rsi5');
  const isNxt=NXTSET.has(code);
  const ch=newCandle(el,true);
  const kospiLine=ch.addLineSeries(KOSPI_STYLE);
  const STS=ST_PARAMS.map(sp=>supertrend(rows,sp.factor,sp.atr));
  const [cs,vol]=addCandleVol(ch);
  const closes=rows.map(b=>b[4]);
  const rsiArr=rsiWilder(closes,14), rsiMa=smaArr(rsiArr,14);
  const cd=[],vd=[],bodyMid=[],rd=[],rmd=[],bounds=[],sessPairs=[];
  const stLn=ST_PARAMS.map(()=>[]),stUp=ST_PARAMS.map(()=>[]),stDn=ST_PARAMS.map(()=>[]);
  let prev=null;
  for(let i=0;i<rows.length;i++){
    const b=rows[i],day=b[6].slice(0,10);
    if(prev!==null&&day!==prev){const base=rows[i-1][0];
      for(let k=1;k<=N_GAP;k++){const gt=base+k*300;cd.push({time:gt});vd.push({time:gt});bodyMid.push({time:gt});
        rd.push({time:gt});rmd.push({time:gt});
        stLn.forEach(a=>a.push({time:gt}));stUp.forEach(a=>a.push({time:gt}));stDn.forEach(a=>a.push({time:gt}));}
      bounds.push(base+Math.ceil(N_GAP/2)*300);}
    else if(i>0&&isNxt){const hm=b[6].slice(11,16),phm=rows[i-1][6].slice(11,16);
      if(phm<'09:00'&&hm>='09:00')  sessPairs.push([rows[i-1][0],b[0]]);
      if(phm<='15:30'&&hm>'15:30')  sessPairs.push([rows[i-1][0],b[0]]);}
    cd.push({time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]});
    vd.push({time:b[0],value:b[5],color:b[4]>=b[1]?'rgba(211,47,47,.35)':'rgba(21,101,192,.35)'});
    bodyMid.push({time:b[0],value:+(((b[1]+b[4])/2).toFixed(2))});
    rd.push(rsiArr[i]==null?{time:b[0]}:{time:b[0],value:+rsiArr[i].toFixed(2)});
    rmd.push(rsiMa[i]==null?{time:b[0]}:{time:b[0],value:+rsiMa[i].toFixed(2)});
    ST_PARAMS.forEach((sp,si)=>{const v=STS[si].st[i],d=STS[si].dir[i];
      stLn[si].push(v==null?{time:b[0]}:{time:b[0],value:+v.toFixed(2),color:d<0?sp.up:sp.dn});
      stUp[si].push((v!=null&&d<0)?{time:b[0],value:+v.toFixed(2)}:{time:b[0]});
      stDn[si].push((v!=null&&d>0)?{time:b[0],value:+v.toFixed(2)}:{time:b[0]});});
    prev=day;}
  cs.setData(cd);vol.setData(vd);
  installBandOverlay(el,ch,cs,ST_PARAMS.flatMap((sp,si)=>[
    {color:sp.bandUp,points:buildFillEnvelope(bodyMid,stUp[si],sp.bandUp)},
    {color:sp.bandDn,points:buildFillEnvelope(bodyMid,stDn[si],sp.bandDn)}
  ]));
  // Supertrend 선 3개 — 봉별 색(direction<0 초록 / >0 빨강)
  ST_PARAMS.forEach((sp,si)=>{const ln=ch.addLineSeries({color:sp.up,lineWidth:sp.w,
    priceFormat:PRICE_FORMAT,
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});ln.setData(stLn[si]);});
  const sig=computeLowSignals(rows), marks=[];
  sig.jeo.forEach(t=>marks.push({time:t,position:'belowBar',color:'#e11d1d',shape:'square',text:''}));
  sig.jeo2.forEach(t=>marks.push({time:t,position:'belowBar',color:'#000000',shape:'square',text:'저2',size:0}));
  computeTopSignals(rows).forEach(t=>marks.push({time:t,position:'aboveBar',color:'#000000',shape:'square',text:'X',size:0}));
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
  const trkBand=ch.addHistogramSeries({priceScaleId:'trkband',base:0,
    priceLineVisible:false,lastValueVisible:false,color:'rgba(50,205,50,0.30)'});
  ch.priceScale('trkband').applyOptions({scaleMargins:{top:0,bottom:0}});
  const kospiLine=ch.addLineSeries(KOSPI_STYLE);
  const times=rows.map(b=>b[0]),closes=rows.map(b=>b[4]);
  const STS=ST_PARAMS.map(sp=>supertrend(rows,sp.factor,sp.atr));
  const [cs,vol]=addCandleVol(ch);
  cs.setData(rows.map(b=>({time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]})));
  (function(){const td=TRACK_D[curCode];if(!td||!td.length)return;
    const st=new Set(td);
    const bd=rows.filter(b=>st.has(b[0])).map(b=>({time:b[0],value:1,color:'rgba(50,205,50,0.30)'}));
    if(bd.length)trkBand.setData(bd);})();
  vol.setData(rows.map(b=>({time:b[0],value:b[5],color:b[4]>=b[1]?'rgba(211,47,47,.35)':'rgba(21,101,192,.35)'})));
  const bodyMid=times.map((t,i)=>({time:t,value:+(((rows[i][1]+rows[i][4])/2).toFixed(2))}));
  const stUp=STS.map(r=>times.map((t,i)=>(r.st[i]!=null&&r.dir[i]<0)?{time:t,value:+r.st[i].toFixed(2)}:{time:t}));
  const stDn=STS.map(r=>times.map((t,i)=>(r.st[i]!=null&&r.dir[i]>0)?{time:t,value:+r.st[i].toFixed(2)}:{time:t}));
  installBandOverlay(el,ch,cs,ST_PARAMS.flatMap((sp,si)=>[
    {color:sp.bandUp,points:buildFillEnvelope(bodyMid,stUp[si],sp.bandUp)},
    {color:sp.bandDn,points:buildFillEnvelope(bodyMid,stDn[si],sp.bandDn)}
  ]));
  // Supertrend 선 3개 — 봉별 색 초록/빨강
  ST_PARAMS.forEach((sp,si)=>{const r=STS[si];
    const ln=ch.addLineSeries({color:sp.up,lineWidth:sp.w,priceLineVisible:false,
      priceFormat:PRICE_FORMAT,
      lastValueVisible:false,crosshairMarkerVisible:false});
    ln.setData(times.map((t,i)=>r.st[i]==null?{time:t}
      :{time:t,value:+r.st[i].toFixed(2),color:r.dir[i]<0?sp.up:sp.dn}));});
  (function(){
    const n=rows.length;if(n<2)return;
    let aIdx=Math.max(0,n-1-20);
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
  charts.push(ch,rch);
}

function popBoxEmpty(show){
  document.getElementById('col5').style.visibility=show?'hidden':'visible';
  document.getElementById('colD').style.visibility=show?'hidden':'visible';
  let e=document.querySelector('#popBox .empty');
  if(show){if(!e){e=document.createElement('div');e.className='empty';e.textContent='데이터 없음';document.getElementById('popBox').appendChild(e);}}
  else if(e)e.remove();
}
function ensureBuilt5(){if(!built5&&curR5.length){buildIntraday(curR5,curCode);built5=true;}}
function ensureBuiltD(){if(!builtD&&curRD.length){buildDaily(curRD);builtD=true;}}
function showChart(code,name){
  curCode=code;
  popTitle.textContent=code+'  '+(name||'');
  popLink.href='https://finance.naver.com/item/main.naver?code='+code;
  destroyChart();
  curR5=MIN5[code]||[]; curRD=DAILY[code]||[];
  if(!curR5.length&&!curRD.length){popBoxEmpty(true);popMs.textContent='';return;}
  popBoxEmpty(false);
  const t0=performance.now();
  applyMobileTab();
  const ms=performance.now()-t0;
  popMs.textContent='render '+(Math.round(ms*10)/10)+' ms · 5분 '+curR5.length+' / 일 '+curRD.length;
}
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
  setTimeout(()=>{extras.forEach(fn=>{try{fn();}catch(e){}});},0);
}

function placePop(x,y){if(window.innerWidth<=767)return;
  const w=Math.min(1020,window.innerWidth-20),h=560;let px=x+18,py=y+18;
  if(px+w>window.innerWidth-8)px=x-w-12;if(py+h>window.innerHeight-8)py=y-h-12;
  pop.style.left=Math.max(8,px)+'px';pop.style.top=Math.max(8,py)+'px';pop.style.transform='none';}
function openPop(){pop.style.display='block';document.body.classList.add('naver-popup-open');
  // iframe 안에서 열릴 때 키보드 포커스를 잡아야 s/d 단축키가 첫 호버부터 동작.
  // 단, 게시판 입력창 등에 이미 포커스가 있으면 뺏지 않음(activeElement===body일 때만).
  try{if(document.activeElement===document.body||document.activeElement===null)pop.focus({preventScroll:true});}catch(e){}}
function closePop(){pop.style.display='none';document.body.classList.remove('naver-popup-open');pinned=false;destroyChart();
  document.removeEventListener('mousemove',unpinOnMove);}
function cancelClose(){clearTimeout(closeTimer);closeTimer=null;}
function scheduleClose(){cancelClose();closeTimer=setTimeout(()=>{if(!pinned)closePop();},220);}
// 키보드(s/d)로 종목 이동 시 임시 고정. 그 뒤 마우스가 팝업 밖에서 움직이면 고정 해제 → 자동닫힘 복구
function unpinOnMove(e){if(pop.contains(e.target))return;
  document.removeEventListener('mousemove',unpinOnMove);pinned=false;scheduleClose();}
function kbPin(){pinned=true;cancelClose();
  document.removeEventListener('mousemove',unpinOnMove);
  document.addEventListener('mousemove',unpinOnMove);}

document.getElementById('naverPopupClose').addEventListener('click',closePop);
document.querySelectorAll('.popTab').forEach(b=>{
  b.addEventListener('click',e=>{e.stopPropagation();applyMobileTab(b.dataset.tab);});
});
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
document.addEventListener('click',e=>{
  if(pop.style.display!=='block')return;
  if(pop.contains(e.target))return;
  if(e.target.closest&&e.target.closest('td[data-code]'))return;
  closePop();});
// 키보드(팝업 열렸을 때만): S/↑=이전, D/↓=다음, Tab/ESC=닫기 (v3는 Supertrend 전용 → 토글 없음)
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
  const k=e.key;
  if(k==='Tab'||k==='Escape'){e.preventDefault();closePop();return;}
  let dir=0;
  if(k==='s'||k==='S'||k==='ArrowUp')dir=-1;
  else if(k==='d'||k==='D'||k==='ArrowDown')dir=1;
  if(dir===0||!curTd)return;
  e.preventDefault();
  const all=Array.from(document.querySelectorAll('td[data-code]'));
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
__AUTO_OPEN__
"""

# ───────── 빌더 ─────────
def build_chart_popup(codes, days5=5, trade_marks=None, cache_key=None, track_dates=None,
                      auto_code=None, auto_name=""):
    """V2 build_chart_popup 와 동일 시그니처 + auto_code(테스트용 자동표시)."""
    codes = sorted({str(c).zfill(6) for c in codes if str(c).strip()})
    if not codes:
        return "<!-- chart_popup_v3: no codes -->"
    print(f"  [chart_popup_v3] {len(codes)}종목 OHLCV 수집 (일봉+5분봉)...")
    t0 = time.time()
    cache5 = (os.path.join(BASE_DIR, "0txt", f"min5_cache_{cache_key}.json")
              if cache_key else None)
    cachek = (os.path.join(BASE_DIR, "0txt", f"kospi5_cache_{cache_key}.json")
              if cache_key else None)
    token = None
    if APP_KEY and SECRET_KEY:
        try:
            token = _kiwoom_token()
        except Exception as e:
            print(f"  [chart_popup_v3] 키움 토큰실패: {e}")
    daily = collect_daily(codes)
    min5  = collect_5min(codes, days=days5, cache_path=cache5, token=token)
    kospi_daily = fetch_kospi_daily()
    kospi5      = collect_kospi_5min(cachek, token)
    nD = sum(1 for c in codes if daily.get(c))
    n5 = sum(1 for c in codes if min5.get(c))
    print(f"  [chart_popup_v3] 완료 {time.time()-t0:.1f}s · 일봉 {nD}/{len(codes)} · 5분봉 {n5}/{len(codes)}"
          f" · KOSPI(일 {len(kospi_daily)}/5분 {len(kospi5)})")
    nxt_codes = [c for c in codes if is_nxt(c)]
    auto = ""
    if auto_code:
        ac = str(auto_code).zfill(6)
        auto = (f"window.addEventListener('load',function(){{pop.style.left='50%';"
                f"pop.style.top='40px';pop.style.transform='translateX(-50%)';"
                f"openPop();pinned=true;showChart('{ac}',{json.dumps(auto_name, ensure_ascii=False)});}});")
    js = (POPUP_JS
          .replace("__DAILY__", json.dumps(daily, ensure_ascii=False))
          .replace("__MIN5__",  json.dumps(min5,  ensure_ascii=False))
          .replace("__NXTSET__", json.dumps(nxt_codes))
          .replace("__TRADES__", json.dumps(trade_marks or {}, ensure_ascii=False))
          .replace("__KOSPI_D__", json.dumps(kospi_daily, ensure_ascii=False))
          .replace("__KOSPI5__",  json.dumps(kospi5, ensure_ascii=False))
          .replace("__TRACK_D__", json.dumps(track_dates or {}, ensure_ascii=False))
          .replace("__AUTO_OPEN__", auto))
    return ("<style>" + POPUP_CSS + "</style>\n"
            + POPUP_HTML.replace("__DAYS5__", str(days5))
            + '\n<script src="lib/lightweight-charts.standalone.production.js"></script>\n'
            + "<script>\n(function(){\n" + js + "\n})();\n</script>")


def build_test_html(code="005930", name="삼성전자"):
    """단독 HTML 테스트 페이지 문자열 생성 (브라우저로 바로 열어 확인)."""
    block = build_chart_popup([code], days5=5, auto_code=code, auto_name=name)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>V3 Supertrend 차트 테스트 · {name} {code}</title>
<style>body{{font-family:'Malgun Gothic',sans-serif;margin:24px;color:#2c3e50;}}
table{{border-collapse:collapse;}} td{{border:1px solid #ccc;padding:8px 14px;}}</style>
</head><body>
<h3>V3 Supertrend 오버레이 테스트 — 10/3 · 11/2 · 12/1 (단일 supertrend 함수, 파라미터 3종)</h3>
<p>아래 행에 마우스를 올리면 팝업이 뜹니다. 페이지 로드시 {name} 차트가 자동으로 열립니다.</p>
<table><tr>
  <td data-code="{code}" data-name="{name}">{name}</td>
  <td data-code="{code}" data-name="{name}">{code}</td>
</tr></table>
{block}
</body></html>"""


if __name__ == "__main__":
    out_path = os.path.join(BASE_DIR, "report-us", "chart_v3_test.html")
    html = build_test_html("005930", "삼성전자")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [chart_popup_v3] 작성 완료 → {out_path}")
    try:
        webbrowser.open("file:///" + out_path.replace("\\", "/"))
    except Exception:
        pass
