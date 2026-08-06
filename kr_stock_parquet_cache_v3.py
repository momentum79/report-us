# -*- coding: utf-8 -*-
"""
Korean Stock Parquet Cache System v3.0
======================================
chu_korea_final_all_tic.py 전용 OHLCV 캐시 (전종목 스캐너 데이터 로딩 최적화).

설계 핵심
---------
- NXT/KRX 데이터 혼용 금지가 최우선 규칙이다.
    * NXT 종목  : kr_nxt_ohlcv.fetch_daily_ohlcv(..., fallback_krx=False)
                  → Kiwoom `_AL`(NXT+KRX 통합) 데이터만 허용. 실패 시 조용히
                    KRX-only 로 대체하지 않고 miss 로 남긴다.
    * KRX 종목  : pykrx stock.get_market_ohlcv_by_date(start, end, ticker) 개별 경로.
- 기존 stock_kr_ohlcv.parquet(v2, stale) 은 절대 건드리지 않는다.
  본 모듈은 별도 파일 stock_kr_ohlcv_v3.parquet 만 읽고 쓴다.
- v2 의 날짜별 일괄 조회(get_market_ohlcv_by_ticker)는 pandas 3.x × pykrx 1.0.51
  조합에서 깨졌으므로 사용하지 않는다. 전부 개별(per-ticker) 경로다.
- 계산은 캐시 tail(500) 으로 한다. 최근 며칠 재수집은 갱신용일 뿐이다.

표준 컬럼: date, ticker, open, high, low, close, volume, value
    - ticker : 6자리 문자열
    - date   : datetime
    - 종목별 날짜 중복 제거, 종목별 최근 500봉 유지

CLI
---
    python kr_stock_parquet_cache_v3.py build   [--sample N] [--delay S]
    python kr_stock_parquet_cache_v3.py refresh [--delay S]
    python kr_stock_parquet_cache_v3.py read    [TICKER]
"""
from __future__ import annotations

import io
import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

# Windows 콘솔 cp949 이모지 인코딩 에러 방지
try:
    if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if sys.stderr and sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

# ── repo 루트를 path 에 추가 (kr_nxt_ohlcv import 용) ───────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pykrx import stock
from kr_nxt_ohlcv import fetch_daily_ohlcv, load_kr_meta, is_etf_like


# ═══════════════════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════════════════
CACHE_DIR              = r"D:\py\report-us"
KR_CACHE_FILE_V3       = os.path.join(CACHE_DIR, "stock_kr_ohlcv_v3.parquet")
KR_CSV_PATH            = r"D:\py\korea\kr.csv"

KEEP_ROWS_PER_TICKER   = 500    # 종목당 최대 보관 봉수
INIT_CALENDAR_DAYS     = 730    # 최초 구축 시 수집 캘린더일 (≈ 500 영업일)
REFRESH_LOOKBACK_DAYS  = 10     # 갱신 시 재수집 캘린더일 (주말/공휴일 여유분)
REFRESH_WORKERS        = 4      # fetch 병렬 워커 수 (1 이하 → 순차 폴백). NXT 키움 호출 가속용.
                                # ※ kr_nxt_ohlcv._throttle() 이 프로세스 전역 최소 호출간격을
                                #    강제하므로 워커를 늘려도 서버로 나가는 초당 호출수는 상한이
                                #    걸린다(429 방지). 메인창 KR150 과 병렬로 도는 부하를 줄이기
                                #    위해 8→4 로 낮춤. 더 줄이려면 KIWOOM_MIN_CALL_INTERVAL 조정.

_STD_COLS = ["date", "ticker", "open", "high", "low", "close", "volume", "value"]


# ═══════════════════════════════════════════════════════════════════
# 내부 유틸리티
# ═══════════════════════════════════════════════════════════════════
def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _empty_cache():
    return pd.DataFrame(columns=_STD_COLS)


def _load_cache(path=KR_CACHE_FILE_V3):
    if not os.path.exists(path):
        return _empty_cache()
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return _empty_cache()
        df["date"] = pd.to_datetime(df["date"])
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        return df
    except Exception as e:
        print(f"⚠ v3 캐시 로드 실패({path}): {e}")
        return _empty_cache()


def _save_cache(df, path=KR_CACHE_FILE_V3):
    if df is None or df.empty:
        print("⚠ 저장할 데이터 없음 → skip")
        return
    _ensure_dir()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["ticker"] = out["ticker"].astype(str).str.zfill(6)
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    out = out[_STD_COLS]
    out.to_parquet(path, index=False)
    print(f"💾 저장 완료: {path}  ({len(out):,}행 / {out['ticker'].nunique()}종목)")


