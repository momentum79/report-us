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
import math
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coloryp_core import compute_lime_final  # LIME 재진입 단일 소스
from us_ohlcv_cache import get_us_ohlcv, prefetch   # 미국 일봉 공유 캐시 (중복 다운로드 제거, auto_adjust=True)

# =========================
# 투자비중 관리 설정 (US 전용)
# =========================
total_investment = 10000  # $10,000

import sys
import io

class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            f.write(obj)
    def flush(self):
        for f in self.files:
            f.flush()

# UTF-8 설정
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except: pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except: pass

HOLDING_FILE = "D:\\py\\buy_us_etf_holding.txt"
OUTPUT_FILE  = "D:\\py\\buy_us_etf.txt"
TRADE_LOG_FILE = "D:\\py\\trade_log.csv"
NASDAQ_UP_DAYS_FILE = "D:\\py\\report-us\\nasdaq_up_days.json"

TOP3_MIN_SCO = 11.0
TOP3_ALLOC_WEIGHTS = [0.40, 0.35, 0.25]  # Top1 / Top2 / Top3

ALLOCATION_MAP = {
    1: [100],
    2: [55, 45],
    3: [45, 30, 25],
    4: [35, 30, 25, 10],
    5: [33, 27, 20, 10, 10],
    6: [31, 25, 16, 10, 10, 8],
}

BANK_ETF_GROUP = {"KBE", "KRE"}

TREND_MULTIPLIER = {
    "LIME":   1.0,
    "GREEN":  0.8,
    "-":      0.4,
    "PURPLE": 0.1,
    "RED":    0.0,
}

# ──────────────────────────────────────────────────────────────────
# Soft multiplier / FIXED cap 설정
# ──────────────────────────────────────────────────────────────────
INDIV_FLOOR_MIN = 0.20
INDIV_FLOOR_MAX = 0.65
FIXED_CAP_RATIO_WHEN_WEAK = 0.40   # 약세장 시 FIXED 자산 총합 상한 (40%)
FIXED_CAP_TRIGGER_MULT    = 0.40   # 이 multiplier 이하면 "약세장"으로 판단

import sys
import io


# Force UTF-8 for stdout/stderr to avoid encoding errors on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def sma(s, n):
    return s.rolling(n).mean()

def calculate_rsi_wilder(s, n=14):
    # Pine Script ta.rsi() 완전 동일 구현
    # u = math.max(x - x[1], 0)  -> upward change
    # d = math.max(x[1] - x, 0)  -> downward change
    # rs = ta.rma(u, y) / ta.rma(d, y)   (ta.rma = EWM alpha=1/n, adjust=False)
    delta = s.diff()
    u = delta.clip(lower=0)           # math.max(x - x[1], 0)
    d = (-delta).clip(lower=0)        # math.max(x[1] - x, 0)
    rma_u = u.ewm(alpha=1/n, adjust=False).mean()
    rma_d = d.ewm(alpha=1/n, adjust=False).mean()
    rs = rma_u / rma_d
    return 100 - (100 / (1 + rs))

def stoch(close, high, low, n):
    ll = low.rolling(n).min()
    hh = high.rolling(n).max()
    return (close - ll) / (hh - ll) * 100

def calculate_tv_signals(df):
    """
    TradingView 저/저2 신호 계산
    1. '저' 신호 (buystat): k3가 20 돌파 + k2 상승
    2. '저2' 신호 (constat): 극심한 과매도 → 벗어남
    
    오늘 또는 어제 신호 발생하면 표시 (2일간)
    """
    if len(df) < 4:  # 최소 4일 데이터 필요
        return "-", "-"
    
    # 컬럼명 통일
    df_copy = df.copy()
    if 'Close' in df_copy.columns:
        df_copy.rename(columns={'Close': 'close', 'High': 'high', 'Low': 'low'}, inplace=True)
    
    # k2, k3 계산
    k3 = sma(stoch(df_copy['close'], df_copy['high'], df_copy['low'], 20), 10)
    k2 = sma(stoch(df_copy['close'], df_copy['high'], df_copy['low'], 10), 5)
    
    df_copy['k2'] = k2
    df_copy['k3'] = k3
    
    # buystat 계산
    buystat = (k3 >= 20) & (k3.shift(1) < 20) & (k2 >= k2.shift(1))
    
    # RSI 계산
    rsi1 = calculate_rsi_wilder(df_copy['close'])
    df_copy['rsi1'] = rsi1
    
    # SMI 계산
    ll = df_copy['low'].rolling(window=10).min()
    hh = df_copy['high'].rolling(window=10).max()
    diff = hh - ll
    rdiff = df_copy['close'] - (hh + ll) / 2
    
    # Double SMA (Pine Script와 일치)
    avgrel = rdiff.rolling(3).mean().rolling(3).mean()
    avgdiff = diff.rolling(3).mean().rolling(3).mean()

    # SMI
    SMI = (avgrel / (avgdiff / 2) * 100).fillna(0)
    SMIsignal = SMI.rolling(3).mean()
    emasignal = SMI.rolling(10).mean()
    
    # constat 계산 (극심한 침체기 판단)
    constat = (SMIsignal <= -60) & (emasignal <= -60) & (rsi1 <= 30)
    
    # ========== 보강된 신호 판독 로직 ==========
    # '저' 신호: buystat이 오늘 또는 어제 True인 경우
    jeo_signal = "-"
    if buystat.iloc[-1] or buystat.iloc[-2]:
        jeo_signal = "저"
    
    # '저2' 신호: 과매도권(constat)을 벗어나는 턴 어라운드 시점 포착
    # 오늘 탈출 = 어제는 침체(True)였는데 오늘은 탈출(False)
    signal_today = constat.iloc[-2] and (not constat.iloc[-1])
    # 어제 탈출 = 그저께는 침체(True)였는데 어제는 탈출(False)
    signal_yesterday = constat.iloc[-3] and (not constat.iloc[-2])
    
    jeo2_signal = "-"
    if signal_today or signal_yesterday:
        jeo2_signal = "저2"
    
    return jeo_signal, jeo2_signal

