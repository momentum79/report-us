# -*- coding: utf-8 -*-
"""
make_kr_chart_display.py
- 요약 게시판(summary.html)의 짝꿍 게시판2 '차트 게시판' 생성 → kr_chart.html
- 4열 그리드. 각 셀 = V2 내장형 lightweight-charts (일봉 캔들 + MA + 거래량 + RSI)
  1행: 고정 — 코스피 / 코스닥 / KODEX 200 / KODEX 코스닥150
  2행: 한국 ETF Top4   (0txt/total_top30.csv 상위 한국 ETF, 1행 중복 제외)
  3행: 주도주 Top4     (0order/0주도주.txt — SPOT+주도주, 비어있으면 행 생략)
  4행: KR150 종합 Top4 (0order/0kr150_top10.txt)
  5행: KR전종목 종합 Top4 (0order/0kr_top10.txt)
- 데이터: 네이버 siseJson 일봉 3년 (chart_popup_v2.collect_daily 재사용, 지수 심볼 KOSPI/KOSDAQ 지원)
- 렌더: make_us_chart_display.build_html 재사용 (us_chart.html 과 동일한 캔들+MA+RSI 음영)
"""
import csv
import re
import sys
from pathlib import Path

# cp949 콘솔(배치 실행)에서 인코딩 불가 문자로 print가 죽지 않게 — 깨지는 문자는 ?로 대체
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from chart_popup_v2 import collect_daily
from make_us_chart_display import add_trend_states, build_html
sys.path.insert(0, str(Path("D:/py")))
from kr_etf_universe import KR_NAME_MAP

# ── 경로 설정 ────────────────────────────────────────────────────
BASE_DIR   = Path("D:/py/report-us")
OUT_HTML   = BASE_DIR / "kr_chart.html"

KR_CSV         = Path("D:/py/korea/kr.csv")
TOTAL_TOP30    = Path("D:/py/0txt/total_top30.csv")
JUDO_TXT       = Path("D:/py/0order/0주도주.txt")        # SPOT+주도주 (make_summary_board.py 가 생성)
KR150_TOP_TXT  = Path("D:/py/0order/0kr150_top10.txt")   # KR150 종합 Top10
KRALL_TOP_TXT  = Path("D:/py/0order/0kr_top10.txt")      # KR전종목 종합 Top10

# 1행 고정: 지수 + 대표 ETF
INDEX_ROW = [
    ("KOSPI",  "코스피"),
    ("KOSDAQ", "코스닥"),
    ("069500", "KODEX 200"),
    ("229200", "KODEX 코스닥150"),
]

PLACEHOLDER = {"ticker": "-", "label": "(없음)", "fetch": "-"}


def load_name_map() -> dict:
    """korea/kr.csv → {6자리 티커: 종목명}"""
    names = {}
    try:
        with KR_CSV.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                t = (row.get("티커") or "").strip().zfill(6)
                n = (row.get("종목명") or "").strip()
                if re.fullmatch(r"\d{6}", t) and n:
                    names[t] = n
    except Exception as e:
        print(f"[WARN] kr.csv 읽기 실패: {e}")
    return names


def read_ticker_lines(path: Path, n: int = 4) -> list[str]:
    """1줄 1티커 txt → 6자리 티커 상위 n개"""
    out = []
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            t = re.sub(r"\*+", "", line).strip()[:6]
            if re.fullmatch(r"\d{6}", t) and t not in out:
                out.append(t)
            if len(out) >= n:
                break
    except Exception as e:
        print(f"[WARN] 읽기 실패: {path.name} -> {e}")
    return out


def top_kr_etf(exclude: set, n: int = 4) -> list[tuple[str, str]]:
    """0txt/total_top30.csv 에서 한국 ETF 상위 n개 → [(티커, 종목명)]
    종목명/한국ETF 판별은 kr_etf_universe.KR_NAME_MAP 기준.
    total_top30.csv 의 한국 ETF 행은 이 유니버스(36개)의 부분집합이므로
    매일 상위가 바뀌어도 항상 커버되며, 0051G0 같은 영숫자 신규 ETF도 잡힌다.
    (kr.csv 에는 ETF 티커가 없어 이름맵으로 쓸 수 없음)"""
    out = []
    seen = set()
    try:
        with TOTAL_TOP30.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                t = re.sub(r"\*+", "", (row.get("티커") or "")).strip()
                if t not in KR_NAME_MAP and t.isdigit():
                    t = t.zfill(6)
                if t not in KR_NAME_MAP or t in exclude or t in seen:
                    continue
                seen.add(t)
                out.append((t, KR_NAME_MAP[t]))
                if len(out) >= n:
                    break
    except Exception as e:
        print(f"[WARN] total_top30.csv 읽기 실패: {e}")
    return out


