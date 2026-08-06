# -*- coding: utf-8 -*-
"""make_index_kr_abc.py — A·B·C 통합 게시판(kor_abc.html) 생성.

세 전략을 추세 성숙도 순서(초입→중간→성숙)로 한 화면 3탭에 모아 비교.
  A 수렴돌파 : kr_converge_data.json      (🟢FIRE 매수트리거 + 🟡WATCH 수렴대기)
  B 횡보돌파 : kr_afterflat_data.json     (10·20 밀착 스퀴즈 상단안착)
  C 한국VCP  : kr_minervini_stage2_final.csv (미너비니 2차 피벗 돌파)

종목명 hover → 내장형 일/주봉 v4 차트(KOSPI 오버레이·추세배경) — B 게시판과 동일 메커니즘 재사용.
"""
import csv
import json
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

JSON_CONVERGE = BASE_DIR / "kr_converge_data.json"      # A
JSON_AFTERFLAT = BASE_DIR / "kr_afterflat_data.json"    # B
CSV_VCP = BASE_DIR / "kr_minervini_stage2_final.csv"    # C
OUTPUT_HTML = BASE_DIR / "kor_abc.html"


def load_json(path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] {path.name} 로드 실패: {e}")
        return None


def read_csv(path):
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"[WARN] {path.name} 로드 실패: {e}")
        return []


def _cell(ticker, name):
    """티커셀(data-code/data-name) + 종목명셀. move_kr_trigger_to_name 이 종목명셀로 hover 이동."""
    return (f'<td class="ticker-col" data-code="{ticker}" data-name="{name}">{ticker}</td>'
            f'<td class="name-col">{name[:6]}</td>')


