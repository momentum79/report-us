#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
etf_history_update.py
─────────────────────
Step 1: 오늘 보유 티커 → holdings_daily*.csv 기록 (같은 날 재실행 idempotent)
Step 2: holdings CSV 집계 → weekly/monthly top CSV 6개 갱신

실행 위치 : D:\\py\\report-us\\
소스 파일  :
  D:\\py\\buy_list_total.txt         → global top5
  D:\\py\\buy_list.txt               → KR top3
  D:\\py\\report-us\\report_us_etf.txt → US top3 (=== 최종 리스트 섹션)
"""

import csv
import io
import re
import pathlib
from datetime import date, timedelta
from collections import Counter

# ── 경로 ────────────────────────────────────────────────────────
BASE    = pathlib.Path(__file__).resolve().parent   # D:\py\report-us
PY      = BASE.parent                               # D:\py
HISTORY = BASE / "etf_history"

SRC_TOTAL  = PY  / "buy_list_total.txt"
SRC_KR     = PY  / "buy_list.txt"
SRC_US_ETF = BASE / "report_us_etf.txt"

H_GLOBAL = HISTORY / "holdings_daily.csv"
H_KR     = HISTORY / "holdings_daily_kr.csv"
H_US     = HISTORY / "holdings_daily_usonly.csv"

W_GLOBAL = HISTORY / "weekly_top5_global.csv"
M_GLOBAL = HISTORY / "monthly_top5_global.csv"
W_KR     = HISTORY / "weekly_top3_kr.csv"
M_KR     = HISTORY / "monthly_top3_kr.csv"
W_US     = HISTORY / "weekly_top3_usonly.csv"
M_US     = HISTORY / "monthly_top3_usonly.csv"

# ── KR ETF 이름 ↔ 티커 매핑 ────────────────────────────────────
_KR_ETFS = [
    '091160', '091180', '305720', '117460', '244580', '091170',
    '102970', '117680', '117700', '139230', '228790', '495050',
    '069500', '229200', '487230', '449450', '475050', '371160',
    '455850', '0051G0', '0038A0', '0048K0', '0023A0', '195930',
    '377990', '411060', '478150', '453810', '446770', '434730',
    '469070', '449180', '449190', '241180', '147970', '325020',
]
_KR_NAMES = [
    '반도체', '자동차', '이차전', '에너지', '바이오', '은행주',
    '증권주', '철강주', '건설주', '조선주', '화장품', '밸류업',
    '코스피', '코스닥', '전력인', '방산주', 'K팝',   '항셈테',
    '반소부', '에셈알', '미로봇', '중로봇', '양자컴', '유로스',
    '신재생', '금현물', '우주방', '인디아', '톱반도', '원자력',
    'ai로봇', '에센피', '나스닥', '니케이', '티모멘', '케모멘',
]
KR_T2N = dict(zip(_KR_ETFS, _KR_NAMES))   # ticker → 이름


# ── 포맷 변환 ───────────────────────────────────────────────────
def fmt_kr(t: str) -> str:
    """KR 티커 → '이름(티커)'"""
    return f"{KR_T2N.get(t, t)}({t})"

def fmt_global(tickers: list) -> list:
    """Global 표시: KR은 '이름(티커)', US는 그대로"""
    return [fmt_kr(t) if t in KR_T2N else t for t in tickers]

def fmt_kr_list(tickers: list) -> list:
    """KR 표시: 전부 '이름(티커)'"""
    return [fmt_kr(t) for t in tickers]


# ── 날짜 레이블 ────────────────────────────────────────────────
def week_label(d: date) -> str:
    return f"{d.year}.{d.month}월{(d.day - 1) // 7 + 1}주"

def month_label(d: date) -> str:
    return f"{d.year}.{d.month:02d}"

def week_date_set(d: date) -> set:
    """이번 주 월요일 ~ 오늘까지 YYYY-MM-DD set"""
    mon = d - timedelta(days=d.weekday())
    return {(mon + timedelta(days=i)).strftime('%Y-%m-%d')
            for i in range(d.weekday() + 1)}


# ── 소스 파일 파싱 ─────────────────────────────────────────────
def read_buy_list(path: pathlib.Path, n: int) -> list:
    """buy_list*.txt → 상위 n 티커 (한 줄 = 한 티커)"""
    if not path.exists():
        print(f"  [WARN] {path} 없음")
        return []
    tickers = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        t = line.strip()
        if t and not t.startswith('#'):
            tickers.append(t)
    return tickers[:n]


def read_us_etf_top(n: int) -> list:
    """report_us_etf.txt의 '=== 최종 리스트' 섹션 → 상위 n US 티커"""
    if not SRC_US_ETF.exists():
        print(f"  [WARN] {SRC_US_ETF} 없음")
        return []
    txt = SRC_US_ETF.read_text(encoding='utf-8', errors='replace')

    # '===' 로 시작하는 줄 중 마지막 것 = 최종 리스트 섹션
    matches = list(re.finditer(r'(?m)^===', txt))
    if not matches:
        return []
    idx = matches[-1].start()

    tickers = []
    for line in txt[idx:].splitlines()[2:]:   # [0]=헤더줄, [1]=컬럼줄, [2~]=데이터
        parts = line.strip().split()
        if not parts:
            break
        raw = parts[0].rstrip('*').strip()
        if not re.match(r'^[A-Z]{1,5}$', raw):
            break
        tickers.append(raw)
        if len(tickers) >= n:
            break
    return tickers


# ── CSV 읽기/쓰기 (2-row-pair 형식) ───────────────────────────
def read_csv_rows(path: pathlib.Path) -> list:
    text = path.read_text(encoding='utf-8-sig')
    return list(csv.reader(io.StringIO(text)))

def write_csv_rows(path: pathlib.Path, rows: list):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(rows)


# ── 주간/월간 CSV 업데이트 ─────────────────────────────────────
def _month_half_key(label: str) -> str:
    """'2026.04' → '2026H1',  '2026.07' → '2026H2'"""
    m = re.match(r'(\d{4})\.(\d{2})', label)
    if m:
        return f"{m.group(1)}{'H1' if int(m.group(2)) <= 6 else 'H2'}"
    return ''

def update_period_csv(path: pathlib.Path, label: str,
                      tickers: list, is_monthly: bool = False):
    """
    2-row-pair 형식 CSV 에서 해당 주/월 열을 갱신 (없으면 추가).
    - 주간(is_monthly=False): 같은 달 블록 마지막 열에 추가 / 새 달 → 맨 앞 블록 신설
    - 월간(is_monthly=True ): 같은 반기 블록 마지막 열에 추가 / 새 반기 → 맨 뒤 블록 신설
    """
    if not tickers:
        return
    data_str = '\n'.join(tickers)
    rows = read_csv_rows(path)

    if is_monthly:
        half_key = _month_half_key(label)
        def same_block(lrow):
            return any(_month_half_key(l.strip()) == half_key for l in lrow if l.strip())
    else:
        pm = re.match(r'(\d{4}\.\d+월)', label)
        month_pfx = pm.group(1) if pm else ''
        def same_block(lrow):
            return any(l.strip().startswith(month_pfx) for l in lrow if l.strip())

    updated = False
    for i in range(0, len(rows) - 1, 2):
        lrow = [l.strip() for l in rows[i]]

        if label in lrow:
            # ① 이미 같은 레이블 존재 → 덮어쓰기
            j = lrow.index(label)
            drow = list(rows[i + 1])
            while len(drow) <= j:
                drow.append('')
            drow[j] = data_str
            rows[i + 1] = drow
            updated = True
            break

        if same_block(lrow):
            # ② 같은 달/반기 블록 → 오른쪽 컬럼 추가
            rows[i]     = list(rows[i])     + [label]
            rows[i + 1] = list(rows[i + 1]) + [data_str]
            updated = True
            break

    if not updated:
        if is_monthly:
            rows = rows + [[label], [data_str]]   # monthly: 맨 뒤 신설
        else:
            rows = [[label], [data_str]] + rows   # weekly : 맨 앞 신설

    write_csv_rows(path, rows)
    kind = "월간" if is_monthly else "주간"
    print(f"  [{kind}] {path.name}  {label}: {tickers}")


# ── Holdings CSV 업데이트 ──────────────────────────────────────
def update_holdings(path: pathlib.Path, today_str: str, tickers: list):
    """오늘 날짜 행 삭제 후 재삽입 (idempotent). 기존 컬럼 구조 유지."""
    if not tickers:
        return
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [r for r in reader if r and r[0] != today_str]

    ncol    = len(header)
    is_us   = 'usonly' in path.name
    rank_col = 2 if is_us else 3   # usonly: [date,ticker,rank,...] / 나머지: [date,ticker,industry,rank,...]

    for rank, t in enumerate(tickers, 1):
        row = [''] * ncol
        row[0] = today_str
        row[1] = t
        if not is_us and ncol > 2:
            # industry 컬럼: KR은 한글명, US는 티커명
            row[2] = KR_T2N.get(t, t)
        if rank_col < ncol:
            row[rank_col] = str(rank)
        rows.append(row)

    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    print(f"  [Holdings] {path.name}  {today_str}: {tickers}")


# ── 티커 빈도 집계 ─────────────────────────────────────────────
def aggregate_top(path: pathlib.Path, dates_or_prefix, n: int,
                  by_month: bool = False) -> list:
    """
    by_month=False : dates_or_prefix = set{'2026-04-19', ...}
    by_month=True  : dates_or_prefix = '2026-04-' (prefix str)
    """
    counter = Counter()
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                d = row.get('date', '')
                hit = (d.startswith(dates_or_prefix) if by_month
                       else d in dates_or_prefix)
                if hit:
                    t = row.get('ticker', '').strip()
                    if t:
                        counter[t] += 1
    except Exception as e:
        print(f"  [WARN] 집계 오류 ({path.name}): {e}")
    return [t for t, _ in counter.most_common(n)]


# ── 메인 ───────────────────────────────────────────────────────
def main():
    today     = date.today()
    ts        = today.strftime('%Y-%m-%d')

    # ── 주말 체크: 토/일은 스킵 (금요일 데이터 유지) ─────────
    DOW = ['월', '화', '수', '목', '금', '토', '일']
    if today.weekday() >= 5:
        print(f"\n  ℹ️  오늘은 {DOW[today.weekday()]}요일({ts}) — 주말은 스킵합니다.")
        print(f"  ✅ 금요일 데이터 유지\n")
        return

    wl        = week_label(today)
    ml        = month_label(today)
    wd        = week_date_set(today)
    month_pfx = f"{today.year}-{today.month:02d}-"

    print(f"\n{'='*58}")
    print(f"  ETF History Update  {ts}  ({DOW[today.weekday()]})")
    print(f"  주간 레이블: {wl}   월간 레이블: {ml}")
    print(f"{'='*58}\n")

    # ── Step 1: 오늘 보유 읽기 ───────────────────────────────
    g5 = read_buy_list(SRC_TOTAL, 5)
    k3 = read_buy_list(SRC_KR,    3)
    u3 = read_us_etf_top(3)
    print(f"[소스 읽기]")
    print(f"  Global top5 : {g5}")
    print(f"  KR top3     : {k3}")
    print(f"  US top3     : {u3}\n")

    # ── Step 2: Holdings CSV 업데이트 ────────────────────────
    print("[Holdings 업데이트]")
    update_holdings(H_GLOBAL, ts, g5)
    update_holdings(H_KR,     ts, k3)
    update_holdings(H_US,     ts, u3)
    print()

    # ── Step 3: 주간/월간 집계 ───────────────────────────────
    wg = fmt_global(aggregate_top(H_GLOBAL, wd,        5))
    wk = fmt_kr_list(aggregate_top(H_KR,    wd,        3))
    wu = aggregate_top(H_US,                wd,        3)
    mg = fmt_global(aggregate_top(H_GLOBAL, month_pfx, 5, True))
    mk = fmt_kr_list(aggregate_top(H_KR,    month_pfx, 3, True))
    mu = aggregate_top(H_US,                month_pfx, 3, True)

    print("[집계 결과]")
    print(f"  주간 global : {wg}")
    print(f"  주간 KR     : {wk}")
    print(f"  주간 US     : {wu}")
    print(f"  월간 global : {mg}")
    print(f"  월간 KR     : {mk}")
    print(f"  월간 US     : {mu}\n")

    # ── Step 4: 주간/월간 CSV 갱신 ───────────────────────────
    print("[CSV 갱신]")
    update_period_csv(W_GLOBAL, wl, wg)
    update_period_csv(W_KR,     wl, wk)
    update_period_csv(W_US,     wl, wu)
    update_period_csv(M_GLOBAL, ml, mg, True)
    update_period_csv(M_KR,     ml, mk, True)
    update_period_csv(M_US,     ml, mu, True)

    print(f"\n{'='*58}")
    print("  ✅ ETF History Update 완료")
    print(f"{'='*58}\n")


if __name__ == '__main__':
    main()