def check_coloryp_logic(df):
    df = df.copy()
    df['M0'], df['M1'], df['M2'], df['M3'], df['M4'] = (
        sma(df.close, 5), sma(df.close, 10), sma(df.close, 20),
        sma(df.close, 60), sma(df.close, 120)
    )
    df['m0s'] = np.where(df.M0.isna() | df.M0.shift(1).isna(), np.nan, np.where(df.M0 >= df.M0.shift(1), 1, -1))
    df['m1s'] = np.where(df.M1.isna() | df.M1.shift(1).isna(), np.nan, np.where(df.M1 >= df.M1.shift(1), 1, -1))
    df['m2s'] = np.where(df.M2.isna() | df.M2.shift(1).isna(), np.nan, np.where(df.M2 >= df.M2.shift(1), 1, -1))
    rad = 180 / np.pi
    for i in range(5):
        df[f'm{i}ang'] = np.sin(np.arctan((df[f"M{i}"] - df[f"M{i}"].shift(1)) / df[f"M{i}"].shift(1) * 100)) * rad
    df['m3s'] = np.where(df.M3.isna() | df.M3.shift(1).isna(), np.nan, np.where((df.M3 >= df.M3.shift(1)) | (df.m3ang > -2), 1, -1))
    df['m4s'] = np.where(df.M4.isna() | df.M4.shift(1).isna(), np.nan, np.where((df.M4 >= df.M4.shift(1)) | (df.m4ang > -1), 1, -1))
    df['m3sm'] = np.where(df.M3.isna() | df.M3.shift(1).isna(), np.nan, np.where((df.M3 <= df.M3.shift(1)) | (df.m3ang < 2), -1, 1))
    df['HLd99'] = np.where((df.m1s == 1) & (df.m2s == 1) & (df.m3s == 1), 2,
                  np.where((df.m1s == 1) & (df.m2s == 1), 1,
                  np.where((df.m0s == -1) & (df.m1s == -1) & (df.m2s == -1) & (df.m3sm == -1), -2,
                  np.where((df.m1s == -1) & (df.m2s == -1), -1, 0))))
    df['HLv99'] = df.HLd99.replace(0, np.nan).ffill().fillna(0)
    # RSI: Wilder EWM 방식 (Pine Script ta.rsi() 완전 동일)
    df['rsi1'] = calculate_rsi_wilder(df.close)
    df['rsi14'] = sma(df.rsi1, 14)
    df['k3'] = sma(stoch(df.close, df.high, df.low, 20), 10)
    df['k2'] = sma(stoch(df.close, df.high, df.low, 10), 5)

    # ── HLv2 (고점x) — Pine 원본 반영 ──
    # frank/srank/trank = percentrank(220), HLd2 = 셋 다 >=95
    # HLv2 = 전봉 HLd2==True and trank 하락 중
    def _prank(series, length):
        def _r(arr): return np.sum(arr[:-1] <= arr[-1]) / length * 100
        return series.rolling(length + 1).apply(_r, raw=True)

    _frank = _prank(100 * (df.close - df.M3) / df.close, 220)
    _srank = _prank(100 * (df.close - df.M2) / df.close, 220)
    _trank = _prank(100 * (df.close - df.M0) / df.close, 220)
    _HLd2  = (_frank >= 95) & (_srank >= 95) & (_trank >= 95)
    _HLv2  = (_HLd2.shift(1) == True) & (_trank <= _trank.shift(1)) & (_trank.shift(1) <= _trank.shift(2))

    # ── LL99, cnt777 — Pine 원본 반영 ──
    # LL99   := HLv2==1 ? close : nz(LL99[1])
    # cnt777 := HLv2==1 ? 0    : nz(cnt777[1]) + 1
    _LL99   = pd.Series(np.nan, index=df.index)
    _cnt777 = pd.Series(0.0,    index=df.index)
    for _i in range(len(df)):
        if _HLv2.iloc[_i]:
            _LL99.iloc[_i]   = df.close.iloc[_i]
            _cnt777.iloc[_i] = 0.0
        else:
            _LL99.iloc[_i]   = _LL99.iloc[_i-1]   if _i > 0 and not pd.isna(_LL99.iloc[_i-1]) else np.nan
            _cnt777.iloc[_i] = (_cnt777.iloc[_i-1] + 1) if _i > 0 else 0.0

    # ── HLd71 — Pine 완전 동일 (cnt777/LL99 기반 강제 -1 포함) ──
    # Pine:
    #   iff_2 = (k3<k3[1] and k2<k2[1] and rsi14<rsi14[1])
    #           or (cnt777<60 and close<LL99*0.96) ? -1 : 0
    #   HLd71 = k3>k3[1] and k2>k2[1] and rsi14>=rsi14[1] ? 1 : iff_2
    _cond_long  = (df.k3 > df.k3.shift(1)) & (df.k2 > df.k2.shift(1)) & (df.rsi14 >= df.rsi14.shift(1))
    _cond_short = (
        ((df.k3 < df.k3.shift(1)) & (df.k2 < df.k2.shift(1)) & (df.rsi14 < df.rsi14.shift(1))) |
        ((_cnt777 < 60) & (df.close < _LL99 * 0.96))
    )
    # np.select: long 우선 (Pine 삼항 동일)
    df['HLd71'] = np.select([_cond_long, _cond_short], [1, -1], default=0)
    df['HLv71'] = df.HLd71.replace(0, np.nan).ffill().fillna(0)
    df['aa'], df['bb'] = sma(df.close, 60), sma(df.close, 200)
    df['HLd7'] = np.where((df.aa >= df.aa.shift(5)) & (df.bb >= df.bb.shift(10)), 1,
                 np.where((df.aa < df.aa.shift(5)) & (df.bb < df.bb.shift(10)), -1, 0))
    df['HLv7'] = df.HLd7.replace(0, np.nan).ffill().fillna(0)
    # TV: sum = m0ang + m1ang + m2ang + m3ang + m4ang (5개 이평 각도 합)
    df['ang_sum'] = df['m0ang'] + df['m1ang'] + df['m2ang'] + df['m3ang'] + df['m4ang']
    df['lime_final'] = compute_lime_final(df.close, df.HLv99, df.HLv7, df.HLv71, df.M1, df.M2)
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
    2일 룸 신호 체크 (check_coloryp_logic 기반 trend_val 방식)
    - 그저께 → 오늘 추세 변화 감지
    """
    if len(df) < 3:
        return "-"

    def _trend(row):
        angle_tol  = all(row.get(f'm{i}ang', 0) <= 0 for i in range(5))
        angle_tol2 = all(row.get(f'm{i}ang', 0) <= 0 for i in range(4))
        hv9  = row.get('HLv99', 0)
        hv7  = row.get('HLv7',  0)
        hv71 = row.get('HLv71', 0)
        if row.get('lime_final'):
            return "LIME"
        elif hv9 >= 1 and hv71 == 1:
            return "GREEN"
        elif (hv9 <= -1 and hv7 == -1 and hv71 == -1) or angle_tol:
            return "RED"
        elif (hv9 <= -1 and hv71 == -1) or angle_tol2:
            return "PURPLE"
        return "-"

    t_prev = _trend(df.iloc[-3])
    t_now  = _trend(df.iloc[-1])

    if t_now == "LIME"   and t_prev != "LIME":   return "🆕LIME"
    if t_now == "GREEN"  and t_prev != "GREEN":  return "🆕GRN"
    if t_now == "RED"    and t_prev != "RED":    return "🆕RED"
    return "-"


def calculate_signal(df):
    """
    jasantop4_final.py와 동일한 로직으로 sco99, sco 계산
    sco99 = 지표 합산 (최대 16점), sco = sco99.rolling(4).mean()
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
    df['atr_filter'] = atr5 > (atr60 * 1.9)

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

    # 이동평균선 방향 (NaN 구간은 NaN 유지)
    m0s = pd.Series(np.where(M0.isna() | M0.shift(1).isna(), np.nan, np.where(M0 >= M0.shift(1), 1, -1)), index=df.index)
    m1s = pd.Series(np.where(M1.isna() | M1.shift(1).isna(), np.nan, np.where(M1 >= M1.shift(1), 1, -1)), index=df.index)
    m2s = pd.Series(np.where(M2.isna() | M2.shift(1).isna(), np.nan, np.where(M2 >= M2.shift(1), 1, -1)), index=df.index)
    m3s = pd.Series(np.where(M3.isna() | M3.shift(1).isna(), np.nan, np.where((M3 >= M3.shift(1)) | (m3ang > -2), 1, -1)), index=df.index)
    m4s = pd.Series(np.where(M4.isna() | M4.shift(1).isna(), np.nan, np.where((M4 >= M4.shift(1)) | (m4ang > -1), 1, -1)), index=df.index)
    m3sm = pd.Series(np.where(M3.isna() | M3.shift(1).isna(), np.nan, np.where((M3 <= M3.shift(1)) | (m3ang < 2), -1, 1)), index=df.index)
    m4sm = pd.Series(np.where(M4.isna() | M4.shift(1).isna(), np.nan, np.where((M4 <= M4.shift(1)) | (m4ang < 1), -1, 1)), index=df.index)

    close = df['close']

    # 종가 vs 이평 비교 (NaN 구간은 NaN 유지)
    s1 = pd.Series(np.where(M0.isna() | close.isna(), np.nan, np.where(close >= M0, 1, -1)), index=df.index)
    s2 = pd.Series(np.where(M1.isna() | close.isna(), np.nan, np.where(close >= M1, 1, -1)), index=df.index)
    s3 = pd.Series(np.where(M2.isna() | close.isna(), np.nan, np.where(close >= M2, 1, -1)), index=df.index)
    s4 = pd.Series(np.where(M3.isna() | close.isna(), np.nan, np.where(close >= M3, 1, -1)), index=df.index)
    s5 = pd.Series(np.where(M4.isna() | close.isna(), np.nan, np.where(close >= M4, 1, -1)), index=df.index)

    # 정배열
    jung = pd.Series(0, index=df.index)
    cond2 = (close >= M0) & (M0 >= M1) & (M1 >= M2) & (M2 >= M3) & (M3 >= M4)
    cond1 = (close >= M0) & (M0 >= M1) & (M1 >= M2) & (M2 >= M3)
    jung.loc[cond2] = 2
    jung.loc[~cond2 & cond1] = 1

    # HLd99
    HLd99 = pd.Series(0, index=df.index)
    cond_HLd99_2  = (m1s == 1) & (m2s == 1) & (m3s == 1)
    cond_HLd99_1  = (m1s == 1) & (m2s == 1)
    cond_HLd99_m2 = (m0s == -1) & (m1s == -1) & (m2s == -1) & (m3sm == -1)
    cond_HLd99_m1 = (m1s == -1) & (m2s == -1)
    HLd99.loc[cond_HLd99_2] = 2
    HLd99.loc[~cond_HLd99_2 & cond_HLd99_1] = 1
    HLd99.loc[cond_HLd99_m2] = -2
    HLd99.loc[cond_HLd99_m1 & ~cond_HLd99_m2] = -1
    HLv99 = HLd99.replace(0, np.nan).ffill().fillna(0)

    # RSI
    rsi1 = calculate_rsi_wilder(df['close'], 14)
    rsi10_inner = rsi1.rolling(window=10).mean()
    rsi10 = rsi10_inner.rolling(window=3).mean()
    rsisco = pd.Series(np.where(rsi10.isna(), np.nan, np.where(rsi10 >= 50, 1, 0)), index=df.index)

    # 신고가 플래그
    new_high_flag = 0
    if len(df) >= 126:
        max_recent_3 = df['close'].iloc[-3:].max()
        max_past_6m  = df['close'].iloc[-126:].max()
        if max_recent_3 >= max_past_6m:
            new_high_flag = 1
    else:
        if df['close'].iloc[-3:].max() >= df['close'].max():
            new_high_flag = 1

    # HLd71 / HLv71 / HLv7 (추세 판정용 — check_coloryp_logic과 동일하게 유지)
    def calc_stoch(c, h, l, period):
        return (c - l.rolling(period).min()) / (h.rolling(period).max() - l.rolling(period).min()) * 100

    k3 = calc_stoch(df['close'], df['high'], df['low'], 20).rolling(10).mean()
    k2 = calc_stoch(df['close'], df['high'], df['low'], 10).rolling(5).mean()
    rsi14 = rsi1.rolling(14).mean()
    cond_up   = (k3 > k3.shift(1)) & (k2 > k2.shift(1)) & (rsi14 >= rsi14.shift(1))
    cond_down = (k3 < k3.shift(1)) & (k2 < k2.shift(1)) & (rsi14 < rsi14.shift(1))
    HLd71 = pd.Series(np.where(cond_up, 1, np.where(cond_down, -1, 0)), index=df.index)
    HLv71 = HLd71.replace(0, np.nan).ffill().fillna(0)

    aa = df['close'].rolling(60).mean()
    bb = df['close'].rolling(200).mean()
    aacol = pd.Series(np.where(aa.isna() | aa.shift(5).isna(),   np.nan, np.where(aa >= aa.shift(5),   1, -1)), index=df.index)
    bbcol = pd.Series(np.where(bb.isna() | bb.shift(10).isna(),  np.nan, np.where(bb >= bb.shift(10),  1, -1)), index=df.index)
    HLd7 = pd.Series(
        np.where(aacol.isna() | bbcol.isna(), np.nan,
        np.where((aacol == 1) & (bbcol == 1),   1,
        np.where((aacol == -1) & (bbcol == -1), -1, 0))),
        index=df.index
    )
    HLv7 = HLd7.replace(0, np.nan).ffill().fillna(0)

    df['HLv99'] = HLv99
    df['HLv7']  = HLv7
    df['HLv71'] = HLv71

    # 이평선/각도/방향 df 저장 (check_coloryp_logic 호출 전 추세 판정에 필요)
    df['M0'] = M0;  df['M1'] = M1;  df['M2'] = M2;  df['M3'] = M3;  df['M4'] = M4
    df['m0ang'] = m0ang; df['m1ang'] = m1ang; df['m2ang'] = m2ang
    df['m3ang'] = m3ang; df['m4ang'] = m4ang
    df['m0s'] = m0s; df['m1s'] = m1s; df['m2s'] = m2s; df['m3s'] = m3s; df['m4s'] = m4s

    # sco99 = 지표 합산 (jasantop4_final.py와 동일, 최대 16점)
    sco99 = (
        s1 + s2 + s3 + s4 + s5 +
        m0s + m1s + m2s + m3s + m4s +
        jung + HLd99 + rsisco + new_high_flag
    )

    # sco = sco99의 4일 이동평균
    df['sco99'] = sco99
    df['sco']   = sco99.rolling(window=4).mean()
    return df


