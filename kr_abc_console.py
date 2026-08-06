# -*- coding: utf-8 -*-
"""KR A/B/C 스캔 결과를 cmd 창에 정렬해서 출력하는 헬퍼.
사용법: python kr_abc_console.py [A|B|C|ALL]
  A = converge (kr_converge_data.json)
  B = afterflat (kr_afterflat_data.json)
  C = minervini (kr_minervini_stage2_final.csv)
표시만 하고 아무 파일도 수정하지 않는다 (read-only).
"""
import csv
import json
import os
import sys
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))


def dwidth(s):
    """동아시아 전각(한글 등)은 2칸으로 세어 실제 콘솔 표시폭 계산."""
    w = 0
    for ch in str(s):
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def trunc(s, width):
    """표시폭이 width를 넘으면 잘라서 끝에 … 표시 (정렬 유지용)."""
    s = str(s)
    if dwidth(s) <= width:
        return s
    out = ""
    w = 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width - 1:
            break
        out += ch
        w += cw
    return out + "…"


def pad(s, width, align="left"):
    s = trunc(s, width)
    gap = width - dwidth(s)
    if gap <= 0:
        return s
    return s + " " * gap if align == "left" else " " * gap + s


def print_table(rows, cols):
    """cols = [(header, key_or_idx, width, align), ...]"""
    header = "  ".join(pad(h, w, a) for h, _, w, a in cols)
    print(header)
    print("  ".join("-" * w for _, _, w, _ in cols))
    for r in rows:
        line = []
        for _, key, w, a in cols:
            v = r.get(key, "") if isinstance(r, dict) else r[key]
            line.append(pad(v, w, a))
        print("  ".join(line))


def fmt_num(v, nd=0):
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def show_A():
    fp = os.path.join(BASE, "kr_converge_data.json")
    if not os.path.exists(fp):
        print("[A] kr_converge_data.json 없음")
        return
    d = json.load(open(fp, encoding="utf-8"))
    fire = d.get("fire", [])
    watch = d.get("watch", [])
    print("=" * 66)
    print(f"[A] 수렴 돌파 (FIRE {len(fire)} / WATCH {len(watch)})  "
          f"기준 수렴<={d.get('converge_max_pct','?')}%  "
          f"거래대금>={d.get('liq_min_uk','?')}억")
    print("=" * 66)
    cols = [
        ("코드", "ticker_num", 6, "left"),
        ("종목명", "name", 16, "left"),
        ("종가", "close", 9, "right"),
        ("등락%", "change", 7, "right"),
        ("당일거래대금", "tv_today_uk", 12, "right"),
        ("돌파가", "trigger_price", 10, "right"),
        ("수렴폭%", "spread_pct", 8, "right"),
        ("NXT", "nxt", 8, "left"),
    ]
    for label, mark, lst in (("FIRE 발화", "🔥", fire), ("WATCH 관찰", "  ", watch)):
        print()
        print("─" * 66)
        print(f" {mark} [{label}]  {len(lst)}종목")
        print("─" * 66)
        if not lst:
            print("   (없음)")
            continue
        rows = [{
            "ticker_num": s.get("ticker_num", s.get("ticker", "")),
            "name": s.get("name", ""),
            "close": fmt_num(s.get("close")),
            "change": fmt_num(s.get("change"), 2),
            "tv_today_uk": fmt_num(s.get("tv_today_uk")) + "억",
            "trigger_price": (fmt_num(s.get("trigger_price")) if s.get("trigger_price") else ""),
            "spread_pct": fmt_num(s.get("spread_pct"), 2),
            "nxt": s.get("nxt", ""),
        } for s in lst]
        print_table(rows, cols)
    print()


def show_B():
    fp = os.path.join(BASE, "kr_afterflat_data.json")
    if not os.path.exists(fp):
        print("[B] kr_afterflat_data.json 없음")
        return
    d = json.load(open(fp, encoding="utf-8"))
    stocks = d.get("stocks", [])
    print("=" * 66)
    print(f"[B] 횡보 돌파 ({len(stocks)}종목)")
    print("=" * 66)
    if not stocks:
        print("  (없음)\n")
        return
    cols = [
        ("코드", "ticker_num", 6, "left"),
        ("종목명", "name", 16, "left"),
        ("종가", "close", 9, "right"),
        ("등락%", "change", 7, "right"),
        ("횡보일", "squeeze_days", 6, "right"),
        ("시총(억)", "market_cap_uk", 11, "right"),
        ("이평간격%", "ma_gap_pct", 9, "right"),
        ("가격폭%", "price_range_pct", 8, "right"),
        ("NXT", "nxt", 8, "left"),
    ]
    rows = [{
        "ticker_num": s.get("ticker_num", s.get("ticker", "")),
        "name": s.get("name", ""),
        "close": fmt_num(s.get("close")),
        "change": fmt_num(s.get("change"), 2),
        "squeeze_days": s.get("squeeze_days", ""),
        "market_cap_uk": fmt_num(s.get("market_cap_uk")),
        "ma_gap_pct": fmt_num(s.get("ma_gap_pct"), 2),
        "price_range_pct": fmt_num(s.get("price_range_pct"), 2),
        "nxt": s.get("nxt", ""),
    } for s in stocks]
    print_table(rows, cols)
    print()


def show_C():
    fp = os.path.join(BASE, "kr_minervini_stage2_final.csv")
    if not os.path.exists(fp):
        print("[C] kr_minervini_stage2_final.csv 없음")
        return
    with open(fp, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print("=" * 66)
    print(f"[C] 미너비니 VCP 2차 ({len(rows)}종목)")
    print("=" * 66)
    if not rows:
        print("  (없음)\n")
        return
    cols = [
        ("코드", "ticker", 6, "left"),
        ("종목명", "종목명", 16, "left"),
        ("상태", "status", 13, "left"),
        ("RS", "RS_rating", 5, "right"),
        ("점수", "Minervini_score", 6, "right"),
        ("종가", "close_now", 9, "right"),
        ("피봇%", "pivot_dist_pct", 7, "right"),
        ("피봇가", "pivot", 9, "right"),
        ("박스%", "pivot_box_pct", 7, "right"),
        ("수축진행", "contractions", 16, "left"),
    ]
    out = [{
        "ticker": r.get("ticker", ""),
        "종목명": r.get("종목명", ""),
        "status": r.get("status", ""),
        "RS_rating": fmt_num(r.get("RS_rating")),
        "Minervini_score": fmt_num(r.get("Minervini_score"), 1),
        "close_now": fmt_num(r.get("close_now")),
        "pivot_dist_pct": fmt_num(r.get("pivot_dist_pct"), 2),
        "pivot": fmt_num(r.get("pivot")),
        "pivot_box_pct": fmt_num(r.get("pivot_box_pct"), 2),
        "contractions": r.get("contractions", ""),
    } for r in rows]
    print_table(out, cols)
    print()


def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "ALL").upper()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if mode in ("A", "ALL"):
        show_A()
    if mode in ("B", "ALL"):
        show_B()
    if mode in ("C", "ALL"):
        show_C()


if __name__ == "__main__":
    main()
