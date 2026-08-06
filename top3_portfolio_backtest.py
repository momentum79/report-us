"""
top3_portfolio_backtest.py
──────────────────────────────────────────────────────────────────
Top3 ETF 포트폴리오 백테스팅 (투자비중 반영, 복리, 증분 실행)

[수정사항]
- invest_pct: 코스피/나스닥 추세를 날짜별로 직접 재계산 (coloryp 로직)
- MDD: 전체 기간 누적 기준 올바르게 계산
- 중복 저장 방지: 같은 날짜 중복 기록 안 함
- history.csv 있으면 1년치 재계산 스킵 → 증분만 실행
- 종목별 내부비중: history 뽑을 땐 TOP3_ALLOC_WEIGHTS 기본값 유지

[투자 로직]
- 매일 Top3 선정 (Final_score = 85×Norm_sco + 15×Norm_rtn, SCO>=11 우선)
- 코스피/나스닥 coloryp 추세 → multiplier → invest_pct 결정
- 각 종목 투자금 = 총자산 × internal_weight[i] × mult(한국/미국)
- 당일 종가 매수, 다음날 종가 재평가 후 교체
- 수수료/슬리피지 없음, 복리
"""

import os, sys, io, warnings, json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    from pykrx import stock
except ImportError:
    print("pykrx 미설치. pip install pykrx")
    sys.exit(1)

# ══════════════════════════════════════════
# 설정
# ══════════════════════════════════════════
BASE_DIR        = Path("D:/py/report-us")
HISTORY_CSV     = BASE_DIR / "top3_bt_history.csv"
LOG_CSV         = BASE_DIR / "top3_bt_log.csv"

INITIAL_CAPITAL     = 100_000_000
BACKTEST_DAYS       = 365
TOP3_ALLOC_WEIGHTS  = [0.40, 0.35, 0.25]   # 내부비중 기본값

TREND_MULTIPLIER = {
    "LIME":   1.0,
    "GREEN":  0.8,
    "-":      0.4,
    "PURPLE": 0.1,
    "RED":    0.0,
}

K_TICKERS = {
    '091160','091180','305720','117460','244580','091170',
    '102970','117680','117700','139230','228790','495050',
    '069500','229200','487230','449450','475050','371160',
    '455850','377990','411060','478150','453810','446770',
    '434730','469070',
}

TICKERS = {
    '091160':'반도체', '091180':'자동차', '305720':'이차전',
    '117460':'에너지', '244580':'바이오', '091170':'은행주',
    '102970':'증권주', '117680':'철강주', '117700':'건설주',
    '139230':'조선주', '228790':'화장품', '495050':'밸류업',
    '069500':'코스피', '229200':'코스닥', '487230':'전력인',
    '449450':'방산주', '475050':'케이피', '371160':'항셈테',
    '455850':'반소부', '0051G0':'에셈알', '0038A0':'미로봇',
    '0048K0':'중로봇', '0023A0':'양자컴', '195930':'유로스',
    '377990':'신재생', '411060':'금현물', '478150':'우주방',
    '453810':'인디아', '446770':'톱반도', '434730':'원자력',
    '469070':'ai로봇', '449180':'에센피', '449190':'나스닥',
    '241180':'니케이', '147970':'티모멘', '325020':'케모멘',
}

KOSPI_TICKER  = '069500'
NASDAQ_TICKER = '449190'


# ══════════════════════════════════════════
# SCO 계산
# ══════════════════════════════════════════
def sma(s, n):
    return s.rolling(n).mean()

def rsi_wilder(s, n=14):
    delta = s.diff()
    u = delta.clip(lower=0)
    d = (-delta).clip(lower=0)
    rma_u = u.ewm(alpha=1/n, adjust=False).mean()
    rma_d = d.ewm(alpha=1/n, adjust=False).mean()
    rs = rma_u / rma_d
    return 100 - (100 / (1 + rs))

