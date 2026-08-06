# make_index_volume_spike.py
import html
from pathlib import Path
from datetime import datetime

BASE = Path(r"D:\py\report-us")
REPORT_TXT = BASE / "report_volume_spike.txt"
OUT_HTML = BASE / "kor_volume_spike.html"

def format_number(s):
    try:
        if not s.strip().replace(',','').replace('.','').replace('-','').isdigit():
            return s
        val = int(s.replace(',', ''))
        return f"{val:,}"
    except:
        return s

def text_to_html_table(text):
    if not text or text.strip().startswith("데이터 없음"):
        return f'<p>{html.escape(text)}</p>'
    
    raw_lines = text.strip().splitlines()
    if not raw_lines: return ""

    html_output = ['<table class="styled-table" id="volumeSpikeTable">']
    html_output.append(
        "<thead><tr>"
        "<th>종목코드</th><th>종목명</th><th>등락률</th>"
        "<th>전일거래량</th><th>현재거래량</th>"
        '<th class="nxt-header" onclick="sortByNXT()" title="클릭하여 NXT 정렬">NXT ⇅</th>'
        "</tr></thead>"
    )
    html_output.append("<tbody>")
    
    for line in raw_lines:
        if "저장 완료" in line or not line.strip(): continue
        cols = line.split("\t")
        if len(cols) < 5: continue

        code     = cols[0]
        name     = cols[1]
        rate     = cols[2]
        prev_vol = cols[3]
        now_vol  = cols[4]
        nxt      = cols[5].strip() if len(cols) >= 6 else ""

        row_html = "<tr>"
        row_html += f'<td class="code-col" data-code="{html.escape(code)}" data-name="{html.escape(name)}">{html.escape(code)}</td>'
        row_html += f'<td>{html.escape(name)}</td>'
        
        color = "black"
        if "+" in rate: color = "#27ae60"
        elif "-" in rate: color = "#e74c3c"
        
        row_html += f'<td style="color: {color}; font-weight: bold;">{html.escape(rate)}</td>'
        row_html += f'<td>{html.escape(format_number(prev_vol))}</td>'
        row_html += f'<td style="font-weight: bold;">{html.escape(format_number(now_vol))}</td>'

        if nxt == "NXT":
            row_html += '<td class="nxt-cell"><span style="color:#8e44ad; font-weight:bold;">NXT</span></td>'
        else:
            row_html += '<td class="nxt-cell"></td>'

        row_html += "</tr>"
        html_output.append(row_html)
        
    html_output.append("</tbody></table>")
    return "\n".join(html_output)

