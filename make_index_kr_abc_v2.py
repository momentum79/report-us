# -*- coding: utf-8 -*-
"""make_index_kr_abc_v2.py — A·B·C 통합 게시판 + V2 병행 패널(kor_abc.html) 생성.

기존 make_index_kr_abc.py 를 절대 수정하지 않고, 그 렌더러(tab_converge/tab_breakout/
tab_vcp 등)를 그대로 import 재사용한다. 좌측 본문(A·B·C 3탭)은 v1 과 동일하게 두고,
우측에 'V2 점수랭킹' 패널(🟢FIRE/🟡WATCH)을 추가로 붙인다.

  좌 : kr_converge_data.json (A/V1) · kr_afterflat_data.json (B) · VCP CSV (C)
  우 : kr_converge_data_v2.json (A/V2 점수랭킹 · 2~3주 병행 비교용)

종목명 hover → 내장형 v4 차트: 페이지 내 모든 data-code 셀을 inject_v2_chart_popup 이
자동 수집하므로, V2 표도 동일한 _cell() 마크업만 쓰면 호버가 그대로 적용된다.

출력: kor_abc.html (v1 배치가 다시 돌면 make_index_kr_abc.py 가 평범한 버전으로 되돌림)
"""
import json
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# v1 보드의 렌더러/헬퍼/경로를 그대로 재사용 (원본 미수정)
from make_index_kr_abc import (
    load_json, read_csv,
    tab_converge, tab_breakout, tab_vcp,
    _cell, _chg, fnum,
    JSON_CONVERGE, JSON_AFTERFLAT, CSV_VCP,
)

JSON_CONVERGE_V2 = BASE_DIR / "kr_converge_data_v2.json"   # A / V2
OUTPUT_HTML = BASE_DIR / "kor_abc.html"


def _grade_badge(g):
    g = (g or "").strip()
    color = {"A": "#16a34a", "B": "#2563eb", "C": "#d97706", "D": "#6b7280"}.get(g, "#6b7280")
    if not g:
        return "-"
    return f'<span style="display:inline-block;min-width:20px;padding:1px 6px;border-radius:10px;background:{color};color:#fff;font-weight:700;font-size:0.72rem;">{g}</span>'


def _over_pct(close, trigger):
    """FIRE 전용: 종가가 돌파가를 넘은 폭(%)."""
    try:
        c, t = float(close), float(trigger)
        if c <= 0 or t <= 0:
            return "-"
        return f"+{(c / t - 1.0) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _num(v, nd=1):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "-"


# ── V2 우측 패널 (점수랭킹) ────────────────────────────────────────
def panel_v2(data):
    if not data:
        return ('<div class="v2-head">🧪 V2 점수랭킹 (실험 · 병행)</div>'
                '<p class="empty-msg">V2 데이터가 아직 없습니다. '
                '(kr_converge_breakout_v2.py 실행 필요)</p>')

    fire = data.get("fire", [])     # total_score 내림차순(스캐너에서 정렬됨)
    watch = data.get("watch", [])   # setup_score 내림차순
    th = data.get("thresholds", {})
    upd = data.get("update_time", "")

    out = [
        '<div class="v2-head">🧪 V2 점수랭킹 (실험 · 2~3주 병행 비교)</div>',
        f'<p class="sub">필수구조 MA20&lt;60&lt;120 · 종가&lt;60·120 · '
        f'횡보40+수렴35+장기15+돌파10 · setup≥{th.get("setup_min", 60)} / '
        f'FIRE total≥{th.get("fire_total_min", 70)}'
        f'<br>Updated: {upd}</p>',
    ]

    # 🟢 FIRE
    fhead = ["Ticker", "종목명", "등급", "TOTAL", "SETUP(전)", "돌파", "등락률", "당일대금",
             "돌파가", "초과%", "시총", "NXT"]
    fh = ('<table class="v2-table"><thead><tr>'
          + "".join(f"<th>{x}</th>" for x in fhead) + "</tr></thead><tbody>")
    fbody = []
    for s in fire:
        nxt = '<span class="nxt-bold">NXT</span>' if s.get("nxt") == "NXT" else ""
        cap = f'{s.get("market_cap_uk", 0):,}억' if s.get("market_cap_uk") else "-"
        age = s.get("best_setup_age")
        setup_cell = f'{_num(s.get("best_setup_score"))}<span class="dim">({age}봉)</span>' if age else _num(s.get("best_setup_score"))
        fbody.append(
            "<tr>" + _cell(s.get("ticker", ""), s.get("name", ""))
            + f'<td>{_grade_badge(s.get("grade"))}</td>'
            + f'<td class="hot">{_num(s.get("total_score"))}</td>'
            + f'<td>{setup_cell}</td>'
            + f'<td>{_num(s.get("breakout_score"))}</td>'
            + f'<td>{_chg(s.get("change"))}</td>'
            + f'<td>{fnum(s.get("tv_today_uk"))}억</td>'
            + f'<td>{fnum(s.get("trigger_price"))}</td>'
            + f'<td class="up">{_over_pct(s.get("close"), s.get("trigger_price"))}</td>'
            + f'<td>{cap}</td><td>{nxt}</td></tr>')
    if not fire:
        fbody.append('<tr><td colspan="12" class="empty-msg">오늘 첫 동시돌파 없음</td></tr>')
    out.append(f'<h2 class="sec">🟢 V2 FIRE — 첫 동시돌파 · {len(fire)}개</h2>')
    out.append(fh + "".join(fbody) + "</tbody></table>")

    # 🟡 WATCH
    whead = ["Ticker", "종목명", "등급", "SETUP", "횡보", "수렴", "장기", "등락률", "돌파가", "시총", "NXT"]
    wh = ('<table class="v2-table"><thead><tr>'
          + "".join(f"<th>{x}</th>" for x in whead) + "</tr></thead><tbody>")
    wbody = []
    for s in watch:
        nxt = '<span class="nxt-bold">NXT</span>' if s.get("nxt") == "NXT" else ""
        cap = f'{s.get("market_cap_uk", 0):,}억' if s.get("market_cap_uk") else "-"
        wbody.append(
            "<tr>" + _cell(s.get("ticker", ""), s.get("name", ""))
            + f'<td>{_grade_badge(s.get("grade"))}</td>'
            + f'<td class="hot">{_num(s.get("setup_score"))}</td>'
            + f'<td>{_num(s.get("sideways_score"))}</td>'
            + f'<td>{_num(s.get("convergence_score"))}</td>'
            + f'<td>{_num(s.get("long_structure_score"))}</td>'
            + f'<td>{_chg(s.get("change"))}</td>'
            + f'<td>{fnum(s.get("trigger_price"))}</td>'
            + f'<td>{cap}</td><td>{nxt}</td></tr>')
    if not watch:
        wbody.append('<tr><td colspan="11" class="empty-msg">해당 없음</td></tr>')
    out.append(f'<h2 class="sec">🟡 V2 WATCH — 수렴대기 (점수순) · {len(watch)}개</h2>')
    out.append(wh + "".join(wbody) + "</tbody></table>")
    return "".join(out)


