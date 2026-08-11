import html
import json
from datetime import datetime
from pathlib import Path


BASE = Path(r"D:\py\report-us")
REPORT_JSON = BASE / "condition_search_results.json"
OUT_HTML = BASE / "kor_condition.html"


def rate_color(value):
    try:
        v = float(value)
    except Exception:
        return "#888"
    if v > 0:
        return "#27ae60"
    if v < 0:
        return "#e74c3c"
    return "#888"


def cs_badge(value):
    try:
        v = float(str(value).replace("%", "").replace(",", ""))
        color = "#27ae60" if v >= 100 else ("#e67e22" if v >= 70 else "#e74c3c")
        return f'<span style="color:{color};font-weight:bold;">{v:.0f}%</span>'
    except Exception:
        return '<span style="color:#aaa;">-</span>'


def tv_html(value):
    try:
        num = float(value)
        if num >= 10000:
            color = "#e74c3c"
        elif num >= 5000:
            color = "#e67e22"
        elif num >= 1000:
            color = "#222"
        else:
            color = "#aaa"
        return f'<span style="color:{color};font-size:0.85em;">{num:,.0f}억</span>'
    except Exception:
        return '<span style="color:#aaa;font-size:0.85em;">-</span>'


def numeric_value(value):
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def trade_value(stock):
    return numeric_value(stock.get("price")) * numeric_value(stock.get("volume"))


def stock_row(stock):
    code = str(stock.get("code", "")).zfill(6)
    name = str(stock.get("name", "")).strip()
    short = name[:12]
    rate = stock.get("rate", 0)
    sign = "+" if isinstance(rate, (int, float)) and rate > 0 else ""
    rate_html = (
        f'<span class="stock-rate" style="color:{rate_color(rate)};">'
        f'{sign}{float(rate):.2f}%</span>'
    )

    nxt = str(stock.get("nxt", ""))
    if nxt == "NXT선":
        nxt_html = f'<span class="nxt-badge-both">{html.escape(nxt)}</span>'
    elif nxt in ("NXT", "선"):
        nxt_html = f'<span class="nxt-badge">{html.escape(nxt)}</span>'
    else:
        nxt_html = ""

    return f"""
      <div class="stock-row">
        <span class="stock-code">{html.escape(code)}</span>
        <span class="sn-amt">{tv_html(stock.get("trade_amount_eok", 0))}</span>
        {rate_html}
        <span class="stock-cs">{cs_badge(stock.get("contract_strength", "-"))}</span>
        <span class="stock-nxt">{nxt_html}</span>
        <span class="stock-name" title="{html.escape(name)}">
          <span class="chart-v4-trigger" data-code="{html.escape(code)}" data-name="{html.escape(name)}">{html.escape(short) if short else "-"}</span>
        </span>
      </div>"""


CHUNK_SIZE = 10  # 카드 1개당 종목 수. 초과분은 다음 카드로 분할 (최대 2카드).


def _card_html(seq, name, total_count, body_html, part=None):
    part_label = ""
    if part:
        part_label = f' <span class="card-part">({part[0]}/{part[1]})</span>'
    return f"""
  <div class="theme-card">
    <div class="card-header">
      <div class="card-title-line">
        <span class="cond-badge">COND</span>
        <span class="theme-name" title="{name}">[{seq}] {name}{part_label}</span>
        <span class="stk-num">{total_count}종목</span>
      </div>
      <div class="card-sub">키움 HTS 조건검색 결과</div>
    </div>
    <div class="stock-list">{body_html}</div>
  </div>"""


