import yfinance as yf
#from pykrx import stock
import pandas as pd
from datetime import datetime, timedelta
import warnings
import requests
import json
import time
import os
#import config
import numpy as np  # calculate_signal에서 이미 사용 중이므로 상단에 명시
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coloryp_core import compute_lime_final, compute_hld71  # LIME 재진입 + HLv71 단일 소스
from us_ohlcv_cache import get_us_ohlcv, prefetch   # 미국 일봉 공유 캐시 (중복 다운로드 제거, auto_adjust=True)

def check_coloryp_condition(df):
    """
    chu_usa.py의 coloryp 로직 동일하게 적용
    """
    df['M0'] = df['close'].rolling(window=5).mean()
    df['M1'] = df['close'].rolling(window=10).mean()
    df['M2'] = df['close'].rolling(window=20).mean()
    df['M3'] = df['close'].rolling(window=60).mean()
    df['M4'] = df['close'].rolling(window=120).mean()

    df['m0s'] = np.where(df['M0'].isna() | df['M0'].shift(1).isna(), np.nan, np.where(df['M0'] >= df['M0'].shift(1), 1, -1))
    df['m1s'] = np.where(df['M1'].isna() | df['M1'].shift(1).isna(), np.nan, np.where(df['M1'] >= df['M1'].shift(1), 1, -1))
    df['m2s'] = np.where(df['M2'].isna() | df['M2'].shift(1).isna(), np.nan, np.where(df['M2'] >= df['M2'].shift(1), 1, -1))

    rad2degree = 180 / np.pi
    df['m0ang'] = np.sin(np.arctan((df['M0'] - df['M0'].shift(1)) / df['M0'].shift(1) * 100)) * rad2degree
    df['m1ang'] = np.sin(np.arctan((df['M1'] - df['M1'].shift(1)) / df['M1'].shift(1) * 100)) * rad2degree
    df['m2ang'] = np.sin(np.arctan((df['M2'] - df['M2'].shift(1)) / df['M2'].shift(1) * 100)) * rad2degree
    df['m3ang'] = np.sin(np.arctan((df['M3'] - df['M3'].shift(1)) / df['M3'].shift(1) * 100)) * rad2degree
    df['m4ang'] = np.sin(np.arctan((df['M4'] - df['M4'].shift(1)) / df['M4'].shift(1) * 100)) * rad2degree

    df['m3s'] = np.where(df['M3'].isna() | df['M3'].shift(1).isna(), np.nan, np.where((df['M3'] >= df['M3'].shift(1)) | (df['m3ang'] > -2), 1, -1))
    df['m4s'] = np.where(df['M4'].isna() | df['M4'].shift(1).isna(), np.nan, np.where((df['M4'] >= df['M4'].shift(1)) | (df['m4ang'] > -1), 1, -1))
    df['m3sm'] = np.where(df['M3'].isna() | df['M3'].shift(1).isna(), np.nan, np.where((df['M3'] <= df['M3'].shift(1)) | (df['m3ang'] < 2), -1, 1))

    condition1 = (df['m1s'] == 1) & (df['m2s'] == 1) & (df['m3s'] == 1)
    condition2 = (df['m1s'] == 1) & (df['m2s'] == 1)
    condition3 = (df['m0s'] == -1) & (df['m1s'] == -1) & (df['m2s'] == -1) & (df['m3sm'] == -1)
    condition4 = (df['m1s'] == -1) & (df['m2s'] == -1)

    df['HLd99'] = np.where(condition1, 2,
                    np.where(condition2, 1,
                    np.where(condition3, -2,
                    np.where(condition4, -1, 0))))
    df['HLv99'] = df['HLd99'].replace(0, np.nan).ffill().fillna(0)

    # RSI14 계산 (Wilder EWM 방식 - TradingView ta.rsi와 동일)
    def calc_rsi_wilder(series, period=14):
        delta = series.diff()
        u = delta.clip(lower=0)
        d = (-delta).clip(lower=0)
        rma_u = u.ewm(alpha=1/period, adjust=False).mean()
        rma_d = d.ewm(alpha=1/period, adjust=False).mean()
        rs = rma_u / rma_d
        return 100 - (100 / (1 + rs))

    df['rsi1'] = calc_rsi_wilder(df['close'], 14)
    df['rsi14'] = df['rsi1'].rolling(window=14).mean()

    # Stochastic 계산
    def calc_stoch(close, high, low, period):
        lowest_low = low.rolling(period).min()
        highest_high = high.rolling(period).max()
        return (close - lowest_low) / (highest_high - lowest_low) * 100
    
    df['k3'] = calc_stoch(df['close'], df['high'], df['low'], 20).rolling(10).mean()
    df['k2'] = calc_stoch(df['close'], df['high'], df['low'], 10).rolling(5).mean()

    # HLv71: cnt777/LL99 강제-숏 분기 포함 (coloryp_core 단일 소스) — 표==차트 일치 보장.
    #   복붙본엔 강제-숏이 빠져 고점 blowoff 후 급락 종목을 차트와 다르게 GREEN 유지하던 버그 있었음.
    df['HLd71'] = compute_hld71(df['close'], df['M0'], df['M2'], df['M3'], df['k3'], df['k2'], df['rsi14'])
    df['HLv71'] = df['HLd71'].replace(0, np.nan).ffill().fillna(0)

    df['aa'] = df['close'].rolling(window=60).mean()
    df['bb'] = df['close'].rolling(window=200).mean()
    df['aacol'] = np.where(df['aa'] >= df['aa'].shift(5), 1, -1)
    df['bbcol'] = np.where(df['bb'] >= df['bb'].shift(10), 1, -1)

    df['HLd7'] = np.where((df['aacol'] == 1) & (df['bbcol'] == 1), 1,
                 np.where((df['aacol'] == -1) & (df['bbcol'] == -1), -1, 0))
    df['HLv7'] = df['HLd7'].replace(0, np.nan).ffill().fillna(0)

    # 각도 조건
    angle_all = (df[['m0ang', 'm1ang', 'm2ang', 'm3ang', 'm4ang']] <= 0).all(axis=1)
    angle_4 = (df[['m0ang', 'm1ang', 'm2ang', 'm3ang']] <= 0).all(axis=1)

    # Color 상태
    df['is_lime'] = compute_lime_final(df['close'], df['HLv99'], df['HLv7'], df['HLv71'], df['M1'], df['M2'])
    df['is_green'] = (df['HLv99'] >= 1) & (df['HLv71'] == 1) & ~df['is_lime']
    df['is_red'] = ((df['HLv99'] <= -1) & (df['HLv71'] <= -1)) | angle_all | angle_4

    return df


