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
import io
import subprocess
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coloryp_core import compute_lime_final  # LIME 재진입 단일 소스

# Force UTF-8 for stdout/stderr to avoid encoding errors on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            try:
                f.write(obj)
                f.flush()
            except ValueError:
                pass
    def flush(self):
        for f in self.files:
            try:
                f.flush()
            except ValueError:
                pass  # 이미 닫힌 파일은 무시

OUT_TXT = Path(__file__).resolve().parent / "report_futures.txt"
TMP_TXT = Path(__file__).resolve().parent / "report_futures_tmp.txt"
f_out = open(TMP_TXT, "w", encoding="utf-8")
sys.stdout = Tee(sys.stdout, f_out)

DATA_SUCCESS = False

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
    df['HLd71'] = np.where((df.k3 > df.k3.shift(1)) & (df.k2 > df.k2.shift(1)) & (df.rsi14 >= df.rsi14.shift(1)), 1,
                  np.where((df.k3 < df.k3.shift(1)) & (df.k2 < df.k2.shift(1)) & (df.rsi14 < df.rsi14.shift(1)), -1, 0))
    df['HLv71'] = df.HLd71.replace(0, np.nan).ffill().fillna(0)
    df['aa'], df['bb'] = sma(df.close, 60), sma(df.close, 200)
    df['HLd7'] = np.where((df.aa >= df.aa.shift(5)) & (df.bb >= df.bb.shift(10)), 1,
                 np.where((df.aa < df.aa.shift(5)) & (df.bb < df.bb.shift(10)), -1, 0))
    df['HLv7'] = df.HLd7.replace(0, np.nan).ffill().fillna(0)
    # TV: sum = m0ang + m1ang + m2ang + m3ang + m4ang (5개 이평 각도 합)
    df['ang_sum'] = df['m0ang'] + df['m1ang'] + df['m2ang'] + df['m3ang'] + df['m4ang']
    df['lime_final'] = compute_lime_final(df.close, df.HLv99, df.HLv7, df.HLv71, df.M1, df.M2, df.M3, df.m3s)
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
        df = yf.download(ticker, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)

        if df.empty or len(df) < 20:
            return None, None, None, None

        if isinstance(df.columns, pd.MultiIndex):
            lvl0 = [str(c).lower() for c in df.columns.get_level_values(0)]
            lvl1 = [str(c).lower() for c in df.columns.get_level_values(1)]
            df.columns = lvl0 if 'close' in lvl0 else lvl1
        else:
            df.columns = [str(c).lower() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                s = df[col]
                if isinstance(s, pd.DataFrame):
                    df[col] = s.iloc[:, 0]
                df[col] = pd.to_numeric(df[col], errors='coerce')

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


def short_name(ticker: str) -> str:
    """티커 → 짧은 표시명 변환
    ES=F      → ES
    AUDUSD=X  → AUD  (xxxUSD=X → xxx)
    EURUSD=X  → EUR
    MXNUSD=X  → MXN  (xxxUSD=X → xxx)
    JPYUSD=X  → JPY  (xxxUSD=X → xxx)
    BRLUSD=X  → BRL  (xxxUSD=X → xxx)
    BTC-USD   → BTC  (xxx-USD → xxx)
    ETH-USD   → ETH
    """
    import re
    # xxx-USD (코인)
    if ticker.endswith("-USD"):
        return ticker[:-4]
    # xxxUSD=X (통화쌍, 앞 3자리만)
    if ticker.endswith("USD=X"):
        return ticker[:3]
    # xxx=X (단순 FX: JPY=X, MXN=X 등)
    if ticker.endswith("=X"):
        return ticker[:-2]
    # xxx=F (선물)
    if ticker.endswith("=F"):
        return ticker[:-2]
    return ticker


def normalize_0_1(series):
    """정규화 함수"""
    min_val = series.min()
    max_val = series.max()
    if max_val == min_val:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - min_val) / (max_val - min_val)


# ====== 해외선물 + FX + 암호화폐 리스트 ======
# ES → ES=F, NQ → NQ=F ... FX는 AUDUSD=X 그대로, BTC-USD 그대로
US_ETFS = [
    # 주가지수
    "ES=F",       # E-Mini S&P 500
    "NQ=F",       # Nasdaq 100
    "RTY=F",      # E-mini Russell 2000
    # 귀금속
    "GC=F",       # Gold
    "SI=F",       # Silver
    "PL=F",       # Platinum
    "HG=F",       # Copper
    "PA=F",       # Palladium
    # 에너지
    "CL=F",       # Crude Oil WTI
    "NG=F",       # Natural Gas
    # 채권
    "ZB=F",       # U.S. Treasury Bond
    # 곡물
    "ZC=F",       # Corn
    "ZO=F",       # Oat
    "ZW=F",       # Wheat (CBOT)
    "ZL=F",       # Soybean Oil
    "ZS=F",       # Soybean
    # 축산물
    "LE=F",       # Live Cattle
    # FX (모두 각국통화/USD 방향으로 통일)
    "AUDUSD=X",   # AUD/USD
    "GBPUSD=X",   # GBP/USD
    "EURUSD=X",   # EUR/USD
    "NZDUSD=X",   # NZD/USD
    "MXNUSD=X",   # MXN/USD
    "JPYUSD=X",   # JPY/USD
    "BRLUSD=X",   # BRL/USD (브라질 헤알)
    # 암호화폐
    "BTC-USD",    # Bitcoin
    "ETH-USD",    # Ethereum
]

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
    
    # Double SMA
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
    signal_yesterday = len(constat) >= 3 and constat.iloc[-3] and (not constat.iloc[-2])
    
    jeo2_signal = "-"
    if signal_today or signal_yesterday:
        jeo2_signal = "저2"
        
    return jeo_signal, jeo2_signal