def render_cards(condition):
    """조건식 1개 → 카드 HTML 리스트 (종목 10개 초과 시 10개씩 최대 2카드로 분할)."""
    if not condition:
        return []

    seq = html.escape(str(condition.get("seq", "")))
    name = html.escape(str(condition.get("name", "")))
    total_count = int(condition.get("total_count") or 0)
    error = condition.get("error", "")

    if error:
        body = f'<div class="empty-note error-note">{html.escape(error)}</div>'
        return [_card_html(seq, name, total_count, body)]

    stocks = sorted(condition.get("stocks", []), key=trade_value, reverse=True)
    if not stocks:
        body = '<div class="empty-note">(종목 없음)</div>'
        return [_card_html(seq, name, total_count, body)]

    chunks = [stocks[i:i + CHUNK_SIZE] for i in range(0, len(stocks), CHUNK_SIZE)]
    chunks = chunks[:2]  # 상위 20개 = 최대 2카드
    total_parts = len(chunks)

    cards = []
    for idx, chunk in enumerate(chunks, 1):
        body = "\n".join(stock_row(stock) for stock in chunk)
        part = (idx, total_parts) if total_parts > 1 else None
        cards.append(_card_html(seq, name, total_count, body, part))
    return cards


def load_data():
    if not REPORT_JSON.exists():
        return {
            "update_time": "-",
            "conditions": [],
            "missing": True,
        }
    try:
        return json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "update_time": "-",
            "conditions": [],
            "missing": False,
            "load_error": str(exc),
        }


