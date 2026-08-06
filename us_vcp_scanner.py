from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError as exc:
    raise SystemExit(
        "yfinance가 설치되어 있지 않습니다.\n"
        "설치: pip install yfinance pandas numpy"
    ) from exc


# ══════════════════════════════════════════════════════════════
#  경로 설정
# ══════════════════════════════════════════════════════════════
INPUT_CSV  = r"D:\py\korea\us.csv"
OUTPUT_DIR = r"D:\py"

# ══════════════════════════════════════════════════════════════
#  파라미터
# ══════════════════════════════════════════════════════════════

# ── 데이터 수집 ────────────────────────────────────────────────
FETCH_PERIOD        = "2y"
MIN_HISTORY_DAYS    = 200

# ── 1차 필터: 고점 위치 ────────────────────────────────────────
LOOKBACK_WEEKS      = 52
PEAK_MIN_WEEKS_AGO  = 8          # 2개월 (이전 12주=3개월 → 짧은 베이스 재돌파 포착 위해 완화)
PEAK_MAX_WEEKS_AGO  = 26         # 6개월

# ── 2차 필터: 현재가 위치 ──────────────────────────────────────
PRICE_NEAR_HIGH_PCT = 0.10       # ±10%

# ── 주봉 Zigzag 수축 분석 ──────────────────────────────────────
ZIGZAG_THRESHOLD    = 0.05       # 5% 반전
CONTRACTION_MIN     = 2
CONTRACTION_MAX     = 6
MIN_CONTRACTION_PCT = 0.05       # 최소 5% 낙폭

# 수축 크기 감소
CONTRACTION_TOLERANCE = 1.20
MAX_VIOLATIONS        = 1

# 기간 단축
DURATION_DECREASE_CHECK = True
DURATION_TOLERANCE      = 1.30
MAX_DURATION_VIOLATIONS = 1

# ── 피벗 박스 (일봉) ───────────────────────────────────────────
PIVOT_WINDOW_MIN    = 3
PIVOT_WINDOW_MAX    = 15
PIVOT_BOX_MAX_WIDTH = 0.08

# ── 진입 상태 ─────────────────────────────────────────────────
PRE_BREAKOUT_MIN    = -5.0
PRE_BREAKOUT_MAX    =  0.0
BREAKOUT_MAX        =  3.0
VOLUME_SURGE_RATIO  =  1.50

# 피벗 앵커링: True면 피벗을 '마지막 수축 고점'(고정)에 앵커.
# False면 기존 방식(최근 일봉 박스 고점 — 매일 따라 올라감). 백테스트 A/B용 토글.
USE_ANCHORED_PIVOT  = True

# ── 거래량 감소 ────────────────────────────────────────────────
VOLUME_DRYUP_RATIO  = 0.90


# ══════════════════════════════════════════════════════════════
#  데이터클래스
# ══════════════════════════════════════════════════════════════
@dataclass
class Filter1Result:
    ticker: str
    peak_high: float
    peak_week: pd.Timestamp
    peak_weeks_ago: int
    base_weekly: pd.DataFrame


@dataclass
class Filter2Result:
    ticker: str
    peak_high: float
    peak_week: pd.Timestamp
    peak_weeks_ago: int
    base_high: float
    close_now: float
    dist_pct: float
    base_weekly: pd.DataFrame
    full_daily: pd.DataFrame


@dataclass
class SwingContraction:
    high_price: float
    low_price: float
    contraction_pct: float
    duration_weeks: int
    high_date: pd.Timestamp
    low_date: pd.Timestamp


@dataclass
class VCPResult:
    ticker: str
    contractions: List[SwingContraction]
    is_size_decreasing: bool
    is_duration_decreasing: bool
    last_is_tightest: bool
    size_violations: int
    duration_violations: int
    vcp_score: float
    volume_dryup: bool


@dataclass
class FinalResult:
    ticker: str
    status: str
    close_now: float
    pivot: float
    pivot_window_days: int
    pivot_box_width_pct: float
    pivot_dist_pct: float
    volume_ratio: float
    vcp_score: float
    contraction_summary: str
    duration_summary: str
    peak_week: pd.Timestamp
    peak_weeks_ago: int


