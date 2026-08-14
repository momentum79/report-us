# chart_popup_v4.py ── [US 일봉/주봉] 내장형 인터랙티브 차트 팝업 (V4)
#
# 목적: 미국 주식 게시판의 호버 팝업을 네이버 PNG → 인터랙티브(lightweight-charts)로 교체.
#   - 패널 2개: 일봉 | 주봉  (V3는 5분+일, V4는 일+주)
#   - 크기/비율: 요약-단타 게시판(make_danta_chart_display.py)과 동일 (캔들 300px · RSI 100px)
#   - 추세배경:
#       · 일봉 = coloryp LIME/GREEN/RED/PURPLE (캐시 ~549봉 → warmup 221봉 충분)
#       · 주봉 = 매집분산 end4 (0majib_col.py): black=매집전환 / orange=분산 / lime=매집
#              coloryp(warmup 220주≈4.3년) 대신 매집분산 사용 → warmup M4=SMA120=120주≈2.3년.
#              M4가 유효한 "최근" 봉에만 색 부착(그 앞은 warmup이라 미부착 = 정확한 최근색만).
#   - 데이터:
#       · 일봉 = D:\py\cache\us_adj_ohlcv.parquet 오프라인 read (네트워크 0)
#       · 주봉 = ~3년 일봉을 별도 캐시(us_wk_warmup.parquet)에 받아 W-FRI 리샘플 → 매집분산 계산.
#              집=yfinance수정주가 / 회사=네이버shim. 머신별 로컬(동기화 X). 최초 1회만 네트워크.
#
# 실행:  python chart_popup_v4.py   →  report-us/chart_v4_test.html  (NVDA 자동표시)
import os, sys, json, time, webbrowser, importlib
import importlib.util   # find_spec (셔틀 판정) — importlib 만 import 하면 util 이 없을 수 있다
import datetime as _dt

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coloryp_core import check_coloryp_logic
_majib = importlib.import_module("0majib_col")   # 파일명이 숫자로 시작 → import_module

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PARQUET     = r"D:\py\cache\us_adj_ohlcv.parquet"
# KR 일봉 단일 원천: stock_kr_ohlcv_v3.parquet (full bat 매 실행마다 갱신, NXT=_AL통합/KRX=pykrx 구분).
# ETF 는 v3 스캔 유니버스에 없어 etf_kr_ohlcv.parquet 로 보완. 겹치는 날짜는 _load_store 에서 최신 우선 dedup.
KR_PARQUETS = [r"D:\py\report-us\stock_kr_ohlcv_v3.parquet", r"D:\py\cache\etf_kr_ohlcv.parquet"]
KR_WK_PARQUET = r"D:\py\cache\kr_wk_warmup.parquet"
WK_PARQUET  = r"D:\py\cache\us_wk_warmup.parquet"   # 주봉 warmup용 ~3년 일봉 (머신별 로컬)
WK_YEARS    = 3          # 매집분산 M4=SMA120(주) warmup 확보용. 최근 ~8개월 주봉색 정확
DISPLAY_WEEKS = 120      # 주봉 embed 개수(~2.3년). 색은 그중 M4 유효한 최근분만
COLS        = ["Open", "High", "Low", "Close", "Volume"]

# ───────── 데이터층: parquet 오프라인 read (새 다운로드 없음) ─────────
_STORE_BY_MARKET = {}
def _normalize_ohlcv_columns(df):
    rename = {
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
        "시가": "Open", "고가": "High", "저가": "Low", "종가": "Close", "거래량": "Volume",
    }
    return df.rename(columns={k: v for k, v in rename.items() if k in df.columns})


def _load_store(market="US"):
    market = str(market or "US").upper()
    if market in _STORE_BY_MARKET:
        return _STORE_BY_MARKET[market]
    paths = [PARQUET] if market == "US" else KR_PARQUETS
    store = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        df = _normalize_ohlcv_columns(pd.read_parquet(path))
        if "date" not in df.columns or "ticker" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["date"])
        for t, g in df.groupby("ticker"):
            tk = str(t).strip().upper().zfill(6) if market == "KR" else str(t).strip().upper()
            if any(c not in g.columns for c in COLS):
                continue
            gg = g.set_index("date")[COLS]
            if tk in store:
                gg = pd.concat([store[tk], gg])
            # 같은 날짜가 여러 parquet 에 있으면 뒤(더 최신 소스)를 유지
            gg = gg[~gg.index.duplicated(keep="last")].sort_index()
            store[tk] = gg
    _STORE_BY_MARKET[market] = store
    return store


def _pick_fresher(a, b):
    """두 일봉 DataFrame 중 마지막 날짜가 더 최신인 것을 선택(빈 것은 제외)."""
    ae = a is None or a.empty
    be = b is None or b.empty
    if ae and be:
        return None
    if ae:
        return b
    if be:
        return a
    return a if a.index.max() >= b.index.max() else b


def daily_rows(ticker, market="US"):
    """캐시에서 일봉 → [[YYYY-MM-DD,o,h,l,c,v], ...] (오름차순).
    KR은 메인 parquet이 stale/누락일 수 있어, 생성시 pykrx로 보강된
    kr_wk_warmup 스토어(더 최신)로 폴백/대체한다."""
    market = str(market or "US").upper()
    key = str(ticker).strip().upper().zfill(6) if market == "KR" else str(ticker).strip().upper()
    df = _load_store(market).get(key)
    if market == "KR":
        df = _pick_fresher(df, _load_kr_wk_store().get(key))
    else:
        df = _pick_fresher(df, _load_wk_store().get(key))
    if df is None or df.empty:
        return []
    out = []
    for idx, r in df.iterrows():
        out.append([idx.strftime("%Y-%m-%d"),
                    round(float(r.Open), 4), round(float(r.High), 4),
                    round(float(r.Low), 4),  round(float(r.Close), 4),
                    int(r.Volume or 0)])
    return out


def weekly_rows(daily):
    """일봉 → 주봉(W-FRI) 리샘플. 추가 수집 없음."""
    if not daily:
        return []
    df = pd.DataFrame(daily, columns=["date", "o", "h", "l", "c", "v"])
    df["date"] = pd.to_datetime(df["date"])
    w = (df.resample("W-FRI", on="date")
           .agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"})
           .dropna(subset=["c"]))
    out = []
    for idx, r in w.iterrows():
        out.append([idx.strftime("%Y-%m-%d"),
                    round(float(r.o), 4), round(float(r.h), 4),
                    round(float(r.l), 4), round(float(r.c), 4), int(r.v)])
    return out


# ───────── 주봉 warmup: ~3년 일봉 별도 캐시 (매집분산 M4=SMA120 warmup용) ─────────
_WK_STORE = None
def _load_wk_store():
    global _WK_STORE
    if _WK_STORE is not None:
        return _WK_STORE
    _WK_STORE = {}
    if os.path.exists(WK_PARQUET):
        try:
            df = pd.read_parquet(WK_PARQUET)
            df["date"] = pd.to_datetime(df["date"])
            for t, g in df.groupby("ticker"):
                _WK_STORE[str(t).upper()] = g.set_index("date")[COLS].sort_index()
        except Exception as e:
            print(f"  [wk warmup] 캐시 read 실패: {e}")
    return _WK_STORE


def _save_wk_store(store):
    try:
        frames = []
        for t, g in store.items():
            gg = g.copy()
            gg.index.name = "date"
            gg = gg.reset_index()
            gg.insert(1, "ticker", t)
            frames.append(gg[["date", "ticker"] + COLS])
        if frames:
            os.makedirs(os.path.dirname(WK_PARQUET), exist_ok=True)
            pd.concat(frames, ignore_index=True).to_parquet(WK_PARQUET, index=False)
    except Exception as e:
        print(f"  [wk warmup] 캐시 저장 실패: {e}")


def _is_naver_shim(yf):
    """회사 셔틀(company_shim/yfinance.py)인지 판정.
    shim 은 네이버 해외차트 API = 원주가라 auto_adjust 인자를 무시한다(shim 자체 주석).
    버전 문자열과 모듈 경로를 둘 다 본다 — 하나가 바뀌어도 오탐/미탐이 안 나게."""
    ver = str(getattr(yf, "__version__", "")).lower()
    path = str(getattr(yf, "__file__", "") or "").lower().replace("/", "\\")
    return ("naver" in ver) or ("shim" in ver) or ("company_shim" in path)


def _shim_on_path():
    """yfinance 를 import 하지 않고 셔틀 여부만 확인(import 비용 회피용).
    need 가 비면 지금처럼 yfinance import 자체를 건너뛰어야 해서 미리 알아야 한다."""
    try:
        spec = importlib.util.find_spec("yfinance")
        origin = str(getattr(spec, "origin", "") or "").lower().replace("/", "\\")
        return "company_shim" in origin
    except Exception:
        return False