def check_volume_intensity(df):
    """
    거래량 조건 체크:
    1. Vol5 > Vol60 × 1.2
    2. 거래대금 > $1,000,000 (100만 달러)
    """
    try:
        if 'volume' not in df.columns or 'close' not in df.columns:
            return False
        
        vol5 = df['volume'].rolling(window=5).mean().iloc[-1]
        vol60 = df['volume'].rolling(window=60).mean().iloc[-1]
        
        if pd.isna(vol5) or pd.isna(vol60) or vol60 <= 0:
            return False
        
        # 조건 1: Vol5 > Vol60 × 1.2
        cond1 = vol5 > (vol60 * 1.2)
        
        # 조건 2: 거래대금 > $1,000,000
        amount = df['close'].iloc[-1] * df['volume'].iloc[-1]
        cond2 = amount > 1_000_000
        
        return bool(cond1 and cond2)
        
    except Exception:
        return False


def get_new_signal(df):
    """
    전일 신호 체크
    - 전일 ❌ + 오늘 ✅ → 출력
    """
    if len(df) < 2:
        return "-"
    
    yesterday = df.iloc[-2]
    today = df.iloc[-1]
    
    # LIME 신호
    if today['is_lime'] and (not yesterday['is_lime']):
        return "🆕LIME"
    
    # GREEN 신호
    if today['is_green'] and (not yesterday['is_green']):
        return "🆕GRN"
    
    # RED 신호
    if today['is_red'] and (not yesterday['is_red']):
        return "🆕RED"
    
    return "-"


