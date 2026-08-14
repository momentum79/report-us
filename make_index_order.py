# make_index_order.py
# 주문 게시판 - 여러 게시판의 "주문용" 핵심 조각을 한 페이지로 모아 보여줌
#   출력: report-us/order.html
#   방식: 이미 생성된 각 게시판 HTML에서 해당 조각을 그대로 추출(fragment extraction).
#         → 원본 데이터 로직/가격조회/리밸런싱 txt 파일에 전혀 영향 없음.
#   ※ 배치에서 각 원본 게시판 생성기들 "다음에" 실행돼야 최신 조각이 반영됨.
#
#   구성:
#     1) 업데이트 시간
#     2) 통합ETF 시장 뱃지(코닥미나일유인상홍브)
#     3) TODAY'S TOP3 LEADERSHIP 도넛 2개
#     4) 통합ETF 주문용 최종 보유 목록  |  당일/주간/월간 Top5
#     5) 한국ETF 주문용 최종 보유 목록  |  당일/주간/월간 Top3
#     6) 해선 주문용 Top4
#     7) 미ETF 주문 목록
#     8) 국가별 랭킹 Top5
#     9) AI Core Regime 박스

import re
import html as _html
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
OUT_HTML = BASE / "order.html"
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read(name):
    p = BASE / name
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def cut(text, start, end, include_end=True, start_from=0):
    """start ~ end 사이 조각 추출 (end 최초 등장 기준)."""
    i = text.find(start, start_from)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    if j < 0:
        return ""
    return text[i:(j + len(end)) if include_end else j]


def cut_before(text, start, before):
    """start ~ (before 최초 등장 직전) 조각 추출."""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(before, i + len(start))
    if j < 0:
        return text[i:].rstrip()
    return text[i:j].rstrip()


# ── 조각 빌더 ─────────────────────────────────────────────────────────────
def frag_badges():
    h = _read("total_etf_combined.html")
    return cut(h, '<table style="border-collapse:separate;border-spacing:3px', '</table>')


def frag_top5():
    h = _read("total_etf_combined.html")
    return cut(h, '<div class="t5-section">', '</div>\n')


def frag_total_order_table():
    h = _read("total_etf_combined.html")
    return cut(h, '<h2>🧾 주문용 최종 보유 목록', '</tbody></table>')


def frag_leadership():
    h = _read("main_hub.html")
    card = cut(h, '<div class="leadership-card">', '\n  </div>')
    m = re.search(r'const LEADERSHIP\s*=\s*(\{.*?\});', h)
    data = m.group(1) if m else "null"
    return card, data


def frag_kr_top3():
    h = _read("kor_etf.html")
    return cut_before(h, '<div class="t3-section">',
                      '<h2 style="border-bottom: 2px solid #e67e22;">🧾 주문용')


def frag_kr_order_table():
    h = _read("kor_etf.html")
    return cut(h, '<h2 style="border-bottom: 2px solid #e67e22;">🧾 주문용 최종 보유 목록',
               '</tbody></table>')


def frag_table_only(fname, after_marker):
    """after_marker 이후 첫 styled-table 하나만 추출."""
    h = _read(fname)
    i = h.find(after_marker)
    if i < 0:
        return ""
    return cut(h, '<table class="styled-table">', '</tbody></table>', start_from=i)


def frag_futures_top4():
    return frag_table_only("futures.html", '🎯 주문용 Top4 (오늘)')


def frag_us_etf_order():
    return frag_table_only("us_etf.html", '🎯 주문 목록')


def frag_country_top5(n=5):
    h = _read("country_returns.html")
    tbl = cut(h, '<table class="styled-table" id="rankTable">', '</table>')
    if not tbl:
        return ""
    head, _sep, body = tbl.partition('<tbody>')
    rows = re.findall(r'<tr>.*?</tr>', body, re.DOTALL)[:n]
    tbl = head + '<tbody>\n' + '\n'.join(rows) + '\n</tbody></table>'
    tbl = tbl.replace('id="rankTable"', 'id="orderCountryTable"')
    tbl = re.sub(r'\s*onclick="sortTableCustom\([^)]*\)"', '', tbl)
    return tbl