def calc_sco_series(df_raw):
    df = df_raw.copy()
    df.columns = [c.lower() for c in df.columns]
    rmap = {}
    for c in df.columns:
        if '종가' in c or c == 'close':      rmap[c] = 'close'
        elif '고가' in c or c == 'high':     rmap[c] = 'high'
        elif '저가' in c or c == 'low':      rmap[c] = 'low'
        elif '거래량' in c or c == 'volume': rmap[c] = 'volume'
    df = df.rename(columns=rmap)
    if 'close' not in df.columns:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    close = df['close'].astype(float)
    M0=sma(close,5);  M1=sma(close,10); M2=sma(close,20)
    M3=sma(close,60); M4=sma(close,120)

    rad = 180/np.pi
    def ang(m): return np.sin(np.arctan((m-m.shift(1))/m.shift(1)*100))*rad
    m0ang=ang(M0); m1ang=ang(M1); m2ang=ang(M2)
    m3ang=ang(M3); m4ang=ang(M4)

    def ms(m):
        return pd.Series(np.where(m.isna()|m.shift(1).isna(), np.nan,
                                  np.where(m>=m.shift(1),1,-1)), index=df.index)
    m0s=ms(M0); m1s=ms(M1); m2s=ms(M2)
    m3s=pd.Series(np.where(M3.isna()|M3.shift(1).isna(), np.nan,
                            np.where((M3>=M3.shift(1))|(m3ang>-2),1,-1)), index=df.index)
    m4s=pd.Series(np.where(M4.isna()|M4.shift(1).isna(), np.nan,
                            np.where((M4>=M4.shift(1))|(m4ang>-1),1,-1)), index=df.index)
    m3sm=pd.Series(np.where(M3.isna()|M3.shift(1).isna(), np.nan,
                             np.where((M3<=M3.shift(1))|(m3ang<2),-1,1)), index=df.index)

    def cv(m):
        return pd.Series(np.where(m.isna()|close.isna(), np.nan,
                                  np.where(close>=m,1,-1)), index=df.index)
    s1=cv(M0); s2=cv(M1); s3=cv(M2); s4=cv(M3); s5=cv(M4)

    jung=pd.Series(0,index=df.index)
    c2=(close>=M0)&(M0>=M1)&(M1>=M2)&(M2>=M3)&(M3>=M4)
    c1=(close>=M0)&(M0>=M1)&(M1>=M2)&(M2>=M3)
    jung[c2]=2; jung[~c2&c1]=1

    HLd99=pd.Series(0,index=df.index)
    cc2=(m1s==1)&(m2s==1)&(m3s==1); cc1=(m1s==1)&(m2s==1)
    cm2=(m0s==-1)&(m1s==-1)&(m2s==-1)&(m3sm==-1); cm1=(m1s==-1)&(m2s==-1)
    HLd99[cc2]=2; HLd99[~cc2&cc1]=1; HLd99[cm2]=-2; HLd99[cm1&~cm2]=-1

    rsi1  = rsi_wilder(close,14)
    rsi10 = sma(rsi1,10).rolling(3).mean()
    rsisco=pd.Series(np.where(rsi10.isna(),np.nan,np.where(rsi10>=50,1,0)),index=df.index)

    new_high=pd.Series(0,index=df.index)
    for i in range(len(df)):
        if i<2: continue
        if close.iloc[max(0,i-2):i+1].max() >= close.iloc[max(0,i-125):i+1].max():
            new_high.iloc[i]=1

    sco99=(s1+s2+s3+s4+s5+m0s+m1s+m2s+m3s+m4s+jung+HLd99+rsisco+new_high)
    return sco99.rolling(4).mean(), close


def normalize_0_1(series):
    mn, mx = series.min(), series.max()
    if mx-mn == 0:
        return pd.Series([0.5]*len(series), index=series.index)
    return (series-mn)/(mx-mn)


