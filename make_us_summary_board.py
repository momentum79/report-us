# make_us_summary_board.py
# 미국요약 게시판 - 미ETF / 해선 / Finviz / 미Main 게시판의 핵심 테이블을 한 페이지로 요약
#   출력: report-us/us_summary.html
#   - 1줄: 미ETF 주문 목록 (그대로)
#   - 2줄: 해선 주문용 Top4 | Finviz 주문용 Top4 (그대로)
#   - 3줄: 미너비니 2차 진입 (1차 통과 → VCP 피벗 돌파) (그대로, us_stock.html과 동일 표)
#   - 4줄: Finviz US Sector Top10 | 미Main US Main Top10
#   - 5줄: (Finviz+미Main 합산) LIME / GREEN / MOM
#   티커 hover → finviz 차트 팝업
#
# 원본 게시판 생성기의 렌더러 함수를 그대로 import 해서 호출 → 표 모양 100% 동일.

import html
import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import make_index_us_etf    as etf_gen
import make_index_futures   as fut_gen
import make_index_us_finviz as fv_gen
import make_index_us_main   as um_gen
import make_index_us        as us_gen

OUT_HTML = BASE / "us_summary.html"
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

TOP_N = 10


CHG_UP_COLOR = "#16a34a"
CHG_DN_COLOR = "#e74c3c"

def _chg_span(val):
    """등락률(%) 색상 span: 상승=lime, 하락=빨간색, 소수점 2자리. 매칭 실패 시 None."""
    s = str(val).strip().replace("%", "").replace("+", "").replace(",", "")
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    if f > 0:
        color, sign = CHG_UP_COLOR, "+"
    elif f < 0:
        color, sign = CHG_DN_COLOR, ""
    else:
        color, sign = "#333", ""
    return f'<span style="color:{color};font-weight:600;">{sign}{f:.2f}%</span>'


# ── 공용: 미니 테이블 렌더러 (섹션 4·5 전용, styled-tableWide) ───────────────
def mini_table(headers, rows, chg_cols=None):
    if not rows:
        return '<p style="padding-left:6px; color:#999; font-size:12px;">없음</p>'
    chg_cols = chg_cols or set()
    out = ['<table class="styled-tableWide">']
    out.append('<thead><tr>' + ''.join(f'<th>{html.escape(h)}</th>' for h in headers) + '</tr></thead><tbody>')
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            c = '' if c is None else str(c)
            if i == 0:
                tk = c.replace('*', '').strip()
                cells.append(f'<td class="ticker-col chart-trigger" data-ticker="{html.escape(tk)}">{html.escape(c)}</td>')
            elif i in chg_cols:
                span = _chg_span(c)
                cells.append(f'<td>{span if span is not None else html.escape(c)}</td>')
            else:
                cells.append(f'<td>{html.escape(c)}</td>')
        out.append('<tr>' + ''.join(cells) + '</tr>')
    out.append('</tbody></table>')
    return '\n'.join(out)


def _read(p):
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


# ── 섹션 1: 미ETF 주문 목록 (그대로) ─────────────────────────────────────────
def build_etf_order():
    text = _read(etf_gen.REPORT_TXT)
    momentum_raw = etf_gen.extract_block(
        text, "=== US ETF Momentum Top ===",
        ["=== 최종 리스트", "이전 보유 종목", "==="]) or ""
    momentum_block = "\n".join(l for l in momentum_raw.splitlines() if "US ETF Momentum" not in l).strip()

    order_raw = etf_gen.extract_block(
        text, "=== 최종 리스트",
        ["[나스닥 단계적 비중]", "[Holdings 투자비중 배분]", "[ATR 트리거"]) or "(주문용 Top4 없음)"
    order_top4 = "\n".join(l for l in order_raw.splitlines() if "최종 리스트" not in l).strip()

    # idx_rel_map (지수대비)
    idx_rel_map = {}
    low_signal_file = etf_gen.BASE / "us_etf_low_signals.json"
    if low_signal_file.exists():
        try:
            import json
            low_data = json.loads(low_signal_file.read_text(encoding="utf-8"))
            for sig in low_data.get('signals', []):
                if sig.get('idx_rel') is not None:
                    idx_rel_map[sig.get('ticker', '')] = sig['idx_rel']
        except Exception:
            pass

    # ticker_meta (위치/RSI/추세색) - momentum 블록 기반
    ticker_meta = {}
    for mline in momentum_block.splitlines():
        mcols = re.split(r'\s{2,}', mline.strip())
        if len(mcols) < 15:
            mcols = mline.strip().split()
        if len(mcols) < 15:
            continue
        mtk = mcols[0].strip().replace("*", "")
        mpos = mcols[2].strip()
        mrsi = mcols[4].strip() if len(mcols) > 4 else "-"
        mtrend = mcols[12].upper() if len(mcols) > 12 else ""
        mstyle = ""
        if "LIME" in mtrend:
            mstyle = 'background-color:#2AF527; color:black; font-weight:bold;'
        elif "GREEN" in mtrend:
            mstyle = 'background-color:#8DCF8C; color:black; font-weight:bold;'
        elif "RED" in mtrend:
            mstyle = 'background-color:#e74c3c; color:white; font-weight:bold;'
        elif "PURPLE" in mtrend:
            mstyle = 'background-color:#9b59b6; color:white; font-weight:bold;'
        ticker_meta[mtk] = {'pos': mpos, 'rsi': mrsi, 'style': mstyle}

    # 타이틀 투자비중 합
    top4_total_pct = 0.0
    for l in order_top4.splitlines():
        if l.strip() and not l.startswith("Ticker"):
            toks = l.split()
            if len(toks) >= 5:
                try:
                    top4_total_pct += (float(toks[-1].replace(',', '')) / 10000) * 100
                except Exception:
                    pass
    _pct = f" ({top4_total_pct:.1f}%)" if top4_total_pct > 0 else ""
    title = (f'🎯 주문 목록{_pct} <span style="font-size:0.7em; color:#000; font-weight:normal;">'
             f'- $10,000불 기준</span>')

    table = etf_gen.text_to_html_table_top4(order_top4, ticker_meta, idx_rel_map)
    return f'<h2>{title}</h2>\n{table}'