def atr_trigger_trailing_exclude(df_signal, drop_pct=0.10, trigger_mult=1.8, release_ratio=1.7, ma_window=10):
    """jasantop4_final.py와 동일한 ATR 제외 로직.

    - 트리거: atr5 > atr60 * trigger_mult
    - 해제(복귀): ① atr5/atr60 < release_ratio(1.7)  또는  ② 종가 >= mt3
    - 제외: ① 트리거 이후 고점 대비 -drop_pct(10%) 이상 하락  또는  ② 종가 < ma_window 이동평균
    - 트리거 탐색: 가장 최근 해제 이후의 가장 최근 트리거 기준 (jasantop4_final 동일)
    """
    info = {'trigger_date': None, 'atr_ratio_last': None, 'peak': None, 'drawdown_pct': None}
    if df_signal is None or df_signal.empty:
        return False, False, info
    if 'atr5' not in df_signal.columns or 'atr60' not in df_signal.columns:
        return False, False, info

    # ── mt3 (ATR15×3 MagicTrend 3번선) 계산 ──
    try:
        _df = df_signal[['close', 'high', 'low']].copy()
        _prev = _df['close'].shift(1)
        _tr = pd.concat([
            _df['high'] - _df['low'],
            (_df['high'] - _prev).abs(),
            (_df['low']  - _prev).abs()
        ], axis=1).max(axis=1)
        _atr15 = _tr.rolling(window=15).mean()

        _tp     = (_df['high'] + _df['low'] + _df['close']) / 3
        _sma_tp = _tp.rolling(window=20).mean()
        _mad    = (_tp - _sma_tp).abs().rolling(window=20).mean()
        _cci    = ((_tp - _sma_tp) / (0.015 * _mad)).fillna(0)

        _upT3   = _df['low']  - _atr15 * 3
        _downT3 = _df['high'] + _atr15 * 3

        _mt3 = [0.0] * len(_df)
        for i in range(1, len(_df)):
            _is_up = pd.notna(_cci.iloc[i]) and _cci.iloc[i] >= 0
            if _is_up:
                _mt3[i] = max(_upT3.iloc[i], _mt3[i-1])
            else:
                _mt3[i] = min(_downT3.iloc[i], _mt3[i-1]) if _mt3[i-1] != 0 else _downT3.iloc[i]

        mt3_last = float(_mt3[-1])
        mt3_series = pd.Series(_mt3, index=df_signal.index)
    except Exception:
        mt3_last = None
        mt3_series = None

    atr60 = df_signal['atr60'].replace(0, pd.NA)
    ratio = (df_signal['atr5'] / atr60).astype(float)
    info['atr_ratio_last'] = float(ratio.iloc[-1]) if pd.notna(ratio.iloc[-1]) else None

    trig = ratio > float(trigger_mult)
    if not trig.any():
        return False, False, info

    # ── 해제 조건: ① ratio < release_ratio  또는  ② 종가 >= mt3 ──
    close_last = float(df_signal['close'].iloc[-1])
    released_by_ratio = pd.notna(ratio.iloc[-1]) and float(ratio.iloc[-1]) < float(release_ratio)
    released_by_mt3   = (mt3_last is not None) and (close_last >= mt3_last)
    released = released_by_ratio or released_by_mt3

    if mt3_series is not None:
        rel = (ratio < float(release_ratio)) | (df_signal['close'] >= mt3_series)
    else:
        rel = ratio < float(release_ratio)

    # 가장 최근 해제 이후의 가장 최근 트리거만 유효
    last_release_pos = rel[rel].index.max() if rel.any() else None
    if last_release_pos is None:
        last_trigger_pos = trig[trig].index.max()
    else:
        trig_after = trig.loc[trig.index > last_release_pos]
        if not trig_after.any():
            return False, False, info
        last_trigger_pos = trig_after[trig_after].index.max()

    if released:
        return False, False, info

    info['trigger_date'] = pd.to_datetime(last_trigger_pos)

    seg = df_signal.loc[df_signal.index >= last_trigger_pos]
    if seg.empty:
        return True, False, info
    peak = float(seg['high'].cummax().iloc[-1])
    close_seg_last = float(seg['close'].iloc[-1])
    if peak <= 0:
        return True, False, info
    dd = (close_seg_last / peak) - 1.0
    info['peak'] = peak
    info['drawdown_pct'] = dd * 100.0

    # 제외 조건: ① 고점 대비 -10% 이상  또는  ② 종가 < ma_window 이평
    cond_trail = dd <= -float(drop_pct)
    sma_val = seg['close'].rolling(int(ma_window), min_periods=int(ma_window)).mean()
    sma_last = sma_val.iloc[-1]
    cond_ma = pd.notna(sma_last) and close_seg_last < float(sma_last)

    exclude_now = bool(cond_trail or cond_ma)
    return True, exclude_now, info


def calculate_cci_for_atr(df, period=20):
    """ATR 레벨 계산용 CCI (Pine Script ta.cci 동일 로직)"""
    tp     = (df['high'] + df['low'] + df['close']) / 3
    sma_tp = tp.rolling(window=period).mean()
    mad    = (tp - sma_tp).abs().rolling(window=period).mean()
    cci    = (tp - sma_tp) / (0.015 * mad)
    return cci.fillna(0)