# ══════════════════════════════════════════
# 추세 계산 (coloryp - jasantop4_final.py 동일)
# ══════════════════════════════════════════
def calc_trend_series(df_raw):
    """
    코스피/나스닥 종가 DataFrame → 날짜별 추세(LIME/GREEN/PURPLE/RED/-) Series 반환
    """
    df = df_raw.copy()
    df.columns = [c.lower() for c in df.columns]
    for c in list(df.columns):
        if '종가' in c: df = df.rename(columns={c:'close'})
    if 'close' not in df.columns:
        return pd.Series(dtype=str)

    close = df['close'].astype(float)
    M0=sma(close,5);  M1=sma(close,10); M2=sma(close,20)
    M3=sma(close,60); M4=sma(close,120)
    aa=sma(close,60); bb=sma(close,200)

    rad=180/np.pi
    def ang(m): return np.sin(np.arctan((m-m.shift(1))/m.shift(1)*100))*rad
    m0ang=ang(M0); m1ang=ang(M1); m2ang=ang(M2)
    m3ang=ang(M3); m4ang=ang(M4)

    def ms(m):
        return pd.Series(np.where(m.isna()|m.shift(1).isna(),np.nan,
                                  np.where(m>=m.shift(1),1,-1)),index=df.index)
    m0s=ms(M0); m1s=ms(M1); m2s=ms(M2)
    m3s=pd.Series(np.where(M3.isna()|M3.shift(1).isna(),np.nan,
                            np.where((M3>=M3.shift(1))|(m3ang>-2),1,-1)),index=df.index)
    m3sm=pd.Series(np.where(M3.isna()|M3.shift(1).isna(),np.nan,
                             np.where((M3<=M3.shift(1))|(m3ang<2),-1,1)),index=df.index)

    HLd99=pd.Series(0,index=df.index)
    cc2=(m1s==1)&(m2s==1)&(m3s==1); cc1=(m1s==1)&(m2s==1)
    cm2=(m0s==-1)&(m1s==-1)&(m2s==-1)&(m3sm==-1); cm1=(m1s==-1)&(m2s==-1)
    HLd99[cc2]=2; HLd99[~cc2&cc1]=1; HLd99[cm2]=-2; HLd99[cm1&~cm2]=-1
    HLv99=HLd99.replace(0,np.nan).ffill().fillna(0)

    # stoch/rsi 기반 HLv71
    rsi1=rsi_wilder(close,14); rsi14=sma(rsi1,14)
    ll20=close.rolling(20).min(); hh20=close.rolling(20).max()
    k3=sma((close-ll20)/(hh20-ll20+1e-9)*100,10)
    ll10=close.rolling(10).min(); hh10=close.rolling(10).max()
    k2=sma((close-ll10)/(hh10-ll10+1e-9)*100,5)
    HLd71=pd.Series(0,index=df.index)
    HLd71[(k3>k3.shift(1))&(k2>k2.shift(1))&(rsi14>=rsi14.shift(1))]=1
    HLd71[(k3<k3.shift(1))&(k2<k2.shift(1))&(rsi14<rsi14.shift(1))]=-1
    HLv71=HLd71.replace(0,np.nan).ffill().fillna(0)

    HLd7=pd.Series(0,index=df.index)
    HLd7[(aa>=aa.shift(5))&(bb>=bb.shift(10))]=1
    HLd7[(aa<aa.shift(5))&(bb<bb.shift(10))]=-1
    HLv7=HLd7.replace(0,np.nan).ffill().fillna(0)

    # 날짜별 추세 판정
    trend=pd.Series('-',index=df.index)
    for idx in df.index:
        try:
            m0a=float(m0ang.loc[idx]); m1a=float(m1ang.loc[idx])
            m2a=float(m2ang.loc[idx]); m3a=float(m3ang.loc[idx]); m4a=float(m4ang.loc[idx])
        except: continue
        if any(np.isnan([m0a,m1a,m2a,m3a,m4a])): continue
        at5 = all(x<=0 for x in [m0a,m1a,m2a,m3a,m4a])
        at4 = all(x<=0 for x in [m0a,m1a,m2a,m3a])
        hv9=float(HLv99.loc[idx]); hv7=float(HLv7.loc[idx]); hv71=float(HLv71.loc[idx])
        if   hv9>=1 and hv7==1  and hv71==1 and close.loc[idx]>=M1.loc[idx]:  trend.loc[idx]='LIME'
        elif hv9>=1 and hv71==1:               trend.loc[idx]='GREEN'
        elif (hv9<=-1 and hv7==-1 and hv71==-1) or at5: trend.loc[idx]='RED'
        elif (hv9<=-1 and hv71==-1) or at4:   trend.loc[idx]='PURPLE'

    return trend


# ══════════════════════════════════════════
# 투자비중 계산
# ══════════════════════════════════════════
def get_bench_multiplier(trend):
    return TREND_MULTIPLIER.get(str(trend).upper(), 0.4)

def calc_alloc(top3_tickers, kospi_trend, nasdaq_trend, total_assets):
    k_mult  = get_bench_multiplier(kospi_trend)
    us_mult = get_bench_multiplier(nasdaq_trend)
    weights = TOP3_ALLOC_WEIGHTS[:len(top3_tickers)]
    alloc={}; total_invested=0
    for i,ticker in enumerate(top3_tickers):
        mult = k_mult if ticker in K_TICKERS else us_mult
        amt  = int(total_assets * weights[i] * mult)
        alloc[ticker]=amt; total_invested+=amt
    invest_pct_eff = total_invested/total_assets if total_assets>0 else 0
    return alloc, invest_pct_eff, weights


