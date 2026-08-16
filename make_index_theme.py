# make_index_theme.py
# naver_theme_crawler.py outputs -> kor_theme.html
# - 당일/전일 테마 카드 표시
# - 📊 테마주 트래킹 (2주) 테이블 (당일 테마 종목 기준)
# - 📅 당일 테마 히스토리 사이드바 (PC 전용, 최근 7일)

import csv
import json
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trading_day import is_kr_trading_day, last_kr_trading_day  # noqa: E402


NAVER_TXT         = Path(r"D:\py\0txt\00_1887_naver_thema.txt")
NAVER_DEBUG_CSV   = Path(r"D:\py\0txt\00_1887_naver_thema_debug.csv")
OUT_HTML          = Path(r"D:\py\report-us\kor_theme.html")
TRACKING_JSON     = Path(r"D:\py\0txt\theme_stock_tracking.json")
HISTORY_JSON      = Path(r"D:\py\0txt\theme_history.json")
YESTERDAY_JSON    = Path(r"D:\py\0txt\theme_yesterday.json")  # ← 전일 당일 테마 스냅샷
THEME_ORDER_JSON  = Path(r"D:\py\report-us\theme_order.json")  # ← 체결강도(키움 ka10003) 소스
BOKGI_THEME_ROOT  = Path(r"D:\py\bokgi_theme")

TRACKING_DAYS = 14  # 2주 보관
HISTORY_DAYS  = 7   # 히스토리 7일


# ── 공통 유틸 ──────────────────────────────────────────────────────

def _as_float(raw, default=0.0) -> float:
    try:
        if raw is None:
            return default
        return float(str(raw).replace(",", "").replace("%", "").replace("+", "").strip())
    except Exception:
        return default


def _as_bool(raw) -> bool:
    return str(raw).strip().lower() in {"1", "true", "t", "yes", "y"}


def _load_naver_passed_codes() -> set[str]:
    codes: set[str] = set()
    if not NAVER_TXT.exists():
        return codes
    try:
        for line in NAVER_TXT.read_text(encoding="utf-8-sig").splitlines():
            code = line.strip().split()[0] if line.strip() else ""
            code = code.lstrip("A").zfill(6)
            if len(code) == 6 and code.isdigit():
                codes.add(code)
    except Exception:
        pass
    return codes


def _load_cntr_map() -> dict:
    """theme_order.json(integrate.py가 키움 ka10003으로 채운 체결강도) → {ticker: cntr_str}."""
    cmap: dict = {}
    if not THEME_ORDER_JSON.exists():
        return cmap
    try:
        data = json.loads(THEME_ORDER_JSON.read_text(encoding="utf-8"))
        for it in data.get("items", []):
            code = str(it.get("ticker", "")).strip().lstrip("A").zfill(6)
            cntr = it.get("cntr_str")
            if len(code) == 6 and code.isdigit() and cntr is not None:
                cmap[code] = cntr
    except Exception:
        pass
    return cmap


def load_naver_theme_data() -> dict:
    """
    Convert naver_theme_crawler.py outputs into the old theme_analysis-like shape.
    The board shows only final passed rows; Kiwoom/Infostock weekly data is not used.
    체결강도(cntr_str)만 theme_order.json(키움 ka10003)에서 종목코드로 매핑.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not NAVER_DEBUG_CSV.exists():
        print(f"[ERROR] {NAVER_DEBUG_CSV} 없음. naver_theme_crawler.py를 먼저 실행하세요.")
        return {"fetched_at": now_str, "daily": {"top_themes": []}}

    passed_codes = _load_naver_passed_codes()
    cntr_map     = _load_cntr_map()
    grouped: dict[str, list[dict]] = {}
    theme_chg_map: dict[str, float] = {}   # 테마군 등락률 (헤더용)

    try:
        with NAVER_DEBUG_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                code = str(row.get("code", "")).strip().lstrip("A").zfill(6)
                if len(code) != 6 or not code.isdigit():
                    continue
                passed = _as_bool(row.get("passed")) or code in passed_codes
                if not passed:
                    continue

                theme_nm = (row.get("theme") or "네이버테마").strip()
                tc_raw = row.get("theme_chg")
                if theme_nm not in theme_chg_map and tc_raw not in (None, "", "-"):
                    try:
                        theme_chg_map[theme_nm] = float(
                            str(tc_raw).replace("+", "").replace("%", "").strip())
                    except Exception:
                        pass
                chg_pct = _as_float(row.get("chg_pct"))
                trade_eok = _as_float(row.get("trade_eok"))
                close_prc = _as_float(row.get("close"))
                stock = {
                    "stk_cd": code,
                    "stk_nm": (row.get("name") or code).strip(),
                    "flu_rt": f"{chg_pct:.2f}",
                    "cur_prc": f"{close_prc:.0f}" if close_prc else "0",
                    "nxt_info": "",
                    "contract_strength": {
                        "cntr_str": cntr_map.get(code, "-"),
                        "acc_trde_prica": trade_eok * 100_000_000,
                    },
                    "naver": {
                        "trade_eok": trade_eok,
                        "ohlc_ok": _as_bool(row.get("ohlc_ok")),
                        "ok_wick": _as_bool(row.get("ok_wick")),
                    },
                }
                grouped.setdefault(theme_nm, []).append(stock)
    except Exception as e:
        print(f"[ERROR] 네이버 테마 CSV 읽기 실패: {e}")
        return {"fetched_at": now_str, "daily": {"top_themes": []}}

    themes = []
    sorted_groups = sorted(
        grouped.items(),
        key=lambda item: sum((s.get("contract_strength") or {}).get("acc_trde_prica", 0) for s in item[1]),
        reverse=True,
    )
    for rank, (theme_nm, stocks) in enumerate(sorted_groups, start=1):
        stocks.sort(
            key=lambda s: (s.get("contract_strength") or {}).get("acc_trde_prica", 0),
            reverse=True,
        )
        avg_chg = sum(_as_float(s.get("flu_rt")) for s in stocks) / len(stocks) if stocks else 0.0
        # 헤더 등락률: 네이버 테마군 등락률 우선, 없으면 구성종목 평균 fallback
        hdr_chg = theme_chg_map.get(theme_nm, avg_chg)
        themes.append({
            "rank": rank,
            "thema_grp_cd": f"NAVER_{rank:02d}",
            "thema_nm": theme_nm,
            "flu_rt": f"{hdr_chg:.2f}",
            "dt_prft_rt": "0",
            "stk_num": str(len(stocks)),
            "stocks": stocks,
        })

    fetched_at = datetime.fromtimestamp(NAVER_DEBUG_CSV.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return {"fetched_at": fetched_at, "daily": {"top_themes": themes}}


def shorten_theme(name: str) -> str:
    """'태양광_잉곳/웨이퍼/셀/모듈' → '태양광_잉곳'"""
    return name.split("/")[0].strip()


def parse_rate(val: str) -> float:
    try:
        return float(str(val).replace("+", "").strip())
    except Exception:
        return 0.0


def parse_price(val: str) -> float:
    """+1944', '-439000' → 1944.0 (절대값)"""
    try:
        return abs(float(str(val).replace("+", "").replace(",", "").strip()))
    except Exception:
        return 0.0


