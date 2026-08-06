import html
import json
import re
from datetime import datetime
from pathlib import Path


BASE = Path(r"D:\py\report-us")
SOURCE_DIR = Path(r"D:\py\0txt\kiwoom_us_condition")
OUT_HTML = BASE / "us_condition.html"

TARGET_CONDITIONS = [
    ("0", "심리25상향"),
    ("1", "GANN 주봉 - 상승"),
    ("2", "GANN 일봉 - 상승"),
    ("3", "★ 백타"),
]
CHUNK_SIZE = 10


def latest_payload(seq):
    pattern = f"*_seq{seq}_*.json"
    files = sorted(SOURCE_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None, None
    path = files[0]
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return path, {"error": str(exc), "rows": [], "count": 0}


def number_text(value):
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        num = float(text.replace(",", ""))
        if num.is_integer():
            return f"{int(num):,}"
        return f"{num:,.2f}".rstrip("0").rstrip(".")
    except ValueError:
        return html.escape(text)


def numeric_value(value):
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def trade_value(row):
    return numeric_value(row.get("price")) * numeric_value(row.get("volume"))


def rate_html(value):
    text = str(value or "").strip()
    if not text:
        return '<span style="color:#aaa;">-</span>'
    raw = text.replace("%", "").replace(",", "")
    try:
        rate = float(raw)
        color = "#27ae60" if rate > 0 else ("#e74c3c" if rate < 0 else "#888")
        sign = "+" if rate > 0 else ""
        return f'<span class="stock-rate" style="color:{color};">{sign}{rate:.2f}%</span>'
    except ValueError:
        return f'<span class="stock-rate">{html.escape(text)}</span>'


def short_name(value):
    text = str(value or "").strip()
    return text[:22]


def stock_row(row):
    code = str(row.get("code", "")).strip()
    name = short_name(row.get("name", ""))
    exchange = str(row.get("exchange", "")).strip()
    price = number_text(row.get("price"))
    volume = number_text(row.get("volume"))
    industry = short_name(row.get("industry", ""))
    yahoo_code = re.sub(r"[^A-Za-z0-9.\-]", "", code)
    link = f"https://finance.yahoo.com/quote/{yahoo_code}" if yahoo_code else "#"
    ticker_attr = f' data-ticker="{html.escape(yahoo_code)}"' if yahoo_code else ""
    return f"""
      <div class="stock-row">
        <span class="stock-code{' ticker-hover' if yahoo_code else ''}"{ticker_attr}>
          <a href="{html.escape(link)}" target="_blank" rel="noopener noreferrer">{html.escape(code)}</a>
        </span>
        <span class="stock-exchange">{html.escape(exchange)}</span>
        {rate_html(row.get("rate"))}
        <span class="stock-price">{price}</span>
        <span class="stock-vol">{volume}</span>
        <span class="stock-name" title="{html.escape(name)}">{html.escape(name) if name else "-"}</span>
        <span class="stock-industry">{html.escape(industry) if industry else "-"}</span>
      </div>"""


def card_html(seq, name, payload, path, part=None):
    count = int(payload.get("count") or len(payload.get("rows", [])) or 0)
    part_label = f' <span class="card-part">({part[0]}/{part[1]})</span>' if part else ""
    source = path.name if path else "결과 파일 없음"
    if payload.get("error"):
        body = f'<div class="empty-note error-note">{html.escape(payload["error"])}</div>'
    else:
        rows = sorted(payload.get("rows", []), key=trade_value, reverse=True)
        if not rows:
            body = '<div class="empty-note">(조건검색 결과 없음)</div>'
        else:
            body = "\n".join(stock_row(row) for row in rows)
    return f"""
  <div class="theme-card">
    <div class="card-header">
      <div class="card-title-line">
        <span class="cond-badge">US</span>
        <span class="theme-name" title="{html.escape(name)}">[{html.escape(seq)}] {html.escape(name)}{part_label}</span>
        <span class="stk-num">{count}종목</span>
      </div>
      <div class="card-sub">{html.escape(source)}</div>
    </div>
    <div class="stock-list">{body}</div>
  </div>"""


def render_condition(seq, name):
    path, payload = latest_payload(seq)
    if payload is None:
        payload = {"rows": [], "count": 0}
    rows = sorted(payload.get("rows", []), key=trade_value, reverse=True)
    if not rows or payload.get("error"):
        return [card_html(seq, name, payload, path)]
    chunks = [rows[i:i + CHUNK_SIZE] for i in range(0, len(rows), CHUNK_SIZE)][:2]
    total_parts = len(chunks)
    cards = []
    for idx, chunk in enumerate(chunks, 1):
        part_payload = dict(payload)
        part_payload["rows"] = chunk
        part = (idx, total_parts) if total_parts > 1 else None
        cards.append(card_html(seq, name, part_payload, path, part))
    return cards


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards = []
    for seq, name in TARGET_CONDITIONS:
        cards.extend(render_condition(seq, name))
    rows = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    cards_html = "\n".join(
        f'<div class="cards-row">\n{"".join(row)}\n</div>' for row in rows
    )

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>US Condition Search</title>
<style>
body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; margin: 0; background-color: #f4f7f6; color:#2c3e50; }}
.top-nav-container {{ display: flex; margin-bottom: 15px; }}
.top-nav {{ display: flex; background-color: #2c3e50; border-radius: 8px; overflow: hidden; width: fit-content; }}
.nav-item {{ padding: 8px 15px; color: #bdc3c7; text-align: center; cursor: pointer; font-weight: bold; text-decoration: none; transition: all 0.3s; font-size: 0.9em; }}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}
.page-title {{ margin: 0 0 4px; font-size: 1.35em; color:#2c3e50; }}
.updated {{ margin:0 0 16px; color:#666; font-size:0.9em; }}
.cards-row {{ display: grid; grid-template-columns: repeat(2, minmax(440px, 560px)); gap: 12px; justify-content: flex-start; align-items: start; margin-bottom: 12px; }}
.card-part {{ color:#7f8c8d; font-size:0.85em; font-weight:600; }}
.theme-card {{ background: white; border: 1px solid #ddd; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.08); overflow: hidden; }}
.card-header {{ padding: 10px 12px; background: #fafafa; border-top: 3px solid #2980b9; border-bottom: 1px solid #eee; }}
.card-title-line {{ display: flex; align-items: center; gap: 6px; min-width:0; }}
.cond-badge {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:0.72em; font-weight:bold; color:white; background:#2980b9; }}
.theme-name {{ flex: 1; min-width: 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight: 700; color:#222; }}
.stk-num {{ color:#7f8c8d; font-size:0.8em; white-space:nowrap; }}
.card-sub {{ color:#95a5a6; font-size:0.78em; margin-top:3px; }}
.stock-list {{ padding: 6px 12px; }}
.stock-row {{ display: grid; grid-template-columns: 64px 28px 70px 74px 88px minmax(120px,1fr) minmax(110px,1fr); gap: 8px; align-items: center; padding: 4px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.85em; }}
.stock-row:last-child {{ border-bottom: none; }}
.stock-code {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.stock-code a {{ color:#2980b9; text-decoration:underline dotted; font-weight:700; }}
.stock-exchange {{ color:#7f8c8d; font-size:0.78em; white-space:nowrap; }}
.stock-rate, .stock-price, .stock-vol {{ font-weight: bold; text-align:right; white-space:nowrap; }}
.stock-name {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#34495e; }}
.stock-industry {{ color:#7f8c8d; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.empty-note {{ color:#95a5a6; font-size:0.85em; padding: 8px 0; }}
.error-note {{ color:#e74c3c; }}
@media (max-width: 1040px) {{
  .cards-row {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 600px) {{
  body {{ padding: 12px; }}
  .top-nav-container, .top-nav {{ width: 100%; }}
  .nav-item {{ flex:1; padding:8px 8px; }}
  .stock-row {{ grid-template-columns: 62px 62px 70px minmax(100px,1fr); }}
  .stock-exchange, .stock-vol, .stock-industry {{ display:none; }}
}}
@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
.stock-name.ticker-hover {{ cursor:pointer; }}
.stock-name.ticker-hover:hover {{ background:#eaf3fb; }}
#naverChartPopup{{
  display:none;position:fixed;z-index:99999;width:1060px;background:#fff;
  border:1px solid #bdc3c7;border-radius:10px;padding:12px 14px 14px;
  box-shadow:0 12px 34px rgba(0,0,0,.24);overflow-y:auto;max-height:92dvh;
  overscroll-behavior:contain;-webkit-overflow-scrolling:touch;
}}
body.naver-popup-open{{overflow:hidden}}
#naverChartPopup .popup-header{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}}
#naverPopupClose{{display:flex;background:#e74c3c;color:#fff;border:none;border-radius:50%;
  width:26px;height:26px;font-size:16px;line-height:1;cursor:pointer;flex-shrink:0;
  align-items:center;justify-content:center;font-weight:bold}}
#naverChartPopup .popup-title{{font-weight:700;color:#2c3e50;font-size:14px;white-space:nowrap}}
#naverChartPopup .popup-link{{font-size:12px;color:#2980b9;text-decoration:none;white-space:nowrap}}
#naverChartPopup .popup-link:hover{{text-decoration:underline}}
.naver-charts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.naver-chart-card{{border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;background:#fff}}
.naver-chart-lab{{font-size:11px;font-weight:700;color:#64748b;padding:5px 8px 2px}}
.naver-chart-wrap{{position:relative;width:100%;height:380px;background:#fff}}
.naver-chart-wrap img{{width:100%;height:100%;display:block;object-fit:fill;background:#fff}}
.naver-chart-loading{{display:none;position:absolute;inset:0;background:rgba(255,255,255,.75);
  align-items:center;justify-content:center;font-size:12px;color:#64748b}}
.naver-chart-loading.show{{display:flex}}
@media(max-width:1000px){{
  #naverChartPopup{{width:96vw;left:2vw!important}}
  .naver-charts-grid{{grid-template-columns:1fr}}
  .naver-chart-wrap{{height:300px}}
}}
@media(max-width:767px){{
  #naverChartPopup{{position:fixed!important;left:2vw!important;top:50%!important;
    transform:translateY(-50%);width:96vw!important;max-height:86dvh!important;padding:8px}}
  .naver-chart-wrap{{height:260px}}
}}
</style>
</head>
<body>
<div class="top-nav-container">
  <div class="top-nav">
    <a href="kor_volume.html" class="nav-item">거래대금</a>
    <a href="danta_journal.html" class="nav-item">매매일지</a>
    <a href="kor_volume_spike.html" class="nav-item">거래량 급증</a>
    <a href="kor_condition.html" class="nav-item">한국조건검색</a>
    <a href="us_condition.html" class="nav-item active">미국조건검색</a>
  </div>
</div>
<h1 class="page-title">미국조건검색</h1>
<p class="updated">페이지: {now} &nbsp;|&nbsp; 대상: [0] 심리25상향, [1] GANN 주봉 - 상승, [2] GANN 일봉 - 상승, [3] ★ 백타</p>
{cards_html}
<div id="naverChartPopup" tabindex="-1">
  <div class="popup-header">
    <button id="naverPopupClose">&#x2715;</button>
    <div class="popup-title" id="naverPopupTitle">-</div>
    <a id="naverPopupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버증권↗</a>
  </div>
  <div class="naver-charts-grid">
    <div class="naver-chart-card">
      <div class="naver-chart-lab">일봉</div>
      <div class="naver-chart-wrap">
        <img id="naverImgDaily" alt="일봉">
        <div class="naver-chart-loading show" id="naverLoadingDaily">로딩중...</div>
      </div>
    </div>
    <div class="naver-chart-card">
      <div class="naver-chart-lab">주봉</div>
      <div class="naver-chart-wrap">
        <img id="naverImgWeekly" alt="주봉">
        <div class="naver-chart-loading show" id="naverLoadingWeekly">로딩중...</div>
      </div>
    </div>
  </div>
</div>

<script>
(function () {{
  var NAVER_SUFFIX_TRY = ['.O', '.P', '', '.N', '.A', '.K'];
  var resolvedCode = {{}};
  var popup      = document.getElementById('naverChartPopup');
  var titleEl    = document.getElementById('naverPopupTitle');
  var linkEl     = document.getElementById('naverPopupLink');
  var imgDaily   = document.getElementById('naverImgDaily');
  var imgWeekly  = document.getElementById('naverImgWeekly');
  var loadDaily  = document.getElementById('naverLoadingDaily');
  var loadWeekly = document.getElementById('naverLoadingWeekly');
  var hoverTimer = null;
  var pinned = false;
  var curEl = null;

  function withTs(u) {{ return u + '?t=' + Date.now(); }}
  function dailyUrl(c)  {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/day/'  + c + '_end.png'); }}
  function weeklyUrl(c) {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/week/' + c + '_end.png'); }}
  function pageUrl(c)   {{ return 'https://m.stock.naver.com/worldstock/stock/' + c + '/total'; }}

  function resolveCode(ticker, cb) {{
    var T = String(ticker || '').replace(/[*]/g, '').toUpperCase();
    if (!T) {{ cb(null); return; }}
    if (resolvedCode[T]) {{ cb(resolvedCode[T]); return; }}
    var candidates = NAVER_SUFFIX_TRY.map(function (s) {{ return T + s; }});
    var i = 0;
    function tryNext() {{
      if (i >= candidates.length) {{ cb(null); return; }}
      var code = candidates[i++];
      var probe = new Image();
      probe.onload  = function () {{ resolvedCode[T] = code; cb(code); }};
      probe.onerror = tryNext;
      probe.src = withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/world/item/candle/day/' + code + '_end.png');
    }}
    tryNext();
  }}

  function loadInto(imgEl, loadingEl, url) {{
    loadingEl.classList.add('show');
    imgEl.style.opacity = '0.35';
    var p = new Image();
    p.onload  = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.src = url;
  }}

  function loadCharts(ticker) {{
    var T = String(ticker || '').replace(/[*]/g, '').toUpperCase();
    titleEl.textContent = T + ' (resolving...)';
    linkEl.href = '#';
    loadDaily.classList.add('show');
    loadWeekly.classList.add('show');
    imgDaily.removeAttribute('src');
    imgWeekly.removeAttribute('src');
    resolveCode(T, function (code) {{
      if (!code) {{
        titleEl.textContent = T + '  (조회 실패)';
        loadDaily.classList.remove('show');
        loadWeekly.classList.remove('show');
        return;
      }}
      titleEl.textContent = T + '  [' + code + ']';
      linkEl.href = pageUrl(code);
      loadInto(imgDaily,  loadDaily,  dailyUrl(code));
      loadInto(imgWeekly, loadWeekly, weeklyUrl(code));
    }});
  }}

  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    var rectW = Math.min(1060, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 700 : 460;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
    popup.style.transform = 'none';
  }}

  function openPopup()  {{
    popup.style.display = 'block'; document.body.classList.add('naver-popup-open');
    try {{ if (document.activeElement === document.body || document.activeElement === null) popup.focus({{preventScroll:true}}); }} catch (e) {{}}
  }}
  function closePopup() {{
    popup.style.display = 'none'; pinned = false; document.body.classList.remove('naver-popup-open');
    document.removeEventListener('mousemove', unpinOnMove);
  }}
  function unpinOnMove(e) {{
    if (popup.contains(e.target)) return;
    document.removeEventListener('mousemove', unpinOnMove); pinned = false;
    setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
  }}
  function kbPin() {{
    pinned = true; clearTimeout(hoverTimer);
    document.removeEventListener('mousemove', unpinOnMove);
    document.addEventListener('mousemove', unpinOnMove);
  }}

  document.getElementById('naverPopupClose').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

  document.querySelectorAll('[data-ticker]').forEach(function (el) {{
    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        curEl = el;
        loadCharts(el.getAttribute('data-ticker') || '');
      }}, 140);
    }});
    el.addEventListener('mousemove', function (e) {{
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    el.addEventListener('mouseleave', function () {{
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    el.addEventListener('click', function (e) {{
      if (window.innerWidth > 767) return;
      e.stopPropagation();
      openPopup();
      curEl = el;
      loadCharts(el.getAttribute('data-ticker') || '');
    }});
  }});

  document.addEventListener('keydown', function (e) {{
    if (popup.style.display !== 'block') return;
    var tg = e.target, tag = tg && tg.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (tg && tg.isContentEditable)) return;
    var k = e.key;
    if (k === 'Tab' || k === 'Escape') {{ e.preventDefault(); closePopup(); return; }}
    var dir = 0;
    if (k === 's' || k === 'S' || k === 'ArrowUp') dir = -1;
    else if (k === 'd' || k === 'D' || k === 'ArrowDown') dir = 1;
    if (dir === 0 || !curEl) return;
    e.preventDefault();
    var all = Array.prototype.slice.call(document.querySelectorAll('[data-ticker]'));
    var i = all.indexOf(curEl);
    if (i < 0) return;
    i += dir;
    if (i < 0 || i >= all.length) return;
    var nt = all[i];
    kbPin();
    curEl = nt;
    loadCharts(nt.getAttribute('data-ticker') || '');
    nt.scrollIntoView({{block:'nearest'}});
  }});
}})();
</script>
</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] us_condition.html updated at {OUT_HTML}")


if __name__ == "__main__":
    main()