# ══════════════════════════════════════════════════════════════
#  유틸
# ══════════════════════════════════════════════════════════════
def ensure_output_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def read_tickers(csv_path: str) -> List[str]:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"입력파일 없음: {csv_path}")
    raw = pd.read_csv(csv_path, dtype=str)
    if raw.empty:
        raise ValueError("입력파일 비어 있음")

    candidate_cols = ["ticker", "Ticker", "TICKER", "symbol", "Symbol", "SYMBOL"]
    col = next((c for c in candidate_cols if c in raw.columns), raw.columns[0])

    tickers = (
        raw[col].astype(str).str.strip().str.upper()
        .replace({"": np.nan, "NAN": np.nan, "NONE": np.nan})
        .dropna().tolist()
    )
    seen, deduped = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    if not deduped:
        raise ValueError("유효한 티커 없음")
    return deduped


# ══════════════════════════════════════════════════════════════
#  데이터 수집
# ══════════════════════════════════════════════════════════════
def download_daily_data(tickers: Sequence[str]) -> Dict[str, pd.DataFrame]:
    data = yf.download(
        tickers=list(tickers),
        period=FETCH_PERIOD,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=False,  # 최신 yfinance에서 threads=True 불안정
    )
    results: Dict[str, pd.DataFrame] = {}
    if len(tickers) == 1:
        results[tickers[0]] = _normalize(data)
        return results
    for ticker in tickers:
        if ticker not in data.columns.get_level_values(0):
            continue
        results[ticker] = _normalize(data[ticker].copy())
    return results


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.columns = [str(c).title() for c in df.columns]
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame()
    df = df[needed].copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().dropna(subset=["Open", "High", "Low", "Close"])
    return df[(df["Close"] > 0) & (df["High"] > 0) & (df["Low"] > 0)]


def daily_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    w = pd.DataFrame()
    w["Open"]   = df["Open"].resample("W-FRI").first()
    w["High"]   = df["High"].resample("W-FRI").max()
    w["Low"]    = df["Low"].resample("W-FRI").min()
    w["Close"]  = df["Close"].resample("W-FRI").last()
    w["Volume"] = df["Volume"].resample("W-FRI").sum()
    w = w.dropna()
    # 당주 미완성 봉 제거: 마지막 주의 금요일이 아직 안 됐으면 제외
    today = pd.Timestamp.today().normalize()
    if len(w) > 0:
        last_week_end = w.index[-1]          # W-FRI 기준 금요일
        if today < last_week_end:            # 오늘이 그 금요일 이전 → 불완전 주
            w = w.iloc[:-1]
    return w


# ══════════════════════════════════════════════════════════════
#  1차 필터
# ══════════════════════════════════════════════════════════════
def filter1_peak_location(ticker: str, weekly: pd.DataFrame) -> Optional[Filter1Result]:
    if len(weekly) < LOOKBACK_WEEKS:
        return None
    recent_w   = weekly.iloc[-LOOKBACK_WEEKS:].copy()
    peak_high  = float(recent_w["High"].max())
    peak_week  = recent_w["High"].idxmax()
    peak_pos   = recent_w.index.get_loc(peak_week)
    weeks_ago  = len(recent_w) - 1 - peak_pos
    if not (PEAK_MIN_WEEKS_AGO <= weeks_ago <= PEAK_MAX_WEEKS_AGO):
        return None
    base_weekly = weekly.loc[peak_week:].copy()
    if len(base_weekly) < PEAK_MIN_WEEKS_AGO:
        return None
    return Filter1Result(
        ticker=ticker,
        peak_high=peak_high,
        peak_week=peak_week,
        peak_weeks_ago=weeks_ago,
        base_weekly=base_weekly,
    )