def cs_badge(cs_val: str) -> str:
    try:
        v = float(cs_val)
        color = "#27ae60" if v >= 100 else "#e74c3c"
        return f'<span style="color:{color};font-size:0.94em;font-weight:bold;">{v:.0f}%</span>'
    except Exception:
        return f'<span style="font-size:0.94em;font-weight:bold;color:#aaa;">{cs_val}</span>'


def nxt_badge(nxt_val: str) -> str:
    if not nxt_val:
        return ""
    bg = "#2c3e50" if nxt_val == "N선" else ("#8e44ad" if nxt_val == "N" else "#e67e22")
    return f'<span style="display:inline-block; font-size:10px; font-weight:bold; color:#fff; background-color:{bg}; padding:1px 4px; border-radius:3px; min-width:18px; text-align:center;">{nxt_val}</span>'


def tv_badge(tv_raw: any) -> str:
    """거래대금 포맷팅 (원 단위 → 억 단위), 1000억 이상 빨간색"""
    try:
        val_won = float(str(tv_raw).replace(",", "").strip())
        val_uk  = val_won / 100_000_000
        if val_uk <= 0:
            return '<span style="color:#aaa;font-size:0.85em;">-</span>'
        
        color = "#e74c3c" if val_uk >= 1000 else "#222"
        weight = "bold" if val_uk >= 1000 else "normal"
        return f'<span style="color:{color};font-size:0.88em;font-weight:{weight};">{val_uk:,.0f}억</span>'
    except Exception:
        return '<span style="color:#aaa;font-size:0.85em;">-</span>'


# ── 테마 카드 ──────────────────────────────────────────────────────

MEDALS = ["🥇", "🥈", "🥉"]


def theme_card(theme: dict, rank: int, show_ticker: bool = False) -> str:
    medal    = MEDALS[rank] if rank < 3 else f"#{rank+1}"
    full_nm  = theme.get("thema_nm", "")
    short_nm = shorten_theme(full_nm)
    flu_rt   = theme.get("flu_rt", "0")
    stk_num  = theme.get("stk_num", "0")
    stocks   = theme.get("stocks", [])

    v = parse_rate(flu_rt)
    hdr_color = "#27ae60" if v > 0 else ("#e74c3c" if v < 0 else "#888")
    sign = "+" if v > 0 else ""

    rows = ""
    for s in stocks:
        cd      = s.get("stk_cd", "")
        nm      = s.get("stk_nm", "")[:12]
        fr      = s.get("flu_rt", "0")
        cs_obj  = s.get("contract_strength") or {}
        cs      = cs_obj.get("cntr_str", "-")
        tv_raw  = cs_obj.get("acc_trde_prica", 0)
        nxt     = s.get("nxt_info", "")
        fr_v    = parse_rate(fr)
        rc      = "#27ae60" if fr_v > 0 else ("#e74c3c" if fr_v < 0 else "#888")
        s_r     = "+" if fr_v > 0 else ""

        ticker_html = f'<span class="stock-ticker">{cd}</span>' if show_ticker else ""
        name_attrs = (f'class="stock-name naver-trigger chart-hover" data-code="{cd}" data-name="{nm}" style="cursor:pointer;"'
                      if cd else 'class="stock-name"')

        rows += f"""
          <div class="stock-row">
            {ticker_html}
            <span {name_attrs}>{nm}</span>
            <span class="stock-rate" style="color:{rc};">{s_r}{fr_v:.2f}%</span>
            <span class="stock-cs">{cs_badge(cs)}</span>
            <span class="stock-tv">{tv_badge(tv_raw)}</span>
            <span class="stock-nxt" style="width:30px; text-align:center; display:inline-block;">{nxt_badge(nxt)}</span>
          </div>"""

    return f"""
  <div class="theme-card">
    <div class="card-header" style="border-top:3px solid {hdr_color};">
      <div class="card-title-line">
        <span class="medal">{medal}</span>
        <span class="theme-name" title="{full_nm}">{short_nm}</span>
        <span class="stk-num">{stk_num}종목</span>
      </div>
      <div class="card-rate" style="color:{hdr_color};">{sign}{v:.2f}%</div>
    </div>
    <div class="stock-list">{rows}
    </div>
  </div>"""


def build_section(period_data: dict, section_id: str, title: str,
                  show_ticker: bool = False) -> str:
    themes = period_data.get("top_themes", [])
    cards  = "".join(theme_card(t, i, show_ticker=show_ticker)
                     for i, t in enumerate(themes))
    return f"""
<div class="section" id="{section_id}">
  <h3 class="sec-title">{title}</h3>
  <div class="cards-row">{cards}
  </div>
</div>"""


# ── 전일 테마 (yesterday) 관리 ────────────────────────────────────

def _snapshot_themes(daily_data: dict) -> list:
    """당일 테마 데이터 → 스냅샷용 top_themes 리스트 (등락률/체결강도는 저장 안 함)"""
    out = []
    for theme in daily_data.get("top_themes", []):
        stocks_snapshot = []
        for s in theme.get("stocks", []):
            stocks_snapshot.append({
                "stk_cd":   s.get("stk_cd", ""),
                "stk_nm":   s.get("stk_nm", ""),
                "nxt_info": s.get("nxt_info", ""),
                # 등락률/체결강도는 저장 안 함 (오늘 값으로 대체하기 때문)
            })
        out.append({
            "rank":         theme.get("rank", 0),
            "thema_grp_cd": theme.get("thema_grp_cd", ""),
            "thema_nm":     theme.get("thema_nm", ""),
            "flu_rt":       theme.get("flu_rt", "0"),   # 그날 테마 등락률 (헤더용)
            "dt_prft_rt":   theme.get("dt_prft_rt", "0"),
            "stk_num":      theme.get("stk_num", "0"),
            "stocks":       stocks_snapshot,
        })
    return out


