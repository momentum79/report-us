import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import warnings
import requests
import json
import time
import os
import numpy as np
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
    2일 룩 신호 체크
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


def compute_early_stage_signals(c, h, l, v):
    """
    마크 미너비니 스타일 초입 단계 감지
    - VCP 축소 패턴, 베이스 품질, 브레이크아웃 타이밍, 거래량 폭발
    반환: dict with early_stage_score (0-100)
    """
    signals = {}
    
    # 1️⃣ 브레이크아웃 점수 (최근 브레이크아웃 후 얼마나 올랐는지 - 적게 오를수록 좋음)
    try:
        c_recent = c.iloc[-10:]
        h_before = h.iloc[-60:-10]
        
        if len(h_before) > 0:
            breakout_level = h_before.max()
            current_price = c.iloc[-1]
            
            if current_price > breakout_level:
                # 브레이크아웃 후 상승률 (낮을수록 좋음)
                breakout_gain = (current_price / breakout_level - 1) * 100
                # 0-10% 상승: 100점, 20% 이상: 0점
                signals['breakout_score'] = max(0, 100 - breakout_gain * 5)
            else:
                signals['breakout_score'] = 0
        else:
            signals['breakout_score'] = 0
    except Exception:
        signals['breakout_score'] = 0
    
    # 2️⃣ 베이스 품질 점수 (조정 구간의 변동폭 - 좁을수록 좋음)
    try:
        base_period = c.iloc[-60:-5]
        if len(base_period) > 20:
            base_high = base_period.max()
            base_low = base_period.min()
            base_range = (base_high - base_low) / base_low if base_low > 0 else 1
            # 변동폭 10%: 50점, 20%: 0점
            signals['base_score'] = max(0, 100 - base_range * 500)
        else:
            signals['base_score'] = 0
    except Exception:
        signals['base_score'] = 0
    
    # 3️⃣ VCP 수축 점수 (변동성 축소 패턴)
    try:
        # True Range 계산
        tr = pd.concat([
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs()
        ], axis=1).max(axis=1)
        atr_14 = tr.rolling(14).mean()
        
        if len(atr_14.dropna()) > 30:
            atr_recent = atr_14.iloc[-14:].mean()
            atr_before = atr_14.iloc[-30:-14].mean()
            
            if atr_before > 0:
                # 변동성 축소율 (양수일수록 좋음)
                atr_contraction = (atr_before - atr_recent) / atr_before
                signals['vcp_score'] = min(100, max(0, atr_contraction * 200))
            else:
                signals['vcp_score'] = 0
        else:
            signals['vcp_score'] = 0
    except Exception:
        signals['vcp_score'] = 0
    
    # 4️⃣ 거래량 폭발 점수
    try:
        if v is not None and len(v) > 50:
            vol_recent = v.iloc[-5:].mean()
            vol_avg = v.iloc[-50:].mean()
            
            if vol_avg > 0:
                vol_surge = vol_recent / vol_avg
                # 1.5배: 25점, 2배 이상: 50점
                signals['volume_score'] = min(100, (vol_surge - 1) * 50)
            else:
                signals['volume_score'] = 0
        else:
            signals['volume_score'] = 0
    except Exception:
        signals['volume_score'] = 0
    
    # 5️⃣ 종합 초입 점수 (가중 평균)
    signals['early_stage_score'] = (
        signals['breakout_score'] * 0.35 +
        signals['base_score'] * 0.25 +
        signals['vcp_score'] * 0.25 +
        signals['volume_score'] * 0.15
    )
    
    return signals


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


def load_tickers_from_csv(csv_path):
    """
    CSV 파일에서 티커 리스트를 읽어옴
    A열 2행부터 티커가 있다고 가정 (1행은 헤더)
    """
    try:
        df = pd.read_csv(csv_path)
        # 첫 번째 열의 모든 값을 티커로 사용 (헤더 제외)
        tickers = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
        print(f"CSV에서 {len(tickers)}개 티커 로드 완료: {csv_path}")
        return sorted(set(tickers))  # 중복 제거 및 정렬
    except Exception as e:
        print(f"[Err] CSV 로드 실패: {e}")
        return []