def ensure_wk_warmup(tickers):
    """부족/오래된 종목만 ~3년 일봉을 받아 warmup 캐시 갱신 (yfinance/네이버shim).

    ※ 회사 셔틀로 받은 원주가는 '메모리에만' 두고 parquet 에 저장하지 않는다.
      us_wk_warmup.parquet 는 git 추적 파일이라, 한 번 원주가가 들어가면 집으로 전염된다
      (2026-08-14 실측: 배당주 44종목 오염, BDX 는 2년 전 가격이 33% 부풀려짐).
      다만 화면 영향은 작다 — _merge_wk_with_fresh 가 keep="last" 라 메인 일봉(수정주가)과
      겹치는 최근 ~2.3년은 전부 덮어써지고, warmup 단독 구간(가장 오래된 ~10개월)만 남는다.
      실측 교정 효과 = 표시봉의 0.8%(각 종목 가장 오래된 봉 1개), 현재색 변경 0종목.
      그래도 막는 이유: 추적 파일이 조용히 갈리는 것 자체가 위험하고(메인 일봉 캐시가 짧거나
      없는 머신에선 이 원주가가 그대로 화면에 나온다), 막는 비용이 0이다.
      회사 실행분도 이번 런에서는 배경이 그려지고, 집 실행 때 수정주가로 파일이 채워진다.
      ※ VSCO 는 야후에 없어(상장폐지/심볼변경) 네이버 원주가가 유일 원천 → 예외로 남겨둠."""
    store = _load_wk_store()
    today = _dt.date.today()
    min_days = int(WK_YEARS * 365 * 0.9)
    # 셔틀에서는 '며칠 늦음'을 이유로 재수집하지 않는다. 저장을 안 하니 매 실행 반복될 뿐인데,
    # 최근 꼬리는 어차피 _merge_wk_with_fresh 가 메인 일봉으로 메워준다(5~10일 지연 대비 장치).
    # → 회사 실행이 집보다 느려지는 일이 없다. 아예 없는/너무 짧은 종목만 받는다.
    shim = _shim_on_path()
    need = []
    for tk in tickers:
        g = store.get(tk)
        if g is None or g.empty:
            need.append(tk); continue
        last = g.index.max().date(); first = g.index.min().date()
        if (today - first).days < min_days:
            need.append(tk); continue
        if not shim and (today - last).days > 5:
            need.append(tk)
    if not need:
        return store
    try:
        import yfinance as yf
    except Exception as e:
        print(f"  [wk warmup] yfinance import 실패({e}) → 주봉 배경 생략")
        return store
    start = (today - _dt.timedelta(days=int(WK_YEARS * 365) + 10)).strftime("%Y-%m-%d")
    end   = (today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"  [wk warmup] {len(need)}종목 ~{WK_YEARS}년 일봉 수집 중…")
    # 회사망은 yfinance 를 차단한다(c1time_real 은 셔틀도 안 켬). 막힌 연결은 TCP 타임아웃까지
    # 수십 초를 잡아먹어 bat 전체가 늘어진다. 반면 '없는 심볼'은 야후가 즉답이라 집에서 0.4~2.8초다.
    # → 소요시간으로 둘을 구분해, 응답 자체가 안 오는 실패가 2번 연속이면 남은 종목을 포기한다.
    #   일봉/주봉 모두 로컬 캐시 읽기라 포기해도 차트는 그대로 그려진다(새 종목만 배경 없음).
    SLOW_FAIL_SEC = 8.0
    slow_fails = 0
    for i, tk in enumerate(need):
        t0 = time.time()
        ok = False
        try:
            df = yf.download(tk, start=start, end=end, auto_adjust=True,
                             progress=False, threads=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[COLS].dropna()
                df.index = pd.to_datetime(df.index)
                store[tk] = df.sort_index()
                ok = True
        except Exception as e:
            print(f"  [wk warmup] {tk} 수집 실패: {e}")
        if ok:
            slow_fails = 0
            continue
        if time.time() - t0 >= SLOW_FAIL_SEC:
            slow_fails += 1
            if slow_fails >= 2:
                print(f"  [wk warmup] 응답 없음 2회 연속 → 네트워크 불가로 판단, "
                      f"남은 {len(need) - i - 1}종목 생략 (기존 캐시로 차트는 정상 생성)")
                break
        else:
            slow_fails = 0
    if _is_naver_shim(yf):
        print(f"  [wk warmup] 네이버 셔틀(원주가) 감지 → 캐시 저장 생략 "
              f"(이번 실행만 메모리 사용, 집 실행 때 수정주가로 저장)")
    else:
        _save_wk_store(store)
    return store


_KR_WK_STORE = None
def _load_kr_wk_store():
    global _KR_WK_STORE
    if _KR_WK_STORE is not None:
        return _KR_WK_STORE
    _KR_WK_STORE = {}
    if os.path.exists(KR_WK_PARQUET):
        try:
            df = _normalize_ohlcv_columns(pd.read_parquet(KR_WK_PARQUET))
            df["date"] = pd.to_datetime(df["date"])
            for t, g in df.groupby("ticker"):
                tk = str(t).strip().zfill(6)
                if any(c not in g.columns for c in COLS):
                    continue
                _KR_WK_STORE[tk] = g.set_index("date")[COLS].sort_index()
        except Exception as e:
            print(f"  [KR wk warmup] cache read failed: {e}")
    return _KR_WK_STORE


def _save_kr_wk_store(store):
    try:
        frames = []
        for t, g in store.items():
            gg = g.copy()
            gg.index.name = "date"
            gg = gg.reset_index()
            gg.insert(1, "ticker", t)
            frames.append(gg[["date", "ticker"] + COLS])
        if frames:
            os.makedirs(os.path.dirname(KR_WK_PARQUET), exist_ok=True)
            pd.concat(frames, ignore_index=True).to_parquet(KR_WK_PARQUET, index=False)
    except Exception as e:
        print(f"  [KR wk warmup] cache save failed: {e}")


def ensure_kr_wk_warmup(tickers):
    store = _load_kr_wk_store()
    base = _load_store("KR")
    today = _dt.date.today()
    min_days = int(WK_YEARS * 365 * 0.9)
    need = []
    for tk in [str(t).strip().zfill(6) for t in tickers if str(t).strip()]:
        g = store.get(tk)
        if g is not None and not g.empty:
            first = g.index.min().date()
            last = g.index.max().date()
            if (today - first).days >= min_days and (today - last).days <= 10:
                continue
        g = base.get(tk)
        if g is not None and not g.empty:
            first = g.index.min().date()
            last = g.index.max().date()
            if (today - first).days >= min_days and (today - last).days <= 10:
                store[tk] = g.sort_index()
                continue
        need.append(tk)
    if need:
        try:
            from pykrx import stock
            start = (today - _dt.timedelta(days=int(WK_YEARS * 365) + 10)).strftime("%Y%m%d")
            end = today.strftime("%Y%m%d")
            print(f"  [KR wk warmup] {len(need)}종목 ~{WK_YEARS}년 일봉 보강")
            for tk in need:
                try:
                    df = stock.get_market_ohlcv_by_date(start, end, tk)
                    if df is None or df.empty:
                        continue
                    df = _normalize_ohlcv_columns(df.reset_index().rename(columns={"날짜": "date"}))
                    df["date"] = pd.to_datetime(df["date"])
                    store[tk] = df.set_index("date")[COLS].dropna().sort_index()
                except Exception as e:
                    print(f"  [KR wk warmup] {tk} fetch failed: {e}")
        except Exception as e:
            print(f"  [KR wk warmup] pykrx unavailable: {e}")
    _save_kr_wk_store(store)
    return store


def _merge_wk_with_fresh(wk_df, fresh_df):
    """warmup 캐시(3년 과거 깊이)와 메인 원천(매일 갱신되는 최신 꼬리)을 날짜 기준 병합.
    warmup은 최대 5~10일 뒤처질 수 있어 이번 주 봉이 누락/부분반영되는 문제가 있었음 →
    이미 메모리에 로드된 메인 parquet(네트워크 0)로 꼬리만 채워 항상 최신 주봉이 되게 함."""
    if fresh_df is None or fresh_df.empty:
        return wk_df
    if wk_df is None or wk_df.empty:
        return fresh_df
    merged = pd.concat([wk_df, fresh_df])
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def weekly_rows_maejib(ticker, market="US"):
    """~3년 일봉 → W-FRI 주봉 → 매집분산 end4 색을 M4 유효봉에만 부착.
    반환: [[date,o,h,l,c,v,(end4)], ...] 최근 DISPLAY_WEEKS개. warmup 미확보 시 배경없는 주봉으로 폴백."""
    market = str(market or "US").upper()
    key = str(ticker).strip().zfill(6) if market == "KR" else str(ticker).strip().upper()
    wk_df = (_load_kr_wk_store() if market == "KR" else _load_wk_store()).get(key)
    fresh_df = _load_store(market).get(key)
    df = _merge_wk_with_fresh(wk_df, fresh_df)
    if df is None or df.empty:
        return weekly_rows(daily_rows(ticker, market))
    d = df.copy(); d.index.name = "date"
    w = (d.resample("W-FRI")
           .agg({"Open": "first", "High": "max", "Low": "min",
                 "Close": "last", "Volume": "sum"})
           .dropna(subset=["Close"]))
    if w.empty:
        return weekly_rows(daily_rows(ticker, market))
    try:
        mdf = pd.DataFrame({
            "time":  w.index.strftime("%Y-%m-%d"),
            "open":  w.Open.values,  "high":   w.High.values,
            "low":   w.Low.values,   "close":  w.Close.values,
            "volume": w.Volume.values})
        calc = _majib.compute_majib(mdf)
        end4 = calc["end4"].values
        m4ok = calc["M4"].notna().values
    except Exception as e:
        print(f"  [주봉 배경] {ticker} 매집분산 계산 실패: {e}")
        end4 = [None] * len(w); m4ok = [False] * len(w)
    out = []
    for i in range(len(w)):
        base = [w.index[i].strftime("%Y-%m-%d"),
                round(float(w.Open.iloc[i]), 4),  round(float(w.High.iloc[i]), 4),
                round(float(w.Low.iloc[i]), 4),   round(float(w.Close.iloc[i]), 4),
                int(w.Volume.iloc[i] or 0)]
        st = end4[i]
        if m4ok[i] and st in ("black", "orange", "lime"):
            base.append(str(st))
        out.append(base)
    return out[-DISPLAY_WEEKS:]


def add_trend_states(rows):
    """rows([date,o,h,l,c,v]) → coloryp 추세state를 index[6]에 append (NONE이면 미부착).
    danta make_danta_chart_display.add_trend_states 와 동일한 판정식."""
    if not rows:
        return rows
    try:
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["dt"] = pd.to_datetime(df["date"])
        calc = check_coloryp_logic(df.set_index("dt"))
        angle_all = (calc[[f"m{i}ang" for i in range(5)]] <= 0).all(axis=1)
        angle_4   = (calc[[f"m{i}ang" for i in range(4)]] <= 0).all(axis=1)
        is_lime   = calc["lime_final"]
        is_green  = (calc["HLv99"] >= 1) & (calc["HLv71"] == 1) & ~is_lime
        is_red    = (((calc["HLv99"] <= -1) & (calc["HLv7"] == -1) & (calc["HLv71"] == -1))
                     | (calc["ang_sum"] == -5) | angle_all)
        is_purple = ((calc["HLv99"] <= -1) & (calc["HLv71"] == -1)) | angle_4
        states = np.select([is_lime, is_green, is_red, is_purple],
                           ["LIME", "GREEN", "RED", "PURPLE"], default="NONE")
        return [list(r) + ([str(states[i])] if states[i] != "NONE" else [])
                for i, r in enumerate(rows)]
    except Exception as e:
        print(f"  [TREND BG] 계산 실패: {e}")
        return [list(r) for r in rows]


# ───────── 팝업 CSS ─────────
POPUP_CSS = r"""
#v4pop{display:none;position:fixed;z-index:99999;width:1060px;background:#fff;
  border:1px solid #bdc3c7;border-radius:10px;padding:10px 12px 12px;
  box-shadow:0 12px 34px rgba(0,0,0,0.24);overflow-y:auto;max-height:92dvh;
  overscroll-behavior:contain;-webkit-overflow-scrolling:touch;}
body.v4-open{overflow:hidden;}
#v4pop .popup-header{display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap;}
#v4Close{display:flex;background:#e74c3c;color:#fff;border:none;border-radius:50%;
  width:26px;height:26px;font-size:16px;line-height:1;cursor:pointer;flex-shrink:0;
  align-items:center;justify-content:center;font-weight:bold;}
#v4pop .popup-title{font-weight:700;color:#2c3e50;font-size:14px;white-space:nowrap;}
#v4pop .popup-link{font-size:12px;color:#2980b9;text-decoration:none;white-space:nowrap;}
#v4pop .popup-link:hover{text-decoration:underline;}
#v4Ms{font-size:10px;color:#94a3b8;font-family:monospace;white-space:nowrap;}
#v4stBtn{margin-left:auto;width:50px;height:26px;flex-shrink:0;cursor:pointer;
  border:2px solid #7c3aed;background:#f5f3ff;color:#ef4444;font-weight:800;
  font-size:14px;line-height:1;border-radius:6px;}
#v4stBtn.on{background:#7c3aed;color:#fff;}
#v4pop .popTabs{display:none;gap:4px;margin-left:6px;}
#v4pop .popTab{padding:4px 12px;font-size:12px;cursor:pointer;border:1px solid #cbd5e1;
  background:#f8fafc;color:#475569;border-radius:5px;font-weight:700;}
#v4pop .popTab.active{background:#3498db;border-color:#3498db;color:#fff;}
#v4pop #popBox{display:flex;gap:14px;}
#v4pop .col{flex:1 1 0;min-width:0;}
#v4pop #colD{flex-grow:1.27;}  /* 일봉을 넓게(주로 봄) ~56% */
#v4pop #colW{flex-grow:1.0;}   /* 주봉은 참고 ~44% */
#v4pop .collab{font-size:11px;font-weight:700;color:#64748b;padding:2px 2px 4px;}
#v4pop .chartbox{position:relative;border:1px solid #eef1f4;border-radius:6px;overflow:hidden;}
#v4pop .legend{position:absolute;display:none;z-index:6;background:rgba(255,255,255,.96);
  border:1px solid #e5e7eb;border-radius:6px;padding:5px 8px;font-size:11px;line-height:1.5;
  color:#334155;pointer-events:none;min-width:150px;box-shadow:0 2px 8px rgba(0,0,0,.13);}
#v4pop .legend b{color:#0f172a;}
#v4pop .legend .k{display:inline-block;width:38px;color:#64748b;}
#v4pop .cchart{width:100%;height:300px;}
#v4pop .rlab{font-size:10px;color:#6b7280;padding:3px 8px 1px;}
#v4pop .rchart{width:100%;height:100px;}
#v4pop .empty{height:410px;display:flex;align-items:center;justify-content:center;
  color:#991b1b;font-size:13px;font-weight:700;}
/* 모바일 전용: RSI 좌측 절반을 스와이프(종목이동) 영역으로 덮음. 마우스 PC(pointer:fine)에는 display:none → 부작용 없음 */
#v4pop .rsi-swipe{display:none;position:absolute;left:0;bottom:0;width:50%;height:100px;
  z-index:7;background:transparent;touch-action:none;}
@media (pointer:coarse){#v4pop .rsi-swipe{display:block;}}
@media (pointer:coarse) and (max-width:767px){#v4pop .rsi-swipe{height:90px;}}
@media (max-width:1000px){
  #v4pop{width:96vw;left:2vw!important;}
  #v4pop .popTabs{display:flex;}
  #v4pop #popBox{display:block;}
  #v4pop .col.hidden{display:none;}
}
@media (max-width:767px){
  #v4pop{position:fixed!important;left:2vw!important;top:50%!important;
    transform:translateY(-50%);width:96vw!important;max-height:86dvh!important;padding:8px;}
  #v4pop .cchart{height:260px;}#v4pop .rchart{height:90px;}
  /* 헤더 1줄 압축(모바일 전용): render/봉수 표기 제거 + ✕ 종목명 차트 S 일봉 주봉 을 한 줄에.
     → 헤더가 2줄→1줄로 줄어든 만큼 차트 세트가 위로 올라와 RSI 잘림이 줄어듦. PC는 위 규칙 그대로. */
  #v4pop #v4Ms{display:none;}
  #v4pop .popup-header{flex-wrap:nowrap;gap:5px;margin-bottom:3px;}
  #v4pop .popup-title{font-size:12.5px;flex:1 1 auto;min-width:0;
    overflow:hidden;text-overflow:ellipsis;}   /* 이름 길면 말줄임(줄바꿈 금지) */
  #v4pop .popup-link{font-size:11px;flex-shrink:0;}
  #v4Close{width:24px;height:24px;font-size:15px;}
  #v4stBtn{width:34px;height:24px;font-size:13px;margin-left:4px;}
  #v4pop .popTabs{margin-left:3px;gap:3px;flex-shrink:0;}
  #v4pop .popTab{padding:3px 8px;font-size:11px;}
  #v4pop .collab{padding:1px 2px 2px;}
  #v4pop .rlab{padding:2px 8px 0;}
}
"""

# ───────── 팝업 HTML ─────────
POPUP_HTML = """
<div id="v4pop" tabindex="-1">
  <div class="popup-header">
    <button id="v4Close">&#x2715;</button>
    <div class="popup-title" id="v4Title">-</div>
    <a id="v4Link" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">차트</a>
    <span id="v4Ms"></span>
    <button id="v4stBtn" title="Supertrend 토글 (10/3·11/2·12/1) · a키">S</button>
    <div class="popTabs">
      <button class="popTab active" data-tab="d">일봉</button>
      <button class="popTab" data-tab="w">주봉</button>
    </div>
  </div>
  <div id="popBox">
    <div class="col" id="colD">
      <div class="collab">일봉 · 추세배경</div>
      <div class="chartbox"><div class="legend" id="lgD"></div><div class="cchart" id="chartD"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div><div class="rchart" id="rsiD"></div><div class="rsi-swipe"></div></div>
    </div>
    <div class="col" id="colW">
      <div class="collab">주봉 · 매집분산 배경 (검=매집전환 · 주황=분산 · 연두=매집)</div>
      <div class="chartbox"><div class="legend" id="lgW"></div><div class="cchart" id="chartW"></div>
        <div class="rlab">RSI(14) · 파랑=RSI 빨강=14이평</div><div class="rchart" id="rsiW"></div><div class="rsi-swipe"></div></div>
    </div>
  </div>
</div>
"""

# ───────── 팝업 JS ─────────
POPUP_JS = r"""
const DAILY  = __DAILY__;   // {TICKER:[[date,o,h,l,c,v,(state)],...]}
const WEEKLY = __WEEKLY__;  // {TICKER:[[date,o,h,l,c,v],...]}
const META   = __META__;    // {CODE:{market:'US'|'KR'}}
const KOSPI_D = __KOSPI_D__;
const TRACK_D = __TRACK_D__;
const TRIGGER_ATTR = '__TRIGGER_ATTR__';
const TRIGGER_SELECTOR = '[' + TRIGGER_ATTR + ']';
const VIS_D=90, VIS_W=70, RIGHT_PAD=5;
const MA_5=[[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a']];
const UP_COLOR='#f23645', DOWN_COLOR='#2962ff';
const VOL_UP='rgba(242,54,69,.72)', VOL_DOWN='rgba(41,98,255,.72)', VOL_SPOT='rgba(0,0,0,1)';
const VOL_SPOT_TURNOVER=5e10;  // spot & 거래대금>이 값 → 노랑 배경 (Pine 50000000000)
const TREND_BG_COLORS={
  LIME:'rgba(0,230,118,0.15)',GREEN:'rgba(76,175,80,0.15)',
  PURPLE:'rgba(192,132,252,0.14)',RED:'rgba(251,113,133,0.13)',NONE:'rgba(0,0,0,0)'};
// 매집분산 end4 (주봉 배경): black=매집전환(진입) / orange=분산 / lime=매집
const TREND_BG_MAEJIB={
  black:'rgba(15,23,42,0.42)',orange:'rgba(255,140,0,0.17)',lime:'rgba(0,200,90,0.17)'};
// canvas 오버레이 배경 사용 여부 — 2026-08-09 검증 완료, 코드 대기 (md/260809_차트_배경_canvas오버레이_주일선택가능.md)
const BG_CANVAS_MODE = {D:false, W:false};
const fmt=n=>{const a=Math.abs(n);return a>=1000?Math.round(n).toLocaleString():n.toFixed(2);};
const axisFmt=n=>{const a=Math.abs(n);
  return a>=1000?Math.round(n).toLocaleString():(a>=1?n.toFixed(2):n.toFixed(3));};
const volFmt=v=>{const a=Math.abs(v);
  return a>=1e6?(v/1e6).toFixed(1)+'M':(a>=1e3?Math.round(v/1e3)+'K':String(Math.round(v)));};
const PRICE_FORMAT={type:'custom',minMove:0.01,formatter:axisFmt};
const KR_PRICE_FORMAT={type:'custom',minMove:1,formatter:n=>Math.round(n).toLocaleString()};
const KOSPI_STYLE={color:'rgba(150,150,150,0.5)',lineWidth:2,
  lineStyle:LightweightCharts.LineStyle.Dotted,priceLineVisible:false,
  lastValueVisible:false,crosshairMarkerVisible:false,autoscaleInfoProvider:()=>null,
  priceFormat:KR_PRICE_FORMAT};

function sma(c,p){const o=[];let s=0;for(let i=0;i<c.length;i++){s+=c[i];if(i>=p)s-=c[i-p];
  if(i>=p-1)o.push({i,v:+(s/p).toFixed(4)});}return o;}
function rsiWilder(cl,p){const out=new Array(cl.length).fill(null);let g=0,l=0;
  for(let i=1;i<cl.length;i++){const ch=cl[i]-cl[i-1],gg=ch>0?ch:0,ll=ch<0?-ch:0;
    if(i<=p){g+=gg;l+=ll;if(i===p){g/=p;l/=p;out[i]=100-100/(1+(l===0?1e9:g/l));}}
    else{g=(g*(p-1)+gg)/p;l=(l*(p-1)+ll)/p;out[i]=100-100/(1+(l===0?1e9:g/l));}}
  return out;}
function smaArr(arr,p){const out=new Array(arr.length).fill(null);const buf=[];let s=0;
  for(let i=0;i<arr.length;i++){const v=arr[i];if(v==null){buf.length=0;s=0;continue;}
    buf.push(v);s+=v;if(buf.length>p)s-=buf.shift();if(buf.length===p)out[i]=s/p;}return out;}
function rollMeanN(arr,n){const out=new Array(arr.length).fill(null);
  for(let i=n-1;i<arr.length;i++){let s=0,ok=true;
    for(let j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}s+=arr[j];}
    out[i]=ok?s/n:null;}return out;}
function rollMaxN(arr,n){const out=new Array(arr.length).fill(null);
  for(let i=n-1;i<arr.length;i++){let m=-Infinity,ok=true;
    for(let j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]>m)m=arr[j];}
    out[i]=ok?m:null;}return out;}
function rollMinN(arr,n){const out=new Array(arr.length).fill(null);
  for(let i=n-1;i<arr.length;i++){let m=Infinity,ok=true;
    for(let j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]<m)m=arr[j];}
    out[i]=ok?m:null;}return out;}
function stochN(close,high,low,n){const out=new Array(close.length).fill(null);
  for(let i=n-1;i<close.length;i++){let lo=Infinity,hi=-Infinity;
    for(let j=i-n+1;j<=i;j++){if(low[j]<lo)lo=low[j];if(high[j]>hi)hi=high[j];}
    out[i]=(hi===lo)?null:(close[i]-lo)/(hi-lo)*100;}return out;}
function computeLowSignals(rows){
  const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);
  const k3=rollMeanN(stochN(close,high,low,20),10);
  const k2=rollMeanN(stochN(close,high,low,10),5);
  const hh=rollMaxN(high,10),ll=rollMinN(low,10);
  const diff=new Array(n).fill(null),rdiff=new Array(n).fill(null);
  for(let i=0;i<n;i++){if(hh[i]!=null&&ll[i]!=null){diff[i]=hh[i]-ll[i];rdiff[i]=close[i]-(hh[i]+ll[i])/2;}}
  const avgrel=rollMeanN(rollMeanN(rdiff,3),3);
  const avgdiff=rollMeanN(rollMeanN(diff,3),3);
  const smi=new Array(n).fill(0);
  for(let i=0;i<n;i++){if(avgrel[i]!=null&&avgdiff[i]!=null&&avgdiff[i]!==0)smi[i]=avgrel[i]/(avgdiff[i]/2)*100;}
  const smisig=rollMeanN(smi,3),emasig=rollMeanN(smi,10),rsi1=rsiWilder(close,14);
  const constat=new Array(n).fill(false);
  for(let i=0;i<n;i++){constat[i]=(smisig[i]!=null&&smisig[i]<=-60)&&(emasig[i]!=null&&emasig[i]<=-60)&&(rsi1[i]!=null&&rsi1[i]<=30);}
  const jeo=[],jeo2=[];
  for(let i=1;i<n;i++){
    if(k3[i]!=null&&k3[i-1]!=null&&k2[i]!=null&&k2[i-1]!=null&&k3[i]>=20&&k3[i-1]<20&&k2[i]>=k2[i-1])jeo.push(rows[i][0]);
    if(constat[i-1]&&!constat[i])jeo2.push(rows[i][0]);
  }
  return {jeo,jeo2};
}
function percentRankN(arr,len){const out=new Array(arr.length).fill(null);
  for(let i=len;i<arr.length;i++){if(arr[i]==null)continue;let cnt=0,ok=true;
    for(let j=i-len;j<i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]<=arr[i])cnt++;}
    out[i]=ok?100*cnt/len:null;}return out;}
function computeTopSignals(rows){
  const n=rows.length,close=rows.map(b=>b[4]);
  const m0=rollMeanN(close,5),m2=rollMeanN(close,20),m3=rollMeanN(close,60);
  const xr=m=>close.map((c,i)=>m[i]==null?null:100*(c-m[i])/c);
  const fr=percentRankN(xr(m3),220),sr=percentRankN(xr(m2),220),tr=percentRankN(xr(m0),220);
  const hld=new Array(n).fill(false);
  for(let i=0;i<n;i++)hld[i]=fr[i]!=null&&sr[i]!=null&&tr[i]!=null&&fr[i]>=95&&sr[i]>=95&&tr[i]>=95;
  const out=[];
  for(let i=2;i<n;i++){
    if(hld[i-1]&&tr[i]!=null&&tr[i-1]!=null&&tr[i-2]!=null&&tr[i]<=tr[i-1]&&tr[i-1]<=tr[i-2])out.push(rows[i][0]);
  }
  return out;
}

function paintLegend(lg,b){
  const cu=b[4]>=b[1]?UP_COLOR:DOWN_COLOR;
  lg.innerHTML=
    '<div><span class="k">날짜</span><b>'+b[0]+'</b></div>'+
    '<div><span class="k">종가</span><b style="color:'+cu+'">'+fmt(b[4])+'</b></div>'+
    '<div><span class="k">거래량</span><b>'+volFmt(b[5])+'</b></div>'+
    '<div><span class="k">시가</span>'+fmt(b[1])+'</div>'+
    '<div><span class="k">고가</span><span style="color:'+UP_COLOR+'">'+fmt(b[2])+'</span></div>'+
    '<div><span class="k">저가</span><span style="color:'+DOWN_COLOR+'">'+fmt(b[3])+'</span></div>';
}
function attachTooltip(ch,el,lg,byKey){
  ch.subscribeCrosshairMove(param=>{
    if(!param.time||!param.point||!byKey.has(param.time)){lg.style.display='none';return;}
    paintLegend(lg,byKey.get(param.time));lg.style.display='block';
    const bw=lg.offsetWidth,bh=lg.offsetHeight;
    let lx=param.point.x-bw-14;if(lx<4)lx=param.point.x+14;
    let ly=param.point.y-bh/2;ly=Math.max(2,Math.min(ly,el.clientHeight-bh-2));
    lg.style.left=lx+'px';lg.style.top=ly+'px';
  });
}
function newCandle(el){
  return LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.08,bottom:0.08}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:2,visible:false},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});
}
function newRsi(el){
  return LightweightCharts.createChart(el,{width:el.clientWidth,height:el.clientHeight,
    layout:{background:{color:'#fff'},textColor:'#888',fontSize:10},
    grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f7f7f7'}},
    rightPriceScale:{borderColor:'#ddd',scaleMargins:{top:0.12,bottom:0.12}},
    timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:2},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});
}
function addRsi(rel,rdata,rmdata){
  const rch=newRsi(rel);
  const bUp=rch.addBaselineSeries({baseValue:{type:'price',price:70},
    topLineColor:'rgba(0,0,0,0)',topFillColor1:'rgba(50,205,50,0.62)',topFillColor2:'rgba(50,205,50,0.30)',
    bottomLineColor:'rgba(0,0,0,0)',bottomFillColor1:'rgba(0,0,0,0)',bottomFillColor2:'rgba(0,0,0,0)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  bUp.setData(rdata);
  const bDn=rch.addBaselineSeries({baseValue:{type:'price',price:30},
    topLineColor:'rgba(0,0,0,0)',topFillColor1:'rgba(0,0,0,0)',topFillColor2:'rgba(0,0,0,0)',
    bottomLineColor:'rgba(0,0,0,0)',bottomFillColor1:'rgba(239,68,68,0.30)',bottomFillColor2:'rgba(239,68,68,0.62)',
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  bDn.setData(rdata);
  const rl=rch.addLineSeries({color:DOWN_COLOR,lineWidth:1,priceLineVisible:false,
    lastValueVisible:true,crosshairMarkerVisible:false});
  rl.setData(rdata);
  const rm=rch.addLineSeries({color:UP_COLOR,lineWidth:1,priceLineVisible:false,
    lastValueVisible:false,crosshairMarkerVisible:false});
  rm.setData(rmdata);
  [70,30].forEach(lv=>rl.createPriceLine({price:lv,color:'#9ca3af',lineWidth:1,
    lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true}));
  return {rch,rl};
}
function syncPair(a,b){let lock=false;
  const s=(src,dst)=>src.timeScale().subscribeVisibleLogicalRangeChange(r=>{
    if(lock||!r)return;lock=true;dst.timeScale().setVisibleLogicalRange(r);lock=false;});
  s(a,b);s(b,a);}
function syncCrosshair(a,aS,aMap,b,bS,bMap){
  let lock=false;
  const link=(src,dst,dstS,dstMap)=>src.subscribeCrosshairMove(p=>{
    if(lock)return;lock=true;
    if(p.time==null||p.point==null)dst.clearCrosshairPosition();
    else{const v=dstMap.get(p.time);
      if(v==null)dst.clearCrosshairPosition();else dst.setCrosshairPosition(v,p.time,dstS);}
    lock=false;});
  link(a,b,bS,bMap);link(b,a,aS,aMap);}
function alignScales(ch,rch){
  requestAnimationFrame(()=>{try{
    const w=Math.max(ch.priceScale('right').width(),rch.priceScale('right').width());
    ch.priceScale('right').applyOptions({minimumWidth:w});
    rch.priceScale('right').applyOptions({minimumWidth:w});
  }catch(e){}});
}
function addCandleVol(ch,priceFormat){
  const cs=ch.addCandlestickSeries({upColor:UP_COLOR,downColor:DOWN_COLOR,borderUpColor:UP_COLOR,
    borderDownColor:DOWN_COLOR,wickUpColor:UP_COLOR,wickDownColor:DOWN_COLOR,priceFormat:priceFormat||PRICE_FORMAT});
  const vol=ch.addHistogramSeries({priceScaleId:'',
    priceFormat:{type:'custom',minMove:1,formatter:volFmt}});
  vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
  return [cs,vol];
}

// ── Supertrend (TradingView ta.supertrend 동일 공식) — S버튼/a키 토글 시 MA 대신 3종 표시 ──
const ST_PARAMS=[
  {atr:10,factor:3,up:'rgba(8,153,129,0.5)', dn:'rgba(242,54,69,0.5)', bandUp:'rgba(8,153,129,0.10)', bandDn:'rgba(242,54,69,0.10)', w:1},
  {atr:11,factor:2,up:'rgba(22,163,74,0.5)', dn:'rgba(239,68,68,0.5)', bandUp:'rgba(22,163,74,0.075)',bandDn:'rgba(239,68,68,0.075)',w:1},
  {atr:12,factor:1,up:'rgba(101,163,13,0.5)',dn:'rgba(249,115,22,0.5)',bandUp:'rgba(101,163,13,0.06)',bandDn:'rgba(249,115,22,0.06)',w:1},
];
const SHOW_BANDS=true;
function atrWilder(rows,p){const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);
  const tr=new Array(n),atr=new Array(n).fill(null);
  for(let i=0;i<n;i++)tr[i]=(i===0)?(high[i]-low[i])
    :Math.max(high[i]-low[i],Math.abs(high[i]-close[i-1]),Math.abs(low[i]-close[i-1]));
  let s=0;for(let i=0;i<n;i++){if(i<p){s+=tr[i];if(i===p-1)atr[i]=s/p;}
    else atr[i]=(atr[i-1]*(p-1)+tr[i])/p;}return atr;}
function supertrend(rows,factor,atrPeriod){const n=rows.length;
  const high=rows.map(b=>b[2]),low=rows.map(b=>b[3]),close=rows.map(b=>b[4]);
  const atr=atrWilder(rows,atrPeriod);
  const st=new Array(n).fill(null),dir=new Array(n).fill(null);
  let prevUpper=0,prevLower=0,prevST=0;
  for(let i=0;i<n;i++){if(atr[i]==null){st[i]=null;dir[i]=null;continue;}
    const hl2=(high[i]+low[i])/2;
    let upper=hl2+factor*atr[i], lower=hl2-factor*atr[i];
    const hasPrev=(i>0&&atr[i-1]!=null);
    if(hasPrev){const pc=close[i-1];
      lower=(lower>prevLower||pc<prevLower)?lower:prevLower;
      upper=(upper<prevUpper||pc>prevUpper)?upper:prevUpper;}
    let d;if(!hasPrev)d=1;else if(prevST===prevUpper)d=(close[i]>upper)?-1:1;
    else d=(close[i]<lower)?1:-1;
    const v=(d===-1)?lower:upper;
    st[i]=v;dir[i]=d;prevUpper=upper;prevLower=lower;prevST=v;}
  return {st,dir};}
function activeValue(p){return p&&p.value!=null?Number(p.value):null;}
function buildFillEnvelope(anchor,line,color){if(!anchor.length||!line.length)return [];
  const out=[];for(let i=0;i<Math.min(anchor.length,line.length);i++){
    const a=activeValue(anchor[i]),v=activeValue(line[i]);
    if(a==null||v==null||!Number.isFinite(a)||!Number.isFinite(v)){out.push({time:anchor[i].time});continue;}
    out.push({time:anchor[i].time,upper:Math.max(a,v),lower:Math.min(a,v),color});}return out;}
function installBandOverlay(el,ch,priceSeries,bands){
  if(!SHOW_BANDS||!bands.length)return;
  el.style.position='relative';
  const canvas=document.createElement('canvas');
  canvas.className='st-band-overlay';
  canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;';
  el.appendChild(canvas);
  let raf=0;
  function queueDraw(){if(raf)return;raf=requestAnimationFrame(()=>{raf=0;draw();});}
  function draw(){const dpr=window.devicePixelRatio||1,w=el.clientWidth,h=el.clientHeight;
    if(!w||!h)return;
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){
      canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
      canvas.style.width=w+'px';canvas.style.height=h+'px';}
    const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    bands.forEach(band=>{let upper=[],lower=[];
      function flush(){if(upper.length<2||lower.length<2){upper=[];lower=[];return;}
        ctx.beginPath();ctx.moveTo(upper[0][0],upper[0][1]);
        for(let i=1;i<upper.length;i++)ctx.lineTo(upper[i][0],upper[i][1]);
        for(let i=lower.length-1;i>=0;i--)ctx.lineTo(lower[i][0],lower[i][1]);
        ctx.closePath();ctx.fillStyle=band.color;ctx.fill();upper=[];lower=[];}
      band.points.forEach(p=>{if(p.upper==null||p.lower==null){flush();return;}
        const x=ch.timeScale().timeToCoordinate(p.time);
        const y1=priceSeries.priceToCoordinate(p.upper);
        const y2=priceSeries.priceToCoordinate(p.lower);
        if(x==null||y1==null||y2==null){flush();return;}
        upper.push([x,y1]);lower.push([x,y2]);});
      flush();});}
  queueDraw();
  ch.timeScale().subscribeVisibleLogicalRangeChange(queueDraw);}

function installTrendBgOverlay(el,ch,rows,bgMap){
  el.style.position='relative';
  const canvas=document.createElement('canvas');
  canvas.className='trendbg-overlay';
  canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:2;';
  el.appendChild(canvas);
  let raf=0;
  function queueDraw(){if(raf)return;raf=requestAnimationFrame(()=>{raf=0;draw();});}
  function draw(){
    const dpr=window.devicePixelRatio||1,w=el.clientWidth,h=el.clientHeight;
    if(!w||!h)return;
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){
      canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
      canvas.style.width=w+'px';canvas.style.height=h+'px';
    }
    const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    const ts=ch.timeScale();
    let spacing=6;
    for(let i=0;i<rows.length-1;i++){
      const x0=ts.timeToCoordinate(rows[i][0]),x1=ts.timeToCoordinate(rows[i+1][0]);
      if(x0!=null&&x1!=null){spacing=x1-x0;break;}
    }
    // 같은 색 연속구간(run)을 하나의 사각형으로 묶어 한 번만 칠함.
    // 경계는 겹치지 않게 이웃 봉과의 정중앙(midpoint)으로 계산 — 겹치면 색이 섞여 탁해지고,
    // 틈을 두면 흰 선이 생기므로 그 중간(겹침도 틈도 없음)이 정답.
    const coords=rows.map(b=>ts.timeToCoordinate(b[0]));
    let i=0;
    while(i<rows.length){
      const tag=rows[i][6],col=tag&&bgMap[tag];
      if(!col||col==='rgba(0,0,0,0)'){i++;continue;}
      let j=i;
      while(j+1<rows.length&&rows[j+1][6]===tag)j++;
      const xi=coords[i],xj=coords[j];
      if(xi!=null&&xj!=null){
        const left=(i>0&&coords[i-1]!=null)?(coords[i-1]+xi)/2:xi-spacing/2;
        const right=(j<rows.length-1&&coords[j+1]!=null)?(xj+coords[j+1])/2:xj+spacing/2;
        ctx.fillStyle=col;ctx.fillRect(left,0,right-left,h);
      }
      i=j+1;
    }
  }
  queueDraw();
  ch.timeScale().subscribeVisibleLogicalRangeChange(queueDraw);
  window.addEventListener('resize',queueDraw);
}

let charts=[], openTimer=null, closeTimer=null, pinned=false, curCode=null, curTd=null, stMode=false;
function normCode(v,market){v=(v||'').replace(/[*]/g,'').trim().toUpperCase();return market==='KR'?v.padStart(6,'0'):v;}
function metaOf(code){return META[code]||{market:'US'};}
function codeFromEl(el){const raw=el.getAttribute(TRIGGER_ATTR)||el.dataset.ticker||el.dataset.code||'';
  const m=(el.getAttribute('data-v4-market')||'').toUpperCase()||(/^\d{6}$/.test(raw)?'KR':'US');
  return normCode(raw,m);}
function nameFromEl(el){return el.getAttribute('data-name')||el.getAttribute('title')||'';}

function buildTF(prefix,rows,visBars,bgMap,code){
  const el=document.getElementById('chart'+prefix), lg=document.getElementById('lg'+prefix);
  const rel=document.getElementById('rsi'+prefix);
  const market=metaOf(code).market;
  const priceFormat=market==='KR'?KR_PRICE_FORMAT:PRICE_FORMAT;
  const ch=newCandle(el);
  if(bgMap){
    if(BG_CANVAS_MODE[prefix]){
      installTrendBgOverlay(el,ch,rows,bgMap);
    }else{
      const trendBand=ch.addHistogramSeries({priceScaleId:'trendbg',base:0,
        priceLineVisible:false,lastValueVisible:false});
      ch.priceScale('trendbg').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
      trendBand.setData(rows.filter(b=>b[6]&&bgMap[b[6]]).map(b=>({
        time:b[0],value:1,color:bgMap[b[6]]})));
    }
  }
  const trackDates=(prefix==='D' ? (TRACK_D[code]||null) : null);
  if(trackDates&&trackDates.length){
    const trkBand=ch.addHistogramSeries({priceScaleId:'trkband',base:0,
      priceLineVisible:false,lastValueVisible:false,color:'rgba(50,205,50,0.30)'});
    ch.priceScale('trkband').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
    const st=new Set(trackDates);
    trkBand.setData(rows.filter(r=>st.has(r[0])).map(r=>({time:r[0],value:1,color:'rgba(50,205,50,0.30)'})));
  }
  const kospiLine=(prefix==='D'&&market==='KR'&&!stMode&&Object.keys(KOSPI_D).length)?ch.addLineSeries(KOSPI_STYLE):null;
  const [cs,vol]=addCandleVol(ch,priceFormat);
  cs.setData(rows.map(b=>({time:b[0],open:b[1],high:b[2],low:b[3],close:b[4]})));
  if(kospiLine){
    const m=rows.length,aIdx=Math.max(0,m-1-20),K0=KOSPI_D[rows[aIdx][0]],P0=rows[aIdx][4];
    if(K0!=null&&K0){
      const kd=[];
      for(let i=aIdx;i<m;i++){const K=KOSPI_D[rows[i][0]];if(K!=null)kd.push({time:rows[i][0],value:P0*K/K0});}
      if(kd.length>=2){
        kospiLine.setData(kd);
        kospiLine.setMarkers([{time:kd[kd.length-1].time,position:'inBar',
          color:'rgba(150,150,150,0.5)',shape:'square',size:2}]);
      }
    }
  }
  // ── 거래량 색 (Pine "거래량"): spot급증→검정 / 종가>=전일종가→빨강 / else 파랑 ──
  const vols=rows.map(b=>b[5]), closeArr=rows.map(b=>b[4]);
  const vsma5=smaArr(vols,5), vsma10=smaArr(vols,10);
  const spotArr=rows.map((b,i)=>
    (i>0&&vols[i]>=vols[i-1]*10)||(vsma5[i]!=null&&vols[i]>=vsma5[i]*2.5));
  vol.setData(rows.map((b,i)=>{
    let c;
    if(spotArr[i])c=VOL_SPOT;
    else if(i===0||closeArr[i]>=closeArr[i-1])c=VOL_UP;
    else c=VOL_DOWN;
    return {time:b[0],value:b[5],color:c};}));
  // 거래량 10이평 라인 (같은 스케일)
  const vma=ch.addLineSeries({priceScaleId:'',color:'#f59e0b',lineWidth:1,
    priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,
    autoscaleInfoProvider:()=>null});
  vma.setData(rows.map((b,i)=>vsma10[i]==null?{time:b[0]}:{time:b[0],value:vsma10[i]}));
  // spot & 거래대금>500억 → 노랑 배경
  const spotBg=ch.addHistogramSeries({priceScaleId:'spotbg',base:0,
    priceLineVisible:false,lastValueVisible:false});
  ch.priceScale('spotbg').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
  spotBg.setData(rows.filter((b,i)=>spotArr[i]&&b[5]*b[4]>VOL_SPOT_TURNOVER)
    .map(b=>({time:b[0],value:1,color:'rgba(255,214,0,0.35)'})));
  const closes=rows.map(b=>b[4]);
  if(!stMode){
    MA_5.forEach(([p,color])=>{const m=new Map(sma(closes,p).map(o=>[rows[o.i][0],o.v]));
      const ln=ch.addLineSeries({color,lineWidth:1,priceLineVisible:false,priceFormat:priceFormat,
        autoscaleInfoProvider:()=>null,lastValueVisible:false,crosshairMarkerVisible:false});
      ln.setData(rows.map(b=>m.has(b[0])?{time:b[0],value:m.get(b[0])}:{time:b[0]}));});
  }else{
    // Supertrend 3종(10/3·11/2·12/1) — 선 3개 + 음영밴드(bodyMid↔Supertrend, 캔버스 오버레이)
    const times=rows.map(b=>b[0]);
    const STS=ST_PARAMS.map(sp=>supertrend(rows,sp.factor,sp.atr));
    const bodyMid=times.map((t,i)=>({time:t,value:+(((rows[i][1]+rows[i][4])/2).toFixed(4))}));
    const stUp=STS.map(r=>times.map((t,i)=>(r.st[i]!=null&&r.dir[i]<0)?{time:t,value:+r.st[i].toFixed(4)}:{time:t}));
    const stDn=STS.map(r=>times.map((t,i)=>(r.st[i]!=null&&r.dir[i]>0)?{time:t,value:+r.st[i].toFixed(4)}:{time:t}));
    installBandOverlay(el,ch,cs,ST_PARAMS.flatMap((sp,si)=>[
      {color:sp.bandUp,points:buildFillEnvelope(bodyMid,stUp[si],sp.bandUp)},
      {color:sp.bandDn,points:buildFillEnvelope(bodyMid,stDn[si],sp.bandDn)}
    ]));
    ST_PARAMS.forEach((sp,si)=>{const r=STS[si];
      const ln=ch.addLineSeries({color:sp.up,lineWidth:sp.w,priceLineVisible:false,priceFormat:priceFormat,
        autoscaleInfoProvider:()=>null,lastValueVisible:false,crosshairMarkerVisible:false});
      ln.setData(times.map((t,i)=>r.st[i]==null?{time:t}
        :{time:t,value:+r.st[i].toFixed(4),color:r.dir[i]<0?sp.up:sp.dn}));});
  }
  const sig=computeLowSignals(rows), marks=[];
  sig.jeo.forEach(t=>marks.push({time:t,position:'belowBar',color:'#e11d1d',shape:'square',text:'저'}));
  sig.jeo2.forEach(t=>marks.push({time:t,position:'belowBar',color:'#000000',shape:'arrowUp',text:'저2'}));
  computeTopSignals(rows).forEach(t=>marks.push({time:t,position:'aboveBar',color:'#000000',shape:'arrowDown',text:'X'}));
  marks.sort((a,b)=>a.time<b.time?-1:(a.time>b.time?1:0));
  if(marks.length)cs.setMarkers(marks);
  const rsiArr=rsiWilder(closes,14), rsiMa=smaArr(rsiArr,14);
  const rd =rows.map((b,i)=>rsiArr[i]==null?{time:b[0]}:{time:b[0],value:+rsiArr[i].toFixed(2)});
  const rmd=rows.map((b,i)=>rsiMa[i] ==null?{time:b[0]}:{time:b[0],value:+rsiMa[i].toFixed(2)});
  const {rch,rl}=addRsi(rel,rd,rmd);
  const n=rows.length, from=Math.max(0,n-visBars), to=n-1+RIGHT_PAD;
  ch.timeScale().setVisibleLogicalRange({from,to});
  rch.timeScale().setVisibleLogicalRange({from,to});
  syncPair(ch,rch); alignScales(ch,rch);
  syncCrosshair(ch,cs,new Map(rows.map(b=>[b[0],b[4]])),
                rch,rl,new Map(rd.filter(d=>d.value!=null).map(d=>[d.time,d.value])));
  attachTooltip(ch,el,lg,new Map(rows.map(b=>[b[0],b])));
  charts.push(ch,rch);
}

function destroyChart(){charts.forEach(c=>{try{c.remove();}catch(e){}});charts=[];
  document.querySelectorAll('#v4pop .st-band-overlay').forEach(n=>n.remove());
  ['lgD','lgW'].forEach(id=>document.getElementById(id).style.display='none');}
const pop=document.getElementById('v4pop');
const popTitle=document.getElementById('v4Title');
const popLink=document.getElementById('v4Link');
const popMs=document.getElementById('v4Ms');
const stBtn=document.getElementById('v4stBtn');

function popBoxEmpty(show){
  document.getElementById('colD').style.visibility=show?'hidden':'visible';
  document.getElementById('colW').style.visibility=show?'hidden':'visible';
  let e=document.querySelector('#popBox .empty');
  if(show){if(!e){e=document.createElement('div');e.className='empty';e.textContent='데이터 없음';document.getElementById('popBox').appendChild(e);}}
  else if(e)e.remove();
}
let curD=[], curW=[], builtD=false, builtW=false;
function ensureD(){if(!builtD&&curD.length){buildTF('D',curD,VIS_D,TREND_BG_COLORS,curCode);builtD=true;}}
function ensureW(){if(!builtW&&curW.length){buildTF('W',curW,VIS_W,TREND_BG_MAEJIB,curCode);builtW=true;}}
function showChart(ticker,name){
  curCode=ticker;
  const meta=metaOf(ticker);
  popTitle.textContent=ticker+(name?('  '+name):'');
  popLink.href=meta.market==='KR'
    ?('https://finance.naver.com/item/main.naver?code='+ticker)
    :('https://finviz.com/quote.ashx?t='+ticker);
  destroyChart();builtD=false;builtW=false;
  curD=DAILY[ticker]||[]; curW=WEEKLY[ticker]||[];
  if(!curD.length&&!curW.length){popBoxEmpty(true);popMs.textContent='';return;}
  popBoxEmpty(false);
  const t0=performance.now();
  applyTab();
  popMs.textContent='render '+(Math.round((performance.now()-t0)*10)/10)+' ms · 일 '+curD.length+' / 주 '+curW.length;
}
function applyTab(which){
  const cD=document.getElementById('colD'), cW=document.getElementById('colW');
  if(window.innerWidth>1000){cD.classList.remove('hidden');cW.classList.remove('hidden');ensureD();ensureW();return;}
  const tab=which||pop.dataset.tab||'d';
  if(tab==='d'){cD.classList.remove('hidden');cW.classList.add('hidden');ensureD();}
  else{cD.classList.add('hidden');cW.classList.remove('hidden');ensureW();}
  pop.dataset.tab=tab;
  document.querySelectorAll('.popTab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
}

function placePop(x,y){if(window.innerWidth<=1000)return;
  const w=Math.min(1060,window.innerWidth-20),h=470;let px=x+18,py=y+18;
  if(px+w>window.innerWidth-8)px=x-w-12;if(py+h>window.innerHeight-8)py=y-h-12;
  pop.style.left=Math.max(8,px)+'px';pop.style.top=Math.max(8,py)+'px';pop.style.transform='none';}
function openPop(){pop.style.display='block';document.body.classList.add('v4-open');
  try{if(document.activeElement===document.body||document.activeElement===null)pop.focus({preventScroll:true});}catch(e){}}
function closePop(){pop.style.display='none';document.body.classList.remove('v4-open');pinned=false;destroyChart();
  document.removeEventListener('mousemove',unpinOnMove);
  if(stMode){stMode=false;stBtn.classList.remove('on');}}
function toggleST(){stMode=!stMode;stBtn.classList.toggle('on',stMode);
  if(curCode&&pop.style.display==='block')showChart(curCode);}
function cancelClose(){clearTimeout(closeTimer);closeTimer=null;}
function scheduleClose(){cancelClose();closeTimer=setTimeout(()=>{if(!pinned)closePop();},220);}
function unpinOnMove(e){if(pop.contains(e.target))return;
  document.removeEventListener('mousemove',unpinOnMove);pinned=false;scheduleClose();}
function kbPin(){pinned=true;cancelClose();
  document.removeEventListener('mousemove',unpinOnMove);
  document.addEventListener('mousemove',unpinOnMove);}

document.getElementById('v4Close').addEventListener('click',closePop);
stBtn.addEventListener('click',e=>{e.stopPropagation();toggleST();});
document.querySelectorAll('.popTab').forEach(b=>{
  b.addEventListener('click',e=>{e.stopPropagation();applyTab(b.dataset.tab);});});
pop.addEventListener('mouseenter',()=>{pinned=true;cancelClose();document.removeEventListener('mousemove',unpinOnMove);});
pop.addEventListener('mouseleave',()=>{pinned=false;scheduleClose();});
function bindV4Triggers(){
document.querySelectorAll(TRIGGER_SELECTOR).forEach(td=>{
  if(td.__v4bound)return;td.__v4bound=true;
  td.addEventListener('mouseenter',e=>{
    if(window.matchMedia('(hover: none)').matches)return;
    cancelClose();
    const x=e.clientX,y=e.clientY,tk=codeFromEl(td);
    clearTimeout(openTimer);
    openTimer=setTimeout(()=>{placePop(x,y);openPop();showChart(tk,nameFromEl(td));curTd=td;},60);});
  td.addEventListener('mouseleave',()=>{clearTimeout(openTimer);scheduleClose();});
  td.addEventListener('click',e=>{
    if(window.matchMedia('(hover: none)').matches||window.innerWidth<=1000){
      e.stopPropagation();cancelClose();clearTimeout(openTimer);
      openPop();pinned=true;showChart(codeFromEl(td),nameFromEl(td));curTd=td;}});
});
}
bindV4Triggers();
window.v4RebindTriggers=bindV4Triggers;
document.addEventListener('click',e=>{
  if(pop.style.display!=='block')return;
  if(pop.contains(e.target))return;
  if(e.target.closest&&e.target.closest(TRIGGER_SELECTOR))return;
  closePop();});
document.addEventListener('keydown',e=>{
  if(pop.style.display!=='block')return;
  const tg=e.target,tag=tg&&tg.tagName;
  if(tag==='INPUT'||tag==='TEXTAREA'||(tg&&tg.isContentEditable))return;
  const k=e.key;
  if(k==='Tab'||k==='Escape'){e.preventDefault();closePop();return;}
  if(k==='a'||k==='A'){if(e.repeat)return;e.preventDefault();toggleST();return;}
  let dir=0;
  if(k==='s'||k==='S'||k==='ArrowUp')dir=-1;
  else if(k==='d'||k==='D'||k==='ArrowDown')dir=1;
  if(dir===0||!curTd)return;
  e.preventDefault();
  const all=Array.from(document.querySelectorAll(TRIGGER_SELECTOR));
  let i=all.indexOf(curTd);if(i<0)return;i+=dir;if(i<0||i>=all.length)return;
  const nt=all[i];kbPin();
  showChart(codeFromEl(nt),nameFromEl(nt));
  curTd=nt;nt.scrollIntoView({block:'nearest'});});
window.addEventListener('resize',()=>{if(curCode&&pop.style.display==='block')showChart(curCode);});
/* ── 모바일 전용: RSI 좌측영역 좌우 스와이프로 종목이동 (PC 단축키 s/d·화살표와 완전 독립) ── */
function navStock(dir){
  if(pop.style.display!=='block'||!curTd)return;
  const all=Array.from(document.querySelectorAll(TRIGGER_SELECTOR));
  let i=all.indexOf(curTd);if(i<0)return;i+=dir;
  if(i<0||i>=all.length){closePop();return;}   /* 첫종목서 이전/마지막종목서 다음 밀면 → 차트 닫기 */
  const nt=all[i];kbPin();
  showChart(codeFromEl(nt),nameFromEl(nt));
  curTd=nt;nt.scrollIntoView({block:'nearest'});}
(function(){
  const TH=40;let sx=0,sy=0,st=0,tracking=false;
  document.querySelectorAll('#v4pop .rsi-swipe').forEach(function(ov){
    ov.addEventListener('touchstart',function(e){
      if(e.touches.length!==1){tracking=false;return;}
      sx=e.touches[0].clientX;sy=e.touches[0].clientY;st=Date.now();tracking=true;
    },{passive:true});
    ov.addEventListener('touchmove',function(e){
      if(!tracking||window.__swipeNavInit)return;
      const t=e.touches[0],dx=t.clientX-sx,dy=t.clientY-sy;
      if(Math.abs(dx)>Math.abs(dy))e.preventDefault();   /* 가로밀기면 사파리 뒤로가기 등 기본제스처 차단 */
    },{passive:false});
    ov.addEventListener('touchend',function(e){
      if(!tracking)return;tracking=false;
      if(window.__swipeNavInit)return;   /* 페이지 전역 스와이프 주입이 있으면 그쪽이 처리 → 이중이동 방지 */
      const t=e.changedTouches[0],dx=t.clientX-sx,dy=t.clientY-sy;
      if(Math.abs(dx)<TH||Math.abs(dx)<=Math.abs(dy))return;   /* 좌우 밀기만·짧은탭/세로는 무시 */
      navStock(dx<0?1:-1);   /* 왼쪽밀기(dx<0)→다음종목, 오른쪽밀기→이전종목 */
    },{passive:true});
  });
})();
__AUTO_OPEN__
"""


def _fetch_kospi_daily(days_back=80):
    try:
        from chart_popup_v2 import fetch_kospi_daily
        return fetch_kospi_daily(days_back=days_back)
    except Exception:
        pass
    try:
        from pykrx import stock
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days_back)
        df = stock.get_index_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "1001")
        if df is None or df.empty:
            return {}
        df = _normalize_ohlcv_columns(df.reset_index().rename(columns={"날짜": "date"}))
        df["date"] = pd.to_datetime(df["date"])
        return {r.date.strftime("%Y-%m-%d"): float(r.Close) for r in df.itertuples()}
    except Exception as e:
        print(f"  [KOSPI overlay] skipped: {e}")
        return {}


