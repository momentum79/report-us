# make_danta_chart_display.py ── 단타 게시판 생성 (요약 게시판 하위: 요약 | 단타 | 차트)
#
# - 고정 6종목의 5분봉 차트를 페이지에 인라인 표시 (팝업 아님, 페이지 열면 바로 로딩)
#   렌더는 거래대금 게시판 팝업(chart_popup_v2)의 5분봉 차트와 동일:
#   MA(5/10/20/60) + RSI(14)+14이평 음영 + 일자경계 점선 + OHL 호버툴팁
# - 신호마커: 저(빨간박스)/저2(검정윗화살표) 저점신호, X(검정아래화살표) 고점신호
# - 매매마커: B(진입, 캔들아래)/S(청산, 캔들위) — 노란 배경 사각박스로 강조(HTML 오버레이)
#   → make_danta_journal 의 fill 재구성 로직 재사용 (0order/intraday_signals)
# - 데이터: 키움 ka10080 5분봉 5일치 (chart_popup_v2.collect_5min — 거래대금 팝업과 동일)
#
# 레이아웃: 2열 × 3행 (스마트폰은 1열 + 우측 여백으로 페이지 스크롤 확보)
# 출력: report-us/danta_chart.html
import os, sys, json
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chart_popup_v2 import collect_5min, is_nxt
from coloryp_core import check_coloryp_logic
import make_danta_journal as dj