# ══════════════════════════════════════════
# 데이터 수집
# ══════════════════════════════════════════
def fetch_all_data(start_str, end_str):
    data={}; total=len(TICKERS)
    for i,ticker in enumerate(TICKERS):
        name=TICKERS.get(ticker,ticker)
        print(f"  [{i+1:2d}/{total}] {ticker} ({name}) ...", end=' ', flush=True)
        try:
            df=stock.get_market_ohlcv_by_date(start_str, end_str, ticker)
            if df is None or df.empty: print("없음"); continue
            data[ticker]=df; print(f"OK ({len(df)}일)")
        except Exception as e:
            print(f"ERR {e}")
    return data


# ══════════════════════════════════════════
# 날짜별 Top3 + 추세 선정
# ══════════════════════════════════════════
def build_daily_top3(raw_data, all_dates):
    """
    날짜별 SCO → Top3 선정 + 코스피/나스닥 추세 계산
    반환: {date: {top3, names, sco_avg, closes, kospi_trend, nasdaq_trend}}
    """
    print("  SCO 계산 중...")
    sco_map={}; close_map={}
    for ticker,df in raw_data.items():
        sco,close=calc_sco_series(df)
        sco_map[ticker]=sco; close_map[ticker]=close

    # ── 코스피/나스닥 추세 시리즈 미리 계산 ──
    print("  코스피/나스닥 추세 계산 중...")
    kospi_trend_s  = calc_trend_series(raw_data[KOSPI_TICKER])  if KOSPI_TICKER  in raw_data else pd.Series(dtype=str)
    nasdaq_trend_s = calc_trend_series(raw_data[NASDAQ_TICKER]) if NASDAQ_TICKER in raw_data else pd.Series(dtype=str)

    daily_top3={}
    for date in all_dates:
        ts=pd.Timestamp(date)
        day_data=[]
        for ticker in TICKERS:
            if ticker not in sco_map: continue
            sco_s=sco_map[ticker]
            if ts not in sco_s.index: continue
            sco_val=sco_s.loc[ts]
            if pd.isna(sco_val): continue
            cl=close_map[ticker]; cl_u=cl[cl.index<=ts]
            rtn=(cl_u.iloc[-1]/cl_u.iloc[-61]-1)*100 if len(cl_u)>=61 else np.nan
            day_data.append({'ticker':ticker,'name':TICKERS[ticker],'sco':sco_val,'rtn':rtn})

        if len(day_data)<3: continue

        df_day=pd.DataFrame(day_data)
        df_day['Norm_sco']=normalize_0_1(df_day['sco'].fillna(df_day['sco'].min()))
        rtn_fill=df_day['rtn'].fillna(df_day['rtn'].min() if df_day['rtn'].notna().any() else 0)
        df_day['Norm_rtn']=normalize_0_1(rtn_fill)
        df_day['Final_score']=85*df_day['Norm_sco']+15*df_day['Norm_rtn']

        cands=df_day[df_day['sco']>=11].nlargest(3,'Final_score')
        if len(cands)==0: cands=df_day.nlargest(3,'Final_score')

        top3_t=cands['ticker'].tolist(); top3_n=cands['name'].tolist()
        sco_avg=float(cands['sco'].mean())

        closes={}
        for t in top3_t:
            cl=close_map.get(t)
            if cl is not None and ts in cl.index:
                closes[t]=float(cl.loc[ts])

        # 날짜별 추세 조회
        kt = kospi_trend_s.loc[ts]  if ts in kospi_trend_s.index  else '-'
        nt = nasdaq_trend_s.loc[ts] if ts in nasdaq_trend_s.index else '-'

        daily_top3[ts]={
            'top3':top3_t,'names':top3_n,'sco_avg':sco_avg,
            'closes':closes,'kospi_trend':kt,'nasdaq_trend':nt,
        }

    return daily_top3, close_map


