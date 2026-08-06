import json
import re
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coloryp_core import check_coloryp_logic

# 설정
BASE_DIR = Path(__file__).resolve().parent
JSON_LOW_POINT = BASE_DIR / "kr_low_point_data.json"
OUTPUT_HTML = BASE_DIR / "kor_low_point.html"

def load_json(path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"데이터 로드 실패 ({path.name}): {e}")
        return None

def build_trend_background(ohlcv):
    daily, weekly = {}, {}
    for code, rows in ohlcv.items():
        if not rows:
            continue
        try:
            df = pd.DataFrame(
                rows, columns=["date", "open", "high", "low", "close", "volume"]
            )
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            calc = check_coloryp_logic(df)
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
            calc["trend_state"] = np.select(
                [is_lime, is_green, is_red, is_purple],
                ["LIME", "GREEN", "RED", "PURPLE"],
                default="NONE",
            )

            daily_cut = calc.index.max() - pd.DateOffset(months=2)
            daily[code] = {
                idx.strftime("%Y-%m-%d"): str(row.trend_state)
                for idx, row in calc.loc[calc.index >= daily_cut].iterrows()
                if row.trend_state != "NONE"
            }

            work = calc.reset_index()
            work["week_start"] = work["date"] - pd.to_timedelta(
                work["date"].dt.weekday, unit="D"
            )
            weekly_cut = work["date"].max() - pd.DateOffset(months=3)
            weekly[code] = {}
            for week_start, group in work.groupby("week_start", sort=True):
                last = group.sort_values("date").iloc[-1]
                if last["date"] >= weekly_cut and last["trend_state"] != "NONE":
                    weekly[code][week_start.strftime("%Y-%m-%d")] = str(last["trend_state"])
        except Exception as e:
            print(f"  [TREND BG] {code} calculation failed: {e}")
    return daily, weekly


def inject_trend_background(popup_block, trend_daily, trend_weekly):
    constants = (
        "const TREND_BG_D="
        + json.dumps(trend_daily, ensure_ascii=False, separators=(",", ":"))
        + ";\nconst TREND_BG_W="
        + json.dumps(trend_weekly, ensure_ascii=False, separators=(",", ":"))
        + ";\nconst TREND_BG_COLORS={"
        + "LIME:'rgba(0,230,118,0.15)',"
        + "GREEN:'rgba(76,175,80,0.15)',"
        + "PURPLE:'rgba(192,132,252,0.14)',"
        + "RED:'rgba(251,113,133,0.13)'};\n"
    )
    popup_block, count = re.subn(
        r"(const TRACK_D\s*=\s*\{\};[^\n]*\n)",
        lambda m: m.group(1) + constants,
        popup_block,
        count=1,
    )
    if count != 1:
        raise RuntimeError("TREND_BG constants insertion point not found")

    needle = "  const trkBand = (trackDates&&trackDates.length) ? cChart.addHistogramSeries({"
    layer = """  const trendStates=(withKospi?TREND_BG_D:TREND_BG_W)[curCode]||null;
  const trendBand=trendStates ? cChart.addHistogramSeries({
    priceScaleId:'trendbg',base:0,priceLineVisible:false,lastValueVisible:false}) : null;
  if(trendBand){
    cChart.priceScale('trendbg').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
    const trendData=raw.filter(r=>trendStates[r[0]]).map(r=>({
      time:r[0],value:1,color:TREND_BG_COLORS[trendStates[r[0]]]}));
    if(trendData.length)trendBand.setData(trendData);
  }
"""
    if needle not in popup_block:
        raise RuntimeError("TREND_BG layer insertion point not found")
    return popup_block.replace(needle, layer + needle, 1)


def inject_v2_chart_popup(html_str):
    """네이버 PNG 팝업 → KR150과 동일한 내장형 인터랙티브(lightweight-charts) 차트로 교체."""
    from make_index_kr_150 import (
        build_chart_popup,
        collect_ohlcv_kr,
        fetch_kospi_daily_fallback,
    )

    codes = sorted(set(re.findall(r'data-code="([^"]+)"', html_str)))
    if not codes:
        return html_str.replace("__CHART_POPUP__", "")

    print(f"[CHART] hover 대상 {len(codes)}종목 OHLCV 수집 (병렬)")
    ohlcv = collect_ohlcv_kr(codes)
    empties = [c for c in codes if not ohlcv.get(c)]
    print("  누락:", (", ".join(empties) if empties else "0"))
    ohlcv_json = json.dumps(ohlcv, separators=(",", ":"))
    trend_daily, trend_weekly = build_trend_background(ohlcv)

    try:
        from chart_popup_v2 import fetch_kospi_daily
        kospi_daily = fetch_kospi_daily()
        print(f"  [KOSPI일봉] {len(kospi_daily)}건 오버레이")
    except Exception as e:
        print(f"  [KOSPI일봉] chart_popup_v2 실패, fallback 시도: {e}")
        try:
            kospi_daily = fetch_kospi_daily_fallback()
            print(f"  [KOSPI일봉] {len(kospi_daily)}건 오버레이(fallback)")
        except Exception as e2:
            print(f"  [KOSPI일봉] 수집 실패(오버레이 생략): {e2}")
            kospi_daily = {}
    kospi_d_json = json.dumps(kospi_daily, ensure_ascii=False, separators=(",", ":"))

    from chart_popup_v4 import build_chart_popup as build_chart_popup_v4, move_kr_trigger_to_name as _mv2name
    popup_block = build_chart_popup_v4(
        codes,
        market="KR",
        trigger_attr="data-code",
        include_kospi=True,
    )
    html_str = _mv2name(html_str)  # 한국종목: 티커 대신 종목명에 hover → 차트
    return html_str.replace("__CHART_POPUP__", popup_block)


