"""
backfill_market_regime_track.py
================================
market_regime_track_total.csv 의 과거 데이터를 채워넣는 스크립트.

jasantop4_global_softcap.py 의 build_market_regime_chart() 가
매일 실시용으로 append 하는 CSV 파일에 과거 일자별 데이터를 소급 삽입한다.

방식:
  - ALL_US_TICKERS + KR_ETFS 의 과거 OHLCV 를 yfinance / pykrx 로 수집
  - 각 날짜별로 Signal_sco(= calculate_signal 결과), 수익률(%) 를 계산
  - 구간별 카운트(Worst/Neutral/Recovery/HotVeryHot/Other, sco_strong/mid/weak/neg) 를 집계
  - 기존 CSV 에 없는 날짜만 추가 (중복 skip)

실행:
  python backfill_market_regime_track.py [--start 2024-01-01] [--end 2025-04-06]
"""

import argparse
import os
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────────────────
# ★ 경로 설정 (필요시 수정)
# ──────────────────────────────────────────────────────────
OUT_DIR       = r"D:\py\report-us"
OUT_TRACK_CSV = os.path.join(OUT_DIR, "market_regime_track_total.csv")
OUT_TRACK_JSON= os.path.join(OUT_DIR, "market_regime_track_total.json")

# ──────────────────────────────────────────────────────────
# Universe (jasantop4_global_softcap.py 와 동일)
# ──────────────────────────────────────────────────────────
US_ETFS = [
    "SPY", "QQQ", "DIA", "IWM", "EFA", "EEM", "VTI", "VOO", "AGG", "BND",
    "GLD", "SLV", "TLT", "IEF", "LQD", "HYG", "XLE", "XLF", "XLV", "XLI",
    "XLK", "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC", "VNQ", "VWO", "VEA",
    "IEMG", "IEFA", "ITOT", "IJH", "IJR", "VTV", "VUG", "IVV", "RSP", "SCHD",
    "VIG", "VYM", "ARKK", "ARKW", "TAN", "ICLN", "SMH", "SOXX", "IBB", "XBI",
    "JETS", "ARKF", "BOTZ", "LIT", "REMX", "DBA", "PDBC", "UNG",
    "IBIT", "ETHA", "EWY", "EWZ", "FEZ", "EWT", "EWC", "EWA", "ITA", "XAR", "CARZ",
    "GMOM", "QMOM", "EMGF", "PICK", "PDP", "PTF", "EIS", "TUR", "SRVR"
]
WORLD_ETFS = sorted(set([
    "SPY", "QQQ", "IWM", "SCZ",
    "EWY", "EWJ", "EWH", "FXI", "INDA", "EIDO", "EWT", "VNM", "EPHE", "THD", "EWS", "EWM",
    "EZU", "VGK", "EWG", "EWU", "EWQ", "EWI", "EWP", "GREK",
    "EWC", "EWW", "EWZ",
    "EZA", "KSA", "EIS", "TUR",
    "EWA", "EWL", "ENZL",
]))
ALL_US_TICKERS = sorted(set(US_ETFS) | set(WORLD_ETFS))

# 한국 ETF — pykrx 없이도 동작하도록 optional
KR_ETFS = [
    '091160', '091180', '305720', '117460', '244580', '091170',
    '102970', '117680', '117700', '139230', '228790', '495050',
    '069500', '229200', '487230', '449450', '475050', '371160',
    '455850', '195930', '377990', '411060', '478150', '453810',
    '446770', '434730', '469070', '449180', '449190', '241180',
    '147970', '325020'
]

# ──────────────────────────────────────────────────────────
# 지표 계산 함수 (jasantop4_global_softcap.py 와 동일 로직)
# ──────────────────────────────────────────────────────────
def sma(s, n):
    return s.rolling(n).mean()

def calculate_rsi_wilder(s, n=14):
    delta = s.diff()
    u = delta.clip(lower=0)
    d = (-delta).clip(lower=0)
    rma_u = u.ewm(alpha=1/n, adjust=False).mean()
    rma_d = d.ewm(alpha=1/n, adjust=False).mean()
    rs = rma_u / rma_d
    return 100 - (100 / (1 + rs))