def _chg(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    cls = "up" if v > 0 else ("down" if v < 0 else "")
    return f'<span class="{cls}">{v:+.2f}%</span>'


def fnum(v, nd=0):
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return str(v or "-")


# ── A: 수렴돌파 (FIRE + WATCH) ────────────────────────────────
def tab_converge(data):
    if not data:
        return '<p class="empty-msg">수렴돌파 데이터가 없습니다.</p>'
    _tvkey = lambda s: float(s.get("tv_today_uk") or 0)
    fire = sorted(data.get("fire", []), key=_tvkey, reverse=True)
    watch = sorted(data.get("watch", []), key=_tvkey, reverse=True)
    cmax = data.get("converge_max_pct", 5.0)
    liq = data.get("liq_min_uk", 300)
    out = [f'<p class="sub">수렴 5·10·20 폭 ≤{cmax}% · 이격(20&lt;60, 종가&lt;120) · 5일평균 거래대금 ≥{liq}억</p>']

    def _table(rows, kind):
        is_watch = (kind == "watch")
        head = ["Ticker", "종목명", "폭%", "등락률", "당일대금"]
        if is_watch:
            head += ["돌파거리", "돌파가"]
        head += ["시총", "NXT"]
        h = "<table><thead><tr>" + "".join(f"<th>{x}</th>" for x in head) + "</tr></thead><tbody>"
        body = []
        for s in rows:
            nxt = '<span class="nxt-bold">NXT</span>' if s.get("nxt") == "NXT" else ""
            cap = f'{s.get("market_cap_uk", 0):,}억' if s.get("market_cap_uk") else "-"
            dist = ""
            if is_watch:
                close = s.get("close")
                trigger = s.get("trigger_price")
                try:
                    dist_pct = (float(trigger) - float(close)) / float(close) * 100
                    dist = f'<td>+{dist_pct:.1f}%</td>'
                except (TypeError, ValueError, ZeroDivisionError):
                    dist = '<td>-</td>'
            trig = f'<td>{fnum(s.get("trigger_price"))}</td>' if is_watch else ""
            body.append(
                "<tr>" + _cell(s.get("ticker", ""), s.get("name", ""))
                + f'<td>{s.get("spread_pct", "-")}%</td>'
                + f'<td>{_chg(s.get("change"))}</td>'
                + f'<td>{fnum(s.get("tv_today_uk"))}억</td>'
                + dist
                + trig
                + f'<td>{cap}</td><td>{nxt}</td></tr>')
        if not rows:
            body.append(f'<tr><td colspan="{9 if is_watch else 7}" class="empty-msg">해당 없음</td></tr>')
        return h + "".join(body) + "</tbody></table>"

    out.append(f'<h2 class="sec">🟢 FIRE — 첫 동시돌파 (매수 트리거) · {len(fire)}개</h2>')
    out.append(_table(fire, "fire"))
    out.append(f'<h2 class="sec">🟡 WATCH — 수렴대기 (관심) · {len(watch)}개</h2>')
    out.append(_table(watch, "watch"))
    return "".join(out)


# ── B: 횡보돌파 ───────────────────────────────────────────────
def tab_breakout(data):
    stocks = (data or {}).get("stocks", [])
    out = ['<p class="sub">5·10·20·60 위 · 10·20 갭 ≤3% · 최근10일 밀착 ≥7일 · 당일 거래대금 ≥50억</p>']
    head = ["Ticker", "종목명", "등락률", "1020갭", "10일HL", "시총", "NXT"]
    h = "<table><thead><tr>" + "".join(f"<th>{x}</th>" for x in head) + "</tr></thead><tbody>"
    body = []
    for s in stocks:
        nxt = '<span class="nxt-bold">NXT</span>' if s.get("nxt") == "NXT" else ""
        cap = f'{s.get("market_cap_uk", 0):,}억' if s.get("market_cap_uk") else "-"
        body.append(
            "<tr>" + _cell(s.get("ticker", ""), s.get("name", ""))
            + f'<td>{_chg(s.get("change"))}</td>'
            + f'<td>{s.get("ma_gap_pct", "-")}%</td>'
            + f'<td>{s.get("price_range_pct", "-")}%</td>'
            + f'<td>{cap}</td><td>{nxt}</td></tr>')
    if not stocks:
        body.append('<tr><td colspan="7" class="empty-msg">검출된 돌파 종목이 없습니다.</td></tr>')
    out.append(h + "".join(body) + "</tbody></table>")
    return "".join(out)


# ── C: 한국VCP (미너비니 2차) ─────────────────────────────────
def tab_vcp(rows):
    out = ['<p class="sub">유동성 ≥100억 · 1차 추세템플릿+RS70 · 2차 VCP 피벗 돌파(고점 6~26주)</p>']
    head = ["Ticker", "종목명", "상태", "RS", "현재가", "거리%", "거래비", "수축"]
    h = "<table><thead><tr>" + "".join(f"<th>{x}</th>" for x in head) + "</tr></thead><tbody>"
    body = []
    for r in rows:
        body.append(
            "<tr>" + _cell((r.get("ticker") or "").strip(), (r.get("종목명") or "").strip())
            + f'<td>{(r.get("status") or "").strip()}</td>'
            + f'<td>{fnum(r.get("RS_rating"))}</td>'
            + f'<td>{fnum(r.get("close_now"))}</td>'
            + f'<td>{fnum(r.get("pivot_dist_pct"), 2)}</td>'
            + f'<td>{fnum(r.get("volume_ratio"), 2)}</td>'
            + f'<td style="font-size:0.72rem;">{(r.get("contractions") or "").strip()}</td></tr>')
    if not rows:
        body.append('<tr><td colspan="8" class="empty-msg">오늘 2차(VCP 피벗 돌파) 진입 후보가 없습니다.</td></tr>')
    out.append(h + "".join(body) + "</tbody></table>")
    return "".join(out)


def generate_html():
    a_data = load_json(JSON_CONVERGE)
    b_data = load_json(JSON_AFTERFLAT)
    c_rows = read_csv(CSV_VCP)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>A·B·C 통합 리포트</title>
    <style>
        body {{ margin:0; padding:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
               background-color:#f4f7f6; color:#333; }}
        .top-nav {{ display:flex; background-color:#2c3e50; box-shadow:0 2px 5px rgba(0,0,0,0.2);
               width:fit-content; margin:0 0 10px 0; border-radius:8px; overflow:hidden; }}
        .nav-item {{ padding:10px 20px; color:#bdc3c7; text-decoration:none; text-align:center; cursor:pointer;
               font-weight:bold; font-size:0.95rem; border-bottom:3px solid transparent; }}
        .nav-item:hover {{ color:#fff; background-color:#3d566e; }}
        .nav-item.active {{ color:#fff; background-color:#34495e; border-bottom-color:#3498db; }}
        .container {{ padding:10px; max-width:520px; margin:0; }}
        .title {{ font-size:1.2em; font-weight:bold; color:#2c3e50; margin:0 0 4px 0; }}
        .sub {{ font-size:0.8em; color:#7f8c8d; margin:0 0 8px 0; }}
        .update-time {{ display:block; font-size:0.8em; color:#7f8c8d; margin:0 0 12px 0; }}
        h2.sec {{ font-size:1.0em; color:#2c3e50; margin:16px 0 6px 0; }}
        .empty-msg {{ padding:24px; color:#999; text-align:center; }}
        .tab-content {{ display:none; }}
        .tab-content.active {{ display:block; }}
        table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden;
               margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background-color:#3498db; color:#fff; padding:8px 6px; font-size:0.78rem; text-align:center; }}
        td {{ padding:8px 6px; border-bottom:1px solid #eee; font-size:0.84rem; text-align:center; white-space:nowrap; }}
        .ticker-col {{ font-weight:bold; color:#2980b9; text-align:left; }}
        .name-col {{ text-align:left; }}
        .up {{ color:#27ae60; font-weight:bold; }}
        .down {{ color:#e74c3c; font-weight:bold; }}
        .nxt-bold {{ color:#8e44ad; font-weight:bold; }}
        @media (max-width:600px) {{ .container {{ max-width:100%; }} th,td {{ padding:6px 4px; font-size:0.76rem; }} }}
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
.col {{ display: flex; flex-direction: column; min-width: 0; }}
.collab {{ font-size: 11px; font-weight: 700; color: #374151; padding: 2px 0 3px; }}
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
    <div class="container">
        <div class="top-nav">
          <a href="kor_realtime.html" class="nav-item">실시간순위</a>
          <a href="kor_low_point.html#low-point" class="nav-item">저점</a>
          <a href="kor_abc.html#vcp" class="nav-item active">한국VCP</a>
        </div>
        <p class="title">🎯 A·B·C 통합 (수렴돌파 · 횡보돌파 · VCP)</p>
        <span class="update-time">Updated: {now}</span>
        <div class="top-nav" style="margin-bottom:8px;">
          <span class="nav-item" id="nav-converge" onclick="location.hash='#converge'">A 수렴돌파</span>
          <span class="nav-item" id="nav-breakout" onclick="location.hash='#breakout'">B 횡보돌파</span>
          <span class="nav-item" id="nav-vcp" onclick="location.hash='#vcp'">C VCP</span>
        </div>

        <div id="tab-converge" class="tab-content active">{tab_converge(a_data)}</div>
        <div id="tab-breakout" class="tab-content">{tab_breakout(b_data)}</div>
        <div id="tab-vcp" class="tab-content">{tab_vcp(c_rows)}</div>
    </div>

    <script>
        function activateTab(key) {{
            var keys = ['converge','breakout','vcp'];
            if (keys.indexOf(key) < 0) key = 'converge';
            keys.forEach(function(k) {{
                document.getElementById('tab-' + k).classList.toggle('active', k === key);
                document.getElementById('nav-' + k).classList.toggle('active', k === key);
            }});
            window.scrollTo(0, 0);
        }}
        function currentKey() {{ return (location.hash || '#converge').replace('#',''); }}
        window.addEventListener('DOMContentLoaded', function () {{ activateTab(currentKey()); }});
        window.addEventListener('hashchange', function () {{ activateTab(currentKey()); }});
    </script>
__CHART_POPUP__
</body>
</html>
"""

    # 종목명 hover → v4 인터랙티브 차트 (B 게시판과 동일 메커니즘 재사용)
    try:
        from make_index_kr_low_point import inject_v2_chart_popup
        html_content = inject_v2_chart_popup(html_content)
    except Exception as e:
        print(f"[WARN] v4 차트 팝업 생략: {e}")
        html_content = html_content.replace("__CHART_POPUP__", "")

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[OK] Generated {OUTPUT_HTML}  (A: fire {len((a_data or {}).get('fire', []))}/watch "
          f"{len((a_data or {}).get('watch', []))}, B: {len((b_data or {}).get('stocks', []))}, C: {len(c_rows)})")


if __name__ == "__main__":
    generate_html()
