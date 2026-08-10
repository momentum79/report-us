# make_index_coin.py
# 코인 게시판 - 카드섹션 + 테이블 (요약 게시판 형태)
# 입력: D:\py\coin\0txt\report_coin.json  (upbit_total.py 가 생성)
# 출력: D:\py\report-us\coin.html

import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

# 회사망 SSL 중간자검사(MITM) 대응: 파이썬 SSL이 윈도우 인증서 저장소(회사 루트CA 포함)를
# 신뢰하게 주입 → 회사에서도 업비트 캔들 fetch 성공(집에선 MITM 없어 그대로 통과).
# 회사판 데이트레이더(company_ssl_inject_trader.py)와 동일한 방식.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # truststore 미설치(집 등)면 기본 검증 사용 — MITM 없으니 정상

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import numpy as np
    import pandas as pd
    from coloryp_core import check_coloryp_logic
    _TREND_OK = True
except Exception as _e:  # 추세배경 미사용 환경에서도 차트는 동작
    print(f"   [warn] 추세배경 모듈 로드 실패(추세배경 생략): {_e}")
    _TREND_OK = False

JSON_PATH = Path(r"D:\py\coin\0txt\report_coin.json")
OUT_HTML  = Path(r"D:\py\report-us\coin.html")

UPBIT_URL = "https://www.upbit.com/exchange?code=CRIX.UPBIT.KRW-{sym}"

# 차트 임베드용 캔들 개수 (빌드 시점에 서버에서 미리 받아 HTML에 박아넣음)
CANDLE_COUNT_D = 200
CANDLE_COUNT_5 = 200
_UPBIT_BASE = "https://api.upbit.com/v1/candles/"


def _fetch_candles(kind, sym, count):
    """업비트 캔들 1종(days / minutes/5) 조회 → 실패 시 None."""
    url = _UPBIT_BASE + kind
    for attempt in range(3):
        try:
            r = requests.get(url, params={"market": f"KRW-{sym}", "count": count},
                             timeout=10)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:          # 서버측 초당 제한 → 잠깐 쉬고 재시도
                time.sleep(0.5)
                continue
            return None
        except requests.RequestException:
            time.sleep(0.3)
    return None


def _add_trend_states(bars):
    """봉 리스트에 추세상태('t': LIME/GREEN/RED/PURPLE) 부여 (단타 게시판과 동일 공식)."""
    if not _TREND_OK or not bars or len(bars) < 60:
        return bars
    try:
        df = pd.DataFrame(bars)
        if isinstance(bars[0]["time"], (int, float)):
            idx = pd.to_datetime(df["time"], unit="s")
        else:
            idx = pd.to_datetime(df["time"])
        calc = check_coloryp_logic(
            df[["open", "high", "low", "close"]].set_index(idx))
        angle_all = (calc[[f"m{i}ang" for i in range(5)]] <= 0).all(axis=1)
        angle_4 = (calc[[f"m{i}ang" for i in range(4)]] <= 0).all(axis=1)
        is_lime = calc["lime_final"]
        is_green = (calc["HLv99"] >= 1) & (calc["HLv71"] == 1) & ~is_lime
        is_red = (((calc["HLv99"] <= -1) & (calc["HLv7"] == -1) & (calc["HLv71"] == -1))
                  | (calc["ang_sum"] == -5) | angle_all)
        is_purple = ((calc["HLv99"] <= -1) & (calc["HLv71"] == -1)) | angle_4
        states = np.select([is_lime, is_green, is_red, is_purple],
                           ["LIME", "GREEN", "RED", "PURPLE"], default="NONE")
        for i, b in enumerate(bars):
            if states[i] != "NONE":
                b["t"] = str(states[i])
    except Exception as e:
        print(f"   [warn] 추세배경 계산 생략: {e}")
    return bars


def fetch_coin_candle_data(symbols):
    """렌더된 심볼들의 일봉/5분봉을 빌드 시점에 받아 JS가 기대하는 형태로 가공.

    반환: { sym: {"d":[일봉...오름차순], "m":[5분봉...오름차순]} }
      d: {time:'YYYY-MM-DD', open,high,low,close,volume}
      m: {time:unix초(KST 벽시계를 UTC로 간주, JS와 동일), open,high,low,close,volume}
    """
    out = {}
    ok = 0
    for sym in symbols:
        raw_d = _fetch_candles("days", sym, CANDLE_COUNT_D)
        time.sleep(0.12)                       # 업비트 초당 제한(≈10req/s) 여유
        raw_5 = _fetch_candles("minutes/5", sym, CANDLE_COUNT_5)
        time.sleep(0.12)
        if not isinstance(raw_d, list) or not isinstance(raw_5, list):
            print(f"   [warn] {sym} 캔들 로드 실패 - 건너뜀")
            continue
        d = [{
            "time": x["candle_date_time_kst"][:10],
            "open": x["opening_price"], "high": x["high_price"],
            "low": x["low_price"], "close": x["trade_price"],
            "volume": round(x["candle_acc_trade_volume"], 4),
        } for x in reversed(raw_d)]
        m = [{
            "time": int(datetime.fromisoformat(x["candle_date_time_kst"])
                        .replace(tzinfo=timezone.utc).timestamp()),
            "open": x["opening_price"], "high": x["high_price"],
            "low": x["low_price"], "close": x["trade_price"],
            "volume": round(x["candle_acc_trade_volume"], 4),
        } for x in reversed(raw_5)]
        _add_trend_states(d)
        _add_trend_states(m)
        out[sym] = {"d": d, "m": m}
        ok += 1
    print(f"   [chart] 차트 캔들 임베드: {ok}/{len(symbols)}개 종목")
    return out


# ── 유틸 ────────────────────────────────────────────────────────────────────
def fmt_value(won):
    """원 단위 거래대금 → 억/조 단위 문자열"""
    try:
        won = float(won)
    except (TypeError, ValueError):
        return "-"
    if won >= 1e12:
        return f"{won/1e12:.2f}조"
    if won >= 1e8:
        return f"{won/1e8:,.0f}억"
    return f"{won:,.0f}"


SURGE_DIR = Path(r"D:\py\coin")


def load_today_surge():
    """오늘 날짜와 일치하는 open_surge_YYYYMMDD.json 만 로드 (없으면 None)."""
    today = datetime.now().strftime("%Y%m%d")
    p = SURGE_DIR / f"open_surge_{today}.json"
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except (OSError, json.JSONDecodeError):
        return None


def fmt_price_won(p):
    """현재가 포맷 — upbit_open_surge.py fmt_price 와 동일 규칙."""
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "-"
    if p >= 100:
        return f"{p:,.0f}원"
    if p >= 1:
        return f"{p:,.2f}원"
    if p >= 0.01:
        return f"{p:.4f}원"
    return f"{p:.8f}원"


def sym_link(sym, name=""):
    # 심볼 링크: 차트 트리거 제거(data-coin 없음) → 심볼 hover 시 차트 안 뜸.
    # 차트는 종목명(name_link)에서 뜬다. 심볼은 업비트 링크로만 유지.
    import html as _html
    href = UPBIT_URL.format(sym=sym)
    return (f'<a class="sym" href="{href}" target="_blank" rel="noopener">{_html.escape(sym)}</a>')


def name_link(sym, name=""):
    # 종목명 링크: 차트 hover 트리거(.sym[data-coin]). 심볼 대신 종목명에 마우스 → 차트.
    import html as _html
    href = UPBIT_URL.format(sym=sym)
    label = name if name else sym
    return (f'<a class="sym" data-coin="{_html.escape(sym)}" data-name="{_html.escape(name or sym)}" '
            f'href="{href}" target="_blank" rel="noopener">{_html.escape(label)}</a>')


def new_sig_html(text):
    if not text or text == "-":
        return ""
    return f'<span class="newsig">{text}</span>'


def sco_class(sco):
    try:
        sco = float(sco)
    except (TypeError, ValueError):
        return ""
    if sco >= 12:
        return "sco-hi"
    if sco < 0:
        return "sco-lo"
    return "sco-mid"


