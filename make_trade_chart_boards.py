# -*- coding: utf-8 -*-
"""
make_trade_chart_boards.py ── 자동일지차트 게시판(성과 tag별)용 차트 생성기
─────────────────────────────────────────────────────────────────────────────
주간성과(make_weekly_performance.py)의 성과 tag 를 그대로 게시판 단위로 쓴다.
tag 확정 규칙은 wp.resolve_performance_tag() 하나만 사용 → 주간성과 표와 차트가
같은 기준으로 갈린다. 같은 종목이라도 tag 가 다르면 포지션·평단이 섞이지 않는다.

원천 2종:
  · fill   = intraday_signals/*.json 체결 (주도주/로켓/수동매매/통합ETF/삼닉v3/5분HL/미국/…)
  · ledger = 0order/tr/ledger/tr_ledger_*.json 의 strategy_tag (KTR_* / UTR_*)

렌더는 기존과 동일 공식:
  · 5분봉 = "요약-단타 게시판"(make_danta_chart_display) PAGE_JS
  · 일봉  = auto_trade_20day_chart_8042.build_ticker_html (KR=pykrx/NXT, US=us_ohlcv_cache)
둘 다 B/S 마커 + 매도 위에 실현손익 금액·% (이익=검정, 손실=빨강) 표기.

출력: report-us/charts/board_<key>/<code>.html   (매 실행 시 폴더 비우고 재생성)
호출: make_index_trade_chart.main() 이 generate() 를 불러 option 목록을 받는다.
"""
import os
import re
import sys
import json
import glob
import shutil
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(BASE_DIR))   # D:\py

import make_weekly_performance as wp            # fill 로더 + 성과 tag 확정
from make_danta_chart_display import PAGE_JS as MIN5_JS, add_trend_states
from chart_popup_v2 import collect_5min, is_nxt
import auto_trade_20day_chart_8042 as d8042     # 일봉 엔진

RECENT_DAYS = 30        # 최근 30일 거래분만 게시판에 노출
NAME_LEN    = 6
DAYS5       = 5         # 5분봉 수집 일수
CHART_WIDTH = 1300      # 모든 게시판 공통 차트 폭(px)
DAILY_BARS  = 60        # 일봉 기본 보기 봉수

CHARTS_DIR = os.path.join(BASE_DIR, "charts")
LEDGER_DIR = os.path.join(os.path.dirname(BASE_DIR), "0order", "tr", "ledger")
LEDGER_FILES = {"KR": "tr_ledger_2773_KR.json", "US": "tr_ledger_1887_US.json"}

