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

def check_coloryp_condition(df):
    """
    chu_usa.py의 coloryp 로직 동일하게 적용
    """
    df['M0'] = df['close'].rolling(window=5).mean()
    df['M1'] = df['close'].rolling(window=10).mean()
    df['M2'] = df['close'].rolling(window=20).mean()
    df['M3'] = df['close'].rolling(window=60).mean()
    df['M4'] = df['close'].rolling(window=120).mean()

    df['m0s'] = np.where(df['M0'] >= df['M0'].shift(1), 1, -1)
    df['m1s'] = np.where(df['M1'] >= df['M1'].shift(1), 1, -1)
    df['m2s'] = np.where(df['M2'] >= df['M2'].shift(1), 1, -1)

    rad2degree = 180 / np.pi
    df['m0ang'] = np.sin(np.arctan((df['M0'] - df['M0'].shift(1)) / df['M0'].shift(1) * 100)) * rad2degree
    df['m1ang'] = np.sin(np.arctan((df['M1'] - df['M1'].shift(1)) / df['M1'].shift(1) * 100)) * rad2degree
    df['m2ang'] = np.sin(np.arctan((df['M2'] - df['M2'].shift(1)) / df['M2'].shift(1) * 100)) * rad2degree
    df['m3ang'] = np.sin(np.arctan((df['M3'] - df['M3'].shift(1)) / df['M3'].shift(1) * 100)) * rad2degree
    df['m4ang'] = np.sin(np.arctan((df['M4'] - df['M4'].shift(1)) / df['M4'].shift(1) * 100)) * rad2degree

    df['m3s'] = np.where((df['M3'] >= df['M3'].shift(1)) | (df['m3ang'] > -2), 1, -1)
    df['m4s'] = np.where((df['M4'] >= df['M4'].shift(1)) | (df['m4ang'] > -1), 1, -1)
    df['m3sm'] = np.where((df['M3'] <= df['M3'].shift(1)) | (df['m3ang'] < 2), -1, 1)

    condition1 = (df['m1s'] == 1) & (df['m2s'] == 1) & (df['m3s'] == 1)
    condition2 = (df['m1s'] == 1) & (df['m2s'] == 1)
    condition3 = (df['m0s'] == -1) & (df['m1s'] == -1) & (df['m2s'] == -1) & (df['m3sm'] == -1)
    condition4 = (df['m1s'] == -1) & (df['m2s'] == -1)

    df['HLd99'] = np.where(condition1, 2,
                    np.where(condition2, 1,
                    np.where(condition3, -2,
                    np.where(condition4, -1, 0))))
    df['HLv99'] = df['HLd99'].replace(0, np.nan).ffill().fillna(0)

    # RSI14 계산
    def calc_rsi(series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = -delta.clip(upper=0).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    df['rsi1'] = calc_rsi(df['close'], 14)
    df['rsi14'] = df['rsi1'].rolling(window=14).mean()

    # Stochastic 계산
    def calc_stoch(close, high, low, period):
        lowest_low = low.rolling(period).min()
        highest_high = high.rolling(period).max()
        return (close - lowest_low) / (highest_high - lowest_low) * 100
    
    df['k3'] = calc_stoch(df['close'], df['high'], df['low'], 20).rolling(10).mean()
    df['k2'] = calc_stoch(df['close'], df['high'], df['low'], 10).rolling(5).mean()

    cond_up = (df['k3'] > df['k3'].shift(1)) & (df['k2'] > df['k2'].shift(1)) & (df['rsi14'] >= df['rsi14'].shift(1))
    cond_down = (df['k3'] < df['k3'].shift(1)) & (df['k2'] < df['k2'].shift(1)) & (df['rsi14'] < df['rsi14'].shift(1))

    df['HLd71'] = np.where(cond_up, 1, np.where(cond_down, -1, 0))
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
    df['is_lime'] = (df['HLv99'] >= 1) & (df['HLv7'] == 1) & (df['HLv71'] == 1)
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
    2일 룸 신호 체크
    - 그저께 ❌ + 오늘 ✅ → 출력
    """
    if len(df) < 3:
        return "-"
    
    day_before_yesterday = df.iloc[-3]
    today = df.iloc[-1]
    
    # LIME 신호
    if today['is_lime'] and (not day_before_yesterday['is_lime']):
        return "🆕LIME"
    
    # GREEN 신호
    if today['is_green'] and (not day_before_yesterday['is_green']):
        return "🆕GRN"
    
    # RED 신호
    if today['is_red'] and (not day_before_yesterday['is_red']):
        return "🆕RED"
    
    return "-"


def calculate_signal(df):
    """
    TradingView Pine Script v5와 동일한 로직으로 sco99, sco 계산
    """
    import numpy as np

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

    m0s = (M0 >= M0.shift(1)).astype(int).replace(0, -1)
    m1s = (M1 >= M1.shift(1)).astype(int).replace(0, -1)
    m2s = (M2 >= M2.shift(1)).astype(int).replace(0, -1)
    m3s = ((M3 >= M3.shift(1)) | (m3ang > -2)).astype(int).replace(False, -1)
    m4s = ((M4 >= M4.shift(1)) | (m4ang > -1)).astype(int).replace(False, -1)

    m3sm = ((M3 <= M3.shift(1)) | (m3ang < 2)).astype(int).replace(False, -1) * -1
    m4sm = ((M4 <= M4.shift(1)) | (m4ang < 1)).astype(int).replace(False, -1) * -1

    close = df['close']

    s1 = (close >= M0).astype(int).replace(0, -1)
    s2 = (close >= M1).astype(int).replace(0, -1)
    s3 = (close >= M2).astype(int).replace(0, -1)
    s4 = (close >= M3).astype(int).replace(0, -1)
    s5 = (close >= M4).astype(int).replace(0, -1)

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

    def calculate_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    rsi1 = calculate_rsi(close, 14)
    rsi10_inner = rsi1.rolling(window=10).mean()
    rsi10 = rsi10_inner.rolling(window=3).mean()

    rsisco = (rsi10 >= 50).astype(int)

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


def _winsorize(series, lo=0.05, hi=0.95):
    """극단값(하위5%/상위95%) 클리핑 후 반환 — Final_score 수익률 정규화용."""
    s = series.copy()
    valid = s.dropna()
    if len(valid) < 5:
        return s
    return s.clip(valid.quantile(lo), valid.quantile(hi))


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
        "QQQ", "XLY", "XLC", "XLI", "XLV", "XLF", "XLP", "XLE", "XLB", "XLU",
        # ❤️ ETF 
        "MTUM", "IMTM", "EMGF", "SPMO", "QMOM", "PDP", "DWAS",
        "PTF", "VUG", "GMOM", "ACWV", "IUSV", "VTV",
        "QQQ", "IWM", "EWY", "EWJ", "INDA", "FXI", "VGK", "VWO", "SCZ", "FEZ",
        "XLB", "XLC", "XLE", "XLF", "XLI", "XLP", "XLU", "XLV", "XLY",
        "SOXX", "CARZ", "LIT", "SLX", "ITA",
        "ARKW", "BOTZ", "BETZ", "FDN", "AIQ", "SRVR", "PAVE", "PICK", "HDRO",
        "GLD", "SLV", "DBC", "DBA", "TLT", "SVXY", "ESGU", "IBIT"
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

    # ❤️ ETF
    etf_tickers = [
        "MTUM", "IMTM", "EMGF", "SPMO", "QMOM", "PDP", "DWAS",
        "PTF", "VUG", "GMOM", "ACWV", "IUSV", "VTV",
        "QQQ", "IWM", "EWY", "EWJ", "INDA", "FXI", "VGK", "VWO", "SCZ", "FEZ",
        "XLB", "XLC", "XLE", "XLF", "XLI", "XLP", "XLU", "XLV", "XLY",
        "SOXX", "CARZ", "LIT", "SLX", "ITA",
        "ARKW", "BOTZ", "BETZ", "FDN", "AIQ", "SRVR", "PAVE", "PICK", "HDRO",
        "GLD", "SLV", "DBC", "DBA", "TLT", "SVXY", "ESGU", "IBIT"
        ]
    for ticker in etf_tickers:
        industry_map[ticker] = "❤ ETF"


    end = datetime.today()
    start = end - timedelta(days=300)  # 120MA + 여유

    rows = []
    atr_filtered = []

    for ticker in US_STOCKS:
        try:
            df = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True
            )

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
            rtn   = (close.iloc[-1] / close.iloc[-61] - 1) * 100
            rtn20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else None

            today_chg = (
                (close.iloc[-1] / close.iloc[-2] - 1) * 100
                if len(close) > 1 else 0
            )

            latest_sco = (
                df_sig["sco"].dropna().iloc[-1]
                if not df_sig["sco"].dropna().empty else None
            )

            rows.append({
                "Ticker": ticker,
                "Industry": industry_map.get(ticker, 'Unknown'),
                "Signal_sco": latest_sco if latest_sco is not None else None,
                "수익률(%)": rtn if rtn is not None else None,
                "수익률20(%)": rtn20 if rtn20 is not None else None,
                "당일등락률(%)": today_chg if today_chg is not None else None,
                "종가": close.iloc[-1] if len(close) > 0 else None,
                "HighVol": is_high_volume,  # ✅ 추가
                "NewSig": new_signal         # ✅ 추가
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
    res["Norm_sco"]  = normalize_0_1(res["Signal_sco"])
    res["Norm_1M_w"] = normalize_0_1(_winsorize(res["수익률20(%)"].fillna(res["수익률20(%)"].min())))
    res["Norm_3M_w"] = normalize_0_1(_winsorize(res["수익률(%)"].fillna(res["수익률(%)"].min())))
    res["Final_score"] = res["Norm_sco"] * 0.55 + res["Norm_1M_w"] * 0.30 + res["Norm_3M_w"] * 0.15

    res = res.sort_values("Final_score", ascending=False).reset_index(drop=True)

    print("\n=== US Stock Momentum Top ===")

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

    print(display_df[["Ticker_Display", "Industry", "Signal_sco", "수익률(%)", "Final_score", "NewSig"]]
      .rename(columns={"Ticker_Display": "Ticker"})
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
    print(display_top4[["Ticker_Display", "Industry", "Signal_sco", "수익률(%)", "Final_score", "NewSig"]]
          .rename(columns={"Ticker_Display": "Ticker"})
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
    print(display_final[["Ticker_Display", "Industry", "Signal_sco", "수익률(%)", "Final_score", "NewSig"]]
          .rename(columns={"Ticker_Display": "Ticker"})
          .round(2)
          .to_string(index=False))
    with open(OUT, "w", encoding="utf-8") as f:
        for t in final_list:
            f.write(f"{t}\n")

    print(f"\n저장 완료: {OUT}")

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
