# make_index_coin.py
# 코인 게시판 - 카드섹션 + 테이블 (요약 게시판 형태)
# 입력: D:\py\coin\0txt\report_coin.json  (upbit_total.py 가 생성)
# 출력: D:\py\report-us\coin.html

import json
from pathlib import Path
from datetime import datetime

JSON_PATH = Path(r"D:\py\coin\0txt\report_coin.json")
OUT_HTML  = Path(r"D:\py\report-us\coin.html")

UPBIT_URL = "https://www.upbit.com/exchange?code=CRIX.UPBIT.KRW-{sym}"


# ── 유틸 ────────────────────────────────────────────────────────────────────
def fmt_value(won):
    """원 단위 거래대금 → 억/조 단위 문자열"""
    try:
        won = float(won)
    except (TypeError, ValueError):
        return "-"
    if won >= 1e12:
        return f"{won/1e12:.2f}조"
    if won >= 1e8:
        return f"{won/1e8:,.0f}억"
    return f"{won:,.0f}"


def sym_link(sym, name=""):
    import html as _html
    href = UPBIT_URL.format(sym=sym)
    dn = f' data-name="{_html.escape(name)}"' if name else ""
    return (f'<a class="sym" data-coin="{_html.escape(sym)}"{dn} '
            f'href="{href}" target="_blank" rel="noopener">{_html.escape(sym)}</a>')


def new_sig_html(text):
    if not text or text == "-":
        return ""
    return f'<span class="newsig">{text}</span>'


def sco_class(sco):
    try:
        sco = float(sco)
    except (TypeError, ValueError):
        return ""
    if sco >= 12:
        return "sco-hi"
    if sco < 0:
        return "sco-lo"
    return "sco-mid"


# ── 카드 (Row1) ─────────────────────────────────────────────────────────────
def card_distribution(d):
    total    = d.get("total", 0)
    analyzed = d.get("analyzed", 0)
    rows = [
        ("sco ≥ 12", d.get("strong", 0),  d.get("strong_pct", 0),  "bar-hi"),
        ("0 ~ 12",   d.get("neutral", 0), d.get("neutral_pct", 0), "bar-mid"),
        ("sco < 0",  d.get("weak", 0),    d.get("weak_pct", 0),    "bar-lo"),
    ]
    body = (f'<div class="dist-head">전체 <b>{total}</b>개 / 분석 '
            f'<b>{analyzed}</b>개</div>')
    for label, cnt, pct, cls in rows:
        body += (
            '<div class="dist-row">'
            f'<span class="dist-label">{label}</span>'
            '<span class="dist-barwrap">'
            f'<span class="dist-bar {cls}" style="width:{max(pct,2)}%"></span>'
            '</span>'
            f'<span class="dist-cnt">{cnt}개 <small>({pct}%)</small></span>'
            '</div>'
        )
    return card("📊 SCO 기준 종목 분포", "#34495e", body, raw=True, cls="card-dist")


def card_symbol_list(title, color, items, value_key="value"):
    """심볼+종목명+거래대금 리스트 카드 (SPOT/주도주)"""
    if not items:
        return card(title, color, '<div class="empty">없음</div>', raw=True)
    rows = ""
    for it in items[:10]:
        val = fmt_value(it.get(value_key)) if value_key else ""
        rows += (
            '<div class="lirow">'
            f'<span class="liname">{sym_link(it["symbol"], it.get("name",""))} '
            f'<small>{it.get("name","")}</small></span>'
            f'<span class="lival">{val}</span>'
            '</div>'
        )
    return card(title, color, rows, raw=True)


def card_high52w(items):
    if not items:
        return card("📈 52주 신고가 근접", "#16a085",
                    '<div class="empty">없음</div>', raw=True)
    chips = "".join(f'<span class="chip">{sym_link(s)}</span>' for s in items)
    return card("📈 52주 신고가 근접", "#16a085",
                f'<div class="chips">{chips}</div>', raw=True)


