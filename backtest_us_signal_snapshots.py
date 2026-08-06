# -*- coding: utf-8 -*-
"""
Paper backtest for save_us_signal_snapshot.py output.

Rule:
  - Buy 1 share per unique ticker per snapshot day.
  - Sell all shares when that day's trend is not LIME/GREEN.
  - Use the snapshot close as the paper execution price.

This is intentionally a paper test only.  It never sends orders.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(r"D:\py\report-us")
DATA_DIR = BASE / "data"
SNAPSHOT_JSONL = DATA_DIR / "us_signal_snapshots.jsonl"
OUT_JSON = DATA_DIR / "us_signal_snapshot_backtest_latest.json"
OUT_CSV = DATA_DIR / "us_signal_snapshot_backtest_trades.csv"

HOLD_TRENDS = {"LIME", "GREEN"}


def _to_float(raw):
    try:
        return float(raw)
    except Exception:
        return None


def load_snapshots() -> list[dict]:
    if not SNAPSHOT_JSONL.exists():
        return []
    rows = []
    for line in SNAPSHOT_JSONL.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return sorted(rows, key=lambda x: x.get("date", ""))


def daily_unique_records(snapshot: dict) -> dict[str, dict]:
    """Keep one buy candidate per ticker/day, preserving first section rank."""
    out = {}
    for rec in snapshot.get("records", []):
        ticker = str(rec.get("ticker", "")).upper().strip()
        if not ticker or ticker in out:
            continue
        price = _to_float(rec.get("close")) or _to_float(rec.get("price"))
        out[ticker] = {
            "ticker": ticker,
            "price": price,
            "trend": rec.get("trend", "UNKNOWN"),
            "source": rec.get("source"),
            "section": rec.get("section"),
            "rank": rec.get("rank"),
        }
    return out


def run_backtest(snapshots: list[dict]) -> dict:
    positions = defaultdict(list)  # ticker -> lots [{date, price, qty}]
    trades = []
    realized_pnl = 0.0
    invested = 0.0

    for snap in snapshots:
        date = snap.get("date", "")
        records = daily_unique_records(snap)

        # Exit first using today's trend/price if the ticker is observed today.
        for ticker, lots in list(positions.items()):
            rec = records.get(ticker)
            if not lots or not rec:
                continue
            price = rec.get("price")
            trend = rec.get("trend")
            if price is None or trend in HOLD_TRENDS:
                continue
            qty = sum(lot["qty"] for lot in lots)
            cost = sum(lot["price"] * lot["qty"] for lot in lots)
            proceeds = price * qty
            pnl = proceeds - cost
            realized_pnl += pnl
            trades.append({
                "date": date,
                "action": "SELL",
                "ticker": ticker,
                "qty": qty,
                "price": price,
                "trend": trend,
                "pnl": pnl,
            })
            positions.pop(ticker, None)

        # Buy 1 share for every unique ticker seen today.
        for ticker, rec in records.items():
            price = rec.get("price")
            if price is None:
                continue
            positions[ticker].append({"date": date, "price": price, "qty": 1})
            invested += price
            trades.append({
                "date": date,
                "action": "BUY",
                "ticker": ticker,
                "qty": 1,
                "price": price,
                "trend": rec.get("trend"),
                "source": rec.get("source"),
                "section": rec.get("section"),
                "rank": rec.get("rank"),
            })

    open_cost = 0.0
    open_market_value = 0.0
    latest_prices = {}
    if snapshots:
        latest = daily_unique_records(snapshots[-1])
        latest_prices = {t: r.get("price") for t, r in latest.items()}

    for ticker, lots in positions.items():
        cost = sum(lot["price"] * lot["qty"] for lot in lots)
        qty = sum(lot["qty"] for lot in lots)
        mark = latest_prices.get(ticker)
        open_cost += cost
        open_market_value += (mark * qty) if mark is not None else cost

    unrealized_pnl = open_market_value - open_cost
    total_pnl = realized_pnl + unrealized_pnl
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot_days": len(snapshots),
        "first_date": snapshots[0].get("date") if snapshots else None,
        "last_date": snapshots[-1].get("date") if snapshots else None,
        "policy": {
            "buy": "1 share per unique ticker per snapshot day",
            "sell": "sell all shares when trend is not LIME/GREEN",
            "price": "snapshot close",
        },
        "trades": trades,
        "summary": {
            "buy_count": sum(1 for t in trades if t["action"] == "BUY"),
            "sell_count": sum(1 for t in trades if t["action"] == "SELL"),
            "open_tickers": len(positions),
            "gross_buy_amount": invested,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": total_pnl,
            "total_return_pct_on_gross_buys": (total_pnl / invested * 100) if invested else 0.0,
        },
        "open_positions": {
            ticker: {
                "qty": sum(lot["qty"] for lot in lots),
                "avg_cost": (sum(lot["price"] * lot["qty"] for lot in lots) / sum(lot["qty"] for lot in lots)),
                "latest_price": latest_prices.get(ticker),
            }
            for ticker, lots in sorted(positions.items())
        },
    }


def write_outputs(result: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["date", "action", "ticker", "qty", "price", "trend", "pnl", "source", "section", "rank"]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.get("trades", []))


def main() -> int:
    snapshots = load_snapshots()
    result = run_backtest(snapshots)
    write_outputs(result)
    summary = result["summary"]
    print(f"[OK] snapshots: {result['snapshot_days']} days")
    print(f"[OK] buys/sells: {summary['buy_count']} / {summary['sell_count']}")
    print(f"[OK] total pnl: {summary['total_pnl']:.2f} ({summary['total_return_pct_on_gross_buys']:.2f}%)")
    print(f"[OK] report: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