# ── 카드 (Row1) ─────────────────────────────────────────────────────────────
def card_distribution(d):
    total    = d.get("total", 0)
    analyzed = d.get("analyzed", 0)
    rows = [
        ("sco ≥ 12", d.get("strong", 0),  d.get("strong_pct", 0),  "bar-hi"),
        ("0 ~ 12",   d.get("neutral", 0), d.get("neutral_pct", 0), "bar-mid"),
        ("sco < 0",  d.get("weak", 0),    d.get("weak_pct", 0),    "bar-lo"),
    ]
    body = (f'<div class="dist-head">전체 <b>{total}</b>개 / 분석 '
            f'<b>{analyzed}</b>개</div>')
    for label, cnt, pct, cls in rows:
        body += (
            '<div class="dist-row">'
            f'<span class="dist-label">{label}</span>'
            '<span class="dist-barwrap">'
            f'<span class="dist-bar {cls}" style="width:{max(pct,2)}%"></span>'
            '</span>'
            f'<span class="dist-cnt">{cnt}개 <small>({pct}%)</small></span>'
            '</div>'
        )
    return card("📊 SCO 기준 종목 분포", "#34495e", body, raw=True, cls="card-dist")


def card_symbol_list(title, color, items, value_key="value"):
    """심볼+종목명+거래대금 리스트 카드 (SPOT/주도주)"""
    if not items:
        return card(title, color, '<div class="empty">없음</div>', raw=True)
    rows = ""
    for it in items[:10]:
        val = fmt_value(it.get(value_key)) if value_key else ""
        rows += (
            '<div class="lirow">'
            f'<span class="liname">{sym_link(it["symbol"], it.get("name",""))} '
            f'<small>{name_link(it["symbol"], it.get("name",""))}</small></span>'
            f'<span class="lival">{val}</span>'
            '</div>'
        )
    return card(title, color, rows, raw=True)


def card_high52w(items):
    if not items:
        return card("📈 52주 신고가 근접", "#16a085",
                    '<div class="empty">없음</div>', raw=True)
    chips = "".join(f'<span class="chip">{name_link(s, s)}</span>' for s in items)
    return card("📈 52주 신고가 근접", "#16a085",
                f'<div class="chips">{chips}</div>', raw=True)


# ── 테이블 (Row2 / Row3) ────────────────────────────────────────────────────
def table_top10(items):
    if not items:
        return card("🏅 Sco Top10", "#2c3e50",
                    '<div class="empty">없음</div>', raw=True)
    head = ('<tr><th>심볼</th><th>종목명</th><th class="r">SCO</th>'
            '<th class="r">수익률</th><th>신호</th></tr>')
    body = ""
    for it in items[:10]:
        rtn = it.get("rtn", 0)
        rtn_cls = "up" if rtn > 0 else ("down" if rtn < 0 else "")
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{name_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="r {sco_class(it.get("sco"))}">{it.get("sco","")}</td>'
            f'<td class="r {rtn_cls}">{rtn:+.2f}%</td>'
            f'<td>{new_sig_html(it.get("new_signal"))}</td></tr>'
        )
    return card("🏅 Sco Top10", "#2c3e50",
                f'<table class="t">{head}{body}</table>', raw=True)


def table_signal(title, color, items):
    """심볼/종목명/거래대금/SCO 테이블 (LIME/MOM/Rocket/GANN/JUNG)"""
    if not items:
        return card(title, color, '<div class="empty">없음</div>', raw=True)
    head = ('<tr><th>심볼</th><th>종목명</th>'
            '<th class="r">거래대금</th><th class="r">SCO</th></tr>')
    body = ""
    for it in items[:10]:
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{name_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="r">{fmt_value(it.get("value"))}</td>'
            f'<td class="r {sco_class(it.get("sco"))}">{it.get("sco","")}</td></tr>'
        )
    return card(title, color, f'<table class="t">{head}{body}</table>', raw=True)


def table_low(items):
    if not items:
        return card("📉 LOW 저점 신호", "#e67e22",
                    '<div class="empty">없음</div>', raw=True)
    head = ('<tr><th>심볼</th><th>종목명</th>'
            '<th class="r">거래대금</th><th class="c">저</th><th class="c">저2</th></tr>')
    body = ""
    for it in items[:10]:
        jeo  = it.get("jeo", "-")
        jeo2 = it.get("jeo2", "-")
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{name_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="r">{fmt_value(it.get("value"))}</td>'
            f'<td class="c">{"🔵" if jeo!="-" else ""}</td>'
            f'<td class="c">{"🟣" if jeo2!="-" else ""}</td></tr>'
        )
    return card("📉 LOW 저점 신호", "#e67e22",
                f'<table class="t">{head}{body}</table>', raw=True)


def table_breakout(items):
    """심볼/종목명/거래대금 테이블 (횡보돌파)"""
    if not items:
        return card("📊 횡보돌파 신호 종목", "#16a085",
                    '<div class="empty">없음</div>', raw=True)
    head = ('<tr><th>심볼</th><th>종목명</th>'
            '<th class="r">거래대금</th></tr>')
    body = ""
    for it in items[:10]:
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{name_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="r">{fmt_value(it.get("value"))}</td></tr>'
        )
    return card("📊 횡보돌파 신호 종목", "#16a085",
                f'<table class="t">{head}{body}</table>', raw=True)


# ── 코인 VCP (coin_vcp_scanner.py 산출) ─────────────────────────────────────
VCP_JSON = Path(r"D:\py\coin\0txt\report_coin_vcp.json")


def load_coin_vcp():
    if not VCP_JSON.exists():
        return None
    try:
        with open(VCP_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _grade_badge(g):
    g = (g or "").strip().upper()
    return f'<span class="grade g-{g}">{g}</span>' if g in ("A", "B", "C", "D") else ""


def _vcp_table(rows):
    head = ('<tr><th>심볼</th><th>종목명</th><th class="r">현재가</th><th class="r">등락률</th>'
            '<th class="c">등급</th><th class="r">점수</th><th class="r">피벗</th>'
            '<th class="r">거리</th><th class="r">거래량비</th><th>수축패턴</th></tr>')
    body = ""
    for it in rows:
        chg = it.get("chg_pct") or 0
        dist = it.get("pivot_dist_pct") or 0
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{name_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="r">{fmt_price_won(it.get("close_now"))}</td>'
            f'<td class="r {"up" if chg > 0 else ("down" if chg < 0 else "")}">{chg:+.2f}%</td>'
            f'<td class="c">{_grade_badge(it.get("setup_grade"))}</td>'
            f'<td class="r">{it.get("setup_score", "")}</td>'
            f'<td class="r">{fmt_price_won(it.get("pivot"))}</td>'
            f'<td class="r {"up" if dist > 0 else "down"}">{dist:+.2f}%</td>'
            f'<td class="r">{it.get("volume_ratio", 0):.2f}배</td>'
            f'<td>{it.get("contractions", "")}</td></tr>'
        )
    return f'<table class="t vcp-t">{head}{body}</table>'


def _vcp_tracker_table(rows):
    head = ('<tr><th>심볼</th><th>종목명</th><th>진입일</th><th class="r">진입가</th>'
            '<th class="r">현재가</th><th class="r">수익률</th><th class="r">최고</th>'
            '<th class="r">최저</th><th class="r">경과</th><th class="r">잔여</th>'
            '<th class="c">결과</th></tr>')
    body = ""
    for it in rows:
        ret = it.get("ret_pct") or 0
        left = it.get("days_left") or 0
        res = it.get("result")
        if res == "익절":
            res_html = '<span class="tag tag-win">익절</span>'
        elif res == "손절":
            res_html = '<span class="tag tag-loss">손절</span>'
        elif res == "기간마감":
            res_html = '<span class="tag tag-flat">기간마감</span>'
        else:
            res_html = '<span class="tag tag-open">추적중</span>'
        left_html = f"D-{left}" if not it.get("closed") else "-"
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name",""))}</td>'
            f'<td class="nm">{name_link(it["symbol"], it.get("name",""))}</td>'
            f'<td>{it.get("entry_date","")}</td>'
            f'<td class="r">{fmt_price_won(it.get("entry_price"))}</td>'
            f'<td class="r">{fmt_price_won(it.get("cur_price"))}</td>'
            f'<td class="r {"up" if ret > 0 else ("down" if ret < 0 else "")}"><b>{ret:+.2f}%</b></td>'
            f'<td class="r up">{it.get("max_ret", 0):+.2f}%</td>'
            f'<td class="r down">{it.get("min_ret", 0):+.2f}%</td>'
            f'<td class="r">{it.get("elapsed", 0)}일</td>'
            f'<td class="r">{left_html}</td>'
            f'<td class="c">{res_html}</td></tr>'
        )
    return f'<table class="t vcp-t">{head}{body}</table>'