# ── 테이블 (Row2 / Row3) ────────────────────────────────────────────────────
def table_top10(items):
    if not items:
        return card("🏅 Sco Top10", "#2c3e50",
                    '<div class="empty">없음</div>', raw=True)
    head = ('<tr><th>심볼</th><th>종목명</th><th class="r">SCO</th>'
            '<th class="r">수익률</th><th>신호</th></tr>')
    body = ""
    for it in items[:10]:
        rtn = it.get("rtn", 0)
        rtn_cls = "up" if rtn > 0 else ("down" if rtn < 0 else "")
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{it.get("name","")}</td>'
            f'<td class="r {sco_class(it.get("sco"))}">{it.get("sco","")}</td>'
            f'<td class="r {rtn_cls}">{rtn:+.2f}%</td>'
            f'<td>{new_sig_html(it.get("new_signal"))}</td></tr>'
        )
    return card("🏅 Sco Top10", "#2c3e50",
                f'<table class="t">{head}{body}</table>', raw=True)


def table_signal(title, color, items):
    """심볼/종목명/거래대금/SCO 테이블 (LIME/MOM/Rocket/GANN/JUNG)"""
    if not items:
        return card(title, color, '<div class="empty">없음</div>', raw=True)
    head = ('<tr><th>심볼</th><th>종목명</th>'
            '<th class="r">거래대금</th><th class="r">SCO</th></tr>')
    body = ""
    for it in items[:10]:
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{it.get("name","")}</td>'
            f'<td class="r">{fmt_value(it.get("value"))}</td>'
            f'<td class="r {sco_class(it.get("sco"))}">{it.get("sco","")}</td></tr>'
        )
    return card(title, color, f'<table class="t">{head}{body}</table>', raw=True)


def table_low(items):
    if not items:
        return card("📉 LOW 저점 신호", "#e67e22",
                    '<div class="empty">없음</div>', raw=True)
    head = ('<tr><th>심볼</th><th>종목명</th>'
            '<th class="r">거래대금</th><th class="c">저</th><th class="c">저2</th></tr>')
    body = ""
    for it in items[:10]:
        jeo  = it.get("jeo", "-")
        jeo2 = it.get("jeo2", "-")
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{it.get("name","")}</td>'
            f'<td class="r">{fmt_value(it.get("value"))}</td>'
            f'<td class="c">{"🔵" if jeo!="-" else ""}</td>'
            f'<td class="c">{"🟣" if jeo2!="-" else ""}</td></tr>'
        )
    return card("📉 LOW 저점 신호", "#e67e22",
                f'<table class="t">{head}{body}</table>', raw=True)


# ── 카드 래퍼 ───────────────────────────────────────────────────────────────
def card(title, color, body, raw=False, cls=""):
    return (
        f'<div class="card {cls}" style="border-top:3px solid {color};">'
        f'<div class="card-title" style="color:{color};">{title}</div>'
        f'<div class="card-body">{body}</div></div>'
    )


