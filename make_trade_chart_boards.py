# -*- coding: utf-8 -*-
"""
make_trade_chart_boards.py ── 자동일지차트 게시판(성과 tag별)용 차트 생성기
─────────────────────────────────────────────────────────────────────────────
주간성과(make_weekly_performance.py)의 성과 tag 를 그대로 게시판 단위로 쓴다.
tag 확정 규칙은 wp.resolve_performance_tag() 하나만 사용 → 주간성과 표와 차트가
같은 기준으로 갈린다. 같은 종목이라도 tag 가 다르면 포지션·평단이 섞이지 않는다.
예외 하나: ADD1(피라미딩 추가매수)은 메뉴를 따로 두지 않고 같은 종목의 Core 차트에
보라색 'A' 화살표로 합친다(2026-10-09 사용자). 평단·손익은 ADD1 자체 장부대로 따로 계산한다.

원천:
  · fill   = intraday_signals/*.json 체결 (주도주/수동매매/통합ETF/삼닉v3/2X단타/저사다리/…)
  · ledger = 0order/tr/ledger/tr_ledger_*.json 의 strategy_tag (KTR_* / UTR_*)
  · coin   = 업비트 TR·Top3 장부, 바이낸스 TR·Top3 장부(history), BTC/ETH 국면v6 체결 jsonl
             (2026-10-09 추가. 일봉은 coin_daily_ohlcv — 업비트/바이낸스 공개 캔들)

렌더:
  · 5분봉 = "요약-단타 게시판"(make_danta_chart_display) PAGE_JS
  · 일봉  = auto_trade_20day_chart_8042.build_ticker_html (KR=pykrx/NXT, US=us_ohlcv_cache, 코인)
  둘 다 ?card=1&focus=YYYY-MM-DD 를 붙이면 '날짜별' 카드 모드(헤더·RSI 없이, 그날 봉 중심).

날짜별(2026-10-09): generate() 가 DAY_CARDS {표시일: [카드]} 를 채운다 → make_trade_daily_home.py 가
  첫 화면(일별손익 + 그날 매매차트 펼침)을 만든다. 표시일 = 체결 시각의 KST 달력일
  (매매 MASTER 일별 손익과 같은 날짜 기준). 차트 봉 위치는 그 시장의 거래일(trade_date).

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
ROOT_DIR = os.path.dirname(BASE_DIR)                 # D:\py
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, ROOT_DIR)

import make_weekly_performance as wp            # fill 로더 + 성과 tag 확정
from make_danta_chart_display import PAGE_JS as MIN5_JS, add_trend_states
from chart_popup_v2 import collect_5min, is_nxt
import auto_trade_20day_chart_8042 as d8042     # 일봉 엔진

RECENT_DAYS = 30        # 최근 30일 거래분만 게시판에 노출
NAME_LEN    = 6
DAYS5       = 25        # 5분봉 수집 거래일수 (30일치 날짜별 카드용. 키움 8페이지 ≈ 40일까지 가능)
CHART_WIDTH = 1300      # 모든 게시판 공통 차트 폭(px)
DAILY_BARS  = 60        # 일봉 기본 보기 봉수

CHARTS_DIR = os.path.join(BASE_DIR, "charts")
LEDGER_DIR = os.path.join(ROOT_DIR, "0order", "tr", "ledger")
LEDGER_FILES = {"KR": "tr_ledger_2773_KR.json", "US": "tr_ledger_1887_US.json"}
COIN_LEDGERS = [   # (venue, 경로) — 포지션 history 를 replay
    ("UPBIT",   os.path.join(ROOT_DIR, "coin", "0order", "ledger", "coin_tr_upbit_live.json")),
    ("UPBIT",   os.path.join(ROOT_DIR, "coin", "0order", "ledger", "coin_ctop3_upbit_live.json")),
    ("BINANCE", os.path.join(ROOT_DIR, "coin_binan", "ledger", "binan_tr_futures_live.json")),
]
RG6_JSONL = os.path.join(ROOT_DIR, "coin", "0order", "btceth_regime_v6_orders.jsonl")
RG6_TAG = "UP_RG6"

# ── 게시판 정의 = 헤더 노출 순서 ──────────────────────────────
#   tag    : 성과 tag (fill 보드는 wp.resolve_performance_tag 결과, ledger 보드는 strategy_tag)
#   kind   : "5min" | "daily"
#   ledger : 있으면 장부 원천(KR/US TR, 코인), 없으면 intraday fill 원천
#   market : 일봉 OHLCV 출처. 생략하면 종목코드로 자동판별(6자리 숫자=KR, 그 외=US)
#
# 순서(2026-10-09 재배치) = 지금 주력 순: 미국 TR → 한국 TR → 코인 → 수동/기타(일봉) → 5분봉.
# 거래 없는 tag 는 헤더에서 자동으로 숨는다(지워도 되지만 남겨둬야 다시 켤 때 그대로 뜬다).
#
# 색상 = 계열 구분(글자는 항상 흰색). 보유자산 게시판 투자비중 도넛의 기준색을 따른다.
#   KTR_* = 파랑(도넛 KR #4a7ac7) · UTR_* = 빨강(도넛 US #e74c3c) · 코인 = 주황(업비트)/황토(바이낸스)
TR_SUFFIXES = [  # (태그 접미사, 메뉴 표기)
    ("ORD_B", "ORD_B"), ("ORD_1A0", "1a0"), ("BLACK_B", "검정B"), ("PURPLE_B", "보라B"),
    ("VOLUME_1", "vol1"), ("VOLUME_2", "vol2"), ("VCP1", "VCP1"), ("BASE", "BASE"),
    ("JEO2", "저2"), ("MA", "MA돌"), ("CHART", "차트"),
]


def _coin_tr_boards(prefix, short, market, colors):
    return [{"key": f"{prefix.lower()}tr_{suf.lower()}", "label": f"{short}TR_{lab}",
             "color": colors[i % len(colors)], "kind": "daily",
             "tag": f"{prefix}_TR_{suf}", "ledger": prefix, "market": market}
            for i, (suf, lab) in enumerate(TR_SUFFIXES)]


BOARDS = [
    # 빨강 — 미국 TR (도넛 US 계열)
    {"key": "utr_ord_b", "label": "UTR_ORD_B",   "color": "#8F1A12", "kind": "daily", "tag": "US_TR_ORD_B",    "ledger": "US"},
    {"key": "utr_1a0",   "label": "UTR_1a0",     "color": "#9D2017", "kind": "daily", "tag": "US_TR_ORD_1A0",  "ledger": "US"},
    {"key": "utr_blackb", "label": "UTR_검정B",  "color": "#A2231A", "kind": "daily", "tag": "US_TR_BLACK_B",  "ledger": "US"},
    {"key": "utr_purpleb","label": "UTR_보라B",  "color": "#A6251B", "kind": "daily", "tag": "US_TR_PURPLE_B", "ledger": "US"},
    {"key": "utr_vcp1",  "label": "UTR_VCP1",    "color": "#AB271C", "kind": "daily", "tag": "US_TR_VCP1",     "ledger": "US"},
    {"key": "utr_base",  "label": "UTR_BASE",    "color": "#C63628", "kind": "daily", "tag": "US_TR_BASE",     "ledger": "US"},
    {"key": "utr_jeo2",  "label": "UTR_저2",     "color": "#E74C3C", "kind": "daily", "tag": "US_TR_JEO2",     "ledger": "US"},
    {"key": "utr_ma",    "label": "UTR_MA돌",    "color": "#EC6252", "kind": "daily", "tag": "US_TR_MA",       "ledger": "US"},
    {"key": "utr_chart", "label": "UTR_차트",    "color": "#F07A6C", "kind": "daily", "tag": "US_TR_CHART",    "ledger": "US"},
    # 파랑 — 한국 TR (도넛 KR 계열)
    {"key": "ktr_ord_b", "label": "KTR_ORD_B",   "color": "#16337A", "kind": "daily", "tag": "KR_TR_ORD_B",    "ledger": "KR"},
    {"key": "ktr_1a0",   "label": "KTR_1a0",     "color": "#1A3A87", "kind": "daily", "tag": "KR_TR_ORD_1A0",  "ledger": "KR"},
    {"key": "ktr_blackb", "label": "KTR_검정B",  "color": "#1E3E8C", "kind": "daily", "tag": "KR_TR_BLACK_B",  "ledger": "KR"},
    {"key": "ktr_purpleb","label": "KTR_보라B",  "color": "#22438F", "kind": "daily", "tag": "KR_TR_PURPLE_B", "ledger": "KR"},
    {"key": "ktr_vol1",  "label": "KTR_vol1",    "color": "#1C4192", "kind": "daily", "tag": "KR_TR_VOLUME_1", "ledger": "KR"},
    {"key": "ktr_vol2",  "label": "KTR_vol2",    "color": "#2450AB", "kind": "daily", "tag": "KR_TR_VOLUME_2", "ledger": "KR"},
    {"key": "ktr_vcp1",  "label": "KTR_VCP1",    "color": "#2D5FC0", "kind": "daily", "tag": "KR_TR_VCP1",     "ledger": "KR"},
    {"key": "ktr_base",  "label": "KTR_BASE",    "color": "#3A6FCF", "kind": "daily", "tag": "KR_TR_BASE",     "ledger": "KR"},
    {"key": "ktr_jeo2",  "label": "KTR_저2",     "color": "#4A7AC7", "kind": "daily", "tag": "KR_TR_JEO2",     "ledger": "KR"},
    {"key": "ktr_ma",    "label": "KTR_MA돌",    "color": "#5A89D4", "kind": "daily", "tag": "KR_TR_MA",       "ledger": "KR"},
    {"key": "ktr_chart", "label": "KTR_차트",    "color": "#6A97DC", "kind": "daily", "tag": "KR_TR_CHART",    "ledger": "KR"},
    # 주황 — 업비트 / 황토 — 바이낸스 (코인, 2026-10-09)
    {"key": "up_ctop3",  "label": "업비트Top3",  "color": "#C2410C", "kind": "daily", "tag": "UP_CTOP3", "ledger": "UP", "market": "UPBIT"},
    *_coin_tr_boards("UP", "업", "UPBIT", ["#D9480F", "#E8590C", "#F76707"]),
    {"key": "up_rg6",    "label": "업비트국면v6", "color": "#9A3412", "kind": "daily", "tag": RG6_TAG,   "ledger": "RG6", "market": "UPBIT"},
    {"key": "bn_ctop3",  "label": "바낸Top3",    "color": "#854D0E", "kind": "daily", "tag": "BN_CTOP3", "ledger": "BN", "market": "BINANCE"},
    *_coin_tr_boards("BN", "바", "BINANCE", ["#A16207", "#B7791F", "#CA8A04"]),
    # 녹색 — 일봉 스윙(주도주·수동 계열)
    {"key": "leader",    "label": "주도주",      "color": "#15794A", "kind": "daily", "tag": "주도주"},
    {"key": "rocket",    "label": "로켓",        "color": "#1D8F58", "kind": "daily", "tag": "ROCKET"},
    {"key": "manual",    "label": "수동매매",    "color": "#2AA467", "kind": "daily", "tag": "수동매매"},
    {"key": "alletf",    "label": "통합ETF",     "color": "#3BB878", "kind": "daily", "tag": "통합ETF"},
    {"key": "usvcp",     "label": "미VCP",       "color": "#5F6871", "kind": "daily", "tag": "미국VCP",     "market": "US"},
    {"key": "us_manual", "label": "미국수동",    "color": "#6F7883", "kind": "daily", "tag": "미국수동",    "market": "US"},
    # 보라·회색 — 5분봉 (날짜별 화면에선 맨 끝 '5분봉' 묶음)
    {"key": "x2danta",   "label": "2X단타",      "color": "#4C1D95", "kind": "5min",  "tag": "2X단타"},
    {"key": "v3_jeo2",   "label": "삼닉v3_저2",  "color": "#5B21B6", "kind": "5min",  "tag": "삼닉v3_저2"},
    {"key": "v3_trend",  "label": "삼닉v3_추세", "color": "#6A2ECB", "kind": "5min",  "tag": "삼닉v3_추세"},
    {"key": "v3_ma",     "label": "삼닉v3_MA",   "color": "#7C3AED", "kind": "5min",  "tag": "삼닉v3_MA"},
    {"key": "hl1",       "label": "5분HL",       "color": "#8B4CEE", "kind": "5min",  "tag": "5minHL"},
    {"key": "hl2",       "label": "5분HL2",      "color": "#985EEA", "kind": "5min",  "tag": "5minHL2"},
    {"key": "hl_etc",    "label": "5분기타",     "color": "#A471DE", "kind": "5min",  "tag": "5minHL_미분류"},
    {"key": "dip",       "label": "저사다리",    "color": "#818A94", "kind": "5min",  "tag": "저점사다리"},
    {"key": "etc8042",   "label": "기타(8042)",  "color": "#939BA4", "kind": "5min",  "tag": "기타(8042)"},
]
BOARD_TAGS = {b["tag"] for b in BOARDS}

# 날짜별 카드 {표시일 'YYYY-MM-DD': [카드 dict, ...]} — generate() 가 채운다
DAY_CARDS = {}


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


def _ccy_of(market):
    return "USD" if market in ("US", "BINANCE") else "KRW"


def _bar_label(date, hhmm):
    """5분봉 시작시각으로 스냅 → 'YYYY-MM-DD HH:MM'."""
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except (ValueError, IndexError):
        h, m = 9, 0
    return f"{date} {h:02d}:{(m // 5) * 5:02d}"


def _new_row(date):
    return {"date": date, "buys": [], "adds": [], "sells": [],
            "realized": 0.0, "basis": 0.0, "remain": 0}


def _wavg(items):
    q = sum(i["qty"] for i in items)
    return (sum(i["qty"] * i["price"] for i in items) / q) if q else 0


def _parse_dt(v):
    """'2026-10-07T04:45:47+09:00' / '2026-10-07 09:23:29' → naive KST datetime (없으면 None)."""
    s = str(v or "").strip()
    if len(s) < 16:
        return None
    try:
        return datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(s[:16].replace("T", " "), "%Y-%m-%d %H:%M")
        except ValueError:
            return None


def _ev(dt, day, side, pnl=None):
    """날짜별 카드용 체결 이벤트. 표시일 = 체결시각 KST 달력일(없으면 거래일)."""
    return {"day": dt.strftime("%Y-%m-%d") if dt else day,
            "t": dt.strftime("%H:%M") if dt else "", "s": side, "pnl": pnl}


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
            d = info.setdefault((tag, code), {"latest": f["date"], "events": []})
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
                info[(tag, code)]["events"].append(_ev(f["dt"], f["date"], "B"))
        else:
            avg = pos["avg"] if pos else float(f["price"])   # 장부外 매도 → 손익 0
            pnl = (f["price"] - avg) * f["qty"]
            row["realized"] += pnl
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
                     "amt": round(pnl),
                     "pct": round((f["price"] / avg - 1) * 100, 2) if avg else 0.0})
                info[(tag, code)]["events"].append(_ev(f["dt"], f["date"], "S", pnl))
        row["remain"] = positions.get(pkey, {}).get("qty", 0)

    rows_by_code = {}
    for (tag, code, _d), row in rows.items():
        rows_by_code.setdefault((tag, code), []).append(row)
    for v in rows_by_code.values():
        v.sort(key=lambda r: r["date"])
    for k, d in info.items():
        d["name"] = names.get(k, "")
    return rows_by_code, marks, info


# ───────── 장부(TR·코인) → tag별 포지션 replay ─────────
def _replay_orders(orders, sign=1.0, add=False):
    """orders: [{'day': 봉 날짜, 'dt': KST datetime|None, 'side': 'BUY'|'SELL', 'qty', 'price'}] 시간순.
    한 포지션(장부 키 하나)의 평단 replay → (rows {day: row}, events, latest).
    add=True 면 매수를 row['adds'] / 이벤트 'A' 로 넣는다(ADD1)."""
    held, avg, rows, evs, latest = 0.0, 0.0, {}, [], ""
    for o in orders:
        day, qty, price = o["day"], o["qty"], o["price"]
        if not day or qty <= 0 or price <= 0:
            continue
        row = rows.setdefault(day, _new_row(day))
        if o["side"] == "BUY":
            avg = ((held * avg + qty * price) / (held + qty)) if held > 0 else price
            held += qty
            row["adds" if add else "buys"].append({"qty": qty, "price": price})
            evs.append(_ev(o["dt"], day, "A" if add else "B"))
        else:
            base = avg if held > 0 else price
            pnl = (price - base) * qty * sign
            row["realized"] += pnl
            row["basis"]    += base * qty
            row["sells"].append({"qty": qty, "price": price})
            held = max(0.0, held - qty)
            evs.append(_ev(o["dt"], day, "S", pnl))
        row["remain"] = held
        latest = max(latest, day)
    return rows, evs, latest


def _tr_positions():
    """KR/US TR 장부 → [(ledger, tag, code, name, market, sign, orders)]."""
    out = []
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
            orders = []
            for o in pos.get("orders") or []:
                qty = int(o.get("filled_qty", 0) or 0)
                price = float(o.get("avg_fill_price", 0) or 0)
                if qty <= 0 or price <= 0:
                    continue
                orders.append({"day": str(o.get("trade_date", ""))[:10],
                               "dt": _parse_dt(o.get("ordered_at")),
                               "side": "BUY" if str(o.get("side", "")).upper() == "BUY" else "SELL",
                               "qty": qty, "price": price, "_k": str(o.get("ordered_at", ""))})
            orders.sort(key=lambda o: (o["day"], o["_k"]))
            out.append((market, tag, code, pos.get("name") or code, market, 1.0, orders))
    return out


def _coin_positions():
    """업비트/바이낸스 코인 장부 history → [(ledger, tag, code, name, market, sign, orders)]."""
    out = []
    for venue, path in COIN_LEDGERS:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [!] 코인 장부 읽기 실패({os.path.basename(path)}): {e}")
            continue
        for pos in (data.get("positions") or {}).values():
            tag = str(pos.get("strategy_tag") or "")
            code = str(pos.get("code") or "")
            if not tag or not code:
                continue
            sign = -1.0 if str(pos.get("direction") or "").upper() == "SHORT" else 1.0
            orders = []
            for h in pos.get("history") or []:
                if h.get("side") not in ("BUY", "SELL"):
                    continue
                try:
                    vol, funds = float(h.get("volume") or 0), float(h.get("funds") or 0)
                except (TypeError, ValueError):
                    continue
                if vol <= 0 or funds <= 0:
                    continue
                orders.append({"day": str(h.get("trade_date") or "")[:10], "dt": _parse_dt(h.get("at")),
                               "side": h["side"], "qty": vol, "price": funds / vol,
                               "_k": str(h.get("at") or "")})
            orders.sort(key=lambda o: (o["_k"], o["day"]))
            name = code[:-4] if venue == "BINANCE" and code.endswith("USDT") else code
            out.append((venue, tag, code, name, venue, sign, orders))
    # BTC/ETH 국면 비중봇 v6 — 체결 jsonl. ADOPT(수동 BTC/ETH 인계) = 그 시각 가격의 진입.
    if os.path.exists(RG6_JSONL):
        by_code = {}
        with open(RG6_JSONL, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                act = str(r.get("action") or "").upper()
                if act not in ("ADOPT", "BUY", "SELL"):
                    continue
                dt = _parse_dt(r.get("time"))
                try:
                    qty, price = float(r.get("fill_volume") or 0), float(r.get("price") or 0)
                except (TypeError, ValueError):
                    continue
                if dt is None or qty <= 0 or price <= 0:
                    continue
                day = (dt - timedelta(hours=9)).strftime("%Y-%m-%d")   # 업비트 일봉 = KST 09:00 경계
                by_code.setdefault(str(r.get("code") or ""), []).append(
                    {"day": day, "dt": dt, "side": "SELL" if act == "SELL" else "BUY",
                     "qty": qty, "price": price, "_k": str(r.get("time"))})
        for code, orders in by_code.items():
            orders.sort(key=lambda o: o["_k"])
            out.append(("RG6", RG6_TAG, code, code, "UPBIT", 1.0, orders))
    return out


def _merge_rows(dst, src):
    for day, r in src.items():
        t = dst.setdefault(day, _new_row(day))
        for k in ("buys", "adds", "sells"):
            t[k].extend(r[k])
        t["realized"] += r["realized"]
        t["basis"]    += r["basis"]
        t["remain"]   = max(t["remain"], r["remain"])


def _pick_core(add_orders, cores):
    """ADD1 이 붙을 Core: ADD1 첫 매수 시점에 보유 중이던(첫매수 ≤ 그 시각 ≤ 마지막 거래) Core.
    없으면 그 시각 이전에 시작한 Core 중 가장 최근 것, 그것도 없으면 첫 Core."""
    k0 = min((o["_k"] or o["day"]) for o in add_orders)
    span = []
    for c in cores:
        ks = [(o["_k"] or o["day"]) for o in c[6]]
        if ks:
            span.append((min(ks), max(ks), c))
    inside = [s for s in span if s[0] <= k0 <= s[1]]
    if inside:
        return max(inside, key=lambda s: s[0])[2]
    before = [s for s in span if s[0] <= k0]
    if before:
        return max(before, key=lambda s: s[0])[2]
    return cores[0] if cores else None


def _replay_ledger(cutoff):
    """TR·코인 장부 → rows_by_code {(tag,code): [일자행]}, info {(tag,code): {'name','latest','market','events'}}.
    ADD1 포지션은 같은 장부·같은 종목의 Core 포지션 행에 합친다(평단은 따로)."""
    rows_by_code, info = {}, {}
    positions = _tr_positions() + _coin_positions()
    cores = [p for p in positions if not p[1].endswith("_ADD1")]
    adds = [p for p in positions if p[1].endswith("_ADD1")]

    built = {}   # (tag, code) → [rows dict, events, latest, name, market]
    for ledger, tag, code, name, market, sign, orders in cores:
        if not orders:
            continue
        rows, evs, latest = _replay_orders(orders, sign)
        cur = built.get((tag, code))
        if cur:                      # 같은 tag·종목이 장부에 두 줄이면(이론상 없음) 합친다
            _merge_rows(cur[0], rows)
            cur[1].extend(evs)
            cur[2] = max(cur[2], latest)
        else:
            built[(tag, code)] = [rows, evs, latest, name, market]
    for p in adds:
        ledger, tag, code, name, market, sign, orders = p
        if not orders:
            continue
        # 같은 장부·같은 종목·같은 계열(KR_TR_/US_TR_/UP_TR_/BN_TR_)의 Core 에만 붙인다
        #   (업비트는 TR 과 Top3 봇이 같은 코인을 따로 들 수 있다)
        fam = tag[:-len("ADD1")]
        core = _pick_core(orders, [c for c in cores if c[0] == ledger and c[2] == code
                                   and c[1].startswith(fam) and c[6]])
        if core is None or (core[1], code) not in built:
            print(f"     [ADD1] {code} {tag}: 붙일 Core 포지션 없음 → 차트 생략")
            continue
        rows, evs, latest = _replay_orders(orders, sign, add=True)
        tgt = built[(core[1], code)]
        _merge_rows(tgt[0], rows)
        tgt[1].extend(evs)
        tgt[2] = max(tgt[2], latest)

    unknown = sorted({t for (t, _c), v in built.items() if t not in BOARD_TAGS and v[2] >= cutoff})
    if unknown:
        print(f"  [!] 메뉴가 없는 장부 tag (게시판에 안 나옴): {', '.join(unknown)}")
    for key, (rows, evs, latest, name, market) in built.items():
        if not latest or latest < cutoff:
            continue
        rows_by_code[key] = sorted(rows.values(), key=lambda r: r["date"])
        info[key] = {"name": name, "latest": latest, "market": market,
                     "events": [e for e in evs if e["day"] >= cutoff]}
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
<script>/* ?card=1&focus=YYYY-MM-DD = 자동일지 '날짜별' 카드(iframe) — 제목·RSI 숨기고 그날 봉만 */
(function(){var q=location.search;if(/[?&]card=1/.test(q))document.documentElement.className+=' card';
var m=q.match(/[?&]focus=([0-9-]{10})/);if(m)window.FOCUS_DAY=m[1];})();</script>
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
  .card body { padding:0; }
  .card .chart-card { width:100%; }
  .card .chart-title, .card .rlab, .card .rchart { display:none !important; }
  .card .cchart { height:100vh; min-height:0; }
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


def _min5_keep_days(rows, days):
    """5분봉은 매매한 날 + 그 직전 거래일만 남긴다(지표 워밍업용). 25일치를 다 넣으면 페이지가 커진다."""
    all_days = sorted({r[6][:10] for r in rows})
    keep = set()
    for d in days:
        if d in all_days:
            keep.add(d)
            i = all_days.index(d)
            if i > 0:
                keep.add(all_days[i - 1])
    if all_days:
        keep.add(all_days[-1])
    return [r for r in rows if r[6][:10] in keep]


# ───────── 일봉 단독 페이지 (auto_trade_20day_chart_8042 엔진 재사용) ─────────
def _daily_html(board, code, name, rows, market):
    """일자행 → 8042 엔진 CSV-row 로 변환 후 렌더. 실패 시 ''."""
    csv_rows = []
    for r in rows:
        mmdd = f"{int(r['date'][5:7])}/{int(r['date'][8:10])}"
        ins = r["buys"] + r.get("adds", [])
        has_b, has_s = bool(ins), bool(r["sells"])
        pct = (r["realized"] / r["basis"] * 100) if (has_s and r["basis"]) else 0.0
        csv_rows.append({
            "티커": code, "종목명": name,
            "날짜":     mmdd if has_b else "",
            "매수가":   _wavg(ins) if has_b else "",
            "매도날짜": mmdd if has_s else "",
            "매도가":   _wavg(r["sells"]) if has_s else "",
            "수익률(%)": round(pct, 2) if has_s else 0,
            "수익금액":  round(r["realized"], 2) if has_s else 0,
            "open포지션": "1" if r.get("remain", 0) > 0 else "0",
            # 체결가 화살표는 평단 1개가 아니라 체결마다 (ADD1 = 보라 'A')
            "_buy_prices":  [b["price"] for b in r["buys"]],
            "_add_prices":  [b["price"] for b in r.get("adds", [])],
            "_sell_prices": [s["price"] for s in r["sells"]],
        })
    # 엔진의 날짜 키는 'M/D' → 연도 넘어가면 겹칠 수 있으나 표시구간(6개월)이라 무시
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


# ───────── 날짜별 카드 ─────────
def _day_cards(board, code, name, url, events, market, min5_days=None):
    """한 차트의 체결 이벤트 → {표시일: 카드}. 카드 = 그날 매수/매도 횟수 + 그날 실현손익."""
    out = {}
    for e in events:
        c = out.get(e["day"])
        if c is None:
            c = out[e["day"]] = {
                "key": board["key"], "board": board["label"], "color": board["color"],
                "kind": board["kind"], "code": code, "name": (name or code)[:NAME_LEN + 4],
                "url": url, "nB": 0, "nA": 0, "nS": 0, "pnl": 0.0, "ccy": _ccy_of(market),
                "t": e["t"] or "99:99"}
            if min5_days is not None:
                c["nodata"] = e["day"] not in min5_days
        if e["s"] == "S":
            c["nS"] += 1
            c["pnl"] += e["pnl"] or 0.0
        elif e["s"] == "A":
            c["nA"] += 1
        else:
            c["nB"] += 1
        if e["t"] and e["t"] < c["t"]:
            c["t"] = e["t"]
    for c in out.values():
        c["pnl"] = round(c["pnl"], 2)
    return out


# ─────────────────────────── 엔트리 ───────────────────────────
def generate():
    """게시판 전체 생성 → {key: [(latest_iso, label, value), ...] 최신순}.
    거래가 없는 tag 는 빈 리스트 → 헤더에서 드롭다운 자체가 안 생긴다.
    부수효과: DAY_CARDS 채움(날짜별 첫 화면용)."""
    cutoff = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    _clean_dirs()
    DAY_CARDS.clear()

    fill_rows, fill_marks, fill_info = _replay_fills(cutoff)
    led_rows, led_info = _replay_ledger(cutoff)

    unknown = sorted({t for (t, _c) in fill_info if t not in BOARD_TAGS})
    if unknown:
        print(f"  [!] 메뉴가 없는 성과 tag (게시판에 안 나옴): {', '.join(unknown)}")

    # 5분봉은 게시판별로 따로 긁으면 같은 종목을 여러 번 조회 → 전체 합집합 1회 수집
    min5_codes = sorted({code for b in BOARDS if b["kind"] == "5min"
                         for (tag, code) in fill_info if tag == b["tag"]})
    min5_raw = {}
    if min5_codes:
        print(f"  [5분봉 수집] {len(min5_codes)}종목 × {DAYS5}일")
        min5_raw = collect_5min(min5_codes, days=DAYS5)

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
            min5_days = None
            if board["kind"] == "5min":
                market = "KR"
                trade_days = sorted({m["t"][:10] for m in fill_marks.get((tag, code), [])})
                rows5 = _min5_keep_days(min5_raw.get(code, []), trade_days)
                rows5 = add_trend_states({code: rows5}).get(code, []) if rows5 else []
                min5_days = {r[6][:10] for r in rows5}
                html = _build_min5_page(board, code, label, rows5,
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
            url = f"charts/{_board_dir(key)}/{code}.html"
            opts.append((info["latest"], label, url))
            for day, card in _day_cards(board, code, name, url, info.get("events", []),
                                        market, min5_days).items():
                DAY_CARDS.setdefault(day, []).append(card)
        opts.sort(key=lambda x: x[0], reverse=True)
        result[key] = opts
        if opts:
            print(f"  [{board['label']}] {len(opts)}종목")
    order = {b["key"]: i for i, b in enumerate(BOARDS)}
    for cards in DAY_CARDS.values():
        cards.sort(key=lambda c: (c["kind"] == "5min", order[c["key"]], c["t"]))
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("make_trade_chart_boards.py — 성과 tag별 자동일지차트 생성")
    print("=" * 60)
    res = generate()
    for b in BOARDS:
        n = len(res.get(b["key"], []))
        if n:
            print(f"{b['label']:12s} {n}개")
    for d in sorted(DAY_CARDS)[-7:]:
        print(d, len(DAY_CARDS[d]), "차트")