def main():
    data = load_data()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    by_seq = {str(c.get("seq")): c for c in data.get("conditions", [])}

    def cards_for(seq):
        return render_cards(by_seq.get(str(seq)))

    # 줄1: [0] [1] / 줄2: [4] [5(2카드)] / 줄3: [2(2카드)]
    rows = [
        cards_for("0") + cards_for("1"),
        cards_for("4") + cards_for("5"),
        cards_for("2"),
    ]
    cards_html = "\n".join(
        f'<div class="cards-row">\n{"".join(row)}\n</div>'
        for row in rows if row
    )

    if data.get("missing"):
        cards_html = '<div class="notice-box">condition_search_results.json 파일이 아직 없습니다.</div>'
    elif data.get("load_error"):
        cards_html = f'<div class="notice-box error-note">{html.escape(data["load_error"])}</div>'
    elif not cards_html:
        cards_html = '<div class="notice-box">(조건검색 결과 없음)</div>'

    update_time = html.escape(str(data.get("update_time", "-")))

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Kiwoom Condition Search</title>
<style>
body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; margin: 0; background-color: #f4f7f6; color:#2c3e50; }}
.top-nav-container {{ display: flex; margin-bottom: 15px; }}
.top-nav {{ display: flex; background-color: #2c3e50; border-radius: 8px; overflow: hidden; width: fit-content; }}
.nav-item {{ padding: 8px 15px; color: #bdc3c7; text-align: center; cursor: pointer; font-weight: bold; text-decoration: none; transition: all 0.3s; font-size: 0.9em; }}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}
.page-title {{ margin: 0 0 4px; font-size: 1.35em; color:#2c3e50; }}
.updated {{ margin:0 0 16px; color:#666; font-size:0.9em; }}
.cards-row {{ display: grid; grid-template-columns: repeat(3, 370px); gap: 12px; justify-content: flex-start; align-items: start; margin-bottom: 12px; }}
.card-part {{ color:#7f8c8d; font-size:0.85em; font-weight:600; }}
.theme-card {{
  width: 370px; background: white; border: 1px solid #ddd; border-radius: 8px;
  box-shadow: 0 2px 5px rgba(0,0,0,0.08); overflow: hidden;
}}
.card-header {{ padding: 10px 12px; background: #fafafa; border-top: 3px solid #2980b9; border-bottom: 1px solid #eee; }}
.card-title-line {{ display: flex; align-items: center; gap: 6px; min-width:0; }}
.cond-badge {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:0.72em; font-weight:bold; color:white; background:#2980b9; }}
.theme-name {{ flex: 1; min-width: 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight: 700; color:#222; }}
.stk-num {{ color:#7f8c8d; font-size:0.8em; white-space:nowrap; }}
.card-sub {{ color:#95a5a6; font-size:0.78em; margin-top:3px; }}
.stock-list {{ padding: 6px 12px; }}
.stock-row {{ display: grid; grid-template-columns: 58px 54px 60px 46px 42px minmax(110px,1fr); gap: 5px; align-items: center; padding: 4px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.85em; }}
.stock-row:last-child {{ border-bottom: none; }}
.stock-code {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; color:#2c3e50; }}
.stock-name {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.sn-amt {{ white-space:nowrap; text-align:right; }}
.chart-v4-trigger {{ font-size:0.82em; color:#2980b9; cursor:pointer; text-decoration:underline dotted; }}
.stock-rate {{ font-weight: bold; text-align:right; white-space:nowrap; }}
.stock-cs {{ font-weight: bold; text-align:right; white-space:nowrap; }}
.stock-nxt {{ text-align: right; white-space: nowrap; }}
.nxt-badge, .nxt-badge-both {{ display:inline-block; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:bold; color:white; background:#8e44ad; }}
.nxt-badge-both {{ background:#1a1a1a; }}
.empty-note {{ color:#95a5a6; font-size:0.85em; padding: 8px 0; }}
.error-note {{ color:#e74c3c; }}
.notice-box {{ background:white; border-left:5px solid #e67e22; padding:14px 16px; border-radius:8px; box-shadow:0 2px 5px rgba(0,0,0,0.08); }}
#naverChartPopup {{
  display:none; position:fixed; z-index:99999; width:860px; background:#fff;
  border:1px solid #bdc3c7; border-radius:10px; padding:12px; box-shadow:0 10px 28px rgba(0,0,0,0.22);
  pointer-events:auto; max-height:90vh; overflow-y:auto;
}}
body.naver-popup-open {{ overflow:hidden; }}
#naverPopupClose {{ display:flex; align-items:center; justify-content:center; width:28px; height:28px; border:none; background:#e74c3c; color:white; border-radius:50%; font-size:18px; cursor:pointer; flex-shrink:0; }}
.popup-header {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }}
.popup-title {{ font-weight:700; color:#2c3e50; font-size:14px; white-space:nowrap; }}
.popup-link {{ font-size:12px; color:#2980b9; text-decoration:none; white-space:nowrap; margin-left:1em; }}
.charts-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.chart-card {{ border:1px solid #e5e7eb; border-radius:8px; overflow:hidden; background:#fafafa; }}
.chart-lab {{ font-size:11px; font-weight:700; color:#64748b; padding:5px 8px 2px; }}
.chart-wrap {{ position:relative; width:100%; height:285px; background:white; }}
.chart-wrap img {{ width:100%; height:100%; display:block; object-fit:fill; background:white; }}
.chart-loading {{ display:none; position:absolute; inset:0; background:rgba(255,255,255,0.75); align-items:center; justify-content:center; font-size:12px; color:#64748b; }}
.chart-loading.show {{ display:flex; }}
@media (max-width: 1040px) {{
  .cards-row {{ grid-template-columns: repeat(2, 370px); }}
}}
@media (max-width: 720px) {{
  .cards-row {{ grid-template-columns: 1fr; }}
  .theme-card {{ width: auto; }}
}}
@media (max-width: 600px) {{
  body {{ padding: 12px; }}
  .cards-row {{ grid-template-columns: 1fr; }}
  .theme-card {{ width: 100%; }}
  .top-nav-container, .top-nav {{ width: 100%; }}
  .nav-item {{ flex:1; padding:8px 8px; }}
}}
@media (max-width: 767px) {{
  #naverChartPopup {{ left:2vw !important; top:50% !important; transform:translateY(-50%); width:96vw !important; max-height:80dvh !important; padding:8px !important; box-sizing:border-box; }}
  .charts-grid {{ grid-template-columns:1fr; gap:6px; }}
  .chart-wrap {{ height:220px; }}
}}
@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
</style>
</head>
<body>
<div class="top-nav-container">
  <div class="top-nav">
    <a href="kor_volume.html" class="nav-item">거래대금</a>
    <a href="danta_journal.html" class="nav-item">매매일지</a>
    <a href="kor_volume_spike.html" class="nav-item">거래량 급증</a>
    <a href="kor_condition.html" class="nav-item active">한국조건검색</a>
    <a href="us_condition.html" class="nav-item">미국조건검색</a>
  </div>
</div>
<h1 class="page-title">키움조건검색</h1>
<p class="updated">데이터: {update_time} &nbsp;|&nbsp; 페이지: {now}</p>
{cards_html}
<div id="naverChartPopup">
  <div class="popup-header">
    <button id="naverPopupClose">&#x2715;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 종목 페이지</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><div class="chart-lab">일봉</div><div class="chart-wrap"><img id="imgDaily" alt="일봉 차트"><div class="chart-loading" id="loadingDaily">불러오는 중...</div></div></div>
    <div class="chart-card"><div class="chart-lab">주봉</div><div class="chart-wrap"><img id="imgWeekly" alt="주봉 차트"><div class="chart-loading" id="loadingWeekly">불러오는 중...</div></div></div>
  </div>
</div>
<script>
(function () {{
  var popup=document.getElementById('naverChartPopup'),popupTitle=document.getElementById('popupTitle'),popupLink=document.getElementById('popupLink');
  var imgDaily=document.getElementById('imgDaily'),imgWeekly=document.getElementById('imgWeekly');
  var loadingDaily=document.getElementById('loadingDaily'),loadingWeekly=document.getElementById('loadingWeekly');
  var closeBtn=document.getElementById('naverPopupClose'),hoverTimer=null,pinned=false;
  function openPopup(){{popup.style.display='block';document.body.classList.add('naver-popup-open');}}
  function closePopup(){{popup.style.display='none';document.body.classList.remove('naver-popup-open');pinned=false;}}
  function withTs(u){{return u+'?t='+Date.now();}}
  function dailyCandleUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'+c+'.png');}}
  function weeklyCandleUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/week/'+c+'.png');}}
  function itemPageUrl(c){{return 'https://finance.naver.com/item/main.naver?code='+c;}}
  function loadInto(img,ld,url){{ld.classList.add('show');var p=new Image();p.onload=function(){{img.src=url;ld.classList.remove('show');}};p.onerror=function(){{img.removeAttribute('src');ld.classList.remove('show');}};p.src=url;}}
  function loadCharts(code,name){{popupTitle.textContent=code+'  '+(name||'');popupLink.href=itemPageUrl(code);loadInto(imgDaily,loadingDaily,dailyCandleUrl(code));loadInto(imgWeekly,loadingWeekly,weeklyCandleUrl(code));}}
  function placePopup(cx,cy){{if(window.innerWidth<=767)return;var rW=Math.min(860,window.innerWidth-20),rH=430,x=cx+18,y=cy+18;if(x+rW>window.innerWidth-8)x=cx-rW-12;if(y+rH>window.innerHeight-8)y=cy-rH-12;if(x<8)x=8;if(y<8)y=8;popup.style.left=x+'px';popup.style.top=y+'px';popup.style.transform='none';}}
  if(closeBtn)closeBtn.addEventListener('click',closePopup);
  popup.addEventListener('mouseenter',function(){{pinned=true;}});
  popup.addEventListener('mouseleave',function(){{pinned=false;closePopup();}});
  document.querySelectorAll('.naver-trigger[data-code]').forEach(function(el){{
    el.addEventListener('mouseenter',function(e){{var code=el.dataset.code,name=el.dataset.name||'';clearTimeout(hoverTimer);hoverTimer=setTimeout(function(){{placePopup(e.clientX,e.clientY);openPopup();loadCharts(code,name);}},140);}});
    el.addEventListener('mousemove',function(e){{if(popup.style.display==='block'&&!pinned)placePopup(e.clientX,e.clientY);}});
    el.addEventListener('mouseleave',function(){{clearTimeout(hoverTimer);setTimeout(function(){{if(!pinned)closePopup();}},120);}});
    el.addEventListener('click',function(e){{e.stopPropagation();placePopup(e.clientX,e.clientY);openPopup();loadCharts(el.dataset.code,el.dataset.name||'');}});
  }});
  document.addEventListener('click',function(e){{if(popup.style.display==='block'&&!popup.contains(e.target)&&!e.target.closest('.naver-trigger'))closePopup();}});
  // === D/S 단축키 (D/↓=다음, S/↑=이전, Tab/ESC=닫기) · PNG라 A(슈퍼트렌드)는 제외 ===
  (function(){{
    var SEL = '.naver-trigger[data-code]';
    var curEl = null;
    document.querySelectorAll(SEL).forEach(function(el){{
      el.addEventListener('mouseenter', function(){{ curEl = el; }});
      el.addEventListener('click', function(){{ curEl = el; }});
    }});
    try {{ popup.setAttribute('tabindex','-1'); }} catch(e){{}}
    var _open = openPopup;
    openPopup = function(){{ _open.apply(this, arguments);
      try {{ if (document.activeElement === document.body || document.activeElement === null) popup.focus({{preventScroll:true}}); }} catch(e){{}} }};
    function unpinOnMove(e){{ if (popup.contains(e.target)) return;
      document.removeEventListener('mousemove', unpinOnMove); pinned = false;
      setTimeout(function(){{ if (!pinned) closePopup(); }}, 120); }}
    function kbPin(){{ pinned = true;
      document.removeEventListener('mousemove', unpinOnMove);
      document.addEventListener('mousemove', unpinOnMove); }}
    /* === SWIPE-NAV-INJECTED: 모바일 좌/우 스와이프 → 키보드 D/S 재사용 (PC 무영향) === */
    (function(){{
      if(window.__swipeNavInit) return; window.__swipeNavInit=true;
      function isTouch(){{ return window.matchMedia('(hover: none)').matches || window.innerWidth<=767; }}
      var sx=0, sy=0, st=0, tr=false;
      document.addEventListener('touchstart', function(e){{
        if(!isTouch() || !e.touches || e.touches.length!==1){{ tr=false; return; }}
        var t=e.touches[0]; sx=t.clientX; sy=t.clientY; st=Date.now(); tr=true;
      }}, true);
      document.addEventListener('touchend', function(e){{
        if(!tr) return; tr=false;
        var t=e.changedTouches && e.changedTouches[0]; if(!t) return;
        var dx=t.clientX-sx, dy=t.clientY-sy, dt=Date.now()-st;
        if(dt>800 || Math.abs(dx)<55 || Math.abs(dx)<Math.abs(dy)*1.6) return;
        var key = dx<0 ? 'd' : 's';
        try{{ document.dispatchEvent(new KeyboardEvent('keydown', {{key:key, bubbles:true, cancelable:true}})); }}catch(err){{}}
      }}, true);
    }})();
    document.addEventListener('keydown', function(e){{
      if (popup.style.display !== 'block') return;
      var tg = e.target, tag = tg && tg.tagName;
      if (tag==='INPUT'||tag==='TEXTAREA'||(tg&&tg.isContentEditable)) return;
      var k = e.key;
      if (k==='Tab'||k==='Escape'){{ e.preventDefault(); closePopup(); return; }}
      var dir = 0;
      if (k==='s'||k==='S'||k==='ArrowUp') dir=-1;
      else if (k==='d'||k==='D'||k==='ArrowDown') dir=1;
      if (dir===0 || !curEl) return;
      e.preventDefault();
      var all = Array.prototype.slice.call(document.querySelectorAll(SEL));
      var i = all.indexOf(curEl);
      if (i<0) return;
      i += dir;
      if (i<0||i>=all.length) return;
      var nt = all[i];
      kbPin(); curEl = nt;
      loadCharts(nt.dataset.code, nt.dataset.name||'');
      nt.scrollIntoView({{block:'nearest'}});
    }});
  }})();
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
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] kor_condition.html updated at {OUT_HTML} (V4 차트 {_codes and len(_codes) or 0}종목)")


if __name__ == "__main__":
    main()