# ── 섹션 2: 해선 주문용 Top4 (그대로) ────────────────────────────────────────
def build_futures_order():
    text = _read(fut_gen.REPORT_TXT)
    momentum_raw = fut_gen.extract_block(
        text, "=== 해외선물 / FX / 암호화폐 Momentum Top ===",
        ["=== 주문용 Top4", "==="]) or ""
    momentum_block = "\n".join(l for l in momentum_raw.splitlines() if "해외선물 / FX" not in l).strip()

    order_raw = fut_gen.extract_block(
        text, "=== 주문용 Top4 (오늘) ===", ["이전 Top4:", "==="]) or "(주문용 Top4 없음)"
    order_top4 = "\n".join(l for l in order_raw.splitlines() if "주문용 Top4" not in l).strip()

    ticker_meta = {}
    for mline in momentum_block.splitlines():
        mcols = re.split(r'\s{2,}', mline.strip())
        if len(mcols) < 15:
            mcols = mline.strip().split()
        if len(mcols) < 15:
            continue
        mtk = mcols[0].strip().replace("*", "")
        mpos = mcols[2].strip()
        mtrend = mcols[11].upper() if len(mcols) > 11 else ""
        mstyle = ""
        if "LIME" in mtrend:
            mstyle = 'background-color:#2AF527; color:black; font-weight:bold;'
        elif "GREEN" in mtrend:
            mstyle = 'background-color:#8DCF8C; color:black; font-weight:bold;'
        elif "RED" in mtrend:
            mstyle = 'background-color:#e74c3c; color:white; font-weight:bold;'
        elif "PURPLE" in mtrend:
            mstyle = 'background-color:#9b59b6; color:white; font-weight:bold;'
        ticker_meta[mtk] = {'pos': mpos, 'style': mstyle}

    table = fut_gen.text_to_html_table_top4(order_top4, ticker_meta)
    return f'<h2>🎯 해선 주문용 Top4 (오늘)</h2>\n{table}'


# ── 섹션 3: Finviz 주문용 Top4 (그대로) ──────────────────────────────────────
def build_finviz_order():
    text = _read(fv_gen.REPORT_TXT)
    order_raw = fv_gen.extract_block(
        text,
        "=== ORDER A max10",
        ["=== 주문용", "==="],
    )
    rows = fv_gen.parse_pipe_block_order(order_raw)
    table = fv_gen.rows_to_html_table_order(rows, table_id="summary-finviz-order-a")
    return f'<h2>🧾 Finviz 주문용 A급 max10 (동일비중)</h2>\n{table}'


def build_us_main_order():
    text = _read(um_gen.REPORT_TXT)
    order_raw = um_gen.extract_block(
        text,
        "=== ORDER A max10",
        ["【US Main Top30", "==="],
    )
    rows = um_gen.parse_pipe_block_order(order_raw)
    table = um_gen.rows_to_html_table_order(rows, table_id="summary-usmain-order-a")
    return f'<h2>🧾 미Main 주문용 A급 max10 (동일비중)</h2>\n{table}'


# ── 파서 (섹션 4·5 용) ──────────────────────────────────────────────────────
def _to_float(value):
    s = str(value or "").replace("$", "").replace("%", "").replace(",", "").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _add_or_merge_candidate(items, ticker, source, **data):
    ticker = str(ticker or "").replace("*", "").strip().upper()
    if not ticker:
        return
    if ticker not in items:
        items[ticker] = {"ticker": ticker, "sources": [], **data}
    if source not in items[ticker]["sources"]:
        items[ticker]["sources"].append(source)
    for key, value in data.items():
        if items[ticker].get(key) in (None, "") and value not in (None, ""):
            items[ticker][key] = value


def _vcp_candidates():
    """실주문(buy_us_order_a_1887.py)과 동일하게 BREAKOUT_TODAY만 후보로 취급.
    PRE_BREAKOUT은 매수 대상이 아니라 피벗 감시 대상이므로 통합 주문표에서 제외."""
    path = us_gen.BASE / "us_minervini_stage2_final.csv"
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    return [r for r in rows if (r.get("status") or "").strip().upper() == "BREAKOUT_TODAY"]


