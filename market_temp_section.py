# -*- coding: utf-8 -*-
"""
시장 온도 섹션 — 게시판 공용 모듈.

원래 make_index_kr_150.py 안에만 있던 build_market_temp_section() 을 떼어내
어느 게시판에서든 쓸 수 있게 만든 것. 기존 박스(판정 뱃지 + 게이지 + EMA + 스파크라인)에
"최근 N일 막대바(최신이 맨 위)"를 추가했다.

사용법
------
    from market_temp_section import build_market_temp_block, load_market_temp

    mt = load_market_temp()                       # report_kr_150.json 에서 읽기
    html_block = build_market_temp_block(mt)      # 기본 30일 막대바

이미 report_kr_150.json 을 읽고 있는 생성기라면 그 dict 를 그대로 넘겨도 된다:
    html_block = build_market_temp_block(data.get('market_temp'))

데이터 원천
-----------
    korea/chu_korea_final.py
      → report-us/rank_history_kr150/market_temp_history.csv   (전체 히스토리)
      → report-us/report_kr_150.json 의 'market_temp' 블록      (최근 60일 + 오늘)

점수 계산 (참고)
---------------
    종목별 sco = sco99(14개 항목 합, -16~+16) 의 4일 이동평균
    H: sco>=11(+2) / W: 8~11(+1) / N: 0~8(0) / C: sco<0(-2)
    MT = 50 + 25 * (2H + W - 2C) / T            → 0~100
    ※ 2026-08-23 N 가중치를 -1 → 0 으로 변경(약한 양수를 감점에서 중립으로).
      이전 공식으로 쌓인 히스토리는 같은 날 전 구간 재계산했다.
"""
import html
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPORT_KR_150_JSON = BASE / "report_kr_150.json"
MARKET_TEMP_CSV = BASE / "rank_history_kr150" / "market_temp_history.csv"

DEFAULT_BAR_DAYS = 30

STATUS_COLORS = {
    '상승 중':   ('#27ae60', '#eafaf1'),
    '회복 중':   ('#2980b9', '#eaf4fb'),
    '중립':      ('#7f8c8d', '#f2f3f4'),
    '하락 중':   ('#e67e22', '#fef9e7'),
    '침체 심화': ('#e74c3c', '#fdedec'),
}


def temp_color(mt):
    """온도 → 색상 (게이지/막대 공용)."""
    if mt >= 55:
        return '#27ae60'
    if mt >= 45:
        return '#f39c12'
    if mt >= 35:
        return '#e67e22'
    return '#e74c3c'


def load_market_temp(json_path=None):
    """report_kr_150.json 의 market_temp 블록을 읽어 반환. 없으면 None."""
    path = Path(json_path) if json_path else REPORT_KR_150_JSON
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("market_temp")
    except Exception:
        return None


def load_history_csv(limit=None):
    """market_temp_history.csv 를 [{date, MT, H, W, N, C, total}, ...] 로 읽는다.
    report_kr_150.json 의 history 는 60일로 잘려 있어서, 그보다 길게 필요할 때 사용."""
    if not MARKET_TEMP_CSV.exists():
        return []
    import csv as _csv
    rows = []
    with MARKET_TEMP_CSV.open("r", encoding="utf-8", newline="") as fh:
        for r in _csv.DictReader(fh):
            try:
                rows.append({
                    "date": str(r["date"]).strip(),
                    "MT": float(r["MT"]),
                    "H": int(float(r["H"])), "W": int(float(r["W"])),
                    "N": int(float(r["N"])), "C": int(float(r["C"])),
                    "total": int(float(r["total"])),
                })
            except (KeyError, ValueError, TypeError):
                continue
    rows.sort(key=lambda x: x["date"])
    return rows[-limit:] if limit else rows