def _vcp_section(title, desc, rows, empty_msg, tracker=False):
    if rows:
        inner = _vcp_tracker_table(rows) if tracker else _vcp_table(rows)
    else:
        inner = f'<div class="empty">{empty_msg}</div>'
    return (f'<div class="vcp-sec"><div class="vcp-sec-t">{title}'
            f'<span class="vcp-cnt">{len(rows)}개</span></div>'
            f'<div class="vcp-sec-d">{desc}</div>{inner}</div>')


def build_vcp_block(v):
    """미국 VCP 게시판(①돌파/②대기/③추격주의/④추적) 구조를 코인에 적용."""
    if not v:
        return ""
    p = v.get("params", {})
    c = v.get("counts", {})
    peak = p.get("peak_weeks_ago") or ["-", "-"]
    btc = v.get("btc_trend")
    btc_html = ('<span class="badge-btc bt-up">BTC 상승</span>' if btc
                else '<span class="badge-btc bt-dn">BTC 하락</span>')

    meta = (f'주봉 {p.get("lookback_weeks","-")}주 룩백 · 고점 {peak[0]}~{peak[1]}주전 · '
            f'고점±{p.get("near_high_pct","-"):g}% · 돌파 거래량 {p.get("volume_surge_ratio","-")}배 · '
            f'추적 {p.get("track_stop_pct","-"):g}% / +{p.get("track_tp_pct","-"):g}% / '
            f'{p.get("track_max_days","-")}일')
    diag = (f'스캔 {v.get("universe",0)}개 → 고점위치 탈락 {c.get("f1",0)} · '
            f'고점근접 탈락 {c.get("f2",0)} · 수축패턴 탈락 {c.get("vcp",0)} · '
            f'피벗없음 {c.get("no_pivot",0)} · 이력부족 {c.get("no_data",0)} → 최종 {c.get("final",0)}개')

    secs = "".join([
        _vcp_section("① VCP 돌파", "피벗을 거래량 동반 돌파한 상태. 실제 매수 후보는 이것뿐입니다.",
                     v.get("breakout", []), "오늘 돌파 종목이 없습니다."),
        _vcp_section("② 피벗 대기", "매수 대상이 아니라 피벗 돌파를 기다리는 감시 대상입니다.",
                     v.get("pre", []), "오늘 피벗 대기 종목이 없습니다."),
        _vcp_section("③ 돌파 약함 / 추격주의", "거래량 미달 돌파(WEAK) 또는 돌파 후 확장(EXTENDED). 추격 금지.",
                     v.get("watch", []), "오늘 추격주의 종목이 없습니다."),
        _vcp_section("④ 돌파 추적", "①에 뜬 종목을 그날 가격 기준으로 자동 등록해 성과를 따라갑니다. 주문과는 연결되어 있지 않습니다.",
                     v.get("tracker", []), "추적 중인 종목이 없습니다 — ①에 종목이 뜨면 자동 등록됩니다.",
                     tracker=True),
    ])
    return (f'<div class="vcp-wrap"><div class="vcp-head">'
            f'<span class="vcp-title">🎯 코인 VCP (미국 VCP 로직 · 감시 전용)</span>'
            f'{btc_html}<span class="vcp-meta">{meta}</span></div>'
            f'<div class="vcp-diag">{diag}</div>{secs}</div>')


# ── 09시 급등 스캔 (open_surge) ──────────────────────────────────────────────
def card_open_surge(items):
    """오늘자 급등 스캔 결과를 컴팩트 테이블 카드로. 데이터 없으면 빈 문자열."""
    if not items:
        return ""
    head = ('<tr><th>심볼</th><th>종목명</th><th class="r">09시상승</th>'
            '<th class="r">현재가</th><th class="r">당일등락</th>'
            '<th class="r">거래량비</th><th class="r">거래대금</th></tr>')
    body = ""
    for it in items:
        dc = it.get("day_change_pct", 0) or 0
        dc_cls = "up" if dc > 0 else ("down" if dc < 0 else "")
        body += (
            f'<tr><td>{sym_link(it["symbol"], it.get("name", ""))}</td>'
            f'<td class="nm">{name_link(it["symbol"], it.get("name", ""))}</td>'
            f'<td class="r up">{it.get("rise_pct", 0):+.2f}%</td>'
            f'<td class="r">{fmt_price_won(it.get("current_price"))}</td>'
            f'<td class="r {dc_cls}">{dc:+.2f}%</td>'
            f'<td class="r">{it.get("vol_ratio", 0):.1f}배</td>'
            f'<td class="r">{it.get("trade_value", 0)/1e8:.2f}억</td></tr>'
        )
    inner = (
        '<div class="surge-cond">조건: 09:00상승률&ge;2.5% AND 거래량&ge;직전10배 '
        'AND 거래대금&ge;4억</div>'
        f'<table class="t surge-t">{head}{body}</table>'
    )
    return card(f"⚡ 09시 급등 스캔 (충족: {len(items)}개)", "#d35400",
                inner, raw=True, cls="card-surge")


# ── 카드 래퍼 ───────────────────────────────────────────────────────────────
def card(title, color, body, raw=False, cls=""):
    return (
        f'<div class="card {cls}" style="border-top:3px solid {color};">'
        f'<div class="card-title" style="color:{color};">{title}</div>'
        f'<div class="card-body">{body}</div></div>'
    )


# ── 보유현황 블록 (업비트 + 바이낸스 선물) — 우측 상단 컴팩트 ─────────────────
COIN_HOLDINGS_JSON = Path(r"D:\py\coin\0txt\holdings_coin.json")
WEEKLY_PERF_JSON = Path(r"D:\py\report-us\weekly_performance.json")