def calculate_signal(df):
    """
    TradingView Pine Script v5와 동일한 로직으로 sco99, sco 계산
    """
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift(1))
    low_close = abs(df['low'] - df['close'].shift(1))

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr5 = tr.rolling(window=5).mean()
    atr60 = tr.rolling(window=60).mean()

    df['atr5'] = atr5
    df['atr60'] = atr60
    df['atr_filter'] = atr5 > (atr60 * 1.8)

    M0 = df['close'].rolling(window=5).mean()
    M1 = df['close'].rolling(window=10).mean()
    M2 = df['close'].rolling(window=20).mean()
    M3 = df['close'].rolling(window=60).mean()
    M4 = df['close'].rolling(window=120).mean()

    rad = 180 / 3.141592653589793
    m0ang = np.sin(np.arctan((M0 - M0.shift(1)) / M0.shift(1) * 100)) * rad
    m1ang = np.sin(np.arctan((M1 - M1.shift(1)) / M1.shift(1) * 100)) * rad
    m2ang = np.sin(np.arctan((M2 - M2.shift(1)) / M2.shift(1) * 100)) * rad
    m3ang = np.sin(np.arctan((M3 - M3.shift(1)) / M3.shift(1) * 100)) * rad
    m4ang = np.sin(np.arctan((M4 - M4.shift(1)) / M4.shift(1) * 100)) * rad

    # #1 이동평균선 방향 (NaN 구간은 NaN 유지)
    m0s = pd.Series(np.where(M0.isna() | M0.shift(1).isna(), np.nan, np.where(M0 >= M0.shift(1), 1, -1)), index=df.index)
    m1s = pd.Series(np.where(M1.isna() | M1.shift(1).isna(), np.nan, np.where(M1 >= M1.shift(1), 1, -1)), index=df.index)
    m2s = pd.Series(np.where(M2.isna() | M2.shift(1).isna(), np.nan, np.where(M2 >= M2.shift(1), 1, -1)), index=df.index)
    m3s = pd.Series(np.where(M3.isna() | M3.shift(1).isna(), np.nan, np.where((M3 >= M3.shift(1)) | (m3ang > -2), 1, -1)), index=df.index)
    m4s = pd.Series(np.where(M4.isna() | M4.shift(1).isna(), np.nan, np.where((M4 >= M4.shift(1)) | (m4ang > -1), 1, -1)), index=df.index)

    m3sm = pd.Series(np.where(M3.isna() | M3.shift(1).isna(), np.nan, np.where((M3 <= M3.shift(1)) | (m3ang < 2), -1, 1)), index=df.index)
    m4sm = pd.Series(np.where(M4.isna() | M4.shift(1).isna(), np.nan, np.where((M4 <= M4.shift(1)) | (m4ang < 1), -1, 1)), index=df.index)

    close = df['close']

    # #2 종가와 이동평균선 비교 (NaN 구간은 NaN 유지)
    s1 = pd.Series(np.where(M0.isna() | close.isna(), np.nan, np.where(close >= M0, 1, -1)), index=df.index)
    s2 = pd.Series(np.where(M1.isna() | close.isna(), np.nan, np.where(close >= M1, 1, -1)), index=df.index)
    s3 = pd.Series(np.where(M2.isna() | close.isna(), np.nan, np.where(close >= M2, 1, -1)), index=df.index)
    s4 = pd.Series(np.where(M3.isna() | close.isna(), np.nan, np.where(close >= M3, 1, -1)), index=df.index)
    s5 = pd.Series(np.where(M4.isna() | close.isna(), np.nan, np.where(close >= M4, 1, -1)), index=df.index)

    jung = pd.Series(0, index=df.index)
    cond2 = (close >= M0) & (M0 >= M1) & (M1 >= M2) & (M2 >= M3) & (M3 >= M4)
    cond1 = (close >= M0) & (M0 >= M1) & (M1 >= M2) & (M2 >= M3)
    jung.loc[cond2] = 2
    jung.loc[~cond2 & cond1] = 1

    HLd99 = pd.Series(0, index=df.index)
    cond_HLd99_2 = (m1s == 1) & (m2s == 1) & (m3s == 1)
    cond_HLd99_1 = (m1s == 1) & (m2s == 1)
    cond_HLd99_m2 = (m0s == -1) & (m1s == -1) & (m2s == -1) & (m3sm == -1)
    cond_HLd99_m1 = (m1s == -1) & (m2s == -1)

    HLd99.loc[cond_HLd99_2] = 2
    HLd99.loc[~cond_HLd99_2 & cond_HLd99_1] = 1
    HLd99.loc[cond_HLd99_m2] = -2
    HLd99.loc[cond_HLd99_m1 & ~cond_HLd99_m2] = -1

    HLv99 = HLd99.mask(HLd99 == 0).ffill().fillna(0)

    # RSI: Wilder EWM 방식 (TradingView ta.rsi와 동일)
    def calculate_rsi_wilder(series, period=14):
        delta = series.diff()
        u = delta.clip(lower=0)
        d = (-delta).clip(lower=0)
        rma_u = u.ewm(alpha=1/period, adjust=False).mean()
        rma_d = d.ewm(alpha=1/period, adjust=False).mean()
        rs = rma_u / rma_d
        return 100 - (100 / (1 + rs))

    rsi1 = calculate_rsi_wilder(close, 14)
    rsi10_inner = rsi1.rolling(window=10).mean()
    rsi10 = rsi10_inner.rolling(window=3).mean()

    # #4 rsisco NaN 구간 처리
    rsisco = pd.Series(np.where(rsi10.isna(), np.nan, np.where(rsi10 >= 50, 1, 0)), index=df.index)

    new_high_flag = 0
    if len(df) >= 126:
        max_recent_3 = df['close'].iloc[-3:].max()
        max_past_6m = df['close'].iloc[-126:].max()
        if max_recent_3 >= max_past_6m:
            new_high_flag = 1
    else:
        max_recent_3 = df['close'].iloc[-3:].max()
        max_past = df['close'].max()
        if max_recent_3 >= max_past:
            new_high_flag = 1

    sco99 = (
        s1 + s2 + s3 + s4 + s5 +
        m0s + m1s + m2s + m3s + m4s +
        jung + HLd99 + rsisco + new_high_flag
    )

    sco = sco99.rolling(window=4).mean()
    df['sco'] = sco

    return df


def normalize_0_1(series):
    min_val = series.min()
    max_val = series.max()
    if max_val - min_val == 0:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - min_val) / (max_val - min_val)


def color_from_row(row):
    if bool(row.get("is_lime", False)):
        return "LIME"
    if bool(row.get("is_green", False)):
        return "GREEN"
    if bool(row.get("is_red", False)):
        return "RED"
    return "-"


def _pos_label(close_series):
    """종가와 이동평균 위치: 정배/역배/-"""
    c = close_series.iloc[-1]
    ma5 = close_series.rolling(5).mean().iloc[-1]
    ma10 = close_series.rolling(10).mean().iloc[-1]
    ma20 = close_series.rolling(20).mean().iloc[-1]
    ma60 = close_series.rolling(60).mean().iloc[-1]
    ma120 = close_series.rolling(120).mean().iloc[-1]
    if pd.isna(ma120):
        return "-"
    if c >= ma5 >= ma10 >= ma20 >= ma60 >= ma120:
        return "정배"
    if c <= ma5 <= ma10 <= ma20 <= ma60 <= ma120:
        return "역배"
    return "-"