# ── 차트 hover 팝업 JS ───────────────────────────────────────────────────────
# 종목 심볼(.sym[data-coin])에 마우스 → 업비트 일봉 캔들 직접 fetch → lightweight-charts.
# 업비트 캔들 API는 Access-Control-Allow-Origin:* 라 브라우저에서 직접 호출 가능.
POPUP_JS = r"""
(function(){
  var LWC = window.LightweightCharts;
  if(!LWC){ return; }
  var UP="#d32f2f", DOWN="#1565c0";
  var pop=document.getElementById('coinpop');
  var elTitle=pop.querySelector('.cp-title');
  var elSub=pop.querySelector('.cp-sub');
  var elChart=pop.querySelector('.cp-chart');
  // MA5·20·60·120 4개 라인 시리즈
  var MA_DEFS=[[5,'#e91e63'],[20,'#16a34a'],[60,'#2563eb'],[120,'#9333ea']];
  var cache={}, chart=null, cs=null, vol=null, maLines=[];
  var curSym=null, pinned=false, closeTimer=null, openTimer=null;
  var hoverless = window.matchMedia('(hover: none)').matches;

  function fmtP(v){
    if(v>=1000) return Math.round(v).toLocaleString();
    if(v>=1)    return v.toFixed(2);
    return v.toPrecision(4);
  }
  function ensureChart(){
    if(chart) return;
    chart=LWC.createChart(elChart,{width:elChart.clientWidth,height:elChart.clientHeight,
      layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
      grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
      rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.08,bottom:0.25}},
      timeScale:{borderColor:'#ddd',rightOffset:3,minBarSpacing:0.4},
      localization:{priceFormatter:fmtP},
      crosshair:{mode:LWC.CrosshairMode.Normal}});
    cs=chart.addCandlestickSeries({upColor:UP,downColor:DOWN,borderUpColor:UP,
      borderDownColor:DOWN,wickUpColor:UP,wickDownColor:DOWN});
    vol=chart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'',color:'#cfd8dc'});
    vol.priceScale().applyOptions({scaleMargins:{top:0.84,bottom:0}});
    // MA 4개 생성
    maLines=[];
    MA_DEFS.forEach(function(def){
      maLines.push(chart.addLineSeries({color:def[1],lineWidth:1,
        priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}));
    });
  }
  function smaSeries(rows,n){
    var out=[],sum=0;
    for(var i=0;i<rows.length;i++){
      sum+=rows[i].close;
      if(i>=n) sum-=rows[i-n].close;
      if(i>=n-1) out.push({time:rows[i].time,value:+(sum/n).toFixed(6)});
    }
    return out;
  }
  function load(sym){
    if(cache[sym]) return Promise.resolve(cache[sym]);
    var url='https://api.upbit.com/v1/candles/days?market=KRW-'+sym+'&count=300';
    return fetch(url).then(function(r){return r.json();}).then(function(j){
      var rows=j.slice().reverse().map(function(d){return{
        time:d.candle_date_time_kst.slice(0,10),
        open:d.opening_price,high:d.high_price,low:d.low_price,close:d.trade_price,
        volume:d.candle_acc_trade_volume};});
      cache[sym]=rows;
      return rows;
    });
  }
  function show(sym,name){
    curSym=sym;
    ensureChart();
    elTitle.textContent=(name?name+' ':'')+'('+sym+'/KRW)';
    elSub.textContent='';
    load(sym).then(function(rows){
      if(curSym!==sym) return;            // 그 사이 다른 종목으로 이동
      cs.setData(rows.map(function(r){return{time:r.time,open:r.open,high:r.high,low:r.low,close:r.close};}));
      vol.setData(rows.map(function(d){return{time:d.time,value:d.volume,
        color:d.close>=d.open?'rgba(211,47,47,0.35)':'rgba(21,101,192,0.35)'};}));
      // MA 4개 데이터 세팅
      MA_DEFS.forEach(function(def,i){
        maLines[i].setData(smaSeries(rows,def[0]));
      });
      // 최근 252봉(약 1년) 범위로 표시
      var total=rows.length, from=Math.max(0,total-252);
      chart.timeScale().setVisibleRange({from:rows[from].time,to:rows[total-1].time});
      if(rows.length>=2){
        var c=rows[rows.length-1].close, p=rows[rows.length-2].close;
        var pct=(c/p-1)*100;
        elSub.textContent=fmtP(c)+'원  '+(pct>=0?'+':'')+pct.toFixed(2)+'%';
        elSub.style.color=pct>=0?UP:DOWN;
      }
    }).catch(function(){
      if(curSym===sym) elTitle.textContent=sym+' — 차트 로드 실패';
    });
  }
  function place(x,y){
    var w=pop.offsetWidth||560, h=pop.offsetHeight||340;
    var px=x+18, py=y+18;
    if(px+w>window.innerWidth-8)  px=x-w-12;
    if(py+h>window.innerHeight-8) py=window.innerHeight-h-8;
    if(px<8)px=8; if(py<8)py=8;
    pop.style.left=px+'px'; pop.style.top=py+'px';
  }
  function openPop(){ pop.style.display='block'; }
  function closePop(){ pop.style.display='none'; curSym=null; pinned=false; }
  function cancelClose(){ if(closeTimer){clearTimeout(closeTimer);closeTimer=null;} }
  function scheduleClose(){ cancelClose(); closeTimer=setTimeout(function(){ if(!pinned) closePop(); },180); }

  document.querySelectorAll('.sym[data-coin]').forEach(function(a){
    a.addEventListener('mouseenter',function(e){
      if(hoverless) return;
      cancelClose();
      var x=e.clientX, y=e.clientY, sym=a.dataset.coin, name=a.dataset.name||'';
      clearTimeout(openTimer);
      openTimer=setTimeout(function(){ openPop(); place(x,y); show(sym,name); },60);
    });
    a.addEventListener('mouseleave',function(){ clearTimeout(openTimer); scheduleClose(); });
    a.addEventListener('click',function(e){
      if(hoverless){ e.preventDefault(); openPop(); pinned=true;
        var r=a.getBoundingClientRect(); place(r.left, r.bottom);
        show(a.dataset.coin, a.dataset.name||''); }
    });
  });
  pop.addEventListener('mouseenter',function(){ pinned=true; cancelClose(); });
  pop.addEventListener('mouseleave',function(){ pinned=false; scheduleClose(); });
  document.addEventListener('click',function(e){
    if(pop.style.display!=='block') return;
    if(pop.contains(e.target)) return;
    if(e.target.closest && e.target.closest('.sym[data-coin]')) return;
    closePop();
  });
  window.addEventListener('resize',function(){
    if(chart && pop.style.display==='block'){ chart.resize(elChart.clientWidth,elChart.clientHeight); }
  });
})();
"""