def main():
    # UTF-8 인코딩 설정 (Windows 콘솔 이모지 출력 에러 방지)
    import sys
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    start_time = time.time()

    
    CSV_PATH = r"D:\py\korea\us.csv"   # mark.csv(수동 워치리스트) 미생성 → us.csv 스크리너 export 공용
    US_TICKERS = load_tickers_from_csv(CSV_PATH)
    
    if not US_TICKERS:
        print(" 티커 리스트가 비어있습니다. CSV 파일을 확인하세요.")
        return

    print(f"총 {len(US_TICKERS)}개 티커 분석 시작...")

    end = datetime.today()
    # ⚠️ HLv7 = SMA60(5봉상승) AND SMA200(10봉상승) → bb.shift(10) 유효에 최소 210 거래봉 필요.
    #   300일(=약 206봉)은 부족 → 마지막 봉 bb.shift(10)=NaN → HLv7 붕괴 → 실제 LIME 이 GREEN 으로 표기
    #   (usa_jasantop4_stocks.py EOG 사례와 동일). 차트(전체 캐시구간)와 맞추려 820일로 확대.
    #   집 bat READONLY 구간이라 창 확대해도 캐시 슬라이스만 → 재다운로드 0.
    start = end - timedelta(days=820)

    rows = []
    atr_filtered = []
    failed_tickers = []

    # 병렬 prefetch: US_TICKERS 배치 다운로드로 캐시 선충전 (값은 단일 yf.download 와 동일 검증됨).
    prefetch(US_TICKERS, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    # ✅ 40개씩 배치로 나누기
    batch_size = 40
    for batch_idx in range(0, len(US_TICKERS), batch_size):
        batch = US_TICKERS[batch_idx:batch_idx + batch_size]
        print(f"\n📦 배치 {batch_idx//batch_size + 1}/{(len(US_TICKERS)-1)//batch_size + 1} 처리 중... ({len(batch)}개 티커)")
        
        # 각 티커별 처리 (공유 캐시 us_ohlcv_cache 증분 조회 — 배치 풀다운로드 제거)
        #   get_us_ohlcv 는 auto_adjust=True 풀다운로드와 동일 결과 보장(드리프트 검사)
        for ticker in batch:
            try:
                df = get_us_ohlcv(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

                if df is None or df.empty or len(df) < 130:
                    continue

                df = df.copy()
                df.columns = [str(c).capitalize() for c in df.columns]

                if 'Close' in df.columns:
                    df = df.rename(columns={"Close": "close", "High": "high", "Low": "low", "Volume": "volume"})
                elif 'close' not in df.columns:
                    continue

                df_sig = calculate_signal(df)

                if df_sig['atr_filter'].iloc[-1]:
                    atr_filtered.append({
                        'Ticker': ticker,
                        'ATR5': df_sig['atr5'].iloc[-1],
                        'ATR60': df_sig['atr60'].iloc[-1],
                        'ATR비율': df_sig['atr5'].iloc[-1] / df_sig['atr60'].iloc[-1]
                    })
                    continue

                df_sig = check_coloryp_condition(df_sig)
                is_high_volume = check_volume_intensity(df_sig)
                new_signal = get_new_signal(df_sig)

                close = df_sig["close"]
                high = df_sig["high"]
                low = df_sig["low"]
                volume = df_sig["volume"] if "volume" in df_sig.columns else None
                
                # 수익률 계산 (3개월, 1개월)
                rtn_3m = (close.iloc[-1] / close.iloc[-61] - 1) * 100 if len(close) > 61 else None
                rtn_1m = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) > 21 else None

                today_chg = (
                    (close.iloc[-1] / close.iloc[-2] - 1) * 100
                    if len(close) > 1 else 0
                )

                latest_sco = (
                    df_sig["sco"].dropna().iloc[-1]
                    if not df_sig["sco"].dropna().empty else None
                )
                
                # 🆕 초입 단계 점수 계산
                early_signals = compute_early_stage_signals(close, high, low, volume)

                rows.append({
                    "Ticker": ticker,
                    "Signal_sco": latest_sco if latest_sco is not None else None,
                    "수익률(%)": rtn_3m if rtn_3m is not None else None,
                    "1M수익률(%)": rtn_1m if rtn_1m is not None else None,
                    "당일등락률(%)": today_chg if today_chg is not None else None,
                    "종가": close.iloc[-1] if len(close) > 0 else None,
                    "HighVol": is_high_volume,
                    "NewSig": new_signal,
                    "early_stage_score": early_signals["early_stage_score"],
                    "breakout_score": early_signals["breakout_score"],
                    "vcp_score": early_signals["vcp_score"]
                })

            except Exception as e:
                failed_tickers.append(ticker)
                print(f"⚠️ {ticker} 처리 실패: {e}")
                continue

    if failed_tickers:
        print(f"\n 처리 실패한 티커 ({len(failed_tickers)}개): {', '.join(failed_tickers)}")
            
    if not rows:
        print("️ 수집된 데이터가 없습니다.")
        return

    res = pd.DataFrame(rows)

    if res.empty or "Signal_sco" not in res.columns:
        print(" 유효한 결과 없음")
        return

    res = res.dropna(subset=["Signal_sco"]).copy()

    if res.empty:
        print("Signal_sco가 있는 데이터가 없습니다.")
        return
    
    # 🆕 과도한 상승 필터 (3개월 80% 이상 제외)
    res = res[res["수익률(%)"] <= 80].copy()
    
    if res.empty:
        print("⚠️ 필터 후 데이터가 없습니다 (모든 종목이 80% 이상 상승)")
        return

    res["Norm_sco"] = normalize_0_1(res["Signal_sco"])
    res["Rank_rtn"] = res["수익률(%)"].rank(pct=True)
    res["Norm_early"] = normalize_0_1(res["early_stage_score"])

    # 🆕 가중치 조정: Early_stage 50% + Signal_sco 35% + Return 15%
    w_early, w_sco, w_rtn = 50, 35, 15
    res["Final_score"] = (
        w_early * res["Norm_early"] + 
        w_sco * res["Norm_sco"] + 
        w_rtn * res["Rank_rtn"]
    )

    res = res.sort_values("Final_score", ascending=False).reset_index(drop=True)

    print("\n=== US Momentum Top (VCP Early Stage) ===")

    display_df = res.head(30).copy()
    display_df['Ticker_Display'] = display_df.apply(
        lambda row: f"{row['Ticker']}**" if row['HighVol'] else f"{row['Ticker']}  ",
        axis=1
    )

    print(display_df[["Ticker_Display", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "1M수익률(%)", "early_stage_score", "Final_score", "NewSig"]]
          .rename(columns={"Ticker_Display": "Ticker", "early_stage_score": "Early_sco", "종가": "Price($)", "당일등락률(%)": "등락률(%)"})
          .round(2)
          .to_string(index=False, max_rows=None))
          
    # 🆕 VCP Early Stage Top 20 저장 (D:\py\vcpearly.txt)
    vcp_out_path = r"D:\py\vcpearly.txt"
    try:
        top20_tickers = res.head(20)["Ticker"].tolist()
        with open(vcp_out_path, "w", encoding="utf-8") as f:
            for t in top20_tickers:
                f.write(f"{t}\n")
        print(f"\n[저장 완료] VCP Top 20 티커 저장: {vcp_out_path} ({len(top20_tickers)}개)")
    except Exception as e:
        print(f"\n[저장 실패] VCP Top 20 저장 중 에러: {e}")
    
    OUT = os.path.join(os.path.dirname(__file__), "buy_us_stock.txt")

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
    print(display_top4[["Ticker_Display", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "1M수익률(%)", "early_stage_score", "Final_score", "NewSig"]]
          .rename(columns={"Ticker_Display": "Ticker", "early_stage_score": "Early_sco", "종가": "Price($)", "당일등락률(%)": "등락률(%)"})
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
    print(display_final[["Ticker_Display", "종가", "당일등락률(%)", "Signal_sco", "수익률(%)", "1M수익률(%)", "early_stage_score", "Final_score", "NewSig"]]
          .rename(columns={"Ticker_Display": "Ticker", "early_stage_score": "Early_sco", "종가": "Price($)", "당일등락률(%)": "등락률(%)"})
          .round(2)
          .to_string(index=False))
          
    with open(OUT, "w", encoding="utf-8") as f:
        for t in final_list:
            f.write(f"{t}\n")

    print(f"\n저장 완료: {OUT}")

    if atr_filtered:
        print("\n" + "=" * 80)
        print(" ATR 필터로 제외된 종목 (고변동성: ATR5 > ATR60 * 1.8)")
        print("=" * 80)
        atr_df = pd.DataFrame(atr_filtered)
        atr_df = atr_df.sort_values('ATR비율', ascending=False)
        atr_df[['ATR5', 'ATR60', 'ATR비율']] = atr_df[['ATR5', 'ATR60', 'ATR비율']].round(1)
        print(atr_df.to_string(index=False))
        print(f"\n제외된 종목 수: {len(atr_filtered)}개")
    else:
        print("\n ATR 필터로 제외된 종목 없음")

    print("\n" + "=" * 80)
    print(" Signal_sco 기준 종목 분포")
    print("=" * 80)
    
    strong_stocks = res[res["Signal_sco"] >= 12]
    weak_stocks = res[res["Signal_sco"] < 0]
    
    print(f"\n전체 US_TICKERS: {len(US_TICKERS)}개")
    print(f"  분석 완료: {len(res)}개")
    print(f"  sco >= 12: {len(strong_stocks)}개 ({len(strong_stocks)/len(res)*100:.1f}%)")
    print(f"  0 <= sco < 12: {len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])}개 ({len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])/len(res)*100:.1f}%)")
    print(f"  sco < 0: {len(weak_stocks)}개 ({len(weak_stocks)/len(res)*100:.1f}%)")
    print(f"\n합계 검증: {len(strong_stocks) + len(weak_stocks) + len(res[(res['Signal_sco'] >= 0) & (res['Signal_sco'] < 12)])} == {len(res)}?")

    print(f"\n[실행 시간] {time.time() - start_time:.2f}초")
if __name__ == "__main__":
    main()
