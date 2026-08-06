# -*- coding: utf-8 -*-
"""
make_danta_journal.py ── 매매일지 게시판 (거래대금 하위게시판)
─────────────────────────────────────────────────────────────────
0_low_high_5min_danta.py(5분 단타봇)가 intraday_signals/YYYY-MM-DD.json 에
남긴 체결(fill) 이벤트만 모아 최근 5일치 매매일지 테이블 + V2 차트 팝업 생성.

- 입력 : D:\\py\\0order\\intraday_signals\\*.json  (봇이 영구 누적, git 동기화)
- 출력 : report-us/danta_journal.html  (+ danta_journal_data.json 디버그용)
- 차트 : chart_popup_v2.build_chart_popup(codes, trade_marks=...) 재사용.
         B(진입, 캔들아래 검정박스) / S(청산, 캔들위 파란박스) 마커 추가 표시 — 식별 거리(투명 더미 2칸) 확보.
- 구분 : lowhigh = 5분단타봇. (추후 leader 등 다른 전략 fill 을 합치면 구분값으로 구별)

실행: python -X utf8 make_danta_journal.py   (cwd: D:\\py\\report-us)
"""
import os
import re
import sys
import glob
import json
import html as html_mod
import time
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chart_popup_v2 import build_chart_popup, _kiwoom_token, KIWOOM_DOMAIN

BASE_DIR   = r"D:\py"
SIGNAL_DIR = os.path.join(BASE_DIR, "0order", "intraday_signals")
OUT_HTML   = os.path.join(BASE_DIR, "report-us", "danta_journal.html")
OUT_JSON   = os.path.join(BASE_DIR, "report-us", "danta_journal_data.json")
DAYS_KEEP  = 5          # 최근 5일치만 표시
NAME_LEN   = 7          # 종목명 최대 7글자

# ETF 브랜드 접두어 제거 (holdings.html getShortName 과 동일 목록) — 무엇을 샀는지 식별용
ETF_PREFIXES = ('KODEX ', 'TIGER ', 'PLUS ', 'KINDEX ', 'ARIRANG ', 'HANARO ',
                'ACE ', 'SOL ', 'KoAct ', 'KB스타 ', 'KIWOON ', 'TIME ', 'RISE ',
                'KB STAR ', 'KBSTAR ', '키움 ')


def short_name(raw):
    """ETF 접두어 제거 후 NAME_LEN 글자로 컷. 주식은 그대로 컷."""
    if not raw:
        return ""
    for p in ETF_PREFIXES:
        if raw.startswith(p):
            raw = raw[len(p):]
            break
    return raw[:NAME_LEN]


# ───────── fill 이벤트 수집 ─────────
def load_fills():
    """intraday_signals 전체 파일 시간순 → fill 이벤트 리스트.
    (포지션 평단 재구성을 위해 전체를 읽고, 표시는 최근 5일만)

    교차파일 중복제거: 같은 체결(acct,ord_no,side,qty,price,tm)이 여러 날짜 파일에
    중복 기록돼도(비거래일 sync 재조회 등) 최초 1건만 채택. 봇 분할체결은
    qty/price/tm 이 달라 키가 달라지므로 보존된다."""
    fills_by_key = {}
    for path in sorted(glob.glob(os.path.join(SIGNAL_DIR, "*.json"))):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.json$", os.path.basename(path))
        if not m:
            continue
        day = m.group(1)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  ⚠ {os.path.basename(path)} 읽기 실패: {e}")
            continue
        for ev in data.get("events", []):
            if ev.get("type") != "fill":
                continue
            qty   = int(ev.get("qty", 0) or 0)
            price = int(ev.get("price", 0) or 0)
            if qty <= 0 or price <= 0:
                continue
            tm = str(ev.get("tm", "") or "").strip()
            ono = str(ev.get("ord_no", "") or "").strip()
            # 체결시각: tm(HHMMSS, ka10076) 우선, 없으면 logged_at(HH:MM:SS 감지시각)
            if len(tm) >= 4 and tm.isdigit():
                hhmm = f"{tm[0:2]}:{tm[2:4]}"
            else:
                hhmm = str(ev.get("logged_at", ""))[:5] or "09:00"
            fill = {
                "date":     day,
                "acct":     str(ev.get("acct", "8042")),
                "code":     str(ev.get("code", "")).zfill(6),
                "name":     ev.get("name", ""),
                "side":     ev.get("side", ""),
                "qty":      qty,
                "price":    price,
                "hhmm":     hhmm,
                "ord_no":   ono,
                "strategy": ev.get("strategy", "lowhigh"),
                "origin":   ev.get("origin", "bot"),
            }
            if ono:
                dk = (fill["acct"], ono, fill["side"], qty, price, tm)
            else:
                dk = (fill["acct"], day, fill["code"], fill["side"], qty, price, tm)
            prev = fills_by_key.get(dk)
            if prev is None or fill["date"] >= prev["date"]:
                fills_by_key[dk] = fill
    return sorted(fills_by_key.values(),
                  key=lambda x: (x["date"], x["hhmm"], x["acct"], x["ord_no"], x["code"]))