def frag_ai_core():
    """AI 관찰판(total_etf_combined_AI.html)의 전체 AI Core Regime 카드
    (좌: Regime + 우: 🏆 Top AI Baskets)를 통째로 추출."""
    h = _read("total_etf_combined_AI.html")
    i = h.find('<div class="ai-core-card">')
    if i < 0:
        return ""
    # 카드 다음에 오는 형제 블록(basket-flow-card) 직전까지 잘라, 마지막 </div>로 마감
    j = h.find('<div class="basket-flow-card">', i)
    seg = h[i:j] if j > 0 else h[i:]
    k = seg.rfind('</div>')
    return (seg[:k + 6] if k >= 0 else seg).rstrip()


def _safe(fn, *a):
    try:
        return fn(*a) or ""
    except Exception as e:
        return f'<p style="color:#c0392b;">[{fn.__name__} 오류] {_html.escape(str(e))}</p>'


def frag_asset_donut():
    """투자비중 + 통화비중 도넛 카드 (보유자산 게시판과 동일). holdings_*.json 직접 읽음."""
    from asset_donut import build_card_html
    return build_card_html()


def build_content():
    badges = _safe(frag_badges)
    top5 = _safe(frag_top5)
    donut = _safe(frag_asset_donut)
    total_tbl = _safe(frag_total_order_table)
    kr_top3 = _safe(frag_kr_top3)
    kr_tbl = _safe(frag_kr_order_table)
    fut = _safe(frag_futures_top4)
    us_etf = _safe(frag_us_etf_order)
    country = _safe(frag_country_top5)

    parts = []
    # 2) 시장 뱃지
    parts.append(f'<div class="section">{badges}</div>')
    # (도넛 리더십 + AI Core Regime 은 상황판(main_hub)으로 이동)
    # 4) 통합 주문표 | Top5 | 투자·통화비중 도넛
    parts.append(
        '<div class="section"><div class="cols-tight">'
        f'<div>{total_tbl}</div>'
        f'<div>{top5}</div>'
        f'<div>{donut}</div>'
        '</div></div>'
    )
    # 5) 한국 주문표 | Top3
    parts.append(
        '<div class="section"><div class="cols-tight">'
        f'<div>{kr_tbl}</div>'
        f'<div>{kr_top3}</div>'
        '</div></div>'
    )
    # 6+7) 해선 주문용 Top4 | 미ETF 주문 목록 (나란히)
    parts.append(
        '<div class="section"><div class="cols-tight">'
        f'<div><h2>🎯 해선 주문용 Top4</h2>{fut}</div>'
        f'<div><h2>🎯 미ETF 주문 목록</h2>{us_etf}</div>'
        '</div></div>'
    )
    # 8) 국가별 랭킹 Top5
    parts.append(f'<div class="section country-rank-section"><h2>🌍 국가별 랭킹 Top5</h2>{country}</div>')

    return "\n".join(parts)


