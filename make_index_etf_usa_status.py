# make_index_etf_usa_status.py
# ─────────────────────────────────────────────────────────
# etf_usa_status.json 읽어서 etf_usa_status.html (ETF현황) 생성
#   · 원천: D:\py\0_etf_usa_status.py web  (9번=전체 8개 API 결과)
#   · 통합ETF 하위게시판(Top3 추세 오른쪽) — table 형태
# 실행: python make_index_etf_usa_status.py
# ─────────────────────────────────────────────────────────

import html
import json
import pathlib
import datetime

REPORT_DIR = pathlib.Path("D:/py/report-us")
JSON_PATH = REPORT_DIR / "etf_usa_status.json"
OUT_HTML = REPORT_DIR / "etf_usa_status.html"


def parse_float(value):
    raw = str(value or "").replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def parse_int(value):
    raw = str(value or "").replace(",", "").replace("+", "").strip()
    try:
        return abs(int(float(raw)))
    except ValueError:
        return 0


def fmt_cell(value, kind):
    """price=소수2자리·콤마 / change=%+부호 / int=만단위(#,###만) / text=원문."""
    text = str(value or "").strip()
    if kind == "price":
        number = parse_float(text)
        return "" if number is None else f"{abs(number):,.2f}"
    if kind == "change":
        number = parse_float(text)
        return "" if number is None else f"{number:.2f}%"
    if kind == "int":
        return "" if text == "" else f"{round(parse_int(text) / 10000):,}만"
    if kind == "amt":
        number = parse_float(text)
        if number is None:
            return ""
        if abs(number) >= 1_000_000_000:
            return f"${number / 1_000_000_000:,.2f}B"
        return f"${number / 1_000_000:,.1f}M"
    return text


def cell_html(value, kind, key=None, truncate_name=False):
    text = html.escape(fmt_cell(value, kind))
    if key == "stk_cd" and text and not text.isdigit():  # 순수 숫자(업종코드)는 실제 티커가 아니므로 제외
        ticker_attr = f' data-ticker="{html.escape(str(value or "").strip().upper())}" class="ticker-hover"'
        return f'<td class="txt"{ticker_attr}>{text}</td>'
    if kind == "change":
        number = parse_float(value)
        if number is not None:
            color = "#1a9e75" if number >= 0 else "#e74c3c"
            sign = "+" if number > 0 else ""
            return f'<td class="num" style="color:{color};font-weight:600">{sign}{text}</td>'
    css = "num" if kind in ("price", "change", "int", "amt") else "txt"
    if truncate_name and key == "stk_nm":
        css += " name-cell"
    return f'<td class="{css}">{text}</td>'


def section_html(sec, narrow=False):
    title = html.escape(f"{sec['num']}. {sec['title']} ({sec['api_id']})")
    columns = sec.get("columns") or []
    rows = sec.get("rows") or []

    if sec.get("error") and not rows:
        body = f'<div class="empty">오류: {html.escape(str(sec["error"]))}</div>'
    elif not columns or not rows:
        body = '<div class="empty">조건에 맞는 행이 없습니다.</div>'
    else:
        highlight = sec.get("highlight_column")
        head_cells = []
        for c in columns:
            label = html.escape(c["label"])
            if highlight and c["key"] == highlight:
                head_cells.append(f'<th style="color:#e74c3c">{label}</th>')
            else:
                head_cells.append(f"<th>{label}</th>")
        head = "".join(head_cells)
        trs = []
        for row in rows:
            tds = "".join(cell_html(row.get(c["key"], ""), c["kind"], c["key"], truncate_name=narrow) for c in columns)
            trs.append(f"<tr>{tds}</tr>")
        body = (
            '<div class="tbl-wrap"><table>'
            f"<thead><tr>{head}</tr></thead>"
            f'<tbody>{"".join(trs)}</tbody>'
            "</table></div>"
        )

    note = ""
    dropped = sec.get("dropped") or []
    if dropped:
        parts = []
        for d in dropped:
            tk = html.escape(str(d.get("ticker", "")))
            shown = d.get("shown")
            actual = d.get("actual")
            reason = html.escape(str(d.get("reason", "")))
            if actual is not None:
                parts.append(f"{tk}({shown:+.0f}%→실제{actual:+.1f}%,{reason})")
            else:
                parts.append(f"{tk}({shown:+.0f}%,{reason})")
        note = f'<div class="note">↳ [네이버검증] 분할/왜곡 {len(dropped)}건 제외: {", ".join(parts)}</div>'

    card_class = "card narrow" if narrow else "card"
    return f'<div class="{card_class}"><div class="ct">{title}</div>{body}{note}</div>'


def main():
    if not JSON_PATH.exists():
        print(f"❌ JSON 파일 없음: {JSON_PATH}  (먼저 'python D:/py/0_etf_usa_status.py web' 실행)")
        return

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    sections = data.get("sections") or []
    generated_at = data.get("generated_at", "")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 2번(ETF 당일 거래대금)·3번(업종별 기간별 수익률) 카드는 스크롤 없이 나란히 보이도록 한 행에 배치
    PAIR_NUMS = ("2", "3")
    solo_before, pair_parts, solo_after = [], [], []
    for sec in sections:
        if sec["num"] in PAIR_NUMS:
            pair_parts.append(section_html(sec))
        elif pair_parts:
            # row-pair 아래에 오는 카드는 wrap 전체폭으로 늘어나지 않게(불필요한 여백 방지) 콘텐츠 폭만 사용
            solo_after.append(section_html(sec, narrow=True))
        else:
            solo_before.append(section_html(sec))
    parts = list(solo_before)
    if pair_parts:
        parts.append(f'<div class="row-pair">{"".join(pair_parts)}</div>')
    parts.extend(solo_after)
    cards = "\n".join(parts)

    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>ETF현황 (미국 ETF 스캐너)</title>