# ══════════════════════════════════════════
# 포트폴리오 시뮬레이션
# ══════════════════════════════════════════
def simulate_portfolio(daily_top3_map, sorted_dates, start_capital=None):
    capital    = float(start_capital if start_capital is not None else INITIAL_CAPITAL)
    holdings   = {}   # {ticker: {'shares':float,'avg_price':float}} + '__cash__':float
    peak_value = capital
    rows       = []

    for i,date in enumerate(sorted_dates):
        info=daily_top3_map.get(date)
        if info is None: continue

        today_top3  = info['top3']
        today_names = info['names']
        today_close = info['closes']
        kospi_trend = info['kospi_trend']
        nasdaq_trend= info['nasdaq_trend']

        # ── 1. 전날 보유종목 당일 종가로 총자산 재평가 ──
        if i==0 or not holdings:
            total_assets=capital
        else:
            cash=holdings.get('__cash__',0)
            invested_value=0
            for ticker,pos in holdings.items():
                if ticker=='__cash__': continue
                cur_price=today_close.get(ticker, pos.get('avg_price',0))
                invested_value += pos['shares']*cur_price
            total_assets=cash+invested_value

        prev_total = rows[-1]['portfolio_total'] if rows else capital

        # ── 2. 투자비중 결정 + 배분 ──
        alloc,invest_pct_eff,int_weights=calc_alloc(
            today_top3, kospi_trend, nasdaq_trend, total_assets)

        # ── 3. 전액 매도 → Top3 재매수 ──
        new_cash=total_assets-sum(alloc.values())
        new_holdings={'__cash__': new_cash}
        for j,ticker in enumerate(today_top3):
            price=today_close.get(ticker)
            if price and price>0 and ticker in alloc:
                new_holdings[ticker]={
                    'shares':   alloc[ticker]/price,
                    'avg_price':price,
                }
        holdings=new_holdings

        # ── 4. 포트폴리오 가치 ──
        portfolio_total=sum(alloc.values())+new_cash

        # ── 성과 계산 ──
        daily_rtn =(portfolio_total/prev_total-1)*100 if prev_total>0 else 0.0
        cum_rtn   =(portfolio_total/INITIAL_CAPITAL-1)*100

        # MDD: 전체 peak 기준 누적 계산 (리셋 없음)
        if portfolio_total>peak_value:
            peak_value=portfolio_total
        mdd=(portfolio_total/peak_value-1)*100 if peak_value>0 else 0.0

        w=int_weights
        row={
            '날짜':              date.strftime("%Y-%m-%d"),
            'invest_pct(%)':     round(invest_pct_eff*100,2),
            'kospi_trend':       kospi_trend,
            'nasdaq_trend':      nasdaq_trend,
            'top1_ticker':       today_top3[0] if len(today_top3)>0 else '',
            'top1_name':         today_names[0] if len(today_names)>0 else '',
            'top1_weight(%)':    round(w[0]*100,2) if len(w)>0 else 0,
            'top1_amount':       alloc.get(today_top3[0],0) if today_top3 else 0,
            'top2_ticker':       today_top3[1] if len(today_top3)>1 else '',
            'top2_name':         today_names[1] if len(today_names)>1 else '',
            'top2_weight(%)':    round(w[1]*100,2) if len(w)>1 else 0,
            'top2_amount':       alloc.get(today_top3[1],0) if len(today_top3)>1 else 0,
            'top3_ticker':       today_top3[2] if len(today_top3)>2 else '',
            'top3_name':         today_names[2] if len(today_names)>2 else '',
            'top3_weight(%)':    round(w[2]*100,2) if len(w)>2 else 0,
            'top3_amount':       alloc.get(today_top3[2],0) if len(today_top3)>2 else 0,
            'invested_total':    int(sum(alloc.values())),
            'cash':              int(new_cash),
            'portfolio_total':   int(portfolio_total),
            'daily_rtn(%)':      round(daily_rtn,4),
            'cum_rtn(%)':        round(cum_rtn,4),
            'mdd(%)':            round(mdd,4),
            'peak_value':        int(peak_value),
            'top3_sco_avg':      round(info['sco_avg'],2),
        }
        rows.append(row)

        sign='+' if daily_rtn>=0 else ''
        n1=today_names[0] if today_names else '?'
        n2=today_names[1] if len(today_names)>1 else '?'
        n3=today_names[2] if len(today_names)>2 else '?'
        print(f"  {row['날짜']}  {n1}/{n2}/{n3}  "
              f"투자{invest_pct_eff*100:.1f}%({kospi_trend}/{nasdaq_trend})  "
              f"{sign}{daily_rtn:.2f}%  누적{cum_rtn:.1f}%  MDD{mdd:.2f}%")

        capital=portfolio_total

    return rows


