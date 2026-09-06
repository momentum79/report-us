# -*- coding: utf-8 -*-
"""
journal_summary.py
==================
매매일지 차트 게시판(trade_chart_list.html)을 열었을 때 차트 대신
가장 먼저 보여줄 "당일 매매요약" 표(trade_journal_summary.html)를 생성한다.

데이터 소스
  - D:\\py\\0tradechart\\0_매매일지.csv         (1887 실현손익)
  - D:\\py\\0tradechart\\0_매매일지_8042.csv     (8042 실현손익)
장부(어느 봇) 매칭 소스
  - D:\\py\\0order\\0_trade_journal.csv          (1887 master: flag/order_type)
  - D:\\py\\0order\\0_trade_log_8042.csv         (8042 fallback presence)
  - D:\\py\\0order\\intraday_signals\\<날짜>.json (acct 필드: 2x/고저/TRAlert/저점)

장부 짧은 라벨
  8042CHU/*CHU → 2x  |  8042 → 고저  |  8042SH → TRAlert
  "저 매수" → 저점  |  로켓 → 로켓  |  TV알림 → TRAlert  |  master(네이버눌림/주도주) → 주도주
  어디서도 못 찾으면 → 수동

표시 범위: 최근 2거래일(매도일 기준) · 당일이 위로.
"""

import csv
import glob
import json
import os
import re
from datetime import datetime

# ─────────────────────────── 경로 ───────────────────────────
JOURNAL_1887   = r"D:\py\0tradechart\0_매매일지.csv"
JOURNAL_8042   = r"D:\py\0tradechart\0_매매일지_8042.csv"
TJ_1887        = r"D:\py\0order\0_trade_journal.csv"
LOG_8042       = r"D:\py\0order\0_trade_log_8042.csv"
INTRADAY_DIR   = r"D:\py\0order\intraday_signals"

RECENT_DAYS = 2   # 최근 N거래일(매도일)만 노출

# 차트 파일명 약어 규칙(make_index_trade_chart.abbr_name 과 동일) — 종목명 → 차트 stem
ETF_PREFIXES = ["KODEX", "TIGER", "KBSTAR", "HANARO", "ARIRANG", "KOSEF",
                "TREX", "FOCUS", "SOL", "ACE", "PLUS", "TIMEFOLIO",
                "KCGI", "WON", "SMART", "RISE", "1Q", "TIME"]


def _abbr_name(stock_name):
    name = (stock_name or "").strip()
    up = name.upper()
    for p in ETF_PREFIXES:
        if up.startswith(p):
            name = name[len(p):].lstrip()
            break
    name = name[:5]
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "")
    return name


# 장부 종류별 전용 보드 차트 폴더 (make_trade_chart_boards.py 생성물, 종목코드 키)
# 보드가 성과tag 단위로 잘게 쪼개져 있어 요약표의 굵은 장부라벨 하나에 여러 후보 폴더가 대응한다.
# 앞에서부터 존재하는 첫 폴더를 쓰고, 다 없으면 20일 일봉으로 폴백.
BOARD_BY_LEDGER = {
    "고저":     ["board_hl1", "board_hl2", "board_hl_etc"],
    "주도주":   ["board_leader"],
    "로켓":     ["board_rocket"],
    "저점":     ["board_dip"],
    "수동":     ["board_manual"],
    "한국매수": ["board_ktr_ord_b", "board_ktr_vol1", "board_ktr_vol2",
                 "board_ktr_vcp1", "board_ktr_base"],
    "한국저점": ["board_ktr_jeo2", "board_ktr_ma"],
}

# kr_pine_buy/kr_pine_lowbuy fill 이벤트의 strategy → 장부 라벨 (sync_kr_pine_1887_fills.py 산출)
KR_PINE_LABELS = {"kr_pine_buy": "한국매수", "kr_pine_lowbuy": "한국저점"}