def generate_html():
    low_point_data = load_json(JSON_LOW_POINT)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 탭별 데이터 준비
    lp_stocks = low_point_data.get("stocks", []) if low_point_data else []
    
    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>저점/돌파 리포트</title>
    <style>
        body {{
            margin: 0; padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #f4f7f6; color: #333;
        }}
        .top-nav {{
            display: flex; background-color: #2c3e50;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            width: fit-content; margin: 0 0 10px 0; border-radius: 8px; overflow: hidden;
        }}
        .nav-item {{
            padding: 10px 20px; color: #bdc3c7; text-decoration: none;
            text-align: center; cursor: pointer;
            font-weight: bold; font-size: 0.95rem;
            border-bottom: 3px solid transparent;
        }}
        .nav-item:hover {{ color: #fff; background-color: #3d566e; }}
        .nav-item.active {{
            color: #fff; background-color: #34495e; border-bottom-color: #3498db;
        }}
        .container {{ padding: 10px; max-width: 500px; margin: 0; }}
        .header-info {{ margin-bottom: 10px; }}
        .title {{ font-size: 1.2em; font-weight: bold; color: #2c3e50; margin: 0 0 4px 0; }}
        .update-time {{ display: block; font-size: 0.85em; color: #7f8c8d; margin: 0; }}
        
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        table {{
            width: 100%; border-collapse: collapse;
            background: white; border-radius: 8px; overflow: hidden;
            margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        th {{
            background-color: #3498db; color: white;
            padding: 8px 6px; font-size: 0.8rem; text-align: center;
        }}
        td {{
            padding: 8px 6px; border-bottom: 1px solid #eee;
            font-size: 0.85rem; text-align: center; white-space: nowrap;
        }}
        .ticker-col {{ font-weight: bold; color: #2980b9; text-align: left; }}
        .name-col {{ text-align: left; }}
        .up {{ color: #27ae60; font-weight: bold; }}
        .down {{ color: #e74c3c; font-weight: bold; }}
        .nxt-bold {{ color: #8e44ad; font-weight: bold; }}
        
        /* 저점 전용 배지 */
        .badge {{
            display: inline-block; padding: 2px 5px;
            border-radius: 4px; font-size: 10px; font-weight: bold;
        }}
        .badge-jeo {{ background-color: #fee2e2; color: #991b1b; }}
        .badge-jeo2 {{ background-color: #ffedd5; color: #9a3412; }}
        
        @media (max-width: 600px) {{
            .container {{ max-width: 100%; }}
            th, td {{ padding: 6px 4px; font-size: 0.75rem; }}
        }}
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
          <a href="kor_low_point.html#low-point" class="nav-item active" id="nav-low-point">저점</a>
          <a href="kor_abc.html#vcp" class="nav-item">한국VCP</a>
        </div>
        <!-- [TAB 1: 저점] -->
        <div id="tab-low-point" class="tab-content active">
            <table>
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>종목명</th>
                        <th>저</th>
                        <th>저2</th>
                        <th>등락률</th>
                        <th>시총</th>
                        <th>NXT</th>
                    </tr>
                </thead>
                <tbody>
    """

    if not lp_stocks:
        html_content += '<tr><td colspan="7" style="padding:40px; color:#999;">검출된 저점 종목이 없습니다.</td></tr>'
    else:
        for s in lp_stocks:
            ticker = s.get("ticker", "")
            name = s.get("name", "")
            jeo = s.get("jeo", "-")
            jeo2 = s.get("jeo2", "-")
            change = s.get("change", 0)
            nxt = s.get("nxt", "")
            market_cap_uk = s.get("market_cap_uk", 0)

            j1_html = f'<span class="badge badge-jeo">저</span>' if jeo == "저" else "-"
            j2_html = f'<span class="badge badge-jeo2">저2</span>' if jeo2 == "저2" else "-"

            c_cls = "up" if change > 0 else ("down" if change < 0 else "")
            c_html = f'<span class="{c_cls}">{change:+.2f}%</span>'

            n_html = f'<span class="nxt-bold">NXT</span>' if nxt == "NXT" else ""
            cap_html = f'{market_cap_uk:,}억' if market_cap_uk else "-"

            html_content += f"""
                    <tr>
                        <td class="ticker-col" data-code="{ticker}" data-name="{name}">{ticker}</td>
                        <td class="name-col">{name[:5]}</td>
                        <td>{j1_html}</td>
                        <td>{j2_html}</td>
                        <td>{c_html}</td>
                        <td>{cap_html}</td>
                        <td>{n_html}</td>
                    </tr>"""

    html_content += """
                </tbody>
            </table>
        </div>
    </div>
__CHART_POPUP__
</body>
</html>
"""

    html_content = inject_v2_chart_popup(html_content)

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[OK] Generated {OUTPUT_HTML}")

if __name__ == "__main__":
    generate_html()