def _dedup_and_trim(df):
    if df is None or df.empty:
        return _empty_cache()
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    df = df.sort_values(["ticker", "date"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df = (
        df.groupby("ticker", group_keys=False)
          .tail(KEEP_ROWS_PER_TICKER)
          .reset_index(drop=True)
    )
    return df


def _pick(cols, *cands):
    for c in cands:
        if c in cols:
            return c
    return None


def _to_standard_long(df_raw, ticker):
    """개별 OHLCV DataFrame(영문 or 한글 컬럼, index=날짜) → 표준 long 포맷."""
    if df_raw is None or len(df_raw) == 0:
        return None

    df = df_raw.copy()
    # index(날짜)를 컬럼으로
    df = df.reset_index()
    cols = list(df.columns)

    date_col   = _pick(cols, "Date", "날짜", "index", cols[0])
    open_col   = _pick(cols, "Open", "시가")
    high_col   = _pick(cols, "High", "고가")
    low_col    = _pick(cols, "Low", "저가")
    close_col  = _pick(cols, "Close", "종가")
    volume_col = _pick(cols, "Volume", "거래량")
    value_col  = _pick(cols, "거래대금", "Value", "value")

    if close_col is None or volume_col is None or date_col is None:
        return None

    out = pd.DataFrame()
    out["date"]   = pd.to_datetime(df[date_col], errors="coerce")
    out["ticker"] = str(ticker).zfill(6)
    out["open"]   = pd.to_numeric(df[open_col],  errors="coerce") if open_col  else pd.NA
    out["high"]   = pd.to_numeric(df[high_col],  errors="coerce") if high_col  else pd.NA
    out["low"]    = pd.to_numeric(df[low_col],   errors="coerce") if low_col   else pd.NA
    out["close"]  = pd.to_numeric(df[close_col], errors="coerce")
    out["volume"] = pd.to_numeric(df[volume_col], errors="coerce")
    if value_col is not None:
        out["value"] = pd.to_numeric(df[value_col], errors="coerce")
    else:
        # _AL(NXT) 경로는 거래대금이 없다 → close*volume 로 보존 (downstream 은
        # 어차피 trading_value = Volume*Close 를 재계산하므로 참고값일 뿐)
        out["value"] = out["close"] * out["volume"]

    out = out.dropna(subset=["date", "close", "volume"])
    out = out[(out["close"] > 0) & (out["volume"] >= 0)]
    if out.empty:
        return None
    return out[_STD_COLS]


# ═══════════════════════════════════════════════════════════════════
# 티커 분류 (NXT vs KRX)
# ═══════════════════════════════════════════════════════════════════
def load_tickers_classified(csv_path=KR_CSV_PATH):
    """
    kr.csv 전체 → [(ticker6, name, is_nxt), ...]

    is_nxt 판정:
      kr.csv NXT 컬럼 == "NXT" 이고 ETF 가 아닌 일반 종목.
    """
    rows = []
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    for _, r in df.iterrows():
        ticker = str(r.iloc[0]).strip().zfill(6)
        name   = str(r.iloc[1]).strip()
        nxt_val = ""
        if len(df.columns) >= 3 and pd.notna(r.iloc[2]):
            nxt_val = str(r.iloc[2]).strip()
        is_nxt = (nxt_val == "NXT") and not is_etf_like(ticker, name)
        rows.append((ticker, name, is_nxt))
    return rows


# ═══════════════════════════════════════════════════════════════════
# 개별 종목 fetch
# ═══════════════════════════════════════════════════════════════════
def _fetch_nxt(ticker, name, start, end):
    """NXT 종목: _AL 통합 데이터만. 실패 시 None (KRX-only 대체 금지)."""
    try:
        df = fetch_daily_ohlcv(ticker, start, end, name=name, fallback_krx=False)
    except Exception as e:
        print(f"  ⚠ NXT fetch 예외 {ticker}({name}): {e}")
        return None
    return _to_standard_long(df, ticker)


def _fetch_krx(ticker, start, end):
    """KRX 일반 종목: pykrx 개별 경로."""
    try:
        df = stock.get_market_ohlcv_by_date(start, end, ticker)
    except Exception as e:
        print(f"  ⚠ KRX fetch 예외 {ticker}: {e}")
        return None
    return _to_standard_long(df, ticker)


def _fetch_one(ticker, name, is_nxt, start, end):
    if is_nxt:
        return _fetch_nxt(ticker, name, start, end), "nxt"
    return _fetch_krx(ticker, start, end), "krx"


# ═══════════════════════════════════════════════════════════════════
# 전 종목 fetch (병렬 / 순차 공통)
# ═══════════════════════════════════════════════════════════════════
def _warm_kiwoom_token():
    """병렬 첫 호출 시 토큰 동시발급 레이스 방지용 1회 워밍."""
    try:
        from kr_nxt_ohlcv import get_access_token
        get_access_token()
    except Exception:
        pass


def _fetch_all(tickers, start, end, workers, delay, progress_every):
    """
    tickers: [(ticker, name, is_nxt), ...] 를 전부 fetch.
    workers > 1 → ThreadPool 병렬, 그 외 → 기존 순차.
    결과 rows 순서는 무관(_dedup_and_trim 이 정렬·중복제거).
    반환: rows, ok, fail, nxt_ok, nxt_fail, krx_ok, krx_fail
    """
    rows, ok, fail = [], 0, 0
    nxt_ok = nxt_fail = krx_ok = krx_fail = 0
    total = len(tickers)
    t0 = time.time()

    def _tally(std, src):
        nonlocal ok, fail, nxt_ok, nxt_fail, krx_ok, krx_fail
        if std is not None and not std.empty:
            rows.append(std); ok += 1
            if src == "nxt": nxt_ok += 1
            else:            krx_ok += 1
        else:
            fail += 1
            if src == "nxt": nxt_fail += 1
            else:            krx_fail += 1

    if workers and workers > 1:
        _warm_kiwoom_token()
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_fetch_one, tk, nm, isx, start, end)
                    for tk, nm, isx in tickers]
            for fu in as_completed(futs):
                try:
                    std, src = fu.result()
                except Exception as e:
                    std, src = None, "krx"
                    print(f"  ⚠ fetch future 예외: {e}")
                _tally(std, src)
                done += 1
                if done % progress_every == 0 or done == total:
                    print(f"  진행 {done}/{total}  ok={ok} fail={fail}  ({time.time()-t0:.0f}s)")
    else:
        for i, (tk, nm, isx) in enumerate(tickers, 1):
            std, src = _fetch_one(tk, nm, isx, start, end)
            _tally(std, src)
            if delay:
                time.sleep(delay)
            if i % progress_every == 0 or i == total:
                print(f"  진행 {i}/{total}  ok={ok} fail={fail}  ({time.time()-t0:.0f}s)")

    return rows, ok, fail, nxt_ok, nxt_fail, krx_ok, krx_fail


