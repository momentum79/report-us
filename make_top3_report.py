# make_top3_report.py
# ─────────────────────────────────────────────────────────
# top3_etf_track.json 읽어서 top3_etf_daily_result.html 생성
# 실행: python make_top3_report.py
# ─────────────────────────────────────────────────────────

import json
import pathlib
import datetime

REPORT_DIR = pathlib.Path("D:/py/report-us")
JSON_PATH  = REPORT_DIR / "top3_etf_track.json"
OUT_HTML   = REPORT_DIR / "top3_etf_daily_result.html"

MA_CONFIGS = [
    (4,  "#ff005f", [3, 2]),   # MA4  로즈 점선
    (9,  "#a78bfa", [5, 3]),   # MA9  보라 점선
    (18, "#f6ad55", [8, 4]),   # MA18 주황 점선
]


BIN_COLORS = {
    "<0":    "#fc8181",
    "0~5":   "#f6ad55",
    "5~8":   "#fbd38d",
    "8~11":  "#a78bfa",
    "11~14": "#5bc8ff",
    ">=14":  "#00d4a8",
}

TREND_LABEL = {
    "LIME":   ("LIME",   "#2ecc71"),
    "GREEN":  ("GREEN",  "#27ae60"),
    "-":      ("-",      "#95a5a6"),
    "PURPLE": ("PURPLE", "#9b59b6"),
    "RED":    ("RED",    "#e74c3c"),
}


def sco_bin(v):
    if v is None:  return "nan"
    if v < 0:      return "<0"
    if v < 5:      return "0~5"
    if v < 8:      return "5~8"
    if v < 11:     return "8~11"
    if v < 14:     return "11~14"
    return ">=14"

def sco_color(v):
    return BIN_COLORS.get(sco_bin(v), "#8b949e")

def rolling_ma(values, n):
    result = []
    for i, v in enumerate(values):
        window = [x for x in values[max(0, i-n+1):i+1] if x is not None]
        if len(window) < n:
            result.append(None)
        else:
            result.append(round(sum(window) / len(window), 2))
    return result

def trend_badge(trend):
    label, color = TREND_LABEL.get(trend, (trend, "#95a5a6"))
    return f'<span style="background:{color};color:#fff;padding:1px 7px;border-radius:4px;font-size:11px;font-weight:bold;">{label}</span>'


def main():
    # ── JSON 로드 ──
    if not JSON_PATH.exists():
        print(f"❌ JSON 파일 없음: {JSON_PATH}")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not raw:
        print("❌ JSON 데이터 없음"); return

    # 날짜 정렬
    sorted_keys = sorted(raw.keys())
    records = [raw[k] for k in sorted_keys]

    dates        = sorted_keys
    sco_avg      = [r.get("top3_sco_avg") for r in records]
    names_list   = [r.get("top3_names", "") for r in records]
    invest_pcts  = [r.get("invest_pct") for r in records]
    kospi_trends = [r.get("kospi_trend", "-") for r in records]
    nasdaq_trends= [r.get("nasdaq_trend", "-") for r in records]
    kospi_rtns   = [r.get("kospi_rtn") for r in records]
    nasdaq_rtns  = [r.get("nasdaq_rtn") for r in records]

    # MA 계산
    ma_series = {}
    for (n, color, dash) in MA_CONFIGS:
        ma_series[n] = rolling_ma(sco_avg, n)

    # 구간 레이블
    bins_list = [sco_bin(v) for v in sco_avg]

    # 마지막 값
    last       = records[-1]
    last_date  = dates[-1]
    last_avg   = last.get("top3_sco_avg")
    last_names = last.get("top3_names", "")
    last_ma4   = ma_series[4][-1]
    last_invest= last.get("invest_pct", 0)
    last_kospi_trend  = last.get("kospi_trend", "-")
    last_nasdaq_trend = last.get("nasdaq_trend", "-")
    # 마지막 유효한 kospi/nasdaq 수익률 (None이면 뒤에서 찾기)
    last_kospi  = next((v for v in reversed(kospi_rtns)  if v is not None), 0)
    last_nasdaq = next((v for v in reversed(nasdaq_rtns) if v is not None), 0)
    last_col   = sco_color(last_avg)
    last_bin   = sco_bin(last_avg)
    kr_col     = '#00d4a8' if last_kospi  >= 0 else '#fc8181'
    nq_col     = '#00d4a8' if last_nasdaq >= 0 else '#fc8181'

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total_days = len(dates)

    # ── HTML 생성 ──
    page = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>Top3 ETF 시장온도</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+KR:wght@300;400;600;700&display=swap');
