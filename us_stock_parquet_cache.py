# -*- coding: utf-8 -*-
"""
US Stock Parquet Cache System
미국 주식 OHLCV 데이터를 Parquet으로 캐싱하여 반복 다운로드 방지
"""
import os
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf


# ═══════════════════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════════════════
CACHE_DIR = r"D:\py\report-us"
US_CACHE_FILE = os.path.join(CACHE_DIR, "stock_us_ohlcv.parquet")

KEEP_ROWS_PER_TICKER = 500   # 종목당 최대 500일 보관
US_REFRESH_DAYS = 2          # 미국: 당일 + 1일 재조회 (시차 고려)
INIT_CALENDAR_DAYS = 800     # 최초 1회: 넉넉하게 800일


# ═══════════════════════════════════════════════════════════════════
# 내부 유틸리티
# ═══════════════════════════════════════════════════════════════════
def _ensure_dir():
    """캐시 디렉토리 생성"""
    os.makedirs(CACHE_DIR, exist_ok=True)


def _empty_cache():
    """빈 캐시 DataFrame"""
    return pd.DataFrame(columns=[
        "date", "ticker", "open", "high", "low", "close", "volume", "value"
    ])


def _load_cache(path):
    """Parquet 캐시 로드"""
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
    """Parquet 캐시 저장"""
    if df is None or df.empty:
        return
    
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    out.to_parquet(path, index=False)


def _dedup_and_trim(df):
    """중복 제거 및 종목당 최대 행수 제한"""
    if df is None or df.empty:
        return _empty_cache()
    
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])
    
    # 같은 날짜는 최신 것만 유지 (당일 재실행 대응)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    
    # 종목당 최근 N개 행만 유지
    df = (
        df.groupby("ticker", group_keys=False)
          .tail(KEEP_ROWS_PER_TICKER)
          .reset_index(drop=True)
    )
    return df


def _normalize_us_df(raw_df, ticker):
    """yfinance DataFrame → 표준 컬럼명 변환"""
    if raw_df is None or raw_df.empty:
        return _empty_cache()
    
    try:
        df = raw_df.copy()
        
        # yfinance 멀티컬럼 처리
        df.columns = [
            c[0].lower() if isinstance(c, tuple) else str(c).lower()
            for c in df.columns
        ]
        
        df = df.reset_index()
        date_col = df.columns[0]
        df = df.rename(columns={
            date_col: "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        })
        
        # 필수 컬럼 확인
        need_cols = ["date", "open", "high", "low", "close", "volume"]
        for c in need_cols:
            if c not in df.columns:
                return _empty_cache()
        
        df["value"] = pd.NA
        df["ticker"] = str(ticker)
        
        # 필수 컬럼만 선택하고 명시적으로 타입 지정
        result = df[["date", "ticker", "open", "high", "low", "close", "volume", "value"]].copy()
        
        # 안전한 타입 변환
        result["date"] = pd.to_datetime(result["date"])
        result["ticker"] = result["ticker"].astype(str)
        for col in ["open", "high", "low", "close", "volume", "value"]:
            result[col] = pd.to_numeric(result[col], errors='coerce')
        
        return result
        
    except Exception as e:
        print(f"  ⚠️  {ticker}: 데이터 정규화 실패 - {e}")
        return _empty_cache()


# ═══════════════════════════════════════════════════════════════════
# 캐시 업데이트 (미국 주식)
# ═══════════════════════════════════════════════════════════════════
def update_us_stock_cache(tickers):
    """
    미국 주식 캐시 업데이트
    - 기존 종목: 당일 + 1일 재조회 (시차 고려)
    - 신규 종목: 800일치 조회
    """
    _ensure_dir()
    today = datetime.today()
    cache_df = _load_cache(US_CACHE_FILE)
    
    merged_list = []
    exist_tickers = set(cache_df["ticker"].unique()) if not cache_df.empty else set()
    
    total = len(tickers)
    for idx, ticker in enumerate(tickers, 1):
        ticker = str(ticker)
        
        # 조회 시작일 결정
        if ticker not in exist_tickers:
            # 신규 종목: 넉넉하게
            from_dt = today - timedelta(days=INIT_CALENDAR_DAYS)
            print(f"  [{idx}/{total}] 🆕 {ticker}: 최초 조회 ({INIT_CALENDAR_DAYS}일)")
        else:
            # 기존 종목: 최근 2일 재조회 (시차 고려)
            tdf = cache_df[cache_df["ticker"] == ticker]
            last_dt = pd.to_datetime(tdf["date"]).max()
            from_dt = min(
                today - timedelta(days=US_REFRESH_DAYS),
                last_dt.to_pydatetime() - timedelta(days=1)
            )
            if idx % 50 == 0:  # 50개마다 진행상황 출력
                print(f"  [{idx}/{total}] ♻️  {ticker}: 업데이트 중...")
        
        # yfinance로 데이터 받기
        try:
            raw = yf.download(
                ticker,
                start=from_dt.strftime("%Y-%m-%d"),
                end=(today + timedelta(days=1)).strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=False,
                group_by="column",
                threads=False,
            )
            new_df = _normalize_us_df(raw, ticker)
        except Exception as e:
            if idx % 100 == 0:  # 에러도 너무 많으면 100개마다만 출력
                print(f"  ⚠️  {ticker}: yfinance 조회 실패 - {e}")
            new_df = _empty_cache()
        
        # 기존 데이터와 병합
        old_df = cache_df[cache_df["ticker"] == ticker] if not cache_df.empty else _empty_cache()
        
        # 안전한 concat을 위해 빈 DataFrame 체크
        if old_df.empty and new_df.empty:
            one_df = _empty_cache()
        elif old_df.empty:
            one_df = new_df
        elif new_df.empty:
            one_df = old_df
        else:
            # 두 DataFrame 모두 데이터가 있을 때만 concat
            try:
                one_df = pd.concat([old_df, new_df], ignore_index=True)
            except Exception as e:
                print(f"  ⚠️  {ticker}: concat 실패, 새 데이터만 사용 - {e}")
                one_df = new_df
        
        one_df = _dedup_and_trim(one_df)
        merged_list.append(one_df)
    
    # 전체 병합 및 저장
    out_df = pd.concat(merged_list, ignore_index=True) if merged_list else _empty_cache()
    out_df = _dedup_and_trim(out_df)
    _save_cache(out_df, US_CACHE_FILE)
    
    print(f"✅ 미국 주식 캐시 업데이트 완료: {len(tickers)}개 종목")
    return out_df


# ═══════════════════════════════════════════════════════════════════
# 캐시 조회
# ═══════════════════════════════════════════════════════════════════
def get_us_stock_ohlcv(ticker, cache_df=None):
    """
    미국 주식 OHLCV 조회
    반환: date를 인덱스로 하는 DataFrame (컬럼: open, high, low, close, volume, value)
    """
    if cache_df is None:
        cache_df = _load_cache(US_CACHE_FILE)
    
    ticker = str(ticker)
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
    # 테스트 (Apple, Microsoft)
    test_tickers = ['AAPL', 'MSFT']
    
    print("\n" + "=" * 60)
    print("🚀 미국 주식 캐시 업데이트 시작")
    print("=" * 60)
    
    us_cache = update_us_stock_cache(test_tickers)
    
    print("\n[테스트] AAPL 데이터 조회:")
    df_aapl = get_us_stock_ohlcv('AAPL', us_cache)
    print(df_aapl.tail())
    
    print("\n[테스트] MSFT 데이터 조회:")
    df_msft = get_us_stock_ohlcv('MSFT', us_cache)
    print(df_msft.tail())
