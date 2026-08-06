# -*- coding: utf-8 -*-
"""
Korean Stock Parquet Cache System v2.0
- 날짜별 전체 종목 일괄 조회 (get_market_ohlcv_by_ticker)
- API 호출: 종목수만큼(~2883번) → 갱신 날짜 수만큼(보통 1~2번)
- 기존 stock_kr_ohlcv.parquet 파일과 완전 호환
"""
import os
from datetime import datetime, timedelta
import pandas as pd
from pykrx import stock


# ═══════════════════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════════════════
CACHE_DIR            = r"D:\py\report-us"
KR_CACHE_FILE        = os.path.join(CACHE_DIR, "stock_kr_ohlcv.parquet")

KEEP_ROWS_PER_TICKER = 500   # 종목당 최대 500일 보관
INIT_CALENDAR_DAYS   = 800   # 최초 1회(parquet 없을 때) 히스토리 구축 기간
REFRESH_LOOKBACK     = 7     # 갱신 시 최근 N 캘린더일 시도 (주말/공휴일 여유분)


# ═══════════════════════════════════════════════════════════════════
# 내부 유틸리티
# ═══════════════════════════════════════════════════════════════════
def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _empty_cache():
    return pd.DataFrame(columns=[
        "date", "ticker", "open", "high", "low", "close", "volume", "value"
    ])


def _load_cache(path):
    if not os.path.exists(path):
        return _empty_cache()
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return _empty_cache()
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return _empty_cache()


def _save_cache(df, path):
    if df is None or df.empty:
        return
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    out.to_parquet(path, index=False)


def _dedup_and_trim(df):
    if df is None or df.empty:
        return _empty_cache()
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df = (
        df.groupby("ticker", group_keys=False)
          .tail(KEEP_ROWS_PER_TICKER)
          .reset_index(drop=True)
    )
    return df


def _fetch_one_day(date_str):
    """
    특정 날짜의 전체 종목 OHLCV를 한 번에 조회 (API 1번 호출).
    휴장일이면 빈 DataFrame 반환.
    """
    try:
        raw = stock.get_market_ohlcv_by_ticker(date_str, market="ALL")
        if raw is None or raw.empty:
            return _empty_cache()

        raw = raw.reset_index()
        col0 = raw.columns[0]  # 티커 컬럼
        rename_map = {
            col0:       "ticker",
            "시가":     "open",
            "고가":     "high",
            "저가":     "low",
            "종가":     "close",
            "거래량":   "volume",
            "거래대금": "value",
        }
        raw = raw.rename(columns=rename_map)
        raw["date"]   = pd.to_datetime(date_str)
        raw["ticker"] = raw["ticker"].astype(str).str.zfill(6)

        for col in ["open", "high", "low", "close", "volume", "value"]:
            if col in raw.columns:
                raw[col] = pd.to_numeric(raw[col], errors="coerce")
            else:
                raw[col] = pd.NA

        return raw[["date", "ticker", "open", "high", "low", "close", "volume", "value"]]

    except Exception as e:
        print(f"  ⚠️  {date_str} 전체 조회 실패: {e}")
        return _empty_cache()