:root{{--bg:#f4f7f6;--sur:#ffffff;--sur2:#f0f4f3;--bor:#e0e7e5;
      --txt:#2c3e50;--txt2:#4a5568;
      --green:#1a9e75;--blue:#2980b9;--purple:#8e44ad;
      --orange:#e67e22;--red:#e74c3c}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--txt);font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;font-size:14px;line-height:1.6;padding:15px}}
.hdr{{padding:12px 0 14px;border-bottom:2px solid #3498db;margin-bottom:16px}}
.hdr h1{{font-size:1.2em;font-weight:bold;color:#2c3e50;margin:0 0 2px}}
.hdr .sub{{font-size:13px;color:#4a5568}}
.top-nav{{display:flex;background-color:#2c3e50;margin-bottom:16px;border-radius:8px;overflow:hidden;width:fit-content}}
.nav-item{{padding:8px 15px;color:#bdc3c7;text-align:center;font-weight:bold;text-decoration:none;transition:all 0.3s;font-size:13px}}
.nav-item:hover{{background-color:#34495e;color:#fff}}
.nav-item.active{{background-color:#3498db;color:white}}
.wrap{{max-width:1320px;margin:0;display:flex;flex-direction:column;gap:16px;align-items:flex-start}}
.card{{background:white;border-radius:8px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.08);width:100%}}
.ct{{font-size:1.0em;font-weight:bold;color:#2c3e50;margin-bottom:12px;
     padding-bottom:4px;border-bottom:2px solid #3498db}}
.sg{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
.sb{{background:#f0f4f3;border:1px solid #d5e0de;border-radius:6px;padding:12px;text-align:center}}
.sl{{font-size:10px;color:#4a5568;margin-bottom:5px;font-weight:bold;text-transform:uppercase}}
.sv{{font-family:'IBM Plex Mono',monospace;font-size:20px;font-weight:700}}
.ss{{font-size:11px;color:#4a5568;margin-top:3px}}
.bg{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}}
.bc{{background:#f8fafa;border-radius:6px;padding:10px 12px;border-left:4px solid;box-shadow:0 1px 3px rgba(0,0,0,0.06)}}
.bn{{font-size:11px;font-weight:700;margin-bottom:7px}}
.br{{display:flex;justify-content:space-between;font-size:11px;color:#4a5568;margin-bottom:2px}}
.br span:last-child{{font-family:'IBM Plex Mono',monospace;color:#2c3e50;font-weight:600}}
canvas{{max-height:340px}}
.range-btns{{display:flex;gap:5px;margin-bottom:10px}}
.rbtn{{padding:3px 10px;font-size:11px;font-weight:700;border:1px solid #ccc;border-radius:4px;background:#f0f4f3;color:#4a5568;cursor:pointer;transition:all 0.2s}}
.rbtn:hover{{background:#ddeeff;border-color:#3498db;color:#2c3e50}}
.rbtn.active{{background:#3498db;border-color:#2980b9;color:#fff}}
.note{{font-size:13px;color:#4a5568;margin-top:8px;line-height:1.9}}
@media(max-width:900px){{.sg,.bg{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:600px){{
  .sg{{grid-template-columns:repeat(2,1fr);gap:6px}}
  .sb{{padding:6px 8px}}
  .sl{{font-size:9px;margin-bottom:3px}}
  .sv{{font-size:16px}}
  .ss{{font-size:9px;margin-top:2px}}
  .bg{{grid-template-columns:repeat(2,1fr);gap:6px}}
  .bc{{padding:7px 9px}}
  .bn{{font-size:10px;margin-bottom:5px}}
  .br{{font-size:10px}}
  .note{{display:none}}
  #mc{{height:300px !important;max-height:300px !important}}
  #hc{{height:200px !important;max-height:200px !important}}
  body{{padding:8px}}
  .hdr{{padding:8px 0 10px}}
  .card{{padding:10px}}
  .wrap{{gap:10px}}
}}
@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
</style>
</head>
<body>
  <div class="top-nav">
    <a href="kor_etf.html" class="nav-item">한국 ETF</a>
    <a href="top3_etf_daily_result.html" class="nav-item active">Top3추세</a>
    <a href="adv_momentum.html" class="nav-item">연금 ETF</a>
  </div>
  <h1>📈 Top3 ETF 시장온도</h1>
  <div class="sub">전체 ETF 36개 · Final_score 기준 Top3(SCO≥11 우선) · {total_days}거래일 누적 · 최종업데이트: {now}</div>
</div>
<div class="wrap">

  <div class="card">
    <div class="ct">현재 상태 ({last_date} 기준)</div>
    <div class="sg">
      <div class="sb">
        <div class="sl">Top3 SCO 평균</div>
        <div class="sv" style="color:{last_col}">{f"{last_avg:.1f}" if last_avg is not None else "-"}</div>
        <div class="ss">시장온도 핵심지표</div>
      </div>
      <div class="sb">
        <div class="sl">SCO MA4</div>
        <div class="sv" style="color:#ff005f">{f"{last_ma4:.1f}" if last_ma4 is not None else "-"}</div>
        <div class="ss">4일 이동평균</div>
      </div>
      <div class="sb">
        <div class="sl">SCO 구간</div>
        <div class="sv" style="color:{last_col};font-size:16px">{last_bin}</div>
        <div class="ss">현재 구간</div>
      </div>
      <div class="sb">
        <div class="sl">Top3 종목</div>
        <div class="sv" style="font-size:12px;color:#2c3e50;padding-top:4px;line-height:1.9;font-weight:600">
          {"<br>".join(last_names.split(",")) if last_names else "-"}
        </div>
      </div>
      <div class="sb">
        <div class="sl">코스피 추세</div>
        <div class="sv" style="font-size:14px;padding-top:6px">{trend_badge(last_kospi_trend)}</div>
        <div class="ss">누적 {last_kospi:+.1f}% · 투자 {last_invest:.0f}%</div>
      </div>
      <div class="sb">
        <div class="sl">나스닥 추세</div>
        <div class="sv" style="font-size:14px;padding-top:6px">{trend_badge(last_nasdaq_trend)}</div>
        <div class="ss">누적 {last_nasdaq:+.1f}%</div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="ct">Top3 SCO 평균(<span id="dynamic-sco-avg" style="color:#3498db;">-</span>) + 코스피 / 나스닥</div>
    <div class="range-btns">
      <button class="rbtn" onclick="setRange(21)">1M</button>
      <button class="rbtn" onclick="setRange(63)">3M</button>
      <button class="rbtn" onclick="setRange(126)">6M</button>
      <button class="rbtn active" onclick="setRange(252)">1Y</button>
      <button class="rbtn" onclick="setRange(null)">ALL</button>
    </div>
    <div id="mc-wrap" style="position:relative;width:100%;height:300px">
      <canvas id="mc"></canvas>
    </div>
    <div class="note" id="mc-note">
      ● 구간 배경: ≥14=초록 / 11~14=파랑 / 8~11=보라 / 5~8=연주황 / 0~5=주황 / &lt;0=빨강 &nbsp;|&nbsp;
      초록실선=SCO평균 / 로즈점선=MA4 / 보라점선=MA9 &nbsp;|&nbsp;
      코스피=주황실선 / 나스닥=검정실선 (우축) &nbsp;|&nbsp; 기준선: 11 / 8 / 0
    </div>
  </div>

  <div class="card">
    <div class="ct">Top3 SCO 평균 일별 막대</div>
    <div id="hc-wrap" style="position:relative;width:100%;height:220px">
      <canvas id="hc"></canvas>
    </div>
  </div>

</div>
<script>
const dates      = {json.dumps(dates)};
const scoAvg     = {json.dumps(sco_avg)};
const scoMA4     = {json.dumps(ma_series[4])};
const scoMA9     = {json.dumps(ma_series[9])};
const scoMA18    = {json.dumps(ma_series[18])};
const namesList  = {json.dumps(names_list)};
const binsL      = {json.dumps(bins_list)};
const kospiR     = {json.dumps(kospi_rtns)};
const nasdaqR    = {json.dumps(nasdaq_rtns)};

const BC = {{
  '<0':'#e74c3c','0~5':'#e67e22','5~8':'#f39c12',
  '8~11':'#8e44ad','11~14':'#2980b9','>=14':'#1a9e75','nan':'#e74c3c'
}};

// ── 기준선 플러그인 (11, 8, 0) ──
const refP = {{
  id:'refP',
  afterDraw(chart) {{
    const {{ctx,chartArea,scales}} = chart;
    if(!scales.yS) return;
    [[11,'#1a9e7599'],[8,'#e67e2299'],[0,'#e74c3c99']].forEach(([v,col]) => {{
      const y = scales.yS.getPixelForValue(v);
      ctx.save();
      ctx.strokeStyle=col; ctx.lineWidth=1; ctx.setLineDash([6,4]);
      ctx.beginPath(); ctx.moveTo(chartArea.left,y); ctx.lineTo(chartArea.right,y); ctx.stroke();
      ctx.restore();
    }});
  }}
}};

// ── 메인 차트 ──
const isMobile = window.innerWidth <= 600;
if(isMobile) {{
  document.getElementById('mc-wrap').style.height = '400px';
  document.getElementById('mc-note').style.display = 'none';
}}

// 현재 구간 상태 (기본 1Y = 252일)
let currentRange = 252;

// 구간 슬라이스 헬퍼
function sliceData(arr, n) {{
  if(n === null) return arr;
  return arr.slice(-n);
}}

// bgP 플러그인은 슬라이스된 binsL 기준으로 동작해야 하므로 동적으로 참조
let activeBinsL = sliceData(binsL, currentRange);

const bgPdyn = {{
  id:'bgPdyn',
  beforeDraw(chart) {{
    const {{ctx,chartArea,scales}} = chart;
    if(!chartArea) return;
    const xs = scales.x;
    ctx.save();
    let prev=null, sx=null;
    activeBinsL.forEach((b,i) => {{
      const x = xs.getPixelForValue(i);
      if(b!==prev) {{
        if(prev!==null && sx!==null) {{
          ctx.fillStyle=(BC[prev]||'#fff')+(prev==='nan'?'40':'18');
          ctx.fillRect(sx,chartArea.top,x-sx,chartArea.bottom-chartArea.top);
        }}
        prev=b; sx=x;
      }}
    }});
    if(prev&&sx!==null) {{
      ctx.fillStyle=(BC[prev]||'#fff')+(prev==='nan'?'40':'18');
      ctx.fillRect(sx,chartArea.top,xs.getPixelForValue(activeBinsL.length-1)-sx,chartArea.bottom-chartArea.top);
    }}
    ctx.restore();
  }}
}};

const mcChart = new Chart(document.getElementById('mc'), {{
  type:'line', plugins:[bgPdyn,refP],
  data:{{
    labels: sliceData(dates, currentRange),
    datasets:[
      {{label:'Top3 SCO 평균', data:sliceData(scoAvg,currentRange),  borderColor:'#1a9e75', borderWidth:2.5, pointRadius:0, tension:0.3, yAxisID:'yS', fill:false, spanGaps:true}},
      {{label:'MA4',           data:sliceData(scoMA4,currentRange),  borderColor:'#ff005f', borderWidth:2,   borderDash:[3,2], pointRadius:0, tension:0.3, yAxisID:'yS', fill:false, spanGaps:true}},
      {{label:'MA9',           data:sliceData(scoMA9,currentRange),  borderColor:'#8e44ad', borderWidth:2,   borderDash:[5,3], pointRadius:0, tension:0.3, yAxisID:'yS', fill:false, spanGaps:true}},
      {{label:'코스피(%)',      data:rebaseReturns(kospiR,currentRange),  borderColor:'#e67e22', borderWidth:1.5, pointRadius:0, tension:0.3, yAxisID:'yK', fill:false, spanGaps:true}},
      {{label:'나스닥(%)',      data:rebaseReturns(nasdaqR,currentRange), borderColor:'#000000', borderWidth:1.5, pointRadius:0, tension:0.3, yAxisID:'yK', fill:false, spanGaps:true}},
    ]
  }},
  options:{{
    responsive:true,
    maintainAspectRatio:false,
    interaction:{{mode:'index',intersect:false}},
    plugins:{{
      legend:{{display:!isMobile, labels:{{color:'#2c3e50',font:{{size:11}},boxWidth:16,padding:14}}}},
      tooltip:{{
        backgroundColor:'#ffffff',borderColor:'#dde4e2',borderWidth:1,
        titleColor:'#2c3e50',bodyColor:'#4a5568',
        callbacks:{{
          afterTitle(items){{
            const offset = currentRange===null ? 0 : Math.max(0, dates.length - currentRange);
            return 'Top3: '+namesList[offset + items[0].dataIndex].replace(/,/g,' / ');
          }},
          label(i){{
            if(i.raw===null) return null;
            return i.datasetIndex<=2
              ? i.dataset.label+': '+i.raw.toFixed(1)
              : i.dataset.label+': '+(i.raw>=0?'+':'')+i.raw.toFixed(2)+'%';
          }}
        }}
      }}
    }},
    scales:{{
      x:{{ticks:{{color:'#4a5568',font:{{size:isMobile?9:10}},maxTicksLimit:isMobile?6:12}},grid:{{color:'#e8eeec'}}}},
      yS:{{
        type:'linear',position:'left',
        ticks:{{color:'#1a9e75',font:{{size:isMobile?9:10}}}},
        grid:{{color:'#e8eeec'}},
        title:{{display:!isMobile,text:'Top3 SCO 평균',color:'#1a9e75',font:{{size:10}}}}
      }},
      yK:{{
        type:'linear',position:'right',
        ticks:{{color:'#e67e22',font:{{size:isMobile?9:10}},callback:v=>v.toFixed(0)+'%'}},
        grid:{{drawOnChartArea:false}},
        title:{{display:!isMobile,text:'누적수익률',color:'#e67e22',font:{{size:10}}}}
      }}
    }}
  }}
}});

// ── 일별 막대 ──
function makeHColors(arr) {{
  return arr.map(v=>{{
    if(v===null) return '#e74c3c40';
    if(v>=14) return '#1a9e7599';
    if(v>=11) return '#2980b999';
    if(v>=8)  return '#8e44ad99';
    if(v>=5)  return '#f39c1299';
    if(v>=0)  return '#e67e2299';
    return '#e74c3c99';
  }});
}}
if(isMobile) document.getElementById('hc-wrap').style.height = '260px';
const hcChart = new Chart(document.getElementById('hc'),{{
  type:'bar',
  data:{{
    labels:sliceData(dates,currentRange),
    datasets:[{{
      label:'Top3 SCO 평균',
      data:sliceData(scoAvg,currentRange),
      backgroundColor:makeHColors(sliceData(scoAvg,currentRange)),
      borderWidth:0
    }}]
  }},
  options:{{
    responsive:true,
    maintainAspectRatio:false,
    plugins:{{
      legend:{{display:false}},
      tooltip:{{
        backgroundColor:'#ffffff',borderColor:'#dde4e2',borderWidth:1,
        titleColor:'#2c3e50',bodyColor:'#4a5568',
        callbacks:{{
          label(i){{return i.raw!==null?'SCO: '+i.raw.toFixed(1):null}},
          afterLabel(i){{
            const offset = currentRange===null ? 0 : Math.max(0, dates.length - currentRange);
            return 'Top3: '+namesList[offset + i.dataIndex].replace(/,/g,' / ');
          }}
        }}
      }}
    }},
    scales:{{
      x:{{ticks:{{color:'#4a5568',font:{{size:isMobile?9:10}},maxTicksLimit:isMobile?6:12}},grid:{{color:'#e8eeec'}}}},
      y:{{ticks:{{color:'#4a5568',font:{{size:isMobile?9:10}}}},grid:{{color:'#e8eeec'}},
          title:{{display:!isMobile,text:'SCO 평균',color:'#4a5568',font:{{size:10}}}}}}
    }}
  }}
}});

// 기간 기준 수익률 재계산 (기간 첫날 값을 0으로 리베이스)
function rebaseReturns(arr, n) {{
  const sliced = sliceData(arr, n);
  // 첫 번째 유효한 값 찾기
  const firstValid = sliced.find(v => v !== null);
  if (firstValid === null || firstValid === undefined) return sliced;
  return sliced.map(v => v === null ? null : parseFloat((v - firstValid).toFixed(2)));
}}

// ── 동적 평균 업데이트 헬퍼 ──
function updateDynamicAvg(sliced) {{
  const validSco = sliced.filter(v => v !== null && v !== undefined);
  let avgText = "-";
  if (validSco.length > 0) {{
    avgText = (validSco.reduce((a, b) => a + b, 0) / validSco.length).toFixed(1);
  }}
  const avgEl = document.getElementById('dynamic-sco-avg');
  if (avgEl) avgEl.innerText = avgText;
}}

// ── 구간 전환 함수 ──
function setRange(n) {{
  currentRange = n;
  activeBinsL = sliceData(binsL, n);

  // 메인 차트 업데이트
  mcChart.data.labels      = sliceData(dates, n);
  mcChart.data.datasets[0].data = sliceData(scoAvg,  n);
  mcChart.data.datasets[1].data = sliceData(scoMA4,  n);
  mcChart.data.datasets[2].data = sliceData(scoMA9,  n);
  mcChart.data.datasets[3].data = rebaseReturns(kospiR,  n);
  mcChart.data.datasets[4].data = rebaseReturns(nasdaqR, n);
  mcChart.update();

  // 막대 차트 업데이트
  const slicedSco = sliceData(scoAvg, n);
  updateDynamicAvg(slicedSco);
  
  hcChart.data.labels = sliceData(dates, n);
  hcChart.data.datasets[0].data = slicedSco;
  hcChart.data.datasets[0].backgroundColor = makeHColors(slicedSco);
  hcChart.update();

  // 버튼 active 상태 업데이트
  document.querySelectorAll('.rbtn').forEach(btn => {{
    const v = btn.getAttribute('onclick');
    const isActive =
      (n === null && v === 'setRange(null)') ||
      (n !== null && v === `setRange(${{n}})`);
    btn.classList.toggle('active', isActive);
  }});
}}

// 초기 평균값 셋팅
updateDynamicAvg(sliceData(scoAvg, currentRange));

</script>
</body>
</html>"""

    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] top3_etf_daily_result.html 생성 완료 → {OUT_HTML}")
    print(f"     총 {total_days}일 데이터 / 최근: {last_date} / SCO: {last_avg}")


if __name__ == "__main__":
    main()