def build_chart_popup(tickers, auto_ticker=None, market="US", market_map=None,
                      trigger_attr="data-ticker", include_kospi=False, track_dates=None):
    def _norm(t, m):
        return str(t).strip().upper().zfill(6) if str(m).upper() == "KR" else str(t).strip().upper()
    raw_map = market_map or {}
    market_map = {_norm(k, v): str(v).upper() for k, v in raw_map.items()}
    tickers = [_norm(t, raw_map.get(str(t).strip().upper(), market)) for t in tickers if str(t).strip()]
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return "<!-- chart_popup_v4: no tickers -->"
    t0 = time.time()
    meta = {tk: {"market": market_map.get(tk, str(market).upper())} for tk in tickers}
    kr_tickers = [tk for tk, v in meta.items() if v["market"] == "KR"]
    _all_tickers = tickers
    tickers = [tk for tk in tickers if meta[tk]["market"] != "KR"]
    ensure_wk_warmup(tickers)            # 주봉 배경용 ~3년 일봉 확보(부족분만 수집)
    if kr_tickers:
        ensure_kr_wk_warmup(kr_tickers)
    tickers = _all_tickers
    daily, weekly = {}, {}
    nD = nW = nBg = 0
    for tk in tickers:
        mkt = meta[tk]["market"]
        d = daily_rows(tk, mkt)
        daily[tk] = add_trend_states(d) if d else []   # 일봉 = coloryp 배경
        wk = weekly_rows_maejib(tk)                     # 주봉 = 매집분산 end4 배경
        weekly[tk] = wk
        if mkt == "KR":
            wk = weekly_rows_maejib(tk, mkt)
            weekly[tk] = wk
        if d:  nD += 1
        if wk: nW += 1
        if any(len(r) > 6 for r in wk): nBg += 1
    print(f"  [chart_popup_v4] {len(tickers)}종목 · 일봉 {nD} · 주봉 {nW}(배경 {nBg}) · {time.time()-t0:.1f}s")
    auto = ""
    if auto_ticker:
        at = str(auto_ticker).upper()
        auto = (f"window.addEventListener('load',function(){{pop.style.left='50%';"
                f"pop.style.top='40px';pop.style.transform='translateX(-50%)';"
                f"openPop();pinned=true;showChart('{at}');}});")
    kospi_daily = _fetch_kospi_daily() if include_kospi and kr_tickers else {}
    track_dates = track_dates or {}
    js = (POPUP_JS
          .replace("__DAILY__",  json.dumps(daily,  ensure_ascii=False, separators=(",", ":")))
          .replace("__WEEKLY__", json.dumps(weekly, ensure_ascii=False, separators=(",", ":")))
          .replace("__META__", json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
          .replace("__KOSPI_D__", json.dumps(kospi_daily, ensure_ascii=False, separators=(",", ":")))
          .replace("__TRACK_D__", json.dumps(track_dates, ensure_ascii=False, separators=(",", ":")))
          .replace("__TRIGGER_ATTR__", trigger_attr)
          .replace("__AUTO_OPEN__", auto))
    return ("<style>" + POPUP_CSS + "</style>\n" + POPUP_HTML
            + '\n<script src="lib/lightweight-charts.standalone.production.js"></script>\n'
            + "<script>\n(function(){\n" + js + "\n})();\n</script>")


def move_kr_trigger_to_name(page_html, attr="data-code"):
    """차트 hover 트리거를 '티커 셀'에서 바로 뒤 '종목명 셀'로 이동.

    <td ... attr="CODE" data-name="NAME">TICKER</td><td ...>NAME</td>
      → <td ...>TICKER</td><td ... attr="CODE" data-name="NAME" ...>NAME</td>

    v4 팝업 트리거 셀렉터([attr])와 종목코드 수집 정규식은 attr 위치와
    무관하므로, 호출 순서에 상관없이 안전하다. 한국 종목은 종목명에
    마우스를 올려야 차트가 뜨도록 하기 위함(미국 종목/티커 셀은 미적용).
    """
    import re as _re_reloc
    pat = _re_reloc.compile(
        r'<td((?:(?!</td>).)*?)\s' + _re_reloc.escape(attr) + r'="([^"]*)"'
        r'((?:(?!</td>).)*?)>((?:(?!</td>).)*?)</td>(\s*)<td\b',
        _re_reloc.S)

    def _repl(m):
        pre, code, post, text, ws = m.groups()
        rest = pre + post
        nm = ''
        nmm = _re_reloc.search(r'\s+data-name="([^"]*)"', rest)
        if nmm:
            nm = ' data-name="%s"' % nmm.group(1)
            rest = rest[:nmm.start()] + rest[nmm.end():]
        first = '<td' + rest + '>' + text + '</td>'
        inject = '<td ' + attr + '="' + code + '"' + nm + ' style="cursor:pointer" '
        return first + ws + inject

    return pat.sub(_repl, page_html)


def build_test_html(tickers, auto_ticker):
    block = build_chart_popup(tickers, auto_ticker=auto_ticker)
    rows = "".join(
        f'<tr><td class="chart-trigger" data-ticker="{t}" style="cursor:pointer;">{t}</td>'
        f'<td>미국주식 일/주봉 V4 테스트</td></tr>' for t in tickers)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>V4 US 일/주봉 차트 테스트</title>
<style>body{{font-family:'Malgun Gothic',sans-serif;margin:24px;color:#2c3e50;background:#f4f7f6;}}
h3{{margin:0 0 6px;}} p{{color:#666;font-size:13px;margin:0 0 14px;}}
table{{border-collapse:collapse;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.08);}}
td{{border-bottom:1px solid #eee;padding:8px 16px;font-size:14px;}}
td.chart-trigger{{font-weight:700;color:#2980b9;}}</style>
</head><body>
<h3>V4 · 미국 일봉/주봉 인터랙티브 차트 (캐시 오프라인 · 새 다운로드 없음)</h3>
<p>티커에 마우스를 올리면 팝업 — 왼쪽 일봉(추세배경) / 오른쪽 주봉. 로드시 {auto_ticker} 자동표시. s/d 키로 위·아래 이동.</p>
<table><tbody>{rows}</tbody></table>
{block}
</body></html>"""


if __name__ == "__main__":
    tickers = ["NVDA", "AAPL", "MSFT", "TSLA", "AMD", "QQQ"]
    out_path = os.path.join(BASE_DIR, "chart_v4_test.html")
    html = build_test_html(tickers, auto_ticker="NVDA")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [chart_popup_v4] 작성 완료 → {out_path}  ({os.path.getsize(out_path)//1024} KB)")
    try:
        webbrowser.open("file:///" + out_path.replace("\\", "/"))
    except Exception:
        pass