def build_bar_table(history, days=DEFAULT_BAR_DAYS, max_height=None):
    """최근 N일 막대바. 최신 날짜가 맨 위(역순).
    max_height 를 주면 그 높이에서 내부 스크롤(예: '320px'), None 이면 전부 펼친다."""
    if not history:
        return ''

    recent = history[-days:]
    vals = [h['MT'] for h in recent]
    vmax = max(vals) or 1
    # 막대 길이는 0~100 이 아니라 '구간 최대값' 기준으로 잡아야 차이가 보인다
    scale_max = max(vmax, 10)

    newest = recent[-1]['date']
    peak_date = max(recent, key=lambda h: h['MT'])['date']
    low_date = min(recent, key=lambda h: h['MT'])['date']

    lines = []
    for h in reversed(recent):                      # ← 최신이 맨 위
        mt = h['MT']
        pct = max(1.0, mt / scale_max * 100)
        color = temp_color(mt)
        md = h['date'][5:].replace('-', '/')        # 2026-08-21 → 08/21

        tag = ''
        if h['date'] == newest:
            tag = '<span style="color:#3498db; font-weight:bold; font-size:0.9em;">현재</span>'
        elif h['date'] == peak_date:
            tag = '<span style="color:#27ae60; font-weight:bold; font-size:0.9em;">고점</span>'
        elif h['date'] == low_date:
            tag = '<span style="color:#e74c3c; font-weight:bold; font-size:0.9em;">저점</span>'

        row_bg = '#f8fbff' if h['date'] == newest else 'transparent'
        lines.append(f'''<tr style="background:{row_bg};">
  <td style="padding:1px 5px 1px 0; color:#7f8c8d; white-space:nowrap; font-variant-numeric:tabular-nums;">{md}</td>
  <td style="padding:1px 7px 1px 0; text-align:right; font-weight:bold; color:{color}; white-space:nowrap; font-variant-numeric:tabular-nums;">{mt:.1f}</td>
  <td style="padding:1px 0; width:100%;">
    <div style="background:{color}; width:{pct:.1f}%; height:8px; border-radius:2px; min-width:2px;"></div>
  </td>
  <td style="padding:1px 0 1px 5px; white-space:nowrap;">{tag}</td>
</tr>''')

    scroll_style = f'max-height:{max_height}; overflow-y:auto;' if max_height else ''
    return f'''<div style="min-width:0;">
  <div style="font-size:0.78em; color:#7f8c8d; margin-bottom:4px;">
    최근 {len(recent)}일 추이 <span style="color:#bbb;">(최신순 · 막대 최대 {scale_max:.0f} 기준)</span>
  </div>
  <div style="{scroll_style}">
    <table style="width:100%; border-collapse:collapse; font-size:0.75em; line-height:1.3;">
      {''.join(lines)}
    </table>
  </div>
</div>'''