# ══════════════════════════════════════════════════════════════
#  2차 필터
# ══════════════════════════════════════════════════════════════
def filter2_price_near_high(
    ticker: str, weekly: pd.DataFrame, daily: pd.DataFrame, f1: Filter1Result
) -> Optional[Filter2Result]:
    base_high = float(f1.base_weekly["High"].max())
    if base_high <= 0:
        return None
    close_now = float(daily["Close"].iloc[-1])
    if close_now <= 0:
        return None
    dist_pct  = (close_now / base_high - 1.0) * 100.0
    if abs(dist_pct) > PRICE_NEAR_HIGH_PCT * 100.0:
        return None
    return Filter2Result(
        ticker=ticker,
        peak_high=f1.peak_high,
        peak_week=f1.peak_week,
        peak_weeks_ago=f1.peak_weeks_ago,
        base_high=base_high,
        close_now=close_now,
        dist_pct=dist_pct,
        base_weekly=f1.base_weekly,
        full_daily=daily,
    )


# ══════════════════════════════════════════════════════════════
#  주봉 Zigzag
# ══════════════════════════════════════════════════════════════
def compute_weekly_zigzag(weekly: pd.DataFrame) -> List[Tuple[pd.Timestamp, float, str]]:
    highs = weekly["High"].to_numpy(dtype=float)
    lows  = weekly["Low"].to_numpy(dtype=float)
    dates = weekly.index.tolist()
    n = len(weekly)
    if n < 4:
        return []

    pivots: List[Tuple[pd.Timestamp, float, str]] = []
    direction  = None
    last_price = (highs[0] + lows[0]) / 2
    last_idx   = 0

    for i in range(1, n):
        h, l = highs[i], lows[i]
        if direction is None:
            if h / last_price - 1 >= ZIGZAG_THRESHOLD:
                direction = "up"; last_price = h; last_idx = i
            elif last_price / l - 1 >= ZIGZAG_THRESHOLD:
                direction = "down"; last_price = l; last_idx = i
        elif direction == "up":
            if h >= last_price:
                last_price = h; last_idx = i
            elif last_price / l - 1 >= ZIGZAG_THRESHOLD:
                pivots.append((dates[last_idx], last_price, "H"))
                direction = "down"; last_price = l; last_idx = i
        else:
            if l <= last_price:
                last_price = l; last_idx = i
            elif h / last_price - 1 >= ZIGZAG_THRESHOLD:
                pivots.append((dates[last_idx], last_price, "L"))
                direction = "up"; last_price = h; last_idx = i

    if direction == "up":
        pivots.append((dates[last_idx], last_price, "H"))
    elif direction == "down":
        pivots.append((dates[last_idx], last_price, "L"))
    return pivots