# ══════════════════════════════════════════
# MDD 재계산 (전체 이력 기준, 리셋 없음)
# ══════════════════════════════════════════
def recalc_mdd(df):
    vals  = df['portfolio_total'].values.astype(float)
    peaks = np.maximum.accumulate(vals)
    df=df.copy()
    df['mdd(%)']     = np.round((vals/peaks-1)*100, 4)
    df['peak_value'] = peaks.astype(int)
    return df


# ══════════════════════════════════════════
# CSV 로드/저장
# ══════════════════════════════════════════
def load_existing_log():
    dfs=[]
    for path in [HISTORY_CSV, LOG_CSV]:
        if path.exists():
            try:
                df=pd.read_csv(path, encoding='utf-8-sig',
                               dtype={'top1_ticker':str,'top2_ticker':str,'top3_ticker':str})
                df['날짜']=pd.to_datetime(df['날짜'])
                dfs.append(df)
            except Exception as e:
                print(f"  ⚠️ {path.name} 로드 실패: {e}")
    if dfs:
        combined=pd.concat(dfs).drop_duplicates('날짜').sort_values('날짜').reset_index(drop=True)
        return combined
    return pd.DataFrame()


# ══════════════════════════════════════════
# 메인
# ══════════════════════════════════════════
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rebuild', action='store_true',
                        help='history.csv 있어도 1년치 강제 재계산 (추세 재계산 포함)')
    args = parser.parse_args()

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    print("="*65)
    print("Top3 ETF 포트폴리오 백테스팅 (투자비중 반영, 복리)")
    print("="*65)

    existing = load_existing_log()

    if existing.empty or args.rebuild:
        # ── 최초 실행: 1년치 전체 계산 ──
        if args.rebuild:
            print("\n[강제 재계산] 1년치 전체 재계산 시작... (추세 포함)")
        else:
            print("\n[최초 실행] 1년치 데이터 계산 시작...")
        end_dt   = datetime.today()
        start_dt = end_dt-timedelta(days=BACKTEST_DAYS+300)
        end_str  = end_dt.strftime("%Y%m%d")
        start_str= start_dt.strftime("%Y%m%d")

        print(f"\n[1단계] 데이터 수집 ({start_str} ~ {end_str})...")
        raw_data=fetch_all_data(start_str, end_str)
        if not raw_data: print("데이터 없음. 종료"); return

        bt_start  = end_dt-timedelta(days=BACKTEST_DAYS)
        all_dates = sorted([d for d in raw_data.get(KOSPI_TICKER,pd.DataFrame()).index
                            if pd.Timestamp(d)>=pd.Timestamp(bt_start)])

        print(f"\n[2단계] Top3 선정 + 추세 계산 ({len(all_dates)}거래일)...")
        daily_top3,_=build_daily_top3(raw_data, all_dates)
        sorted_dates=sorted(daily_top3.keys())

        print(f"\n[3단계] 포트폴리오 시뮬레이션 ({len(sorted_dates)}일)...")
        rows=simulate_portfolio(daily_top3, sorted_dates, start_capital=INITIAL_CAPITAL)
        if not rows: print("결과 없음. 종료"); return

        df_result=pd.DataFrame(rows)
        df_result=recalc_mdd(df_result)

        print(f"\n[4단계] CSV 저장 → {HISTORY_CSV}")
        df_result.to_csv(HISTORY_CSV, index=False, encoding='utf-8-sig')
        print(f"  ✅ {len(df_result)}일 저장 완료")

    else:
        # ── 증분 실행: 마지막 날짜 이후만 계산 ──
        last_date   = existing['날짜'].max()
        last_capital= int(existing.loc[existing['날짜']==last_date,'portfolio_total'].iloc[0])
        last_peak   = int(existing['peak_value'].max())

        print(f"\n기존 이력: {len(existing)}일  마지막: {last_date.strftime('%Y-%m-%d')}")
        print(f"마지막 자산: {last_capital:,}원  누적 peak: {last_peak:,}원")

        today=datetime.today()
        if last_date.date()>=today.date():
            print("\n✅ 이미 최신 상태입니다.")
            _print_summary(existing); return

        fetch_start=(last_date-timedelta(days=200)).strftime("%Y%m%d")
        today_str  =today.strftime("%Y%m%d")
        print(f"\n[1단계] 증분 데이터 수집 ({fetch_start} ~ {today_str})...")
        raw_data=fetch_all_data(fetch_start, today_str)
        if not raw_data: print("데이터 없음. 종료"); return

        kospi_df  =raw_data.get(KOSPI_TICKER, pd.DataFrame())
        new_dates =[d for d in sorted(kospi_df.index) if pd.Timestamp(d)>last_date]

        if not new_dates:
            print("\n✅ 새로운 거래일 없음.")
            _print_summary(existing); return

        print(f"\n[2단계] 신규 {len(new_dates)}일 Top3 선정 + 추세 계산...")
        daily_top3,_=build_daily_top3(raw_data, new_dates)
        sorted_dates=sorted(daily_top3.keys())

        if not sorted_dates:
            print("신규 데이터 없음.")
            _print_summary(existing); return

        print(f"\n[3단계] 포트폴리오 시뮬레이션 ({len(sorted_dates)}일)...")
        rows=simulate_portfolio(daily_top3, sorted_dates, start_capital=last_capital)
        if not rows: print("신규 결과 없음."); return

        # 중복 날짜 제거 후 전체 MDD 재계산
        df_new =pd.DataFrame(rows)
        df_new['날짜']=pd.to_datetime(df_new['날짜'])
        df_all =pd.concat([existing,df_new]).drop_duplicates('날짜').sort_values('날짜').reset_index(drop=True)
        df_all =recalc_mdd(df_all)

        # 신규분만 LOG_CSV에 저장 (중복 없이)
        new_rows=df_all[df_all['날짜']>last_date]
        if not new_rows.empty:
            mode  ='a' if LOG_CSV.exists() else 'w'
            header=not LOG_CSV.exists()
            new_rows.to_csv(LOG_CSV, mode=mode, index=False, encoding='utf-8-sig', header=header)
            print(f"\n✅ {len(new_rows)}일 추가 → {LOG_CSV}")

        # HISTORY_CSV도 MDD 업데이트
        df_all[df_all['날짜']<=last_date].to_csv(HISTORY_CSV, index=False, encoding='utf-8-sig')
        existing=df_all
        print(f"✅ 전체 MDD 재계산 완료 ({len(df_all)}일)")

    _print_summary(load_existing_log())