def load_stop_info():
    """봇 강제손절(청산) 식별용. fill 엔 사유가 없어 order/signal 이벤트에서 추출.
      - stop_ords : reason 이 '손절...'인 매도 order 의 ord_no 집합
      - stop_days : signal=='stoploss' 가 뜬 (date, code) 집합 (ord_no 누락 대비 폴백)
    -5% 자동손절(0_low_high_5min_danta.py)만 해당. 수동/외부 매도는 사유 없어 미포함."""
    stop_ords, stop_days = set(), set()
    for path in sorted(glob.glob(os.path.join(SIGNAL_DIR, "*.json"))):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.json$", os.path.basename(path))
        if not m:
            continue
        day = m.group(1)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for ev in data.get("events", []):
            t = ev.get("type")
            if t == "order" and ev.get("side") == "sell" \
                    and str(ev.get("reason", "")).strip().startswith("손절"):
                ono = str(ev.get("ord_no", "") or "").strip()
                if ono:
                    stop_ords.add(ono)
            elif t == "signal" and ev.get("signal") == "stoploss":
                stop_days.add((day, str(ev.get("code", "")).zfill(6)))
    return stop_ords, stop_days


def classify_result(row, stop_ords, stop_days):
    """청산완료 행 → '익절'/'손절'/'청산'. 청산=봇 -5% 자동손절(음수 실현 한정)."""
    if not row["sells"]:
        return ""
    realized = row["realized"]
    is_stop = (row["date"], row["code"]) in stop_days \
        or any(s.get("ord_no") in stop_ords for s in row["sells"] if s.get("ord_no"))
    if is_stop and realized < 0:
        return "청산"
    return "익절" if realized >= 0 else "손절"


# ───────── 포지션 재구성 → 일자별 행 ─────────
def build_rows(fills):
    """시간순 fill → (date, acct, code) 행 dict.
    positions: 전 기간 누적 평단/수량 (장부와 동일 로직)."""
    positions = {}   # (acct,code) -> {"qty","avg"}
    rows = {}        # (date,acct,code) -> row
    for ev in fills:
        key  = (ev["acct"], ev["code"])
        rkey = (ev["date"], ev["acct"], ev["code"])
        row = rows.setdefault(rkey, {
            "date": ev["date"], "acct": ev["acct"], "code": ev["code"],
            "name": ev["name"], "strategy": ev["strategy"],
            "buys": [], "sells": [], "realized": 0, "basis": 0, "remain": 0,
        })
        pos = positions.get(key)
        if ev["side"] == "buy":
            if pos:
                tot = pos["qty"] * pos["avg"] + ev["qty"] * ev["price"]
                pos["qty"] += ev["qty"]
                pos["avg"] = tot / pos["qty"]
            else:
                pos = positions[key] = {"qty": ev["qty"], "avg": float(ev["price"])}
            row["buys"].append({"tm": ev["hhmm"], "qty": ev["qty"], "price": ev["price"]})
        else:
            avg = pos["avg"] if pos else float(ev["price"])   # 장부外 매도: pnl 0 처리
            row["realized"] += round((ev["price"] - avg) * ev["qty"])
            row["basis"]    += round(avg * ev["qty"])
            if pos:
                pos["qty"] -= ev["qty"]
                if pos["qty"] <= 0:
                    del positions[key]
            row["sells"].append({"tm": ev["hhmm"], "qty": ev["qty"], "price": ev["price"],
                                 "ord_no": ev.get("ord_no", "")})
        row["remain"] = positions.get(key, {}).get("qty", 0)
        row["avg"]    = round(positions.get(key, {}).get("avg", 0))
    return rows, positions