def stoch(close, high, low, n):
    ll = low.rolling(n).min()
    hh = high.rolling(n).max()
    return (close - ll) / (hh - ll) * 100

def calculate_signal_sco(df):
    """
    jasantop4_global_softcap.py 의 calculate_signal() 핵심 로직.
    df: close/high/low 컬럼을 가진 OHLCV DataFrame (일봉, 충분한 길이 필요)
    반환: 마지막 행의 Signal_sco 값 (float)
    """
    if len(df) < 130:
        return np.nan

    close = df['close']
    high  = df['high']
    low   = df['low']

    # ATR
    hl   = high - low
    hc   = (high - close.shift(1)).abs()
    lc   = (low  - close.shift(1)).abs()
    tr   = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr5  = tr.rolling(5).mean()
    atr60 = tr.rolling(60).mean()

    # 이평
    M = {i: close.rolling(w).mean() for i, w in enumerate([5,10,20,60,120])}

    rad = 180 / np.pi
    ang = {}
    for i in range(5):
        prev = M[i].shift(1)
        ang[i] = np.sin(np.arctan((M[i] - prev) / prev * 100)) * rad

    # 이평 방향
    def ms(mi, tol=None, tol2=None):
        prev = M[mi].shift(1)
        if tol is not None:
            return np.where(M[mi].isna() | prev.isna(), np.nan,
                            np.where((M[mi] >= prev) | (ang[mi] > tol), 1, -1))
        return np.where(M[mi].isna() | prev.isna(), np.nan,
                        np.where(M[mi] >= prev, 1, -1))

    m0s = pd.Series(ms(0), index=df.index)
    m1s = pd.Series(ms(1), index=df.index)
    m2s = pd.Series(ms(2), index=df.index)
    m3s = pd.Series(np.where(M[3].isna() | M[3].shift(1).isna(), np.nan,
                             np.where((M[3] >= M[3].shift(1)) | (ang[3] > -2), 1, -1)), index=df.index)
    m4s = pd.Series(np.where(M[4].isna() | M[4].shift(1).isna(), np.nan,
                             np.where((M[4] >= M[4].shift(1)) | (ang[4] > -1), 1, -1)), index=df.index)
    m3sm= pd.Series(np.where(M[3].isna() | M[3].shift(1).isna(), np.nan,
                             np.where((M[3] <= M[3].shift(1)) | (ang[3] < 2), -1, 1)), index=df.index)

    HLd99 = np.where((m1s==1)&(m2s==1)&(m3s==1), 2,
             np.where((m1s==1)&(m2s==1), 1,
             np.where((m0s==-1)&(m1s==-1)&(m2s==-1)&(m3sm==-1), -2,
             np.where((m1s==-1)&(m2s==-1), -1, 0))))
    HLv99 = pd.Series(HLd99, index=df.index).replace(0, np.nan).ffill().fillna(0)

    rsi1  = calculate_rsi_wilder(close)
    rsi14 = sma(rsi1, 14)
    k3    = sma(stoch(close, high, low, 20), 10)
    k2    = sma(stoch(close, high, low, 10),  5)

    HLd71 = np.where((k3>k3.shift(1))&(k2>k2.shift(1))&(rsi14>=rsi14.shift(1)),  1,
             np.where((k3<k3.shift(1))&(k2<k2.shift(1))&(rsi14<rsi14.shift(1)), -1, 0))
    HLv71 = pd.Series(HLd71, index=df.index).replace(0, np.nan).ffill().fillna(0)

    aa = sma(close, 60); bb = sma(close, 200)
    HLd7 = np.where((aa>=aa.shift(5))&(bb>=bb.shift(10)), 1,
            np.where((aa<aa.shift(5))&(bb<bb.shift(10)), -1, 0))
    HLv7 = pd.Series(HLd7, index=df.index).replace(0, np.nan).ffill().fillna(0)

    # sco99 점수 계산
    scores = pd.Series(0.0, index=df.index)
    scores += np.where(HLv99 >= 1,  2, np.where(HLv99 <= -1, -2, 0))
    scores += np.where(HLv71 == 1,  2, np.where(HLv71 == -1, -2, 0))
    scores += np.where(HLv7  == 1,  2, np.where(HLv7  == -1, -2, 0))
    for i in range(5):
        scores += np.where(pd.Series(m0s if i==0 else m1s if i==1 else m2s if i==2 else m3s if i==3 else m4s, index=df.index) == 1, 1,
                  np.where(pd.Series(m0s if i==0 else m1s if i==1 else m2s if i==2 else m3s if i==3 else m4s, index=df.index) == -1, -1, 0))

    sco99 = pd.Series(scores, index=df.index)
    sco   = sco99.rolling(4).mean()

    return float(sco.iloc[-1]) if not pd.isna(sco.iloc[-1]) else np.nan