CSS = r"""
body { font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif; padding:12px; margin:0; background:#f4f7f6; color:#2c3e50; line-height:1.4; }
.top-nav-container { display:flex; margin-bottom:10px; }
.top-nav { display:flex; background:#2c3e50; border-radius:8px; overflow:hidden; flex-wrap:wrap; }
.nav-item { padding:7px 14px; color:#bdc3c7; cursor:pointer; text-decoration:none; font-size:0.85em; font-weight:bold; transition:0.2s; }
.nav-item:hover { background:#34495e; color:#fff; }
.nav-item.active { background:#3498db; color:#fff; }
.update-bar { font-size:0.8em; color:#888; margin-bottom:8px; }
.section { margin-bottom:8px; }
h2 { margin:12px 0 6px 0; padding-bottom:4px; color:#2c3e50; border-bottom:2px solid #8e44ad; font-size:1.12em; }
.cols-tight { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; }
.cols-tight > div { flex:0 1 auto; min-width:0; }

/* ── styled-table (통합/한국 기준: 보라 헤더) ── */
.styled-table { width:auto; min-width:unset; max-width:100%; border-collapse:collapse; margin:4px 0 10px 0; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.1); font-size:13px; border-radius:8px; overflow:hidden; }
.styled-table thead tr { background:linear-gradient(135deg,#8e44ad,#6c3483); color:#fff; text-align:center; }
.styled-table th, .styled-table td { padding:5px 10px; border-bottom:1px solid #eee; white-space:nowrap; }
.styled-table td { text-align:center; }
.styled-table tbody tr:hover { background:#f1f8ff; }
.styled-table td.narrow { font-weight:bold; color:#2980b9; text-align:left; }
.styled-table td.name-col { max-width:150px; overflow:hidden; text-overflow:ellipsis; text-align:left; }
.sig-up, .up { color:#27ae60; font-weight:bold; }
.sig-down, .down { color:#e74c3c; font-weight:bold; }
.held-bold { background:#fff9c4 !important; color:#d32f2f !important; font-weight:bold !important; }
.final-order-table { min-width:unset; }
.country-rank-section { width:fit-content; max-width:100%; }
#orderCountryTable { min-width:340px; }
.warn-x td { opacity:0.55; }
.warn-x td.narrow, .warn-x td.name-col { text-decoration:line-through; color:#999 !important; }
.pos-badge { display:inline-block; width:22px; height:22px; line-height:22px; border-radius:50%; font-size:0.75rem; font-weight:bold; color:#fff; text-align:center; }
.pos-1 { background:#16a34a !important; } .pos-2 { background:#65a30d !important; }
.pos-3 { background:#d97706 !important; } .pos-4 { background:#ea580c !important; } .pos-5 { background:#dc2626 !important; }
.chart-trigger { cursor:pointer; text-decoration:underline dotted; }
.chart-trigger:hover { background:#e8f4f8 !important; }
.ticker-col { cursor:pointer; }
.index-trigger { cursor:default; }
.sig-jung { background:#e8f5e9; color:#27ae60 !important; font-weight:bold; }
.sig-yeok { background:#ffebee; color:#e74c3c !important; font-weight:bold; }
td[data-code], td[data-code] + td { cursor:pointer; }
td[data-code] + td:hover { background:#e8f4f8 !important; }
.pc-only {}
@media (max-width:700px) {
  .pc-only { display:none !important; }
  #orderCountryTable { min-width:min(340px, calc(100vw - 24px)); }
}

/* ── 국가별 랭킹 col-* ── */
.col-score { text-align:right; font-weight:bold; font-family:monospace; font-size:13px; color:#2c3e50; }
.col-ticker { font-weight:bold; color:#2980b9; text-align:left; }
.col-name { text-align:left; max-width:150px; overflow:hidden; text-overflow:ellipsis; }
.col-chg, .col-return3m, .col-pos, .col-sco, .col-ma, .col-avg, .col-jung { text-align:center; }
.col-low { text-align:center; }
.low-badge { display:inline-block; padding:2px 7px; border-radius:10px; font-size:10px; font-weight:bold; color:#fff; text-align:center; min-width:30px; }
.low-jeo { background:#2ecc71; } .low-jeo2 { background:#3498db; } .low-both { background:#e74c3c; } .low-track { background:#95a5a6; }

/* ── 당일/주간/월간 Top5 ── */
.t5-section { margin:0; }
.t5-section-title { font-size:1.12em; font-weight:bold; color:#2c3e50; border-bottom:2px solid #8e44ad; padding-bottom:4px; margin:12px 0 6px 0; }
.t5-cards-row { display:flex; gap:8px; flex-wrap:nowrap; align-items:flex-start; }
.t5-card { background:#fff; border-radius:7px; box-shadow:0 2px 6px rgba(0,0,0,0.09); min-width:110px; max-width:160px; flex:0 0 auto; overflow:hidden; }
.t5-header { display:flex; align-items:center; justify-content:space-between; padding:5px 9px 4px 9px; border-bottom:1px solid #eee; gap:4px; }
.t5-title { font-size:0.8em; font-weight:bold; color:#2c3e50; white-space:nowrap; }
.t5-label { font-size:0.72em; color:#888; white-space:nowrap; background:#f0f0f0; border-radius:3px; padding:1px 5px; }
.t5-body { padding:5px 9px 6px 9px; }
.t5-row { display:flex; align-items:center; gap:5px; padding:2px 0; border-bottom:1px solid #f5f5f5; font-size:0.82em; }
.t5-row:last-child { border-bottom:none; }
.t5-medal { font-size:0.88em; flex-shrink:0; min-width:16px; text-align:center; }
.t5-name { flex:1; color:#2c3e50; font-weight:700; white-space:nowrap; font-size:0.93em; letter-spacing:0.02em; }
.t5-empty { font-size:0.78em; color:#aaa; padding:6px 0; }

/* ── 당일/주간/월간 Top3 ── */
.t3-section { margin:0; }
.t3-section-title { font-size:1.12em; font-weight:bold; color:#2c3e50; border-bottom:2px solid #8e44ad; padding-bottom:4px; margin:12px 0 6px 0; }
.t3-cards-row { display:flex; gap:8px; flex-wrap:nowrap; align-items:flex-start; }
.t3-card { background:#fff; border-radius:7px; box-shadow:0 2px 6px rgba(0,0,0,0.09); min-width:130px; max-width:180px; flex:0 0 auto; overflow:hidden; }
.t3-header { display:flex; align-items:center; justify-content:space-between; padding:5px 9px 4px 9px; background:#fafafa; border-bottom:1px solid #eee; gap:4px; }
.t3-title { font-size:0.8em; font-weight:bold; color:#2c3e50; white-space:nowrap; }
.t3-label { font-size:0.72em; color:#888; white-space:nowrap; background:#f0f0f0; border-radius:3px; padding:1px 5px; }
.t3-body { padding:5px 9px 6px 9px; }
.t3-row { display:flex; align-items:center; gap:4px; padding:3px 0; border-bottom:1px solid #f5f5f5; font-size:0.8em; }
.t3-row:last-child { border-bottom:none; }
.t3-medal { font-size:0.9em; flex-shrink:0; }
.t3-name { flex:1; color:#2c3e50; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:0.95em; }
.t3-ticker { font-size:0.78em; color:#2980b9; text-decoration:none; white-space:nowrap; flex-shrink:0; }
.t3-ticker:hover { text-decoration:underline; }
.t3-empty { font-size:0.78em; color:#aaa; }

/* ── Top3 Leadership 카드 + 도넛 ── */
.leadership-card { background:#fff; border-radius:10px; padding:10px 12px 12px 12px; box-shadow:0 1px 4px rgba(0,0,0,0.10); border:1px solid #f0e6da; display:flex; flex-direction:column; gap:6px; align-self:flex-start; width:fit-content; min-width:320px; }
.leadership-card-title { display:flex; align-items:baseline; justify-content:space-between; gap:8px; border-bottom:1px solid #f3e7d6; padding-bottom:4px; }
.leadership-card-title-main { font-size:13px; font-weight:700; color:#2c3e50; letter-spacing:0.04em; }
.lc-sub { font-size:10.5px; color:#95a5a6; font-weight:500; }
.leadership-body { display:flex; gap:18px; align-items:flex-start; flex-wrap:wrap; justify-content:flex-start; }
.lc-flow-section { flex:0 1 auto; max-width:360px; min-width:240px; display:flex; flex-direction:column; gap:6px; }
.lc-section-title { font-size:11.5px; font-weight:700; color:#5a4630; }
.money-flow-table { width:auto; border-collapse:collapse; font-size:12px; }
.money-flow-table td { padding:2.5px 10px 2.5px 4px; border-bottom:1px solid #f6f1ea; line-height:1.3; }
.money-flow-table td:last-child { padding-right:4px; }
.money-flow-table tr:last-child td { border-bottom:none; }
.money-flow-table td.lc-cat { text-align:left; color:#2c3e50; white-space:nowrap; }
.money-flow-table td.lc-delta { text-align:right; font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap; }
.money-flow-table td.lc-detail { text-align:right; color:#95a5a6; font-size:10.5px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.money-flow-table td.lc-arrow { text-align:center; width:18px; }
.money-flow-table tr.flow-strong td { background:#fff3f0; }
.money-flow-table tr.flow-strong td.lc-cat { color:#c0392b; font-weight:700; }
.money-flow-table tr.flow-strong td.lc-delta { color:#c0392b; }
.money-flow-table tr.flow-noise td { color:#b5b5b5; font-size:10.5px; }
.leadership-insight { background:#fff8ee; border:1px solid #f5d9a8; border-radius:5px; padding:5px 8px; font-size:11.5px; color:#5a4630; display:flex; gap:6px; align-items:flex-start; line-height:1.4; }
.lc-insight-tag { font-weight:700; color:#b9772b; white-space:nowrap; font-size:11px; }
.lc-insight-text { color:#5a4630; }
.doughnut-row { display:flex; gap:10px; flex:0 1 auto; justify-content:flex-start; }
.doughnut-wrap { flex:0 0 180px; max-width:200px; position:relative; }
.doughnut-label { text-align:center; font-size:10.5px; color:#7f8c8d; margin-bottom:2px; font-weight:600; }
.doughnut-canvas-wrap { position:relative; height:150px; }
.doughnut-center { position:absolute; top:calc(50% + 7px); left:50%; transform:translate(-50%,-50%); text-align:center; pointer-events:none; }
.dc-num { font-size:15px; font-weight:800; color:#2c3e50; line-height:1; }
.dc-num span { font-size:10px; color:#95a5a6; font-weight:500; }
.dc-lbl { font-size:9.5px; color:#7f8c8d; margin-top:1px; }
@media (max-width:780px) { .leadership-body { flex-direction:column; } .lc-flow-section { max-width:100%; } .doughnut-row { width:100%; justify-content:space-around; } }

/* ── AI Core Regime 박스 ── */
.ai-core-card { display:flex; gap:14px; background:linear-gradient(135deg,#fffbea,#fff5e1); border:1px solid #f0b400; padding:12px 14px; border-radius:10px; margin:6px 0 10px 0; box-shadow:0 2px 6px rgba(0,0,0,0.08); flex-wrap:wrap; width:fit-content; max-width:760px; align-self:flex-start; }
.ai-core-left { flex:0 0 180px; min-width:170px; }
.ai-core-right { flex:0 1 auto; min-width:220px; max-width:520px; }
.ai-top-title { font-size:0.82em; font-weight:bold; color:#2c3e50; margin-bottom:4px; }
.ai-top-list { display:grid; grid-template-columns:24px auto 1fr auto; align-items:baseline; column-gap:10px; row-gap:2px; width:max-content; max-width:100%; font-size:0.86em; }
.ai-top-row { display:contents; }
.ai-top-rank { font-weight:bold; color:#7f8c8d; text-align:left; white-space:nowrap; padding:1px 0; }
.ai-top-name { font-weight:700; color:#2c3e50; white-space:nowrap; padding:1px 0; }
.ai-top-score { grid-column:3/4; justify-self:end; font-weight:bold; color:#d35400; text-align:right; white-space:nowrap; padding:1px 0; padding-right:10px; min-width:3.5em; }
.ai-top-cnt { grid-column:4/5; justify-self:end; color:#888; font-size:0.82em; text-align:right; white-space:nowrap; padding:1px 0; min-width:1.5em; }
.ai-core-help { margin-top:8px; padding-top:6px; border-top:1px dashed #f1c40f; font-size:0.72em; color:#95a5a6; line-height:1.35; }
.ai-core-help b { color:#7f8c8d; font-weight:700; }
.ai-core-label { font-size:0.76em; color:#7f8c8d; margin-bottom:1px; }
.ai-core-score { font-size:2.1em; font-weight:800; line-height:1.05; margin-bottom:3px; }
.ai-core-state { display:inline-block; padding:2px 9px; border-radius:12px; color:#fff; font-weight:bold; font-size:0.82em; margin-bottom:5px; }
.ai-core-state-row { display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin-bottom:4px; }
.ai-breadth-state { font-size:0.78em; }
.ai-core-rdg { display:flex; gap:6px; margin:3px 0 4px 0; flex-wrap:wrap; }
.ai-rdg-cell { display:inline-flex; align-items:baseline; gap:3px; background:#fff; border:1px solid #f1c40f; border-radius:6px; padding:1px 7px; font-size:0.78em; line-height:1.2; }
.ai-rdg-lbl { color:#888; font-weight:600; }
.ai-rdg-val { color:#2c3e50; font-weight:700; }
.ai-core-dup { display:flex; align-items:center; gap:6px; flex-wrap:wrap; font-size:0.78em; margin-top:4px; }
.ai-dup-pill { display:inline-block; padding:1px 7px; border-radius:8px; color:#fff; font-weight:bold; font-size:0.92em; }
.ai-core-dup-meta { color:#888; }
.ai-core-dup-contrib { font-size:0.78em; color:#555; margin:2px 0 4px 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ai-core-breadth { font-size:0.82em; margin:3px 0; }
.ai-core-breadth span { display:inline-block; padding:1px 7px; margin-right:3px; border-radius:8px; font-weight:bold; }
.ai-b-strong { background:#d5f5e3; color:#1d8348; } .ai-b-mid { background:#fef9e7; color:#b7950b; }
.ai-b-weak { background:#ebebeb; color:#555; } .ai-b-neg { background:#fadbd8; color:#c0392b; }
.ai-core-meta { font-size:0.76em; color:#888; }

/* ── 차트 호버 팝업 ── */
#ordPopup { display:none; position:fixed; z-index:99999; background:#fff; border:1px solid #bdc3c7; border-radius:10px; padding:10px; box-shadow:0 10px 28px rgba(0,0,0,0.22); max-width:1000px; max-height:90dvh; overflow:auto; }
.ord-pop-head { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
#ordPopClose { background:#e74c3c; color:#fff; border:none; border-radius:50%; width:26px; height:26px; font-size:16px; line-height:1; cursor:pointer; }
.ord-pop-title { font-weight:700; color:#2c3e50; font-size:14px; }
.ord-pop-link { color:#2980b9; font-size:12px; text-decoration:none; }
.ord-pop-link:hover { text-decoration:underline; }
.ord-pop-imgs { display:flex; gap:10px; flex-wrap:wrap; }
.ord-pop-imgs img { width:480px; max-width:46vw; height:auto; background:#fff; border:1px solid #eee; border-radius:6px; }
@media (max-width:767px) { #ordPopup { left:2vw !important; width:96vw; top:50% !important; transform:translateY(-50%); } .ord-pop-imgs img { width:100%; max-width:100%; } }
"""