def _print_summary(df):
    if df.empty: print("데이터 없음."); return
    df=df.sort_values('날짜')
    last=df.iloc[-1]; first=df.iloc[0]
    final_cap =int(last['portfolio_total'])
    cum_rtn   =float(last['cum_rtn(%)'])
    mdd       =float(df['mdd(%)'].min())
    avg_invest=float(df['invest_pct(%)'].mean())
    n_days    =(pd.to_datetime(last['날짜'])-pd.to_datetime(first['날짜'])).days
    cagr      =((final_cap/INITIAL_CAPITAL)**(365/max(n_days,1))-1)*100 if n_days>0 else 0
    pos_days  =int((df['daily_rtn(%)']>0).sum())
    neg_days  =int((df['daily_rtn(%)']<0).sum())
    win_rate  =pos_days/len(df)*100 if len(df)>0 else 0

    print("\n"+"="*65)
    print("📊 포트폴리오 백테스팅 최종 요약")
    print("="*65)
    print(f"  기간        : {pd.to_datetime(first['날짜']).strftime('%Y-%m-%d')} ~ {pd.to_datetime(last['날짜']).strftime('%Y-%m-%d')} ({len(df)}거래일)")
    print(f"  초기자본    : {INITIAL_CAPITAL:>15,}원")
    print(f"  최종자산    : {final_cap:>15,}원")
    print(f"  누적수익률  : {cum_rtn:>+.2f}%")
    print(f"  CAGR        : {cagr:>+.2f}%")
    print(f"  MDD         : {mdd:.2f}%")
    print(f"  평균투자비중: {avg_invest:.1f}%")
    print(f"  승률        : {win_rate:.1f}% ({pos_days}↑ / {neg_days}↓)")
    print(f"\n  최근 5일:")
    cols=['날짜','top1_name','top2_name','top3_name',
          'kospi_trend','nasdaq_trend','invest_pct(%)','daily_rtn(%)','cum_rtn(%)','mdd(%)']
    print(df[cols].tail(5).to_string(index=False))
    print("="*65)
    print(f"\n✅ 저장 위치:")
    print(f"   초기이력: {HISTORY_CSV}")
    print(f"   추가로그: {LOG_CSV}")


if __name__=="__main__":
    main()