def build_market_temp_block(mt_data, bar_days=DEFAULT_BAR_DAYS, show_bars=True,
                            max_width='600px', bar_max_height=None):
    """
    시장 온도 박스 HTML.
      mt_data       : report_kr_150.json 의 'market_temp' dict
      bar_days      : 막대바 일수 (기본 30)
      show_bars     : False 면 기존 박스만 (막대바 없음)
      max_width     : 박스 최대폭. 컬럼을 꽉 채우려면 '100%'
      bar_max_height: 막대바 내부 스크롤 높이. None 이면 전부 펼침
    """
    if not mt_data:
        return '<p style="color:#95a5a6; font-size:0.85em;">(시장 온도 데이터 없음)</p>'

    today = mt_data.get('today', 50)
    ema5 = mt_data.get('ema5', 50)
    ema20 = mt_data.get('ema20', 50)
    status = mt_data.get('status', '-')
    dist = mt_data.get('distribution', {}) or {}
    history = mt_data.get('history', []) or []

    H = dist.get('H', 0)
    W = dist.get('W', 0)
    N = dist.get('N', 0)
    C = dist.get('C', 0)
    T = dist.get('total', 1) or 1

    s_color, s_bg = STATUS_COLORS.get(status, ('#7f8c8d', '#f2f3f4'))
    gauge_color = temp_color(today)
    gauge_pct = round(today, 1)

    # ── 스파크라인 SVG (JSON history = 최근 60일) ──
    sparkline_svg = ''
    if len(history) >= 2:
        sw, sh = 260, 60
        mt_vals = [h['MT'] for h in history]
        ema5_vals = [h['ema5'] for h in history]
        ema20_vals = [h['ema20'] for h in history]

        all_vals = mt_vals + ema5_vals + ema20_vals
        vmin, vmax = min(all_vals), max(all_vals)
        vrange = (vmax - vmin) or 1
        n = len(history)

        def to_x(i):
            return round(sw * i / (n - 1), 1)

        def to_y(v):
            return round(sh - (v - vmin) / vrange * (sh - 6) - 3, 1)

        def make_path(vals, stroke):
            pts = ' '.join(f'{to_x(i)},{to_y(v)}' for i, v in enumerate(vals))
            return (f'<polyline stroke="{stroke}" points="{pts}" fill="none" '
                    f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>')

        y50 = to_y(50) if vmin <= 50 <= vmax else -1
        center_line = (f'<line x1="0" y1="{y50}" x2="{sw}" y2="{y50}" stroke="#bdc3c7" '
                       f'stroke-width="0.8" stroke-dasharray="3,3"/>') if y50 >= 0 else ''

        sparkline_svg = f'''<svg width="{sw}" height="{sh}" viewBox="0 0 {sw} {sh}" style="display:block; max-width:100%;">
  {center_line}
  {make_path(ema20_vals, '#e74c3c')}
  {make_path(ema5_vals, '#27ae60')}
  {make_path(mt_vals, '#3498db')}
</svg>
<div style="font-size:10px; color:#999; margin-top:2px; display:flex; gap:10px; flex-wrap:wrap;">
  <span style="color:#3498db;">● MT</span>
  <span style="color:#27ae60;">● EMA5</span>
  <span style="color:#e74c3c;">● EMA20</span>
  <span style="color:#bdc3c7;">— 50선</span>
</div>'''

    # ── 막대바: JSON history(60일)로 충분하면 그걸 쓰고, 모자라면 CSV 로 보충 ──
    bars_html = ''
    if show_bars:
        src = history if len(history) >= bar_days else (load_history_csv() or history)
        bars_html = build_bar_table(src, bar_days, max_height=bar_max_height)

    return f'''<div style="
      background:white; border-radius:8px; padding:12px 16px;
      box-shadow:0 4px 6px rgba(0,0,0,0.1); margin-bottom:14px;
      max-width:{max_width};">

  <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px; flex-wrap:wrap;">
    <span style="font-weight:bold; color:#2c3e50; font-size:0.95em;">🌡 시장 온도</span>
    <span style="background:{s_bg}; color:{s_color}; font-weight:bold;
                 padding:2px 10px; border-radius:12px; font-size:0.85em;
                 border:1px solid {s_color};">{html.escape(str(status))}</span>
    <span style="font-size:1.3em; font-weight:bold; color:{gauge_color};">{today:.1f}</span>
    <span style="color:#aaa; font-size:0.8em;">/ 100</span>
  </div>

  <div style="background:#ecf0f1; border-radius:4px; height:8px; margin-bottom:10px; position:relative;">
    <div style="background:{gauge_color}; width:{gauge_pct}%; height:100%; border-radius:4px;"></div>
    <div style="position:absolute; left:35%; top:-3px; width:1px; height:14px; background:#bdc3c7;"></div>
    <div style="position:absolute; left:45%; top:-3px; width:1px; height:14px; background:#bdc3c7;"></div>
    <div style="position:absolute; left:55%; top:-3px; width:1px; height:14px; background:#bdc3c7;"></div>
  </div>

  <!-- 좌: EMA/분포 + 스파크라인 / 우: 최근 N일 막대바 (세로로 쌓으면 카드가 너무 길어져 옆 컬럼과 높이차가 생긴다) -->
  <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">
    <div style="flex:0 0 auto; min-width:0;">
      <div style="font-size:0.82em; color:#555; line-height:1.7;">
        <div>EMA5 <b style="color:#27ae60;">{ema5:.1f}</b>
             &nbsp; EMA20 <b style="color:#e74c3c;">{ema20:.1f}</b></div>
        <div style="color:#999; font-size:0.95em;">
          H:<b>{H}</b>({H / T * 100:.0f}%)
          W:<b>{W}</b>({W / T * 100:.0f}%)
          N:<b>{N}</b>({N / T * 100:.0f}%)
          C:<b>{C}</b>({C / T * 100:.0f}%)
        </div>
      </div>
      <div style="margin-top:6px;">
        {sparkline_svg if sparkline_svg else '<span style="font-size:0.8em;color:#aaa;">히스토리 누적 중...</span>'}
      </div>
    </div>
    <div style="flex:1 1 260px; min-width:240px;">
      {bars_html}
    </div>
  </div>
</div>'''


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    mt = load_market_temp()
    if not mt:
        print("market_temp 블록을 못 읽었습니다:", REPORT_KR_150_JSON)
        sys.exit(1)

    hist = load_history_csv()
    print(f"JSON history {len(mt.get('history', []))}일 / CSV history {len(hist)}일")
    print(f"today={mt.get('today')} status={mt.get('status')}")

    out = BASE / "_market_temp_preview.html"
    out.write_text(
        '<meta charset="utf-8"><body style="background:#eef2f5; padding:20px; '
        'font-family:-apple-system,BlinkMacSystemFont,\'Malgun Gothic\',sans-serif;">'
        + build_market_temp_block(mt) + '</body>',
        encoding="utf-8")
    print("미리보기 →", out)