def _collect_us_signal_items():
    """미Main/Finviz ORDER A max10 + VCP 후보를 티커 기준으로 병합한 신호 딕셔너리.
    (sco/3M/Final/Color/상태를 이미 계산해 둔 다른 게시판 산출물을 재사용)"""
    items = {}

    main_raw = um_gen.extract_block(
        _read(um_gen.REPORT_TXT),
        "=== ORDER A max10",
        ["\U0001f3c6S Main Top30", "==="],
    )
    for row in um_gen.parse_pipe_block_order(main_raw):
        if len(row) < 9:
            continue
        ticker, _weight, price, chg, sco, rtn, final, color, newsig = row[:9]
        _add_or_merge_candidate(
            items, ticker, "미Main",
            price=_to_float(price), chg=chg, sco=sco, rtn=rtn,
            final=final, color=color, status=newsig,
        )

    finviz_raw = fv_gen.extract_block(
        _read(fv_gen.REPORT_TXT),
        "=== ORDER A max10",
        ["==="],
    )
    for row in fv_gen.parse_pipe_block_order(finviz_raw):
        if len(row) < 10:
            continue
        ticker, _weight, industry, price, chg, sco, rtn, final, color, newsig = row[:10]
        _add_or_merge_candidate(
            items, ticker, "Finviz",
            industry=industry, price=_to_float(price), chg=chg, sco=sco,
            rtn=rtn, final=final, color=color, status=newsig,
        )

    for row in _vcp_candidates():
        _add_or_merge_candidate(
            items, row.get("ticker"), "VCP",
            price=_to_float(row.get("close_now")),
            chg=row.get("chg_pct", ""),
            rtn=row.get("R3M", ""),
            final=row.get("vcp_score", ""),
            color="",
            status=row.get("status", ""),
        )

    # 🆕 위 소스에 없는 종목(저장티커는 있으나 ORDER A/VCP엔 안 뜨는 경우) 보강용 전체 유니버스 스냅샷
    for snap_file, src_label in (
        (BASE / "us_finviz_all_signal_snapshot.json", "Finviz全"),
        (BASE / "us_main_all_signal_snapshot.json", "Main全"),
        (BASE / "us_etf_all_signal_snapshot.json", "ETF全"),
    ):
        try:
            snap = json.loads(snap_file.read_text("utf-8"))
            for tk, v in (snap.get("tickers") or {}).items():
                _add_or_merge_candidate(
                    items, tk, src_label,
                    sco=v.get("sco"), rtn=v.get("rtn"), final=v.get("final"),
                    color=v.get("color"), pos=v.get("pos"),
                )
        except (OSError, ValueError):
            pass

    # 🆕 국가 ETF(EWY 등) 보강용: world_rank.json은 필터 없이 전 국가 ETF를 매일 갱신
    try:
        world = json.loads((BASE / "world_rank.json").read_text("utf-8"))
        for row in world.get("data") or []:
            _add_or_merge_candidate(
                items, row.get("Ticker"), "World",
                sco=row.get("sco"), rtn=row.get("Return3M"), final=row.get("Score"),
                color=row.get("추세"), pos=row.get("정"),
            )
    except (OSError, ValueError):
        pass

    return items


def _us_top30_lookup():
    """미Main Top30(sco 기준) 블록에서 ticker -> {sco, rtn, final} 폭넓은 보조 조회표.
    (ORDER A max10 풀보다 넓은 커버리지, Color/상태는 없음)"""
    text = _read(um_gen.REPORT_TXT)
    raw = um_gen.extract_block(text, "【US Main Top30", [])
    out = {}
    for row in um_gen.parse_pipe_block_top30(raw):
        if not row or len(row) < 7:
            continue
        ticker, _price, _chg, sco, rtn, final, _newsig = row[:7]
        t = str(ticker or "").replace("*", "").strip().upper()
        if not t:
            continue
        out.setdefault(t, {"sco": sco, "rtn": rtn, "final": final})
    return out


# ── Pine Screener TR 주문셋(us_pine_buy_1887.py / us_pine_lowbuy_1887.py) 예상표 ──
TR_BUY_PLAN_JSON = BASE / "us_pine_buy_plan.json"
TR_LOWBUY_PLAN_JSON = BASE / "us_pine_lowbuy_plan.json"


def _load_tr_plan(path, source_label):
    """반환: (budget, rows) - 파일 없거나 손상 시 (None, [])."""
    if not path.exists():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    budget = data.get("budget") or 0.0
    rows = [{**r, "source": r.get("tag") or source_label} for r in (data.get("rows") or [])]
    return budget, rows


def build_us_tr_order():
    """0000_us_buy.bat(추세 매수+고점 매도, 저2/MA돌파 매수까지 순차 실행) 이 남긴 스냅샷 → 주문 예상표."""
    buy_budget, buy_rows = _load_tr_plan(TR_BUY_PLAN_JSON, "매수")
    low_budget, low_rows = _load_tr_plan(TR_LOWBUY_PLAN_JSON, "저점")

    if buy_budget is None and low_budget is None:
        return ('<h2>🎯 미국주식 TR 통합 주문 예상표</h2>\n'
                '<p style="padding-left:6px; color:#999; font-size:12px;">'
                '아직 실행 결과 없음 (0000_us_buy.bat 실행 필요)</p>')

    budget = (buy_budget or 0.0) + (low_budget or 0.0)
    candidates = buy_rows + low_rows

    signal_items = _collect_us_signal_items()
    top30_lookup = _us_top30_lookup()

    rows = []
    for c in candidates:
        ticker = str(c.get("ticker", "-")).strip().upper()
        sig = signal_items.get(ticker) or {}
        fallback = top30_lookup.get(ticker) or {}
        price = c.get("price")
        flu_rt = c.get("flu_rt")
        rows.append([
            ticker or "-",
            c.get("source", "-"),
            f"{price:.2f}" if price else "-",
            f"{flu_rt:.2f}" if flu_rt is not None else "-",
            sig.get("sco") or fallback.get("sco") or "-",
            sig.get("rtn") or fallback.get("rtn") or "-",
            sig.get("final") or fallback.get("final") or "-",
            sig.get("color") or "-",
            sig.get("status") or "-",
            sig.get("pos") or "-",
        ])

    title = f"🎯 미국주식 TR 통합 주문 예상표 - {len(candidates)}종목, ${budget:,.0f} 기준"
    headers = ["Ticker", "구분", "Price($)", "등락률(%)", "sco", "3M(%)", "Final", "Color", "상태", "위치"]
    table = mini_table(headers, rows, chg_cols={3})
    return f'<div class="us-tr-order"><h2>{title}</h2>\n{table}</div>'