def _chart_url(charts_dir, name, acct, sell_ymd="", ledger="", code=""):
    """종목 차트 상대 URL.
    1순위: 장부 전용 보드 차트(고저/주도주=5분봉, 로켓=일봉; 종목코드 키) — 있으면 사용.
    폴백: 20일 세션차트(charts/20days/, B&S 매매마커 포함 — 8042_20/1887_20 게시판과 동일
          포맷) → 일반 차트(charts/). 보드 차트가 없는 장부(저점/TRAlert/수동)이거나
          전용 보드 차트가 아직 없을 때(예: rocket 일봉 미생성) 기존 일봉으로 폴백한다.
    sell_ymd: 'YYYYMMDD' — 1887 20일차트는 파일명에 매도일(YYMMDD)이 붙는 경우가 있어
    같은 종목의 여러 매매 중 해당 거래일 세션차트를 우선 매칭한다."""
    if not charts_dir:
        return ""
    if code:
        for board in BOARD_BY_LEDGER.get(ledger, []):
            if os.path.exists(os.path.join(charts_dir, board, code + ".html")):
                return f"charts/{board}/{code}.html"
    abbr = _abbr_name(name)
    base = f"{abbr}_{acct}"
    d20 = os.path.join(charts_dir, "20days")
    cands = glob.glob(os.path.join(d20, glob.escape(base) + "*.html"))
    if cands:
        yy = sell_ymd[2:] if len(sell_ymd) == 8 else ""
        best = ""
        if yy:                                   # 매도일이 파일명에 든 세션차트 우선
            for p in cands:
                if yy in os.path.basename(p):
                    best = p
                    break
        if not best:                             # 접미사 없는 기본(보유중 등) 차트
            for p in cands:
                if os.path.basename(p) == base + ".html":
                    best = p
                    break
        if not best:                             # 그 외 파일명 정렬상 가장 최근
            best = sorted(cands)[-1]
        return "charts/20days/" + os.path.basename(best)[:-5] + ".html"
    if os.path.exists(os.path.join(charts_dir, base + ".html")):   # 일반 차트 폴백
        return f"charts/{base}.html"
    return ""

# 장부 라벨 색상(badge)
LEDGER_COLORS = {
    "2x":      "#9B5DE5",
    "고저":    "#00BB8A",
    "TRAlert": "#F4A261",
    "주도주":  "#3A86FF",
    "로켓":    "#E63946",
    "저점":    "#2D9D5F",
    "한국매수": "#3A86FF",
    "한국저점": "#2D9D5F",
    "수동":    "#9AA0A6",
}
ACCT_COLORS = {"1887": "#3A86FF", "8042": "#E63946"}


# ─────────────────────── 날짜 유틸 ───────────────────────
def _to_full_ymd(s, year):
    """매매일지 날짜(mm/dd 또는 yyyy-mm-dd) → 'YYYYMMDD'. 빈값 ''."""
    nums = re.findall(r"\d+", str(s or ""))
    if len(nums) >= 3 and len(nums[0]) == 4:
        return f"{int(nums[0]):04d}{int(nums[1]):02d}{int(nums[2]):02d}"
    if len(nums) >= 2:
        m, d = int(nums[0]), int(nums[1])
        y = year - 1 if m > datetime.now().month + 1 else year
        return f"{y:04d}{m:02d}{d:02d}"
    return ""


# ─────────────────── 장부 매칭 소스 로드 ───────────────────
def _load_intraday():
    """code → [(ymd, side, acct, reason), ...]  (type==order 만)."""
    out = {}
    for path in glob.glob(os.path.join(INTRADAY_DIR, "*.json")):
        base = os.path.basename(path)[:-5]            # 2026-06-24
        ymd = base.replace("-", "")
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        evs = data if isinstance(data, list) else list(data.values())
        flat = []
        for v in evs:
            if isinstance(v, list):
                flat += v
            elif isinstance(v, dict):
                flat.append(v)
        for e in flat:
            if not isinstance(e, dict) or e.get("type") != "order":
                continue
            code = str(e.get("code", "")).lstrip("A").strip()
            if not code:
                continue
            out.setdefault(code, []).append((
                ymd,
                str(e.get("side", "")).lower(),
                e.get("acct"),
                str(e.get("reason", "")),
            ))
    return out