from asset_donut import DONUT_CSS as _DONUT_CSS   # noqa: E402  (CSS 는 위 CSS 정의 뒤에 붙여야 함)
CSS += _DONUT_CSS


POPUP_JS = r"""
(function(){
  var popup=document.getElementById('ordPopup');
  var title=document.getElementById('ordPopTitle');
  var link=document.getElementById('ordPopLink');
  var img1=document.getElementById('ordImg1'), img2=document.getElementById('ordImg2');
  var hoverTimer=null, closeTimer=null, pinned=false;
  var TS=Date.now();
  function urls(el){
    var tk=el.getAttribute('data-ticker');
    if(tk){
      return { title:tk, link:'https://finviz.com/quote.ashx?t='+tk,
        a:'https://charts2.finviz.com/chart.ashx?t='+tk+'&ty=c&ta=1&p=d&s=l&t='+TS,
        b:'https://charts2.finviz.com/chart.ashx?t='+tk+'&ty=c&ta=1&p=w&s=l&t='+TS };
    }
    var cd=el.getAttribute('data-code'); var nm=el.getAttribute('data-name')||cd;
    return { title:nm+' ('+cd+')', link:'https://finance.naver.com/item/main.naver?code='+cd,
      a:'https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'+cd+'.png?t='+TS,
      b:'https://ssl.pstatic.net/imgfinance/chart/item/candle/week/'+cd+'.png?t='+TS };
  }
  function load(el){ var u=urls(el); title.textContent=u.title; link.href=u.link; img1.src=u.a; img2.src=u.b; }
  function place(cx,cy){ if(window.innerWidth<=767)return; var w=Math.min(1000,window.innerWidth-20),h=430; var x=cx+18,y=cy+18; if(x+w>window.innerWidth-8)x=cx-w-12; if(y+h>window.innerHeight-8)y=cy-h-12; if(x<8)x=8; if(y<8)y=8; popup.style.left=x+'px'; popup.style.top=y+'px'; popup.style.transform='none'; }
  function open(){ popup.style.display='block'; }
  function close(){ popup.style.display='none'; pinned=false; }
  function schedClose(){ clearTimeout(closeTimer); closeTimer=setTimeout(function(){ if(!pinned)close(); },140); }
  document.getElementById('ordPopClose').addEventListener('click',close);
  popup.addEventListener('mouseenter',function(){ clearTimeout(closeTimer); pinned=true; });
  popup.addEventListener('mouseleave',function(){ pinned=false; schedClose(); });
  function attach(el){
    el.addEventListener('mouseenter',function(e){ if(window.innerWidth<=768)return; clearTimeout(closeTimer); clearTimeout(hoverTimer); hoverTimer=setTimeout(function(){ place(e.clientX,e.clientY); open(); load(el); },140); });
    el.addEventListener('mousemove',function(e){ if(window.innerWidth<=768)return; if(popup.style.display==='block'&&!pinned)place(e.clientX,e.clientY); });
    el.addEventListener('mouseleave',function(){ if(window.innerWidth<=768)return; clearTimeout(hoverTimer); schedClose(); });
    el.addEventListener('click',function(e){ e.stopPropagation(); clearTimeout(hoverTimer); place(e.clientX,e.clientY); open(); load(el); });
    el.style.cursor='pointer';
  }
  document.querySelectorAll('.chart-trigger[data-ticker], td[data-code]').forEach(attach);
  document.addEventListener('click',function(e){
    if(window.innerWidth<=767 && popup.style.display==='block'){ if(!popup.contains(e.target))close(); }
    else if(window.innerWidth>767){ if(!e.target.closest('#ordPopup') && !e.target.closest('.chart-trigger') && !e.target.closest('[data-code]'))close(); }
  });
})();
"""