# ── TR 스크리너 CSV(us_buy.csv)의 주봉 신호(주M) 1=매집 / 2=vol빵 ──────────────
TR_US_CSV = Path(r"D:\py\0order\tr\us_buy.csv")
JUM_LABEL = {"1": "매집", "2": "vol빵"}


def build_us_tr_weekly():
    title = "🎯 미국주식 TR 주봉 - 매집(1), vol빵(2)"
    try:
        with TR_US_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            src = list(csv.DictReader(f))
    except OSError:
        return (f'<h2>{title}</h2>\n<p style="padding-left:6px; color:#999; font-size:12px;">'
                f'{html.escape(TR_US_CSV.name)} 없음</p>')

    picked = []
    for r in src:
        code = (r.get("주M") or "").strip()
        if code not in JUM_LABEL:
            continue
        try:
            sco = float((r.get("sco") or "").strip())
        except ValueError:
            sco = -99.0
        picked.append((code, sco, r))
    picked.sort(key=lambda x: (x[0] != "2", -x[1]))

    rows = [[
        (r.get("심볼") or "-").strip(),
        JUM_LABEL[code],
        (r.get("가격") or "-").strip(),
        (r.get("등락률(%)") or "-").strip(),
        (r.get("sco") or "-").strip(),
        (r.get("3M(%)") or "-").strip(),
        (r.get("위치") or "-").strip(),
    ] for code, _sco, r in picked]

    headers = ["Ticker", "구분", "Price($)", "등락률(%)", "sco", "3M(%)", "위치"]
    table = mini_table(headers, rows, chg_cols={3})
    return f'<div class="us-tr-weekly"><h2>{title}</h2>\n{table}</div>'


def _finviz_space_rows(block, drop_header=True):
    rows = []
    for l in block.splitlines():
        s = l.strip()
        if not s or '【' in s or all(ch in '-=' for ch in s):
            continue
        cols = re.split(r'\s{2,}', s)
        if len(cols) < 2:
            cols = s.split()
        rows.append(cols)
    if drop_header and rows and 'Ticker' in rows[0][0]:
        rows = rows[1:]
    return rows


def _pipe_rows(block):
    rows = []
    for l in block.splitlines():
        s = l.strip()
        if not s or s.startswith('【') or s.startswith('-') or s.startswith('='):
            continue
        if 'Ticker' in s and ('sco' in s or 'Signal' in s):
            continue
        if '|' in s:
            rows.append([p.strip() for p in s.split('|')])
    return rows


def _pipe_to_tps(rows):
    """us_main pipe rows → [Ticker, Price($), 등락률(%), sco]
    파이프 구조: [0]ticker [1]signal [2]price [3]chg [4]date [5]sco [6]sco99"""
    out = []
    for p in rows:
        if len(p) < 6:
            continue
        ticker = p[0]
        price = p[2].replace('$', '').strip()
        chg = p[3].replace('%', '').strip()
        sco = p[5].replace('sco:', '').strip()
        try:
            sco = f"{float(sco):.1f}"
        except ValueError:
            pass
        out.append([ticker, price, chg, sco])
    return out


# ── 섹션 3: 미너비니 2차 진입 (1차 통과 → VCP 피벗 돌파) (그대로) ────────────
def build_minervini2():
    csv_path = us_gen.BASE / "us_minervini_stage2_final.csv"
    table = us_gen.minervini2_to_html(csv_path)
    return f'<h2>🎯 미국 VCP 매수 후보 (돌파/대기 분리)</h2>\n{table}'


# ── 섹션 4: 우량주 Top10 (Finviz | 미Main) ──────────────────────────────────
def build_top10_row():
    fv_text = _read(fv_gen.REPORT_TXT)
    fv_mom_raw = fv_gen.extract_block(
        fv_text, "=== US Stock Momentum Top ===",
        ["【MOM", "【LIME", "=== 주문용 Top4", "==="]) or ""
    fv_mom_block = "\n".join(l for l in fv_mom_raw.splitlines() if "US Stock Momentum Top" not in l).strip()
    fv_rows = _finviz_space_rows(fv_mom_block)[:TOP_N]
    fv_table = mini_table(["Ticker", "Industry", "Price($)", "등락률(%)", "Sig_sco", "3M(%)", "Final_sco", "NewSig"], fv_rows, chg_cols={3})

    um_text = _read(um_gen.REPORT_TXT)
    um_top30_raw = um_gen.extract_block(um_text, "【US Main Top30", [])
    um_rows = um_gen.parse_pipe_block_top30(um_top30_raw)
    um_rows = [r for r in um_rows if r][:TOP_N]
    um_table = um_gen.rows_to_html_table_top30(um_rows)

    # VCP Early stage (report_us.txt → US Momentum Top 블록)
    us_text = _read(us_gen.REPORT_TXT)
    vcp_raw = us_gen.extract_block(
        us_text, "=== US Momentum Top (VCP Early Stage) ===",
        ["=== 주문용 Top4", "==="]) or ""
    vcp_block = "\n".join(l for l in vcp_raw.splitlines() if "US Momentum Top" not in l).strip()
    vcp_rows = _finviz_space_rows(vcp_block)[:TOP_N]
    vcp_table = mini_table(
        ["Ticker", "Price($)", "등락률(%)", "Sig_sco", "수익(%)", "1M(%)", "Early", "Final", "New"], vcp_rows, chg_cols={2})

    return f"""<h2>🏆 우량주 Top10</h2>
<div class="cols-tight">
  <div class="col"><h3 class="signal-header">Finviz · US Sector 우량주 Top10</h3>{fv_table}</div>
  <div class="col"><h3 class="signal-header">미Main · US Main Top10</h3>{um_table}</div>
  <div class="col"><h3 class="signal-header">VCP Early stage Top10</h3>{vcp_table}</div>
</div>"""