def load_coin_holdings():
    if not COIN_HOLDINGS_JSON.exists():
        return None
    try:
        with open(COIN_HOLDINGS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def load_binance_futures_week():
    """make_weekly_performance.py 가 sync_binance_futures_income_v1.py 원천으로
    집계한 이번 주(월~일) 실현손익(REALIZED_PNL+COMMISSION+FUNDING_FEE, USDT)."""
    if not WEEKLY_PERF_JSON.exists():
        return None
    try:
        with open(WEEKLY_PERF_JSON, encoding="utf-8") as f:
            return json.load(f).get("binance_futures_week")
    except (OSError, json.JSONDecodeError):
        return None


def _won(n):
    try:
        return f"{int(round(float(n))):,}원"
    except (TypeError, ValueError):
        return "-"


def _man(n):
    """원 → '만' 단위 (보유테이블 평가금액용)."""
    try:
        return f"{int(round(float(n) / 10000)):,}만"
    except (TypeError, ValueError):
        return "-"


def _usdt_won(usdt, krw):
    """1,889.51(2,765,373원) 형식 — 업비트 USDT/KRW 환율(김프반영) 환산."""
    if usdt is None:
        return "-"
    u = f"{float(usdt):,.2f}"
    if krw is None:
        return u
    return f'{u}<small class="kw">({int(round(float(krw))):,}원)</small>'


def _pct(v):
    if v is None:
        return '<span class="mut">-</span>'
    if v > 0:
        cls = "up"
    elif v <= -8:
        cls = "down"
    elif v < 0:
        cls = "warn"
    else:
        cls = ""
    return f'<span class="{cls}">{v:+.2f}%</span>'


def _qty(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v >= 1000:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return f"{v:.8f}".rstrip("0").rstrip(".")


def _sum_row(label, val_html):
    return (f'<div class="ac-srow"><span class="ac-slab">{label}</span>'
            f'<span class="ac-sval">{val_html}</span></div>')


def _upbit_card(up):
    if not up or not up.get("ok"):
        msg = (up or {}).get("error", "데이터 없음")
        return card("🟦 업비트", "#1565c0", f'<div class="empty">{msg}</div>', raw=True, cls="ac-card")
    pnl = up.get("pnl")
    rate = up.get("pnl_rate")
    pnl_cls = "up" if (pnl or 0) > 0 else ("down" if (pnl or 0) < 0 else "")
    summ = (
        _sum_row("총자산", _won(up.get("total_asset")))
        + _sum_row("평가총액", _won(up.get("eval_total")))
        + _sum_row("평가손익",
                   f'<span class="{pnl_cls}">{("+" if (pnl or 0) >= 0 else "")}{_won(pnl)}</span> '
                   f'{_pct(rate)}' if pnl is not None else "-")
        + _sum_row("예수금", _won(up.get("krw_balance")))
    )
    head = ('<tr><th>코인</th><th class="r">수량</th><th class="r">현재가</th>'
            '<th class="r">수익률</th><th class="r">평가</th></tr>')
    body = ""
    for h in up.get("holdings", []):
        body += (
            f'<tr><td class="sym">{h.get("cur")}</td>'
            f'<td class="r">{_qty(h.get("qty"))}</td>'
            f'<td class="r">{_won(h.get("price")) if h.get("price") else "-"}</td>'
            f'<td class="r">{_pct(h.get("pnl_rate"))}</td>'
            f'<td class="r">{_man(h.get("eval")) if h.get("eval") else "-"}</td></tr>'
        )
    table = f'<table class="ac-t">{head}{body}</table>' if body else '<div class="empty">보유 없음</div>'
    return card("🟦 업비트", "#1565c0", summ + table, raw=True, cls="ac-card")


def _week_pnl_row(week):
    """coin.html 바이낸스 카드 하단에 붙는 '이번주 실현손익' 한 줄. 데이터 없으면 빈 문자열."""
    if not week or not week.get("has_data"):
        return ""
    total = week.get("total") or 0.0
    cls = "up" if total > 0 else ("down" if total < 0 else "")
    sign = "+" if total > 0 else ""
    return _sum_row(
        f'이번주 실현손익({week.get("label", "")})',
        f'<span class="{cls}">{sign}{total:.2f} USDT</span>',
    )


def _binance_card(bn, rate, week=None):
    subtitle = f'<small class="kw">USDT/KRW {int(round(rate)):,}원</small>' if rate else ""
    if not bn or not bn.get("ok"):
        msg = (bn or {}).get("error", "데이터 없음")
        body = f'<div class="empty">{msg}</div>' + _week_pnl_row(week)
        return card("🟨 바이낸스 선물", "#e08e0b", body, raw=True, cls="ac-card")
    pnl = bn.get("pnl")
    pnl_cls = "up" if (pnl or 0) > 0 else ("down" if (pnl or 0) < 0 else "")
    summ = (
        _sum_row("지갑", _usdt_won(bn.get("wallet"), bn.get("wallet_krw")))
        + _sum_row("가용", _usdt_won(bn.get("available"), bn.get("available_krw")))
        + _sum_row("미실현손익",
                   f'<span class="{pnl_cls}">{_usdt_won(pnl, bn.get("pnl_krw"))}</span>')
    )
    positions = bn.get("positions", [])
    if not positions:
        table = '<div class="empty">열린 포지션 없음</div>'
    else:
        # 열이 많아 행/열 전치 — 필드는 행, 포지션(코인)은 열
        def _cells(fn):
            return "".join(f'<td class="r">{fn(p)}</td>' for p in positions)

        def _side_badge(p):
            side = p.get("side")
            cls = "b-long" if side == "LONG" else "b-short"
            return f'<span class="badge {cls}">{side} {p.get("lev")}x</span>'

        def _buf(p):
            b = p.get("buffer")
            if b is None:
                return "-"
            cls = "down" if b < 5 else ""
            return f'<span class="{cls}">{b:.1f}%</span>'

        sym_head = "".join(
            f'<th class="r sym">{(p.get("symbol") or "").replace("USDT", "")}</th>'
            for p in positions)
        rows = [
            ("방향", "".join(f'<td class="r">{_side_badge(p)}</td>' for p in positions)),
            ("보유수량", _cells(lambda p: _qty(p.get("amt")))),
            ("진입가", _cells(lambda p: _usdt_won(p.get("entry"), p.get("entry_krw")))),
            ("현재가", _cells(lambda p: _usdt_won(p.get("mark"), p.get("mark_krw")))),
            ("수익률", _cells(lambda p: _pct(p.get("roe")))),
            ("청산가", _cells(lambda p: _usdt_won(p.get("liq"), p.get("liq_krw")))),
            ("청산버퍼", "".join(f'<td class="r">{_buf(p)}</td>' for p in positions)),
        ]
        body = f'<tr><th class="fld">종목</th>{sym_head}</tr>'
        for lab, cells in rows:
            body += f'<tr><td class="fld">{lab}</td>{cells}</tr>'
        table = f'<table class="ac-t ac-tv">{body}</table>'
    return card(f"🟨 바이낸스 선물 {subtitle}", "#e08e0b", summ + table + _week_pnl_row(week), raw=True, cls="ac-card ac-binance")


def build_acct_block(ch):
    if not ch:
        return ""
    up = _upbit_card(ch.get("upbit"))
    bn = _binance_card(ch.get("binance"), ch.get("usdt_krw"), load_binance_futures_week())
    return f'<div class="acct-wrap">{up}{bn}</div>'


# ── 차트 hover 팝업 JS ───────────────────────────────────────────────────────
# 종목 심볼(.sym[data-coin])에 마우스 → 업비트 일봉 캔들 직접 fetch → lightweight-charts.
# 업비트 캔들 API는 Access-Control-Allow-Origin:* 라 브라우저에서 직접 호출 가능.
POPUP_JS = r"""
(function(){
  var LWC = window.LightweightCharts;
  if(!LWC){ return; }
  var UP="#f23645", DOWN="#2962ff";
  var VOL_UP="rgba(242,54,69,0.4)", VOL_DOWN="rgba(41,98,255,0.4)";
  var MA_D=[[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a'],[120,'#111111']];
  var MA_5=[[5,'#e11d1d'],[10,'#404040'],[20,'#ff8c00'],[60,'#16a34a']];
  var RIGHT_PAD=3;
  var RIGHT_SCALE_W=78;
  var TREND_BG_COLORS={
    LIME:'rgba(0,230,118,0.15)',GREEN:'rgba(76,175,80,0.15)',
    PURPLE:'rgba(192,132,252,0.14)',RED:'rgba(251,113,133,0.13)'};

  var pop=document.getElementById('coinpop');
  var elTitle=pop.querySelector('.cp-title');
  var elSub=pop.querySelector('.cp-sub');
  var tabs=pop.querySelectorAll('.cp-tab');
  var col5=document.getElementById('cpCol5');
  var colD=document.getElementById('cpColD');
  var cache={}, charts=[], curTab='5';
  var curSym=null, pinned=false, closeTimer=null, openTimer=null;
  var hoverless = window.matchMedia('(hover: none)').matches;

  // 가격: 큰 값은 #,###K, 코인 소수가는 정밀 유지
  function fmtP(v){
    if(Math.abs(v)>=1000000) return Math.round(v/1000).toLocaleString()+'K';
    if(v>=1000) return Math.round(v).toLocaleString();
    if(v>=1)    return v.toFixed(2);
    return v.toPrecision(4);
  }
  // 거래량: 큰 값은 #,###K
  function fmtVol(v){
    if(Math.abs(v)>=1000000) return Math.round(v/1000).toLocaleString()+'K';
    if(Math.abs(v)>=1000)    return Math.round(v).toLocaleString();
    return (Math.round(v*100)/100).toLocaleString();
  }
  function sma(rows,n){
    var out=[],sum=0;
    for(var i=0;i<rows.length;i++){
      sum+=rows[i].close;
      if(i>=n) sum-=rows[i-n].close;
      if(i>=n-1) out.push({time:rows[i].time,value:sum/n});
    }
    return out;
  }
  // RSI(14)+14이평 — 봉 전체에 정렬된 배열 반환(앞부분 null은 whitespace).
  // 캔들차트와 RSI차트의 논리인덱스가 같아져야 setVisibleLogicalRange 가 어긋나지 않는다.
  function rsiWilder(rows,n){
    var N=rows.length, rv=new Array(N).fill(null), mv=new Array(N).fill(null), i;
    if(N>=n+1){
      var gain=0,loss=0;
      for(i=1;i<=n;i++){var ch=rows[i].close-rows[i-1].close; if(ch>=0)gain+=ch; else loss-=ch;}
      var ag=gain/n, al=loss/n;
      rv[n]=al===0?100:100-100/(1+ag/al);
      for(i=n+1;i<N;i++){
        var d=rows[i].close-rows[i-1].close, g=d>0?d:0, l=d<0?-d:0;
        ag=(ag*(n-1)+g)/n; al=(al*(n-1)+l)/n;
        rv[i]=al===0?100:100-100/(1+ag/al);
      }
      var buf=[],sum=0;
      for(i=0;i<N;i++){
        if(rv[i]==null){buf.length=0;sum=0;continue;}
        buf.push(rv[i]);sum+=rv[i];
        if(buf.length>14)sum-=buf.shift();
        if(buf.length===14)mv[i]=sum/14;
      }
    }
    var rsi=[],rma=[];
    for(i=0;i<N;i++){
      rsi.push(rv[i]==null?{time:rows[i].time}:{time:rows[i].time,value:+rv[i].toFixed(2)});
      rma.push(mv[i]==null?{time:rows[i].time}:{time:rows[i].time,value:+mv[i].toFixed(2)});
    }
    return {rsi:rsi,rma:rma};
  }
  // ── 저/저2 저점신호 (단타 게시판 computeLowSignals 동일 공식) ──
  function rollMeanN(arr,n){var o=new Array(arr.length).fill(null);
    for(var i=n-1;i<arr.length;i++){var s=0,ok=true;
      for(var j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}s+=arr[j];}
      o[i]=ok?s/n:null;}return o;}
  function rollMaxN(arr,n){var o=new Array(arr.length).fill(null);
    for(var i=n-1;i<arr.length;i++){var m=-Infinity,ok=true;
      for(var j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]>m)m=arr[j];}
      o[i]=ok?m:null;}return o;}
  function rollMinN(arr,n){var o=new Array(arr.length).fill(null);
    for(var i=n-1;i<arr.length;i++){var m=Infinity,ok=true;
      for(var j=i-n+1;j<=i;j++){if(arr[j]==null){ok=false;break;}if(arr[j]<m)m=arr[j];}
      o[i]=ok?m:null;}return o;}
  function stochN(close,high,low,n){var o=new Array(close.length).fill(null);
    for(var i=n-1;i<close.length;i++){var lo=Infinity,hi=-Infinity;
      for(var j=i-n+1;j<=i;j++){if(low[j]<lo)lo=low[j];if(high[j]>hi)hi=high[j];}
      o[i]=(hi===lo)?null:(close[i]-lo)/(hi-lo)*100;}return o;}
  function rsiArr(cl,p){var N=cl.length,out=new Array(N).fill(null),i;
    if(N<p+1)return out;var g=0,l=0;
    for(i=1;i<=p;i++){var ch=cl[i]-cl[i-1];if(ch>=0)g+=ch;else l-=ch;}
    var ag=g/p,al=l/p;out[p]=al===0?100:100-100/(1+ag/al);
    for(i=p+1;i<N;i++){var d=cl[i]-cl[i-1],gg=d>0?d:0,ll=d<0?-d:0;
      ag=(ag*(p-1)+gg)/p;al=(al*(p-1)+ll)/p;out[i]=al===0?100:100-100/(1+ag/al);}
    return out;}
  function computeLowSignals(rows){
    var n=rows.length,i;
    var high=rows.map(function(b){return b.high;}),low=rows.map(function(b){return b.low;}),
        close=rows.map(function(b){return b.close;});
    var k3=rollMeanN(stochN(close,high,low,20),10);
    var k2=rollMeanN(stochN(close,high,low,10),5);
    var hh=rollMaxN(high,10),ll=rollMinN(low,10);
    var diff=new Array(n).fill(null),rdiff=new Array(n).fill(null);
    for(i=0;i<n;i++){if(hh[i]!=null&&ll[i]!=null){diff[i]=hh[i]-ll[i];rdiff[i]=close[i]-(hh[i]+ll[i])/2;}}
    var avgrel=rollMeanN(rollMeanN(rdiff,3),3),avgdiff=rollMeanN(rollMeanN(diff,3),3);
    var smi=new Array(n).fill(0);
    for(i=0;i<n;i++){if(avgrel[i]!=null&&avgdiff[i]!=null&&avgdiff[i]!==0)smi[i]=avgrel[i]/(avgdiff[i]/2)*100;}
    var smisig=rollMeanN(smi,3),emasig=rollMeanN(smi,10),rsi1=rsiArr(close,14);
    var constat=new Array(n).fill(false);
    for(i=0;i<n;i++){constat[i]=(smisig[i]!=null&&smisig[i]<=-60)&&(emasig[i]!=null&&emasig[i]<=-60)&&(rsi1[i]!=null&&rsi1[i]<=30);}
    var jeo=[],jeo2=[];
    for(i=1;i<n;i++){
      if(k3[i]!=null&&k3[i-1]!=null&&k2[i]!=null&&k2[i-1]!=null&&k3[i]>=20&&k3[i-1]<20&&k2[i]>=k2[i-1])jeo.push(rows[i].time);
      if(constat[i-1]&&!constat[i])jeo2.push(rows[i].time);
    }
    return {jeo:jeo,jeo2:jeo2};
  }
  function newCandle(el,intraday){
    return LWC.createChart(el,{width:el.clientWidth,height:el.clientHeight,
      layout:{background:{color:'#fff'},textColor:'#333',fontSize:11},
      grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f3f3f3'}},
      rightPriceScale:{borderColor:'#ddd',minimumWidth:RIGHT_SCALE_W,scaleMargins:{top:0.08,bottom:0.08}},
      timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:intraday?1.2:0.4,visible:false},
      localization:{priceFormatter:fmtP},
      crosshair:{mode:LWC.CrosshairMode.Normal}});
  }
  function newRsi(el,intraday){
    return LWC.createChart(el,{width:el.clientWidth,height:el.clientHeight,
      layout:{background:{color:'#fff'},textColor:'#888',fontSize:10},
      grid:{vertLines:{color:'#f3f3f3'},horzLines:{color:'#f7f7f7'}},
      rightPriceScale:{borderColor:'#ddd',minimumWidth:RIGHT_SCALE_W,scaleMargins:{top:0.12,bottom:0.12}},
      timeScale:{borderColor:'#ddd',rightOffset:RIGHT_PAD,minBarSpacing:intraday?1.2:0.4,
        timeVisible:!!intraday,secondsVisible:false},
      crosshair:{mode:LWC.CrosshairMode.Normal}});
  }
  function addCandleVol(ch){
    var cs=ch.addCandlestickSeries({upColor:UP,downColor:DOWN,borderUpColor:UP,
      borderDownColor:DOWN,wickUpColor:UP,wickDownColor:DOWN,
      priceFormat:{type:'custom',minMove:0.0001,formatter:fmtP}});
    var vol=ch.addHistogramSeries({priceScaleId:'',
      priceFormat:{type:'custom',minMove:0.0001,formatter:fmtVol}});
    vol.priceScale().applyOptions({scaleMargins:{top:0.85,bottom:0}});
    return [cs,vol];
  }
  function addRsi(rel,intraday,rdata,rmdata){
    var rch=newRsi(rel,intraday);
    var bUp=rch.addBaselineSeries({baseValue:{type:'price',price:70},
      topLineColor:'rgba(0,0,0,0)',topFillColor1:'rgba(50,205,50,0.62)',topFillColor2:'rgba(50,205,50,0.30)',
      bottomLineColor:'rgba(0,0,0,0)',bottomFillColor1:'rgba(0,0,0,0)',bottomFillColor2:'rgba(0,0,0,0)',
      priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    bUp.setData(rdata);
    var bDn=rch.addBaselineSeries({baseValue:{type:'price',price:30},
      topLineColor:'rgba(0,0,0,0)',topFillColor1:'rgba(0,0,0,0)',topFillColor2:'rgba(0,0,0,0)',
      bottomLineColor:'rgba(0,0,0,0)',bottomFillColor1:'rgba(239,68,68,0.30)',bottomFillColor2:'rgba(239,68,68,0.62)',
      priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
    bDn.setData(rdata);
    var rl=rch.addLineSeries({color:DOWN,lineWidth:1,priceLineVisible:false,
      lastValueVisible:true,crosshairMarkerVisible:false});
    rl.setData(rdata);
    var rm=rch.addLineSeries({color:UP,lineWidth:1,priceLineVisible:false,
      lastValueVisible:false,crosshairMarkerVisible:false});
    rm.setData(rmdata);
    [70,30].forEach(function(lv){rl.createPriceLine({price:lv,color:'#9ca3af',lineWidth:1,
      lineStyle:LWC.LineStyle.Dashed,axisLabelVisible:true});});
    return {rch:rch,rl:rl};
  }
  function syncPair(a,b){var lock=false;
    var s=function(src,dst){src.timeScale().subscribeVisibleLogicalRangeChange(function(r){
      if(lock||!r)return;lock=true;dst.timeScale().setVisibleLogicalRange(r);lock=false;});};
    s(a,b);s(b,a);}
  function syncScaleWidth(a,b){
    var apply=function(){try{
      var w=Math.max(a.priceScale('right').width(),b.priceScale('right').width());
      a.priceScale('right').applyOptions({minimumWidth:w});
      b.priceScale('right').applyOptions({minimumWidth:w});
    }catch(e){}};
    requestAnimationFrame(apply);
    a.timeScale().subscribeVisibleLogicalRangeChange(apply);
  }
  function syncCrosshair(a,aS,aMap,b,bS,bMap){
    var lock=false;
    var link=function(src,dst,dstS,dstMap){src.subscribeCrosshairMove(function(p){
      if(lock)return;lock=true;
      if(p.time==null||p.point==null)dst.clearCrosshairPosition();
      else{var v=dstMap.get(p.time);
        if(v==null)dst.clearCrosshairPosition();else dst.setCrosshairPosition(v,p.time,dstS);}
      lock=false;});};
    link(a,b,bS,bMap);link(b,a,aS,aMap);
  }
  function destroy(){ charts.forEach(function(o){try{o.ch.remove();}catch(e){}}); charts=[]; }
  function resizeAll(){ charts.forEach(function(o){ if(o.el.clientWidth) o.ch.resize(o.el.clientWidth,o.el.clientHeight); }); }

  function buildPane(prefix,rows,intraday,maSet){
    var el=document.getElementById('cpChart'+prefix);
    var rel=document.getElementById('cpRsi'+prefix);
    var ch=newCandle(el,intraday);
    // 추세배경(LIME/GREEN/RED/PURPLE) — 캔들보다 먼저 추가해 뒤에 깔리게
    var trendBand=ch.addHistogramSeries({priceScaleId:'trendbg',base:0,
      priceLineVisible:false,lastValueVisible:false});
    ch.priceScale('trendbg').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
    trendBand.setData(rows.filter(function(b){return b.t&&TREND_BG_COLORS[b.t];})
      .map(function(b){return{time:b.time,value:1,color:TREND_BG_COLORS[b.t]};}));
    var cv=addCandleVol(ch), cs=cv[0], vol=cv[1];
    cs.setData(rows);
    vol.setData(rows.map(function(d){return{time:d.time,value:d.volume,
      color:d.close>=d.open?VOL_UP:VOL_DOWN};}));
    maSet.forEach(function(m){
      var ln=ch.addLineSeries({color:m[1],lineWidth:1,priceLineVisible:false,
        lastValueVisible:false,crosshairMarkerVisible:false});
      ln.setData(sma(rows,m[0]));
    });
    // 저(빨간박스)/저2(검정 윗화살표) 저점신호 마커
    var sig=computeLowSignals(rows), marks=[];
    sig.jeo.forEach(function(t){marks.push({time:t,position:'belowBar',color:'#e11d1d',shape:'square',text:'저'});});
    sig.jeo2.forEach(function(t){marks.push({time:t,position:'belowBar',color:'#000000',shape:'arrowUp',text:'저2'});});
    marks.sort(function(a,b){return (a.time>b.time)?1:(a.time<b.time?-1:0);});
    if(marks.length) cs.setMarkers(marks);
    var r=rsiWilder(rows,14);
    var ro=addRsi(rel,intraday,r.rsi,r.rma);
    syncPair(ch,ro.rch);
    syncScaleWidth(ch,ro.rch);
    var candleMap=new Map(rows.map(function(d){return[d.time,d.close];}));
    var rsiMap=new Map(r.rsi.map(function(d){return[d.time,d.value];}));
    syncCrosshair(ch,cs,candleMap,ro.rch,ro.rl,rsiMap);
    charts.push({ch:ch,el:el},{ch:ro.rch,el:rel});
    var total=rows.length, want=intraday?120:90;
    if(total>want) ch.timeScale().setVisibleLogicalRange({from:total-want,to:total-1+RIGHT_PAD});
    else ch.timeScale().fitContent();
  }

  function loadSym(sym){
    // 1순위: 빌드 시점에 박아넣은 캔들 데이터 사용 → 네트워크 호출 0 (즉시 표시)
    var c=(window.__COIN_DATA__||{})[sym];
    if(c && c.d && c.d.length) return Promise.resolve(c);
    // 2순위: 임베드가 비었으면 브라우저에서 업비트 직접 fetch (CORS 허용)
    if(cache[sym]) return Promise.resolve(cache[sym]);
    var base='https://api.upbit.com/v1/candles/';
    var qs='?market=KRW-'+encodeURIComponent(sym)+'&count=200';
    return Promise.all([
      fetch(base+'days'+qs).then(function(r){return r.json();}),
      fetch(base+'minutes/5'+qs).then(function(r){return r.json();})
    ]).then(function(res){
      var rawD=res[0], raw5=res[1];
      if(!Array.isArray(rawD) || !rawD.length) throw new Error('no data');
      var d=rawD.slice().reverse().map(function(x){return{
        time:x.candle_date_time_kst.slice(0,10),
        open:x.opening_price,high:x.high_price,low:x.low_price,
        close:x.trade_price,volume:Math.round(x.candle_acc_trade_volume*1e4)/1e4};});
      var m=(Array.isArray(raw5)?raw5:[]).slice().reverse().map(function(x){return{
        time:Math.floor(Date.parse(x.candle_date_time_kst+'Z')/1000),
        open:x.opening_price,high:x.high_price,low:x.low_price,
        close:x.trade_price,volume:Math.round(x.candle_acc_trade_volume*1e4)/1e4};});
      var obj={d:d,m:m};
      cache[sym]=obj;
      return obj;
    });
  }
  function applyTab(){
    tabs.forEach(function(b){b.classList.toggle('active',b.dataset.tab===curTab);});
    col5.classList.toggle('hidden',curTab!=='5');
    colD.classList.toggle('hidden',curTab!=='d');
    requestAnimationFrame(resizeAll);
  }
  function show(sym,name){
    curSym=sym;
    elTitle.textContent=(name?name+' ':'')+'('+sym+'/KRW)';
    elSub.textContent='로딩...'; elSub.style.color='#888';
    destroy();
    loadSym(sym).then(function(c){
      if(curSym!==sym) return;            // 그 사이 다른 종목으로 이동
      destroy();
      buildPane('5',c.m,true,MA_5);
      buildPane('D',c.d,false,MA_D);
      applyTab();
      var rows=c.d;
      if(rows.length>=2){
        var cc=rows[rows.length-1].close, pp=rows[rows.length-2].close;
        var pct=(cc/pp-1)*100;
        elSub.textContent=fmtP(cc)+'원  '+(pct>=0?'+':'')+pct.toFixed(2)+'%';
        elSub.style.color=pct>=0?UP:DOWN;
      }
    }).catch(function(){
      if(curSym===sym){ elSub.textContent='로드 실패'; elSub.style.color=DOWN; }
    });
  }
  function place(x,y){
    var w=pop.offsetWidth||1020, h=pop.offsetHeight||440;
    var px=x+18, py=y+18;
    if(px+w>window.innerWidth-8)  px=x-w-12;
    if(py+h>window.innerHeight-8) py=window.innerHeight-h-8;
    if(px<8)px=8; if(py<8)py=8;
    pop.style.left=px+'px'; pop.style.top=py+'px';
  }
  function openPop(){ pop.style.display='block'; }
  function closePop(){ pop.style.display='none'; curSym=null; pinned=false; }
  function cancelClose(){ if(closeTimer){clearTimeout(closeTimer);closeTimer=null;} }
  function scheduleClose(){ cancelClose(); closeTimer=setTimeout(function(){ if(!pinned) closePop(); },180); }

  tabs.forEach(function(b){ b.addEventListener('click',function(){ curTab=b.dataset.tab; applyTab(); }); });

  document.querySelectorAll('.sym[data-coin]').forEach(function(a){
    a.addEventListener('mouseenter',function(e){
      if(hoverless) return;
      cancelClose();
      var x=e.clientX, y=e.clientY, sym=a.dataset.coin, name=a.dataset.name||'';
      clearTimeout(openTimer);
      openTimer=setTimeout(function(){ openPop(); place(x,y); show(sym,name); },60);
    });
    a.addEventListener('mouseleave',function(){ clearTimeout(openTimer); scheduleClose(); });
    a.addEventListener('click',function(e){
      if(hoverless){ e.preventDefault(); openPop(); pinned=true;
        var r=a.getBoundingClientRect(); place(r.left, r.bottom);
        show(a.dataset.coin, a.dataset.name||''); }
    });
  });
  pop.addEventListener('mouseenter',function(){ pinned=true; cancelClose(); });
  pop.addEventListener('mouseleave',function(){ pinned=false; scheduleClose(); });
  document.addEventListener('click',function(e){
    if(pop.style.display!=='block') return;
    if(pop.contains(e.target)) return;
    if(e.target.closest && e.target.closest('.sym[data-coin]')) return;
    closePop();
  });
  window.addEventListener('resize',function(){
    if(pop.style.display==='block') resizeAll();
  });
})();
"""


# ── 빌드 ────────────────────────────────────────────────────────────────────
def build_html(data):
    dist = data.get("distribution", {})
    gen  = data.get("generated_at", "")
    popup_js = POPUP_JS

    acct_block = build_acct_block(load_coin_holdings())

    row1 = "".join([
        card_distribution(dist),
        card_symbol_list("💥 SPOT 신호 종목", "#e74c3c", data.get("spot", [])),
        card_symbol_list("🏆 주도주 신호 종목", "#f39c12", data.get("leader", [])),
        card_high52w(data.get("high52w", [])),
    ])
    row2 = "".join([
        table_top10(data.get("top10", [])),
        table_signal("🟢 LIME 신호 종목", "#2ecc71", data.get("lime", [])),
        table_signal("⭐ MOM 신호 종목", "#3498db", data.get("mom", [])),
        table_signal("🚀 Rocket(inv3) 신호 종목", "#9b59b6", data.get("rocket", [])),
    ])
    row3 = "".join([
        table_low(data.get("low", [])),
        table_signal("🔥 GANN 불기둥 신호 종목", "#c0392b", data.get("gann", [])),
        table_signal("🔥 JUNG 정배열 신호 종목", "#27ae60", data.get("jung", [])),
        table_breakout(data.get("breakout", [])),
    ])

    # 09시 급등 스캔 (오늘 날짜 일치 시에만) — 1번째·2번째 줄 사이에 삽입
    surge_card = card_open_surge(load_today_surge())
    surge_row = f'<div class="grid grid-surge">{surge_card}</div>' if surge_card else ""

    # 코인 VCP 블록 — 3번째 줄 아래 전체폭
    vcp_block = build_vcp_block(load_coin_vcp())

    # 화면에 실제 렌더된 심볼만 수집(순서 보존) → 빌드 시점 캔들 임베드
    seen, symbols = set(), []
    for sym in re.findall(r'data-coin="([^"]+)"', row1 + surge_card + row2 + row3 + vcp_block):
        if sym not in seen:
            seen.add(sym); symbols.append(sym)
    coin_data = fetch_coin_candle_data(symbols)
    coin_data_js = json.dumps(coin_data, ensure_ascii=False, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>코인</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
    background: #f4f7f6; color: #2c3e50;
  }}
  .page-head {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }}
  .page-head h1 {{ font-size: 1.4rem; margin: 0; }}
  .page-head .ts {{ font-size: 0.8rem; color: #7f8c8d; }}

  .grid {{ display: grid; gap: 12px; margin-bottom: 12px; justify-content: start; }}
  /* 분포 카드만 고정폭, 나머지는 내용에 맞춰 폭 축소 + 좌측 정렬 */
  .grid-row1 {{ grid-template-columns: 280px repeat(3, minmax(150px, max-content)); }}
  .grid-row2 {{ grid-template-columns: repeat(4, minmax(150px, max-content)); }}
  .grid-row3 {{ grid-template-columns: repeat(4, minmax(150px, max-content)); }}

  .card {{
    background: #fff; border-radius: 8px; padding: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    display: flex; flex-direction: column; min-width: 0;
  }}
  .card-title {{ font-size: 0.92rem; font-weight: 700; margin-bottom: 8px; }}
  .card-body {{ font-size: 0.82rem; }}
  .empty {{ color: #bdc3c7; font-size: 0.8rem; padding: 6px 0; }}

  /* 분포 카드 */
  .dist-head {{ font-size: 0.82rem; color: #555; margin-bottom: 8px; }}
  .dist-row {{ display: flex; align-items: center; gap: 6px; margin: 5px 0; font-size: 0.78rem; }}
  .dist-label {{ width: 52px; color: #555; flex-shrink: 0; }}
  .dist-barwrap {{ flex: 1; background: #eef0f1; border-radius: 4px; height: 12px; overflow: hidden; }}
  .dist-bar {{ display: block; height: 100%; border-radius: 4px; }}
  .bar-hi {{ background: #2ecc71; }}
  .bar-mid {{ background: #95a5a6; }}
  .bar-lo {{ background: #e74c3c; }}
  .dist-cnt {{ width: 78px; text-align: right; flex-shrink: 0; }}
  .dist-cnt small {{ color: #95a5a6; }}

  /* 심볼 리스트 카드 */
  .lirow {{ display: flex; justify-content: space-between; align-items: center; padding: 3px 0; border-bottom: 1px solid #f2f4f4; }}
  .lirow:last-child {{ border-bottom: none; }}
  .liname {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 11em; }}
  .liname small {{ color: #95a5a6; font-size: 0.72rem; }}
  .lival {{ color: #34495e; font-size: 0.78rem; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{ background: #eafaf1; border-radius: 12px; padding: 3px 10px; font-size: 0.78rem; }}

  /* 테이블 */
  table.t {{ width: 100%; border-collapse: collapse; font-size: 0.76rem; }}
  table.t th {{ text-align: left; color: #95a5a6; font-weight: 600; padding: 3px 4px; border-bottom: 1px solid #ecf0f1; font-size: 0.72rem; }}
  table.t td {{ padding: 4px 4px; border-bottom: 1px solid #f6f7f8; }}
  table.t tr:last-child td {{ border-bottom: none; }}
  table.t .r {{ text-align: right; }}
  table.t .c {{ text-align: center; }}
  table.t .nm {{ color: #555; max-width: 7em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

  a.sym {{ font-weight: 700; color: #2980b9; text-decoration: none; }}
  a.sym:hover {{ text-decoration: underline; }}

  /* 코인 VCP 블록 — 내용폭에 맞춤 (페이지 전체로 안 늘림) */
  .vcp-wrap {{
    background: #fff; border-radius: 8px; padding: 12px 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-top: 3px solid #8e44ad;
    margin-bottom: 12px; overflow-x: auto;
    width: max-content; max-width: 100%;
  }}
  .vcp-head {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
  .vcp-title {{ font-size: 0.92rem; font-weight: 700; color: #8e44ad; }}
  .vcp-meta {{ font-size: 0.7rem; color: #95a5a6; }}
  .vcp-diag {{ font-size: 0.7rem; color: #7f8c8d; margin-top: 4px; }}
  .vcp-sec {{ margin-top: 12px; }}
  .vcp-sec-t {{ font-size: 0.84rem; font-weight: 700; color: #2c3e50; }}
  .vcp-cnt {{ color: #95a5a6; font-weight: 400; font-size: 0.74rem; margin-left: 6px; }}
  .vcp-sec-d {{ font-size: 0.7rem; color: #95a5a6; margin: 2px 0 5px; }}
  table.vcp-t {{ width: auto; }}
  table.vcp-t th, table.vcp-t td {{ white-space: nowrap; padding: 3px 12px; }}
  table.vcp-t th:first-child, table.vcp-t td:first-child {{ padding-left: 0; }}
  table.vcp-t td.nm {{ max-width: none; color: #333; }}
  table.vcp-t .r {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .grade {{ display: inline-block; border-radius: 3px; padding: 0 5px; color: #fff; font-size: 0.68rem; font-weight: 700; }}
  .g-A {{ background: #27ae60; }} .g-B {{ background: #2980b9; }}
  .g-C {{ background: #f39c12; }} .g-D {{ background: #95a5a6; }}
  .tag {{ display: inline-block; border-radius: 3px; padding: 0 5px; color: #fff; font-size: 0.68rem; font-weight: 700; }}
  .tag-win {{ background: #27ae60; }} .tag-loss {{ background: #e74c3c; }}
  .tag-flat {{ background: #95a5a6; }} .tag-open {{ background: #8e44ad; }}
  .badge-btc {{ border-radius: 10px; padding: 1px 8px; font-size: 0.68rem; font-weight: 700; color: #fff; }}
  .bt-up {{ background: #27ae60; }} .bt-dn {{ background: #7f8c8d; }}

  /* 09시 급등 스캔 카드 — 컴팩트 + 내용폭에 맞춤 (페이지 전체로 안 늘림) */
  .grid-surge {{ grid-template-columns: max-content; }}
  .card-surge {{ padding: 10px 14px; max-width: 100%; overflow-x: auto; }}
  .surge-cond {{ font-size: 0.74rem; color: #7f8c8d; margin-bottom: 6px; }}
  table.surge-t {{ width: auto; }}
  table.surge-t th, table.surge-t td {{ white-space: nowrap; padding: 3px 12px; }}
  table.surge-t th:first-child, table.surge-t td:first-child {{ padding-left: 0; }}
  table.surge-t td.nm {{ max-width: none; color: #333; }}
  table.surge-t .r {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .up {{ color: #27ae60; }}
  .down {{ color: #e74c3c; }}
  .warn {{ color: #e67e22; }}
  .sco-hi {{ color: #27ae60; font-weight: 700; }}
  .sco-lo {{ color: #e74c3c; }}
  .sco-mid {{ color: #7f8c8d; }}
  .newsig {{ font-size: 0.72rem; }}

  /* 보유현황 블록 (업비트 + 바이낸스) — 우측 컬럼 고정, 좌측(신호카드들)과 독립적으로 쌓임 */
  .page-flex {{ display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }}
  .page-left {{ flex: 0 1 auto; min-width: 280px; }}
  .acct-wrap {{ display: flex; flex-direction: column; gap: 12px; flex-shrink: 0; }}
  .ac-card {{ min-width: 300px; max-width: 480px; overflow-x: auto; }}
  .ac-card .card-title {{ font-size: 1.08rem; }}
  .ac-srow {{ display: flex; justify-content: space-between; align-items: baseline;
    gap: 10px; padding: 4px 0; font-size: 0.95rem; border-bottom: 1px solid #f4f6f7; }}
  .ac-slab {{ color: #7f8c8d; flex-shrink: 0; }}
  .ac-sval {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
  table.ac-t {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; margin-top: 10px;
    white-space: nowrap; }}
  table.ac-t th {{ text-align: left; color: #95a5a6; font-weight: 600; padding: 5px 7px;
    border-bottom: 1px solid #ecf0f1; font-size: 0.86rem; }}
  table.ac-t td {{ padding: 5px 7px; border-bottom: 1px solid #f6f7f8; }}
  table.ac-t tr:last-child td {{ border-bottom: none; }}
  table.ac-t .r {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.ac-t td.sym {{ font-weight: 700; color: #2c3e50; }}
  table.ac-t th.sym {{ font-weight: 700; color: #2c3e50; text-align: right; }}
  /* 전치 테이블(바이낸스): 필드=행, 코인=열 */
  table.ac-tv td.fld, table.ac-tv th.fld {{ text-align: left; color: #7f8c8d;
    font-weight: 600; white-space: nowrap; background: #fafbfc; }}
  .ac-binance {{ max-width: 480px; }}
  .ac-card .kw {{ color: #95a5a6; font-weight: 400; font-size: 0.92em; }}
  .ac-card .mut {{ color: #bdc3c7; }}
  .badge {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.78rem;
    font-weight: 700; color: #fff; }}
  .badge.b-long {{ background: #e74c3c; }}
  .badge.b-short {{ background: #2980b9; }}
  @media (max-width: 1100px) {{
    .page-flex {{ flex-direction: column; }}
    .acct-wrap {{ width: 100%; flex-direction: row; flex-wrap: wrap; }}
    .ac-card {{ flex: 1 1 300px; }}
  }}

  /* 차트 hover 팝업 (5분봉 + 일봉) */
  #coinpop {{
    position: fixed; z-index: 9999; display: none;
    width: 1020px; max-width: 96vw;
    background: #fff; border: 1px solid #d8dde0; border-radius: 8px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.18); padding: 8px 10px;
  }}
  #coinpop .cp-head {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }}
  #coinpop .cp-title {{ font-weight: 700; font-size: 0.86rem; color: #2c3e50; }}
  #coinpop .cp-sub {{ font-size: 0.8rem; font-weight: 600; white-space: nowrap; }}
  #coinpop .cp-tabs {{ display: none; margin-left: auto; gap: 6px; }}
  #coinpop .cp-tab {{ padding: 4px 10px; border: 1px solid #bdc3c7; background: #f5f5f5;
    border-radius: 6px; font-size: 0.75rem; font-weight: 700; color: #34495e; cursor: pointer; }}
  #coinpop .cp-tab.active {{ background: #2980b9; color: #fff; border-color: #2980b9; }}
  #coinpop .cp-box {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  #coinpop .cp-col {{ display: flex; flex-direction: column; min-width: 0; }}
  #coinpop .cp-lab {{ font-size: 0.7rem; font-weight: 700; color: #374151; padding: 2px 0 3px; }}
  #coinpop .cp-chart {{ width: 100%; height: 300px; }}
  #coinpop .cp-rsi {{ width: 100%; height: 100px; }}
  @media (max-width: 767px) {{
    #coinpop {{ width: 96vw; left: 2vw !important; }}
    #coinpop .cp-box {{ grid-template-columns: 1fr; }}
    #coinpop .cp-tabs {{ display: flex; }}
    #coinpop .cp-col.hidden {{ display: none; }}
    #coinpop .cp-chart {{ height: 230px; }}
    #coinpop .cp-rsi {{ height: 64px; }}
  }}

  @media (max-width: 900px) {{
    .grid {{ justify-content: stretch; }}
    .grid-row1, .grid-row2, .grid-row3 {{ grid-template-columns: 1fr 1fr; }}
    .grid-surge {{ grid-template-columns: 1fr; }}
  }}
  @media (max-width: 560px) {{
    .grid {{ justify-content: stretch; }}
    .grid-row1, .grid-row2, .grid-row3 {{ grid-template-columns: 1fr; }}
  }}

  /* ───── 모바일 전용: SCO 분포 + 업비트 + 바이낸스 3블록만 노출 (PC 영향 없음) ───── */
  @media (max-width: 767px) {{
    body {{ padding: 10px; }}
    .page-flex {{ flex-direction: column; align-items: stretch; }}
    .page-left {{ width: 100%; min-width: 0; max-width: 100%; }}
    .acct-wrap {{ width: 100%; flex-direction: column; }}
    .ac-card {{ min-width: 0; max-width: 100%; flex: 0 0 auto; }}
    .ac-binance {{ max-width: 100%; }}
    table.ac-t {{ font-size: 0.86rem; }}
    table.ac-t th, table.ac-t td {{ padding: 5px 4px; }}

    /* 좌측 컬럼은 전부 감추고 SCO 분포 카드 하나만 되살림 */
    .page-left > * {{ display: none; }}
    .page-left > .grid-row1 {{ display: grid; grid-template-columns: 1fr; }}
    .grid-row1 > .card {{ display: none; }}
    .grid-row1 > .card-dist {{ display: flex; }}
  }}
</style>
</head>
<body>
  <div class="page-head">
    <h1>₿ 코인</h1>
    <span class="ts">업데이트: {gen}</span>
  </div>

  <div class="page-flex">
    <div class="page-left">
      <div class="grid grid-row1">{row1}</div>
      {surge_row}
      <div class="grid grid-row2">{row2}</div>
      <div class="grid grid-row3">{row3}</div>
      {vcp_block}
    </div>
    {acct_block}
  </div>

  <div id="coinpop">
    <div class="cp-head">
      <span class="cp-title">-</span>
      <span class="cp-sub"></span>
      <div class="cp-tabs">
        <button class="cp-tab active" data-tab="5">5분봉</button>
        <button class="cp-tab" data-tab="d">일봉</button>
      </div>
    </div>
    <div class="cp-box">
      <div class="cp-col" id="cpCol5">
        <div class="cp-lab">5분봉 · RSI(14)</div>
        <div class="cp-chart" id="cpChart5"></div>
        <div class="cp-rsi" id="cpRsi5"></div>
      </div>
      <div class="cp-col" id="cpColD">
        <div class="cp-lab">일봉 · 기본 90봉 · RSI(14)</div>
        <div class="cp-chart" id="cpChartD"></div>
        <div class="cp-rsi" id="cpRsiD"></div>
      </div>
    </div>
  </div>

  <script src="lib/lightweight-charts.standalone.production.js"></script>
  <script>window.__COIN_DATA__ = {coin_data_js};</script>
  <script>
{popup_js}
  </script>
</body>
</html>
"""


def main():
    if not JSON_PATH.exists():
        print(f"❌ {JSON_PATH} 없음 — upbit_total.py 먼저 실행하세요.")
        return
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    html = build_html(data)
    OUT_HTML.write_text(html, encoding="utf-8")
    try:
        print(f"✅ coin.html 생성 완료 → {OUT_HTML}")
    except UnicodeEncodeError:
        print(f"[OK] coin.html generated -> {OUT_HTML}")


if __name__ == "__main__":
    main()