def main():
    text = ""
    if REPORT_TXT.exists():
        raw_data = REPORT_TXT.read_bytes()
        
        if raw_data.startswith(b'\xef\xbb\xbf'):
            raw_data = raw_data[3:]

        encodings = ["utf-8", "cp949", "utf-16", "utf-8-sig"]
        for enc in encodings:
            try:
                temp_text = raw_data.decode(enc)
                if any(k in temp_text for k in ["에이엔피", "저장 완료", "종목명", "거래"]):
                    text = temp_text
                    break
            except:
                continue
        
        if not text:
            for enc in encodings:
                try:
                    text = raw_data.decode(enc)
                    break
                except:
                    continue

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Korea Volume Spike</title>
<style>
body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; margin: 0; background-color: #f4f7f6; }}
.header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
.header h1 {{ margin: 0; font-size: 1.8em; }}
.styled-table {{ width: auto; min-width: 580px; border-collapse: collapse; margin: 10px 0; font-size: 14px; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }}
.styled-table thead tr {{ background-color: #3498db; color: #ffffff; text-align: left; }}
.styled-table th, .styled-table td {{ padding: 10px 15px; border-bottom: 1px solid #eee; white-space: nowrap; }}
.styled-table td.code-col {{ width: 80px; font-weight: bold; font-family: monospace; }}
.styled-table tbody tr:nth-of-type(even) {{ background-color: #f9f9f9; }}
.nxt-header {{
  cursor: pointer;
  background-color: #2980b9 !important;
  user-select: none;
  text-align: center;
}}
.nxt-header:hover {{ background-color: #1a6a9a !important; }}
.nxt-cell {{ text-align: center; width: 50px; }}
.top-nav-container {{ display: flex; margin-bottom: 12px; }}
.top-nav {{ display: flex; background-color: #2c3e50; border-radius: 8px; overflow: hidden; width: fit-content; }}
.nav-item {{ padding: 8px 15px; color: #bdc3c7; text-align: center; cursor: pointer; font-weight: bold; text-decoration: none; transition: all 0.3s; font-size: 0.9em; }}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}
@media (max-width: 600px) {{
  .header h1 {{ font-size: 1.2em; }}
  .styled-table {{ font-size: 11px; min-width: 100%; }}
  .styled-table th, .styled-table td {{ padding: 4px 5px; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
/* === Naver Chart Popup === */
#naverChartPopup {{
  display: none; position: fixed; z-index: 99999;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; max-height: 90vh; overflow-y: auto;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border: none;
  background: #e74c3c; color: white; border-radius: 50%;
  font-size: 18px; cursor: pointer; flex-shrink: 0;
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
/* 스마트폰: 팝업 화면 중앙 고정, 차트 상하 배치 */
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

/* 태블릿 */
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
  .charts-grid {{ grid-template-columns: 1fr; }}
  .chart-wrap {{ height: 260px; }}
}}
</style>
</head>
<body>

<div class="top-nav-container">
    <div class="top-nav">
        <a href="kor_volume.html" class="nav-item">거래대금</a>
        <a href="danta_journal.html" class="nav-item">매매일지</a>
        <a href="kor_volume_spike.html" class="nav-item active">거래량 급증</a>
        <a href="kor_condition.html" class="nav-item">한국조건검색</a>
        <a href="us_condition.html" class="nav-item">미국조건검색</a>
    </div>
</div>

<p style="margin: 0 0 10px 0; color: #000; font-size: 0.9em;">업데이트: {now}</p>
{text_to_html_table(text)}
<script>
let nxtSortState = 0;
let originalOrder = [];

window.addEventListener('DOMContentLoaded', () => {{
  const tbody = document.querySelector('#volumeSpikeTable tbody');
  if (tbody) originalOrder = Array.from(tbody.querySelectorAll('tr'));
}});

window.addEventListener('pagehide', () => {{ resetSort(); }});
window.addEventListener('pageshow', (e) => {{ if (e.persisted) resetSort(); }});

function resetSort() {{
  nxtSortState = 0;
  const tbody = document.querySelector('#volumeSpikeTable tbody');
  const th = document.querySelector('.nxt-header');
  if (tbody && originalOrder.length) originalOrder.forEach(r => tbody.appendChild(r));
  if (th) th.textContent = 'NXT ⇅';
}}

function sortByNXT() {{
  const table = document.getElementById('volumeSpikeTable');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const th = table.querySelector('.nxt-header');

  nxtSortState = (nxtSortState + 1) % 3;

  if (nxtSortState === 0) {{
    originalOrder.forEach(r => tbody.appendChild(r));
    th.textContent = 'NXT ⇅';
    return;
  }}

  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {{
    const aVal = a.querySelectorAll('td')[5]?.innerText.trim() === 'NXT' ? 1 : 0;
    const bVal = b.querySelectorAll('td')[5]?.innerText.trim() === 'NXT' ? 1 : 0;
    return nxtSortState === 1 ? bVal - aVal : aVal - bVal;
  }});

  rows.forEach(r => tbody.appendChild(r));
  th.textContent = nxtSortState === 1 ? 'NXT ▼' : 'NXT ▲';
}}
</script>
<div id="naverChartPopup">
  <div class="popup-header">
    <button id="naverPopupClose">&#x2715;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 종목 페이지</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-card-header"><div class="chart-card-title">당일 선차트 (1일)</div><div class="chart-status" id="statusIntraday">대기중</div></div>
      <div class="chart-wrap"><img id="imgIntraday" alt="당일 차트"><div class="chart-loading" id="loadingIntraday">불러오는 중...</div></div>
    </div>
    <div class="chart-card">
      <div class="chart-card-header"><div class="chart-card-title">일봉</div><div class="chart-status" id="statusDaily">대기중</div></div>
      <div class="chart-wrap"><img id="imgDaily" alt="일봉 차트"><div class="chart-loading" id="loadingDaily">불러오는 중...</div></div>
    </div>
  </div>
</div>
<script>
(function () {{ return;
  var popup=document.getElementById('naverChartPopup'),popupTitle=document.getElementById('popupTitle'),popupLink=document.getElementById('popupLink');
  var imgIntraday=document.getElementById('imgIntraday'),imgDaily=document.getElementById('imgDaily');
  var loadingIntraday=document.getElementById('loadingIntraday'),loadingDaily=document.getElementById('loadingDaily');
  var statusIntraday=document.getElementById('statusIntraday'),statusDaily=document.getElementById('statusDaily');
  var closeBtn=document.getElementById('naverPopupClose'),hoverTimer=null,pinned=false;
  function openPopup(){{popup.style.display='block';document.body.classList.add('naver-popup-open');}}
  function closePopup(){{popup.style.display='none';document.body.classList.remove('naver-popup-open');pinned=false;}}
  var TS=Date.now();
  function withTs(u){{return u+'?t='+TS;}}
  function intradayUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/area/day/'+c+'.png');}}
  function dailyCandleUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'+c+'.png');}}
  function itemPageUrl(c){{return 'https://finance.naver.com/item/main.naver?code='+c;}}
  function setStatus(el,t,col){{el.textContent=t;el.style.color=col||'#94a3b8';}}
  function loadInto(img,ld,st,url,lbl){{
    ld.classList.add('show');img.style.opacity='0.35';setStatus(st,'로딩중...','#f59e0b');
    var p=new Image();
    p.onload=function(){{img.src=url;img.style.opacity='1';ld.classList.remove('show');setStatus(st,'로드 성공','#22c55e');}};
    p.onerror=function(){{img.removeAttribute('src');img.style.opacity='1';ld.classList.remove('show');setStatus(st,lbl+' 실패','#ef4444');}};
    p.src=url;
  }}
  function loadCharts(code,name){{popupTitle.textContent=code+'  '+(name||'');popupLink.href=itemPageUrl(code);loadInto(imgIntraday,loadingIntraday,statusIntraday,intradayUrl(code),'당일');loadInto(imgDaily,loadingDaily,statusDaily,dailyCandleUrl(code),'일봉');}}
  function placePopup(cx,cy){{var isMobile=window.innerWidth<=767;if(isMobile)return;var rW=Math.min(860,window.innerWidth-20),rH=window.innerWidth<=900?650:430,x=cx+18,y=cy+18;if(x+rW>window.innerWidth-8)x=cx-rW-12;if(y+rH>window.innerHeight-8)y=cy-rH-12;if(x<8)x=8;if(y<8)y=8;popup.style.left=x+'px';popup.style.top=y+'px';popup.style.transform='none';}}
  if(closeBtn)closeBtn.addEventListener('click',closePopup);
  popup.addEventListener('mouseenter',function(){{pinned=true;}});
  popup.addEventListener('mouseleave',function(){{pinned=false;closePopup();}});
  document.querySelectorAll('td[data-naver-off]').forEach(function(td){{  /* 종목명 hover는 V4 팝업이 담당 → naver PNG 팝업 비활성 */
    var hot=(td.nextElementSibling&&td.nextElementSibling.tagName==='TD')?td.nextElementSibling:td;
    hot.addEventListener('mouseenter',function(e){{var code=td.dataset.code,name=td.dataset.name||'';clearTimeout(hoverTimer);hoverTimer=setTimeout(function(){{placePopup(e.clientX,e.clientY);openPopup();loadCharts(code,name);}},140);}});
    hot.addEventListener('mousemove',function(e){{if(popup.style.display==='block'&&!pinned)placePopup(e.clientX,e.clientY);}});
    hot.addEventListener('mouseleave',function(){{clearTimeout(hoverTimer);setTimeout(function(){{if(!pinned)closePopup();}},120);}});
    hot.addEventListener('click',function(){{var code=td.dataset.code,name=td.dataset.name||'';if(popup.style.display==='block'&&popupTitle.textContent.startsWith(code)){{closePopup();return;}}placePopup(window.innerWidth/2,window.innerHeight/4);openPopup();loadCharts(code,name);}});
    hot.addEventListener('click',function(e){{if(window.innerWidth>767)return;e.stopPropagation();openPopup();loadCharts(td.dataset.code,td.dataset.name||'');}});
  }});
  (function(){{
    var seen={{}},queue=[];
    document.querySelectorAll('td[data-naver-off]').forEach(function(td){{  /* naver PNG 프리로드 비활성 */
      var c=td.dataset.code;if(!c||seen[c])return;seen[c]=true;queue.push(c);
    }});
    var idx=0,CONCURRENCY=3;
    function next(){{
      if(idx>=queue.length)return;
      var c=queue[idx++],done=0;
      function step(){{if(++done>=2)next();}}
      [intradayUrl(c),dailyCandleUrl(c)].forEach(function(u){{var im=new Image();im.onload=step;im.onerror=step;im.src=u;}});
    }}
    setTimeout(function(){{for(var i=0;i<CONCURRENCY&&i<queue.length;i++)next();}},300);
  }})();
  document.addEventListener('click',function(e){{if(window.innerWidth<=767&&popup.style.display==='block'){{if(!popup.contains(e.target))closePopup();}}}});
  // === D/S 단축키 (D/↓=다음, S/↑=이전, Tab/ESC=닫기) · PNG라 A(슈퍼트렌드)는 제외 ===
  (function(){{
    var SEL = 'td[data-code]';
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
    from chart_popup_v4 import build_chart_popup as _bcp_v4, move_kr_trigger_to_name as _mv2name
    page = _mv2name(page)  # 한국종목: 티커 대신 종목명에 hover → 차트
    _codes = sorted(set(_re.findall(r'data-code="([^"]+)"', page)))
    page = page.replace(
        "</body>",
        _bcp_v4(_codes, market="KR", trigger_attr="data-code", include_kospi=False) + "\n</body>",
        1,
    )
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] kor_volume_spike.html updated (V4 차트 {len(_codes)}종목)")

if __name__ == "__main__":
    main()
