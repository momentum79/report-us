# -*- coding: utf-8 -*-
"""make_index_kr_vcp.py — 한국VCP 게시판(kor_vcp.html) 생성.

입력
  - kr_minervini_stage2_final.csv : 1차+2차 모두 통과(VCP 피벗 진입) 종목
  - kr_minervini_stage1.csv       : 1차(추세템플릿+RS) 통과 매수후보
  - minervini_tracker_kr_view.json: 🎯 미너비니주 지표 추적 뷰(P:10%/S:-5%/2주홀딩)

상단 네비(실시간순위/저점/횡보돌파/한국VCP)로 보드 간 상호이동.
"""
import csv
import html
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
STAGE2_CSV = BASE_DIR / "kr_minervini_stage2_final.csv"
STAGE1_CSV = BASE_DIR / "kr_minervini_stage1.csv"
TRACKER_VIEW = BASE_DIR / "minervini_tracker_kr_view.json"
OUTPUT_HTML = BASE_DIR / "kor_vcp.html"


def _read_csv(path):
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def fnum(v, nd=2):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return html.escape(str(v or ""))


def stage2_table(rows):
    if not rows:
        return ('<p style="padding:24px;color:#999;text-align:center;">오늘 2차(VCP 피벗 돌파) '
                '진입 후보가 없습니다. 1차 통과 종목이 베이스를 형성하면 자동 표시됩니다.</p>')
    head = ["종목", "상태", "RS", "현재가", "피벗", "거리%", "거래비", "수축"]
    out = ["<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"]
    for r in rows:
        nm = html.escape((r.get("종목명") or r.get("ticker") or "").strip())
        tk = html.escape((r.get("ticker") or "").strip())
        out.append(
            "<tr>"
            f'<td class="ticker-col" data-code="{tk}" data-name="{nm}" style="cursor:pointer;">{nm}</td>'
            f'<td>{html.escape((r.get("status") or "").strip())}</td>'
            f'<td>{fnum(r.get("RS_rating"), 0)}</td>'
            f'<td>{fnum(r.get("close_now"), 0)}</td>'
            f'<td>{fnum(r.get("pivot"), 0)}</td>'
            f'<td>{fnum(r.get("pivot_dist_pct"))}</td>'
            f'<td>{fnum(r.get("volume_ratio"))}</td>'
            f'<td style="font-size:0.72rem;">{html.escape((r.get("contractions") or "").strip())}</td>'
            "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def tracker_table(path):
    doc = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            doc = {}
    rows = doc.get("rows", [])
    if not rows:
        return '<p style="padding:24px;color:#999;text-align:center;">추적 중인 종목이 없습니다.</p>'
    head = ["종목", "등락률", "현재가", "수익률", "경과", "10", "20", "60"]
    out = ["<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"]
    for r in rows:
        nm = html.escape((r.get("name") or r.get("ticker") or "").strip())
        tk = html.escape((r.get("ticker") or "").strip())
        chg = r.get("chg_pct", 0.0) or 0.0
        ret = r.get("ret_pct", 0.0) or 0.0
        chg_cls = "up" if chg >= 0 else "down"
        ret_cls = "up" if ret >= 0 else "down"

        def vx(val):
            return ('<td class="up">V</td>' if val == "V" else '<td class="down">X</td>')
        out.append(
            "<tr>"
            f'<td class="ticker-col" data-code="{tk}" data-name="{nm}" style="cursor:pointer;">{nm}</td>'
            f'<td class="{chg_cls}">{chg:+.2f}%</td>'
            f'<td>{r.get("close", 0):.0f}</td>'
            f'<td class="{ret_cls}">{ret:+.2f}%</td>'
            f'<td>{int(r.get("elapsed", 0))}일째</td>'
            + vx(r.get("v10")) + vx(r.get("v20")) + vx(r.get("v60"))
            + "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def stage1_list(rows):
    passed = [r for r in rows if str(r.get("Minervini_pass")).strip().lower() in ("true", "1")]
    if not passed:
        return ""
    chips = " · ".join(html.escape((r.get("종목명") or r.get("Ticker") or "").strip()) for r in passed)
    return (f'<details style="margin-bottom:20px;"><summary style="cursor:pointer;font-weight:bold;'
            f'color:#2c3e50;padding:8px 0;">1차(추세템플릿+RS) 통과 매수후보 {len(passed)}개 ▾</summary>'
            f'<div style="background:#fff;border-radius:8px;padding:10px;font-size:0.82rem;'
            f'color:#444;line-height:1.7;">{chips}</div></details>')


def main():
    stage2 = _read_csv(STAGE2_CSV)
    stage1 = _read_csv(STAGE1_CSV)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>한국VCP 리포트</title>
    <style>
        body {{ margin:0; padding:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
               background-color:#f4f7f6; color:#333; }}
        .top-nav {{ display:flex; background-color:#2c3e50; box-shadow:0 2px 5px rgba(0,0,0,0.2);
               width:fit-content; margin:0 0 10px 0; border-radius:8px; overflow:hidden; }}
        .nav-item {{ padding:10px 20px; color:#bdc3c7; text-decoration:none; text-align:center; cursor:pointer;
               font-weight:bold; font-size:0.95rem; border-bottom:3px solid transparent; }}
        .nav-item:hover {{ color:#fff; background-color:#3d566e; }}
        .nav-item.active {{ color:#fff; background-color:#34495e; border-bottom-color:#3498db; }}
        .container {{ padding:10px; max-width:560px; margin:0; }}
        .title {{ font-size:1.2em; font-weight:bold; color:#2c3e50; margin:0 0 4px 0; }}
        .sub {{ font-size:0.8em; color:#7f8c8d; margin:0 0 8px 0; }}
        .update-time {{ display:block; font-size:0.8em; color:#7f8c8d; margin:0 0 12px 0; }}
        h2.sec {{ font-size:1.0em; color:#2c3e50; margin:18px 0 6px 0; }}
        table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden;
               margin-bottom:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background-color:#3498db; color:#fff; padding:8px 6px; font-size:0.78rem; text-align:center; }}
        td {{ padding:8px 6px; border-bottom:1px solid #eee; font-size:0.84rem; text-align:center; white-space:nowrap; }}
        .ticker-col {{ font-weight:bold; color:#2980b9; text-align:left; }}
        .up {{ color:#27ae60; font-weight:bold; }}
        .down {{ color:#e74c3c; font-weight:bold; }}
        @media (max-width:600px) {{ .container {{ max-width:100%; }} th,td {{ padding:6px 4px; font-size:0.76rem; }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="top-nav">
          <a href="kor_realtime.html" class="nav-item">실시간순위</a>
          <a href="kor_low_point.html#low-point" class="nav-item">저점</a>
          <a href="kor_low_point.html#breakout" class="nav-item">횡보돌파</a>
          <a href="kor_vcp.html" class="nav-item active">한국VCP</a>
        </div>
        <p class="title">🎯 한국 미너비니 2차 진입</p>
        <p class="sub">유동성 20일평균 거래대금≥100억 · 1차 추세템플릿+RS70 · 2차 VCP 피벗 돌파(고점 6~26주)</p>
        <span class="update-time">Updated: {now}</span>

        <h2 class="sec">① 2차 진입 후보 (1차 통과 → VCP 피벗 돌파)</h2>
        {stage2_table(stage2)}

        {stage1_list(stage1)}

        <h2 class="sec">② 미너비니주 지표 (P:10%, S:-5%, 2주홀딩)</h2>
        <p class="sub">2차 진입 출현일 종가=기준가 · 3주(21일) 추적 · 10/20/60 = 종가 이평 이탈여부(V 유지 / X 하향이탈 고착)</p>
        {tracker_table(TRACKER_VIEW)}
    </div>
</body>
</html>"""

    # 종목명(=종목 셀)에 hover → 내장형 일/주봉 차트 (KR150 등과 동일한 V4 팝업)
    import re as _re
    try:
        from chart_popup_v4 import build_chart_popup as _bcp_v4
        _codes = sorted(set(_re.findall(r'data-code="([^"]+)"', html_doc)))
        if _codes:
            html_doc = html_doc.replace(
                "</body>",
                _bcp_v4(_codes, market="KR", trigger_attr="data-code", include_kospi=False) + "\n</body>",
                1,
            )
            print(f"[OK] 한국VCP V4 차트 {len(_codes)}종목")
    except Exception as _e:
        print(f"[WARN] VCP 차트 팝업 생략: {_e}")

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"[OK] Generated {OUTPUT_HTML}  (2차 {len(stage2)}개)")


if __name__ == "__main__":
    main()