DONUT_JS = r"""
if (typeof Chart !== 'undefined' && typeof ChartDataLabels !== 'undefined') { Chart.register(ChartDataLabels); }
(function() {
    const LEADERSHIP = %%LEADERSHIP%%;
    if (!LEADERSHIP) return;
    const CAT_COLORS = { 'KR':'#4a7ac7','US':'#e74c3c','Commodity':'#8e6e3a','Metals':'#f1c40f','Bonds':'#34495e','Crypto':'#9b59b6' };
    const CAT_LABELS_KO = { 'KR':'KR','US':'US','Commodity':'Comm','Metals':'Metals','Bonds':'Bonds','Crypto':'Crypto' };
    const CAT_ORDER = ['KR','US','Commodity','Metals','Bonds','Crypto'];
    function makeLeadershipDoughnut(canvasId, scores) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;
        const entries = CAT_ORDER.map(k => [k, (scores && scores[k]) || 0]).filter(e => e[1] > 0);
        if (entries.length === 0) return null;
        const labels = entries.map(e => CAT_LABELS_KO[e[0]]);
        const data = entries.map(e => e[1]);
        const colors = entries.map(e => CAT_COLORS[e[0]]);
        const total = data.reduce((a,b) => a+b, 0) || 1;
        const hasDataLabels = (typeof ChartDataLabels !== 'undefined');
        return new Chart(canvas.getContext('2d'), {
            type: 'doughnut',
            data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderWidth: 2, borderColor: '#fff' }] },
            options: { responsive: true, maintainAspectRatio: false, cutout: '52%', layout: { padding: 8 },
                plugins: {
                    legend: { display: false },
                    datalabels: { display: hasDataLabels, color: '#fff', textAlign: 'center', textStrokeColor: 'rgba(0,0,0,0.55)', textStrokeWidth: 3, font: { weight: 'bold', size: 11 }, anchor: 'center', align: 'center', clamp: true,
                        formatter: function(v, ctx) { const pct = (v / total) * 100; const label = ctx.chart.data.labels[ctx.dataIndex]; if (pct < 5) return label; return label + '\n' + pct.toFixed(0) + '%'; } },
                    tooltip: { callbacks: { label: function(c) { return c.label + ': ' + c.parsed + 'pt (' + (c.parsed/total*100).toFixed(1) + '%)'; } } }
                }
            }
        });
    }
    makeLeadershipDoughnut('leadershipTodayChart', LEADERSHIP.scores_today);
    makeLeadershipDoughnut('leadershipPrevChart',  LEADERSHIP.scores_prev);
})();
"""


PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>주문 게시판</title>
<style>%%CSS%%</style>
</head>
<body>

<div class="top-nav-container"><div class="top-nav">
    <a href="main_hub.html" class="nav-item">상황판</a>
    <a href="order.html" class="nav-item active">주문</a>
    <a href="summary.html" class="nav-item">요약</a>
    <a href="danta_chart.html" class="nav-item">단타</a>
    <a href="kr_chart.html" class="nav-item">차트</a>
    <a href="us_summary.html" class="nav-item">미국요약</a>
</div></div>

<div class="update-bar">📡 업데이트: %%NOW%%　(주문용 조각 통합)</div>

%%CONTENT%%

<div id="ordPopup">
  <div class="ord-pop-head">
    <button id="ordPopClose" title="닫기">&#215;</button>
    <span class="ord-pop-title" id="ordPopTitle">-</span>
    <a class="ord-pop-link" id="ordPopLink" href="#" target="_blank" rel="noopener noreferrer">차트 열기</a>
  </div>
  <div class="ord-pop-imgs">
    <img id="ordImg1" alt="일봉"><img id="ordImg2" alt="주봉">
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0"></script>
<script>%%DONUT%%</script>
<script>%%POPUP%%</script>

</body>
</html>
"""


def main():
    content = build_content()
    page = (PAGE
            .replace("%%CSS%%", CSS)
            .replace("%%NOW%%", now)
            .replace("%%CONTENT%%", content)
            .replace("%%DONUT%%", "")
            .replace("%%POPUP%%", ""))
    us_tickers = sorted(set(re.findall(r'data-ticker="([^"]+)"', page)))
    kr_codes = sorted(set(re.findall(r'data-code="([^"]+)"', page)))
    page = re.sub(
        r'data-ticker="([^"]+)"',
        r'data-ticker="\1" data-v4-code="\1" data-v4-market="US"',
        page,
    )
    page = re.sub(
        r'data-code="([^"]+)"',
        r'data-code="\1" data-v4-code="\1" data-v4-market="KR"',
        page,
    )
    from chart_popup_v4 import build_chart_popup
    market_map = {t.upper(): "US" for t in us_tickers}
    market_map.update({c.zfill(6): "KR" for c in kr_codes})
    v4_block = build_chart_popup(
        list(market_map),
        market_map=market_map,
        trigger_attr="data-v4-code",
        include_kospi=True,
    )
    page = page.replace("</body>", v4_block + "\n</body>")
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] order.html 생성 완료: {OUT_HTML}")


if __name__ == "__main__":
    main()