def main():
    start_time = time.time()
    warnings.filterwarnings("ignore")
    
    atr_triggered = []
    atr_excluded = []
    atr_filtered = []
    
    end = datetime.now()
    start = end - timedelta(days=400)  # 200일 이평 확보 위해 400일(영업일 약 280일)
    
    rows = []
    
    for ticker in US_ETFS:
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

            # ── MultiIndex 컬럼 처리 ──────────────────────────────────────
            # yfinance 버전에 따라 두 가지 형태로 내려옴:
            #   신버전: ('Price', 'ES=F')  → level0='Price'(=컬럼명), level1=ticker
            #   구버전: ('ES=F', 'Close')  → level0=ticker, level1=컬럼명
            # 'close'가 level0에 있으면 그걸 쓰고, 없으면 level1을 사용
            if isinstance(df.columns, pd.MultiIndex):
                lvl0 = [str(c).lower() for c in df.columns.get_level_values(0)]
                lvl1 = [str(c).lower() for c in df.columns.get_level_values(1)]
                if 'close' in lvl0:
                    df.columns = lvl0
                else:
                    df.columns = lvl1
            else:
                df.columns = [str(c).lower() for c in df.columns]

            # 중복 컬럼 제거
            df = df.loc[:, ~df.columns.duplicated()]

            if 'close' not in df.columns:
                print(f"⚠️ {ticker} 컬럼 없음: {df.columns.tolist()}")
                continue

            # 각 컬럼을 확실하게 1차원 Series로 변환
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    s = df[col]
                    if isinstance(s, pd.DataFrame):
                        df[col] = s.iloc[:, 0]
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # close NaN 행 제거 (선물 티커는 당일 미체결 빈 행이 마지막에 붙는 경우 있음)
            df = df.dropna(subset=['close'])

            if len(df) < 130:
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
                        'Ticker': short_name(ticker),
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
                    'Ticker': short_name(ticker),
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
                        'Ticker': short_name(ticker),
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

            # ✅ 저/저2 신호 계산
            try:
                jeo_signal, jeo2_signal = calculate_tv_signals(df_sig)
            except Exception:
                jeo_signal, jeo2_signal = "-", "-"

            close = df_sig["close"]
            rtn = (close.iloc[-1] / close.iloc[-61] - 1) * 100

            today_chg = (
                (close.iloc[-1] / close.iloc[-2] - 1) * 100
                if len(close) > 1 else 0
            )

            latest_sco = (
                df_sig["sco"].dropna().iloc[-1]
                if not df_sig["sco"].dropna().empty else None
            )
            
            # ✅ 15개 컬럼 데이터 수집
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

            rows.append({
                "Ticker": short_name(ticker),
                "등락": today_chg,
                "위치": price_pos,
                "Signal_sco": latest_sco if latest_sco is not None else None,
                "정배": alignment,
                "신호": new_signal,
                "저": jeo_signal,
                "저2": jeo2_signal,
                "5": ma_dirs[0],
                "10": ma_dirs[1],
                "20": ma_dirs[2],
                "60": ma_dirs[3],
                "120": ma_dirs[4],
                "추세": trend,
                "136평": ma136_pct,
                "수익률(%)": rtn if rtn is not None else None,
                "Final_score": None,  # 나중에 계산
                "HighVol": is_high_volume
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
    res["Norm_sco"] = normalize_0_1(res["Signal_sco"].fillna(res["Signal_sco"].min()))
    res["Norm_rtn"] = normalize_0_1(res["수익률(%)"].fillna(res["수익률(%)"].min()))

    w_sco, w_rtn = 85, 15
    res["Final_score"] = w_sco * res["Norm_sco"] + w_rtn * res["Norm_rtn"]

    res = res.sort_values("Final_score", ascending=False).reset_index(drop=True)

    print("\n=== 해외선물 / FX / 암호화폐 Momentum Top ===")

    # ✅ 15개 컬럼 출력 (Name 제외)
    display_df = res.head(30).copy()
    display_df['Ticker_Display'] = display_df.apply(
        lambda row: f"{row['Ticker']}**" if row['HighVol'] else f"{row['Ticker']}  ",
        axis=1
    )

    print(display_df[["Ticker_Display", "등락", "위치", "Signal_sco", "정배", "신호", 
                      "5", "10", "20", "60", "120", "추세", "136평", "수익률(%)", "Final_score"]]
          .rename(columns={"Ticker_Display": "Ticker", "Signal_sco": "Sco", "수익률(%)": "3M(%)", "Final_score": "Score"})
          .round(2)
          .to_string(index=False, max_rows=None))
          
    # -------------------------
    # 주문/보유 리스트 생성 (Top4 + 이전 Top4 유지)
    # 규칙:
    #  - 오늘 Top4는 무조건 포함
    #  - "이전 Top4" 중 오늘 Top4에서 밀려난 종목은 sco >= 11일 때만 유지
    #  - 최종 출력/저장은 Final_score 기준으로 정렬된 결과
    # -------------------------
    OUT = "D:/py/buy_futures.txt"

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
    # 주문용 Top4는 간단하게 5개 컬럼만
    print(display_top4[["Ticker_Display", "Signal_sco", "수익률(%)", "Final_score", "신호"]]
          .rename(columns={"Ticker_Display": "Ticker", "Signal_sco": "Sco", "수익률(%)": "3M(%)", "Final_score": "Score"})
          .round(2)
          .to_string(index=False))

    if prev_top4:
        print(f"\n이전 Top4: {prev_top4}")
    else:
        print("\n이전 Top4: 없음(첫 실행 또는 파일 없음)")

    if carryover:
        tmp = res[res["Ticker"].isin(carryover)][["Ticker", "Signal_sco", "수익률(%)", "Final_score"]].copy()
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
    # 최종 리스트도 간단하게 5개 컬럼만
    print(display_final[["Ticker_Display", "Signal_sco", "수익률(%)", "Final_score", "신호"]]
          .rename(columns={"Ticker_Display": "Ticker", "Signal_sco": "Sco", "수익률(%)": "3M(%)", "Final_score": "Score"})
          .round(2)
          .to_string(index=False))
          
    with open(OUT, "w", encoding="utf-8") as f:
        for t in final_list:
            f.write(f"{t}\n")

    print(f"\n저장 완료: {OUT}")

    # 🆕 D:\0txt 폴더에도 추가 저장
    try:
        EXTRA_OUT = r"D:\py\0txt\buy_futures.txt"
        os.makedirs(os.path.dirname(EXTRA_OUT), exist_ok=True)
        with open(EXTRA_OUT, "w", encoding="utf-8") as f:
            for t in final_list:
                f.write(f"{t}\n")
        print(f"추가 저장 완료: {EXTRA_OUT}")
    except Exception as e:
        print(f"추가 저장 실패: {e}")

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
    
    print(f"\n전체 선물/FX/코인: {len(US_ETFS)}개")
    print(f"  sco >= 12: {len(strong_stocks)}개 ({len(strong_stocks)/len(res)*100:.1f}%)")
    print(f"  0 <= sco < 12: {len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])}개 ({len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])/len(res)*100:.1f}%)")
    print(f"  sco < 0: {len(weak_stocks)}개 ({len(weak_stocks)/len(res)*100:.1f}%)")
    print(f"\n합계 검증: {len(strong_stocks) + len(weak_stocks) + len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])} == {len(res)}?")

    # ✅ 저점 신호 JSON 저장 (웹 대시보드용)
    low_signals = []
    for _, row in res.iterrows():
        if row.get('저', '-') != '-' or row.get('저2', '-') != '-':
            low_signals.append({
                'ticker': row['Ticker'],
                'name': row['Ticker'],  # 이름이 따로 없으므로 티커로 대체
                'change_pct': round(float(row.get('등락', 0)), 2),
                'position': int(row.get('위치', 0)),
                'jeo': row.get('저', '-'),
                'jeo2': row.get('저2', '-'),
            })
    
    low_signal_data = {
        'update_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'total_count': len(low_signals),
        'signals': low_signals
    }
    low_signal_path = os.path.join("D:\\py\\report-us", "futures_low_signals.json")
    try:
        with open(low_signal_path, "w", encoding="utf-8") as f:
            json.dump(low_signal_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 해선 저점 신호 데이터가 '{low_signal_path}'에 저장되었습니다.")
    except Exception as e:
        print(f"⚠️ 저점 신호 저장 실패: {e}")

    print(f"\n[실행 시간] {time.time() - start_time:.2f}초")

    # make_index_futures.py 자동 실행
    print("\n=== make_index_futures.py 실행 중 ===")
    script_path = Path(__file__).resolve().parent / "make_index_futures.py"
    try:
        subprocess.run(["python", str(script_path)], check=True)
    except Exception as e:
        print(f"make_index_futures.py 실행 실패: {e}")

    global DATA_SUCCESS
    DATA_SUCCESS = True


if __name__ == "__main__":
    _original_stdout = sys.stdout
    try:
        main()
    finally:
        sys.stdout = _original_stdout  # 먼저 복원
        f_out.close()                  # 그 다음 닫기
        import os
        if DATA_SUCCESS:
            if TMP_TXT.exists():
                os.replace(TMP_TXT, OUT_TXT)
        else:
            if TMP_TXT.exists():
                os.remove(TMP_TXT)