def roll_and_load_yesterday(daily_data: dict, fetched_at: str) -> dict:
    """전일 스냅샷 관리 + 로드 (같은 날 여러 번 실행해도 전일 데이터 보존).

    저장 구조: {"yesterday": {flat 스냅샷}, "today": {flat 스냅샷}}
    - today 스냅샷의 날짜가 오늘과 다르면(=날짜가 바뀜) today를 yesterday로 승격
    - 같은 날 재실행 시에는 yesterday를 건드리지 않고 today만 갱신
      → 종일 돌려도 "전일 테마"가 어제 데이터로 유지됨 (이전 버그: 매 실행마다 덮어써서
        2번째 실행부터 오늘 데이터가 전일로 표시되던 문제 수정)
    - 휴장일(주말/공휴일)에는 아예 쓰지 않고 직전 거래일 스냅샷을 그대로 반환
      → 토/일에 돌려서 금요일 데이터가 yesterday로 밀렸다가 사라지던 문제 방지
    반환: build_yesterday_section 용 flat dict (yesterday)
    """
    try:
        today_str = fetched_at[:10] if fetched_at else ""
    except Exception:
        today_str = ""
    if len(today_str) != 10:
        today_str = datetime.now().strftime("%Y-%m-%d")

    # 기존 파일 로드 (신/구 포맷 모두 지원)
    store = {}
    if YESTERDAY_JSON.exists():
        try:
            store = json.loads(YESTERDAY_JSON.read_text(encoding="utf-8"))
        except Exception:
            store = {}

    # 휴장일: 스냅샷 롤링/저장 없이 직전 거래일 상태 유지
    if not is_kr_trading_day(today_str):
        prev = last_kr_trading_day(today_str)
        kept = store.get("yesterday") or {}
        print(f"[휴장일] {today_str} — 전일 테마 스냅샷 갱신 생략, "
              f"직전 거래일({prev}) 상태 유지 "
              f"(today={(store.get('today') or {}).get('date_str', '-')}, "
              f"yesterday={kept.get('date_str', '-')})")
        return kept

    if "today" in store or "yesterday" in store:
        yesterday_snap = store.get("yesterday") or {}
        today_snap     = store.get("today") or {}
    else:
        # 구 포맷(flat) → 마지막으로 저장된 today 스냅샷으로 간주
        today_snap     = store if store.get("top_themes") else {}
        yesterday_snap = {}

    # 날짜가 바뀌었으면 직전 today → yesterday 로 승격
    if today_snap.get("date_str") and today_snap.get("date_str") != today_str:
        yesterday_snap = today_snap

    today_snapshot = {
        "date_str":   today_str,
        "source":     "naver",
        "top_themes": _snapshot_themes(daily_data),
    }

    new_store = {"yesterday": yesterday_snap, "today": today_snapshot}
    try:
        YESTERDAY_JSON.write_text(
            json.dumps(new_store, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[OK] 전일 스냅샷 저장: today={today_str}, "
              f"yesterday={yesterday_snap.get('date_str', '-')}")
    except Exception as e:
        print(f"[ERROR] theme_yesterday.json 저장 실패: {e}")

    return yesterday_snap


def build_yesterday_section(yesterday_data: dict, daily_data: dict,
                             tracking_data: dict = None) -> str:
    """
    전일 테마 섹션 빌드.
    - 티커/종목명/NXT 정보 → yesterday_data 에서
    - 등락률/체결강도          → daily_data 의 오늘 데이터에서 매핑
                               없으면 tracking_data 에서 보완 (버그1 수정)
    """
    if not yesterday_data or not yesterday_data.get("top_themes"):
        return ""

    is_naver_snapshot = yesterday_data.get("source") == "naver" or any(
        str(t.get("thema_grp_cd", "")).startswith("NAVER_")
        for t in yesterday_data.get("top_themes", [])
    )
    if not is_naver_snapshot:
        return ""

    date_str = yesterday_data.get("date_str", "")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_label = f"{dt.month}/{dt.day}"
    except Exception:
        date_label = date_str

    today_str = datetime.now().strftime("%Y-%m-%d")

    # 오늘 등락률/체결강도 lookup dict  {stk_cd: {...}}
    # 1차: 당일 top3 테마 종목
    today_lookup: dict[str, dict] = {}
    for theme in daily_data.get("top_themes", []):
        for s in theme.get("stocks", []):
            cd = s.get("stk_cd", "")
            if cd and cd not in today_lookup:
                today_lookup[cd] = {
                    "flu_rt":            s.get("flu_rt", "0"),
                    "flu_sig":           s.get("flu_sig", "3"),
                    "contract_strength": s.get("contract_strength"),
                }

    # ✅ 2차 보완: tracking_data에서 오늘 값 채우기
    # (전일 종목이 오늘 top3에 없는 경우 → 0% 오표시 방지)
    if tracking_data:
        for stk_cd, info in tracking_data.items():
            if stk_cd not in today_lookup:
                flu_rt = info.get("pct_history", {}).get(today_str, "")
                if flu_rt:
                    today_lookup[stk_cd] = {
                        "flu_rt":            flu_rt,
                        "flu_sig":           "3",
                        "contract_strength": {
                            "cntr_str": info.get("today_cntr", "-"),
                            "acc_trde_prica": info.get("today_tv", 0)
                        },
                    }

    # 전일 테마별 카드 생성 (오늘 등락률/체결강도로 덮어쓰기)
    enriched_themes = []
    for theme in yesterday_data.get("top_themes", []):
        enriched_stocks = []
        for s in theme.get("stocks", []):
            cd = s.get("stk_cd", "")
            today_info = today_lookup.get(cd, {})
            enriched_stocks.append({
                "stk_cd":            cd,
                "stk_nm":            s.get("stk_nm", ""),
                "nxt_info":          s.get("nxt_info", ""),
                # 오늘 현재 시세로 갱신 (없으면 "-" 유지)
                "flu_rt":            today_info.get("flu_rt", "-"),
                "flu_sig":           today_info.get("flu_sig", "3"),
                "contract_strength": today_info.get("contract_strength"),
            })
        enriched_themes.append({
            **theme,
            "stocks": enriched_stocks,
        })

    enriched_data = {"top_themes": enriched_themes}
    section = build_section(
        enriched_data,
        "yesterday",
        f"📅 전일 테마 ({date_label}) — 오늘 등락률/체결강도",
        show_ticker=False
    )

    return section


# ── 테마주 트래킹 ──────────────────────────────────────────────────

def update_theme_stock_tracking(daily_data: dict) -> dict:
    """당일 테마 구성종목 누적 트래킹 (14일 보관).

    휴장일에는 갱신하지 않고 직전 거래일 상태를 그대로 반환한다.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cutoff    = (datetime.now() - timedelta(days=TRACKING_DAYS)).strftime("%Y-%m-%d")

    # 기존 데이터 로드
    if TRACKING_JSON.exists():
        try:
            tracking = json.loads(TRACKING_JSON.read_text(encoding="utf-8"))
        except Exception:
            tracking = {}
    else:
        tracking = {}

    if not is_kr_trading_day(today_str):
        print(f"[휴장일] {today_str} — 테마주 트래킹 갱신 생략, "
              f"직전 거래일({last_kr_trading_day(today_str)}) 상태 유지 ({len(tracking)}종목)")
        return tracking

    # 14일 지난 항목 제거
    tracking = {k: v for k, v in tracking.items()
                if v.get("added_date", "") >= cutoff}

    # 오늘 당일 테마 종목 수집 (중복 방지: 상위 테마 우선)
    seen   = set()
    themes = daily_data.get("top_themes", [])
    for theme in themes:
        theme_nm = shorten_theme(theme.get("thema_nm", ""))
        for s in theme.get("stocks", []):
            stk_cd  = s.get("stk_cd", "").strip()
            stk_nm  = s.get("stk_nm", "")
            flu_rt  = s.get("flu_rt", "0")
            cur_prc = parse_price(s.get("cur_prc", "0"))
            cs_obj  = s.get("contract_strength") or {}
            cs      = cs_obj.get("cntr_str", "-")
            tv_raw  = cs_obj.get("acc_trde_prica", 0)
            nxt     = s.get("nxt_info", "")

            if not stk_cd or stk_cd in seen:
                continue
            seen.add(stk_cd)

            if stk_cd not in tracking:
                # 신규 등록
                tracking[stk_cd] = {
                    "stk_nm":      stk_nm,
                    "theme_nm":    theme_nm,
                    "added_date":  today_str,
                    "base_prc":    cur_prc,
                    "base_flu_rt": flu_rt,
                    "pct_history": {},
                }

            # 오늘 값 갱신 (당일 테마 등장 종목)
            tracking[stk_cd]["pct_history"][today_str] = flu_rt
            tracking[stk_cd]["today_prc"]   = cur_prc
            tracking[stk_cd]["today_cntr"]  = cs
            tracking[stk_cd]["today_tv"]    = tv_raw
            tracking[stk_cd]["nxt_info"]    = nxt
            # 거래대금 누적 기록
            if "tv_history" not in tracking[stk_cd]:
                tracking[stk_cd]["tv_history"] = {}
            tracking[stk_cd]["tv_history"][today_str] = tv_raw

    # ── bokgi_theme daily.csv로 전체 추적 종목 가격/거래대금 갱신 ──
    # bokgi_theme.py가 이미 daily.csv를 최신 상태로 유지하므로 여기서 읽기만 함
    if BOKGI_THEME_ROOT.exists() and tracking:
        ok_cnt = 0
        for stk_cd, info in tracking.items():
            added_date_str = info.get("added_date", "")
            folders = list(BOKGI_THEME_ROOT.glob(f"{added_date_str}_{stk_cd}_*"))
            if not folders:
                continue
            daily_csv = folders[0] / "daily.csv"
            if not daily_csv.exists():
                continue
            try:
                df = pd.read_csv(daily_csv, encoding="utf-8-sig", dtype=str)
                if df.empty or "날짜" not in df.columns:
                    continue
                df = df[df["날짜"] >= added_date_str]
                if df.empty:
                    continue
                last = df.iloc[-1]
                close_prc = float(last["종가"])
                vol       = float(last["거래량"])
                last_date = str(last["날짜"])[:10]
                flu_rt    = last.get("전일비(%)", "")
                if close_prc > 0:
                    tracking[stk_cd]["today_prc"] = close_prc
                # 오늘 등락률: daily.csv 마지막 행 전일비(%) 저장
                if flu_rt not in ("", None):
                    tracking[stk_cd]["last_flu_rt"]   = str(flu_rt)
                    tracking[stk_cd]["last_flu_date"]  = last_date
                # tv_history: 등록일 이후 날짜별 종가×거래량 전체 채우기
                if "tv_history" not in tracking[stk_cd]:
                    tracking[stk_cd]["tv_history"] = {}
                for _, row in df.iterrows():
                    date_key = str(row["날짜"])[:10]
                    tv = float(row["종가"]) * float(row["거래량"])
                    if tv > 0:
                        tracking[stk_cd]["tv_history"][date_key] = tv
                tracking[stk_cd]["today_tv"] = close_prc * vol
                ok_cnt += 1
            except Exception:
                continue
        print(f"[OK] bokgi_theme daily.csv 가격/거래대금 갱신: {ok_cnt}/{len(tracking)}종목")

    # ── 5일+ 경과 종목: 거래대금 미달 시 삭제 ──────────────────────────
    # 규칙: days >= 5 이면, 당일거래대금 < 100억 OR 일평균거래대금 < 100억 → 삭제
    TV_THRESHOLD = 100 * 100_000_000  # 100억 (원)
    to_delete = []
    for stk_cd, info in tracking.items():
        try:
            days_passed = (datetime.now() - datetime.strptime(info.get("added_date", today_str), "%Y-%m-%d")).days
        except Exception:
            days_passed = 0
        if days_passed < 5:
            continue
        today_tv = float(info.get("today_tv", 0) or 0)
        tv_hist  = info.get("tv_history", {})
        cum_tv   = sum(float(v) for v in tv_hist.values() if v)
        avg_tv   = cum_tv / days_passed if days_passed > 0 else 0
        if today_tv < TV_THRESHOLD or avg_tv < TV_THRESHOLD:
            nm = info.get("stk_nm", stk_cd)
            print(f"🗑 거래대금 미달 삭제: {stk_cd} {nm} "
                  f"| 당일 {today_tv/100_000_000:.0f}억 "
                  f"| 일평균 {avg_tv/100_000_000:.0f}억 "
                  f"| {days_passed}일 경과")
            to_delete.append(stk_cd)
    for stk_cd in to_delete:
        del tracking[stk_cd]

    try:
        TRACKING_JSON.write_text(
            json.dumps(tracking, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[ERROR] theme_stock_tracking.json 저장 실패: {e}")

    return tracking


def build_theme_tracking_table(tracking: dict) -> str:
    """📊 테마주 트래킹 테이블 HTML
    컬럼: Ticker | Name | 체결강도 | 오늘 등락률 | 누적 등락률 | 경과일 | 테마
    """
    if not tracking:
        return '<p style="color:#95a5a6;margin-left:10px;">(트래킹 종목 없음)</p>'

    today_str = datetime.now().strftime("%Y-%m-%d")

    # ✅ 버그2 수정: "-", "N/A", "" → 0%로 오인 방지, 명시적으로 "-" 표시
    def pct_td(v_str):
        if not v_str or v_str in ("-", "N/A"):
            return '<td style="color:#aaa;text-align:right;">-</td>'
        try:
            v     = parse_rate(v_str)
            color = "#27ae60" if v > 0 else ("#e74c3c" if v < 0 else "#888")
            sign  = "+" if v > 0 else ""
            return f'<td style="color:{color};text-align:right;">{sign}{v:.2f}%</td>'
        except Exception:
            return f'<td style="color:#aaa;text-align:right;">{v_str}</td>'

    rows = []
    sorted_items = sorted(
        tracking.items(),
        key=lambda x: x[1].get("added_date", ""),
        reverse=True
    )

    for stk_cd, info in sorted_items:
        stk_nm   = info.get("stk_nm", "")
        theme_nm = info.get("theme_nm", "")
        added_dt = info.get("added_date", "-")
        base_prc = info.get("base_prc", 0)
        today_prc= info.get("today_prc", 0)
        cntr_str = info.get("today_cntr", "-")
        nxt_info = info.get("nxt_info", "")
        pct_hist = info.get("pct_history", {})

        # ✅ 오늘 등락률: 없으면 "N/A" → pct_td()에서 "-"로 표시
        # 오늘 등락률: 오늘 테마 등장분 우선, 없으면 daily.csv 마지막 전일비(%)
        today_flu = pct_hist.get(today_str)
        if not today_flu:
            today_flu = info.get("last_flu_rt", "N/A")

        # 누적 등락률 (기준가 대비)
        cum_td = '<td style="color:#aaa;text-align:right;">-</td>'
        if base_prc and today_prc:
            try:
                cum   = (today_prc / base_prc - 1) * 100
                sign  = "+" if cum >= 0 else ""
                color = "#27ae60" if cum > 0 else ("#e74c3c" if cum < 0 else "#888")
                cum_td = f'<td style="color:{color};font-weight:bold;text-align:right;">{sign}{cum:.2f}%</td>'
            except Exception:
                pass

        # 경과일
        try:
            days = (datetime.now() - datetime.strptime(added_dt, "%Y-%m-%d")).days
        except Exception:
            days = 0
        expire_in = TRACKING_DAYS - days
        d_color   = "#27ae60" if days <= 5 else ("#e67e22" if days <= 10 else "#e74c3c")

        # 체결강도 셀
        try:
            cs_v   = float(cntr_str)
            cs_col = "#27ae60" if cs_v >= 100 else "#e74c3c"
            cs_td  = f'<td style="color:{cs_col};text-align:center;font-weight:bold;font-size:0.95em;">{cs_v:.0f}%</td>'
        except Exception:
            cs_td  = '<td style="color:#aaa;text-align:center;font-weight:bold;font-size:0.95em;">-</td>'

        # 거래대금 셀
        tv_raw_trk = info.get("today_tv", 0)
        tv_td = f'<td style="text-align:right;">{tv_badge(tv_raw_trk)}</td>'

        # 누적거래대금 셀 (tv_history 합산)
        tv_history = info.get("tv_history", {})
        cum_tv_won = sum(float(v) for v in tv_history.values() if v)
        cum_tv_td = f'<td style="text-align:right;">{tv_badge(cum_tv_won)}</td>'

        nxt_td = f'<td style="text-align:center;">{nxt_badge(nxt_info)}</td>'

        rows.append(
            f'<tr>'
            f'<td class="narrow" data-code="{stk_cd}" data-name="{stk_nm}">{stk_cd}</td>'
            f'<td class="name-col">{stk_nm}</td>'
            f'{cs_td}'
            f'{nxt_td}'
            f'{pct_td(today_flu)}'
            f'{cum_td}'
            f'{tv_td}'
            f'{cum_tv_td}'
            f'<td style="color:{d_color};font-size:11px;text-align:center;white-space:nowrap;">{days}일 (D-{expire_in})</td>'
            f'<td style="color:#7f8c8d;font-size:11px;text-align:center;">{theme_nm}</td>'
            f'</tr>'
        )

    if not rows:
        return '<p style="color:#95a5a6;">(트래킹 종목 없음)</p>'

    def _th(label):
        return (f'<th onclick="sortTrkTable(this)" '
                f'style="cursor:pointer;user-select:none;">{label}</th>')

    header = (
        '<thead><tr>'
        + _th('Ticker') + _th('Name') + _th('체결강도') + _th('구분')
        + _th('오늘 등락률') + _th('누적 등락률') + _th('거래대금') + _th('누적거래대금') + _th('경과일') + _th('테마')
        + '</tr></thead>'
    )
    return (
        f'<table id="tracking-table" class="styled-table">{header}'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


# ── 히스토리 사이드바 (PC 전용) ────────────────────────────────────

def update_theme_history(daily_data: dict, fetched_at: str) -> dict:
    """당일 테마 상위 3개명 → theme_history.json (7일치 보관).

    휴장일에는 기록하지 않는다. 빈 항목이 들어가면 7일 창을 잡아먹어
    실제 거래일 히스토리가 밀려나기 때문.
    """
    try:
        date_str = fetched_at[:10]  # 'YYYY-MM-DD'
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")

    themes = daily_data.get("top_themes", [])
    names  = [shorten_theme(t.get("thema_nm", "")) for t in themes[:3]]

    if HISTORY_JSON.exists():
        try:
            history = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
        except Exception:
            history = {}
    else:
        history = {}

    if not is_kr_trading_day(date_str):
        print(f"[휴장일] {date_str} — 테마 히스토리 기록 생략, "
              f"직전 거래일({last_kr_trading_day(date_str)})까지 유지")
        return history

    history[date_str] = names

    # 최근 7일치만 유지
    sorted_keys = sorted(history.keys(), reverse=True)[:HISTORY_DAYS]
    history = {k: history[k] for k in sorted_keys}

    try:
        HISTORY_JSON.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠ theme_history.json 저장 실패: {e}")

    return history


def build_theme_history_sidebar(history: dict) -> str:
    """PC 전용 사이드바 HTML (날짜별 당일 테마 3개)"""
    if not history:
        return '<div style="font-size:0.8em;color:#aaa;padding:8px;">히스토리 누적 중...</div>'

    rows = ""
    for date_str in sorted(history.keys(), reverse=True):
        names = history[date_str]
        try:
            dt    = datetime.strptime(date_str, "%Y-%m-%d")
            label = f"{dt.month}/{dt.day}일"
        except Exception:
            label = date_str

        themes_str = " / ".join(names) if names else "-"
        rows += (
            f'<div class="hist-row">'
            f'<span class="hist-date">{label}</span>'
            f'<span class="hist-themes">{themes_str}</span>'
            f'</div>'
        )

    return f'<div class="history-box">{rows}</div>'


# ── 메인 ──────────────────────────────────────────────────────────

def main():
    data = load_naver_theme_data()
    fetched_at  = data.get("fetched_at", "")
    daily_data  = data.get("daily",  {})
    now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 전일 스냅샷 관리 + 로드 (같은 날 여러 번 실행해도 전일 데이터 보존)
    yesterday_data = roll_and_load_yesterday(daily_data, fetched_at)

    # ── 트래킹 + 히스토리 업데이트
    tracking_data = update_theme_stock_tracking(daily_data)
    history_data  = update_theme_history(daily_data, fetched_at)

    # ── HTML 섹션 생성
    # 당일 테마: 거래대금 합계 기준 내림차순 정렬
    def _theme_total_tv(theme):
        return sum(
            float((s.get("contract_strength") or {}).get("acc_trde_prica", 0) or 0)
            for s in theme.get("stocks", [])
        )
    daily_themes_sorted = sorted(daily_data.get("top_themes", []), key=_theme_total_tv, reverse=True)
    daily_data_for_html = {**daily_data, "top_themes": daily_themes_sorted}
    daily_html     = build_section(daily_data_for_html, "daily",  "📅 당일 테마")
    # ✅ tracking_data 전달 → 전일 종목 오늘 등락률 보완
    yesterday_html = build_yesterday_section(yesterday_data, daily_data, tracking_data)
    tracking_html  = build_theme_tracking_table(tracking_data)
    sidebar_html   = build_theme_history_sidebar(history_data)

    # 전일 테마 없을 때 안내 메시지
    if not yesterday_html:
        yesterday_html = '''
<div class="section" id="yesterday">
  <h3 class="sec-title">📅 전일 테마</h3>
  <p style="color:#95a5a6;font-size:0.85em;padding:6px 0;">
    (전일 데이터 누적 중 — 다음 실행 시 표시됩니다)
  </p>
</div>'''

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>주도 테마</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background: #f4f7f6;
  padding: 16px;
}}

/* ── 내비게이션 ── */
.top-nav-container {{ display: flex; margin-bottom: 10px; }}
.top-nav {{
  display: flex; background-color: #2c3e50;
  border-radius: 8px; overflow: hidden; width: fit-content;
}}
.nav-item {{
  padding: 7px 14px; color: #bdc3c7; text-align: center;
  cursor: pointer; font-weight: bold; text-decoration: none;
  transition: all 0.2s; font-size: 0.85em;
}}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}

/* ── 업데이트 시각 ── */
.update-bar {{ font-size: 0.82em; color: #888; margin-bottom: 10px; }}

/* ── 메인 레이아웃: 좌(콘텐츠) + 우(사이드바, PC 전용) ── */
.main-layout {{
  display: flex;
  gap: 16px;
  align-items: flex-start;
}}
.content-area {{ flex: 0 1 auto; min-width: 0; max-width: 100%; }}

/* ── PC 전용 사이드바 ── */
.sidebar {{
  width: 190px;
  min-width: 170px;
  flex-shrink: 0;
  padding-top: 2px;
}}
.sidebar-title {{
  font-size: 0.8em;
  font-weight: bold;
  color: #2c3e50;
  border-bottom: 2px solid #e74c3c;
  padding-bottom: 3px;
  margin-bottom: 6px;
}}
.history-box {{
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  padding: 6px 10px;
}}
.hist-row {{
  padding: 5px 0;
  border-bottom: 1px solid #f0f0f0;
  line-height: 1.5;
}}
.hist-row:last-child {{ border-bottom: none; }}
.hist-date {{
  display: block;
  font-size: 0.75em;
  font-weight: bold;
  color: #e74c3c;
}}
.hist-themes {{
  display: block;
  font-size: 0.76em;
  color: #555;
  word-break: keep-all;
  line-height: 1.4;
}}

/* 모바일: 사이드바 숨김 */
@media (max-width: 700px) {{
  .sidebar {{ display: none !important; }}
}}

/* ── 섹션 제목 ── */
.sec-title {{
  font-size: 0.95em; font-weight: bold; color: #2c3e50;
  border-bottom: 2px solid #3498db;
  padding-bottom: 4px; margin-bottom: 8px;
}}

/* 전일 테마 섹션 타이틀: 주황 테두리로 구분 */
#yesterday .sec-title {{
  border-bottom-color: #e67e22;
  color: #d35400;
}}

/* ── 카드 행 ── */
.cards-row {{
  display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px;
}}

/* ── 테마 카드 ── */
.theme-card {{
  background: white; border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.10);
  min-width: 215px; max-width: 280px; flex: 1;
  overflow: hidden; transition: box-shadow 0.2s;
}}
.theme-card:hover {{ box-shadow: 0 4px 14px rgba(0,0,0,0.16); }}
.card-header {{ padding: 8px 10px 6px 10px; background: #fafafa; border-bottom: 1px solid #eee; }}
.card-title-line {{ display: flex; align-items: center; gap: 5px; margin-bottom: 2px; }}
.medal {{ font-size: 1em; }}
.theme-name {{
  font-size: 0.88em; font-weight: bold; color: #2c3e50;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1;
}}
.stk-num {{ font-size: 0.72em; color: #999; white-space: nowrap; }}
.card-rate {{ font-size: 1.05em; font-weight: bold; margin-top: 1px; padding-left: 22px; }}
.stock-list {{ padding: 6px 10px 8px 10px; }}
.stock-row {{
  display: flex; align-items: center; gap: 4px;
  padding: 3px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.82em;
}}
.stock-row:last-child {{ border-bottom: none; }}
.stock-ticker {{
  font-size: 0.78em; color: #2980b9; font-weight: bold;
  white-space: nowrap; min-width: 50px;
}}
.stock-name {{ flex: 1; color: #333; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 60px; }}
.stock-rate {{ font-weight: bold; white-space: nowrap; min-width: 52px; text-align: right; }}
.stock-cs {{ white-space: nowrap; min-width: 48px; text-align: right; }}
.stock-tv {{ white-space: nowrap; min-width: 50px; text-align: right; margin-right: 2px; }}

/* ── 트래킹 테이블 ── */
.styled-table {{
  width: max-content; border-collapse: collapse;
  margin: 8px 0 16px 0; font-size: 12px;
  background: white; box-shadow: 0 2px 6px rgba(0,0,0,0.08);
  border-radius: 8px; overflow: hidden;
}}
.styled-table thead tr {{
  background: linear-gradient(135deg, #8e44ad, #6c3483);
  color: #fff; text-align: center;
}}
.styled-table th, .styled-table td {{
  padding: 5px 8px; border-bottom: 1px solid #f0f0f0;
  white-space: nowrap; text-align: center;
}}
.styled-table td.narrow {{ font-weight: bold; color: #2980b9; text-align: left; }}
.styled-table td.name-col {{ text-align: left; max-width: 90px; overflow: hidden; text-overflow: ellipsis; }}
.styled-table tbody tr:hover {{ background: #fafafa; }}

/* ── 섹션 ── */
.section {{ margin-bottom: 6px; }}
.tracking-section {{ margin-top: 14px; overflow-x: auto; }}
.tracking-title {{
  font-size: 0.92em; font-weight: bold; color: #8e44ad;
  border-bottom: 2px solid #8e44ad;
  padding-bottom: 4px; margin-bottom: 8px;
}}

/* ── 반응형 (모바일) ── */
@media (max-width: 600px) {{
  body {{ padding: 10px; }}

  /* 카드: 가로 스크롤 가능하게 */
  .cards-row {{
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    gap: 8px;
    padding-bottom: 6px;
  }}
  .theme-card {{
    min-width: 240px;
    max-width: 240px;
    flex-shrink: 0;
  }}

  /* 종목행 안에서 ticker + 이름 잘 보이게 */
  .stock-row {{ font-size: 0.80em; gap: 3px; }}
  .stock-ticker {{ min-width: 46px; font-size: 0.76em; }}
  .stock-name {{ min-width: 55px; }}
  .stock-rate {{ min-width: 48px; font-size: 0.80em; }}
  .stock-cs {{ min-width: 38px; font-size: 0.80em; }}
  .stock-tv {{ min-width: 35px; font-size: 0.78em; }}

  .styled-table {{ font-size: 11px; }}
  .styled-table th, .styled-table td {{ padding: 4px 6px; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
/* === Naver Chart Popup === */
#naverChartPopup {{
  display: none; position: fixed; z-index: 99999;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; max-height: 90vh; overflow-y: auto;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border: none;
  background: #e74c3c; color: white; border-radius: 50%;
  font-size: 18px; cursor: pointer; flex-shrink: 0;
}}
.popup-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; margin-left: 1em; }}
.popup-link:hover {{ text-decoration: underline; }}
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.chart-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fafafa; }}
.chart-card-header {{ display: none; }}
.chart-card-title {{ font-size: 12px; font-weight: 700; color: #334155; }}
.chart-status {{ font-size: 11px; color: #94a3b8; }}
.chart-wrap {{ position: relative; width: 100%; height: 285px; background: white; }}
.chart-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: white; }}
.chart-loading {{ display: none; position: absolute; inset: 0; background: rgba(255,255,255,0.75); align-items: center; justify-content: center; font-size: 12px; color: #64748b; }}
.chart-loading.show {{ display: flex; }}
@media (max-width: 767px) {{
  #naverChartPopup {{
    position: fixed !important;
    left: 2vw !important;
    top: 50% !important;
    transform: translateY(-50%);
    width: 96vw !important;
    max-height: 80dvh !important;
    overflow-y: auto !important;
    padding: 8px !important;
    box-sizing: border-box;
  }}
  .charts-grid {{ grid-template-columns: 1fr; gap: 6px; }}
  .chart-wrap {{ height: 220px; }}
  #naverPopupClose {{ display: flex !important; }}
}}
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopup {{ width: min(96vw, 860px); left: 2vw !important; }}
  .charts-grid {{ grid-template-columns: 1fr; }}
  .chart-wrap {{ height: 260px; }}
}}
</style>
</head>
<body>

<div class="top-nav-container">
  <div class="top-nav">
    <a href="kor_theme.html" class="nav-item active">주도테마</a>
    <a href="kor_150.html"   class="nav-item">KR150</a>
    <a href="kor_stock.html" class="nav-item">KR전종목</a>
  </div>
</div>

<div class="update-bar">
  📡 데이터: {fetched_at} &nbsp;|&nbsp; 페이지: {now}
</div>

<div class="main-layout">

  <!-- 좌: 메인 콘텐츠 -->
  <div class="content-area">
    {daily_html}
    {yesterday_html}

    <div class="tracking-section">
      <h3 class="tracking-title">📊 테마주 트래킹 (2주)</h3>
      {tracking_html}
    </div>
  </div>

  <!-- 우: PC 전용 사이드바 -->
  <div class="sidebar">
    <div class="sidebar-title">📅 당일 테마 히스토리</div>
    {sidebar_html}
  </div>

</div>

<script>
(function () {{
  var _col = -1, _asc = true;
  window.sortTrkTable = function (th) {{
    var table = document.getElementById('tracking-table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    var rows  = Array.from(tbody.querySelectorAll('tr'));
    var col   = th.cellIndex;
    _asc = (_col === col) ? !_asc : true;
    _col = col;

    function val(row) {{
      var txt = row.cells[col].textContent.replace(/,/g, '').trim();
      // 부호 포함 숫자 추출 (+28.30%, 1101억, 1일 등)
      var m = txt.match(/([+-]?\\d+\\.?\\d*)/);
      return m ? parseFloat(m[1]) : txt.toLowerCase();
    }}

    rows.sort(function (a, b) {{
      var va = val(a), vb = val(b);
      if (typeof va === 'number' && typeof vb === 'number') return _asc ? va - vb : vb - va;
      return _asc ? (va < vb ? -1 : va > vb ? 1 : 0)
                  : (va > vb ? -1 : va < vb ? 1 : 0);
    }});
    rows.forEach(function (r) {{ tbody.appendChild(r); }});
  }};
}})();
</script>
<div id="legacyNaverChartPopup">
  <div class="popup-header">
    <button id="naverPopupClose" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-card-header"><div class="chart-card-title">당일 선차트 (1일)</div><div class="chart-status" id="statusIntraday">대기중</div></div>
      <div class="chart-wrap"><img id="imgIntraday" alt="당일 차트"><div class="chart-loading" id="loadingIntraday">불러오는 중...</div></div>
    </div>
    <div class="chart-card">
      <div class="chart-card-header"><div class="chart-card-title">일봉</div><div class="chart-status" id="statusDaily">대기중</div></div>
      <div class="chart-wrap"><img id="imgDaily" alt="일봉 차트"><div class="chart-loading" id="loadingDaily">불러오는 중...</div></div>
    </div>
  </div>
</div>
<script>
(function () {{ return;
  var popup=document.getElementById('naverChartPopup'),popupTitle=document.getElementById('popupTitle'),popupLink=document.getElementById('popupLink');
  var imgIntraday=document.getElementById('imgIntraday'),imgDaily=document.getElementById('imgDaily');
  var loadingIntraday=document.getElementById('loadingIntraday'),loadingDaily=document.getElementById('loadingDaily');
  var statusIntraday=document.getElementById('statusIntraday'),statusDaily=document.getElementById('statusDaily');
  var closeBtn=document.getElementById('naverPopupClose'),hoverTimer=null,pinned=false;
  function openPopup(){{popup.style.display='block';document.body.classList.add('naver-popup-open');}}
  function closePopup(){{popup.style.display='none';document.body.classList.remove('naver-popup-open');pinned=false;}}
  var TS=Date.now();
  function withTs(u){{return u+'?t='+TS;}}
  function intradayUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/area/day/'+c+'.png');}}
  function dailyCandleUrl(c){{return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'+c+'.png');}}
  function itemPageUrl(c){{return 'https://finance.naver.com/item/main.naver?code='+c;}}
  function setStatus(el,t,col){{el.textContent=t;el.style.color=col||'#94a3b8';}}
  function loadInto(img,ld,st,url,lbl){{
    ld.classList.add('show');img.style.opacity='0.35';setStatus(st,'로딩중...','#f59e0b');
    var p=new Image();
    p.onload=function(){{img.src=url;img.style.opacity='1';ld.classList.remove('show');setStatus(st,'로드 성공','#22c55e');}};
    p.onerror=function(){{img.removeAttribute('src');img.style.opacity='1';ld.classList.remove('show');setStatus(st,lbl+' 실패','#ef4444');}};
    p.src=url;
  }}
  function loadCharts(code,name){{popupTitle.textContent=code+'  '+(name||'');popupLink.href=itemPageUrl(code);loadInto(imgIntraday,loadingIntraday,statusIntraday,intradayUrl(code),'당일');loadInto(imgDaily,loadingDaily,statusDaily,dailyCandleUrl(code),'일봉');}}
  function placePopup(cx,cy){{
    var isMobile=window.innerWidth<=767;
    if(isMobile)return;
    var rW=Math.min(860,window.innerWidth-20),rH=window.innerWidth<=1000?650:430,x=cx+18,y=cy+18;
    if(x+rW>window.innerWidth-8)x=cx-rW-12;
    if(y+rH>window.innerHeight-8)y=cy-rH-12;
    if(x<8)x=8;if(y<8)y=8;
    popup.style.left=x+'px';popup.style.top=y+'px';
    popup.style.transform='none';
  }}
  if(closeBtn)closeBtn.addEventListener('click',closePopup);
  popup.addEventListener('mouseenter',function(){{pinned=true;}});
  popup.addEventListener('mouseleave',function(){{pinned=false;closePopup();}});
  document.querySelectorAll('td[data-code], .naver-trigger[data-code]').forEach(function(el){{
    var hot=(el.tagName==='TD'&&el.nextElementSibling&&el.nextElementSibling.tagName==='TD')?el.nextElementSibling:el;
    hot.addEventListener('mouseenter',function(e){{
      if(window.innerWidth<=767)return;
      var code=el.dataset.code,name=el.dataset.name||'';
      clearTimeout(hoverTimer);
      hoverTimer=setTimeout(function(){{placePopup(e.clientX,e.clientY);openPopup();loadCharts(code,name);}},140);
    }});
    hot.addEventListener('mousemove',function(e){{
      if(window.innerWidth<=767)return;
      if(popup.style.display==='block'&&!pinned)placePopup(e.clientX,e.clientY);
    }});
    hot.addEventListener('mouseleave',function(){{
      if(window.innerWidth<=767)return;
      clearTimeout(hoverTimer);setTimeout(function(){{if(!pinned)closePopup();}},120);
    }});
    hot.addEventListener('click',function(e){{
      e.stopPropagation();
      var code=el.dataset.code,name=el.dataset.name||'';
      if(popup.style.display==='block'&&popupTitle.textContent.startsWith(code)){{closePopup();return;}}
      placePopup(e.clientX,e.clientY);openPopup();loadCharts(code,name);
    }});
  }});
  (function(){{
    var seen={{}},queue=[];
    document.querySelectorAll('td[data-code], .naver-trigger[data-code]').forEach(function(el){{
      var c=el.dataset.code;if(!c||seen[c])return;seen[c]=true;queue.push(c);
    }});
    var idx=0,CONCURRENCY=3;
    function next(){{
      if(idx>=queue.length)return;
      var c=queue[idx++],done=0;
      function step(){{if(++done>=2)next();}}
      [intradayUrl(c),dailyCandleUrl(c)].forEach(function(u){{var im=new Image();im.onload=step;im.onerror=step;im.src=u;}});
    }}
    setTimeout(function(){{for(var i=0;i<CONCURRENCY&&i<queue.length;i++)next();}},300);
  }})();
  document.addEventListener('click',function(e){{
    if(window.innerWidth<=767&&popup.style.display==='block'){{
      if(!popup.contains(e.target))closePopup();
    }} else if(window.innerWidth>767){{
      if(!pinned&&!popup.contains(e.target)&&!e.target.closest('[data-code]'))closePopup();
    }}
  }});
  // === D/S 단축키 (D/↓=다음, S/↑=이전, Tab/ESC=닫기) · PNG라 A(슈퍼트렌드)는 제외 ===
  (function(){{
    var SEL = 'td[data-code], .naver-trigger[data-code]';
    var curEl = null;
    document.querySelectorAll(SEL).forEach(function(el){{
      el.addEventListener('mouseenter', function(){{ curEl = el; }});
      el.addEventListener('click', function(){{ curEl = el; }});
    }});
    try {{ popup.setAttribute('tabindex','-1'); }} catch(e){{}}
    var _open = openPopup;
    openPopup = function(){{ _open.apply(this, arguments);
      try {{ if (document.activeElement === document.body || document.activeElement === null) popup.focus({{preventScroll:true}}); }} catch(e){{}} }};
    function unpinOnMove(e){{ if (popup.contains(e.target)) return;
      document.removeEventListener('mousemove', unpinOnMove); pinned = false;
      setTimeout(function(){{ if (!pinned) closePopup(); }}, 120); }}
    function kbPin(){{ pinned = true;
      document.removeEventListener('mousemove', unpinOnMove);
      document.addEventListener('mousemove', unpinOnMove); }}
    /* === SWIPE-NAV-INJECTED: 모바일 좌/우 스와이프 → 키보드 D/S 재사용 (PC 무영향) === */
    (function(){{
      if(window.__swipeNavInit) return; window.__swipeNavInit=true;
      function isTouch(){{ return window.matchMedia('(hover: none)').matches || window.innerWidth<=767; }}
      var sx=0, sy=0, st=0, tr=false;
      document.addEventListener('touchstart', function(e){{
        if(!isTouch() || !e.touches || e.touches.length!==1){{ tr=false; return; }}
        var t=e.touches[0]; sx=t.clientX; sy=t.clientY; st=Date.now(); tr=true;
      }}, true);
      document.addEventListener('touchend', function(e){{
        if(!tr) return; tr=false;
        var t=e.changedTouches && e.changedTouches[0]; if(!t) return;
        var dx=t.clientX-sx, dy=t.clientY-sy, dt=Date.now()-st;
        if(dt>800 || Math.abs(dx)<55 || Math.abs(dx)<Math.abs(dy)*1.6) return;
        var key = dx<0 ? 'd' : 's';
        try{{ document.dispatchEvent(new KeyboardEvent('keydown', {{key:key, bubbles:true, cancelable:true}})); }}catch(err){{}}
      }}, true);
    }})();
    document.addEventListener('keydown', function(e){{
      if (popup.style.display !== 'block') return;
      var tg = e.target, tag = tg && tg.tagName;
      if (tag==='INPUT'||tag==='TEXTAREA'||(tg&&tg.isContentEditable)) return;
      var k = e.key;
      if (k==='Tab'||k==='Escape'){{ e.preventDefault(); closePopup(); return; }}
      var dir = 0;
      if (k==='s'||k==='S'||k==='ArrowUp') dir=-1;
      else if (k==='d'||k==='D'||k==='ArrowDown') dir=1;
      if (dir===0 || !curEl) return;
      e.preventDefault();
      var all = Array.prototype.slice.call(document.querySelectorAll(SEL));
      var i = all.indexOf(curEl);
      if (i<0) return;
      i += dir;
      if (i<0||i>=all.length) return;
      var nt = all[i];
      kbPin(); curEl = nt;
      loadCharts(nt.dataset.code, nt.dataset.name||'');
      nt.scrollIntoView({{block:'nearest'}});
    }});
  }})();
}})();
</script>
</body>
</html>
"""

    import re as _re
    page = _re.sub(
        r"\n<div id=\"legacyNaverChartPopup\">.*?</script>\s*</body>\s*</html>\s*$",
        "\n</body>\n</html>",
        page,
        flags=_re.S,
    )
    from chart_popup_v2 import build_chart_popup as _bcp_v2
    _codes = sorted(set(_re.findall(r'data-code="([^"]+)"', page)))
    page = page.replace(
        "</body>",
        _bcp_v2(_codes, cache_key="theme") + "\n</body>",
        1,
    )
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] kor_theme.html 생성 완료: {OUT_HTML} (V2 5분봉+일봉 {len(_codes)}종목)")


if __name__ == "__main__":
    main()