def sync_1887_fills_for_chart():
    """Refresh 1887 fills before building fixed-6 chart markers and PnL."""
    order_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "0order")
    if order_dir not in sys.path:
        sys.path.insert(0, order_dir)
    try:
        import sync_1887_fills
        sync_1887_fills.main()
    except Exception as e:
        print(f"  ⚠ 1887 동기화 생략: {e}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_HTML = os.path.join(BASE_DIR, "danta_chart.html")
DAYS5    = 5   # 거래대금 게시판 팝업과 동일 (5일치 — X신호 percentrank220 확보)

# 고정 6종목 (2열 × 3행)
ROWS = [
    [("0193W0", "삼전 x2 (레버리지)"),        ("0193T0", "하닉 x2 (레버리지)")],
    [("0193L0", "삼전 x-2 (인버스레버리지)"),  ("0197X0", "하닉 x-2 (인버스레버리지)")],
    [("122630", "KODEX 레버리지"),            ("252670", "KODEX 인버스 x2")],
]

# 당일 실현손익 표 (6행 2열) — 차트 우측 사이드패널. (code, 짧은라벨)
PNL_TABLE = [
    ("0193W0", "삼전x 2"),
    ("0193L0", "삼전x -2"),
    ("0193T0", "하닉x 2"),
    ("0197X0", "하닉x -2"),
    ("122630", "코스피 x2"),
    ("252670", "코스피 x-2"),
]


# ───────── 당일 실현손익 (make_danta_journal 의 fill/포지션 로직 재사용) ─────────
def compute_today_pnl(codes):
    """오늘(달력 기준) 코드별 실현손익 합계(1887 고정 6종목 계좌 기준).
    매매일지 게시판의 '일간' 수치와 동일 기준(datetime.now().date())."""
    pnl = {c: 0 for c in codes}
    try:
        fills = dj.load_fills()
        rows, _ = dj.build_rows(fills)
        today = datetime.now().strftime("%Y-%m-%d")
        for r in rows.values():
            if r["date"] == today and r["acct"] == "1887" and r["sells"] and r["code"] in pnl:
                pnl[r["code"]] += r["realized"]
        tot = sum(pnl.values())
        print(f"  [당일손익] {today} 합계 {tot:+,}원")
    except Exception as e:
        print(f"  ⚠ 당일 실현손익 계산 생략: {e}")
    return pnl


# ───────── B/S 매매마커 (make_danta_journal 로직 재사용) ─────────
# 자동일지차트(8042_20)와 동일하게 S(청산) 마커엔 익손절금액·수익률을 함께 실어준다.
# → dj.build_trade_marks 는 {t,s}만 주므로, fill 평단을 직접 재구성해 매도별 손익을 계산.
def build_trade_marks(codes):
    try:
        fills = dj.load_fills()
        rows, _ = dj.build_rows(fills)
        dates = set(sorted({r["date"] for r in rows.values()})[-dj.DAYS_KEEP:])
        marks, positions = {}, {}   # positions: (acct,code) -> {"qty","avg"}  (build_rows 동일 순회)
        for ev in fills:
            key = (ev["acct"], ev["code"])
            pos = positions.get(key)
            keep = ev["date"] in dates and ev["code"] in codes
            if ev["side"] == "buy":
                if pos:
                    tot = pos["qty"] * pos["avg"] + ev["qty"] * ev["price"]
                    pos["qty"] += ev["qty"]
                    pos["avg"] = tot / pos["qty"]
                else:
                    pos = positions[key] = {"qty": ev["qty"], "avg": float(ev["price"])}
                if keep:
                    marks.setdefault(ev["code"], []).append(
                        {"t": dj.bar_label(ev["date"], ev["hhmm"]), "s": "B",
                         "acct": ev["acct"], "origin": ev.get("origin", "bot")})
            else:
                avg = pos["avg"] if pos else float(ev["price"])   # 장부外 매도: 손익 0
                amt = round((ev["price"] - avg) * ev["qty"])
                pct = round((ev["price"] / avg - 1) * 100, 2) if avg else 0.0
                if pos:
                    pos["qty"] -= ev["qty"]
                    if pos["qty"] <= 0:
                        del positions[key]
                if keep:
                    marks.setdefault(ev["code"], []).append(
                        {"t": dj.bar_label(ev["date"], ev["hhmm"]), "s": "S",
                         "amt": amt, "pct": pct, "acct": ev["acct"],
                         "origin": ev.get("origin", "bot")})
        n = sum(len(v) for v in marks.values())
        print(f"  [B/S] 매매마커 {n}건 ({', '.join(sorted(marks)) or '없음'})")
        return marks
    except Exception as e:
        print(f"  ⚠ B/S 마커 생략: {e}")
        return {}


# ───────── 페이지 JS (chart_popup_v2 POPUP_JS 의 5분봉 렌더와 동일 공식) ─────────
def add_trend_states(min5):
    result = {}
    for code, rows in min5.items():
        if not rows:
            result[code] = rows
            continue
        try:
            df = pd.DataFrame(
                rows,
                columns=["time", "open", "high", "low", "close", "volume", "label"],
            )
            df["date"] = pd.to_datetime(df["label"])
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
            result[code] = [
                list(row) + ([str(states[i])] if states[i] != "NONE" else [])
                for i, row in enumerate(rows)
            ]
        except Exception as e:
            print(f"  [TREND BG] {code} calculation failed: {e}")
            result[code] = [list(row) for row in rows]
    return result


PAGE_JS = r"""
const MIN5   = __MIN5__;     // {code: [[ts,o,h,l,c,v,'YYYY-MM-DD HH:MM'],...]}
const ORDER  = __ORDER__;    // [{idx, code, label}]
const NXTSET = new Set(__NXTSET__);  // 세션선(09:00·15:30)은 NXT 종목에만
const TRADES = __TRADES__;   // {code:[{t:'YYYY-MM-DD HH:MM', s:'B'|'S'}]}
// 터치 기기에서는 세로 터치드래그를 차트가 가로채지 않게 해 페이지 스크롤이 되게 한다
const IS_TOUCH = window.matchMedia('(pointer: coarse)').matches;
const MA_5=[[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a']];
const UP_COLOR='#f23645', DOWN_COLOR='#2962ff';
const VOL_UP='rgba(242,54,69,.35)', VOL_DOWN='rgba(41,98,255,.35)';
const TREND_BG_COLORS={
  LIME:'rgba(0,230,118,0.15)',GREEN:'rgba(76,175,80,0.15)',
  PURPLE:'rgba(192,132,252,0.14)',RED:'rgba(251,113,133,0.13)',
  NONE:'rgba(255,255,255,0)'};
const RIGHT_PAD=5, N_GAP=1, PREV5_BUF=24;
// 보드 프리뷰 페이지에서만 window.VIEW_2DAYS=true 주입 → 기본 표시구간을 최근 2거래일로.
// (요약-단타 게시판은 미주입 → 기존 '당일+전일 2h' 유지. 폭이 안 늘어 2일치면 캔들이 너무 얇아짐)
const VIEW_2DAYS = (typeof window!=='undefined' && window.VIEW_2DAYS) || false;
const ALL_CHARTS=[];  // [chart, el] — 리사이즈 시 폭/높이 재적용
const ALIGN_PAIRS=[]; // [candle, rsi] — 우측 가격축 폭을 맞춰 캔들↔RSI 세로선 정렬
const ANNO_REDRAW=[]; // S(청산) 익손절금액·% 오버레이 재그리기 콜백 (스크롤/리사이즈)
const fmt=n=>Math.round(n).toLocaleString();
const axisFmt=n=>{
  const v=Math.round(n);
  return Math.abs(v)>=1000000 ? Math.round(v/1000).toLocaleString()+'K' : v.toLocaleString();
};
const PRICE_FORMAT={type:'custom',minMove:1,formatter:axisFmt};
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
// ── MagicTrend (TradingView @v4 "SL" 동일 공식) — ATR=sma(tr,AP), 색=cci(close,20) 부호(≥0 파랑/<0 빨강)
function cciN(close,length){const n=close.length,out=new Array(n).fill(null),ma=smaArr(close,length);
  for(let i=0;i<n;i++){if(ma[i]==null)continue;let d=0;for(let j=i-length+1;j<=i;j++)d+=Math.abs(close[j]-ma[i]);
    d/=length;out[i]=(d===0)?0:(close[i]-ma[i])/(0.015*d);}return out;}
function magicTrend(rows,coeff,ap,cciLen){const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);const tr=new Array(n);
  for(let i=0;i<n;i++)tr[i]=(i===0)?(high[i]-low[i])
    :Math.max(high[i]-low[i],Math.abs(high[i]-close[i-1]),Math.abs(low[i]-close[i-1]));
  const atr=smaArr(tr,ap),cci=cciN(close,cciLen);const mt=new Array(n).fill(null),up=new Array(n).fill(null);let prev=0;
  for(let i=0;i<n;i++){const c=cci[i],a=atr[i];
    if(c==null||a==null){mt[i]=null;up[i]=null;prev=0;continue;}
    const upT=low[i]-a*coeff,downT=high[i]+a*coeff;
    const v=(c>=0)?((upT<prev)?prev:upT):((downT>prev)?prev:downT);mt[i]=v;up[i]=(c>=0);prev=v;}
  return {mt,up};}

// ── 저/저2 저점신호 (kr_low_signal.py calculate_tv_signals 와 동일 공식, null-aware rolling) ──
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

function paintLegend(lg,b){
  const cu=b[4]>=b[1]?UP_COLOR:DOWN_COLOR;
  lg.innerHTML=
    '<div><span class="k">날짜</span><b>'+b[6]+'</b></div>'+
    '<div><span class="k">종가</span><b style="color:'+cu+'">'+fmt(b[4])+'</b></div>'+
    '<div><span class="k">거래량</span><b>'+b[5].toLocaleString()+'</b></div>'+
    '<div><span class="k">시가</span>'+fmt(b[1])+'</div>'+
    '<div><span class="k">고가</span><span style="color:'+UP_COLOR+'">'+fmt(b[2])+'</span></div>'+
    '<div><span class="k">저가</span><span style="color:'+DOWN_COLOR+'">'+fmt(b[3])+'</span></div>';
}
function attachTooltip(ch,el,lg,byKey){
  ch.subscribeCrosshairMove(param=>{
    if(!param.time||!param.point||!byKey.has(param.time)){lg.style.display='none';return;}
    paintLegend(lg,byKey.get(param.time));lg.style.display='block';
    const bw=lg.offsetWidth,bh=lg.offsetHeight;
    let lx=param.point.x-bw-14;if(lx<4)lx=param.point.x+14;
    let ly=param.point.y-bh/2;ly=Math.max(2,Math.min(ly,el.clientHeight-bh-2));
    lg.style.left=lx+'px';lg.style.top=ly+'px';
  });
}
function newCandle(el){
  return LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.08,bottom:0.08}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:1.2,visible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    handleScroll:{vertTouchDrag:!IS_TOUCH}});
}
function newRsi(el){
  return LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#888',fontSize:10},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f7f7f7'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.12,bottom:0.12}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:1.2,
      timeVisible:true,secondsVisible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    handleScroll:{vertTouchDrag:!IS_TOUCH}});
}
function addRsi(rel,rdata,rmdata){
  const rch=newRsi(rel);
  // 과매수 영역(>70): RSI선과 70 사이 lime — baseline series 활용
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
// 캔들↔RSI 크로스헤어(세로선) 동기화 — 한쪽에 마우스를 올리면 다른쪽도 같은 시각에 세로선 표시.
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
// 캔들과 RSI는 별도 차트라 우측 가격축 폭이 다르면(예: 30,000 vs 60.00) 플롯영역 좌측끝이
// 어긋나 같은 시각의 세로선이 따로 논다. 두 축의 폭을 더 넓은 쪽으로 통일해 정렬한다.
function alignScales(ch,rch){
  requestAnimationFrame(()=>{try{
    const w=Math.max(ch.priceScale('right').width(),rch.priceScale('right').width());
    ch.priceScale('right').applyOptions({minimumWidth:w});
    rch.priceScale('right').applyOptions({minimumWidth:w});
  }catch(e){}});
}
function addCandleVol(ch){
  const cs=ch.addCandlestickSeries({upColor:UP_COLOR,downColor:DOWN_COLOR,borderUpColor:UP_COLOR,
    borderDownColor:DOWN_COLOR,wickUpColor:UP_COLOR,wickDownColor:DOWN_COLOR,
    priceFormat:PRICE_FORMAT});
  const vol=ch.addHistogramSeries({priceScaleId:'',
    priceFormat:{type:'custom',minMove:1,formatter:v=>Math.round(v/1000).toLocaleString()+'K'}});
  vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
  return [cs,vol];
}

function buildIntraday(card,code,rows){
  const el=card.querySelector('.cchart'), lg=card.querySelector('.legend');
  const rel=card.querySelector('.rchart');
  const isNxt=NXTSET.has(code);
  const ch=newCandle(el);
  const trendBand=ch.addHistogramSeries({
    priceScaleId:'trendbg',base:0,priceLineVisible:false,lastValueVisible:false});
  ch.priceScale('trendbg').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
  trendBand.setData(rows.filter(b=>(b[7]||'NONE')!=='NONE').map(b=>({
    time:b[0],value:1,color:TREND_BG_COLORS[b[7]]})));
  const [cs,vol]=addCandleVol(ch);
  const closes=rows.map(b=>b[4]);
  const maMaps=MA_5.map(([p])=>new Map(sma(closes,p).map(o=>[rows[o.i][0],o.v])));
  const rsiArr=rsiWilder(closes,14), rsiMa=smaArr(rsiArr,14);
  const mtc=magicTrend(rows,3,10,20);   // MagicTrend(10,3) ATR선 — 연속 rows 기준 계산
  const cd=[],vd=[],md=MA_5.map(()=>[]),rd=[],rmd=[],mtd=[],bounds=[],sessPairs=[]; let prev=null;
  for(let i=0;i<rows.length;i++){
    const b=rows[i],day=b[6].slice(0,10);
    if(prev!==null&&day!==prev){const base=rows[i-1][0];
      for(let k=1;k<=N_GAP;k++){const gt=base+k*300;cd.push({time:gt});vd.push({time:gt});
        md.forEach(a=>a.push({time:gt}));rd.push({time:gt});rmd.push({time:gt});mtd.push({time:gt});}
      bounds.push(base+Math.ceil(N_GAP/2)*300);}
    else if(i>0&&isNxt){const hm=b[6].slice(11,16),phm=rows[i-1][6].slice(11,16);
      // 정규장 시작(09:00)·끝(15:30) 세션선 — NXT 종목에만 (캔들 사이 빈틈에 표시)
      if(phm<'09:00'&&hm>='09:00')  sessPairs.push([rows[i-1][0],b[0]]);
      if(phm<='15:30'&&hm>'15:30')  sessPairs.push([rows[i-1][0],b[0]]);}
    cd.push({time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]});
    vd.push({time:b[0],value:b[5],color:b[4]>=b[1]?VOL_UP:VOL_DOWN});
    md.forEach((a,mi)=>{const m=maMaps[mi];a.push(m.has(b[0])?{time:b[0],value:m.get(b[0])}:{time:b[0]});});
    rd.push(rsiArr[i]==null?{time:b[0]}:{time:b[0],value:+rsiArr[i].toFixed(2)});
    rmd.push(rsiMa[i]==null?{time:b[0]}:{time:b[0],value:+rsiMa[i].toFixed(2)});
    mtd.push(mtc.mt[i]==null?{time:b[0]}:{time:b[0],value:+mtc.mt[i].toFixed(2),color:mtc.up[i]?'#0022FC':'#ff5252'});
    prev=day;}
  cs.setData(cd);vol.setData(vd);
  MA_5.forEach(([p,color],mi)=>{const ln=ch.addLineSeries({color,lineWidth:1,priceLineVisible:false,
    priceFormat:PRICE_FORMAT,autoscaleInfoProvider:()=>null,
    lastValueVisible:false,crosshairMarkerVisible:false});ln.setData(md[mi]);});
  // MagicTrend(10,3) ATR선 오버레이 — 2px 점선, 점별 색(CCI≥0 파랑/<0 빨강). 거래대금 팝업과 동일
  const mtLine=ch.addLineSeries({color:'#0022FC',lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed,priceLineVisible:false,
    priceFormat:PRICE_FORMAT,autoscaleInfoProvider:()=>null,
    lastValueVisible:false,crosshairMarkerVisible:false});mtLine.setData(mtd);
  // 저/저2 저점신호 + X 고점신호 마커 (저=빨간박스 글자, 저2=윗화살표, X=캔들위 검정 아래화살표)
  const sig=computeLowSignals(rows), marks=[];
  sig.jeo.forEach(t=>marks.push({time:t,position:'belowBar',color:'#e11d1d',shape:'square',text:'저'}));
  sig.jeo2.forEach(t=>marks.push({time:t,position:'belowBar',color:'#000000',shape:'arrowUp',text:'저2'}));
  computeTopSignals(rows).forEach(t=>marks.push({time:t,position:'aboveBar',color:'#000000',shape:'arrowDown',text:'X'}));
  // 매매일지 B(진입)/S(청산) — 노란 박스 오버레이로 강조(확 눈에 띄게).
  //   B = 캔들아래 노란박스 'B'(검정글자) / S = 캔들위 노란박스 'S'(파랑글자) + 익손절금액·%
  //   네이티브 마커는 글자 배경박스를 못 줘서, 글자크기·형태는 그대로 둔 채 HTML 오버레이로 박스만 입힌다.
  const lbl2t=new Map(rows.map(b=>[b[6],b[0]]));
  const hiByT=new Map(rows.map(b=>[b[0],b[2]]));
  const loByT=new Map(rows.map(b=>[b[0],b[3]]));
  const sells=[], buys=[];
  (TRADES[code]||[]).forEach(m=>{
    let t=lbl2t.get(m.t);
    if(t==null){const r=rows.find(b=>b[6].slice(0,10)===m.t.slice(0,10)&&b[6]>=m.t);if(r)t=r[0];}
    if(t==null)return;
    if(m.s==='B'){
      buys.push({time:t,low:loByT.get(t)||0,acct:m.acct,origin:m.origin});
    } else {
      const p=(m.pct==null)?0:m.pct, ps=(p>=0?'+':'')+p.toFixed(1)+'%';
      sells.push({time:t,high:hiByT.get(t)||0,pct:ps,amt:m.amt||0,profit:p>=0,acct:m.acct,origin:m.origin});
    }
  });
  marks.sort((a,b)=>a.time-b.time);
  if(marks.length)cs.setMarkers(marks);
  const {rch,rl}=addRsi(rel,rd,rmd);
  // 디폴트 표시 구간: 현재일 전체 + 직전일 마지막 ~2시간(PREV5_BUF봉)만.
  // (5일치 데이터는 그대로 로드 → 휠/드래그로 더 보기 가능). 우측 여백 RIGHT_PAD 유지.
  const lastDay=rows[rows.length-1][6].slice(0,10);
  let ix=rows.length-1, curDayBars=0;
  for(;ix>=0&&rows[ix][6].slice(0,10)===lastDay;ix--)curDayBars++;
  let span=curDayBars+N_GAP+PREV5_BUF;
  if(VIEW_2DAYS){
    let prevDayBars=0;
    if(ix>=0){const prevDay=rows[ix][6].slice(0,10);
      for(;ix>=0&&rows[ix][6].slice(0,10)===prevDay;ix--)prevDayBars++;}
    span=curDayBars+prevDayBars+N_GAP;  // 직전 거래일 전체(NXT면 오전8시 프리장 포함)까지
  }
  const tot=cd.length, from=Math.max(0,tot-span), to=tot-1+RIGHT_PAD;
  ch.timeScale().setVisibleLogicalRange({from,to});
  rch.timeScale().setVisibleLogicalRange({from,to});
  syncPair(ch,rch);
  syncCrosshair(ch,cs,new Map(rows.map(b=>[b[0],b[4]])),
                rch,rl,new Map(rd.filter(d=>d.value!=null).map(d=>[d.time,d.value])));
  ALIGN_PAIRS.push([ch,rch]);alignScales(ch,rch);
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
  // B(진입)/S(청산) 노란박스 오버레이.
  //   B = 캔들 아래 노란박스 'B' / S = 캔들 위 익손절금액·% + 노란박스 'S'
  //   (금액/%: 익절 검정·손절 빨강 — 박스 없이 텍스트만)
  const anno=document.createElement('div');anno.className='anno';box.appendChild(anno);
  function drawAnno(){
    if(!sells.length&&!buys.length){anno.innerHTML='';return;}
    const tsc=ch.timeScale();let html='';
    buys.forEach(b=>{
      const x=tsc.timeToCoordinate(b.time);if(x==null)return;
      const y=cs.priceToCoordinate(b.low);if(y==null)return;
      const bc=(b.acct&&b.acct.endsWith('DIP'))?' dip':'';   // 8042DIP·1887DIP 등 수동 저점매수
      const bt=(b.origin==='manual')?'BB':'B';   // 수동매수는 글자 하나 더(BB)
      html+='<div class="bmark'+bc+'" style="left:'+x+'px;top:'+(y+12)+'px;color:#111111">'+bt+'</div>';
    });
    sells.forEach(s=>{
      const x=tsc.timeToCoordinate(s.time);if(x==null)return;
      const y=cs.priceToCoordinate(s.high);if(y==null)return;
      const pc=s.profit?'#111111':'#e11d1d';
      const amtline=s.amt?('<div style="color:'+pc+'">'+(s.amt>0?'+':'')+Math.round(s.amt).toLocaleString()+'</div>'):'';
      html+='<div class="s" style="left:'+x+'px;top:'+(y-18)+'px">'+amtline+
            '<div style="color:'+pc+'">'+s.pct+'</div>'+
            '<div><span class="sbox'+((s.acct&&s.acct.endsWith('DIP'))?' dip':'')+'" style="color:#1448cc">'+(s.origin==='manual'?'SS':'S')+'</span></div></div>';
    });
    anno.innerHTML=html;
  }
  drawAnno();ch.timeScale().subscribeVisibleLogicalRangeChange(drawAnno);ANNO_REDRAW.push(drawAnno);
  attachTooltip(ch,el,lg,new Map(rows.map(b=>[b[0],b])));
  ALL_CHARTS.push([ch,el],[rch,rel]);
}

function renderAll(){
  const t0=performance.now(); let ok=0;
  ORDER.forEach(o=>{
    const card=document.getElementById('card-'+o.idx);
    const rows=MIN5[o.code]||[];
    if(!rows.length){
      card.querySelector('.chartbox').innerHTML='<div class="empty">데이터 없음 ('+o.code+')</div>';
      return;
    }
    try{ buildIntraday(card,o.code,rows); ok++; }
    catch(e){ console.error(o.code,e);
      card.querySelector('.chartbox').innerHTML='<div class="empty">렌더 오류 ('+o.code+')</div>'; }
  });
  document.getElementById('status').textContent=
    '✅ '+ok+'/'+ORDER.length+'개 차트 렌더 ('+Math.round(performance.now()-t0)+'ms)'+
    ' · 휠=확대 드래그=이동 · 기본 '+(VIEW_2DAYS?'최근 2거래일':'당일+전일 2h')+' (5일치 내장)';
}
window.addEventListener('load', renderAll);

let __rt=null;
window.addEventListener('resize',()=>{
  clearTimeout(__rt);
  __rt=setTimeout(()=>{
    ALL_CHARTS.forEach(([ch,el])=>{try{ch.applyOptions({width:el.clientWidth,height:el.clientHeight});}catch(e){}});
    ALIGN_PAIRS.forEach(([ch,rch])=>alignScales(ch,rch));
    ANNO_REDRAW.forEach(fn=>{try{fn();}catch(e){}});
  },150);
});
"""

PAGE_TMPL = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>단타 게시판 (5분봉 · 고정 6종목)</title>
<script src="lib/lightweight-charts.standalone.production.js"></script>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:#f0f2f5; font-family:-apple-system,'Malgun Gothic',sans-serif; padding:16px; color:#1f2937; }
  .top-nav-container { display:flex; margin-bottom:10px; }
  .top-nav { display:flex; background:#2c3e50; border-radius:8px; overflow:hidden; }
  .nav-item { padding:7px 14px; color:#bdc3c7; cursor:pointer; text-decoration:none; font-size:0.85em; font-weight:bold; transition:0.2s; }
  .nav-item:hover { background:#34495e; color:#fff; }
  .nav-item.active { background:#3498db; color:white; }
  h1 { margin-bottom:4px; font-size:16px; color:#333; }
  #status { font-size:12px; color:#16a34a; font-weight:700; margin-bottom:12px; }

  /* 차트(2열) + 당일손익표(3번째 열) 가로 배치 */
  .board-wrap { display:flex; align-items:flex-start; gap:24px; }
  /* 2열 × 3행 — 차트 사이 여백(gap)은 페이지 스크롤 가능한 빈 공간 */
  .chart-grid { flex:1 1 0; min-width:0; display:grid; grid-template-columns:repeat(2,1fr); gap:18px 26px; max-width:1500px; }

  /* 당일 실현손익 표 (6행 2열) — 차트 우측 작은 사이드패널 */
  .pnl-side { flex:0 0 auto; }
  .pnl-table { border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden;
    box-shadow:0 2px 8px rgba(0,0,0,0.08); text-align:center; }
  .pnl-table caption { font-size:12px; font-weight:bold; color:#444; padding:7px 0 6px;
    background:#f8fafc; border-bottom:1px solid #eee; }
  .pnl-table td { padding:7px 16px; border-bottom:1px solid #f0f0f0; white-space:nowrap;
    font-size:13px; text-align:center; }
  .pnl-table tr:last-child td { border-bottom:none; }
  .pnl-table tr.total td { border-top:2px solid #cbd5e1; background:#f8fafc; }
  .pnl-table tr.total td.nm { font-weight:800; }
  .pnl-table td.nm { color:#000; font-weight:600; }
  .pnl-table td.pl { font-family:'JetBrains Mono',monospace; font-weight:700; }
  .chart-card { background:#fff; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.08); overflow:hidden; min-width:0; }
  .chart-title { padding:7px 10px; font-size:13px; font-weight:bold; color:#444;
    border-bottom:1px solid #eee; display:flex; align-items:center; gap:8px; white-space:nowrap; }
  .chart-title .sub { font-size:10px; font-weight:normal; color:#999; font-family:monospace; }

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
  .rchart { width:100%; height:100px; }
  .empty  { height:300px; display:flex; align-items:center; justify-content:center; color:#991b1b; font-size:12px; font-weight:700; }
  .divider { position:absolute; top:0; bottom:0; width:0; display:none; z-index:4;
    border-left:2px dashed rgba(40,40,40,.85); pointer-events:none; }
  /* S(청산) 익손절금액·%·S 오버레이 — 자동일지차트(8042_20)와 동일 */
  .anno { position:absolute; left:0; top:0; right:0; bottom:0; pointer-events:none; z-index:5; overflow:hidden; }
  .anno .s { position:absolute; transform:translate(-50%,-100%); text-align:center;
    font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; line-height:1.2;
    white-space:nowrap; text-shadow:0 0 2px #fff,0 0 2px #fff; }
  /* B(진입)/S(청산) 노란 박스 강조 — 글자크기·형태는 그대로, 노란 배경 사각박스로 가독성↑ */
  .anno .bmark { position:absolute; transform:translate(-50%,0);
    font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; line-height:1.25;
    background:#ffe600; border:1px solid #b59500; border-radius:2px; padding:0 4px; text-shadow:none; }
  .anno .sbox { display:inline-block; background:#ffe600; border:1px solid #b59500;
    border-radius:2px; padding:0 4px; line-height:1.25; text-shadow:none; }
  /* *DIP(수동 저점매수: 8042DIP·1887DIP) — 눈에 덜 띄게: 회색 반투명 + 글자만 감싸는 원형(여백없음) */
  .anno .bmark.dip, .anno .sbox.dip {
    background:rgba(140,140,140,0.5); border:1px solid rgba(110,110,110,0.5);
    border-radius:50%; padding:0; width:1.35em; height:1.35em;
    display:inline-flex; align-items:center; justify-content:center; box-sizing:border-box; }

  /* 태블릿: 2열 유지 — 가로 스크롤 */
  @media (max-width:1100px) and (min-width:769px) { body{overflow-x:auto;} .chart-grid{min-width:1000px;} }
  /* 스마트폰: 종목당 1개씩 세로 나열 + 우측 여백(차트 밖 터치로 페이지 스크롤) */
  @media (max-width:768px) {
    body { padding:10px 36px 10px 8px; }
    .board-wrap { flex-direction:column; gap:14px; }
    .chart-grid { grid-template-columns:1fr; min-width:0; gap:14px; }
    .pnl-side { align-self:flex-start; }
    .cchart { height:260px; }
    .rchart { height:90px; }
  }
</style>
</head>
<body>
__NAV__
<h1>⚡ 단타 게시판 (5분봉 · 고정 6종목 · 저/저2/X + B/S) — 갱신 __NOW__</h1>
<div id="status">렌더링 준비 중...</div>
__GRID__

<script>
(function(){
__JS__
})();
</script>
</body>
</html>
"""


def _pnl_color(v):
    # +면 빨강 / -면 파랑 / 0은 검정
    if v > 0:
        return "#e11d1d"
    if v < 0:
        return "#1d4ed8"
    return "#111111"


def build_pnl_table(pnl):
    """당일 실현손익 6행 2열 표 + 합계 행. 종목명=검정, 손익=+빨강/-파랑."""
    trs = []
    total = 0
    for code, label in PNL_TABLE:
        v = pnl.get(code, 0)
        total += v
        trs.append(
            f'<tr><td class="nm">{label}</td>'
            f'<td class="pl" style="color:{_pnl_color(v)}">{v:,}원</td></tr>')
    trs.append(
        f'<tr class="total"><td class="nm">손익</td>'
        f'<td class="pl" style="color:{_pnl_color(total)}">{total:,}원</td></tr>')
    return ('<table class="pnl-table"><caption>당일 실현손익</caption>'
            '<tbody>' + ''.join(trs) + '</tbody></table>')


def build_page(min5, trade_marks, nxt_codes, pnl):
    cards, order = [], []
    for row in ROWS:
        for code, label in row:
            idx = len(order)
            order.append({"idx": idx, "code": code, "label": label})
            cards.append(
                f'<div class="chart-card">'
                f'<div class="chart-title">{label}<span class="sub">{code}</span></div>'
                f'<div class="cwrap" id="card-{idx}">'
                f'<div class="chartbox"><div class="legend"></div><div class="cchart"></div></div>'
                f'<div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평 · 저/저2=저점신호 X=고점신호 B/S=매매</div>'
                f'<div class="rchart"></div>'
                f'</div></div>')
    grid = ('<div class="board-wrap">'
            '<div class="chart-grid">' + ''.join(cards) + '</div>'
            '<div class="pnl-side">' + build_pnl_table(pnl) + '</div>'
            '</div>')
    nav = ('<div class="top-nav-container"><div class="top-nav">'
           '<a href="main_hub.html" class="nav-item">상황판</a>'
           '<a href="order.html" class="nav-item">주문</a>'
           '<a href="summary.html" class="nav-item">요약</a>'
           '<a href="danta_chart.html" class="nav-item active">단타</a>'
           '<a href="kr_chart.html" class="nav-item">차트</a>'
           '<a href="us_summary.html" class="nav-item">미국요약</a>'
           '</div></div>')
    js = (PAGE_JS
          .replace("__MIN5__",   json.dumps(min5, ensure_ascii=False, separators=(",", ":")))
          .replace("__ORDER__",  json.dumps(order, ensure_ascii=False, separators=(",", ":")))
          .replace("__NXTSET__", json.dumps(nxt_codes))
          .replace("__TRADES__", json.dumps(trade_marks, ensure_ascii=False, separators=(",", ":"))))
    return (PAGE_TMPL
            .replace("__NAV__", nav)
            .replace("__NOW__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__GRID__", grid)
            .replace("__JS__", js))


def main():
    print("=" * 60)
    print("make_danta_chart_display.py 실행 (단타 게시판 - 고정 6종목 5분봉)")
    print("=" * 60)
    codes = [code for row in ROWS for (code, _) in row]
    sync_1887_fills_for_chart()

    print(f"[5분봉 수집] {len(codes)}종목 × {DAYS5}일치 (ka10080)")
    min5 = collect_5min(codes, days=DAYS5)
    min5 = add_trend_states(min5)
    for c in codes:
        n = len(min5.get(c, []))
        print(f"  {c:8s} {n:4d} bars" + ("" if n else "  ⚠ 데이터 없음"))

    trade_marks = build_trade_marks(set(codes))
    nxt_codes = [c for c in codes if is_nxt(c)]
    pnl = compute_today_pnl(codes)

    html = build_page(min5, trade_marks, nxt_codes, pnl)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[OK] 저장 완료: {OUT_HTML}  ({os.path.getsize(OUT_HTML)//1024} KB)")


if __name__ == "__main__":
    main()