def _load_kr_pine_fills():
    """code → [(ymd, side), ...]  한국 TR 추세/저점셋 fill(acct=1887, strategy=kr_pine_buy|kr_pine_lowbuy).
    strategy_tag_1887 는 매수시점에만 태깅되므로(매도는 자체청산이라 재태깅 없음) 이 매칭은
    buy_ymd(매수일)에만 유효 — resolve_ledger 에서 buy_ymd 매칭 전용으로 쓴다."""
    out = {}
    for path in glob.glob(os.path.join(INTRADAY_DIR, "*.json")):
        base = os.path.basename(path)[:-5]
        ymd = base.replace("-", "")
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        evs = data if isinstance(data, list) else list(data.values())
        flat = []
        for v in evs:
            if isinstance(v, list):
                flat += v
            elif isinstance(v, dict):
                flat.append(v)
        for e in flat:
            if not isinstance(e, dict) or e.get("type") != "fill":
                continue
            if str(e.get("acct")) != "1887":
                continue
            label = KR_PINE_LABELS.get(e.get("strategy"))
            if not label:
                continue
            code = str(e.get("code", "")).lstrip("A").strip()
            if not code:
                continue
            out.setdefault(code, []).append((ymd, str(e.get("side", "")).lower(), label))
    return out


def _load_tj1887():
    """1887 master 주문로그.
      buys  : ticker → [(ymd, flag, order_type), ...]  (BUY 만)
      seen  : {ticker}  (BUY/SELL 무관 — 1887 봇이 손댄 종목. 매수봇 미상 시 주도주 fallback용)
    """
    buys, seen = {}, set()
    if not os.path.exists(TJ_1887):
        return buys, seen
    with open(TJ_1887, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = str(row.get("ticker", "")).lstrip("A").strip()
            if not code:
                continue
            seen.add(code)
            if row.get("side") != "BUY":
                continue
            ymd = str(row.get("date", "")).replace("-", "").strip()
            buys.setdefault(code, []).append((ymd, row.get("flag", ""), row.get("order_type", "")))
    return buys, seen


def _load_log8042():
    """8042 fallback: {(ticker, ymd)} presence."""
    out = set()
    if not os.path.exists(LOG_8042):
        return out
    with open(LOG_8042, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = str(row.get("Ticker", "")).lstrip("A").strip()
            ymd = str(row.get("Date", "")).replace("-", "").strip()
            if code and ymd:
                out.add((code, ymd))
    return out


# ─────────────────────── 라벨 변환 ───────────────────────
def _acct_to_label(acct, reason):
    a = (acct or "").strip()
    rs = reason or ""
    if a.endswith("CHU"):
        return "2x"
    if a == "8042":
        return "고저"
    if a == "8042SH":
        return "TRAlert"
    # 1887 / None 계열
    if rs.startswith("저") or "저2" in rs or "저 매수" in rs:
        return "저점"
    if "로켓" in rs or "rocket" in rs.lower():
        return "로켓"
    if "TV" in rs:
        return "TRAlert"
    return "주도주"


def _flag_to_label(flag, order_type):
    ot = order_type or ""
    if flag == "3" or "TV" in ot:
        return "TRAlert"
    if ot.startswith("저"):
        return "저점"
    if "로켓" in ot or "rocket" in ot.lower():
        return "로켓"
    return "주도주"   # flag 1/2/4 = 주도주·네이버눌림·장후 (모두 master)


def _acct_family(acct, acct_file):
    """intraday acct 가 이 계좌(1887/8042)에 속하는지 — 동명 종목 교차오염 방지."""
    a = acct or ""
    if acct_file == "8042":
        return a.endswith("CHU") or a.startswith("8042")
    return a == "1887" or a == "" or acct is None


def resolve_ledger(acct_file, ticker, buy_ymd, sell_ymd, intraday, tj1887, tj1887_seen, log8042,
                    kr_pine=None):
    # 0) 한국 TR 추세/저점셋 — 매수시점 strategy 태그 직접 매칭(가장 확실한 소스, buy_ymd 전용)
    if acct_file == "1887" and kr_pine:
        for (ymd, side, label) in kr_pine.get(ticker, []):
            if ymd == buy_ymd and side == "buy":
                return label

    # 1) intraday 주문이벤트 (해당 계좌 family 만) — 매수 이벤트가 봇을 정의
    evs = [e for e in intraday.get(ticker, []) if _acct_family(e[2], acct_file)]
    cand = None
    for want in (buy_ymd, sell_ymd):
        if not want:
            continue
        for (ymd, side, acct, reason) in evs:
            if ymd == want and side == "buy":
                cand = (acct, reason)
                break
        if cand:
            break
    if not cand:
        for want in (buy_ymd, sell_ymd):
            if not want:
                continue
            for (ymd, side, acct, reason) in evs:
                if ymd == want:
                    cand = (acct, reason)
                    break
            if cand:
                break
    if not cand and evs:
        ymd, side, acct, reason = sorted(evs)[-1]
        cand = (acct, reason)
    if cand:
        return _acct_to_label(*cand)

    # 2) 1887 master 주문로그 flag
    if acct_file == "1887":
        bl = tj1887.get(ticker, [])
        c = None
        if buy_ymd:
            for (ymd, flag, ot) in bl:
                if ymd == buy_ymd:
                    c = (flag, ot)
                    break
        if not c and bl:
            ymd, flag, ot = sorted(bl)[-1]
            c = (flag, ot)
        if c:
            return _flag_to_label(*c)
        # 매수봇 미상이나 1887 봇이 손댄 흔적(매수/자동매도)이 있으면 master(주도주)로 귀속.
        # 매수가 로그 보관기간(약 12일) 이전인 스윙 종목이 '수동'으로 오기되는 것 방지.
        if ticker in tj1887_seen:
            return "주도주"

    # 3) 8042 로그 presence fallback (봇 구분 불가 → 고저로 표기)
    if acct_file == "8042":
        if (ticker, buy_ymd) in log8042 or (ticker, sell_ymd) in log8042:
            return "고저"

    return "수동"


# ─────────────────── 매매일지(실현손익) 로드 ───────────────────
def _load_trades(path, acct_file, year, intraday, tj1887, tj1887_seen, log8042, kr_pine=None):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            sell_d = (r.get("매도날짜") or "").strip()
            pnl_s = (r.get("총실현손익") or "").strip().replace(",", "")
            if not sell_d or pnl_s == "":
                continue                       # 미실현(보유) 행 제외
            try:
                pnl = int(round(float(pnl_s)))
            except ValueError:
                continue
            sell_ymd = _to_full_ymd(sell_d, year)
            buy_ymd = _to_full_ymd(r.get("날짜", ""), year)
            ticker = (r.get("티커") or "").strip()
            name = (r.get("종목명") or "").strip()
            ret_s = (r.get("수익률(%)") or "").strip()
            try:
                ret = float(ret_s)
            except ValueError:
                ret = None
            ledger = resolve_ledger(acct_file, ticker, buy_ymd, sell_ymd,
                                    intraday, tj1887, tj1887_seen, log8042, kr_pine)
            gubun = "익절" if pnl > 0 else ("손절" if pnl < 0 else "청산")
            rows.append({
                "sell_ymd": sell_ymd, "acct": acct_file, "gubun": gubun,
                "ledger": ledger, "ticker": ticker, "name": name,
                "ret": ret, "pnl": pnl,
            })
    return rows


# ─────────────────────── HTML 렌더 ───────────────────────
def _fmt_date(ymd):
    if len(ymd) == 8:
        return f"{int(ymd[4:6])}/{int(ymd[6:8])}"
    return ymd


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_html(rows, day_count):
    GU_COLOR = {"익절": "#E63946", "손절": "#3A86FF", "청산": "#9AA0A6"}
    GU_SHORT = {"익절": "익", "손절": "손", "청산": "청"}   # 구분 칼럼 짧은 라벨

    body = []
    for r in rows:
        ret = r["ret"]
        ret_v = "" if ret is None else f"{ret:.2f}"
        ret_disp = "-" if ret is None else (f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%")
        ret_col = "#9AA0A6" if ret is None else ("#E63946" if ret >= 0 else "#3A86FF")
        pnl = r["pnl"]
        pnl_disp = f"+{pnl:,}" if pnl > 0 else f"{pnl:,}"
        pnl_col = "#E63946" if pnl > 0 else ("#3A86FF" if pnl < 0 else "#9AA0A6")
        acct_col = ACCT_COLORS.get(r["acct"], "#9AA0A6")
        led_col = LEDGER_COLORS.get(r["ledger"], "#9AA0A6")
        chart = r.get("chart", "")
        nm_attr = f' data-chart="{chart}"' if chart else ""
        body.append(f"""    <tr>
      <td data-v="{r['sell_ymd']}" class="c-date">{_fmt_date(r['sell_ymd'])}</td>
      <td data-v="{r['acct']}" class="c-acct" style="color:{acct_col}">{r['acct']}</td>
      <td data-v="{r['gubun']}"><span class="badge" style="background:{GU_COLOR[r['gubun']]}">{GU_SHORT.get(r['gubun'], r['gubun'])}</span></td>
      <td data-v="{r['ledger']}"><span class="badge" style="background:{led_col}">{_esc(r['ledger'])}</span></td>
      <td data-v="{r['ticker']}" class="c-tk">{_esc(r['ticker'])}</td>
      <td data-v="{_esc(r['name'])}" class="c-nm"{nm_attr}>{_esc(r['name'])}</td>
      <td data-v="{ret_v}" class="c-num" style="color:{ret_col}">{ret_disp}</td>
      <td data-v="{pnl}" class="c-num" style="color:{pnl_col}">{pnl_disp}</td>
    </tr>""")

    if not body:
        body_html = '<tr><td colspan="8" class="empty">최근 거래 내역이 없습니다.</td></tr>'
    else:
        body_html = "\n".join(body)

    # 당일(가장 최근 매도일) 각 계좌 실현손익 — 2거래일 합산이 아니라 당일 1일치만
    today_ymd = max((r["sell_ymd"] for r in rows if r["sell_ymd"]), default="")
    acct_today = {"1887": 0, "8042": 0}
    for r in rows:
        if r["sell_ymd"] == today_ymd and r["acct"] in acct_today:
            acct_today[r["acct"]] += r["pnl"]

    def _pnl_won(v):
        col = "#E63946" if v > 0 else ("#3A86FF" if v < 0 else "#666")
        disp = f"+{v:,}" if v > 0 else f"{v:,}"
        return f'<b style="color:{col};font-weight:700">{disp}원</b>'

    today_disp = _fmt_date(today_ymd) if today_ymd else "-"
    pnl_summary = (f'<span style="color:#999">{today_disp} 당일</span> &nbsp; '
                   f'1887: {_pnl_won(acct_today["1887"])} &nbsp;,&nbsp; '
                   f'8042: {_pnl_won(acct_today["8042"])}')

    updated = datetime.now().strftime("%Y.%m.%d %H:%M")
    total = sum(r["pnl"] for r in rows)
    total_col = "#E63946" if total > 0 else ("#3A86FF" if total < 0 else "#666")
    total_disp = f"+{total:,}" if total > 0 else f"{total:,}"

    # 컬럼: 0날짜 1계좌 2구분 3장부 4티커 5종목명 6수익률 7실현손익
    headers = [
        ("날짜", "str"), ("계좌", "str"), ("구분", "str"), ("장부", "str"),
        ("티커", "str"), ("종목명", "str"), ("수익률", "num"), ("실현손익", "num"),
    ]
    ths = "".join(
        f'<th data-type="{t}" onclick="sortTable(this,{i})">{h}</th>'
        for i, (h, t) in enumerate(headers)
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>매매일지 요약</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f5f5f7;color:#1d1d1f;font-family:'Noto Sans KR',sans-serif;padding:22px 16px}}
.wrap{{max-width:860px;margin:0}}
.title{{display:flex;align-items:baseline;gap:12px;margin-bottom:4px}}
.title h1{{font-size:19px;font-weight:700}}
.title .mark{{color:#3A86FF;font-weight:700}}
.sub{{font-size:12px;color:#999;margin-bottom:16px}}
.sub b{{color:#666;font-weight:500}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e6e6e6;
       border-radius:10px;overflow:hidden;font-size:13px}}
thead th{{background:#fafafa;color:#555;font-weight:700;font-size:12px;text-align:center;
         padding:11px 8px;border-bottom:1px solid #ececec;cursor:pointer;user-select:none;
         white-space:nowrap}}
thead th:hover{{background:#f0f4ff;color:#3A86FF}}
tbody td{{padding:10px 8px;text-align:center;border-bottom:1px solid #f3f3f3;white-space:nowrap}}
tbody tr:last-child td{{border-bottom:none}}
tbody tr:hover{{background:#fafbff}}
.badge{{display:inline-block;color:#fff;font-size:11px;font-weight:700;
        padding:2px 9px;border-radius:20px;min-width:42px}}
.c-date{{font-family:'JetBrains Mono',monospace;font-weight:700;color:#333}}
.c-tk{{font-family:'JetBrains Mono',monospace;color:#888;font-size:12px}}
.c-acct{{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:12px}}
.c-nm{{text-align:left;font-weight:500;max-width:200px;overflow:hidden;text-overflow:ellipsis}}
.c-nm[data-chart]{{cursor:pointer;text-decoration:underline dotted #c4c4c4;text-underline-offset:3px}}
.c-nm[data-chart]:hover{{color:#3A86FF}}
#jtbl:focus{{outline:none}}
tbody tr.cur{{background:#eef4ff}}
.c-num{{font-family:'JetBrains Mono',monospace;font-weight:700;text-align:right;padding-right:14px}}
.empty{{padding:34px;color:#aaa;font-size:13px}}
/* 차트 페이지를 0.8배 축소해 통째로 보여줌. 5분봉(고저·주도주) 보드는 2거래일치를 줌인 없이
   읽으려면 폭이 2배 필요 → iframe 폭 1420px(=710×2)로 잡고 0.8배 → 박스 1136px.
   (일봉 rocket 차트는 같은 폭에서 가로 여백이 늘 뿐 잘리지 않음) */
#chart-preview{{position:fixed;display:none;z-index:9999;width:1136px;height:680px;background:#fff;
  border:1px solid #d8d8d8;border-radius:10px;box-shadow:0 12px 34px rgba(0,0,0,0.20);overflow:hidden}}
#chart-preview iframe{{width:1420px;height:850px;border:none;display:block;background:#fff;
  transform:scale(0.8);transform-origin:0 0}}
@media (max-width:1024px){{#chart-preview{{display:none!important}}}}
.foot{{margin-top:14px;font-size:11px;color:#bbb;text-align:right}}
.total{{margin-top:12px;text-align:right;font-size:13px;color:#666}}
.total b{{font-family:'JetBrains Mono',monospace;font-size:15px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="title"><span class="mark">■</span><h1>매매일지</h1></div>
  <div class="sub">{pnl_summary}</div>
  <table id="jtbl" tabindex="-1">
    <thead><tr>{ths}</tr></thead>
    <tbody>
{body_html}
    </tbody>
  </table>
  <div class="total">합계 실현손익 &nbsp;<b style="color:{total_col}">{total_disp}</b> 원</div>
  <div class="foot">journal_summary.py · {updated}</div>
</div>
<div id="chart-preview"><iframe id="chart-preview-frame" src="about:blank" scrolling="no"></iframe></div>
<script>
// ── 종목명 hover 차트 미리보기 + D/S 행 이동 ──────────────────────
(function(){{
  var tbl = document.getElementById('jtbl');
  var tb  = tbl.tBodies[0];
  var pv  = document.getElementById('chart-preview');
  var pvf = document.getElementById('chart-preview-frame');
  var cur = -1, hideTimer = null;

  // 이 게시판은 dashboard → trade_chart_list → (이 요약) 3중 iframe 안에서 열린다.
  // 메뉴 클릭으로 보드를 열면 포커스가 최상위 dashboard에 남아 D/S keydown이 여기까지
  // 못 온다. 표 위로 마우스가 오면 이 문서로 포커스를 끌어와 첫 호버부터 단축키가 먹게 한다.
  // (입력창 등에 이미 포커스가 있으면 뺏지 않는다.)
  function grabFocus(){{
    try {{
      var a = document.activeElement;
      if (a === document.body || a === null || a === document.documentElement) {{
        tbl.focus({{preventScroll: true}});
      }}
    }} catch (e) {{}}
  }}
  tbl.addEventListener('mouseenter', grabFocus);

  function dataRows(){{
    return Array.prototype.slice.call(tb.rows).filter(function(r){{ return r.cells.length === 8; }});
  }}
  function chartOf(tr){{ var c = tr.cells[5]; return c ? (c.getAttribute('data-chart') || '') : ''; }}

  function place(rect){{
    var w = pv.offsetWidth || 560, h = pv.offsetHeight || 420;
    var vw = window.innerWidth, vh = window.innerHeight;
    var left = rect.right + 14;                       // 종목명 셀 오른쪽
    if (left + w > vw - 8) left = rect.left - w - 14; // 넘치면 왼쪽
    if (left < 8) left = Math.max(8, (vw - w) / 2);   // 그래도 넘치면 중앙
    var top = rect.top + rect.height / 2 - h / 2;
    if (top < 8) top = 8;
    if (top + h > vh - 8) top = Math.max(8, vh - h - 8);
    pv.style.left = left + 'px';
    pv.style.top  = top + 'px';
  }}
  function showFor(tr){{
    clearTimeout(hideTimer);
    var url = chartOf(tr);
    if (!url) {{ hide(); return; }}
    if (pvf.getAttribute('src') !== url) pvf.setAttribute('src', url);
    // 행 전체가 아니라 '종목명 셀' 기준으로 띄워 종목명 바로 우측에 나오게 한다.
    var anchor = tr.cells[5] || tr;
    place(anchor.getBoundingClientRect());
    pv.style.display = 'block';
  }}
  function hide(){{ pv.style.display = 'none'; }}
  function scheduleHide(){{ hideTimer = setTimeout(hide, 140); }}

  function setCur(i){{
    cur = i;
    var rs = dataRows();
    rs.forEach(function(tr, k){{
      if (k === i) tr.classList.add('cur'); else tr.classList.remove('cur');
    }});
  }}

  // hover (종목명 셀)
  dataRows().forEach(function(tr, i){{
    var nm = tr.cells[5];
    if (!nm || !nm.getAttribute('data-chart')) return;
    nm.addEventListener('mouseenter', function(){{ grabFocus(); setCur(i); showFor(tr); }});
  }});
  tb.addEventListener('mouseleave', scheduleHide);
  pv.addEventListener('mouseenter', function(){{ clearTimeout(hideTimer); }});
  pv.addEventListener('mouseleave', scheduleHide);

  // D/S(또는 ↓/↑) 행 이동 — 부모 게시판에서도 호출(window.journalNav)
  window.journalNav = function(dir){{
    var rs = dataRows();
    if (!rs.length) return;
    if (cur < 0) setCur(dir > 0 ? 0 : rs.length - 1);
    else setCur(Math.min(rs.length - 1, Math.max(0, cur + dir)));
    var tr = dataRows()[cur];
    if (tr) {{ tr.scrollIntoView({{block: 'nearest'}}); showFor(tr); }}
  }};

  // iframe 자체가 포커스됐을 때(표 클릭 등) 직접 처리
  document.addEventListener('keydown', function(e){{
    var t = e.target, tag = t && t.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (t && t.isContentEditable)) return;
    var k = e.key, dir = 0;
    if (k === 's' || k === 'S' || k === 'ArrowUp') dir = -1;
    else if (k === 'd' || k === 'D' || k === 'ArrowDown') dir = 1;
    if (!dir) return;
    e.preventDefault();
    window.journalNav(dir);
  }});
}})();

// 컬럼 클릭 정렬. 화살표 표시 없음. 페이지를 새로 열면(게시판 재진입) 초기 정렬로 리셋.
function sortTable(th, col){{
  var tbl = document.getElementById('jtbl');
  var tb  = tbl.tBodies[0];
  var rows = Array.prototype.slice.call(tb.rows).filter(function(r){{return r.cells.length===8;}});
  if(!rows.length) return;
  var type = th.getAttribute('data-type');
  var prevCol = tbl.getAttribute('data-col');
  var prevDir = tbl.getAttribute('data-dir');
  var dir = (prevCol == String(col) && prevDir == 'asc') ? 'desc' : 'asc';
  rows.sort(function(a,b){{
    var x = a.cells[col].getAttribute('data-v');
    var y = b.cells[col].getAttribute('data-v');
    if(type === 'num'){{
      x = parseFloat(x); y = parseFloat(y);
      if(isNaN(x)) x = -Infinity; if(isNaN(y)) y = -Infinity;
      return dir === 'asc' ? x - y : y - x;
    }}
    x = x || ''; y = y || '';
    if(x < y) return dir === 'asc' ? -1 : 1;
    if(x > y) return dir === 'asc' ? 1 : -1;
    return 0;
  }});
  rows.forEach(function(r){{ tb.appendChild(r); }});
  tbl.setAttribute('data-col', col);
  tbl.setAttribute('data-dir', dir);
}}
</script>
</body>
</html>"""


def build_summary_file(output_path, charts_dir=None):
    """매매요약 HTML 생성 후 output_path 에 저장. (노출 거래일 수, 건수) 반환.
    charts_dir: report-us/charts 경로. 종목명 hover/단축키 차트 미리보기 매핑용."""
    year = datetime.now().year
    intraday = _load_intraday()
    tj1887, tj1887_seen = _load_tj1887()
    log8042 = _load_log8042()
    kr_pine = _load_kr_pine_fills()

    rows = _load_trades(JOURNAL_1887, "1887", year, intraday, tj1887, tj1887_seen, log8042, kr_pine)
    rows += _load_trades(JOURNAL_8042, "8042", year, intraday, tj1887, tj1887_seen, log8042)

    # 2x(레버리지 추세봇)는 "요약-단타 게시판"에 따로 표시 → 매매일지에선 제외(당일 손익합계 포함).
    rows = [r for r in rows if r["ledger"] != "2x"]

    # 종목명 → 차트 URL. 장부 전용 보드 차트(고저/주도주=5분봉, 로켓=일봉) 우선 → 없으면 20일 일봉.
    for r in rows:
        r["chart"] = _chart_url(charts_dir, r["name"], r["acct"], r["sell_ymd"],
                                ledger=r["ledger"], code=r["ticker"])

    # 최근 N거래일(매도일) 만
    distinct = sorted({r["sell_ymd"] for r in rows if r["sell_ymd"]}, reverse=True)
    keep = set(distinct[:RECENT_DAYS])
    rows = [r for r in rows if r["sell_ymd"] in keep]

    # 기본 정렬: 매도일 내림차순(당일 위) → 계좌 → 실현손익 내림차순
    rows.sort(key=lambda r: (r["sell_ymd"], r["acct"], r["pnl"]), reverse=True)

    html = build_html(rows, len(keep))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return len(keep), len(rows)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_journal_summary.html")
    days, n = build_summary_file(out)
    print(f"[OK] {out}  ({days}거래일 / {n}건)")