# ── 섹션 5: 신호 종합 LIME / GREEN / MOM (Finviz + 미Main 합산) ──────────────
def build_signals_row():
    fv_text = _read(fv_gen.REPORT_TXT)
    um_text = _read(um_gen.REPORT_TXT)

    # Finviz 신호 블록 (4-col: Ticker Industry Sig_sco 3M%)
    fv_lime = _finviz_space_rows(fv_gen.extract_block(fv_text, "【LIME 신호 (매수)】", ["【GREEN", "=== 주문용 Top4"]))[:TOP_N]
    fv_green = _finviz_space_rows(fv_gen.extract_block(fv_text, "【GREEN 신호 (관심)】", ["【🔥 JUNG", "=== 주문용 Top4"]))[:TOP_N]
    fv_mom = _finviz_space_rows(fv_gen.extract_block(fv_text, "【MOM(모멘텀) 돌파】", ["【LIME", "【GREEN", "=== 주문용 Top4"]))[:TOP_N]

    # 미Main 신호 블록 (pipe → [Ticker, Price, sco])
    um_lime = _pipe_to_tps(_pipe_rows(um_gen.extract_block(um_text, "【LIME", ["【GREEN", "【RED"])))[:TOP_N]
    um_green = _pipe_to_tps(_pipe_rows(um_gen.extract_block(um_text, "【GREEN", ["【RED", "【US Main Top30"])))[:TOP_N]
    um_mom = _pipe_to_tps(_pipe_rows(um_gen.extract_block(um_text, "【MOM", ["【LIME", "【GREEN", "【RED"])))[:TOP_N]

    fv_hdr = ["Ticker", "Industry", "Price($)", "등락률(%)", "Sco", "3M(%)"]
    um_hdr = ["Ticker", "Price($)", "등락률(%)", "sco"]
    fv_chg = {3}
    um_chg = {2}

    def col(emoji, label, fv_rows, um_rows):
        fv_tbl = mini_table(fv_hdr, fv_rows, chg_cols=fv_chg)
        um_tbl = mini_table(um_hdr, um_rows, chg_cols=um_chg)
        return f"""  <div class="col">
    <h3 class="signal-header">{emoji} {label}</h3>
    <div class="src-cap">Finviz 섹터</div>{fv_tbl}
    <div class="src-cap">미Main 주식</div>{um_tbl}
  </div>"""

    return f"""<h2>📊 신호 종합 (LIME / GREEN / MOM)</h2>
<div class="cols-tight">
{col("🟢", "LIME", fv_lime, um_lime)}
{col("🌱", "GREEN", fv_green, um_green)}
{col("🚀", "MOM", fv_mom, um_mom)}
</div>"""


def _safe(fn):
    """섹션 렌더러 1개 실행 (실패해도 다른 섹션은 살림)"""
    try:
        return fn()
    except Exception as e:
        return f'<p style="color:#c0392b;">[{fn.__name__} 오류] {html.escape(str(e))}</p>'


def build_content():
    parts = []
    parts.append(f'<div class="section">{_safe(build_minervini2)}</div>')
    parts.append(f'<div class="section">{_safe(build_top10_row)}</div>')
    parts.append(
        '<div class="section"><div class="cols-tight">'
        f'<div>{_safe(build_us_tr_order)}</div>'
        f'<div>{_safe(build_us_tr_weekly)}</div>'
        '</div></div>'
    )
    parts.append(f'<div class="section">{_safe(build_signals_row)}</div>')
    return "\n".join(parts)