def calc_return_3m(close_series):
    """마지막 날 기준 63거래일(약 3개월) 수익률(%)"""
    if len(close_series) < 64:
        return np.nan
    start = close_series.iloc[-64]
    end   = close_series.iloc[-1]
    if start == 0 or pd.isna(start):
        return np.nan
    return round((end / start - 1) * 100, 2)


# ──────────────────────────────────────────────────────────
# 미국 티커 일봉 다운로드 (yfinance bulk)
# ──────────────────────────────────────────────────────────
def download_us_ohlcv(tickers, start, end):
    """
    yfinance 로 여러 티커의 일봉을 한 번에 다운로드.
    반환: dict[ticker] = DataFrame(close/high/low)
    """
    print(f"  [US] yfinance 다운로드: {len(tickers)}개 티커 ({start} ~ {end})")
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by='ticker',
    )

    result = {}
    for t in tickers:
        try:
            if len(tickers) == 1:
                df = raw[['Close','High','Low']].copy()
            else:
                df = raw[t][['Close','High','Low']].copy()
            df.columns = ['close','high','low']
            df = df.dropna(how='all')
            if len(df) >= 10:
                result[t] = df
        except Exception:
            pass
    print(f"  [US] 성공: {len(result)}/{len(tickers)}개")
    return result


# ──────────────────────────────────────────────────────────
# 한국 ETF pykrx 다운로드 (optional)
# ──────────────────────────────────────────────────────────
def download_kr_ohlcv(tickers, start, end):
    try:
        from pykrx import stock as pykrx_stock
    except ImportError:
        print("  [KR] pykrx 미설치 → 한국 ETF 스킵")
        return {}

    result = {}
    start_str = start.replace('-', '')
    end_str   = end.replace('-', '')
    for t in tickers:
        # pykrx 에서 숫자가 아닌 티커(0038A0 등)는 스킵
        if not t.isdigit():
            continue
        try:
            df = pykrx_stock.get_market_ohlcv_by_date(start_str, end_str, t)
            if df is None or df.empty:
                continue
            df = df.rename(columns={'종가': 'close', '고가': 'high', '저가': 'low'})
            df = df[['close','high','low']].dropna(how='all')
            if len(df) >= 10:
                result[t] = df
        except Exception:
            pass
    print(f"  [KR] pykrx 성공: {len(result)}/{len(tickers)}개")
    return result