# ── 빌드 ────────────────────────────────────────────────────────────────────
def build_html(data):
    dist = data.get("distribution", {})
    gen  = data.get("generated_at", "")
    popup_js = POPUP_JS

    row1 = "".join([
        card_distribution(dist),
        card_symbol_list("💥 SPOT 신호 종목", "#e74c3c", data.get("spot", [])),
        card_symbol_list("🏆 주도주 신호 종목", "#f39c12", data.get("leader", [])),
        card_high52w(data.get("high52w", [])),
    ])
    row2 = "".join([
        table_top10(data.get("top10", [])),
        table_signal("🟢 LIME 신호 종목", "#2ecc71", data.get("lime", [])),
        table_signal("⭐ MOM 신호 종목", "#3498db", data.get("mom", [])),
        table_signal("🚀 Rocket(inv3) 신호 종목", "#9b59b6", data.get("rocket", [])),
    ])
    row3 = "".join([
        table_low(data.get("low", [])),
        table_signal("🔥 GANN 불기둥 신호 종목", "#c0392b", data.get("gann", [])),
        table_signal("🔥 JUNG 정배열 신호 종목", "#27ae60", data.get("jung", [])),
    ])

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>코인</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
    background: #f4f7f6; color: #2c3e50;
  }}
  .page-head {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }}
  .page-head h1 {{ font-size: 1.4rem; margin: 0; }}
  .page-head .ts {{ font-size: 0.8rem; color: #7f8c8d; }}

  .grid {{ display: grid; gap: 12px; margin-bottom: 12px; justify-content: start; }}
  /* 분포 카드만 고정폭, 나머지는 내용에 맞춰 폭 축소 + 좌측 정렬 */
  .grid-row1 {{ grid-template-columns: 280px repeat(3, minmax(150px, max-content)); }}
  .grid-row2 {{ grid-template-columns: repeat(4, minmax(150px, max-content)); }}
  .grid-row3 {{ grid-template-columns: repeat(3, minmax(150px, max-content)); }}

  .card {{
    background: #fff; border-radius: 8px; padding: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    display: flex; flex-direction: column; min-width: 0;
  }}
  .card-title {{ font-size: 0.92rem; font-weight: 700; margin-bottom: 8px; }}
  .card-body {{ font-size: 0.82rem; }}
  .empty {{ color: #bdc3c7; font-size: 0.8rem; padding: 6px 0; }}

  /* 분포 카드 */
  .dist-head {{ font-size: 0.82rem; color: #555; margin-bottom: 8px; }}
  .dist-row {{ display: flex; align-items: center; gap: 6px; margin: 5px 0; font-size: 0.78rem; }}
  .dist-label {{ width: 52px; color: #555; flex-shrink: 0; }}
  .dist-barwrap {{ flex: 1; background: #eef0f1; border-radius: 4px; height: 12px; overflow: hidden; }}
  .dist-bar {{ display: block; height: 100%; border-radius: 4px; }}
  .bar-hi {{ background: #2ecc71; }}
  .bar-mid {{ background: #95a5a6; }}
  .bar-lo {{ background: #e74c3c; }}
  .dist-cnt {{ width: 78px; text-align: right; flex-shrink: 0; }}
  .dist-cnt small {{ color: #95a5a6; }}

  /* 심볼 리스트 카드 */
  .lirow {{ display: flex; justify-content: space-between; align-items: center; padding: 3px 0; border-bottom: 1px solid #f2f4f4; }}
  .lirow:last-child {{ border-bottom: none; }}
  .liname {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 11em; }}
  .liname small {{ color: #95a5a6; font-size: 0.72rem; }}
  .lival {{ color: #34495e; font-size: 0.78rem; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{ background: #eafaf1; border-radius: 12px; padding: 3px 10px; font-size: 0.78rem; }}

  /* 테이블 */
  table.t {{ width: 100%; border-collapse: collapse; font-size: 0.76rem; }}
  table.t th {{ text-align: left; color: #95a5a6; font-weight: 600; padding: 3px 4px; border-bottom: 1px solid #ecf0f1; font-size: 0.72rem; }}
  table.t td {{ padding: 4px 4px; border-bottom: 1px solid #f6f7f8; }}
  table.t tr:last-child td {{ border-bottom: none; }}
  table.t .r {{ text-align: right; }}
  table.t .c {{ text-align: center; }}
  table.t .nm {{ color: #555; max-width: 7em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

  a.sym {{ font-weight: 700; color: #2980b9; text-decoration: none; }}
  a.sym:hover {{ text-decoration: underline; }}
  .up {{ color: #e74c3c; }}
  .down {{ color: #2980b9; }}
  .sco-hi {{ color: #27ae60; font-weight: 700; }}
  .sco-lo {{ color: #e74c3c; }}
  .sco-mid {{ color: #7f8c8d; }}
  .newsig {{ font-size: 0.72rem; }}

  /* 차트 hover 팝업 */
  #coinpop {{
    position: fixed; z-index: 9999; display: none;
    width: 560px; max-width: 92vw;
    background: #fff; border: 1px solid #d8dde0; border-radius: 8px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.18); padding: 8px 10px;
  }}
  #coinpop .cp-head {{ display: flex; justify-content: space-between; align-items: baseline;
    gap: 8px; margin-bottom: 4px; }}
  #coinpop .cp-title {{ font-weight: 700; font-size: 0.86rem; color: #2c3e50; }}
  #coinpop .cp-sub {{ font-size: 0.8rem; font-weight: 600; white-space: nowrap; }}
  #coinpop .cp-chart {{ width: 100%; height: 300px; }}
  #coinpop .cp-legend {{ display: flex; gap: 10px; margin-top: 4px; flex-wrap: wrap; }}
  #coinpop .cp-legend span {{ font-size: 0.7rem; font-family: monospace; display: flex; align-items: center; gap: 3px; }}
  #coinpop .cp-legend i {{ display: inline-block; width: 18px; height: 2px; border-radius: 1px; }}
  @media (max-width: 767px) {{
    #coinpop {{ width: 94vw; left: 3vw !important; }}
    #coinpop .cp-chart {{ height: 240px; }}
  }}

  @media (max-width: 900px) {{
    .grid {{ justify-content: stretch; }}
    .grid-row1, .grid-row2, .grid-row3 {{ grid-template-columns: 1fr 1fr; }}
  }}
  @media (max-width: 560px) {{
    .grid {{ justify-content: stretch; }}
    .grid-row1, .grid-row2, .grid-row3 {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
  <div class="page-head">
    <h1>₿ 코인</h1>
    <span class="ts">업데이트: {gen}</span>
  </div>

  <div class="grid grid-row1">{row1}</div>
  <div class="grid grid-row2">{row2}</div>
  <div class="grid grid-row3">{row3}</div>

  <div id="coinpop">
    <div class="cp-head">
      <span class="cp-title">-</span>
      <span class="cp-sub"></span>
    </div>
    <div class="cp-chart"></div>
    <div class="cp-legend">
      <span><i style="background:#e91e63"></i>MA5</span>
      <span><i style="background:#16a34a"></i>MA20</span>
      <span><i style="background:#2563eb"></i>MA60</span>
      <span><i style="background:#9333ea"></i>MA120</span>
    </div>
  </div>

  <script src="lib/lightweight-charts.standalone.production.js"></script>
  <script>
{popup_js}
  </script>
</body>
</html>
"""


def main():
    if not JSON_PATH.exists():
        print(f"❌ {JSON_PATH} 없음 — upbit_total.py 먼저 실행하세요.")
        return
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    html = build_html(data)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"✅ coin.html 생성 완료 → {OUT_HTML}")


if __name__ == "__main__":
    main()