# ── 게시판 정의 = 헤더 노출 순서 ──────────────────────────────
#   tag    : 성과 tag (fill 보드는 wp.resolve_performance_tag 결과, ledger 보드는 strategy_tag)
#   kind   : "5min" | "daily"
#   ledger : 있으면 TR ledger 원천("KR"/"US"), 없으면 intraday fill 원천
#   market : 일봉 OHLCV 출처. 생략하면 종목코드로 자동판별(6자리 숫자=KR, 그 외=US)
#
# 색상 = 계열 구분(글자는 항상 흰색). 보유자산 게시판 투자비중 도넛의 기준색을 따른다.
#   KTR_* = 파랑(도넛 KR #4a7ac7) · UTR_* = 빨강(도넛 US #e74c3c) · 현금계열 회색(#bdc3c7)은
#   흰 글씨 대비가 모자라 한 단계 어둡게 잡았다. 계열 안에서는 명도만 달리해 서로 구분한다.
BOARDS = [
    # 녹색 — 일봉 스윙(주도주 계열)
    {"key": "leader",    "label": "주도주",      "color": "#15794A", "kind": "daily", "tag": "주도주"},
    {"key": "rocket",    "label": "로켓",        "color": "#1D8F58", "kind": "daily", "tag": "ROCKET"},
    {"key": "manual",    "label": "수동매매",    "color": "#2AA467", "kind": "daily", "tag": "수동매매"},
    {"key": "alletf",    "label": "통합ETF",     "color": "#3BB878", "kind": "daily", "tag": "통합ETF"},
    # 보라 — 5분봉 단타
    {"key": "v3_jeo2",   "label": "삼닉v3_저2",  "color": "#5B21B6", "kind": "5min",  "tag": "삼닉v3_저2"},
    {"key": "v3_trend",  "label": "삼닉v3_추세", "color": "#6A2ECB", "kind": "5min",  "tag": "삼닉v3_추세"},
    {"key": "v3_ma",     "label": "삼닉v3_MA",   "color": "#7C3AED", "kind": "5min",  "tag": "삼닉v3_MA"},
    {"key": "hl1",       "label": "5분HL",       "color": "#8B4CEE", "kind": "5min",  "tag": "5minHL"},
    {"key": "hl2",       "label": "5분HL2",      "color": "#985EEA", "kind": "5min",  "tag": "5minHL2"},
    {"key": "hl_etc",    "label": "5분기타",     "color": "#A471DE", "kind": "5min",  "tag": "5minHL_미분류"},
    # 회색 — 그 외
    {"key": "usvcp",     "label": "미VCP",       "color": "#5F6871", "kind": "daily", "tag": "미국VCP",     "market": "US"},
    {"key": "us_manual", "label": "미국수동",    "color": "#6F7883", "kind": "daily", "tag": "미국수동",    "market": "US"},
    {"key": "dip",       "label": "저사다리",    "color": "#818A94", "kind": "5min",  "tag": "저점사다리"},
    {"key": "etc8042",   "label": "기타(8042)",  "color": "#939BA4", "kind": "5min",  "tag": "기타(8042)"},
    # 파랑 — 한국 TR (도넛 KR 계열)
    {"key": "ktr_ord_a", "label": "KTR_ORD_A",   "color": "#16337A", "kind": "daily", "tag": "KR_TR_ORD_A",    "ledger": "KR"},
    {"key": "ktr_vol1",  "label": "KTR_vol1",    "color": "#1C4192", "kind": "daily", "tag": "KR_TR_VOLUME_1", "ledger": "KR"},
    {"key": "ktr_vol2",  "label": "KTR_vol2",    "color": "#2450AB", "kind": "daily", "tag": "KR_TR_VOLUME_2", "ledger": "KR"},
    {"key": "ktr_vcp1",  "label": "KTR_VCP1",    "color": "#2D5FC0", "kind": "daily", "tag": "KR_TR_VCP1",     "ledger": "KR"},
    {"key": "ktr_base",  "label": "KTR_BASE",    "color": "#3A6FCF", "kind": "daily", "tag": "KR_TR_BASE",     "ledger": "KR"},
    {"key": "ktr_jeo2",  "label": "KTR_저2",     "color": "#4A7AC7", "kind": "daily", "tag": "KR_TR_JEO2",     "ledger": "KR"},
    {"key": "ktr_ma",    "label": "KTR_MA돌",    "color": "#5A89D4", "kind": "daily", "tag": "KR_TR_MA",       "ledger": "KR"},
    # 빨강 — 미국 TR (도넛 US 계열)
    {"key": "utr_ord_a", "label": "UTR_ORD_A",   "color": "#8F1A12", "kind": "daily", "tag": "US_TR_ORD_A",    "ledger": "US"},
    {"key": "utr_vcp1",  "label": "UTR_VCP1",    "color": "#AB271C", "kind": "daily", "tag": "US_TR_VCP1",     "ledger": "US"},
    {"key": "utr_base",  "label": "UTR_BASE",    "color": "#C63628", "kind": "daily", "tag": "US_TR_BASE",     "ledger": "US"},
    {"key": "utr_jeo2",  "label": "UTR_저2",     "color": "#E74C3C", "kind": "daily", "tag": "US_TR_JEO2",     "ledger": "US"},
    {"key": "utr_ma",    "label": "UTR_MA돌",    "color": "#EC6252", "kind": "daily", "tag": "US_TR_MA",       "ledger": "US"},
]


# ─────────────────────────── 공통 ───────────────────────────
def _board_dir(key):
    return f"board_{key}"