def main():
    start_time = time.time()

    # US 개별주 티커 리스트
    US_STOCKS = sorted([
        # 📱 TECHNOLOGY
        "MSFT", "AAPL", "NVDA", "AVGO", "AMD", "INTC", "QCOM", "TXN", "ADI", "MU",
        "MPWR", "NXP", "MCHP", "ON", "ORCL", "PLTR", "SNPS", "CRWD", "FTNT", "CRM",
        "ADBE", "INTU", "CDNS", "NOW", "UBER", "ADP", "ADSK", "ROP", "TYL", "IBM",
        "DELL", "ANET", "HPQ", "WDC", "STX", "APH", "GLW", "TEL", "CSCO", "MSI",
        # 🛒 CONSUMER CYCLICAL
        "AMZN", "TSLA", "GM", "F", "HD", "LOW", "MCD", "SBUX", "CMG", "YUM",
        "BKNG", "ABNB", "RCL", "CCL", "MAR", "HLT", "NCLH", "TJX", "NKE", "AZO",
        # 📡 COMMUNICATION SERVICES
        "GOOG", "META", "NFLX", "DIS", "WBD", "TMUS", "VZ", "T", "APP",
        # 🏭 INDUSTRIALS
        "GE", "RTX", "BA", "LMT", "GD", "NOC", "CAT", "DE", "UNP", "CSX",
        "NSC", "ETN", "EMR", "ITW", "CMI", "IR", "ROK", "WM", "TT", "JCI",
        "CARR", "UPS", "FDX", "SPCX",
        # 🏥 HEALTHCARE
        "LLY", "JNJ", "MRK", "ABBV", "AMGN", "BMY", "PFE", "GILD", "UNH", "CVS",
        "CI", "ABT", "SYK", "MDT", "BSX", "EW", "TMO", "DHR", "IDXX", "BDX",
        "VRTX", "REGN",
        # 🏦 FINANCIALS
        "JPM", "BAC", "WFC", "C", "USB", "PNC", "AXP", "COF", "MS", "GS",
        "SCHW", "CME", "BLK", "BX", "KKR", "BRK-B", "PGR", "CB", "AIG", "AFL",
        "MET", "PRU", "ALL",
        # 🧺 CONSUMER DEFENSIVE
        "WMT", "COST", "KO", "PEP", "PG", "CL", "KMB", "PM", "MO",
        # ⚡ ENERGY
        "XOM", "CVX", "COP", "EOG", "OXY", "SLB",
        # 🏗 BASIC MATERIALS
        "LIN", "APD", "SHW", "CRH", "NEM", "GOLD",
        # 🔌 UTILITIES
        "NEE", "DUK", "SO", "AEP", "XEL", "PEG",
        "QQQ", "XLY", "XLC", "XLI", "XLV", "XLF", "XLP", "XLE", "XLB", "XLU"
    ])

    # Industry Map 생성
    industry_map = {}
    
    # 📱 TECHNOLOGY
    tech_tickers = [
        "MSFT", "AAPL", "NVDA", "AVGO", "AMD", "INTC", "QCOM", "TXN", "ADI", "MU",
        "MPWR", "NXP", "MCHP", "ON", "ORCL", "PLTR", "SNPS", "CRWD", "FTNT", "CRM",
        "ADBE", "INTU", "CDNS", "NOW", "UBER", "ADP", "ADSK", "ROP", "TYL", "IBM",
        "DELL", "ANET", "HPQ", "WDC", "STX", "APH", "GLW", "TEL", "CSCO", "MSI", "QQQ",
    ]
    for ticker in tech_tickers:
        industry_map[ticker] = "📱TECH"

    # 🛒 CONSUMER CYCLICAL
    consumer_cyc_tickers = [
        "AMZN", "TSLA", "GM", "F", "HD", "LOW", "MCD", "SBUX", "CMG", "YUM",
        "BKNG", "ABNB", "RCL", "CCL", "MAR", "HLT", "NCLH", "TJX", "NKE", "AZO", "XLY"
    ]
    for ticker in consumer_cyc_tickers:
        industry_map[ticker] = "🛒CONS"

    # 📡 COMMUNICATION SERVICES
    comm_tickers = ["GOOG", "META", "NFLX", "DIS", "WBD", "TMUS", "VZ", "T", "APP", "XLC"]
    for ticker in comm_tickers:
        industry_map[ticker] = "📡COMM"

    # 🏭 INDUSTRIALS
    industrial_tickers = [
        "GE", "RTX", "BA", "LMT", "GD", "NOC", "CAT", "DE", "UNP", "CSX",
        "NSC", "ETN", "EMR", "ITW", "CMI", "IR", "ROK", "WM", "TT", "JCI",
        "CARR", "UPS", "FDX", "SPCX", "XLI"
    ]
    for ticker in industrial_tickers:
        industry_map[ticker] = "🏭INDU"

    # 🏥 HEALTHCARE
    healthcare_tickers = [
        "LLY", "JNJ", "MRK", "ABBV", "AMGN", "BMY", "PFE", "GILD", "UNH", "CVS",
        "CI", "ABT", "SYK", "MDT", "BSX", "EW", "TMO", "DHR", "IDXX", "BDX","XLV",
        "VRTX", "REGN"
    ]
    for ticker in healthcare_tickers:
        industry_map[ticker] = "🏥HEAL"

    # 🏦 FINANCIALS
    financial_tickers = [
        "JPM", "BAC", "WFC", "C", "USB", "PNC", "AXP", "COF", "MS", "GS",
        "SCHW", "CME", "BLK", "BX", "KKR", "BRK-B", "PGR", "CB", "AIG", "AFL", "XLF",
        "MET", "PRU", "ALL"
    ]
    for ticker in financial_tickers:
        industry_map[ticker] = "🏦FINA"

    # 🧺 CONSUMER DEFENSIVE
    consumer_def_tickers = ["WMT", "COST", "KO", "PEP", "PG", "CL", "KMB", "PM", "MO", "XLP"]
    for ticker in consumer_def_tickers:
        industry_map[ticker] = "🧺DEFC"

    # ⚡ ENERGY
    energy_tickers = ["XOM", "CVX", "COP", "EOG", "OXY", "SLB", "XLE"]
    for ticker in energy_tickers:
        industry_map[ticker] = "⚡ENER"

    # 🏗 BASIC MATERIALS
    materials_tickers = ["LIN", "APD", "SHW", "CRH", "NEM", "GOLD", "XLB"]
    for ticker in materials_tickers:
        industry_map[ticker] = "🏗MATE"

    # 🔌 UTILITIES
    utility_tickers = ["NEE", "DUK", "SO", "AEP", "XEL", "PEG", "XLU"]
    for ticker in utility_tickers:
        industry_map[ticker] = "🔌UTIL"

    end = datetime.today()
    # ⚠️ HLv7 = SMA60(5봉상승) AND SMA200(10봉상승) → bb.shift(10) 이 유효하려면 최소 210 거래봉 필요.
    #   기존 300일(=약 206 거래봉)은 부족 → 마지막 봉 bb.shift(10)=NaN → bbcol=-1 → HLv7 붕괴 →
    #   실제 LIME 인 종목이 표에서 GREEN 으로 잘못 표기(EOG 사례). 차트(chart_popup_v4)는 캐시
    #   전체구간을 써서 정상 LIME → 표 vs 차트 불일치의 진짜 원인.
    #   → 차트가 쓰는 전체 캐시구간(upfront prefetch_us_all = 820일)과 동일 창으로 맞춰 일치 보장.
    #   집 bat 은 READONLY 라 창을 늘려도 캐시 슬라이스만 → 재다운로드 0(속도 무영향).
    start = end - timedelta(days=820)

    rows = []
    atr_filtered = []

    # 병렬 prefetch: US_STOCKS 배치 다운로드로 캐시 선충전 (값은 단일 yf.download 와 동일 검증됨).
    prefetch(US_STOCKS, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    for ticker in US_STOCKS:
        try:
            # 공유 캐시 사용 (중복 다운로드 제거). auto_adjust=True 기준 → 신호값 불변.
            df = get_us_ohlcv(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

            if df.empty or len(df) < 130:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.columns = df.columns.str.capitalize()

            if 'Close' in df.columns:
                df = df.rename(columns={"Close": "close", "High": "high", "Low": "low", "Volume": "volume"})
            elif 'close' not in df.columns:
                continue

            df_sig = calculate_signal(df)

            if df_sig['atr_filter'].iloc[-1]:
                atr_filtered.append({
                    'Ticker': ticker,
                    'Industry': industry_map.get(ticker, 'Unknown'),
                    'ATR5': df_sig['atr5'].iloc[-1],
                    'ATR60': df_sig['atr60'].iloc[-1],
                    'ATR비율': df_sig['atr5'].iloc[-1] / df_sig['atr60'].iloc[-1]
                })
                continue

            # ✅ coloryp 조건 체크
            df_sig = check_coloryp_condition(df_sig)
            
            # ✅ 거래량 체크
            is_high_volume = check_volume_intensity(df_sig)
            
            # ✅ 신규 신호 체크 (2일 룸)
            new_signal = get_new_signal(df_sig)

            close = df_sig["close"]
            rtn = (close.iloc[-1] / close.iloc[-61] - 1) * 100 if len(close) >= 61 else None

            today_chg = (
                (close.iloc[-1] / close.iloc[-2] - 1) * 100
                if len(close) > 1 else 0
            )

            latest_sco = (
                df_sig["sco"].dropna().iloc[-1]
                if not df_sig["sco"].dropna().empty else None
            )
            latest_row = df_sig.iloc[-1]
            color_state = color_from_row(latest_row)
            sco_vals = {}
            rtn_vals = {}
            color_vals = {}
            for bar_idx in range(3):
                pos = -1 - bar_idx
                sco_vals[f"sco_b{bar_idx}"] = (
                    float(df_sig["sco"].iloc[pos])
                    if len(df_sig) >= bar_idx + 1 and pd.notna(df_sig["sco"].iloc[pos]) else None
                )
                rtn_vals[f"rtn_b{bar_idx}"] = (
                    (close.iloc[pos] / close.iloc[pos - 60] - 1) * 100
                    if len(close) >= bar_idx + 61 else None
                )
                color_vals[f"color_b{bar_idx}"] = (
                    color_from_row(df_sig.iloc[pos])
                    if len(df_sig) >= bar_idx + 1 else "-"
                )

            rows.append({
                "Ticker": ticker,
                "Industry": industry_map.get(ticker, 'Unknown'),
                "Signal_sco": latest_sco if latest_sco is not None else None,
                "수익률(%)": rtn if rtn is not None else None,
                "당일등락률(%)": today_chg if today_chg is not None else None,
                "종가": close.iloc[-1] if len(close) > 0 else None,
                "HighVol": is_high_volume,  # ✅ 추가
                "NewSig": new_signal,        # ✅ 추가
                "Color": color_state,
                "Pos": _pos_label(close),
                **sco_vals,
                **rtn_vals,
                **color_vals,
            })

        except Exception as e:
            print(f"⚠️ {ticker} 처리 실패: {e}")
            continue
    if not rows:
        print("⚠️ 수집된 데이터가 없습니다.")
        return

    res = pd.DataFrame(rows)

    if res.empty or "Signal_sco" not in res.columns:
        print("⚠️ 유효한 결과 없음")
        return

    res = res.dropna(subset=["Signal_sco"]).copy()

    if res.empty:
        print("⚠️ Signal_sco가 있는 데이터가 없습니다.")
        return

    # =========================
    # 점수 정규화 + 최종 점수
    # =========================
    for bar_idx in range(3):
        sco_col = f"sco_b{bar_idx}"
        rtn_col = f"rtn_b{bar_idx}"
        norm_col = f"Norm_sco_b{bar_idx}"
        rank_col = f"Rank_rtn_b{bar_idx}"
        final_col = f"Final_score_b{bar_idx}"
        res[norm_col] = normalize_0_1(res[sco_col].fillna(res[sco_col].min()))
        res[rank_col] = res[rtn_col].fillna(res[rtn_col].min()).rank(pct=True)
        res[final_col] = res[norm_col] * 0.85 + res[rank_col] * 0.15
        res[f"OrderA_b{bar_idx}"] = (
            (res[sco_col] >= 11)
            & (res[final_col] >= 0.80)
            & (res[f"color_b{bar_idx}"].isin(["LIME", "GREEN"]))
        )

    res["Norm_sco"] = res["Norm_sco_b0"]
    res["Rank_rtn"] = res["Rank_rtn_b0"]
    res["Final_score"] = res["Final_score_b0"]
    res["OrderARecent2"] = (
        (res["OrderA_b0"] & ~res["OrderA_b1"])
        | (res["OrderA_b1"] & ~res["OrderA_b2"])
    )

    res = res.sort_values("Final_score", ascending=False).reset_index(drop=True)

    # ✅ 전체 유니버스 스냅샷 저장 (필터 없이 전 종목, TR 오더테이블 조회용)
    try:
        snapshot_tickers = {}
        for _, r in res.iterrows():
            snapshot_tickers[str(r["Ticker"])] = {
                "sco": round(float(r["Signal_sco"]), 2),
                "final": round(float(r["Final_score"]), 4),
                "rtn": round(float(r["수익률(%)"]), 2) if pd.notna(r["수익률(%)"]) else None,
                "pos": r.get("Pos", "-"),
                "color": r.get("Color", "-"),
            }
        snapshot_path = os.path.join(os.path.dirname(__file__), "us_finviz_all_signal_snapshot.json")
        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump({
                "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "count": len(snapshot_tickers),
                "tickers": snapshot_tickers,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ us_finviz_all_signal_snapshot.json 저장 실패: {e}")
    order_a_df = res[
        res["OrderARecent2"]
    ].head(10).copy()
    if not order_a_df.empty:
        order_a_df["Weight(%)"] = round(100.0 / len(order_a_df), 2)

    print("\n=== US Stock Momentum Top ===")

    # ─────────────────────────────────────────────────────────────────
    # report_us_finviz.txt 출력 (make_index_us_finviz.py 용)
    # ─────────────────────────────────────────────────────────────────
    REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_us_finviz.txt")

    # 신호별 종목 분류
    lime_list  = res[res["NewSig"] == "🆕LIME"].sort_values("Final_score", ascending=False)
    green_list = res[res["NewSig"] == "🆕GRN"].sort_values("Final_score", ascending=False)
    red_list   = res[res["NewSig"] == "🆕RED"].sort_values("Final_score", ascending=False)

    # MOM 돌파: is_lime 또는 is_green 상태인 종목 중 sco >= 11
    # (coloryp 결과는 df_sig 별로 계산됐으므로, NewSig 외에 상태 컬럼이 없음 →
    #  Signal_sco >= 12 & NewSig != RED 를 MOM 돌파 기준으로 사용)
    mom_list = res[(res["Signal_sco"] >= 11)].sort_values("Final_score", ascending=False)

    def df_to_report_lines(df):
        """DataFrame → report용 문자열 (헤더 포함)"""
        if df.empty:
            return "없음"
        header = f"{'Ticker':<8} {'Industry':<10} {'Price($)':>10} {'등락률(%)':>10} {'Sig_sco':>8} {'3M(%)':>8}"
        lines = [header]
        for _, row in df.iterrows():
            ticker_disp = f"{row['Ticker']}**" if row.get('HighVol') else f"{row['Ticker']}"
            price_val = row['종가'] if pd.notna(row.get('종가')) else 0.0
            chg_val = row['당일등락률(%)'] if pd.notna(row.get('당일등락률(%)')) else 0.0
            lines.append(
                f"{ticker_disp:<8} {str(row['Industry']):<10} {price_val:>10.2f} {chg_val:>+10.2f} {row['Signal_sco']:>8.2f} {row['수익률(%)']:>8.2f}"
            )
        return "\n".join(lines)

    report_lines = []
    report_lines.append(f"【MOM(모멘텀) 돌파】")
    report_lines.append(df_to_report_lines(mom_list))
    report_lines.append("")
    report_lines.append(f"【LIME 신호 (매수)】")
    report_lines.append(df_to_report_lines(lime_list))
    report_lines.append("")
    report_lines.append(f"【GREEN 신호 (관심)】")
    report_lines.append(df_to_report_lines(green_list))
    report_lines.append("")
    report_lines.append(f"【🔥 JUNG 정배열 돌파】")
    report_lines.append(df_to_report_lines(red_list))
    report_lines.append("")

    # ✅ Ticker 표시 수정 (** 추가, align 유지)
    display_df = res.head(30).copy()
    display_df['Ticker_Display'] = display_df.apply(
        lambda row: f"{row['Ticker']}**" if row['HighVol'] else f"{row['Ticker']}  ",
        axis=1
    )

#    print(display_df[["Ticker_Display", "Industry", "Signal_sco", "수익률(%)", "Final_score", "NewSig"]]
 #         .rename(columns={"Ticker_Display": "Ticker"})
  #        .round(2)
   #       .to_string(index=False))

    print(display_df[["Ticker_Display", "Industry", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "Final_score", "NewSig"]]
      .rename(columns={"Ticker_Display": "Ticker", "종가": "Price($)", "당일등락률(%)": "등락률(%)"})
      .round(2)
      .to_string(index=False, max_rows=None))  # max_rows=None 추가
    # -------------------------
    # 주문/보유 리스트 생성 (Top4 + 이전 Top4 유지)
    # 규칙:
    #  - 오늘 Top4는 무조건 포함
    #  - "이전 Top4" 중 오늘 Top4에서 밀려난 종목은 sco >= 11일 때만 유지
    #  - 최종 출력/저장은 Final_score 기준으로 정렬된 결과
    # -------------------------
    OUT = "D:/py/buy_us_stock.txt"

    def load_prev_top4(path: str) -> list[str]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        return []

    today_top4 = res.head(4)["Ticker"].tolist()
    prev_top4 = load_prev_top4(OUT)

    carryover = []
    for t in prev_top4:
        if t in today_top4:
            continue
        row = res[res["Ticker"] == t]
        if row.empty:
            continue
        sco_val = row.iloc[0]["Signal_sco"]
        if pd.notna(sco_val) and float(sco_val) >= 11:
            carryover.append(t)

    combined = []
    for t in today_top4 + carryover:
        if t not in combined:
            combined.append(t)

    final_df = res[res["Ticker"].isin(combined)].copy()
    final_df = final_df.sort_values("Final_score", ascending=False).reset_index(drop=True)
    final_list = final_df["Ticker"].tolist()

    print("\n=== 주문용 Top4 (오늘) ===")
    display_top4 = res.head(4).copy()
    display_top4['Ticker_Display'] = display_top4.apply(
        lambda row: f"{row['Ticker']}**" if row['HighVol'] else f"{row['Ticker']}  ",
        axis=1
    )
    print(display_top4[["Ticker_Display", "Industry", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "Final_score", "NewSig"]]
          .rename(columns={"Ticker_Display": "Ticker", "종가": "Price($)", "당일등락률(%)": "등락률(%)"})
          .round(2)
          .to_string(index=False))

    if prev_top4:
        print(f"\n이전 Top4: {prev_top4}")
    else:
        print("\n이전 Top4: 없음(첫 실행 또는 파일 없음)")

    if carryover:
        tmp = res[res["Ticker"].isin(carryover)][["Ticker", "Industry", "Signal_sco", "수익률(%)", "Final_score"]].copy()
        tmp = tmp.sort_values("Final_score", ascending=False)
        print("\n=== 유지된 이전 Top4 (오늘 Top4 탈락했지만 sco>=11) ===")
        print(tmp.round(2).to_string(index=False))
    else:
        print("\n=== 유지된 이전 Top4 없음 (조건: 오늘 Top4 탈락 & sco>=11) ===")

    print(f"\n=== 최종 리스트 ({len(final_list)}개) - Final_score 정렬 ===")
    display_final = final_df.copy()
    display_final['Ticker_Display'] = display_final.apply(
        lambda row: f"{row['Ticker']}**" if row['HighVol'] else f"{row['Ticker']}  ",
        axis=1
    )
    print(display_final[["Ticker_Display", "Industry", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "Final_score", "NewSig"]]
          .rename(columns={"Ticker_Display": "Ticker", "종가": "Price($)", "당일등락률(%)": "등락률(%)"})
          .round(2)
          .to_string(index=False))
    with open(OUT, "w", encoding="utf-8") as f:
        for t in final_list:
            f.write(f"{t}\n")

    print(f"\n저장 완료: {OUT}")

    # ─────────────────────────────────────────────────────────────────
    # report_us_finviz.txt 저장
    # 구성: 신호 블록(MOM/LIME/GREEN/JUNG) + 기존 콘솔 출력 내용
    # ─────────────────────────────────────────────────────────────────
    def _df_str(df_in, cols, rename=None):
        d = df_in[cols].copy()
        if rename:
            d = d.rename(columns=rename)
        return d.round(2).to_string(index=False, max_rows=None)

    console_sections = []
    console_sections.append("\n=== US Stock Momentum Top ===")
    console_sections.append(_df_str(
        display_df, ["Ticker_Display", "Industry", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "Final_score", "NewSig"],
        {"Ticker_Display": "Ticker", "종가": "Price($)", "당일등락률(%)": "등락률(%)"}
    ))
    console_sections.append("\n=== ORDER A max10 (equal weight) ===")
    console_sections.append("Ticker | Weight(%) | Industry | Price($) | 등락률(%) | sco | 3M(%) | Final | Color | NewSig")
    if order_a_df.empty:
        console_sections.append("None")
    else:
        for _, row in order_a_df.iterrows():
            ticker_disp = f"{row['Ticker']}**" if row["HighVol"] else f"{row['Ticker']}"
            console_sections.append(
                f"{ticker_disp} | {row['Weight(%)']:.2f} | {row['Industry']} | "
                f"{row['종가']:.2f} | {row['당일등락률(%)']:+.2f} | {row['Signal_sco']:.2f} | "
                f"{row['수익률(%)']:.2f} | {row['Final_score']:.2f} | {row['Color']} | {row['NewSig']}"
            )
    console_sections.append("\n=== 주문용 Top4 (오늘) ===")
    console_sections.append(_df_str(
        display_top4, ["Ticker_Display", "Industry", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "Final_score", "NewSig"],
        {"Ticker_Display": "Ticker", "종가": "Price($)", "당일등락률(%)": "등락률(%)"}
    ))
    if prev_top4:
        console_sections.append(f"\n이전 Top4: {prev_top4}")
    else:
        console_sections.append("\n이전 Top4: 없음(첫 실행 또는 파일 없음)")
    if carryover:
        tmp2 = res[res["Ticker"].isin(carryover)][["Ticker", "Industry", "Signal_sco", "수익률(%)", "Final_score"]].copy()
        tmp2 = tmp2.sort_values("Final_score", ascending=False)
        console_sections.append("\n=== 유지된 이전 Top4 (오늘 Top4 탈락했지만 sco>=11) ===")
        console_sections.append(tmp2.round(2).to_string(index=False))
    else:
        console_sections.append("\n=== 유지된 이전 Top4 없음 (조건: 오늘 Top4 탈락 & sco>=11) ===")
    console_sections.append(f"\n=== 최종 리스트 ({len(final_list)}개) - Final_score 정렬 ===")
    console_sections.append(_df_str(
        display_final, ["Ticker_Display", "Industry", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "Final_score", "NewSig"],
        {"Ticker_Display": "Ticker", "종가": "Price($)", "당일등락률(%)": "등락률(%)"}
    ))

    # report_us_finviz.txt 파일 직접 저장 (HTML 생성기 용)
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
            f.write("\n\n")
            f.write("\n".join(console_sections))
        print(f"저장 완료: {REPORT_PATH}")
    except PermissionError:
        print(f"⚠️ 권한 오류로 {REPORT_PATH}에 직접 저장하지 못했습니다. (배치파일 redirection 확인 필요)")
        # 콘솔에도 출력하여 캡처될 수 있게 함
        print("\n" + "\n".join(report_lines))
        print("\n" + "\n".join(console_sections))

    print(f"저장 완료: {REPORT_PATH}")

    if atr_filtered:
        print("\n" + "=" * 80)
        print("🚫 ATR 필터로 제외된 종목 (고변동성: ATR5 > ATR60 * 1.8)")
        print("=" * 80)
        atr_df = pd.DataFrame(atr_filtered)
        atr_df = atr_df.sort_values('ATR비율', ascending=False)
        print(atr_df.to_string(index=False))
        print(f"\n제외된 종목 수: {len(atr_filtered)}개")
    else:
        print("\n✅ ATR 필터로 제외된 종목 없음")

    print("\n" + "=" * 80)
    print("📊 Signal_sco 기준 종목 분포")
    print("=" * 80)
    
    strong_stocks = res[res["Signal_sco"] >= 12]
    weak_stocks = res[res["Signal_sco"] < 0]
    
    print(f"\n전체 US_STOCKS: {len(US_STOCKS)}개")
    print(f"  sco >= 12: {len(strong_stocks)}개 ({len(strong_stocks)/len(res)*100:.1f}%)")
    print(f"  0 <= sco < 12: {len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])}개 ({len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])/len(res)*100:.1f}%)")
    print(f"  sco < 0: {len(weak_stocks)}개 ({len(weak_stocks)/len(res)*100:.1f}%)")
    print(f"\n합계 검증: {len(strong_stocks) + len(weak_stocks) + len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])} == {len(res)}?")

    print(f"\n[실행 시간] {time.time() - start_time:.2f}초")


if __name__ == "__main__":
    main()
