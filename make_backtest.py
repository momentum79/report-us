# make_backtest.py
# 확인용 백테스트 페이지 생성 (원본 파일 절대 안 건드림).
#
# 목적:
#   - KOSPI / NASDAQ 누적수익률 vs (avg_sco, top3_sco_avg, invest_pct, regime_proxy)
#   - 어느 시그널이 지수와 가장 비례하는지 시각적 + Pearson 상관계수로 확인
#
# 입력:
#   - report-us/top3_etf_track_total.json   (292일: kospi_rtn, nasdaq_rtn, invest_pct, top3_sco_avg, avg_sco 등)
#   - report-us/market_regime_track_total.json (552일: avg_sco, sco_strong/mid/weak/neg, regime_map_score)
#
# 출력:
#   - report-us/backtest.html  (이중 Y축 Chart.js + 상관관계 표)
#
# 원본 영향 없음: 기존 산출물 파일을 절대 수정/덮어쓰지 않음.

import json
import math
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
TOP3_FILE   = BASE / "top3_etf_track_total.json"
REGIME_FILE = BASE / "market_regime_track_total.json"
OUT_HTML    = BASE / "backtest.html"


def _valid(v):
    if v is None:
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    return True


def _to_float(v, default=None):
    try:
        f = float(v)
        if math.isnan(f):
            return default
        return f
    except Exception:
        return default