def calculate_atr_levels_for_ticker_us(ticker):
    """ATR 3단계 가격 계산 - Pine Script MagicTrend 로직과 정확히 동일 (미국 ETF 버전)

    Pine Script 원본:
        mt1 := cci >= 0 ? (upT1 < nz(mt1[1]) ? nz(mt1[1]) : upT1)   ← 상승: max(upT1, prev)
                        : (downT1 > nz(mt1[1]) ? nz(mt1[1]) : downT1) ← 하락: min(downT1, prev)

    핵심:
      - 상승(CCI>=0): mt = max(upT, prev)   → 지지선이 계속 올라가기만 함
      - 하락(CCI< 0): mt = min(downT, prev)  → 저항선이 계속 내려가기만 함
      - nz(mt[1]) 초기값=0 → 첫 봉은 upT/downT 그대로 사용 (Pine nz() 동일)

    반환: (current_price, mt1, mt2, mt3) 또는 (None, None, None, None)
    """
    try:
        end   = datetime.now()
        start = end - timedelta(days=365)
        # 공유 캐시 사용 (중복 다운로드 제거). auto_adjust=True 기준 → 신호값 불변.
        df = get_us_ohlcv(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

        if df.empty or len(df) < 20:
            return None, None, None, None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]

        # True Range 계산 (Pine: ta.tr)
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = (df['high'] - df['prev_close']).abs()
        df['lc'] = (df['low']  - df['prev_close']).abs()
        df['TR'] = df[['hl', 'hc', 'lc']].max(axis=1)

        # ATR (Pine: ta.sma(ta.tr, N))
        df['ATR5']  = df['TR'].rolling(window=5).mean()
        df['ATR10'] = df['TR'].rolling(window=10).mean()
        df['ATR15'] = df['TR'].rolling(window=15).mean()

        # CCI (Pine: ta.cci(close, 20))
        df['CCI'] = calculate_cci_for_atr(df, period=20)

        # 상승/하락 밴드 계산
        df['upT1']   = df['low']  - df['ATR5']  * 1
        df['downT1'] = df['high'] + df['ATR5']  * 1
        df['upT2']   = df['low']  - df['ATR10'] * 2
        df['downT2'] = df['high'] + df['ATR10'] * 2
        df['upT3']   = df['low']  - df['ATR15'] * 3
        df['downT3'] = df['high'] + df['ATR15'] * 3

        # Pine Script nz(mt[1]) 초기값=0 와 동일하게 0.0으로 시작
        mt1 = [0.0] * len(df)
        mt2 = [0.0] * len(df)
        mt3 = [0.0] * len(df)

        for i in range(1, len(df)):
            cci_val = df['CCI'].iloc[i]
            is_up   = pd.notna(cci_val) and cci_val >= 0

            # Line 1 (AP=5, coeff=1)
            if is_up:
                mt1[i] = max(df['upT1'].iloc[i], mt1[i-1])
            else:
                mt1[i] = min(df['downT1'].iloc[i], mt1[i-1]) if mt1[i-1] != 0 else df['downT1'].iloc[i]

            # Line 2 (AP=10, coeff=2)
            if is_up:
                mt2[i] = max(df['upT2'].iloc[i], mt2[i-1])
            else:
                mt2[i] = min(df['downT2'].iloc[i], mt2[i-1]) if mt2[i-1] != 0 else df['downT2'].iloc[i]

            # Line 3 (AP=15, coeff=3)
            if is_up:
                mt3[i] = max(df['upT3'].iloc[i], mt3[i-1])
            else:
                mt3[i] = min(df['downT3'].iloc[i], mt3[i-1]) if mt3[i-1] != 0 else df['downT3'].iloc[i]

        current_price = float(df['close'].iloc[-1])
        atr1_val      = float(mt1[-1])
        atr2_val      = float(mt2[-1])
        atr3_val      = float(mt3[-1])

        # 강제 보정 완전 제거:
        # 하락장(CCI<0)에서 mt선은 현재가 위(저항선)에 위치하는 것이 정상 Pine 동작.
        return current_price, atr1_val, atr2_val, atr3_val

    except Exception:
        return None, None, None, None


def get_atr_stage(close, atr1, atr2):
    """ATR 단계 판정 (Pine Script MagicTrend 기준)

    ATR0단계: 현재가 >= mt1  → 가장 빠른 선 위 (안전/상승)
    ATR1단계: mt1 > 현재가 >= mt2 → 1번선 아래, 2번선 위 (주의)
    ATR2단계: mt2 > 현재가        → 2번선 아래 (위험)

    상승장(mt선이 현재가 아래 = 지지선): close >= atr1 → ATR0
    하락장(mt선이 현재가 위  = 저항선): 어느 선 사이에 있는지로 단계 판정
    """
    if close is None or atr1 is None or atr2 is None:
        return None

    # mt선이 현재가 아래 = 상승장 (지지선 역할) → ATR0
    if atr1 <= close:
        return 0  # ATR0: 현재가가 1번선 위 (안전)

    # mt선이 현재가 위 = 하락장 (저항선 역할) → 단계 판정
    if atr1 > close >= atr2:
        return 1  # ATR1: 1번선 아래, 2번선 위 (주의)
    else:
        return 2  # ATR2: 2번선 아래 (위험)


def normalize_0_1(series):
    """정규화 함수"""
    min_val = series.min()
    max_val = series.max()
    if max_val == min_val:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - min_val) / (max_val - min_val)


def _winsorize(series, lo=0.05, hi=0.95):
    """극단값(하위5%/상위95%) 클리핑 후 반환 — Final_score 수익률 정규화용."""
    s = series.copy()
    valid = s.dropna()
    if len(valid) < 5:
        return s
    return s.clip(valid.quantile(lo), valid.quantile(hi))


def load_up_days_data(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"up_days": 0, "last_date": "", "last_trend": ""}