# ═══════════════════════════════════════════════════════════════════
# 빌드 / 갱신
# ═══════════════════════════════════════════════════════════════════
def build_full_cache(tickers=None, sample=None, delay=0.05, save=True, workers=REFRESH_WORKERS):
    """
    최초 전체 구축. 기존 v3 캐시는 무시하고 새로 만든다.
    tickers : None → kr.csv 전체. sample=N → 앞 N개만(테스트).
    반환: 구축된 cache_df
    """
    _ensure_dir()
    if tickers is None:
        tickers = load_tickers_classified()
    if sample:
        tickers = tickers[:sample]

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=INIT_CALENDAR_DAYS)).strftime("%Y%m%d")

    nxt_n = sum(1 for _, _, x in tickers if x)
    krx_n = len(tickers) - nxt_n
    _mode = f"병렬 워커{workers}" if (workers and workers > 1) else "순차"
    print("=" * 64)
    print(f"🏗  v3 캐시 전체 구축 시작  ({start}~{end}, {INIT_CALENDAR_DAYS}일)  [{_mode}]")
    print(f"   대상: {len(tickers)}종목  (NXT _AL: {nxt_n} / KRX pykrx: {krx_n})")
    print("=" * 64)

    rows, ok, fail, nxt_ok, nxt_fail, krx_ok, krx_fail = _fetch_all(
        tickers, start, end, workers=workers, delay=delay, progress_every=50)

    if not rows:
        print("⚠ 구축 실패: 수집 데이터 없음")
        return _empty_cache()

    out = _dedup_and_trim(pd.concat(rows, ignore_index=True))
    print("-" * 64)
    print(f"✅ 구축 완료: {ok}종목 성공 / {fail}실패")
    print(f"   NXT  성공 {nxt_ok} 실패 {nxt_fail}")
    print(f"   KRX  성공 {krx_ok} 실패 {krx_fail}")
    if nxt_fail and (nxt_ok + nxt_fail) and nxt_fail / (nxt_ok + nxt_fail) > 0.1:
        print(f"   ⚠ NXT 누락률 {nxt_fail/(nxt_ok+nxt_fail)*100:.1f}% — Kiwoom 토큰/네트워크 확인 필요")
    if save:
        _save_cache(out)
    return out