# ───────── 현재가 (보유중 평가용, ka10001) ─────────
def fetch_cur_prices(codes):
    out = {}
    if not codes:
        return out
    try:
        token = _kiwoom_token()
    except Exception as e:
        print(f"  ⚠ 현재가 토큰 실패(평가 생략): {e}")
        return out
    for c in codes:
        try:
            r = requests.post(KIWOOM_DOMAIN + "/api/dostk/stkinfo",
                headers={"api-id": "ka10001", "Authorization": f"Bearer {token}",
                         "Content-Type": "application/json;charset=UTF-8"},
                data=json.dumps({"stk_cd": c}), timeout=10)
            d = r.json()
            if d.get("return_code", -1) == 0:
                cur = d.get("cur_prc", "")      # 봇 get_current_price 와 동일 키
                if cur:
                    out[c] = abs(int(float(str(cur).replace(",", ""))))
        except Exception as e:
            print(f"  ⚠ 현재가 {c}: {e}")
        time.sleep(0.25)
    return out


# ───────── trade_marks (B/S, 5분봉 시작시각으로 스냅) ─────────
def bar_label(date, hhmm):
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except (ValueError, IndexError):
        h, m = 9, 0
    m = (m // 5) * 5
    return f"{date} {h:02d}:{m:02d}"


def build_trade_marks(rows_kept):
    marks = {}
    for row in rows_kept:
        arr = marks.setdefault(row["code"], [])
        for b in row["buys"]:
            arr.append({"t": bar_label(row["date"], b["tm"]), "s": "B"})
        for s in row["sells"]:
            arr.append({"t": bar_label(row["date"], s["tm"]), "s": "S"})
    return marks


def _wavg(items):
    q = sum(i["qty"] for i in items)
    return round(sum(i["qty"] * i["price"] for i in items) / q) if q else None


def build_daily_trades(rows_kept):
    """일봉 화살표용: {code:[{t:'YYYY-MM-DD', b:진입가|null, s:청산가|null}]}.
    그날 매수 가중평균=진입가, 매도 가중평균=청산가 (일봉 1캔들에 끝점 정확히 부착)."""
    out = {}
    for row in rows_kept:
        out.setdefault(row["code"], []).append({
            "t": row["date"],
            "b": _wavg(row["buys"]) if row["buys"] else None,
            "s": _wavg(row["sells"]) if row["sells"] else None,
        })
    return out


def build_result_summary(rows_kept, stop_ords, stop_days):
    """헤더 라벨용: {code:{'익':n,'손':n,'청':n}} (청산완료 행만 집계)."""
    out = {}
    for row in rows_kept:
        if not row["sells"]:
            continue
        res = classify_result(row, stop_ords, stop_days)
        key = {"익절": "익", "손절": "손", "청산": "청"}.get(res)
        if not key:
            continue
        out.setdefault(row["code"], {"익": 0, "손": 0, "청": 0})[key] += 1
    return out


def result_cell(res):
    color = {"익절": "#2e7d32", "손절": "#ff5252", "청산": "#9e9e9e"}.get(res, "#555")
    return f'<td style="color:{color};font-weight:bold;">{res or "—"}</td>'


# ───────── HTML ─────────
def fmt_date(iso):
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


def pnl_html(v):
    color = "#d32f2f" if v > 0 else ("#1565c0" if v < 0 else "#555")
    return f'<span style="color:{color};font-weight:bold;">{v:+,}</span>'


def pct_html(v):
    color = "#d32f2f" if v > 0 else ("#1565c0" if v < 0 else "#555")
    return f'<span style="color:{color};font-weight:bold;">{v:+.2f}%</span>'


def build_open_rows(rows_kept, cur_prices, still_open):
    """보유중(매도없음 + 잔량 존재) 행 → HTML tr 들."""
    out = []
    target = [r for r in rows_kept
              if not r["sells"] and (r["acct"], r["code"]) in still_open and r["buys"]]
    for row in sorted(target, key=lambda r: (r["date"], r["acct"], r["code"]), reverse=True):
        code, name = row["code"], short_name(row["name"])
        if code in cur_prices:
            bq = sum(b["qty"] for b in row["buys"])
            bavg = sum(b["qty"] * b["price"] for b in row["buys"]) / bq
            unreal = round((cur_prices[code] - bavg) * bq)
            ret = (cur_prices[code] - bavg) / bavg * 100
            pct_cell, pnl_cell = pct_html(ret), pnl_html(unreal)
        else:
            pct_cell, pnl_cell = "—", "—"
        out.append(
            f'<tr>'
            f'<td>{fmt_date(row["date"])}</td>'
            f'<td class="code-col" data-code="{code}" data-name="{html_mod.escape(row["name"])}">{code}</td>'
            f'<td>{html_mod.escape(name)}</td>'
            f'<td>{row["remain"]}</td>'
            f'<td>{pct_cell}</td>'
            f'<td>{pnl_cell}</td>'
            f'<td class="strat-cell">{html_mod.escape(row["strategy"])}</td>'
            f'<td>{html_mod.escape(row["acct"])}</td>'
            f'</tr>')
    return "".join(out)


def build_closed_rows(rows_kept, stop_ords, stop_days):
    """청산 완료(매도 있음) 행 → HTML tr 들. 결과(익절/손절/청산) + 매수/매도시각 컬럼 포함."""
    out = []
    target = [r for r in rows_kept if r["sells"]]
    for row in sorted(target, key=lambda r: (r["date"], r["acct"], r["code"]), reverse=True):
        code, name = row["code"], short_name(row["name"])
        ret = row["realized"] / row["basis"] * 100 if row["basis"] else 0.0
        pct_cell, pnl_cell = pct_html(ret), pnl_html(row["realized"])
        res_cell = result_cell(classify_result(row, stop_ords, stop_days))
        buy_tm  = row["buys"][0]["tm"]  if row["buys"]  else "—"
        sell_tm = row["sells"][-1]["tm"] if row["sells"] else "—"
        tm_cell = f"{buy_tm} / {sell_tm}"
        out.append(
            f'<tr>'
            f'<td>{fmt_date(row["date"])}</td>'
            f'<td class="code-col" data-code="{code}" data-name="{html_mod.escape(row["name"])}">{code}</td>'
            f'<td>{html_mod.escape(name)}</td>'
            f'{res_cell}'
            f'<td class="time-cell">{tm_cell}</td>'
            f'<td>{pct_cell}</td>'
            f'<td>{pnl_cell}</td>'
            f'<td class="strat-cell">{html_mod.escape(row["strategy"])}</td>'
            f'<td>{html_mod.escape(row["acct"])}</td>'
            f'</tr>')
    return "".join(out)


def main():
    print("=" * 60)
    print("  매매일지 게시판 생성 (2773 단타 + 8042 5분단타 + 1887 주도주 · 최근 5일)")
    print("=" * 60)
    # 계좌 당일체결을 신호파일에 병합(읽기전용 조회). 실패해도 무시.
    # 8042=단타 한정 계좌진실(수동매도 반영), 1887=주도주 계좌단위 전체.
    sys.path.insert(0, os.path.join(BASE_DIR, "0order"))
    try:
        import sync_8042_fills
        sync_8042_fills.main()
    except Exception as e:
        print(f"  ⚠ 8042 동기화 생략: {e}")
    try:
        import sync_8042chu_fills          # 추세봇(8042CHU) 계좌진실 — 봇이 못 잡은 체결 자가치유
        sync_8042chu_fills.main()
    except Exception as e:
        print(f"  ⚠ 8042CHU 동기화 생략: {e}")
    try:
        import sync_1887_fills
        sync_1887_fills.main()
    except Exception as e:
        print(f"  ⚠ 1887 동기화 생략: {e}")
    try:
        import sync_allone_etf_fills         # allone 8042 통합ETF(국내+미국상장) → acct=8042ETF
        sync_allone_etf_fills.main()
    except Exception as e:
        print(f"  ⚠ 통합ETF 동기화 생략: {e}")
    try:
        import sync_us_1887_fills            # 미국 ORDER A(1887) 매수 jsonl → acct=1887US
        sync_us_1887_fills.main()
    except Exception as e:
        print(f"  ⚠ 미국 ORDER A 동기화 생략: {e}")
    try:
        import sync_us_pine_1887_fills       # 미국 Pine 추세/저점(1887) 매수·매도 jsonl → acct=1887US
        sync_us_pine_1887_fills.main()
    except Exception as e:
        print(f"  ⚠ 미국 Pine 추세/저점 동기화 생략: {e}")
    fills = load_fills()
    rows, positions = build_rows(fills)
    # 2x 레버리지 추세봇의 예전 8042CHU 체결만 제외한다.
    # 1887로 이관된 고정 6종목은 strategy=trend여도 단타 차트/손익에 포함되어야 한다.
    rows = {k: v for k, v in rows.items()
            if not (v.get("acct") == "8042CHU" and v.get("strategy") == "trend")}
    stop_ords, stop_days = load_stop_info()

    dates = sorted({r["date"] for r in rows.values()})[-DAYS_KEEP:]
    rows_kept = [r for r in rows.values() if r["date"] in dates]
    print(f"  fill {len(fills)}건 → 표시 {len(rows_kept)}행 (날짜 {dates or '없음'})")

    still_open = {k for k, v in positions.items() if v["qty"] > 0}
    open_codes = sorted({c for (a, c) in still_open
                         if any(r["code"] == c and not r["sells"] for r in rows_kept)})
    cur_prices = fetch_cur_prices(open_codes)

    codes = sorted({r["code"] for r in rows_kept})
    trade_marks = build_trade_marks(rows_kept)
    daily_trades = build_daily_trades(rows_kept)
    result_summary = build_result_summary(rows_kept, stop_ords, stop_days)
    popup_block = (build_chart_popup(codes, trade_marks=trade_marks,
                                     daily_trades=daily_trades, result_summary=result_summary)
                   if codes else "<!-- 기록 없음: 팝업 생략 -->")

    open_rows   = build_open_rows(rows_kept, cur_prices, still_open)
    closed_rows = build_closed_rows(rows_kept, stop_ords, stop_days)
    if not open_rows:
        open_rows = '<tr><td colspan="8" style="color:#888;padding:18px;">현재 보유중인 종목이 없습니다</td></tr>'
    if not closed_rows:
        closed_rows = '<tr><td colspan="9" style="color:#888;padding:18px;">최근 5일 청산 완료 기록이 없습니다</td></tr>'

    # ── 실현손익: 일간(오늘) / 주간(이번주 월~금). 전 기간 rows 기준, 2계좌 합산 ──
    today = datetime.now().date()
    wk_start = today - timedelta(days=today.weekday())   # 이번주 월요일
    wk_end   = wk_start + timedelta(days=4)              # 이번주 금요일
    daily_pnl = weekly_pnl = 0
    for r in rows.values():
        if not r["sells"]:
            continue
        try:
            rd = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if rd == today:
            daily_pnl += r["realized"]
        if wk_start <= rd <= wk_end:
            weekly_pnl += r["realized"]

    def _pnl_span(v):
        c = "#d32f2f" if v > 0 else ("#1565c0" if v < 0 else "#666")
        return f'<span style="color:{c};">{v:,}</span>'
    done_title = (f'📒 매매일지 (완료) - 일간: {_pnl_span(daily_pnl)}, '
                  f'주간: {_pnl_span(weekly_pnl)}')

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>매매일지 (5분단타)</title>
<style>
body {{ font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif; padding:20px; margin:0; background:#f4f7f6; }}
.top-nav-container {{ display:flex; margin-bottom:15px; }}
.top-nav {{ display:flex; background:#2c3e50; border-radius:8px; overflow:hidden; width:fit-content; }}
.nav-item {{ padding:8px 15px; color:#bdc3c7; text-align:center; cursor:pointer; font-weight:bold;
  text-decoration:none; transition:all .3s; font-size:.9em; }}
.nav-item:hover {{ background:#34495e; color:#fff; }}
.nav-item.active {{ background:#3498db; color:#fff; }}
h2 {{ margin:10px 0 6px; padding-bottom:6px; color:#2c3e50; border-bottom:2px solid #3498db;
  font-size:1.1em; width:fit-content; }}
.journal-table {{ width:auto; border-collapse:collapse; margin:10px 0; font-size:13px; background:#fff;
  box-shadow:0 2px 5px rgba(0,0,0,.1); border-radius:8px; overflow:hidden; }}
.journal-table thead tr {{ background:#3498db; color:#fff; }}
.journal-table th, .journal-table td {{ padding:6px 14px; border-bottom:1px solid #eee;
  white-space:nowrap; text-align:center; }}
.journal-table td.code-col {{ font-weight:500; color:#2980b9; }}
.strat-cell {{ color:#8e44ad; font-size:12px; }}
.time-cell {{ font-family:'Consolas','Menlo',monospace; color:#444; font-size:12px; }}
.note {{ color:#777; font-size:12px; margin:4px 0 0; }}
@media (max-width:600px) {{
  .journal-table {{ font-size:11px; }}
  .journal-table th, .journal-table td {{ padding:4px 6px; }}
}}
@media screen and (max-width:950px) and (orientation:landscape) and (hover:none) and (pointer:coarse) {{
  .top-nav-container, .top-nav {{ display:none !important; }}
}}
</style>
</head>
<body>

<div class="top-nav-container">
  <div class="top-nav">
    <a href="kor_volume.html" class="nav-item">거래대금</a>
    <a href="danta_journal.html" class="nav-item active">매매일지</a>
    <a href="kor_volume_spike.html" class="nav-item">거래량 급증</a>
    <a href="kor_condition.html" class="nav-item">한국조건검색</a>
    <a href="us_condition.html" class="nav-item">미국조건검색</a>
  </div>
</div>

<p style="margin:0 0 12px 0; color:#555; font-size:.9em;">페이지: {now}</p>

<h2>📒 매매일지 <span style="font-size:.65em;color:#888;font-weight:normal;">2773 단타(chulow) + 8042 5분단타(lowhigh) + 1887 주도주(leader) · 최근 {DAYS_KEEP}일 · 티커 클릭=차트(B진입/S청산)</span></h2>
<table class="journal-table">
<thead><tr>
  <th>날짜</th><th>티커</th><th>종목명</th><th>남은보유주</th><th>수익률</th><th>실현손익</th><th>구분</th><th>계좌</th>
</tr></thead>
<tbody>
{open_rows}
</tbody>
</table>
<p class="note">· 보유중(매도없음)인 행은 현재가 기준 (수수료/세금 미반영).</p>

<h2 style="margin-top:24px;">{done_title}</h2>
<table class="journal-table">
<thead><tr>
  <th>날짜</th><th>티커</th><th>종목명</th><th>결과</th><th>매수/매도시각</th><th>수익률</th><th>실현손익</th><th>구분</th><th>계좌</th>
</tr></thead>
<tbody>
{closed_rows}
</tbody>
</table>
<p class="note">· 결과=익절(+수익)/손절(−수익)/청산(봇 -5% 자동손절). 수익률/실현손익은 봇 체결 기준(수수료/세금 미반영).<br>
· 차트 5분봉: <span style="background:#000;color:#fff;font-weight:bold;padding:0 4px;border-radius:2px;">↑</span>=진입(캔들 아래), <span style="background:#000;color:#fff;font-weight:bold;padding:0 4px;border-radius:2px;">↓</span>=청산(캔들 위). 일봉: 진입↑/청산↓ 화살표 끝점이 체결가에 정확히 부착(당일진입·청산 겹치면 좌우 분리).</p>

{popup_block}
</body>
</html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"generated": now, "dates": dates,
                   "rows": sorted(rows_kept, key=lambda r: (r["date"], r["code"])),
                   "trade_marks": trade_marks},
                  f, ensure_ascii=False, indent=2)
    print(f"  ✅ {OUT_HTML}")
    print(f"  ✅ {OUT_JSON}")


if __name__ == "__main__":
    main()