# ──────────────────────────────────────────────────────────
# 날짜별 regime 집계
# ──────────────────────────────────────────────────────────
def compute_regime_for_date(target_date_str, all_ohlcv, window=300):
    """
    target_date_str: 'YYYY-MM-DD'
    all_ohlcv: dict[ticker] = full DataFrame (close/high/low, DatetimeIndex)
    window: 지표 계산에 사용할 과거 행 수 (최소 200 이상 권장)
    """
    target_dt = pd.Timestamp(target_date_str)

    sco_list = []
    rtn_list = []

    for ticker, df in all_ohlcv.items():
        # target_date 이하 데이터만 사용
        sub = df[df.index <= target_dt].tail(window)
        if len(sub) < 130:
            continue

        sco = calculate_signal_sco(sub)
        rtn = calc_return_3m(sub['close'])

        if not pd.isna(sco):
            sco_list.append(sco)
        if not pd.isna(rtn):
            rtn_list.append(rtn)

    if not sco_list:
        return None

    sco_arr = np.array(sco_list)
    rtn_arr = np.array(rtn_list) if rtn_list else np.array([np.nan]*len(sco_list))

    n = len(sco_arr)

    # zone counts (sco/rtn 길이가 다를 수 있으므로 최소값 기준)
    m = min(len(sco_arr), len(rtn_arr))
    s = sco_arr[:m]; r = rtn_arr[:m]

    worst      = int(((s < 0)  & (r < 0)).sum())
    neutral    = int(((s >= 0) & (s < 8)  & (r >= 0)  & (r < 15)).sum())
    recovery   = int(((s >= 0) & (s < 8)  & (r >= 15) & (r < 30)).sum())
    hot        = int(((s >= 8) & (r >= 30)).sum())
    other      = max(0, m - (worst + neutral + recovery + hot))

    sco_strong = int((sco_arr >= 11).sum())
    sco_mid    = int(((sco_arr >= 8) & (sco_arr < 11)).sum())
    sco_weak   = int(((sco_arr >= 0) & (sco_arr < 8)).sum())
    sco_neg    = int((sco_arr < 0).sum())

    avg_sco = round(float(sco_arr.mean()), 2)
    avg_3m  = round(float(rtn_arr[~np.isnan(rtn_arr)].mean()), 2) if len(rtn_arr) > 0 else 0.0

    row = {
        'date':           target_date_str,
        'Worst':          worst,
        'Neutral':        neutral,
        'Recovery':       recovery,
        'HotVeryHot':     hot,
        'Other':          other,
        'total_universe': m,
        'avg_sco':        avg_sco,
        'avg_3m':         avg_3m,
        'QQQ_close':      None,  # 아래에서 채움
        'sco_strong':     sco_strong,
        'sco_mid':        sco_mid,
        'sco_weak':       sco_weak,
        'sco_neg':        sco_neg,
        'Worst_pct':      round(worst/m*100,2)      if m>0 else 0.0,
        'Neutral_pct':    round(neutral/m*100,2)    if m>0 else 0.0,
        'Recovery_pct':   round(recovery/m*100,2)   if m>0 else 0.0,
        'HotVeryHot_pct': round(hot/m*100,2)        if m>0 else 0.0,
        'Other_pct':      round(other/m*100,2)      if m>0 else 0.0,
    }
    return row


# ──────────────────────────────────────────────────────────
# QQQ 종가 채우기
# ──────────────────────────────────────────────────────────
def fill_qqq_close(rows, qqq_df):
    if qqq_df is None or qqq_df.empty:
        return rows
    for row in rows:
        dt = pd.Timestamp(row['date'])
        # 해당 날짜 또는 직전 거래일
        sub = qqq_df[qqq_df.index <= dt]
        if not sub.empty:
            row['QQQ_close'] = round(float(sub['close'].iloc[-1]), 2)
    return rows


# ──────────────────────────────────────────────────────────
# 거래일 목록 생성 (yfinance QQQ 기준)
# ──────────────────────────────────────────────────────────
def get_trading_days(start, end):
    df = yf.download('QQQ', start=start, end=end, auto_adjust=True, progress=False)
    return [d.strftime('%Y-%m-%d') for d in df.index]