def refresh_cache(tickers=None, delay=0.05, save=True, workers=REFRESH_WORKERS):
    """
    정상 갱신: 기존 v3 캐시 로드 → 최근 REFRESH_LOOKBACK_DAYS 재수집 → merge.
    v3 캐시가 없으면 자동으로 build_full_cache 로 분기.
    workers>1 → fetch 병렬(ThreadPool), workers<=1 → 기존 순차.
    """
    cache_df = _load_cache()
    if cache_df.empty:
        print("ℹ v3 캐시 없음 → 전체 구축으로 분기")
        return build_full_cache(tickers=tickers, delay=delay, save=save, workers=workers)

    if tickers is None:
        tickers = load_tickers_classified()

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=REFRESH_LOOKBACK_DAYS)).strftime("%Y%m%d")

    nxt_n = sum(1 for _, _, x in tickers if x)
    krx_n = len(tickers) - nxt_n
    _mode = f"병렬 워커{workers}" if (workers and workers > 1) else "순차"
    print("=" * 64)
    print(f"🔄 v3 캐시 갱신  (최근 {REFRESH_LOOKBACK_DAYS}일: {start}~{end})  [{_mode}]")
    print(f"   대상: {len(tickers)}종목  (NXT _AL: {nxt_n} / KRX pykrx: {krx_n})")
    print(f"   기존 캐시 last_date: {cache_df['date'].max().strftime('%Y-%m-%d')}")
    print("=" * 64)

    rows, ok, fail, _no, _nf, _ko, _kf = _fetch_all(
        tickers, start, end, workers=workers, delay=delay, progress_every=100)

    if rows:
        merged = pd.concat([cache_df] + rows, ignore_index=True)
    else:
        merged = cache_df
    out = _dedup_and_trim(merged)
    print("-" * 64)
    print(f"✅ 갱신 완료: 신규 수집 {ok}종목 / 실패 {fail}")
    print(f"   갱신 후 last_date: {out['date'].max().strftime('%Y-%m-%d')}")
    if save:
        _save_cache(out)
    return out


# ═══════════════════════════════════════════════════════════════════
# 캐시 조회 (chu_korea_final_all_tic.py 가 그대로 쓰는 형태)
# ═══════════════════════════════════════════════════════════════════
def get_kr_stock_ohlcv_v3(ticker, cache_df=None):
    """
    반환: index=date(datetime), 컬럼 Open/High/Low/Close/Volume (영문) DataFrame.
          chu_korea_final_all_tic.py 의 fetch_daily_ohlcv 반환형과 동일하게 맞춤.
          (chu 의 한글→영문 rename 은 no-op 이 됨)
    종목 없으면 빈 DataFrame.
    """
    if cache_df is None:
        cache_df = _load_cache()

    ticker = str(ticker).zfill(6)
    df = cache_df[cache_df["ticker"] == ticker]
    if df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = df.sort_values("date").copy()
    df = df.set_index(pd.to_datetime(df["date"]))
    df.index.name = "Date"
    out = df[["open", "high", "low", "close", "volume"]].rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    return out.tail(KEEP_ROWS_PER_TICKER)


def cache_summary(cache_df=None):
    """간단 요약 dict."""
    if cache_df is None:
        cache_df = _load_cache()
    if cache_df.empty:
        return {"rows": 0, "tickers": 0, "last_date": None, "first_date": None}
    return {
        "rows": len(cache_df),
        "tickers": cache_df["ticker"].nunique(),
        "last_date": cache_df["date"].max().strftime("%Y-%m-%d"),
        "first_date": cache_df["date"].min().strftime("%Y-%m-%d"),
    }


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════
def _main():
    p = argparse.ArgumentParser(description="KR stock OHLCV cache v3")
    sub = p.add_subparsers(dest="cmd")

    pb = sub.add_parser("build", help="최초 전체 구축 (기존 v3 무시)")
    pb.add_argument("--sample", type=int, default=None, help="앞 N개만 테스트")
    pb.add_argument("--delay", type=float, default=0.05)
    pb.add_argument("--workers", type=int, default=REFRESH_WORKERS, help="fetch 병렬 워커(1=순차)")

    pr = sub.add_parser("refresh", help="최근 N일 재수집 후 merge")
    pr.add_argument("--delay", type=float, default=0.05)
    pr.add_argument("--workers", type=int, default=REFRESH_WORKERS, help="fetch 병렬 워커(1=순차)")

    prd = sub.add_parser("read", help="캐시 조회")
    prd.add_argument("ticker", nargs="?", default=None)

    args = p.parse_args()

    if args.cmd == "build":
        build_full_cache(sample=args.sample, delay=args.delay, workers=args.workers)
    elif args.cmd == "refresh":
        refresh_cache(delay=args.delay, workers=args.workers)
    elif args.cmd == "read":
        cdf = _load_cache()
        print("📊 캐시 요약:", cache_summary(cdf))
        if args.ticker:
            print(f"\n[{args.ticker}] 최근 5봉:")
            print(get_kr_stock_ohlcv_v3(args.ticker, cdf).tail(5))
    else:
        p.print_help()


if __name__ == "__main__":
    _main()