<style>
:root{{--bg:#f4f7f6;--sur:#fff;--bor:#e0e7e5;--txt:#2c3e50;--txt2:#4a5568}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--txt);font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;font-size:14px;line-height:1.6;padding:15px}}
.top-nav-container{{display:flex;margin-bottom:10px}}
.top-nav{{display:flex;background:#2c3e50;border-radius:8px;overflow:hidden;width:fit-content}}
.nav-item{{padding:8px 15px;color:#bdc3c7;text-align:center;font-weight:bold;text-decoration:none;transition:all .3s;font-size:13px}}
.nav-item:hover{{background:#34495e;color:#fff}}
.nav-item.active{{background:#3498db;color:#fff}}
.hdr{{padding:2px 0 14px;border-bottom:2px solid #3498db;margin-bottom:16px}}
.hdr h1{{font-size:1.2em;font-weight:bold;color:#2c3e50;margin:0 0 2px}}
.hdr .sub{{font-size:13px;color:#4a5568}}
.wrap{{max-width:1320px;margin:0;display:flex;flex-direction:column;gap:16px}}
.card{{background:#fff;border-radius:8px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,.08)}}
.card.narrow{{align-self:flex-start}}
.card.narrow td.name-cell{{max-width:120px;overflow:hidden;text-overflow:ellipsis}}
.row-pair{{display:flex;align-items:flex-start;gap:0}}
.row-pair .card+.card{{margin-left:20px;padding-left:20px;border-left:2px solid #d5e0de}}
@media(max-width:900px){{
  .row-pair{{flex-direction:column;gap:16px}}
  .row-pair .card+.card{{margin-left:0;padding-left:16px;border-left:none;border-top:2px solid #d5e0de;padding-top:12px}}
}}
.ct{{font-size:1.0em;font-weight:bold;color:#2c3e50;margin-bottom:12px;padding-bottom:4px;border-bottom:2px solid #3498db}}
.tbl-wrap{{overflow-x:auto}}
.row-pair .tbl-wrap{{max-height:410px;overflow-y:auto}}
table{{border-collapse:collapse;width:auto;font-size:13px;white-space:nowrap}}
thead th{{background:#f0f4f3;color:#4a5568;font-weight:700;text-align:left;padding:7px 10px;border-bottom:2px solid #d5e0de;position:sticky;top:0}}
tbody td{{padding:6px 10px;border-bottom:1px solid #eef2f1}}
tbody tr:nth-child(even){{background:#fafcfb}}
tbody tr:hover{{background:#eef6fb}}
td.num{{text-align:right;font-family:'IBM Plex Mono','Consolas',monospace}}
td.txt{{text-align:left}}
.empty{{color:#95a5a6;padding:10px 2px;font-size:13px}}
.note{{margin-top:8px;font-size:12px;color:#b45309;line-height:1.7}}
td.ticker-hover{{cursor:pointer;color:#2980b9;text-decoration:underline dotted;text-underline-offset:2px}}
td.ticker-hover:hover{{color:#1a5c8a;background:#eaf3fb}}
@media(max-width:600px){{
  body{{padding:8px}} .card{{padding:10px}} table{{font-size:12px}}
  thead th,tbody td{{padding:5px 7px}}
}}

/* ── Naver 호버 차트 팝업 (일봉/주봉, KR150 수준 크기) ── */
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
      <a href="total_etf_combined.html" class="nav-item">통합 ETF</a>
      <a href="total_etf_combined_AI.html" class="nav-item">🤖 AI 관찰판</a>
      <a href="top3_etf_daily_result_total.html" class="nav-item">Top3 추세</a>
      <a href="etf_usa_status.html" class="nav-item active">ETF현황</a>
      <a href="hanmi_watch.html" class="nav-item">한미관심주</a>
    </div>
  </div>
  <div class="hdr">
    <h1>🇺🇸 ETF현황 — 미국 ETF 스캐너</h1>
    <div class="sub">키움 미국 ETF API {len(sections)}종 · 거래량 {round(2_000_000/10000):,}만주↑ 필터 · 데이터: {html.escape(generated_at)} · 페이지생성: {now}</div>
  </div>
  <div class="wrap">
{cards}
  </div>

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
    var curEl = null;   // 현재 차트가 가리키는 셀 (D/S 단축키 이동 기준)

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

    document.querySelectorAll('td[data-ticker]').forEach(function (el) {{
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
      var all = Array.prototype.slice.call(document.querySelectorAll('td[data-ticker]'));
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
</html>"""

    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] etf_usa_status.html 생성 완료 → {OUT_HTML} ({len(sections)}개 섹션)")


if __name__ == "__main__":
    main()