def load_top3():
    if not TOP3_FILE.exists():
        return {}
    with open(TOP3_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_regime():
    if not REGIME_FILE.exists():
        return []
    with open(REGIME_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def pearson(xs, ys):
    """결측 제거 후 Pearson 상관계수. 점 부족하면 None."""
    pairs = [(x, y) for x, y in zip(xs, ys) if _valid(x) and _valid(y)]
    n = len(pairs)
    if n < 5:
        return None, n
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    mx = sx / n
    my = sy / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    dx2 = sum((p[0] - mx) ** 2 for p in pairs)
    dy2 = sum((p[1] - my) ** 2 for p in pairs)
    denom = math.sqrt(dx2 * dy2)
    if denom == 0:
        return None, n
    return num / denom, n


def main():
    top3 = load_top3()
    regime_list = load_regime()
    regime_by_date = {row.get("date"): row for row in regime_list if row.get("date")}

    if not top3:
        print(f"⚠️ {TOP3_FILE} 없음. 백테스트 페이지 생성 중단.")
        return

    # 날짜 정렬 (top3 기준 - kospi_rtn / nasdaq_rtn 누적이 있어서)
    dates = sorted(top3.keys())

    rows = []
    for d in dates:
        t = top3[d]
        r = regime_by_date.get(d, {})

        kospi  = _to_float(t.get("kospi_rtn"))
        nasdaq = _to_float(t.get("nasdaq_rtn"))
        invest = _to_float(t.get("invest_pct"))
        # invest_pct는 2026-03-19부터 진짜 값. 그 이전은 placeholder 0 → 결측 처리
        if invest is not None and invest == 0.0 and d < "2026-03-19":
            invest = None
        top3_sco = _to_float(t.get("top3_sco_avg"))
        avg_sco_t = _to_float(t.get("avg_sco"))   # 최근만 채워짐
        avg_sco_r = _to_float(r.get("avg_sco"))   # market_regime은 552일 풍부
        avg_sco = avg_sco_t if avg_sco_t is not None else avg_sco_r

        # regime_proxy: (sco_strong - sco_neg) / total_universe * 100
        # market_regime_track 우선, 없으면 top3 sco_zone_*  사용
        s_strong = _to_float(r.get("sco_strong"))
        s_neg    = _to_float(r.get("sco_neg"))
        s_total  = _to_float(r.get("total_universe"))
        if s_strong is None:
            s_strong = _to_float(t.get("sco_zone_strong"))
        if s_neg is None:
            s_neg = _to_float(t.get("sco_zone_neg"))
        # universe 추정: top3 JSON엔 total_cnt 없으니 4 zone 합으로 근사
        if s_total is None:
            ss = [t.get(k) for k in ("sco_zone_strong","sco_zone_mid","sco_zone_weak","sco_zone_neg")]
            ss = [_to_float(x) for x in ss]
            if all(x is not None for x in ss):
                s_total = sum(ss)
        if s_strong is not None and s_neg is not None and s_total and s_total > 0:
            regime_proxy = (s_strong - s_neg) / s_total * 100.0
        else:
            regime_proxy = None

        # regime_map_score: 오늘부터 누적 시작.
        # 과거 row는 fillna(0)로 채워져 있어 0은 결측 처리.
        regime_score = _to_float(r.get("regime_map_score"))
        if regime_score is not None and regime_score == 0.0:
            regime_score = None

        rows.append({
            "date": d,
            "kospi": kospi,
            "nasdaq": nasdaq,
            "invest_pct": invest,
            "top3_sco": top3_sco,
            "avg_sco": avg_sco,
            "regime_proxy": regime_proxy,
            "regime_score": regime_score,
        })

    # 상관계수
    def col(name):
        return [r[name] for r in rows]

    corr_results = []
    for idx_name, idx_key in [("KOSPI", "kospi"), ("NASDAQ", "nasdaq")]:
        for sig_label, sig_key in [
            ("invest_pct (투자비중)", "invest_pct"),
            ("top3_sco_avg",         "top3_sco"),
            ("avg_sco",              "avg_sco"),
            ("regime_proxy",         "regime_proxy"),
            ("regime_map_score",     "regime_score"),
        ]:
            c, n = pearson(col(idx_key), col(sig_key))
            corr_results.append((idx_name, sig_label, c, n))

    # 상관표 HTML
    def _cell(c):
        if c is None:
            return '<span style="color:#999;">-</span>'
        if c >= 0.6:    color = "#1e7e34"; weight = "bold"
        elif c >= 0.3:  color = "#27ae60"; weight = "600"
        elif c <= -0.6: color = "#922b21"; weight = "bold"
        elif c <= -0.3: color = "#c0392b"; weight = "600"
        else:           color = "#7f8c8d"; weight = "500"
        return f'<span style="color:{color};font-weight:{weight};">{c:+.3f}</span>'

    corr_rows = ""
    for idx_name, sig_label, c, n in corr_results:
        corr_rows += (
            f'<tr><td>{idx_name}</td><td>{sig_label}</td>'
            f'<td style="text-align:right;">{_cell(c)}</td>'
            f'<td style="text-align:right;color:#888;">{n}</td></tr>\n'
        )

    # 데이터 JSON (Chart.js)
    data_json = json.dumps(rows, ensure_ascii=False)
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    valid_total = sum(1 for r in rows if _valid(r["kospi"]))
    regime_score_valid = sum(1 for r in rows if _valid(r["regime_score"]))

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>Backtest: 지수 vs Regime / 투자비중</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Segoe UI', -apple-system, sans-serif;
  background: #f0f2f5; color: #2c3e50; padding: 14px; line-height: 1.4;
}}
.hdr {{ font-size: 18px; font-weight: 800; color: #2c3e50; margin-bottom: 4px; }}
.meta {{ font-size: 12px; color: #888; margin-bottom: 12px; }}
.note {{
  background: #fff8ee; border:1px solid #f1d9b1; border-radius: 8px;
  padding: 10px 12px; font-size: 12.5px; color: #5a4630; margin-bottom: 14px;
  line-height: 1.6;
}}
.note b {{ color: #b9772b; }}
.card {{
  background: #fff; border-radius: 10px; padding: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 14px;
}}
.card-title {{
  font-size: 13px; font-weight: 700; color: #2c3e50;
  border-bottom: 1px solid #eee; padding-bottom: 6px; margin-bottom: 10px;
  letter-spacing: 0.03em;
}}
.chart-wrap {{ position: relative; height: 480px; width: 100%; }}

table.corr {{
  width: 100%; border-collapse: collapse; font-size: 13px;
}}
table.corr th, table.corr td {{
  border-bottom: 1px solid #eee; padding: 6px 10px; text-align: left;
}}
table.corr th {{ background: #2c3e50; color: #fff; font-size: 11px; font-weight:600; }}
table.corr tbody tr:hover {{ background: #fafbfc; }}

.legend-explain {{ font-size: 11.5px; color: #666; margin-top: 8px; line-height: 1.6; }}
.legend-explain code {{ background: #eef; padding: 1px 4px; border-radius: 3px; font-size: 11px; }}
</style>
</head>
<body>

<div class="hdr">📈 Backtest: 지수 vs Regime / 투자비중 (확인용)</div>
<div class="meta">Updated: {update_time} · 데이터 포인트: {valid_total}일</div>

<div class="note">
  <b>⚠️ 목적</b>: KOSPI / NASDAQ 누적수익률에 가장 잘 비례하는 시그널을 확인 (Regime Score · 투자비중 · sco 등).<br>
  <b>regime_map_score</b>는 오늘부터 누적 시작 ({regime_score_valid}일치) → 백테스트 의미 없음.
  대신 동일 의미의 <code>regime_proxy = (sco_strong − sco_neg) / total_universe × 100</code>로 대체 (552일 누적).<br>
  <b>invest_pct</b>는 2026-03-19부터 진짜 값 (그 이전 245일은 placeholder 0 → 결측 처리). 실제 백테스트 표본은 52일.<br>
  좌Y축: KOSPI/NASDAQ 누적수익률(%). 우Y축: 시그널(스케일 다름, 0~100 또는 sco 값).
</div>

<div class="card">
  <div class="card-title">📊 시계열 비교 (이중 Y축)</div>
  <div class="chart-wrap"><canvas id="bt"></canvas></div>
  <div class="legend-explain">
    범례를 클릭하면 라인을 켜고 끌 수 있습니다. KOSPI/NASDAQ과 같이 움직이는 시그널이 상관관계가 높습니다.
  </div>
</div>

<div class="card">
  <div class="card-title">📐 Pearson 상관계수</div>
  <table class="corr">
    <thead>
      <tr><th>지수</th><th>시그널</th><th style="text-align:right;">상관계수</th><th style="text-align:right;">N (일)</th></tr>
    </thead>
    <tbody>
      {corr_rows}
    </tbody>
  </table>
  <div class="legend-explain">
    절대값 ≥ 0.6: 강한 상관 / 0.3~0.6: 중간 / &lt; 0.3: 약함. 양수=같이 움직임 / 음수=반대로 움직임.<br>
    데이터가 누적된 구간만 계산되므로 N이 작은 시그널은 참고만.
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const ROWS = {data_json};
const labels = ROWS.map(r => r.date);

const ds = (label, key, color, yAxis, dash) => ({{
  label, data: ROWS.map(r => r[key]),
  borderColor: color, backgroundColor: color,
  borderWidth: 1.8, pointRadius: 0,
  fill: false, yAxisID: yAxis, tension: 0.15,
  borderDash: dash || [],
  spanGaps: true,
}});

new Chart(document.getElementById('bt').getContext('2d'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [
      ds('KOSPI 누적%',  'kospi',        '#c0392b', 'yIdx'),
      ds('NASDAQ 누적%', 'nasdaq',       '#1f3b73', 'yIdx'),
      ds('invest_pct',   'invest_pct',   '#e67e22', 'ySig'),
      ds('top3_sco_avg', 'top3_sco',     '#27ae60', 'ySig', [4,2]),
      ds('avg_sco',      'avg_sco',      '#16a085', 'ySig', [4,2]),
      ds('regime_proxy', 'regime_proxy', '#8e44ad', 'ySig'),
      ds('regime_map_score', 'regime_score', '#000', 'ySig'),
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 14, font: {{size: 11}} }} }},
      tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': ' + (c.parsed.y==null?'-':c.parsed.y.toFixed(2)) }} }}
    }},
    scales: {{
      x: {{ ticks: {{ maxTicksLimit: 14, font: {{size: 9}} }}, grid: {{ display: false }} }},
      yIdx: {{ position: 'left', title: {{ display:true, text:'지수 누적수익률 (%)' }}, ticks: {{ font: {{size: 10}} }} }},
      ySig: {{ position: 'right', title: {{ display:true, text:'시그널 (sco / %)' }}, grid: {{ display:false }}, ticks: {{ font: {{size: 10}} }} }}
    }}
  }}
}});
</script>

</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] backtest.html 생성 완료 → {OUT_HTML}")
    print(f"     데이터 포인트: {valid_total}일 / regime_map_score 누적: {regime_score_valid}일")


if __name__ == "__main__":
    main()
