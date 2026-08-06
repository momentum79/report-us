# -*- coding: utf-8 -*-
"""
Save daily US signal candidates for later paper/backtest review.

This script reads the same text/CSV artifacts used by make_us_summary_board.py
and appends one date snapshot to:
  D:/py/report-us/data/us_signal_snapshots.jsonl

It is intentionally read-only with respect to scanners/order files.  No live
orders are placed here.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(r"D:\py")
BASE = ROOT / "report-us"
DATA_DIR = BASE / "data"
SNAPSHOT_JSONL = DATA_DIR / "us_signal_snapshots.jsonl"
LATEST_JSON = DATA_DIR / "us_signal_snapshot_latest.json"
LATEST_CSV = DATA_DIR / "us_signal_snapshot_latest.csv"

FINVIZ_TXT = BASE / "report_us_finviz.txt"
US_MAIN_TXT = BASE / "report_us_main.txt"
US_STOCK_TXT = BASE / "report_us.txt"
MINERVINI_CSV = BASE / "us_minervini_stage2_final.csv"
US_OHLCV_CACHE = ROOT / "cache" / "us_adj_ohlcv.parquet"

TOP_N = 10
HOLD_TRENDS = {"LIME", "GREEN"}
OHLCV_CACHE_STORE: dict[str, pd.DataFrame] | None = None

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _clean_ticker(raw: str) -> str:
    ticker = str(raw or "").replace("*", "").strip().upper()
    return ticker if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker) else ""


def _to_float(raw):
    try:
        return float(str(raw).replace("$", "").replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def _extract_between_markers(text: str, start_contains: str, end_contains: Iterable[str]) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if start_contains in line:
            start = i + 1
            break
    if start is None:
        return ""

    end = len(lines)
    markers = tuple(end_contains)
    for i in range(start, len(lines)):
        if any(m in lines[i] for m in markers):
            end = i
            break
    return "\n".join(lines[start:end])


def _space_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        s = line.strip()
        if not s or s.startswith("-") or s.startswith("="):
            continue
        parts = re.split(r"\s{2,}", s)
        if len(parts) < 2:
            parts = s.split()
        if not parts or parts[0].lower() == "ticker":
            continue
        ticker = _clean_ticker(parts[0])
        if ticker:
            parts[0] = ticker
            rows.append(parts)
    return rows


def _pipe_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        s = line.strip()
        if not s or "|" not in s or s.startswith("-") or s.startswith("="):
            continue
        if s.lower().startswith("ticker"):
            continue
        parts = [p.strip() for p in s.split("|")]
        ticker = _clean_ticker(parts[0] if parts else "")
        if ticker:
            parts[0] = ticker
            rows.append(parts)
    return rows


def _finviz_signal_tables(text: str) -> list[list[list[str]]]:
    """Return Finviz signal tables in report order: MOM, LIME, GREEN, JUNG.

    The section headers may be mojibake in old console output, but each signal
    table uses the stable header shape: "Ticker Industry Sig_sco 3M(%)".
    """
    tables: list[list[list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Ticker") and "Sig_sco" in s:
            if current is not None:
                tables.append(_space_rows("\n".join(current)))
            current = []
            continue
        if current is None:
            continue
        if s.startswith("Ticker") and "Sig_sco" in s:
            tables.append(_space_rows("\n".join(current)))
            current = []
            continue
        if "ATR" in s or "Signal_sco" in s:
            break
        current.append(line)
    if current is not None:
        tables.append(_space_rows("\n".join(current)))
    return tables


def _all_signal_pipe_rows(text: str, signal: str) -> list[list[str]]:
    rows = []
    wanted = signal.upper()
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.strip().split("|")]
        if len(parts) < 2:
            continue
        ticker = _clean_ticker(parts[0])
        sig = parts[1].upper()
        if ticker and sig == wanted:
            parts[0] = ticker
            rows.append(parts)
    return rows


def _add_record(records: list[dict], seen: set[tuple[str, str]], source: str,
                section: str, rank: int, ticker: str, **fields) -> None:
    ticker = _clean_ticker(ticker)
    if not ticker:
        return
    key = (source + ":" + section, ticker)
    if key in seen:
        return
    seen.add(key)
    rec = {
        "source": source,
        "section": section,
        "rank": rank,
        "ticker": ticker,
    }
    rec.update({k: v for k, v in fields.items() if v not in ("", None)})
    records.append(rec)


def collect_finviz(records: list[dict], seen: set[tuple[str, str]]) -> None:
    text = _read(FINVIZ_TXT)
    if not text:
        return

    order = _space_rows(_extract_between_markers(
        text, "Top4", ["Top4:", "==="]
    ))[:4]
    for i, row in enumerate(order, 1):
        _add_record(records, seen, "finviz", "order_top4", i, row[0],
                    signal_sco=_to_float(row[2] if len(row) > 2 else None),
                    final_score=_to_float(row[-2] if len(row) > 5 else None),
                    signal=row[-1] if len(row) > 1 else None)

    top = _space_rows(_extract_between_markers(
        text, "US Stock Momentum Top", ["MOM", "LIME", "Top4"]
    ))[:TOP_N]
    for i, row in enumerate(top, 1):
        _add_record(records, seen, "finviz", "sector_quality_top10", i, row[0],
                    signal_sco=_to_float(row[2] if len(row) > 2 else None),
                    rtn_3m_pct=_to_float(row[3] if len(row) > 3 else None),
                    final_score=_to_float(row[4] if len(row) > 4 else None),
                    signal=row[5] if len(row) > 5 else None)

    mom = _space_rows(_extract_between_markers(
        text, "【MOM", ["【LIME", "【GREEN", "=== 주문용 Top4", "=== 二"]
    ))[:TOP_N]
    if not mom:
        signal_tables = _finviz_signal_tables(text)
        mom = (signal_tables[0] if len(signal_tables) > 0 else [])[:TOP_N]
    for i, row in enumerate(mom, 1):
        _add_record(records, seen, "finviz", "signal_mom", i, row[0],
                    signal="MOM",
                    signal_sco=_to_float(row[2] if len(row) > 2 else None),
                    rtn_3m_pct=_to_float(row[3] if len(row) > 3 else None))

    lime = _space_rows(_extract_between_markers(
        text, "【LIME", ["【GREEN", "【RED", "=== 주문용 Top4", "=== 二"]
    ))[:TOP_N]
    for i, row in enumerate(lime, 1):
        _add_record(records, seen, "finviz", "signal_lime", i, row[0],
                    signal="LIME",
                    signal_sco=_to_float(row[2] if len(row) > 2 else None),
                    rtn_3m_pct=_to_float(row[3] if len(row) > 3 else None))


def collect_us_main(records: list[dict], seen: set[tuple[str, str]]) -> None:
    text = _read(US_MAIN_TXT)
    if not text:
        return

    top = _pipe_rows(_extract_between_markers(text, "US Main Top30", []))[:TOP_N]
    for i, row in enumerate(top, 1):
        _add_record(records, seen, "us_main", "main_quality_top10", i, row[0],
                    signal_sco=_to_float(row[1] if len(row) > 1 else None),
                    rtn_3m_pct=_to_float(row[2] if len(row) > 2 else None),
                    final_score=_to_float(row[3] if len(row) > 3 else None),
                    signal=row[4] if len(row) > 4 else None)

    mom = _all_signal_pipe_rows(text, "MOM")[:TOP_N]
    for i, row in enumerate(mom, 1):
        _add_record(records, seen, "us_main", "signal_mom", i, row[0],
                    signal="MOM",
                    price=_to_float(row[2] if len(row) > 2 else None),
                    signal_sco=_to_float(row[4].replace("sco:", "") if len(row) > 4 else None))

    lime = _all_signal_pipe_rows(text, "LIME")[:TOP_N]
    for i, row in enumerate(lime, 1):
        _add_record(records, seen, "us_main", "signal_lime", i, row[0],
                    signal="LIME",
                    price=_to_float(row[2] if len(row) > 2 else None),
                    signal_sco=_to_float(row[4].replace("sco:", "") if len(row) > 4 else None))


def collect_us_stock_vcp(records: list[dict], seen: set[tuple[str, str]]) -> None:
    text = _read(US_STOCK_TXT)
    vcp = _space_rows(_extract_between_markers(
        text, "US Momentum Top (VCP Early Stage)", ["Top4", "==="]
    ))[:TOP_N]
    for i, row in enumerate(vcp, 1):
        _add_record(records, seen, "us_stock", "vcp_early_top10", i, row[0],
                    signal_sco=_to_float(row[1] if len(row) > 1 else None),
                    rtn_3m_pct=_to_float(row[2] if len(row) > 2 else None),
                    rtn_1m_pct=_to_float(row[3] if len(row) > 3 else None),
                    early_score=_to_float(row[4] if len(row) > 4 else None),
                    final_score=_to_float(row[5] if len(row) > 5 else None),
                    signal=row[6] if len(row) > 6 else None)


def collect_minervini(records: list[dict], seen: set[tuple[str, str]]) -> None:
    if not MINERVINI_CSV.exists():
        return
    with MINERVINI_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            if i > TOP_N:
                break
            _add_record(records, seen, "minervini", "stage2_entry", i, row.get("ticker", ""),
                        signal=row.get("status"),
                        rs_rating=_to_float(row.get("RS_rating")),
                        minervini_score=_to_float(row.get("Minervini_score")),
                        rtn_3m_pct=_to_float(row.get("R3M")),
                        price=_to_float(row.get("close_now")),
                        pivot=_to_float(row.get("pivot")),
                        pivot_dist_pct=_to_float(row.get("pivot_dist_pct")))


def _load_ohlcv_from_parquet(ticker: str) -> pd.DataFrame | None:
    global OHLCV_CACHE_STORE
    if not US_OHLCV_CACHE.exists():
        return None
    if OHLCV_CACHE_STORE is None:
        OHLCV_CACHE_STORE = {}
        try:
            long_df = pd.read_parquet(US_OHLCV_CACHE)
            long_df["date"] = pd.to_datetime(long_df["date"])
            for tkr, group in long_df.groupby("ticker"):
                g = group.sort_values("date").set_index("date")
                cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in g.columns]
                if len(cols) == 5:
                    OHLCV_CACHE_STORE[str(tkr).upper()] = g[cols].copy()
        except Exception:
            OHLCV_CACHE_STORE = {}
    return OHLCV_CACHE_STORE.get(ticker.upper())


def _load_ohlcv_with_fallback(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        from us_ohlcv_cache import get_us_ohlcv
        live_or_cached = get_us_ohlcv(ticker, start, end)
        if live_or_cached is not None and not live_or_cached.empty:
            return live_or_cached
    except Exception:
        pass
    return _load_ohlcv_from_parquet(ticker)


def _trend_from_ohlcv(ticker: str, start: str, end: str) -> dict:
    from coloryp_core import check_coloryp_logic

    df = _load_ohlcv_with_fallback(ticker, start, end)
    if df is None or df.empty or len(df) < 220:
        return {"trend": "UNKNOWN"}
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    rename = {c: c.lower() for c in df.columns}
    df = df.rename(columns=rename)
    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(set(df.columns)):
        return {"trend": "UNKNOWN"}
    out = check_coloryp_logic(df[["open", "high", "low", "close", "volume"]])
    last = out.iloc[-1]
    hv99 = int(last.get("HLv99", 0))
    hv7 = int(last.get("HLv7", 0))
    hv71 = int(last.get("HLv71", 0))
    ang_sum = float(last.get("ang_sum", 0) or 0)
    trend = "-"
    if bool(last.get("lime_final", False)):
        trend = "LIME"
    elif hv99 >= 1 and hv71 == 1:
        trend = "GREEN"
    elif (hv99 <= -1 and hv7 == -1 and hv71 == -1) or ang_sum <= -14:
        trend = "RED"
    elif (hv99 <= -1 and hv71 == -1) or ang_sum <= -8:
        trend = "PURPLE"
    return {
        "trend": trend,
        "close": float(last.get("close")),
        "trend_date": out.index[-1].strftime("%Y-%m-%d"),
        "hold_ok": trend in HOLD_TRENDS,
    }


def attach_trends(records: list[dict]) -> None:
    tickers = sorted({r["ticker"] for r in records})
    if not tickers:
        return
    end = datetime.today() + timedelta(days=1)
    start = end - timedelta(days=380)
    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    cache = {}
    for ticker in tickers:
        try:
            cache[ticker] = _trend_from_ohlcv(ticker, start_s, end_s)
        except Exception as exc:
            cache[ticker] = {"trend": "ERROR", "trend_error": str(exc)[:160]}
    for rec in records:
        rec.update(cache.get(rec["ticker"], {"trend": "UNKNOWN"}))


def load_existing_dates() -> set[str]:
    dates = set()
    if not SNAPSHOT_JSONL.exists():
        return dates
    for line in SNAPSHOT_JSONL.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            dates.add(json.loads(line).get("date", ""))
        except Exception:
            pass
    return dates


def write_outputs(snapshot: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_key = snapshot["date"]
    lines = []
    if SNAPSHOT_JSONL.exists():
        for line in SNAPSHOT_JSONL.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                if json.loads(line).get("date") == date_key:
                    continue
            except Exception:
                pass
            lines.append(line)
    lines.append(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    SNAPSHOT_JSONL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LATEST_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "date", "source", "section", "rank", "ticker", "signal", "trend",
        "hold_ok", "price", "close", "signal_sco", "rtn_3m_pct",
        "rtn_1m_pct", "early_score", "final_score", "trend_date",
    ]
    with LATEST_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for rec in snapshot["records"]:
            row = {"date": snapshot["date"], **rec}
            w.writerow(row)


def main() -> int:
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    collect_finviz(records, seen)
    collect_us_main(records, seen)
    collect_us_stock_vcp(records, seen)
    collect_minervini(records, seen)

    attach_trends(records)

    unique_buy_candidates = sorted({r["ticker"] for r in records})
    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": 1,
        "policy": {
            "paper_buy": "1 share per unique ticker per snapshot day",
            "paper_sell": "sell when trend is not LIME or GREEN",
            "order_execution": "no live order; snapshot only",
        },
        "sources": {
            "finviz": str(FINVIZ_TXT),
            "us_main": str(US_MAIN_TXT),
            "us_stock": str(US_STOCK_TXT),
            "minervini": str(MINERVINI_CSV),
        },
        "unique_buy_candidates": unique_buy_candidates,
        "records": records,
    }
    write_outputs(snapshot)
    print(f"[OK] saved US signal snapshot: {len(records)} rows, {len(unique_buy_candidates)} unique tickers")
    print(f"[OK] latest: {LATEST_JSON}")
    print(f"[OK] history: {SNAPSHOT_JSONL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