PAGE_TMPL = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>미국요약 게시판</title>
<style>
body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 14px; margin:0; background-color: #f4f7f6; color:#2c3e50; line-height:1.4; }}
.top-nav-container {{ display: flex; margin-bottom: 10px; }}
.top-nav {{ display: flex; background: #2c3e50; border-radius: 8px; overflow: hidden; }}
.nav-item {{ padding: 7px 14px; color: #bdc3c7; cursor: pointer; text-decoration:none; font-size: 0.85em; font-weight: bold; transition:0.2s; }}
.nav-item:hover {{ background: #34495e; color: #fff; }}
.nav-item.active {{ background: #3498db; color: white; }}
.update-bar {{ font-size: 0.82em; color: #888; margin-bottom: 8px; }}
.section {{ margin-bottom: 8px; }}
h2 {{ margin-top: 18px; margin-bottom: 8px; padding-bottom: 5px; color: #2c3e50; border-bottom: 2px solid #e67e22; font-size: 1.25em; }}
.signal-header {{ margin: 8px 0 4px 0; padding-bottom: 3px; color: #2c3e50; font-size: 1.0em; border-bottom: 1px solid #e67e22; }}
.src-cap {{ font-size: 11px; color: #999; font-weight:bold; margin-top:6px; }}
.cols {{ display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-start; }}
.cols .styled-tableWide {{ margin: 3px 0 4px 0; }}
.cols .src-cap {{ margin-top: 2px; }}
.cols p {{ margin: 2px 0; }}
.col {{ flex: 1 1 280px; min-width: 280px; }}
/* 내용 너비에 맞춰 붙여서 배치 (늘어나지 않음) - 우량주 Top10·주문용 Top4 한 줄용 */
.cols-tight {{ display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }}
.cols-tight > .col, .cols-tight > div {{ flex: 0 1 auto; min-width: 0; }}
.us-tr-order h2, .us-tr-weekly h2 {{ margin-top: 18px; font-size: 1.35em; }}
.us-tr-order .styled-table {{ font-size: 15px; }}
.us-tr-order .styled-table th, .us-tr-order .styled-table td {{ padding: 7px 12px; }}

.styled-table {{ width: auto; border-collapse: collapse; margin: 8px 0 14px 0; font-size: 13px; background: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }}
.styled-table thead tr {{ background: linear-gradient(135deg, #e67e22, #d35400); color: #fff; text-align: center; }}
.styled-table th, .styled-table td {{ padding: 6px 14px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; text-align: center; }}
.styled-table td:nth-child(1) {{ text-align: left; font-weight: bold; color: #2980b9; }}

.styled-tableWide {{ width: auto; max-width:100%; border-collapse: collapse; margin: 5px 0 12px 0; font-size: 12px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 6px; overflow: hidden; }}
.styled-tableWide thead tr {{ background-color: #e67e22; color: #fff; text-align: left; }}
.styled-tableWide th, .styled-tableWide td {{ padding: 4px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
.styled-tableWide td.ticker-col {{ width: 70px; font-weight: 600; }}
.styled-tableWide tbody tr:nth-of-type(even) {{ background-color: #fdf8f4; }}
.styled-tableWide tbody tr:last-of-type {{ border-bottom: 2px solid #e67e22; }}

.sig-up {{ color: #27ae60; font-weight: 600; }}
.sig-down {{ color: #e74c3c; font-weight: 600; }}
.pos-badge {{ display:inline-block; width:22px; height:22px; line-height:22px; border-radius:50%; font-size:0.75rem; font-weight:bold; color:white; text-align:center; }}
.pos-1 {{ background-color:#16a34a !important; }} .pos-2 {{ background-color:#65a30d !important; }}
.pos-3 {{ background-color:#d97706 !important; }} .pos-4 {{ background-color:#ea580c !important; }}
.pos-5 {{ background-color:#dc2626 !important; }}
.trend-badge {{ display:inline-block; padding:2px 6px; border-radius:4px; font-size:0.85em; font-weight:700; }}
.trend-lime {{ background:#2AF527; color:black; }} .trend-green {{ background:#8DCF8C; color:black; }}
.trend-red {{ background:#e74c3c; color:white; }} .trend-purple {{ background:#9b59b6; color:white; }}
.sig-badge {{ display:inline-block; padding:1px 6px; border-radius:4px; font-size:11px; font-weight:600; white-space:nowrap; }}
.sig-lime {{ background:#c8f77a; color:#2a5000; }} .sig-green {{ background:#b6eac4; color:#1a4a28; }}
.sig-mom {{ background:#c9a8f7; color:#3a006f; }} .sig-red {{ background:#f7b8b8; color:#7a0000; }}
.ticker-col {{ cursor:pointer; text-decoration:underline dotted; }}
.ticker-col:hover {{ background:#e8f4f8; }}
.chart-trigger {{ cursor:pointer; }}
.pc-only {{}}
@media (max-width: 700px) {{ .pc-only {{ display:none !important; }} }}

/* ── 미국 차트 팝업 (finviz) ── */
#usChartPopup {{ display:none; position:fixed; z-index:99999; width:1244px; box-sizing:border-box; background:#fff; border:1px solid #bdc3c7; border-radius:10px; padding:12px; box-shadow:0 10px 28px rgba(0,0,0,0.22); overflow-y:auto; max-height:90dvh; }}
body.us-popup-open {{ overflow:hidden; }}
#usPopupClose {{ display:flex; background:#e74c3c; color:#fff; border:none; border-radius:50%; width:28px; height:28px; font-size:18px; line-height:1; cursor:pointer; align-items:center; justify-content:center; font-weight:bold; }}
.popup-header {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }}
.popup-title {{ font-weight:700; color:#2c3e50; font-size:14px; }}
.popup-link {{ font-size:12px; color:#2980b9; text-decoration:none; margin-left:1em; }}
.popup-link:hover {{ text-decoration:underline; }}
.charts-grid {{ display:grid; grid-template-columns:repeat(2, max-content); gap:12px; }}
.chart-card {{ border:1px solid #e5e7eb; border-radius:8px; overflow:hidden; background:#fafafa; }}
.chart-wrap {{ position:relative; width:601px; height:345px; background:white; }}
.chart-wrap img {{ width:100%; height:100%; display:block; object-fit:fill; background:white; }}
.chart-loading {{ display:none; position:absolute; inset:0; background:rgba(255,255,255,0.75); align-items:center; justify-content:center; font-size:12px; color:#64748b; }}
.chart-loading.show {{ display:flex; }}
@media (max-width: 767px) {{ #usChartPopup {{ position:fixed !important; left:2vw !important; top:50% !important; transform:translateY(-50%); width:96vw !important; max-height:80dvh !important; padding:8px !important; box-sizing:border-box; }} .charts-grid {{ grid-template-columns:1fr; gap:6px; }} .chart-wrap {{ width:100%; height:auto; min-height:0; }} .chart-wrap img {{ width:100%; height:auto; }} }}
@media (min-width: 768px) and (max-width: 1000px) {{ #usChartPopup {{ width:min(96vw,1244px); left:2vw !important; }} .charts-grid {{ grid-template-columns:1fr; }} .chart-wrap {{ width:100%; height:auto; min-height:0; }} .chart-wrap img {{ width:100%; height:auto; }} }}
</style>
</head>
<body>

<div class="top-nav-container"><div class="top-nav">
    <a href="main_hub.html" class="nav-item">상황판</a>
    <a href="order.html" class="nav-item">주문</a>
    <a href="summary.html" class="nav-item">요약</a>
    <a href="danta_chart.html" class="nav-item">단타</a>
    <a href="kr_chart.html" class="nav-item">차트</a>
    <a href="us_summary.html" class="nav-item active">미국요약</a>
</div></div>

<div class="update-bar">📡 업데이트: {now}　(미ETF · 해선 · Finviz · 미Main 요약)</div>

{content}

<div id="usChartPopup" tabindex="-1">
  <div class="popup-header">
    <button id="usPopupClose" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">finviz 열기</a>
    <a id="popupLinkTV" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">TradingView</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><div class="chart-wrap"><img id="imgDaily" alt="일봉"><div class="chart-loading" id="loadingDaily">불러오는 중...</div></div></div>
    <div class="chart-card"><div class="chart-wrap"><img id="imgWeekly" alt="주봉"><div class="chart-loading" id="loadingWeekly">불러오는 중...</div></div></div>
  </div>
</div>
<script>
(function () {{ return;
  var popup = document.getElementById('usChartPopup');
  var popupTitle = document.getElementById('popupTitle');
  var popupLink = document.getElementById('popupLink');
  var popupLinkTV = document.getElementById('popupLinkTV');
  var imgDaily = document.getElementById('imgDaily');
  var imgWeekly = document.getElementById('imgWeekly');
  var loadingDaily = document.getElementById('loadingDaily');
  var loadingWeekly = document.getElementById('loadingWeekly');
  var hoverTimer = null, closeTimer = null, pinned = false, curEl = null;
  var TS = Date.now();
  function withTs(u) {{ return u + '&t=' + TS; }}
  function dailyUrl(c)  {{ return withTs('https://charts2.finviz.com/chart.ashx?t=' + c + '&ty=c&ta=1&p=d&s=l'); }}
  function weeklyUrl(c) {{ return withTs('https://charts2.finviz.com/chart.ashx?t=' + c + '&ty=c&ta=1&p=w&s=l'); }}
  function loadInto(img, ld, url) {{
    ld.classList.add('show'); img.style.opacity = '0.35';
    var probe = new Image();
    probe.onload = function () {{ img.src = url; img.style.opacity = '1'; ld.classList.remove('show'); }};
    probe.onerror = function () {{ img.removeAttribute('src'); img.style.opacity = '1'; ld.classList.remove('show'); }};
    probe.src = url;
  }}
  function loadCharts(c) {{
    popupTitle.textContent = c;
    popupLink.href = 'https://finviz.com/quote.ashx?t=' + c;
    popupLinkTV.href = 'https://www.tradingview.com/symbols/' + c + '/';
    loadInto(imgDaily, loadingDaily, dailyUrl(c));
    loadInto(imgWeekly, loadingWeekly, weeklyUrl(c));
  }}
  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    var w = Math.min(1244, window.innerWidth - 20), h = window.innerWidth <= 1000 ? 600 : 410;
    var x = cx + 18, y = cy + 18;
    if (x + w > window.innerWidth - 8) x = cx - w - 12;
    if (y + h > window.innerHeight - 8) y = cy - h - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px'; popup.style.transform = 'none';
  }}
  function openPopup() {{
    popup.style.display = 'block';
    document.body.classList.add('us-popup-open');
    try {{
      if (document.activeElement === document.body || document.activeElement === null) {{
        popup.focus({{preventScroll:true}});
      }}
    }} catch (e) {{}}
  }}
  function closePopup() {{
    popup.style.display = 'none';
    pinned = false;
    document.body.classList.remove('us-popup-open');
    document.removeEventListener('mousemove', unpinOnMove);
  }}
  function cancelClose() {{ clearTimeout(closeTimer); closeTimer = null; }}
  function scheduleClose() {{
    cancelClose();
    closeTimer = setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
  }}
  function unpinOnMove(e) {{
    if (popup.contains(e.target)) return;
    document.removeEventListener('mousemove', unpinOnMove);
    pinned = false;
    scheduleClose();
  }}
  function kbPin() {{
    pinned = true;
    cancelClose();
    document.removeEventListener('mousemove', unpinOnMove);
    document.addEventListener('mousemove', unpinOnMove);
  }}
  document.getElementById('usPopupClose').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ cancelClose(); pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; scheduleClose(); }});
  function attach(el) {{
    var code = el.getAttribute('data-ticker');
    if (!code) return;
    el.addEventListener('mouseenter', function (e) {{ if (window.innerWidth <= 768) return; cancelClose(); clearTimeout(hoverTimer); hoverTimer = setTimeout(function () {{ placePopup(e.clientX, e.clientY); openPopup(); loadCharts(code); curEl = el; }}, 140); }});
    el.addEventListener('mousemove', function (e) {{ if (window.innerWidth <= 768) return; if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY); }});
    el.addEventListener('mouseleave', function () {{ if (window.innerWidth <= 768) return; clearTimeout(hoverTimer); scheduleClose(); }});
    el.addEventListener('click', function (e) {{ e.stopPropagation(); cancelClose(); clearTimeout(hoverTimer); placePopup(e.clientX, e.clientY); openPopup(); loadCharts(code); curEl = el; }});
  }}
  document.querySelectorAll('.chart-trigger[data-ticker]').forEach(attach);
  // 키보드(팝업 열렸을 때만): S/↑=이전, D/↓=다음, Tab/ESC=닫기
  /* === SWIPE-NAV-INJECTED: 모바일 좌/우 스와이프 → 키보드 D/S 재사용 (PC 무영향) === */
  (function(){{
    if(window.__swipeNavInit) return; window.__swipeNavInit=true;
    function isTouch(){{ return window.matchMedia('(hover: none)').matches || window.innerWidth<=767; }}
    var sx=0, sy=0, st=0, tr=false;
    document.addEventListener('touchstart', function(e){{
      if(!isTouch() || !e.touches || e.touches.length!==1){{ tr=false; return; }}
      var t=e.touches[0]; sx=t.clientX; sy=t.clientY; st=Date.now(); tr=true;
    }}, true);
    document.addEventListener('touchend', function(e){{
      if(!tr) return; tr=false;
      var t=e.changedTouches && e.changedTouches[0]; if(!t) return;
      var dx=t.clientX-sx, dy=t.clientY-sy, dt=Date.now()-st;
      if(dt>800 || Math.abs(dx)<55 || Math.abs(dx)<Math.abs(dy)*1.6) return;
      var key = dx<0 ? 'd' : 's';
      try{{ document.dispatchEvent(new KeyboardEvent('keydown', {{key:key, bubbles:true, cancelable:true}})); }}catch(err){{}}
    }}, true);
  }})();
  document.addEventListener('keydown', function (e) {{
    if (popup.style.display !== 'block') return;
    var target = e.target, tag = target && target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (target && target.isContentEditable)) return;
    var key = e.key;
    if (key === 'Tab' || key === 'Escape') {{
      e.preventDefault();
      closePopup();
      return;
    }}
    var dir = 0;
    if (key === 's' || key === 'S' || key === 'ArrowUp') dir = -1;
    if (key === 'd' || key === 'D' || key === 'ArrowDown') dir = 1;
    if (dir === 0 || !curEl) return;
    e.preventDefault();
    var all = Array.from(document.querySelectorAll('.chart-trigger[data-ticker]'));
    var i = all.indexOf(curEl);
    if (i < 0) return;
    i += dir;
    if (i < 0 || i >= all.length) return;
    var nextEl = all[i];
    var nextCode = nextEl.getAttribute('data-ticker');
    if (!nextCode) return;
    kbPin();
    loadCharts(nextCode);
    curEl = nextEl;
    nextEl.scrollIntoView({{block:'nearest'}});
  }});
  // 프리로드: 차트 트리거 티커를 위→아래 순서로 중복제거 후 순차 선행 로딩 (Finviz 차단 방지 위해 동시 3개 제한)
  (function () {{
    var seen = {{}}, queue = [];
    document.querySelectorAll('.chart-trigger[data-ticker]').forEach(function (el) {{
      var c = el.getAttribute('data-ticker');
      if (!c || seen[c]) return;
      seen[c] = true; queue.push(c);
    }});
    var idx = 0, CONCURRENCY = 3;
    function next() {{
      if (idx >= queue.length) return;
      var c = queue[idx++], done = 0;
      function step() {{ if (++done >= 2) next(); }}
      [dailyUrl(c), weeklyUrl(c)].forEach(function (u) {{
        var im = new Image();
        im.onload = step; im.onerror = step;
        im.src = u;
      }});
    }}
    setTimeout(function () {{
      for (var i = 0; i < CONCURRENCY && i < queue.length; i++) next();
    }}, 300);
  }})();
  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767 && popup.style.display === 'block') {{ if (!popup.contains(e.target)) closePopup(); }}
    else if (window.innerWidth > 767) {{ if (!e.target.closest('#usChartPopup') && !e.target.closest('.chart-trigger')) closePopup(); }}
  }});
}})();
</script>

</body>
</html>
"""


def main():
    content = build_content()
    page = PAGE_TMPL.format(now=now, content=content)
    import re as _re
    from chart_popup_v4 import build_chart_popup as _bcp_v4
    _tks = sorted(set(_re.findall(r'data-ticker="([^"]+)"', page)))
    page = page.replace(
        "</body>",
        _bcp_v4(_tks, market="US", trigger_attr="data-ticker") + "\n</body>",
        1,
    )
    OUT_HTML.write_text(page, encoding='utf-8')
    print(f"[OK] us_summary.html 생성 완료: {OUT_HTML} (V4 차트 {len(_tks)}종목)")


if __name__ == '__main__':
    main()