# ──────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2024-01-01', help='시작일 YYYY-MM-DD')
    parser.add_argument('--end',   default=datetime.now().strftime('%Y-%m-%d'), help='종료일 YYYY-MM-DD')
    parser.add_argument('--skip-kr', action='store_true', help='한국 ETF 스킵')
    args = parser.parse_args()

    start = args.start
    end   = args.end
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 기존 CSV 로드 ──────────────────────────────────────
    if os.path.exists(OUT_TRACK_CSV):
        existing_df = pd.read_csv(OUT_TRACK_CSV, encoding='utf-8-sig')
        existing_dates = set(existing_df['date'].astype(str).tolist())
        print(f"기존 CSV: {len(existing_df)}행, {len(existing_dates)}개 날짜")
    else:
        existing_df    = pd.DataFrame()
        existing_dates = set()
        print("기존 CSV 없음 → 새로 생성")

    # ── 거래일 목록 ────────────────────────────────────────
    # 데이터 다운로드는 window 만큼 여유 있게
    dl_start = (datetime.strptime(start, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')
    dl_end   = (datetime.strptime(end, '%Y-%m-%d') + timedelta(days=3)).strftime('%Y-%m-%d')

    print(f"\n거래일 목록 조회: {start} ~ {end}")
    trading_days = get_trading_days(start, dl_end)
    trading_days = [d for d in trading_days if start <= d <= end]
    new_days     = [d for d in trading_days if d not in existing_dates]
    print(f"전체 거래일: {len(trading_days)}일 / 신규 처리 대상: {len(new_days)}일")

    if not new_days:
        print("추가할 날짜 없음. 종료.")
        return

    # ── OHLCV 다운로드 ─────────────────────────────────────
    print(f"\n미국 ETF OHLCV 다운로드 ({dl_start} ~ {dl_end})")
    us_ohlcv = download_us_ohlcv(ALL_US_TICKERS, dl_start, dl_end)

    all_ohlcv = dict(us_ohlcv)

    if not args.skip_kr:
        print("한국 ETF OHLCV 다운로드")
        kr_ohlcv = download_kr_ohlcv(KR_ETFS, dl_start, dl_end)
        all_ohlcv.update(kr_ohlcv)

    qqq_df = all_ohlcv.get('QQQ')
    print(f"총 {len(all_ohlcv)}개 티커 사용 가능\n")

    # ── 날짜별 계산 ────────────────────────────────────────
    new_rows = []
    for i, day in enumerate(new_days, 1):
        print(f"[{i:3d}/{len(new_days)}] {day} 계산 중...", end=' ')
        row = compute_regime_for_date(day, all_ohlcv)
        if row is None:
            print("데이터 부족 스킵")
            continue
        print(f"universe={row['total_universe']} avg_sco={row['avg_sco']} sco≥11={row['sco_strong']}")
        new_rows.append(row)

    if not new_rows:
        print("유효한 신규 행 없음.")
        return

    # QQQ 종가 채우기
    new_rows = fill_qqq_close(new_rows, qqq_df)

    # ── 기존 데이터와 병합 ────────────────────────────────
    new_df = pd.DataFrame(new_rows)

    # 컬럼 순서를 기존 CSV 에 맞춤
    col_order = [
        'date', 'Worst', 'Neutral', 'Recovery', 'HotVeryHot', 'Other',
        'total_universe', 'avg_sco', 'avg_3m', 'QQQ_close',
        'sco_strong', 'sco_mid', 'sco_weak', 'sco_neg',
        'Worst_pct', 'Neutral_pct', 'Recovery_pct', 'HotVeryHot_pct', 'Other_pct',
    ]
    for col in col_order:
        if col not in new_df.columns:
            new_df[col] = np.nan

    if not existing_df.empty:
        for col in col_order:
            if col not in existing_df.columns:
                existing_df[col] = np.nan
        merged = pd.concat([existing_df, new_df[col_order]], ignore_index=True)
    else:
        merged = new_df[col_order]

    merged['date'] = merged['date'].astype(str)
    merged = merged.drop_duplicates(subset=['date'], keep='last')
    merged = merged.sort_values('date').reset_index(drop=True)

    # ── 저장 ──────────────────────────────────────────────
    merged.to_csv(OUT_TRACK_CSV, index=False, encoding='utf-8-sig')
    print(f"\n✅ CSV 저장 완료: {OUT_TRACK_CSV}  (총 {len(merged)}행)")

    try:
        with open(OUT_TRACK_JSON, 'w', encoding='utf-8') as f:
            json.dump(merged.to_dict(orient='records'), f, ensure_ascii=False, indent=2)
        print(f"✅ JSON 저장 완료: {OUT_TRACK_JSON}")
    except Exception as e:
        print(f"⚠️ JSON 저장 실패: {e}")

    print("\n=== 결과 미리보기 (최신 5일) ===")
    print(merged.tail(5)[['date','avg_sco','sco_strong','sco_mid','sco_weak','sco_neg','total_universe']].to_string(index=False))


if __name__ == '__main__':
    main()