def _clean_dirs():
    """게시판 폴더 비우기 + 정의에서 빠진 옛 board_* 폴더 제거."""
    keep = {_board_dir(b["key"]) for b in BOARDS}
    os.makedirs(CHARTS_DIR, exist_ok=True)
    for path in glob.glob(os.path.join(CHARTS_DIR, "board_*")):
        if os.path.isdir(path) and os.path.basename(path) not in keep:
            shutil.rmtree(path, ignore_errors=True)
    for name in keep:
        d = os.path.join(CHARTS_DIR, name)
        os.makedirs(d, exist_ok=True)
        for f in glob.glob(os.path.join(d, "*.html")):
            try:
                os.remove(f)
            except OSError:
                pass


def _label(latest_iso, name):
    """'YYYY-MM-DD' + 종목명 → 'M/D 종목명6'."""
    nm = (name or "").strip()[:NAME_LEN]
    if latest_iso and len(latest_iso) == 10:
        return f"{int(latest_iso[5:7])}/{int(latest_iso[8:10])} {nm}"
    return nm


# KR 종목코드 = 6자리, 숫자로 시작(뒤에 영문 섞일 수 있음: 0193T0/0197X0 같은 단일종목 ETF).
# isdigit() 만 쓰면 0193T0 이 US 로 잘못 분류돼 yfinance 로 새어나가고,
# 다운로드 실패 -> "일봉 데이터 없음, skip" -> 게시판에서 해당 종목 차트가 사라진다.
_KR_CODE_RE = re.compile(r"\d[0-9A-Z]{5}")


def _market_of(code):
    return "KR" if _KR_CODE_RE.fullmatch(str(code).strip().upper()) else "US"


def _bar_label(date, hhmm):
    """5분봉 시작시각으로 스냅 → 'YYYY-MM-DD HH:MM'."""
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except (ValueError, IndexError):
        h, m = 9, 0
    return f"{date} {h:02d}:{(m // 5) * 5:02d}"


def _new_row(date):
    return {"date": date, "buys": [], "sells": [],
            "realized": 0.0, "basis": 0.0, "remain": 0}


def _wavg(items):
    q = sum(i["qty"] for i in items)
    return (sum(i["qty"] * i["price"] for i in items) / q) if q else 0


# ───────── intraday fill → tag별 포지션 replay ─────────
def _replay_fills(cutoff):
    """전 기간 fill 로 (계좌,종목,tag) 평단을 재구성.
    반환: rows_by_code {(tag,code): [일자행]}, marks {(tag,code): [B/S]}, info {(tag,code): {...}}
    cutoff 이전 거래는 평단 계산엔 쓰되 노출(info)·마커에선 뺀다."""
    positions, rows, marks, info, names = {}, {}, {}, {}, {}
    for f in wp.load_fills():
        tag = wp.resolve_performance_tag(f)
        if tag is None:                       # Pine TR = ledger 원천
            continue
        code, acct = f["code"], f["acct"]
        if f["name"]:
            names[(tag, code)] = f["name"]
        keep = f["date"] >= cutoff
        if keep:
            d = info.setdefault((tag, code), {"latest": f["date"]})
            if f["date"] > d["latest"]:
                d["latest"] = f["date"]
        pkey = (acct, code, tag)
        rkey = (tag, code, f["date"])
        row = rows.setdefault(rkey, _new_row(f["date"]))
        pos = positions.get(pkey)
        hhmm = f["dt"].strftime("%H:%M")
        if f["side"] == "buy":
            if pos and pos["qty"] > 0:
                tot = pos["qty"] * pos["avg"] + f["qty"] * f["price"]
                pos["qty"] += f["qty"]
                pos["avg"] = tot / pos["qty"]
            else:
                pos = positions[pkey] = {"qty": f["qty"], "avg": float(f["price"])}
            row["buys"].append({"qty": f["qty"], "price": f["price"]})
            if keep:
                marks.setdefault((tag, code), []).append(
                    {"t": _bar_label(f["date"], hhmm), "s": "B"})
        else:
            avg = pos["avg"] if pos else float(f["price"])   # 장부外 매도 → 손익 0
            row["realized"] += (f["price"] - avg) * f["qty"]
            row["basis"]    += avg * f["qty"]
            row["sells"].append({"qty": f["qty"], "price": f["price"]})
            if pos:
                pos["qty"] -= f["qty"]
                if pos["qty"] <= 0:
                    del positions[pkey]
                    pos = None
            if keep:
                marks.setdefault((tag, code), []).append(
                    {"t": _bar_label(f["date"], hhmm), "s": "S",
                     "amt": round((f["price"] - avg) * f["qty"]),
                     "pct": round((f["price"] / avg - 1) * 100, 2) if avg else 0.0})
        row["remain"] = positions.get(pkey, {}).get("qty", 0)

    rows_by_code = {}
    for (tag, code, _d), row in rows.items():
        rows_by_code.setdefault((tag, code), []).append(row)
    for v in rows_by_code.values():
        v.sort(key=lambda r: r["date"])
    for k, d in info.items():
        d["name"] = names.get(k, "")
    return rows_by_code, marks, info