def to_charts(pairs) -> list[dict]:
    """[(티커, 이름)] → build_html 용 charts 리스트"""
    return [{"ticker": t, "label": f"{name} ({t})", "fetch": t} for t, name in pairs]


def pad4(charts: list[dict]) -> list[dict]:
    while len(charts) < 4:
        charts.append(dict(PLACEHOLDER))
    return charts


def main():
    print("=" * 60)
    print("make_kr_chart_display.py 실행 (요약 게시판2 - 차트 게시판)")
    print("=" * 60)

    names = load_name_map()
    named = lambda tickers: [(t, names.get(t, t)) for t in tickers]

    row1 = to_charts(INDEX_ROW)

    etf_pairs = top_kr_etf(exclude={t for t, _ in INDEX_ROW})
    row2 = pad4(to_charts(etf_pairs))
    print(f"[OK] ETF Top4      -> {[t for t, _ in etf_pairs]}")

    judo = read_ticker_lines(JUDO_TXT)
    row3 = to_charts(named(judo))          # 비어있으면 행 자체를 생략
    print(f"[OK] 주도주 Top4   -> {judo if judo else '(없음 - 행 생략)'}")

    kr150 = read_ticker_lines(KR150_TOP_TXT)
    row4 = pad4(to_charts(named(kr150)))
    print(f"[OK] KR150 Top4    -> {kr150}")

    krall = read_ticker_lines(KRALL_TOP_TXT)
    row5 = pad4(to_charts(named(krall)))
    print(f"[OK] KR전종목 Top4 -> {krall}")

    rows_meta = [{"label": "📌 한국 지수 / 대표 ETF", "charts": row1},
                 {"label": "📊 한국 ETF Top4 [통합 Top30]", "charts": row2}]
    if row3:
        rows_meta.append({"label": "🔥 주도주 Top4 (SPOT+주도주) [KR전종목]", "charts": pad4(row3)})
    rows_meta.append({"label": "📈 KR150 종합 Top4", "charts": row4})
    rows_meta.append({"label": "📈 KR전종목 종합 Top4", "charts": row5})

    # ── OHLCV 수집 (네이버 siseJson 일봉 3년, 중복 제거) ──
    codes = []
    for row in rows_meta:
        for c in row["charts"]:
            if c["fetch"] != "-" and c["fetch"] not in codes:
                codes.append(c["fetch"])
    print(f"\n[OHLCV 수집] {len(codes)}개 심볼 (일봉 3년)")
    ohlcv = collect_daily(codes)
    for c in codes:
        print(f"  {c:<8} {len(ohlcv.get(c, [])):>4} bars")

    # 추세배경(LIME/GREEN/PURPLE/RED) 상태를 각 봉에 부착 — us_chart.html 과 동일
    ohlcv = add_trend_states(ohlcv)

    empties = [c for c in codes if not ohlcv.get(c)]
    if empties:
        print(f"  [경고] 데이터 누락: {', '.join(empties)}")

    lib = BASE_DIR / "lib" / "lightweight-charts.standalone.production.js"
    if not lib.exists():
        print(f"  [경고] 차트 라이브러리 없음: {lib}")

    nav_html = (
        '<a href="main_hub.html" class="nav-item">상황판</a>'
        '<a href="order.html" class="nav-item">주문</a>'
        '<a href="summary.html" class="nav-item">요약</a>'
        '<a href="danta_chart.html" class="nav-item">단타</a>'
        '<a href="kr_chart.html" class="nav-item active">차트</a>'
        '<a href="us_summary.html" class="nav-item">미국요약</a>'
    )
    html = build_html(rows_meta, ohlcv, {},
                      title="차트 게시판 (한국 지수·ETF·주식)",
                      heading="📊 차트 게시판 (한국 지수 · ETF · 주식)",
                      nav_html=nav_html, trend_background=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    kb = len(html.encode("utf-8")) / 1024
    print(f"\n[OK] 저장 완료: {OUT_HTML}  ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