# ═══════════════════════════════════════════════════════════════════
# 캐시 업데이트 (핵심 함수)
# ═══════════════════════════════════════════════════════════════════
def update_kr_stock_cache(tickers):
    """
    한국 주식 캐시 업데이트 (v2.0 날짜별 일괄 방식)

    [기존 v1.0] 종목 루프: API 호출 = 종목수(~2883번) → 약 7분
    [신규 v2.0] 날짜 루프: API 호출 = 갱신 날짜수(보통 1~2번) → 약 10초

    흐름:
      parquet 없음 → 초기화 (날짜별 루프로 800일치 구축, 약 160번 호출)
      parquet 있음 → 캐시에 없는 날짜만 조회 (보통 1번)
    """
    _ensure_dir()
    today      = datetime.today()
    cache_df   = _load_cache(KR_CACHE_FILE)
    ticker_set = set(str(t).zfill(6) for t in tickers)

    # ── CASE 1: 최초 실행 (parquet 없음) ──────────────────────────
    if cache_df.empty:
        print(f"🆕 parquet 없음 → 최초 초기화 시작 ({INIT_CALENDAR_DAYS}일치)")
        print(f"   날짜별 일괄 조회 방식 (영업일 1개 = API 1번)")
        all_rows = []
        fetched  = 0
        d        = today

        for _ in range(INIT_CALENDAR_DAYS + 100):  # 공휴일 여유분 +100
            if fetched >= INIT_CALENDAR_DAYS:
                break
            date_str = d.strftime("%Y%m%d")
            d -= timedelta(days=1)

            day_df = _fetch_one_day(date_str)
            if day_df.empty:
                continue  # 휴장일 스킵

            day_df = day_df[day_df["ticker"].isin(ticker_set)]
            if not day_df.empty:
                all_rows.append(day_df)
            fetched += 1

            if fetched % 50 == 0:
                print(f"  진행중... {fetched}/{INIT_CALENDAR_DAYS}일")

        if all_rows:
            out_df = pd.concat(all_rows, ignore_index=True)
            out_df = _dedup_and_trim(out_df)
            _save_cache(out_df, KR_CACHE_FILE)
            print(f"✅ 초기화 완료: {fetched}일치 / {len(ticker_set)}개 종목")
            return out_df
        else:
            print("⚠️  초기화 실패: 데이터 없음")
            return _empty_cache()

    # ── CASE 2: 정상 갱신 (parquet 있음) ─────────────────────────
    exist_dates = set(cache_df["date"].dt.strftime("%Y%m%d").unique())

    # 최근 REFRESH_LOOKBACK 캘린더일 중 캐시에 없는 날짜만
    dates_to_fetch = []
    for i in range(REFRESH_LOOKBACK):
        d_str = (today - timedelta(days=i)).strftime("%Y%m%d")
        if d_str not in exist_dates:
            dates_to_fetch.append(d_str)

    if not dates_to_fetch:
        print(f"✅ 캐시 최신 상태 (갱신 불필요, 최근: {max(exist_dates)})")
        return cache_df

    print(f"📅 갱신 대상 날짜: {dates_to_fetch}")

    new_rows = []
    for date_str in dates_to_fetch:
        print(f"  📡 {date_str} 전체 종목 일괄 조회 중...")
        day_df = _fetch_one_day(date_str)

        if day_df.empty:
            print(f"  ⏭️  {date_str}: 데이터 없음 (휴장일)")
            continue

        day_df = day_df[day_df["ticker"].isin(ticker_set)]
        new_rows.append(day_df)
        print(f"  ✅ {date_str}: {len(day_df)}개 종목 수집")

    if new_rows:
        new_df = pd.concat(new_rows, ignore_index=True)
        out_df = pd.concat([cache_df, new_df], ignore_index=True)
        out_df = _dedup_and_trim(out_df)
        _save_cache(out_df, KR_CACHE_FILE)
        print(f"✅ 캐시 업데이트 완료! ({len(new_rows)}일치 추가)")
        return out_df
    else:
        print("✅ 신규 데이터 없음 (전부 휴장일)")
        return cache_df


# ═══════════════════════════════════════════════════════════════════
# 캐시 조회 (기존과 동일 - 변경 없음)
# ═══════════════════════════════════════════════════════════════════
def get_kr_stock_ohlcv(ticker, cache_df=None):
    """
    한국 주식 OHLCV 조회
    반환: date를 인덱스로 하는 DataFrame (컬럼: open, high, low, close, volume, value)
    """
    if cache_df is None:
        cache_df = _load_cache(KR_CACHE_FILE)

    ticker = str(ticker).zfill(6)
    df = cache_df[cache_df["ticker"] == ticker].copy()

    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "value"])

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")

    return df[["open", "high", "low", "close", "volume", "value"]].tail(KEEP_ROWS_PER_TICKER)


# ═══════════════════════════════════════════════════════════════════
# 테스트용 메인
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    test_tickers = ['005930', '000660']

    print("\n" + "=" * 60)
    print("🚀 한국 주식 캐시 업데이트 테스트")
    print("=" * 60)

    kr_cache = update_kr_stock_cache(test_tickers)

    print("\n[테스트] 005930 (삼성전자) 최근 3일:")
    print(get_kr_stock_ohlcv('005930', kr_cache).tail(3))

    print("\n[테스트] 000660 (SK하이닉스) 최근 3일:")
    print(get_kr_stock_ohlcv('000660', kr_cache).tail(3))