# ───────── TR ledger → tag별 포지션 replay ─────────
def _replay_ledger(cutoff):
    """tr_ledger_*.json positions(code|strategy_tag) → 일자행/이름/최신거래일.
    반환: rows_by_code {(tag,code): [일자행]}, info {(tag,code): {'name','latest','market'}}"""
    rows_by_code, info = {}, {}
    for market, fname in LEDGER_FILES.items():
        path = os.path.join(LEDGER_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [!] TR ledger 읽기 실패({fname}): {e}")
            continue
        for pos in (data.get("positions") or {}).values():
            tag = pos.get("strategy_tag")
            code = str(pos.get("code", "") or "")
            if not tag or not code:
                continue
            orders = [o for o in (pos.get("orders") or [])
                      if int(o.get("filled_qty", 0) or 0) > 0
                      and float(o.get("avg_fill_price", 0) or 0) > 0]
            if not orders:
                continue
            orders.sort(key=lambda o: (str(o.get("trade_date", "")),
                                       str(o.get("ordered_at", ""))))
            qty_held, avg, rows, latest = 0, 0.0, {}, ""
            for o in orders:
                day = str(o.get("trade_date", ""))[:10]
                qty = int(o.get("filled_qty", 0) or 0)
                price = float(o.get("avg_fill_price", 0) or 0)
                row = rows.setdefault(day, _new_row(day))
                if str(o.get("side", "")).upper() == "BUY":
                    avg = ((qty_held * avg + qty * price) / (qty_held + qty)) if qty_held + qty else price
                    qty_held += qty
                    row["buys"].append({"qty": qty, "price": price})
                else:
                    base = avg if qty_held > 0 else price
                    row["realized"] += (price - base) * qty
                    row["basis"]    += base * qty
                    row["sells"].append({"qty": qty, "price": price})
                    qty_held = max(0, qty_held - qty)
                row["remain"] = qty_held
                if day > latest:
                    latest = day
            if not latest or latest < cutoff:
                continue
            key = (tag, code)
            rows_by_code[key] = sorted(rows.values(), key=lambda r: r["date"])
            info[key] = {"name": pos.get("name") or code, "latest": latest,
                         "market": market}
    return rows_by_code, info


# ───────── 5분봉 단독 페이지 (단타 게시판 PAGE_JS 1카드 재사용) ─────────
MIN5_TMPL = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>__LABEL__ __CODE__ (5분봉)</title>
<script src="../../lib/lightweight-charts.standalone.production.js"></script>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:#fff; font-family:-apple-system,'Malgun Gothic',sans-serif; padding:8px; color:#1f2937; }
  .chart-card { background:#fff; width:min(__W__px,100%); }
  .chart-title { padding:6px 8px; font-size:14px; font-weight:bold; color:#333;
    display:flex; align-items:center; gap:8px; white-space:nowrap; }
  .chart-title .sub { font-size:11px; font-weight:normal; color:#999; font-family:monospace; }
  .chart-title .bd { font-size:11px; font-weight:700; color:#fff; padding:1px 8px; border-radius:20px; }
  .chart-title #status { font-size:11px; font-weight:700; color:#16a34a; margin-left:auto; }
  .cwrap { width:100%; }
  .chartbox { position:relative; }
  .legend { position:absolute; display:none; z-index:6; background:rgba(255,255,255,.96);
    border:1px solid #e5e7eb; border-radius:6px; padding:5px 8px; font-size:11px;
    line-height:1.5; color:#334155; pointer-events:none; min-width:150px;
    box-shadow:0 2px 8px rgba(0,0,0,.13); }
  .legend b { color:#0f172a; }
  .legend .k { display:inline-block; width:38px; color:#64748b; }
  .cchart { width:100%; height:calc(100vh - 200px); min-height:300px; }
  .rlab { font-size:10px; color:#6b7280; padding:3px 8px 1px; }
  .rchart { width:100%; height:130px; }
  .empty { height:300px; display:flex; align-items:center; justify-content:center; color:#991b1b; font-size:13px; font-weight:700; }
  .divider { position:absolute; top:0; bottom:0; width:0; display:none; z-index:4;
    border-left:2px dashed rgba(40,40,40,.85); pointer-events:none; }
  .anno { position:absolute; left:0; top:0; right:0; bottom:0; pointer-events:none; z-index:5; overflow:hidden; }
  .anno .s { position:absolute; transform:translate(-50%,-100%); text-align:center;
    font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; line-height:1.2;
    white-space:nowrap; text-shadow:0 0 2px #fff,0 0 2px #fff; }
  .anno .bmark { position:absolute; transform:translate(-50%,0);
    font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; line-height:1.25;
    background:#ffe600; border:1px solid #b59500; border-radius:2px; padding:0 4px; text-shadow:none; }
  .anno .sbox { display:inline-block; background:#ffe600; border:1px solid #b59500;
    border-radius:2px; padding:0 4px; line-height:1.25; text-shadow:none; }
</style>
</head>
<body>
<div class="chart-card">
  <div class="chart-title">__LABEL__ <span class="sub">__CODE__</span>
    <span class="bd" style="background:__COLOR__">__BOARD__</span>
    <span id="status">렌더링…</span></div>
  <div class="cwrap" id="card-0">
    <div class="chartbox"><div class="legend"></div><div class="cchart"></div></div>
    <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평 · 저/저2=저점신호 X=고점신호 B/S=매매 · 갱신 __NOW__</div>
    <div class="rchart"></div>
  </div>
</div>
<script>
(function(){
__JS__
})();
</script>
</body>
</html>
"""


def _build_min5_page(board, code, label, rows, marks):
    order = [{"idx": 0, "code": code, "label": label}]
    nxt = [code] if is_nxt(code) else []
    # 보드 프리뷰는 폭이 넓어(매매일지 hover) 2거래일치를 줌인 없이 보여줌 → VIEW_2DAYS 켬.
    js = ("window.VIEW_2DAYS=true;\n" + MIN5_JS
          .replace("__MIN5__",   json.dumps({code: rows}, ensure_ascii=False, separators=(",", ":")))
          .replace("__ORDER__",  json.dumps(order, ensure_ascii=False, separators=(",", ":")))
          .replace("__NXTSET__", json.dumps(nxt))
          .replace("__TRADES__", json.dumps({code: marks}, ensure_ascii=False, separators=(",", ":"))))
    return (MIN5_TMPL
            .replace("__LABEL__", label)
            .replace("__CODE__", code)
            .replace("__BOARD__", board["label"])
            .replace("__COLOR__", board["color"])
            .replace("__W__", str(CHART_WIDTH))
            .replace("__NOW__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__JS__", js))


# ───────── 일봉 단독 페이지 (auto_trade_20day_chart_8042 엔진 재사용) ─────────
def _daily_html(board, code, name, rows, market):
    """일자행 → 8042 엔진 CSV-row 로 변환 후 렌더. 실패 시 ''."""
    csv_rows = []
    for r in rows:
        mmdd = f"{int(r['date'][5:7])}/{int(r['date'][8:10])}"
        has_b, has_s = bool(r["buys"]), bool(r["sells"])
        pct = (r["realized"] / r["basis"] * 100) if (has_s and r["basis"]) else 0.0
        csv_rows.append({
            "티커": code, "종목명": name,
            "날짜":     mmdd if has_b else "",
            "매수가":   _wavg(r["buys"]) if has_b else "",
            "매도날짜": mmdd if has_s else "",
            "매도가":   _wavg(r["sells"]) if has_s else "",
            "수익률(%)": round(pct, 2) if has_s else 0,
            "수익금액":  round(r["realized"]) if has_s else 0,
            "open포지션": "1" if r.get("remain", 0) > 0 else "0",
        })
    html = d8042.build_ticker_html(code, name, csv_rows, market=market)
    if not html:
        return ""
    # 8042 전용 표기 → 이 게시판 표기 + 기본 보기 봉수 + 공통 차트 폭
    return (html
            .replace('<span class="acnt">8042</span>',
                     f'<span class="acnt" style="background:{board["color"]}">{board["label"]}</span>')
            .replace(f"<title>{name} [8042]</title>", f"<title>{name} [{board['label']}]</title>")
            .replace(",from=Math.max(0,tot-120),", f",from=Math.max(0,tot-{DAILY_BARS}),")
            .replace(
                ".chartbox{position:relative;background:#fff;border:1px solid #e0e0e0;border-radius:10px;overflow:hidden;flex:1;min-height:0;display:flex;flex-direction:column}",
                ".chartbox{position:relative;background:#fff;border:1px solid #e0e0e0;border-radius:10px;"
                f"overflow:hidden;flex:none;min-height:0;display:flex;flex-direction:column;"
                f"width:min({CHART_WIDTH}px,100%);height:calc(100vh - 110px)}}"))


# ─────────────────────────── 엔트리 ───────────────────────────
def generate():
    """게시판 전체 생성 → {key: [(latest_iso, label, value), ...] 최신순}.
    거래가 없는 tag 는 빈 리스트 → 헤더에서 드롭다운 자체가 안 생긴다."""
    cutoff = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    _clean_dirs()

    fill_rows, fill_marks, fill_info = _replay_fills(cutoff)
    led_rows, led_info = _replay_ledger(cutoff)

    # 5분봉은 게시판별로 따로 긁으면 같은 종목을 여러 번 조회 → 전체 합집합 1회 수집
    min5_codes = sorted({code for b in BOARDS if b["kind"] == "5min"
                         for (tag, code) in fill_info if tag == b["tag"]})
    min5 = {}
    if min5_codes:
        print(f"  [5분봉 수집] {len(min5_codes)}종목 × {DAYS5}일")
        min5 = add_trend_states(collect_5min(min5_codes, days=DAYS5))

    result = {}
    for board in BOARDS:
        tag, key = board["tag"], board["key"]
        out_dir = os.path.join(CHARTS_DIR, _board_dir(key))
        src_info = led_info if board.get("ledger") else fill_info
        src_rows = led_rows if board.get("ledger") else fill_rows
        codes = sorted([(k[1], v) for k, v in src_info.items() if k[0] == tag],
                       key=lambda kv: kv[1]["latest"], reverse=True)
        opts = []
        for code, info in codes:
            name = info.get("name") or code
            label = _label(info["latest"], name)
            if board["kind"] == "5min":
                html = _build_min5_page(board, code, label,
                                        min5.get(code, []),
                                        fill_marks.get((tag, code), []))
            else:
                market = board.get("market") or info.get("market") or _market_of(code)
                html = _daily_html(board, code, name,
                                   src_rows.get((tag, code), []), market)
                if not html:
                    print(f"     {code} {name}  [!] 일봉 데이터 없음, skip")
                    continue
            with open(os.path.join(out_dir, f"{code}.html"), "w", encoding="utf-8") as f:
                f.write(html)
            opts.append((info["latest"], label, f"charts/{_board_dir(key)}/{code}.html"))
        opts.sort(key=lambda x: x[0], reverse=True)
        result[key] = opts
        if opts:
            print(f"  [{board['label']}] {len(opts)}종목")
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("make_trade_chart_boards.py — 성과 tag별 자동일지차트 생성")
    print("=" * 60)
    res = generate()
    for b in BOARDS:
        print(f"{b['label']:12s} {len(res.get(b['key'], []))}개")