def _count(d, key):
    return len((d or {}).get(key, []))


def generate_html():
    a_data = load_json(JSON_CONVERGE)
    b_data = load_json(JSON_AFTERFLAT)
    c_rows = read_csv(CSV_VCP)
    v2_data = load_json(JSON_CONVERGE_V2)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>A·B·C 통합 리포트 (+V2)</title>
    <style>
        body {{ margin:0; padding:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
               background-color:#f4f7f6; color:#333; }}
        .top-nav {{ display:flex; background-color:#2c3e50; box-shadow:0 2px 5px rgba(0,0,0,0.2);
               width:fit-content; margin:0 0 10px 0; border-radius:8px; overflow:hidden; }}
        .nav-item {{ padding:10px 20px; color:#bdc3c7; text-decoration:none; text-align:center; cursor:pointer;
               font-weight:bold; font-size:0.95rem; border-bottom:3px solid transparent; }}
        .nav-item:hover {{ color:#fff; background-color:#3d566e; }}
        .nav-item.active {{ color:#fff; background-color:#34495e; border-bottom-color:#3498db; }}
        .abc-layout {{ display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap; padding:10px; }}
        .container {{ padding:0; max-width:640px; margin:0; flex:0 0 auto; }}
        .v2-container {{ flex:1 1 760px; max-width:950px; min-width:340px;
               background:#faf5ff; border:1px solid #e9d5ff; border-radius:10px; padding:12px 14px; }}
        .v2-head {{ font-size:1.1em; font-weight:800; color:#6b21a8; margin:0 0 8px 0; }}
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
        .v2-table th {{ background-color:#7c3aed; }}
        .v2-table td.hot {{ font-weight:800; color:#6b21a8; }}
        .v2-table .dim {{ color:#9ca3af; font-size:0.72rem; }}
        @media (max-width:600px) {{ .container {{ max-width:100%; }} th,td {{ padding:6px 4px; font-size:0.76rem; }}
               /* 표가 넓어져도 페이지 전체가 아니라 패널 안에서만 가로 스크롤 */
               .container, .v2-container {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
               .v2-container {{ min-width:0; box-sizing:border-box; }} }}
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
    <div class="abc-layout">
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

      <div class="v2-container">{panel_v2(v2_data)}</div>
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

    # 종목명 hover → v4 인터랙티브 차트 (좌 A·B·C + 우 V2 의 모든 data-code 자동 수집)
    try:
        from make_index_kr_low_point import inject_v2_chart_popup
        html_content = inject_v2_chart_popup(html_content)
    except Exception as e:
        print(f"[WARN] v4 차트 팝업 생략: {e}")
        html_content = html_content.replace("__CHART_POPUP__", "")

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[OK] Generated {OUTPUT_HTML}  "
          f"(A/v1: fire {_count(a_data,'fire')}/watch {_count(a_data,'watch')}, "
          f"B: {_count(b_data,'stocks')}, C: {len(c_rows)}  ||  "
          f"A/v2: fire {_count(v2_data,'fire')}/watch {_count(v2_data,'watch')})")


if __name__ == "__main__":
    generate_html()