# ══════════════════════════════════════════════════════════════
#  VCP 수축 분석
# ══════════════════════════════════════════════════════════════
def analyze_vcp(ticker: str, f2: Filter2Result) -> Optional[VCPResult]:
    weekly = f2.base_weekly
    pivots = compute_weekly_zigzag(weekly)
    if len(pivots) < 4:
        return None

    contractions: List[SwingContraction] = []
    i = 0
    while i < len(pivots) - 1:
        if pivots[i][2] == "H" and pivots[i + 1][2] == "L":
            h_date, h_price = pivots[i][0], pivots[i][1]
            l_date, l_price = pivots[i + 1][0], pivots[i + 1][1]
            pct = (h_price - l_price) / h_price * 100.0
            if pct >= MIN_CONTRACTION_PCT * 100.0:
                # get_loc 실패 시 0 대신 None으로 처리 → duration 의미없는 1 방지
                h_idx = weekly.index.get_loc(h_date) if h_date in weekly.index else None
                l_idx = weekly.index.get_loc(l_date) if l_date in weekly.index else None
                if h_idx is None or l_idx is None:
                    i += 2
                    continue
                duration = max(1, abs(l_idx - h_idx))
                contractions.append(SwingContraction(
                    high_price=h_price, low_price=l_price,
                    contraction_pct=round(pct, 2), duration_weeks=duration,
                    high_date=h_date, low_date=l_date,
                ))
            i += 2
        else:
            i += 1

    if not (CONTRACTION_MIN <= len(contractions) <= CONTRACTION_MAX):
        return None

    sizes     = [c.contraction_pct for c in contractions]
    durations = [c.duration_weeks   for c in contractions]

    # 조건 1: 크기 감소
    size_violations = sum(
        1 for j in range(1, len(sizes))
        if sizes[j] > sizes[j - 1] * CONTRACTION_TOLERANCE
    )
    if size_violations > MAX_VIOLATIONS:
        return None
    if sizes[-1] >= sizes[0]:
        return None

    # 조건 2: 마지막이 가장 타이트
    if sizes[-1] != min(sizes):
        return None

    # 조건 3: 기간 감소
    duration_violations = 0
    if DURATION_DECREASE_CHECK and len(durations) >= 2:
        duration_violations = sum(
            1 for j in range(1, len(durations))
            if durations[j] > durations[j - 1] * DURATION_TOLERANCE
        )
        if duration_violations > MAX_DURATION_VIOLATIONS:
            return None
    is_duration_decreasing = (durations[-1] < durations[0]) if len(durations) >= 2 else True

    # 거래량 감소
    half = max(2, len(weekly) // 2)
    vol_first  = float(weekly["Volume"].iloc[:half].mean())
    vol_second = float(weekly["Volume"].iloc[half:].mean())
    volume_dryup = (vol_second <= vol_first * VOLUME_DRYUP_RATIO) if vol_first > 0 else False

    # 점수
    score = 1.0
    score -= 0.15 * max(0, abs(len(contractions) - 3))
    score -= 0.25 * size_violations
    score -= 0.15 * duration_violations
    if all(sizes[j] < sizes[j-1] for j in range(1, len(sizes))):
        score += 0.20
    if len(durations) >= 2 and all(durations[j] < durations[j-1] for j in range(1, len(durations))):
        score += 0.15
    if volume_dryup:
        score += 0.15
    if sizes[-1] < 5.0:
        score += 0.10

    return VCPResult(
        ticker=ticker,
        contractions=contractions,
        is_size_decreasing=True,
        is_duration_decreasing=is_duration_decreasing,
        last_is_tightest=True,
        size_violations=size_violations,
        duration_violations=duration_violations,
        vcp_score=round(max(0.0, min(2.0, score)), 3),
        volume_dryup=volume_dryup,
    )


# ══════════════════════════════════════════════════════════════
#  피벗 박스 (일봉)
# ══════════════════════════════════════════════════════════════
def find_pivot_box(daily: pd.DataFrame) -> Optional[Tuple[float, int, float]]:
    if len(daily) < PIVOT_WINDOW_MIN + 1:
        return None
    max_window = min(PIVOT_WINDOW_MAX, len(daily) - 1)
    for window in range(PIVOT_WINDOW_MIN, max_window + 1):
        box   = daily.iloc[-window:]
        pivot = float(box["High"].max())
        b_low = float(box["Low"].min())
        if pivot <= 0:
            continue
        width = (pivot - b_low) / pivot
        if width <= PIVOT_BOX_MAX_WIDTH:
            return pivot, window, round(width * 100.0, 2)
    return None


# ══════════════════════════════════════════════════════════════
#  진입 분류
# ══════════════════════════════════════════════════════════════
def classify_entry(ticker: str, f2: Filter2Result, vcp: VCPResult) -> Optional[FinalResult]:
    daily = f2.full_daily
    search_df  = daily.iloc[-30:].copy() if len(daily) >= 30 else daily.copy()
    box_info   = find_pivot_box(search_df)

    if USE_ANCHORED_PIVOT:
        # 피벗을 '마지막 수축 고점'에 고정(앵커). 기존 일봉 박스 피벗은 매일 최근
        # 고가를 따라 올라가 종가가 영원히 피벗 밑(PRE_BREAKOUT 고착)에 머물러
        # BREAKOUT_TODAY 전환이 안 됨 → 베이스 저항(마지막 수축 고점)에 고정해 해결.
        pivot = float(vcp.contractions[-1].high_price)
        if box_info is not None:
            _, pivot_window_days, box_width_pct = box_info
        else:
            pivot_window_days, box_width_pct = 0, round(vcp.contractions[-1].contraction_pct, 2)
    else:
        if box_info is None:
            return None
        pivot, pivot_window_days, box_width_pct = box_info

    close_now    = float(daily["Close"].iloc[-1])
    volume_now   = float(daily["Volume"].iloc[-1])
    avg_vol_20   = float(daily["Volume"].tail(20).mean()) if len(daily) >= 20 else float(daily["Volume"].mean())
    volume_ratio = volume_now / avg_vol_20 if avg_vol_20 > 0 else 0.0
    pivot_dist   = (close_now / pivot - 1.0) * 100.0

    EXTENDED_MAX = 7.0   # 피벗 돌파 후 +7% 이내까지 추적

    status: Optional[str] = None
    if PRE_BREAKOUT_MIN <= pivot_dist < PRE_BREAKOUT_MAX:
        status = "PRE_BREAKOUT"
    elif 0.0 < pivot_dist <= BREAKOUT_MAX and close_now > pivot and volume_ratio >= VOLUME_SURGE_RATIO:
        # pivot_dist > 0 으로 변경 → 정확히 pivot과 같을 때는 PRE/TODAY 어느 쪽도 아님
        status = "BREAKOUT_TODAY"
    elif 0.0 < pivot_dist <= BREAKOUT_MAX and close_now > pivot:
        status = "BREAKOUT_WEAK"   # 돌파했으나 거래량 미달
    elif BREAKOUT_MAX < pivot_dist <= EXTENDED_MAX:
        status = "EXTENDED"        # 돌파 후 추세 중 (한국 버전과 동일)

    if status is None:
        return None

    sizes     = [c.contraction_pct for c in vcp.contractions]
    durations = [c.duration_weeks   for c in vcp.contractions]

    return FinalResult(
        ticker=ticker,
        status=status,
        close_now=round(close_now, 4),
        pivot=round(pivot, 4),
        pivot_window_days=pivot_window_days,
        pivot_box_width_pct=box_width_pct,
        pivot_dist_pct=round(pivot_dist, 2),
        volume_ratio=round(volume_ratio, 2),
        vcp_score=vcp.vcp_score,
        contraction_summary=" → ".join(f"{s:.1f}%" for s in sizes),
        duration_summary=" → ".join(f"{d}w" for d in durations),
        peak_week=f2.peak_week,
        peak_weeks_ago=f2.peak_weeks_ago,
    )


# ══════════════════════════════════════════════════════════════
#  저장
# ══════════════════════════════════════════════════════════════
def save_outputs(output_dir: str, vcp_rows: List[dict], final_rows: List[dict]) -> dict:
    ensure_output_dir(output_dir)
    paths = {
        "vcp_csv":   os.path.join(output_dir, "us_vcp2_candidates.csv"),
        "vcp_txt":   os.path.join(output_dir, "us_vcp2_candidates.txt"),
        "final_csv": os.path.join(output_dir, "us_vcp2_final.csv"),
        "final_txt": os.path.join(output_dir, "us_vcp2_final.txt"),
    }
    with open(paths["vcp_txt"], "w", encoding="utf-8") as f:
        for r in vcp_rows:
            f.write(f"{r['ticker']}\n")
    with open(paths["final_txt"], "w", encoding="utf-8") as f:
        for r in final_rows:
            f.write(f"{r['ticker']}\n")
    if vcp_rows:
        pd.DataFrame(vcp_rows).to_csv(paths["vcp_csv"], index=False, encoding="utf-8-sig")
    if final_rows:
        pd.DataFrame(final_rows).to_csv(paths["final_csv"], index=False, encoding="utf-8-sig")
    return paths


# ══════════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════════
def run_scan(input_csv: str = INPUT_CSV, output_dir: str = OUTPUT_DIR) -> None:
    tickers = read_tickers(input_csv)
    print(f"입력 티커: {len(tickers)}개")

    data_map = download_daily_data(tickers)
    print(f"다운로드 완료: {sum(1 for v in data_map.values() if not v.empty)}개\n")

    skip_nodata = skip_hist = skip_f1 = skip_f2 = skip_vcp = 0
    vcp_rows: List[dict]   = []
    final_rows: List[dict] = []

    for idx, ticker in enumerate(tickers, 1):
        daily = data_map.get(ticker)
        if daily is None or daily.empty:
            skip_nodata += 1
            continue
        if len(daily) < MIN_HISTORY_DAYS:
            skip_hist += 1
            continue

        weekly = daily_to_weekly(daily)
        if len(weekly) < LOOKBACK_WEEKS:
            skip_hist += 1
            continue

        f1 = filter1_peak_location(ticker, weekly)
        if f1 is None:
            skip_f1 += 1
            continue

        f2 = filter2_price_near_high(ticker, weekly, daily, f1)
        if f2 is None:
            skip_f2 += 1
            continue

        vcp = analyze_vcp(ticker, f2)
        if vcp is None:
            skip_vcp += 1
            continue

        sizes     = [c.contraction_pct for c in vcp.contractions]
        durations = [c.duration_weeks   for c in vcp.contractions]

        vcp_rows.append({
            "ticker":          ticker,
            "peak_week":       f2.peak_week.strftime("%Y-%m-%d"),
            "peak_weeks_ago":  f2.peak_weeks_ago,
            "base_high":       round(f2.base_high, 4),
            "close_now":       round(f2.close_now, 4),
            "dist_pct":        round(f2.dist_pct, 2),
            "contractions":    " → ".join(f"{s:.1f}%" for s in sizes),
            "durations_weeks": " → ".join(f"{d}w" for d in durations),
            "contraction_cnt": len(vcp.contractions),
            "vcp_score":       vcp.vcp_score,
            "size_decrease":   vcp.is_size_decreasing,
            "dur_decrease":    vcp.is_duration_decreasing,
            "volume_dryup":    vcp.volume_dryup,
        })

        final = classify_entry(ticker, f2, vcp)
        if final is None:
            continue

        final_rows.append({
            "ticker":            final.ticker,
            "status":            final.status,
            "close_now":         final.close_now,
            "pivot":             final.pivot,
            "pivot_window_days": final.pivot_window_days,
            "pivot_box_pct":     final.pivot_box_width_pct,
            "pivot_dist_pct":    final.pivot_dist_pct,
            "volume_ratio":      final.volume_ratio,
            "vcp_score":         final.vcp_score,
            "contractions":      final.contraction_summary,
            "durations":         final.duration_summary,
            "peak_week":         final.peak_week.strftime("%Y-%m-%d"),
            "peak_weeks_ago":    final.peak_weeks_ago,
        })

        if idx % 50 == 0:
            print(f"  진행: {idx}/{len(tickers)}")

    status_order = {"BREAKOUT_TODAY": 0, "PRE_BREAKOUT": 1, "BREAKOUT_WEAK": 2, "EXTENDED": 3}
    final_rows.sort(key=lambda x: (
        status_order.get(x["status"], 9),
        -x["vcp_score"],
        abs(x["pivot_dist_pct"]),
    ))

    paths = save_outputs(output_dir, vcp_rows, final_rows)

    print("\n" + "=" * 70)
    print("[단계별 통계]")
    print(f"  입력:                {len(tickers):>5}개")
    print(f"  데이터 없음/부족:    {skip_nodata + skip_hist:>5}개")
    print(f"  1차 탈락(고점위치):  {skip_f1:>5}개  ← 12~26주 전 고점 없음")
    print(f"  2차 탈락(현재가):    {skip_f2:>5}개  ← 베이스 고점 ±10% 밖")
    print(f"  VCP 탈락:            {skip_vcp:>5}개  ← 수축 감소 패턴 미충족")
    print(f"  VCP 통과:            {len(vcp_rows):>5}개")
    print(f"  최종(피벗):          {len(final_rows):>5}개")
    print("=" * 70)

    if final_rows:
        print("\n[최종 VCP 종목] — 돌파 직전 / 직후만")
        print(f"{'티커':>8}  {'상태':<16} {'현재가':>10} {'피벗':>10} "
              f"{'피벗거리%':>9} {'거래량비':>7} {'점수':>6}  수축패턴  /  기간")
        print("-" * 110)
        for r in final_rows:
            print(
                f"{r['ticker']:>8}  {r['status']:<16} "
                f"{r['close_now']:>10.2f} {r['pivot']:>10.2f} "
                f"{r['pivot_dist_pct']:>+9.2f} {r['volume_ratio']:>7.2f} "
                f"{r['vcp_score']:>6.3f}  "
                f"{r['contractions']}  /  {r['durations']}"
            )
    else:
        print("\n최종 통과 종목 없음.")

    print(f"\n저장:")
    print(f"  VCP 후보: {paths['vcp_csv']}")
    print(f"  최종:     {paths['final_csv']}")


if __name__ == "__main__":
    run_scan()