def save_up_days_data(data, file_path):
    try:
        data["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass

def calc_up_days(trend, chg, pos, up_days_file, label=""):
    today = datetime.now().strftime("%Y-%m-%d")
    data = load_up_days_data(up_days_file)
    up_days = int(data.get("up_days", 0))
    last_date = data.get("last_date", "")
    last_trend = data.get("last_trend", "")
    
    prefix = f"[{label} 단계적 비중]" if label else "[단계적 비중]"
    
    if trend in ('PURPLE', 'RED'):
        save_up_days_data({"up_days": 0, "last_date": today, "last_trend": trend}, up_days_file)
        mult = TREND_MULTIPLIER[trend]
        print(f"{prefix} {trend} → up_days=0 리셋, multiplier={mult}")
        return 0, mult

    if trend == 'GREEN':
        if pos is None or pos <= 1: mult = 0.7
        elif pos == 2: mult = 0.6
        elif pos == 3: mult = 0.5
        else: mult = 0.4
        print(f"{prefix} GREEN(위치{pos}) → multiplier={mult}")
        return up_days, mult

    if trend == 'LIME':
        if pos is None or pos <= 1: mult = 0.85
        elif pos == 2: mult = 0.8
        elif pos == 3: mult = 0.6
        else: mult = 0.4
        print(f"{prefix} LIME(위치{pos}) → multiplier={mult}")
        return up_days, mult

    if last_date != today:
        if last_trend in ('PURPLE', 'RED'): up_days = 0
        if chg is not None and chg > 0: up_days += 1
        elif chg is not None and chg < 0: up_days -= 1
        up_days = max(0, min(up_days, 3))
        save_up_days_data({"up_days": up_days, "last_date": today, "last_trend": trend}, up_days_file)

    mult = {0: 0.2, 1: 0.2, 2: 0.3, 3: 0.4}.get(up_days, 0.4)
    chg_str = f"{chg:+.2f}%" if chg is not None else "N/A"
    counted = "카운팅" if last_date != today else "재실행(스킵)"
    print(f"{prefix} up_days={up_days}({counted}) → multiplier={mult} (등락: {chg_str})")
    return up_days, mult

def calc_vol_penalty(vol_annualized, vol_median):
    if vol_median is None or vol_median <= 0: return 1.0
    ratio = vol_annualized / vol_median
    if ratio <= 1.10: return 1.00
    elif ratio <= 1.25: return 0.95
    elif ratio <= 1.40: return 0.90
    else: return 0.85

def calc_atr_penalty(atr_stage):
    return {0: 1.00, 1: 0.95, 2: 0.85, 3: 0.70}.get(atr_stage if atr_stage is not None else 0, 1.00)

def calc_internal_weights(selected_df, vol_info_dict, base_weights=None):
    tickers = selected_df['Ticker'].tolist()
    if base_weights is None:
        base_weights = list(TOP3_ALLOC_WEIGHTS[:len(tickers)])
    else:
        base_weights = list(base_weights[:len(tickers)])

    vols = [vol_info_dict.get(t, {}).get('vol63', None) for t in tickers]
    valid_vols = [v for v in vols if v is not None]
    vol_median = float(np.median(valid_vols)) if valid_vols else None

    adj_weights, penalty_logs = [], []
    for i, t in enumerate(tickers):
        info = vol_info_dict.get(t, {})
        vol63 = info.get('vol63', None)
        atr_stage = info.get('atr_stage', 0)
        vp = calc_vol_penalty(vol63 if vol63 is not None else (vol_median or 0), vol_median)
        ap = calc_atr_penalty(atr_stage)
        adj_w = base_weights[i] * vp * ap
        adj_weights.append(adj_w)
        penalty_logs.append(
            f"   [{t}] "
            f"기본{base_weights[i]*100:.0f}% × vol벌점{vp:.2f}"
            f"(vol={'N/A' if vol63 is None else f'{vol63:.1f}%'}, "
            f"중앙={'N/A' if vol_median is None else f'{vol_median:.1f}%'}) "
            f"× ATR{atr_stage}벌점{ap:.2f} → 조정전{adj_w*100:.1f}%"
        )

    total = sum(adj_weights)
    normalized = [w / total for w in adj_weights] if total > 0 else [1.0/len(tickers)] * len(tickers)
    
    print("\n[변동성 감점형 내부비중 조정]")
    print(f"  Holdings vol63 중앙값: {'N/A' if vol_median is None else f'{vol_median:.1f}%'}")
    for log in penalty_logs: print(log)
    print(f"  최종 내부비중: " + " / ".join(f"{w*100:.1f}%" for w in normalized))
    return normalized

def get_individual_floor_mult(row, market_mult):
    """
    개별 ETF의 강도(Signal_sco, 위치)에 따라 최소 multiplier 바닥을 부여한다.
    시장이 PURPLE/RED(≤0.15)일 때는 weakness_factor=0.4로 바닥을 축소한다.
    """
    sco = row.get('Signal_sco', np.nan)
    pos = row.get('위치', np.nan)

    weakness_factor = 0.4 if market_mult <= 0.15 else 1.0

    if pd.isna(sco):
        base = INDIV_FLOOR_MIN
    elif sco >= 15:
        base = 0.55 * weakness_factor
    elif sco >= 14:
        base = 0.50 * weakness_factor
    elif sco >= 13:
        base = 0.45 * weakness_factor
    elif sco >= 12:
        base = 0.35 * weakness_factor
    elif sco >= 11:
        base = 0.30 * weakness_factor
    else:
        base = INDIV_FLOOR_MIN

    if pd.notna(pos):
        try:
            pos_val = float(pos)
            if pos_val <= 1:
                base += 0.05 * weakness_factor
            elif pos_val >= 4:
                base -= 0.05 * weakness_factor
        except Exception:
            pass

    return float(min(INDIV_FLOOR_MAX * weakness_factor, max(INDIV_FLOOR_MIN, base)))


def get_effective_multiplier(row, is_fixed, us_mult):
    """
    FIXED는 1.0 유지.
    그 외는 시장 multiplier와 개별 floor 중 큰 값을 적용한다.
    """
    if is_fixed:
        return 1.0, None

    floor_mult = get_individual_floor_mult(row, us_mult)
    return float(max(us_mult, floor_mult)), floor_mult


def cap_fixed_allocations(alloc_dict, meta_dict, total_inv, us_mult):
    """
    시장 multiplier가 FIXED_CAP_TRIGGER_MULT 이하일 때,
    FIXED 자산 총합이 총투자금의 FIXED_CAP_RATIO_WHEN_WEAK를 넘지 못하게 비례 축소한다.
    줄어든 금액은 현금으로 남기고 재분배하지 않는다.
    """
    weak_market = us_mult <= FIXED_CAP_TRIGGER_MULT
    cap_amount  = round(total_inv * FIXED_CAP_RATIO_WHEN_WEAK, 2)
    cap_info = {
        'weak_market': weak_market,
        'cap_ratio': FIXED_CAP_RATIO_WHEN_WEAK,
        'cap_amount': cap_amount,
        'fixed_total_before': 0,
        'fixed_total_after': 0,
        'applied': False,
        'scale': 1.0,
    }

    fixed_idxs   = [idx for idx, meta in meta_dict.items() if meta.get('is_fixed')]
    fixed_total  = sum(alloc_dict.get(idx, 0) for idx in fixed_idxs)
    cap_info['fixed_total_before'] = fixed_total

    if not weak_market or total_inv <= 0 or fixed_total <= 0 or fixed_total <= cap_amount:
        cap_info['fixed_total_after'] = fixed_total
        return alloc_dict, meta_dict, cap_info

    scale = cap_amount / fixed_total
    cap_info['applied'] = True
    cap_info['scale']   = scale

    for idx in fixed_idxs:
        alloc_dict[idx]           = round(alloc_dict.get(idx, 0) * scale, 2)
        meta_dict[idx]['cap_scaled'] = True
        meta_dict[idx]['cap_scale']  = scale

    cap_info['fixed_total_after'] = sum(alloc_dict.get(idx, 0) for idx in fixed_idxs)
    return alloc_dict, meta_dict, cap_info


def calc_holdings_alloc(selected_df, total_inv, nasdaq_trend, base_weights=None,
                        vol_info_dict=None, nasdaq_chg=None, nasdaq_pos=None):
    _up_days_n, us_mult = calc_up_days(nasdaq_trend, nasdaq_chg, nasdaq_pos, NASDAQ_UP_DAYS_FILE, label="나스닥")

    if base_weights is None:
        base_weights = list(TOP3_ALLOC_WEIGHTS[:len(selected_df)])

    if vol_info_dict and not selected_df.empty:
        internal_weights = calc_internal_weights(selected_df, vol_info_dict, base_weights)
    else:
        internal_weights = list(base_weights[:len(selected_df)])

    alloc_dict = {}
    alloc_meta = {}

    for (idx, row), w in zip(selected_df.iterrows(), internal_weights):
        is_fixed = row['Ticker'] in FIXED_ONE_TICKERS
        raw_mult, floor_mult = get_effective_multiplier(row, is_fixed, us_mult)
        amt = round(total_inv * w * raw_mult, 2)

        alloc_dict[idx] = amt
        alloc_meta[idx] = {
            'ticker':      row['Ticker'],
            'is_fixed':    is_fixed,
            'weight':      float(w),
            'raw_mult':    float(raw_mult),
            'display_mult': float(raw_mult),
            'floor_mult':  None if floor_mult is None else float(floor_mult),
            'cap_scaled':  False,
            'cap_scale':   1.0,
        }

    alloc_dict, alloc_meta, cap_info = cap_fixed_allocations(
        alloc_dict, alloc_meta, total_inv, us_mult
    )

    # display_mult 재계산 (cap 적용 후 실제 비율)
    for idx, meta in alloc_meta.items():
        denom = total_inv * meta['weight']
        if denom > 0:
            meta['display_mult'] = float(alloc_dict.get(idx, 0) / denom)

    total_alloc = sum(alloc_dict.values())
    return alloc_dict, total_alloc, internal_weights, us_mult, alloc_meta, cap_info

def load_holding_list(path=HOLDING_FILE):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def save_holding_list(tickers, path=HOLDING_FILE):
    with open(path, "w", encoding="utf-8") as f:
        for t in tickers:
            f.write(f"{t}\n")

def build_final_holding_df(score_df, investable_df, priority_tickers, ticker_col, max_count=6):
    """Fill holdings from investable candidates while allowing only one of KBE/KRE."""
    if investable_df.empty:
        return investable_df.copy()

    investable_tickers = set(investable_df[ticker_col].tolist())
    bank_df = investable_df[investable_df[ticker_col].isin(BANK_ETF_GROUP)].copy()
    preferred_bank = None
    if not bank_df.empty:
        bank_df['_bank_sco'] = pd.to_numeric(bank_df['Signal_sco'], errors='coerce').fillna(-np.inf)
        bank_df['_bank_score'] = pd.to_numeric(bank_df['Final_score'], errors='coerce').fillna(-np.inf)
        preferred_bank = bank_df.sort_values(
            ['_bank_sco', '_bank_score'], ascending=False
        ).iloc[0][ticker_col]

    selected = []
    for ticker in list(priority_tickers) + investable_df[ticker_col].tolist():
        if ticker not in investable_tickers:
            continue
        if ticker in BANK_ETF_GROUP:
            if preferred_bank is None:
                continue
            ticker = preferred_bank
        if ticker in selected:
            continue
        selected.append(ticker)
        if len(selected) >= max_count:
            break

    final_df = score_df[score_df[ticker_col].isin(selected)].copy()
    final_df = final_df.sort_values('Final_score', ascending=False)
    return final_df

# ====== Multiplier 분류 ======
# multiplier = 1.0 고정: 원자재·채권 (나스닥 추세와 무관하게 비중 유지)
FIXED_ONE_TICKERS = {
    'GLD', 'SLV', 'DBA', 'DBC', 'PDBC', 'UNG', 'REMX', 'PICK', 'XME',
    'TLT', 'HYG', 'XLE',
}

# ====== US ETF 리스트 ======
US_ETFS = [
    # 미국 대형/중소형 지수
    "SPY", "QQQ", "DIA", "IWM", "IJH",
    # 스타일
    "VTV", "VUG",
    # 글로벌/선진국/이머징
    "EFA", "VWO", "SCZ",
    # 채권
    "TLT", "HYG",
    # 원자재
    "GLD", "SLV", "DBA", "PDBC", "UNG", "REMX", "PICK", "XME",
    # 섹터 XL
    "XLE", "XLF", "XLV", "XLI", "XLK", "XLP", "XLU", "XLY", "XLB", "XLC",
    # 부동산
    "VNQ",
    # 배당
    "SCHD", "VYM",
    # 테크/테마
    "SMH", "IBB", "XBI",
    "ARKK", "ARKW", "ARKF",
    "BOTZ", "LIT", "TAN", "ICLN",
    "ITB", "KRE", "KBE",
    # 항공
    "JETS",
    # 방산
    "ITA",
    # 크립토
    "IBIT", "ETHA",
    # 자동차
    "CARZ",
    # 모멘텀/팩터
    "MTUM", "GMOM", "QMOM", "PDP", "PTF",
    # 기타 테마
    "EMGF", "SRVR", "SVXY",
    # 레이더용 테마/SW/인프라
    "IGV", "CIBR", "URA", "COPX", "PAVE", "GRID", "GUNR",
    # 국가별 ETF (미국상장) ── WORLD_ETFS
    "EWY", "EWJ", "EWH", "FXI", "INDA", "EIDO", "EWT", "VNM", "EPHE", "THD", "EWS", "EWM",
    "EZU", "VGK", "EWG", "EWU", "EWQ", "EWI", "EWP", "GREK",
    "EWC", "EWW", "EWZ",
    "EZA", "KSA", "EIS", "TUR",
    "EWA", "EWL", "ENZL",
]


def main():
    start_time = time.time()
    warnings.filterwarnings("ignore")
    
    atr_triggered = []
    atr_excluded = []
    atr_filtered = []
    
    end = datetime.now()
    start = end - timedelta(days=400)  # 200일 이평 확보 위해 400일(영업일 약 280일)
    
    rows = []

    # 병렬 prefetch: US_ETFS 를 배치 다운로드로 캐시에 미리 채움 (이후 get_us_ohlcv 는 캐시 적중).
    # 값은 단일 yf.download 와 동일 검증됨(verify_us_fetch_equivalence.py). 실패분은 get_us_ohlcv 폴백.
    prefetch(US_ETFS, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    for ticker in US_ETFS:
        try:
            # 공유 캐시 사용 (중복 다운로드 제거). auto_adjust=True 기준 → 신호값 불변.
            df = get_us_ohlcv(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

            if df.empty or len(df) < 130:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.columns = [str(c).lower() for c in df.columns]

            if 'close' not in df.columns:
                print(f"⚠️ {ticker} 컬럼 없음: {df.columns.tolist()}")
                continue

            df_sig = calculate_signal(df)

            # ── ATR 과열 트리거 후 고점 대비 -10% 하락 시 제외 (복귀: atr5/atr60 < 1.7) ──
            active_trig, exclude_now, atr_info = atr_trigger_trailing_exclude(
                df_sig, drop_pct=0.10, trigger_mult=1.8, release_ratio=1.7, ma_window=10
            )

            # ATR 비율 기록 (통계용)
            if df_sig['atr5'].iloc[-1] > 0 and df_sig['atr60'].iloc[-1] > 0:
                ratio_val = df_sig['atr5'].iloc[-1] / df_sig['atr60'].iloc[-1]
                if ratio_val > 1.8:
                    atr_filtered.append({
                        'Ticker': ticker,
                        'ATR5': df_sig['atr5'].iloc[-1],
                        'ATR60': df_sig['atr60'].iloc[-1],
                        'ATR비율': ratio_val
                    })

            # 출력은 오늘 기준 최근 2주만
            cutoff = df_sig.index[-1] - pd.Timedelta(days=14)
            if active_trig and atr_info.get('trigger_date') is not None and atr_info['trigger_date'] >= cutoff:
                cp, lv1, lv2, lv3 = calculate_atr_levels_for_ticker_us(ticker)
                atr_stage = get_atr_stage(cp, lv1, lv2)
                atr_triggered.append({
                    'Ticker': ticker,
                    'ATR단계': f"ATR{atr_stage}단계" if atr_stage is not None else '-'
                })

            if exclude_now:
                trig_date = atr_info.get('trigger_date')
                today_ts  = pd.Timestamp(df_sig.index[-1])
                within_2weeks = (
                    trig_date is not None and
                    pd.to_datetime(trig_date) >= today_ts - pd.Timedelta(days=14)
                )
                if within_2weeks:
                    _cp, _lv1, _lv2, _lv3 = calculate_atr_levels_for_ticker_us(ticker)
                    _stage = get_atr_stage(_cp, _lv1, _lv2)
                    atr_excluded.append({
                        'Ticker': ticker,
                        'ATR단계': f"ATR{_stage}단계" if _stage is not None else '-'
                    })
                # ATR 제외지만 rows에는 포함하지 않음 (투자 후보에서 제외)
                continue

            # ✅ coloryp 조건 체크 (jasantop4_final과 동일한 check_coloryp_logic 사용)
            df_sig = check_coloryp_logic(df_sig)
            
            # ✅ 거래량 체크
            is_high_volume = check_volume_intensity(df_sig)
            
            # ✅ 신규 신호 체크 (2일 룩)
            new_signal = get_new_signal(df_sig)

            close = df_sig["close"]
            rtn = (close.iloc[-1] / close.iloc[-61] - 1) * 100

            # 🎯 20봉 수익률 계산 (지수대비용)
            rtn20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else None

            today_chg = (
                (close.iloc[-1] / close.iloc[-2] - 1) * 100
                if len(close) > 1 else 0
            )

            latest_sco = (
                df_sig["sco"].dropna().iloc[-1]
                if not df_sig["sco"].dropna().empty else None
            )
            
            # ✅ 15개 컬럼 데이터 수집
            # vol63 계산
            pct_chg = close.pct_change()
            vol63 = pct_chg.iloc[-63:].std() * math.sqrt(252) * 100 if len(pct_chg) >= 63 else None
            
            # 항상 ATR 단계 계산
            _cp, _lv1, _lv2, _lv3 = calculate_atr_levels_for_ticker_us(ticker)
            _stage = get_atr_stage(_cp, _lv1, _lv2)
            atr_stage_val = _stage if _stage is not None else 0

            # 가격 위치 계산 (jasantop4_final.py와 동일: 이평선 위/아래 카운트)
            ma136 = df_sig['close'].rolling(window=136).mean().iloc[-1]
            close_val = close.iloc[-1]
            mas_for_pos = [df_sig['M0'].iloc[-1], df_sig['M1'].iloc[-1],
                           df_sig['M2'].iloc[-1], df_sig['M3'].iloc[-1]]
            price_pos = sum(1 for ma in mas_for_pos if ma > close_val) + 1
            
            # 정배/역배
            alignment = "-"
            if df_sig['M0'].iloc[-1] > df_sig['M1'].iloc[-1] > df_sig['M2'].iloc[-1] > df_sig['M3'].iloc[-1] > df_sig['M4'].iloc[-1]:
                alignment = "정배"
            elif df_sig['M0'].iloc[-1] < df_sig['M1'].iloc[-1] < df_sig['M2'].iloc[-1] < df_sig['M3'].iloc[-1] < df_sig['M4'].iloc[-1]:
                alignment = "역배"
            
            # 이평선 방향
            ma_dirs = []
            for col in ['m0s', 'm1s', 'm2s', 'm3s', 'm4s']:
                val = df_sig[col].iloc[-1]
                if val == 1:
                    ma_dirs.append("상")
                elif val == -1:
                    ma_dirs.append("하")
                else:
                    ma_dirs.append("-")
            
            # 추세 색상 (jasantop4_final과 동일한 판정 로직)
            # TV: angle_tol  = m0~m4ang <= 0 (5개 모두) → RED 강제
            # TV: angle_tol2 = m0~m3ang <= 0 (4개)     → PURPLE 강제
            angle_tol  = all(df_sig[f'm{i}ang'].iloc[-1] <= 0 for i in range(5))
            angle_tol2 = all(df_sig[f'm{i}ang'].iloc[-1] <= 0 for i in range(4))
            hv9  = df_sig['HLv99'].iloc[-1]
            hv7  = df_sig['HLv7'].iloc[-1]
            hv71 = df_sig['HLv71'].iloc[-1]
            if bool(df_sig['lime_final'].iloc[-1]):
                trend = "LIME"
            elif hv9 >= 1 and hv71 == 1:
                trend = "GREEN"
            elif (hv9 <= -1 and hv7 == -1 and hv71 == -1) or angle_tol:
                trend = "RED"
            elif (hv9 <= -1 and hv71 == -1) or angle_tol2:
                trend = "PURPLE"
            else:
                trend = "-"
            
            # 136평 대비 %
            ma136_pct = ((close.iloc[-1] - ma136) / ma136 * 100) if pd.notna(ma136) and ma136 > 0 else 0

            # RSI(14) 당일/전일 (정수)
            rsi_today = int(round(df_sig['rsi1'].iloc[-1])) if pd.notna(df_sig['rsi1'].iloc[-1]) else 0
            rsi_prev  = int(round(df_sig['rsi1'].iloc[-2])) if len(df_sig) > 1 and pd.notna(df_sig['rsi1'].iloc[-2]) else 0
            rsi_str   = f"{rsi_today}({rsi_prev})"

            # ✅ 저/저2 신호 계산
            try:
                jeo_signal, jeo2_signal = calculate_tv_signals(df_sig)
            except Exception:
                jeo_signal, jeo2_signal = "-", "-"

            rows.append({
                "Ticker": ticker,
                "등락": today_chg,
                "위치": price_pos,
                "Signal_sco": latest_sco if latest_sco is not None else None,
                "정배": alignment,
                "신호": new_signal,
                "5": ma_dirs[0],
                "10": ma_dirs[1],
                "20": ma_dirs[2],
                "60": ma_dirs[3],
                "120": ma_dirs[4],
                "추세": trend,
                "136평": ma136_pct,
                "수익률(%)": rtn if rtn is not None else None,
                "수익률20(%)": rtn20,
                "Final_score": None,  # 나중에 계산
                "HighVol": is_high_volume,
                "저": jeo_signal,
                "저2": jeo2_signal,
                "vol63": vol63,
                "atr_stage_val": atr_stage_val,
                "atr_excluded": exclude_now,
                "RSI_str": rsi_str,
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
    res["Norm_sco"]  = normalize_0_1(res["Signal_sco"].fillna(res["Signal_sco"].min()))
    res["Norm_1M_w"] = normalize_0_1(_winsorize(res["수익률20(%)"].fillna(res["수익률20(%)"].min())))
    res["Norm_3M_w"] = normalize_0_1(_winsorize(res["수익률(%)"].fillna(res["수익률(%)"].min())))
    res["Final_score"] = res["Norm_sco"] * 0.55 + res["Norm_1M_w"] * 0.30 + res["Norm_3M_w"] * 0.15


    res = res.sort_values("Final_score", ascending=False).reset_index(drop=True)

    # 🎯 지수대비(%) 계산: 각 종목의 20봉 수익률 - 나스닥(QQQ) 20봉 수익률
    qqq_rtn20 = None
    qqq_row = res[res['Ticker'] == 'QQQ']
    if not qqq_row.empty and '수익률20(%)' in qqq_row.columns:
        qqq_rtn20 = qqq_row['수익률20(%)'].iloc[0]

    def calc_idx_relative(row):
        rtn20_val = row.get('수익률20(%)')
        if pd.isna(rtn20_val) or rtn20_val is None:
            return None
        if qqq_rtn20 is not None and not pd.isna(qqq_rtn20):
            return rtn20_val - qqq_rtn20
        return None

    res['지수대비(%)'] = res.apply(calc_idx_relative, axis=1)

    print("\n=== US ETF Momentum Top ===")

    # ✅ 15개 컬럼 출력 (Name 제외)
    display_df = res.head(30).copy()
    display_df['Ticker_Display'] = display_df.apply(
        lambda row: f"{row['Ticker']}**" if row['HighVol'] else f"{row['Ticker']}  ",
        axis=1
    )

    print(display_df[["Ticker_Display", "등락", "위치", "Signal_sco", "RSI_str", "정배", "신호", 
                      "5", "10", "20", "60", "120", "추세", "136평", "수익률(%)", "Final_score", "지수대비(%)"]]
          .rename(columns={"Ticker_Display": "Ticker", "Signal_sco": "Sco", "수익률(%)": "3M(%)", "Final_score": "Score", "지수대비(%)": "지수대비", "RSI_str": "RSI"})
          .round(2)
          .to_string(index=False, max_rows=None))
          
    # ── Top3 선정 ──────────────────────────────────────────────
    if 'atr_excluded' not in res.columns: res['atr_excluded'] = False
    
    cond = (res['Signal_sco'] >= TOP3_MIN_SCO) & (~res['atr_excluded'])
    investable_df = res.loc[cond].sort_values(by='Final_score', ascending=False).copy()
    
    strong_count = int(len(investable_df))
    selected_top3 = investable_df.head(3).copy()
    top3_avg_sco = float(selected_top3['Signal_sco'].mean()) if not selected_top3.empty else np.nan
    top3_avg_pos = float(selected_top3['위치'].mean()) if (not selected_top3.empty and selected_top3['위치'].notna().any()) else np.nan

    # 나스닥(QQQ) 당일 등락률 + 위치 추출
    nasdaq_chg_for_mult = None
    nasdaq_pos_for_mult = None
    nasdaq_trend = "-"
    nasdaq_row = res[res['Ticker'] == 'QQQ']
    if not nasdaq_row.empty:
        nasdaq_chg_for_mult = nasdaq_row.iloc[0].get('등락', None)
        nasdaq_pos_for_mult = nasdaq_row.iloc[0].get('위치', None)
        nasdaq_trend = nasdaq_row.iloc[0].get('추세', '-')

    # ── Holdings 결정 (비중 배분 전 수행) ─────────────────────
    prev_holding = load_holding_list()
    top_3_tickers = selected_top3['Ticker'].tolist()
    print(f"\n이전 보유 종목: {prev_holding if prev_holding else '없음'}")
    print(f"현재 Top3: {top_3_tickers}")

    holding_symbols = []
    for ticker in prev_holding:
        ticker_data = res[res['Ticker'] == ticker]
        if not ticker_data.empty:
            sco_value = ticker_data.iloc[0]['Signal_sco']
            is_atr_excluded = bool(ticker_data.iloc[0].get('atr_excluded', False))
            if is_atr_excluded:
                print(f"  제거: {ticker} (ATR제외)")
            elif pd.notna(sco_value) and sco_value >= TOP3_MIN_SCO:
                holding_symbols.append(ticker)
                print(f"  유지: {ticker} (sco={sco_value:.1f})")
            else:
                sco_str = f"{sco_value:.1f}" if pd.notna(sco_value) else "N/A"
                print(f"  제거: {ticker} (sco={sco_str})")

    for ticker in top_3_tickers:
        if ticker not in holding_symbols:
            holding_symbols.append(ticker)
            print(f"  추가: {ticker}")

    candidate_tickers = holding_symbols + investable_df['Ticker'].tolist()
    final_holding_df = build_final_holding_df(
        res, investable_df, candidate_tickers, 'Ticker', max_count=6
    )
    final_holding    = final_holding_df['Ticker'].tolist()
    bank_holding = [t for t in final_holding if t in BANK_ETF_GROUP]
    if bank_holding:
        print(f"  은행 ETF 제한 적용: {bank_holding[0]}만 보유 후보 포함")
    print(f"\n최종 보유 종목 ({len(final_holding)}개): {final_holding}")
    save_holding_list(final_holding)

    # ── 비중 배분 (ALLOCATION_MAP 기반, 전체 holdings 대상) ───
    res['투자금액'] = 0.0
    final_holding_df['투자금액'] = 0.0
    n_holdings = len(final_holding_df)

    if n_holdings > 0:
        base_weights_pct = ALLOCATION_MAP.get(n_holdings, ALLOCATION_MAP[max(ALLOCATION_MAP.keys())])
        base_weights     = [w / 100.0 for w in base_weights_pct]

        vol_info_dict = {
            row['Ticker']: {
                'vol63': row.get('vol63', None),
                'atr_stage': int(row.get('atr_stage_val', 0)) if pd.notna(row.get('atr_stage_val')) else 0,
            }
            for _, row in final_holding_df.iterrows()
        }

        alloc_dict, invest_amount_total, internal_weights, us_mult_applied, alloc_meta, cap_info = calc_holdings_alloc(
            final_holding_df, total_investment, nasdaq_trend,
            base_weights=base_weights, vol_info_dict=vol_info_dict,
            nasdaq_chg=nasdaq_chg_for_mult, nasdaq_pos=nasdaq_pos_for_mult,
        )
        for idx, amt in alloc_dict.items():
            res.loc[idx, '투자금액'] = amt
            if idx in final_holding_df.index:
                final_holding_df.loc[idx, '투자금액'] = amt
    else:
        alloc_dict          = {}
        invest_amount_total = 0
        internal_weights    = []
        us_mult_applied     = 0.0
        alloc_meta          = {}
        cap_info            = {}
        vol_info_dict       = {}

    invest_pct = invest_amount_total / total_investment if total_investment > 0 else 0.0

    print(f"\n=== 최종 리스트 ({len(final_holding)}개) - Final_score 정렬 ===")
    display_final = final_holding_df.copy()
    display_final['Ticker_Display'] = display_final.apply(
        lambda row: f"{row['Ticker']}**" if row.get('HighVol', False) else f"{row['Ticker']}  ",
        axis=1
    )
    print(display_final[["Ticker_Display", "등락", "Signal_sco", "수익률(%)", "Final_score", "신호", "투자금액"]]
          .rename(columns={"Ticker_Display": "Ticker", "Signal_sco": "Sco", "수익률(%)": "3M(%)", "Final_score": "Score"})
          .round(2)
          .to_string(index=False))

    # ── Holdings 투자비중 배분 출력 ──
    gate_sco_txt = f"{top3_avg_sco:.2f}" if pd.notna(top3_avg_sco) else "-"
    gate_pos_txt = f"{top3_avg_pos:.2f}" if pd.notna(top3_avg_pos) else "-"
    # ※ calc_up_days는 calc_holdings_alloc 내부에서 이미 호출됨 → 재호출 금지
    us_mult_txt  = str(us_mult_applied)

    print(f"\n[Holdings 투자비중 배분] (ALLOCATION_MAP[{n_holdings}])")
    print(f" strong_count={strong_count} / top3_avg_sco={gate_sco_txt} / top3_avg_pos={gate_pos_txt}")
    print(f" 나스닥={nasdaq_trend}(×{us_mult_txt})")
    for (_, row), w in zip(final_holding_df.iterrows(), internal_weights):
        idx  = row.name
        amt  = alloc_dict.get(idx, 0)
        meta = alloc_meta.get(idx, {})
        disp_mult = meta.get('display_mult', meta.get('raw_mult', 0))
        floor_m   = meta.get('floor_mult')
        is_fixed  = row['Ticker'] in FIXED_ONE_TICKERS
        if is_fixed:
            cap_note = f" [FIXED→CAP×{meta.get('cap_scale',1.0):.2f}]" if meta.get('cap_scaled') else " [FIXED]"
            mult_lbl = f"1.0{cap_note} → eff×{disp_mult:.2f}"
        else:
            floor_note = f" floor={floor_m:.2f}" if floor_m is not None else ""
            mult_lbl = f"×{us_mult_txt}{floor_note} → eff×{disp_mult:.2f}"
        print(f"   [{row['Ticker']}] 조정비중{w*100:.1f}% {mult_lbl} → ${amt:,.2f}")

    if cap_info.get('applied'):
        print(f" ⚠️  FIXED cap 적용: ${cap_info['fixed_total_before']:,.0f} → ${cap_info['fixed_total_after']:,.0f}"
              f" (상한 ${cap_info['cap_amount']:,.0f} = {FIXED_CAP_RATIO_WHEN_WEAK*100:.0f}%)")
    print(f" 총 투자비중={invest_pct*100:.1f}% / 총 투자금액=${invest_amount_total:,.2f} / $10,000")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for t in final_holding:
            f.write(f"{t}\n")
    print(f"\n저장 완료: {OUTPUT_FILE}")

    try:
        EXTRA_OUT = r"D:\py\0txt\buy_us_etf.txt"
        os.makedirs(os.path.dirname(EXTRA_OUT), exist_ok=True)
        with open(EXTRA_OUT, "w", encoding="utf-8") as f:
            for t in final_holding:
                f.write(f"{t}\n")
        print(f"추가 저장 완료: {EXTRA_OUT}")
    except Exception as e:
        print(f"추가 저장 실패: {e}")

    # JSON 통계 저장 (웹 리포트용)
    total_cnt = len(res)
    valid_cnt = len(res[res['Final_score'].notna()])
    atr_excl_cnt = len(atr_excluded)
    sco_pos = len(res[res['Signal_sco'] >= 0])
    sco_neg = len(res[res['Signal_sco'] < 0])
    sco_strong = len(res[res['Signal_sco'] >= 11])
    
    stats_data = {
        "avg_sco": round(float(res['Signal_sco'].mean()), 1) if not res.empty else None,
        "total_cnt": int(total_cnt),
        "valid_cnt": int(valid_cnt),
        "atr_excl_cnt": int(atr_excl_cnt),
        "sco_pos": sco_pos,
        "sco_neg": sco_neg,
        "sco_strong": sco_strong,
        "strong_count": strong_count,
        "top3_avg_sco": None if pd.isna(top3_avg_sco) else round(float(top3_avg_sco), 2),
        "top3_avg_pos": None if pd.isna(top3_avg_pos) else round(float(top3_avg_pos), 2),
        "nasdaq_trend": nasdaq_trend,
        "nasdaq_mult": us_mult_txt,
        "invest_pct": round(float(invest_pct) * 100, 1),
        "invest_amount_total": float(invest_amount_total),
        "vol63_median": round(float(np.median([v for v in [vol_info_dict.get(t, {}).get('vol63') for t in vol_info_dict] if v is not None])), 1) if vol_info_dict else None,
        "internal_weights": [round(w * 100, 4) for w in internal_weights],
        "n_holdings": n_holdings,
        "holdings_tickers": final_holding,
        "top3_tickers": top_3_tickers,
        "allocation_map_used": ALLOCATION_MAP.get(n_holdings, []),
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    stats_path = os.path.join("D:\\py\\report-us", "us_signal_stats.json")
    try:
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats_data, f, ensure_ascii=False, indent=4)
        print(f"✅ 통계 데이터가 '{stats_path}'에 저장되었습니다.")
    except Exception as e:
        print(f"⚠️ 통계 데이터 저장 실패: {e}")

    # ✅ 저점 신호 JSON 저장 (웹 대시보드용) + 지수대비(%) 포함
    low_signals = []
    for _, row in res.iterrows():
        sig_entry = {
            'ticker': row['Ticker'],
            'jeo': row.get('저', '-'),
            'jeo2': row.get('저2', '-'),
        }
        idx_rel_val = row.get('지수대비(%)')
        sig_entry['idx_rel'] = round(float(idx_rel_val), 2) if pd.notna(idx_rel_val) else None
        low_signals.append(sig_entry)
    
    low_signal_data = {
        'update_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'total_count': sum(1 for s in low_signals if s.get('jeo', '-') != '-' or s.get('jeo2', '-') != '-'),
        'signals': low_signals
    }
    low_signal_path = os.path.join("D:\\py\\report-us", "us_etf_low_signals.json")
    try:
        with open(low_signal_path, "w", encoding="utf-8") as f:
            json.dump(low_signal_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 저점 신호 데이터가 '{low_signal_path}'에 저장되었습니다.")
    except Exception as e:
        print(f"⚠️ 저점 신호 저장 실패: {e}")

    if atr_triggered:
        print("\n[ATR 트리거 종목 - 최근 2주]")
        df_trig = pd.DataFrame(atr_triggered)[['Ticker', 'ATR단계']]
        print(df_trig.to_string(index=False))
        print(f"트리거 종목 수: {len(atr_triggered)}개")
    else:
        print("\n[ATR 트리거 종목 - 최근 2주] 없음")

    if atr_excluded:
        print("\n[ATR 트레일링(-10%)로 제외 - 최근 2주]")
        df_excl = pd.DataFrame(atr_excluded)[['Ticker', 'ATR단계']]
        print(df_excl.to_string(index=False))
        print(f"제외 종목 수: {len(atr_excluded)}개")
    else:
        print("\n[ATR 트레일링(-10%)로 제외 - 최근 2주] 없음")

    if atr_filtered:
        print("\n" + "=" * 80)
        print("ATR 과열 감지 종목 (ATR5 > ATR60 * 1.8 이력 있음)")
        print("=" * 80)
        atr_df = pd.DataFrame(atr_filtered)
        atr_df = atr_df.sort_values('ATR비율', ascending=False)
        print(atr_df.to_string(index=False))
    else:
        print("\n✅ ATR 과열 감지 종목 없음")

    print("\n" + "=" * 80)
    print("📊 Signal_sco 기준 종목 분포")
    print("=" * 80)
    
    strong_stocks = res[res["Signal_sco"] >= 12]
    weak_stocks = res[res["Signal_sco"] < 0]
    
    print(f"\n전체 US_ETFS: {len(US_ETFS)}개")
    print(f"  sco >= 12: {len(strong_stocks)}개 ({len(strong_stocks)/len(res)*100:.1f}%)")
    print(f"  0 <= sco < 12: {len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])}개 ({len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])/len(res)*100:.1f}%)")
    print(f"  sco < 0: {len(weak_stocks)}개 ({len(weak_stocks)/len(res)*100:.1f}%)")
    print(f"\n합계 검증: {len(strong_stocks) + len(weak_stocks) + len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])} == {len(res)}?")

    print(f"\n[실행 시간] {time.time() - start_time:.2f}초")


if __name__ == "__main__":
    report_file_path = "D:\\py\\report-us\\report_us_etf.txt"
    try:
        f = open(report_file_path, "w", encoding="utf-8")
        original_stdout = sys.stdout
        sys.stdout = Tee(sys.stdout, f)
    except PermissionError:
        f = None
        original_stdout = None

    try:
        main()
    finally:
        if original_stdout is not None:
            sys.stdout = original_stdout
        if f is not None:
            f.close()

