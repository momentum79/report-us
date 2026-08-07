# make_index_kor_etf.py
import html
import pathlib
import datetime
import re
import json
import csv

# ── 현재가 조회 ────────────────────────────────────────────
def _sco_dist_bars(rows, total=None, analyzed=None, title=""):
    """coin게시판 스타일 SCO 분포 막대. rows=[(label, count, pct_str, color), ...]"""
    head = ""
    if total is not None:
        a = f' / 분석 <b>{analyzed}</b>개' if analyzed is not None else ""
        head = (f'<div style="font-size:0.72rem;color:#777;margin:0 0 4px;">'
                f'전체 <b>{total}</b>개{a}</div>')
    bars = ""
    for label, cnt, pct, color in rows:
        try:
            w = max(float(str(pct).replace('%', '').strip()), 2)
        except (TypeError, ValueError):
            w = 2
        bars += (
            '<div style="display:flex;align-items:center;gap:6px;margin:3px 0;font-size:0.78rem;">'
            f'<span style="width:60px;color:#555;flex-shrink:0;">{label}</span>'
            '<span style="flex:1;background:#eef0f1;border-radius:4px;height:11px;overflow:hidden;">'
            f'<span style="display:block;height:100%;border-radius:4px;width:{w}%;background:{color};"></span>'
            '</span>'
            f'<span style="width:96px;text-align:right;flex-shrink:0;color:#555;">{cnt}개 '
            f'<span style="color:#aaa;">({pct})</span></span>'
            '</div>'
        )
    t = (f'<div style="font-weight:bold;color:#000;font-size:0.9em;margin:0 0 4px;">{title}</div>'
         if title else "")
    return f'<div style="margin:0 0 10px;">{t}{head}{bars}</div>'


def _load_asset_8042() -> int:
    """asset_8042.json에서 추정자산(십만원 절하) 읽기. 없으면 API 직접 호출."""
    f = pathlib.Path(__file__).resolve().parent / "asset_8042.json"
    try:
        if f.exists():
            val = int(json.loads(f.read_text(encoding="utf-8")).get("estimated_asset", 0))
            if val > 0:
                return val
    except Exception:
        pass
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fetch_asset_8042",
            str(pathlib.Path(__file__).resolve().parent.parent / "fetch_asset_8042.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.fetch_and_save()
        if f.exists():
            return int(json.loads(f.read_text(encoding="utf-8")).get("estimated_asset", 0))
    except Exception:
        pass
    return 0

ASSET_8042 = _load_asset_8042()
PENSION_ASSET = 100_000_000  # 연금계좌 기준금액 (1억)
LOW_AMT_THRESHOLD = 5_000_000_000  # 10일 평균 거래대금 50억 미만 → 행 회색 처리

def _get_kor_price(ticker: str) -> float | None:
    """pykrx로 한국 ETF 현재가(당일/전일 종가) 조회"""
    try:
        from pykrx import stock as krx
        today = datetime.date.today().strftime("%Y%m%d")
        df = krx.get_market_ohlcv_by_date(today, today, ticker)
        if df.empty:
            past = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%Y%m%d")
            df = krx.get_market_ohlcv_by_date(past, today, ticker)
        if df.empty:
            return None
        return float(df["종가"].iloc[-1])
    except Exception as e:
        print(f"[현재가 오류] {ticker}: {e}")
        return None

REPORT_TXT = pathlib.Path(__file__).resolve().parent / "report_kor_etf.txt"
OUT_HTML   = pathlib.Path(__file__).resolve().parent / "kor_etf.html"
GANN_FIRE_JSON = pathlib.Path(__file__).resolve().parent / "kr_etf_gann_fire_set.json"
LOW_HISTORY_FILE = pathlib.Path(__file__).resolve().parent / "kor_etf_low_history.json"
REBALANCING_TXT = pathlib.Path(r"D:\py\0order\00_etf_korea_rebalancing.txt")

# ── Top3 CSV 경로 ──────────────────────────────────────────
WEEKLY_TOP3_CSV  = pathlib.Path(r"D:\py\report-us\etf_history\weekly_top3_kr.csv")
MONTHLY_TOP3_CSV = pathlib.Path(r"D:\py\report-us\etf_history\monthly_top3_kr.csv")


# ── 저점 신호 5일 추적 ────────────────────────────────────
def load_low_history() -> dict:
    if not LOW_HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(LOW_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[경고] 저점 이력 JSON 읽기 실패: {e}")
        return {}


def update_low_history(low_signals_dict: dict) -> dict:
    today     = datetime.date.today()
    today_str = today.isoformat()
    history   = load_low_history()

    to_delete = []
    for ticker, rec in history.items():
        try:
            first_date   = datetime.date.fromisoformat(rec["first_date"])
            days_elapsed = (today - first_date).days
            if days_elapsed > 7:
                to_delete.append(ticker)
        except Exception:
            to_delete.append(ticker)
    for ticker in to_delete:
        del history[ticker]

    for ticker, (jeo, jeo2) in low_signals_dict.items():
        new_jeo  = (jeo  != "-" and str(jeo).strip()  not in ("", "-", "0", "nan"))
        new_jeo2 = (jeo2 != "-" and str(jeo2).strip() not in ("", "-", "0", "nan"))
        has_signal = new_jeo or new_jeo2

        if has_signal:
            if ticker in history:
                rec      = history[ticker]
                old_jeo  = rec.get("signal_jeo",  False)
                old_jeo2 = rec.get("signal_jeo2", False)
                if new_jeo != old_jeo or new_jeo2 != old_jeo2:
                    history[ticker] = {
                        "first_date":  today_str,
                        "signal_jeo":  new_jeo,
                        "signal_jeo2": new_jeo2,
                    }
            else:
                history[ticker] = {
                    "first_date":  today_str,
                    "signal_jeo":  new_jeo,
                    "signal_jeo2": new_jeo2,
                }

    LOW_HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return history


def get_low_badge(ticker: str, history: dict) -> str:
    if ticker not in history:
        return ""
    rec = history[ticker]
    try:
        first_date   = datetime.date.fromisoformat(rec["first_date"])
        days_elapsed = (datetime.date.today() - first_date).days
    except Exception:
        return ""

    if days_elapsed == 0:
        sig_jeo  = rec.get("signal_jeo",  False)
        sig_jeo2 = rec.get("signal_jeo2", False)
        if sig_jeo and sig_jeo2:
            return '<span class="low-badge low-both">저1,2</span>'
        elif sig_jeo:
            return '<span class="low-badge low-jeo">저</span>'
        elif sig_jeo2:
            return '<span class="low-badge low-jeo2">저2</span>'
    elif 1 <= days_elapsed <= 5:
        return f'<span class="low-badge low-track">{days_elapsed}저</span>'

    return ""

def extract_block(lines, start_keys, end_keys=None):
    start = None
    for i, line in enumerate(lines):
        if any(k in line for k in start_keys):
            start = i
            break
    if start is None:
        return None

    end = len(lines)
    if end_keys:
        for i in range(start + 1, len(lines)):
            if any(lines[i].startswith(k) for k in end_keys):
                end = i
                break

    return "\n".join(lines[start:end]).strip()


# ══════════════════════════════════════════════════════════
# ── 🆕 당일/주간/월간 Top3 카드 섹션 ──────────────────────
# ══════════════════════════════════════════════════════════

def _parse_top3_entry(entry: str) -> list[str]:
    """
    'ETF명(티커)\nETF명(티커)\nETF명(티커)' → ['ETF명(티커)', ...]
    """
    lines = [l.strip() for l in entry.strip().splitlines() if l.strip()]
    return lines[:3]


def get_weekly_top3() -> tuple[str, list[str]]:
    """
    weekly CSV 첫 번째 행(최신 월 블록)의 마지막 차수 top3 반환.
    Returns: (label, ['ETF명(티커)', ...])  e.g. ('4월3주', ['반도체(091160)', ...])
    """
    if not WEEKLY_TOP3_CSV.exists():
        return ("", [])
    try:
        import io
        text = WEEKLY_TOP3_CSV.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))  # 멀티라인 셀 정상 파싱
        # 2행1쌍 블록들 → 모든 주 컬럼을 시간순(오래된→최신)으로 수집.
        #   블록은 '최신월이 맨 위' 저장 → 블록 역순 + 블록내 좌→우(1주→5주) = 전체 시간순.
        #   월초 첫 월요일처럼 '지난주'가 전월 블록에 있어도 정확히 잡힘.
        blocks = []
        for i in range(0, len(rows) - 1, 2):
            labels = [c.strip() for c in rows[i]]
            data   = list(rows[i + 1])
            pairs  = [(lab, data[j]) for j, lab in enumerate(labels)
                      if lab and j < len(data) and data[j].strip()]
            blocks.append(pairs)
        flat = [p for block in reversed(blocks) for p in block]
        if not flat:
            return ("", [])
        # 월요일: 이번 주 집계는 오늘 하루뿐(당일과 동일) → 지난주(완성된 한 주) 표시.
        idx = -1
        if datetime.date.today().weekday() == 0 and len(flat) >= 2:
            idx = -2
        label_raw, entry = flat[idx]
        label = re.sub(r'^\d{4}\.', '', label_raw)
        return (label, _parse_top3_entry(entry))
    except Exception as e:
        print(f"[주간 Top3 파싱 오류] {e}")
        return ("", [])


def get_monthly_top3() -> tuple[str, list[str]]:
    """
    monthly CSV에서 현재 연/월에 해당하는 top3 반환.
    Returns: (label, ['ETF명', ...])  e.g. ('4월', ['건설주', '이차전', '반도체'])
    """
    if not MONTHLY_TOP3_CSV.exists():
        return ("", [])
    try:
        today = datetime.date.today()
        # 그 달 1주차(1~7일)엔 이번 달 집계가 주간 카드와 겹침 → 지난달(완성된 달) 표시.
        #   2주차(8일~)부터 이번 달.
        if today.day <= 7:
            ref = today.replace(day=1) - datetime.timedelta(days=1)  # 지난달 말일
        else:
            ref = today
        target_key = f"{ref.year}.{ref.month:02d}"  # '2026.04'

        import io
        text = MONTHLY_TOP3_CSV.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))  # 멀티라인 셀 정상 파싱

        i = 0
        while i < len(rows):
            header_row = rows[i]
            data_row   = rows[i + 1] if i + 1 < len(rows) else []
            headers = [c.strip() for c in header_row]
            for j, hdr in enumerate(headers):
                if hdr == target_key and j < len(data_row):
                    entry = data_row[j].strip()
                    if entry:
                        label = f"{ref.month}월"
                        return (label, _parse_top3_entry(entry))
            i += 2
        return ("", [])
    except Exception as e:
        print(f"[월간 Top3 파싱 오류] {e}")
        return ("", [])


def get_daily_top3(rank_block: str) -> list[str]:
    """
    rank_block 텍스트에서 상위 3행 파싱 → ['ETF명(티커)', ...] 반환
    """
    result = []
    for line in rank_block.splitlines():
        line = line.strip()
        if not line or line.startswith('Ticker') or all(c in '-=' for c in line):
            continue
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 2:
            cols = line.split()
        if not cols:
            continue
        raw_ticker = cols[0].strip().lstrip('X_')
        ticker_match = re.search(r'(\d{6})', raw_ticker)
        if not ticker_match:
            continue
        ticker = ticker_match.group(1)
        name   = cols[1].strip().lstrip('X_') if len(cols) > 1 else ""
        result.append(f"{name}({ticker})")
        if len(result) >= 3:
            break
    return result


MEDALS = ["🥇", "🥈", "🥉"]

def _top3_mini_card(card_id: str, title: str, label: str, items: list[str], border_color: str, bg_color: str = "#ffffff") -> str:
    """
    컴팩트 Top3 카드 HTML 생성
    card_id: 'daily' | 'weekly' | 'monthly'
    items: ['ETF명(티커)', ...] (1~3개)
    """
    if not items:
        body = '<div class="t3-empty">데이터 없음</div>'
    else:
        body = ""
        for i, item in enumerate(items[:3]):
            medal = MEDALS[i] if i < 3 else f"#{i+1}"
            m = re.search(r'\(([^)]+)\)$', item)
            ticker = m.group(1) if m else ""
            name   = item[:item.rfind('(')] if m else item
            ticker_html = (
                f'<a href="https://finance.naver.com/item/main.naver?code={ticker}" '
                f'target="_blank" rel="noopener" class="t3-ticker">{ticker}</a>'
            ) if ticker else ""
            body += f"""
      <div class="t3-row">
        <span class="t3-medal">{medal}</span>
        <span class="t3-name">{html.escape(name)}</span>
        {ticker_html}
      </div>"""

    label_html = f'<span class="t3-label">{html.escape(label)}</span>' if label else ""

    return f"""
<div class="t3-card" style="border-top:3px solid {border_color}; background:{bg_color};">
  <div class="t3-header" style="background:{bg_color};">
    <span class="t3-title">{title}</span>
    {label_html}
  </div>
  <div class="t3-body">{body}
  </div>
</div>"""


def build_top3_section(rank_block: str) -> str:
    """🧾 당일/주간/월간 Top3 카드 섹션 HTML"""
    today = datetime.date.today()
    daily_label = f"{today.month}/{today.day}"
    daily_items = get_daily_top3(rank_block)

    weekly_label, weekly_items = get_weekly_top3()
    monthly_label, monthly_items = get_monthly_top3()

    daily_card   = _top3_mini_card("daily",   "📅 당일",  daily_label,   daily_items,   "#3498db", "#e8f5e9")
    weekly_card  = _top3_mini_card("weekly",  "📆 주간",  weekly_label,  weekly_items,  "#27ae60", "#dfffff")
    monthly_card = _top3_mini_card("monthly", "📊 월간",  monthly_label, monthly_items, "#e67e22", "#ffffdf")

    return f"""
<div class="t3-section">
  <div class="t3-section-title">🧾 당일/주간/월간 Top3</div>
  <div class="t3-cards-row">
    {daily_card}
    {weekly_card}
    {monthly_card}
  </div>
</div>"""


# ══════════════════════════════════════════════════════════
# (이하 기존 함수 그대로)
# ══════════════════════════════════════════════════════════

import re

def _build_final_order_table(held_list, rank_block, s_data, idx_rel_map=None):
    if not held_list:
        return '<p style="color:#7f8c8d;">보유 종목 없음 (현금 100%)</p>'

    # sc3 (운영 대표) 와 s1 (비교용) per_ticker_alloc 둘 다 읽기
    per_ticker_alloc_sc3 = s_data.get('per_ticker_alloc_sc3')
    if per_ticker_alloc_sc3 is None:
        # 구버전 호환: per_ticker_alloc 이 sc3 라고 가정
        per_ticker_alloc_sc3 = s_data.get('per_ticker_alloc')
    per_ticker_alloc_s1  = s_data.get('per_ticker_alloc_s1', [])
    internal_weights     = s_data.get('internal_weights', [])
    top3_k_tickers       = s_data.get('top3_k_tickers', [])
    k_mult               = s_data.get('kospi_mult', 0)
    us_mult              = s_data.get('nasdaq_mult', 0)
    sc3_ok               = s_data.get('sc3_ok', True)  # sc3 계산 성공 여부

    def _to_alloc_map(alloc_list):
        m = {}
        if not alloc_list:
            return m
        for entry in alloc_list:
            tk = str(entry.get('ticker', '')).strip()
            if not tk:
                continue
            try:
                m[tk] = float(entry.get('effective_pct', 0))
            except (TypeError, ValueError):
                m[tk] = 0
        return m

    alloc_pct_sc3 = _to_alloc_map(per_ticker_alloc_sc3)
    alloc_pct_s1  = _to_alloc_map(per_ticker_alloc_s1)

    # sc3 데이터가 없으면 구버전 호환 폴백 (internal_weights × 시장 mult)
    if not alloc_pct_sc3:
        for i, tk in enumerate(held_list):
            w = internal_weights[i] / 100.0 if i < len(internal_weights) else 0
            mult = k_mult if tk in top3_k_tickers else us_mult
            alloc_pct_sc3[tk] = w * mult * 100

    alloc_pct = alloc_pct_sc3  # '비중' 컬럼은 sc3 기준

    price_map = {}
    for tk in held_list:
        price_map[tk] = _get_kor_price(tk)

    rank_rows = {}
    for line in rank_block.splitlines():
        line = line.strip()
        if not line or line.startswith('Ticker') or all(c in '-=' for c in line):
            continue
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 5:
            cols = line.split()
        if not cols:
            continue
        raw_ticker = cols[0].strip()
        is_warn_x = raw_ticker.startswith('X_')
        if is_warn_x:
            raw_ticker = raw_ticker[2:]
        ticker_match = re.search(r'(\d{6,}|[0-9A-Z]{6,})', raw_ticker)
        if ticker_match:
            tk = ticker_match.group(1)
            rank_rows[tk] = (cols, is_warn_x)

    rows_html = []
    rebalancing_rows = []
    for tk in held_list:
        data = rank_rows.get(tk)
        cols, is_warn_x = data if data else (None, False)

        if cols is None or len(cols) < 5:
            rows_html.append(f'<tr><td class="narrow held-bold">{html.escape(tk)}</td>'
                             f'<td colspan="5" style="color:#999;">데이터 없음</td></tr>')
            continue

        ticker_disp = cols[0].strip()
        if ticker_disp.startswith('X_'):
            ticker_disp = ticker_disp[2:]

        name_disp = cols[1].strip()
        if name_disp.startswith('X_'):
            name_disp = name_disp[2:]

        chg_str  = cols[2] if len(cols) > 2 else '-'
        pos_str  = cols[3] if len(cols) > 3 else '-'
        sco_str  = cols[4] if len(cols) > 4 else '-'

        pct_val = alloc_pct.get(tk)
        if pct_val is not None:
            pct_disp = f'{pct_val:.1f}%'
            pct_color_style = 'color:#27ae60;font-weight:bold;' if pct_val >= 20 else 'color:#e67e22;font-weight:bold;'
        else:
            pct_disp = '-'
            pct_color_style = 'color:#999;'

        try:
            chg_val = float(re.sub(r'[^\d.+-]', '', chg_str))
            chg_cls = 'sig-up' if chg_val > 0 else ('sig-down' if chg_val < 0 else '')
        except:
            chg_cls = ''

        pos_badge = f'<span class="pos-badge pos-{pos_str}">{html.escape(pos_str)}</span>' if pos_str in ('1','2','3','4','5') else html.escape(pos_str)

        idx_rel_val = (idx_rel_map or {}).get(tk)
        if idx_rel_val is not None:
            try:
                irv = float(idx_rel_val)
                ir_cls = 'sig-up' if irv > 0 else ('sig-down' if irv < 0 else '')
                ir_disp = f'{irv:+.1f}%'
            except:
                ir_cls = ''
                ir_disp = '-'
        else:
            ir_cls = ''
            ir_disp = '-'

        price = price_map.get(tk)
        pct_sc3 = alloc_pct_sc3.get(tk, 0)
        pct_s1  = alloc_pct_s1.get(tk, 0)
        if ASSET_8042 > 0 and price and price > 0:
            qty_sc3     = int(ASSET_8042   * pct_sc3 / 100 / price) if pct_sc3 > 0 else 0
            qty_s1      = int(ASSET_8042   * pct_s1  / 100 / price) if pct_s1  > 0 else 0
            pension_qty = int(PENSION_ASSET * pct_sc3 / 100 / price) if pct_sc3 > 0 else 0  # 연금 = sc3 만
            qty_sc3_disp     = f'{qty_sc3:,}주'     if qty_sc3 > 0     else '-'
            qty_s1_disp      = f'{qty_s1:,}주'      if qty_s1 > 0      else '-'
            pension_qty_disp = f'{pension_qty:,}주' if pension_qty > 0 else '-'
            qty_amt_disp     = f'{int(qty_sc3 * price / 10000):,}만원'     if qty_sc3 > 0     else '-'
            pension_amt_disp = f'{int(pension_qty * price / 10000):,}만원' if pension_qty > 0 else '-'
            if qty_sc3 > 0:
                rebalancing_rows.append(f"{tk},{qty_sc3}")  # 주문 파일은 sc3 만
        else:
            qty_sc3_disp = '-'
            qty_s1_disp  = '-'
            pension_qty_disp = '-'
            qty_amt_disp = '-'
            pension_amt_disp = '-'

        row_cls = 'warn-x' if is_warn_x else ''
        rows_html.append(
            f'<tr class="{row_cls}">'
            f'<td class="narrow held-bold" data-code="{html.escape(tk)}" data-name="{html.escape(name_disp)}">{html.escape(ticker_disp)}</td>'
            f'<td class="name-col held-bold">{html.escape(name_disp)}</td>'
            f'<td class="{chg_cls}">{html.escape(chg_str)}</td>'
            f'<td>{pos_badge}</td>'
            f'<td>{html.escape(sco_str)}</td>'
            f'<td style="{pct_color_style}">{pct_disp}</td>'
            f'<td class="{ir_cls}">{ir_disp}</td>'
            f'<td style="font-weight:bold;">{qty_sc3_disp}</td>'
            f'<td style="color:#7f8c8d;">{qty_s1_disp}</td>'
            f'<td class="pc-only" style="color:#555;">{qty_amt_disp}</td>'
            f'<td style="font-weight:bold;color:#8e44ad;">{pension_qty_disp}</td>'
            f'<td class="pc-only" style="color:#8e44ad;">{pension_amt_disp}</td>'
            f'</tr>'
        )

    # 주문 파일: sc3 정상일 때만 갱신 (실패 시 전일 값 유지)
    if sc3_ok:
        try:
            REBALANCING_TXT.write_text("\n".join(rebalancing_rows), encoding="utf-8")
            print(f"[리밸런싱] 저장: {REBALANCING_TXT} ({len(rebalancing_rows)}개 종목, sc3 기준)")
        except Exception as e:
            print(f"[리밸런싱 저장 실패] {e}")
    else:
        print(f"⚠️ [리밸런싱] sc3 계산 실패 → {REBALANCING_TXT} 미갱신 (전일 값 유지)")

    thead_html = (
        '<thead><tr>'
        '<th>ticker</th>'
        '<th>Name</th>'
        '<th>등락</th>'
        '<th>위치</th>'
        '<th>sco</th>'
        '<th>비중</th>'
        '<th>지수대비(%)</th>'
        '<th>수량(sc3)</th>'
        '<th>수량(s1)</th>'
        '<th class="pc-only">총액</th>'
        '<th>연금</th>'
        '<th class="pc-only">총액</th>'
        '</tr></thead>'
    )
    return '<table class="styled-table final-order-table">\n' + thead_html + '\n<tbody>\n' + '\n'.join(rows_html) + '\n</tbody></table>'


def char_to_rank(c: str):
    if c in ('x', '-'):
        return None
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return 10 + (ord(c.upper()) - ord('A'))
    return None


def is_rank_rising(name: str) -> bool:
    m = re.search(r'\(([A-Za-z0-9x\-]{4})\)$', name)
    if not m:
        return False
    ranks = [char_to_rank(ch) for ch in m.group(1)]
    if any(r is None for r in ranks):
        return False
    today, d1, d2, d3 = ranks
    if today <= 3:
        return True
    top3days_all_in_top5 = (today <= 5 and d1 <= 5 and d2 <= 5)
    for cur, prev in [(today, d1), (d1, d2), (d2, d3)]:
        if cur <= prev:
            continue
        if top3days_all_in_top5:
            continue
        return False
    return True


def _fmt_ref_num(v, mul=1.0, dp=1):
    """참조칼럼(Base/Stab/하방/MDD/Spike) 숫자 포맷. None/오류 → '-'."""
    if v is None:
        return "-"
    try:
        return f"{float(v) * mul:.{dp}f}"
    except (TypeError, ValueError):
        return "-"


def text_to_html_table(text, held_list=None, add_header=False, header_cols=None, low_signals_dict=None, idx_rel_map=None, lime_thresh_map=None, gann_fire_set=None, low_history=None, stab_map=None, low_amt_set=None):
    if low_signals_dict is None:
        low_signals_dict = {}
    if lime_thresh_map is None:
        lime_thresh_map = {}
    if gann_fire_set is None:
        gann_fire_set = set()
    if low_amt_set is None:
        low_amt_set = set()

    if not text:
        return ""
    if len(text.strip().splitlines()) <= 2 and "없음" in text:
        return f'<p>{html.escape(text)}</p>'
    
    raw_lines = text.strip().splitlines()
    if not raw_lines: return ""

    SKIP_PATTERNS = ['투자금액 배분된', '시간']
    data_lines = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped: continue
        if all(c in '-=' for c in stripped): continue
        if any(p in stripped for p in SKIP_PATTERNS): continue
        data_lines.append(stripped)
    if not data_lines: return f'<pre>{html.escape(text)}</pre>'

    html_output = ['<table class="styled-table">']
    
    first_line = data_lines[0].strip()
    is_header = first_line.startswith("Ticker")
    
    start_idx = 0
    if is_header:
        headers = header_cols or ["Ticker", "Name", "등락", "위치", "Sco", "RSI", "정", "5", "10", "20", "60", "120", "136평", "3M(%)", "Score", "저점", "지수대비"]
        html_output.append("<thead><tr>" + "".join(f"<th>{html.escape(h.strip())}</th>" for h in headers) + "</tr></thead>")
        start_idx = 1
    elif add_header and header_cols:
        html_output.append("<thead><tr>" + "".join(f"<th>{html.escape(h.strip())}</th>" for h in header_cols) + "</tr></thead>")
        
    html_output.append("<tbody>")
    for line in data_lines[start_idx:]:
        line = line.strip()
        if not line: continue
        
        cols = re.split(r'\s{2,}', line)
        if len(cols) < 5: cols = line.split()

        current_ticker = ""
        is_warn_x = False
        if len(cols) > 0:
            raw_ticker = cols[0].strip()
            if raw_ticker.startswith("X_"):
                is_warn_x = True
                cols[0] = raw_ticker[2:]
            if len(cols) > 1 and cols[1].strip().startswith("X_"):
                cols[1] = cols[1].strip()[2:]
            ticker_match = re.search(r'([0-9A-Z]{6,})', cols[0])
            if ticker_match:
                current_ticker = ticker_match.group(1)
        
        highlight_class = ""
        if held_list and current_ticker in held_list:
            ticker_idx = held_list.index(current_ticker)
            highlight_class = "held-bold" if (len(held_list) <= 3 or ticker_idx < 3) else "held-plain"
        
        name_style = ""
        trend_val = cols[12].upper() if len(cols) > 12 else ""
        if "LIME" in trend_val or trend_val == "3":
            name_style = 'style="background-color:#2ecc71; color:black; font-weight:bold;"'
        elif "GREEN" in trend_val or trend_val == "2" or trend_val == "1":
            color = "#8ed99f" if (trend_val == "2" or "GREEN" in trend_val) else "#cdeccf"
            name_style = f'style="background-color:{color}; color:black; font-weight:bold;"'
        elif "RED" in trend_val or trend_val == "-3" or trend_val == "-1":
            color = "#e74c3c" if (trend_val == "-3" or "RED" in trend_val) else "#ef9a9a"
            text_color = "white" if (trend_val == "-3" or "RED" in trend_val) else "black"
            name_style = f'style="background-color:{color}; color:{text_color}; font-weight:bold;"'
        elif "PURPLE" in trend_val or trend_val == "-2":
            name_style = 'style="background-color:#9b59b6; color:white; font-weight:bold;"'

        row_cls_list = []
        if is_warn_x:
            row_cls_list.append('warn-x')
        if current_ticker in low_amt_set:
            row_cls_list.append('low-amt')
        row_html = f'<tr class="{" ".join(row_cls_list)}">' if row_cls_list else "<tr>"

        lt_pre = lime_thresh_map.get(current_ticker)
        sco_bg = ""
        if lt_pre:
            ll_pre, _ = lt_pre
            if ll_pre.startswith('▲'):
                sco_bg = 'background-color:#fff176;'
            else:
                sco_bg = 'background-color:#ffe0b2;'

        for i, c in enumerate(cols):
            if i == 12 or i == 16 or i >= 17: continue

            cell_class = []
            content = html.escape(c)
            extra_style = ""
            data_attrs = ""

            if i == 0:
                cell_class.append("narrow")
                if highlight_class: cell_class.append(highlight_class)
                if current_ticker:
                    _nm = html.escape(cols[1].strip() if len(cols) > 1 else "")
                    data_attrs = f' data-code="{html.escape(current_ticker)}" data-name="{_nm}"'
            elif i == 1:
                cell_class.append("name-col")
                if highlight_class: cell_class.append(highlight_class)
                if is_rank_rising(c):
                    content = content + "★"
                    extra_style = name_style if name_style else 'style="color:black; font-weight:bold;"'
                else:
                    extra_style = name_style
            elif i == 2:
                try:
                    val = float(re.sub(r'[^\d.+-]', '', c))
                    cell_class.append("sig-up" if val > 0 else ("sig-down" if val < 0 else ""))
                except: pass
            elif i == 3:
                pos_val = c.strip()
                if pos_val in ("1","2","3","4","5"):
                    content = f'<span class="pos-badge pos-{pos_val}">{content}</span>'
                elif c == "5": cell_class.append("pos-5")
                elif c == "4": cell_class.append("pos-4")
            elif i == 4:
                if sco_bg:
                    extra_style = f'style="{sco_bg}font-weight:bold;"'
            elif i == 5:
                m_rsi = re.match(r'(\d+)\((\d+)\)', c.strip())
                if m_rsi:
                    today_rsi = int(m_rsi.group(1))
                    prev_rsi  = int(m_rsi.group(2))
                    cell_class.append("up" if today_rsi >= 50 else "down")
                    if today_rsi >= 30 and prev_rsi < 30:
                        extra_style = 'style="background-color:#d5f5e3; font-weight:bold;"'
            elif i == 6:
                if "정배" in c: cell_class.append("sig-jung")
                elif "역배" in c: cell_class.append("sig-yeok")
            elif 7 <= i <= 11:
                if c.strip() == '상': cell_class.append("up")
                elif c.strip() == '하': cell_class.append("down")
            elif i == 13:
                try:
                    num_val = float(c.replace('%', ''))
                    cell_class.append("up" if num_val > 0 else ("down" if num_val < 0 else ""))
                except: pass

            cls_str = f' class="{" ".join(cell_class)}"' if cell_class else ''
            style_str = f' {extra_style}' if extra_style else ''
            row_html += f"<td{cls_str}{style_str}{data_attrs}>{content}</td>"

        # 📊 참조칼럼(표시전용, Score 오른쪽): Base·Stab·하방%·MDD%·Spike
        #    통합ETF와 동일 계산값(jasantop4_final.py → kr_etf_stab.json). 랭킹엔 미반영.
        sm = {}
        if stab_map:
            sm = stab_map.get(current_ticker) or stab_map.get(current_ticker.zfill(6)) or {}
        row_html += f'<td class="narrow">{_fmt_ref_num(sm.get("base"), 100, 1)}</td>'
        row_html += f'<td class="narrow">{_fmt_ref_num(sm.get("stab"), 1, 2)}</td>'
        row_html += f'<td class="narrow">{_fmt_ref_num(sm.get("downside"), 1, 1)}</td>'
        row_html += f'<td class="narrow">{_fmt_ref_num(sm.get("mdd"), 1, 1)}</td>'
        row_html += f'<td class="narrow">{_fmt_ref_num(sm.get("spike"), 1, 2)}</td>'

        if low_history is not None:
            low_badge = get_low_badge(current_ticker, low_history)
        else:
            jeo, jeo2 = (low_signals_dict or {}).get(current_ticker, ('-', '-'))
            low_badge = ""
            if jeo != '-' and jeo2 != '-':
                low_badge = '<span class="low-badge low-both">저1,2</span>'
            elif jeo != '-':
                low_badge = '<span class="low-badge low-jeo">저</span>'
            elif jeo2 != '-':
                low_badge = '<span class="low-badge low-jeo2">저2</span>'

        if current_ticker.zfill(6) in gann_fire_set:
            low_badge += ' <span style="display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:bold;background:#2980b9;color:white;">🔥</span>'

        row_html += f"<td>{low_badge}</td>"
        
        if idx_rel_map is None:
            idx_rel_map = {}
        idx_rel_val = idx_rel_map.get(current_ticker)
        if idx_rel_val is not None:
            try:
                irv = float(idx_rel_val)
                ir_cls = 'sig-up' if irv > 0 else ('sig-down' if irv < 0 else '')
                ir_disp = f'{irv:+.1f}%'
            except:
                ir_cls = ''
                ir_disp = '-'
        else:
            ir_cls = ''
            ir_disp = '-'
        row_html += f'<td class="{ir_cls}">{ir_disp}</td>'

        lt = lime_thresh_map.get(current_ticker)
        if lt:
            ll, lp = lt
            is_entry = ll.startswith('▲')
            lt_color = '#27ae60' if is_entry else '#e74c3c'
            lt_disp  = f'{ll} {lp:,}'
            row_html += f'<td style="color:{lt_color};font-weight:bold;white-space:nowrap;">{lt_disp}</td>'
        else:
            row_html += '<td></td>'
        
        row_html += "</tr>"
        html_output.append(row_html)
    html_output.append("</tbody></table>")
    return "\n".join(html_output)


def main():
    text = REPORT_TXT.read_text(encoding="utf-8", errors="replace") if REPORT_TXT.exists() else ""
    lines = text.splitlines()
    lines = [
        line for line in lines
        if "매매용 티커 목록이" not in line
        and "점수 순위대로 정렬" not in line
    ]

    rank_block = extract_block(
        lines,
        start_keys=["전체 종목 (투자금액 배분 순)", "투자금액 배분된 종목"],
        end_keys=["이전 보유 종목:", "현재 Top 3:", "현재 Top3", "✅", "최종 보유 종목"]
    ) or "(랭킹 없음)"

    final_hold = extract_block(
        lines,
        start_keys=["최종 보유 종목"],
        end_keys=["[ATR 트리거", "[ATR 트레일링", "✅ 매매용", "\n\n"]
    ) or "(최종 보유 종목 없음)"

    held_list = []
    if final_hold:
        held_match = re.search(r"최종 보유 종목.*?:\s*\[(.+?)\]", final_hold)
        if held_match:
            held_list = [t.strip().strip("'").strip('"') for t in held_match.group(1).split(',')]
        else:
            held_match2 = re.search(r'\[(.*?)\]', final_hold)
            if held_match2:
                held_list = [t.strip().strip("'").strip('"') for t in held_match2.group(1).split(',')]

    if rank_block and rank_block != "(랭킹 없음)":
        first = rank_block.splitlines()[0]
        if "투자금액 배분" in first or "전체 종목" in first:
            rank_block = "\n".join(rank_block.splitlines()[1:]).strip()

    atr_trigger = extract_block(
        lines,
        start_keys=["[ATR 트리거"],
        end_keys=["[ATR 트레일링"]
    )
    if atr_trigger and "[" in atr_trigger:
        tr_lines = [l for l in atr_trigger.splitlines() 
                    if not l.strip().startswith("[") 
                    and "Ticker" not in l 
                    and "종목 수" not in l and "수:" not in l]
        atr_trigger = "\n".join(tr_lines).strip()
    atr_trigger = atr_trigger or "[ATR 트리거 종목] 없음"

    atr_exclude = extract_block(
        lines,
        start_keys=["[ATR 트레일링"],
        end_keys=["[실행 소요 시간]", "========================================"]
    )
    if atr_exclude and "[" in atr_exclude:
        ex_lines = [l for l in atr_exclude.splitlines() 
                    if not l.strip().startswith("[") 
                    and "Ticker" not in l 
                    and "종목 수" not in l and "수:" not in l]
        atr_exclude = "\n".join(ex_lines).strip()
    atr_exclude = atr_exclude or "[ATR 트레일링] 없음"

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    investor_html = ""
    investor_file = pathlib.Path(__file__).resolve().parent / "investor_data.json"
    if investor_file.exists():
        try:
            inv_data = json.loads(investor_file.read_text(encoding="utf-8"))
            kpi = inv_data.get('KOSPI', {})
            kdq = inv_data.get('KOSDAQ', {})
            investor_html = f"""
<p style="margin: 0; font-size: 0.9em; color: #34495e;">Kospi200 ({kpi.get('change_rate','0%')}) : 외국인 {kpi.get('foreigner','0')}억 / 연기금 {kpi.get('pension','0')}억</p>
<p style="margin: 0; font-size: 0.9em; color: #34495e;">Kosdaq150 ({kdq.get('change_rate','0%')}): 외국인 {kdq.get('foreigner','0')}억 / 연기금 {kdq.get('pension','0')}억</p>
"""
        except:
            pass

    paa_invest_pct_str = ""
    adv_html_file = pathlib.Path(__file__).resolve().parent / "adv_momentum.html"
    if adv_html_file.exists():
        try:
            adv_text = adv_html_file.read_text(encoding="utf-8")
            paa_match = re.search(r'투자비중\s*(\d+(?:\.\d+)?%)', adv_text)
            if paa_match:
                paa_invest_pct_str = paa_match.group(1)
        except:
            pass

    stats_html = ""
    stats_file = pathlib.Path(__file__).resolve().parent / "kr_signal_stats.json"

    low_signals_dict = {}
    idx_rel_map = {}
    lime_thresh_map = {}
    low_amt_set = set()   # 10일 평균 거래대금 50억 미만
    low_signal_file = pathlib.Path(__file__).resolve().parent / "kr_etf_low_signals.json"
    if low_signal_file.exists():
        try:
            low_data = json.loads(low_signal_file.read_text(encoding="utf-8"))
            for sig in low_data.get('signals', []):
                ticker = sig.get('ticker', '')
                jeo = sig.get('jeo', '-')
                jeo2 = sig.get('jeo2', '-')
                low_signals_dict[ticker] = (jeo, jeo2)
                if sig.get('idx_rel') is not None:
                    idx_rel_map[ticker] = sig['idx_rel']
                if sig.get('lime_label') and sig.get('lime_price') is not None:
                    lime_thresh_map[ticker] = (sig['lime_label'], sig['lime_price'])
                _a10 = sig.get('amt10')
                if _a10 is not None and _a10 < LOW_AMT_THRESHOLD:
                    low_amt_set.add(ticker)
        except:
            pass

    gann_fire_set = set()
    if GANN_FIRE_JSON.exists():
        try:
            gann_data = json.loads(GANN_FIRE_JSON.read_text(encoding='utf-8'))
            gann_fire_set = set(str(t).strip().zfill(6) for t in gann_data.get('tickers', []))
        except Exception:
            gann_fire_set = set()

    # 📊 참조칼럼(Base/Stab/하방%/MDD%/Spike) — jasantop4_final.py 산출값 (표시전용)
    stab_map = {}
    stab_json_file = pathlib.Path(__file__).resolve().parent / "kr_etf_stab.json"
    if stab_json_file.exists():
        try:
            stab_map = json.loads(stab_json_file.read_text(encoding='utf-8')).get('stab', {}) or {}
        except Exception:
            stab_map = {}

    def parse_trend(val):
        COLOR = {
            'LIME':   '#2ecc71',
            'GREEN':  '#27ae60',
            'PURPLE': '#9b59b6',
            'RED':    '#e74c3c',
        }
        v = (val or '-').strip()
        color = COLOR.get(v.upper(), '#7f8c8d')
        return f'<b style="color:{color};">{v}</b>'

    bench_html = ""
    bench_line1 = next((l for l in lines if '[벤치마크 추세]' in l), None)
    bench_line2 = None
    if bench_line1:
        idx = lines.index(bench_line1)
        if idx + 1 < len(lines) and '에센피' in lines[idx + 1]:
            bench_line2 = lines[idx + 1]

    def extract_trend(line, key):
        m = re.search(rf'{key}:\s*(\S+)', line)
        return m.group(1) if m else '-'

    if bench_line1:
        kospi  = extract_trend(bench_line1, '코스피')
        kosdaq = extract_trend(bench_line1, '코스닥')
        sp500  = extract_trend(bench_line2, '에센피') if bench_line2 else '-'
        nasdaq = extract_trend(bench_line2, '나스닥') if bench_line2 else '-'
        bench_html = f"""
<p style="margin:0; font-size:0.95em;">
    🌐 &nbsp;
    <span class="label">코스피:</span> {parse_trend(kospi)} &nbsp;/&nbsp;
    <span class="label">코스닥:</span> {parse_trend(kosdaq)} &nbsp;&nbsp;|&nbsp;&nbsp;
    <span class="label">에센피:</span> {parse_trend(sp500)} &nbsp;/&nbsp;
    <span class="label">나스닥:</span> {parse_trend(nasdaq)}
</p>"""

    s_data = {}
    if stats_file.exists():
        try:
            s_data = json.loads(stats_file.read_text(encoding="utf-8"))
            invest_pct      = s_data.get('invest_pct', 0)            # 운영 대표값 (sc3)
            invest_pct_sc3  = s_data.get('invest_pct_sc3')           # 비교용 sc3 (= invest_pct)
            invest_pct_s1   = s_data.get('invest_pct_s1', 0)         # 비교용 s1 (기존)
            if invest_pct_sc3 is None:
                invest_pct_sc3 = invest_pct                          # 구버전 호환

            # sc3 실패 여부는 kr_sc3_status.json 으로 판정 (실패 시 kr_signal_stats.json 은 갱신 안 됨)
            sc3_ok = True
            sc3_status_path = pathlib.Path(__file__).resolve().parent / "kr_sc3_status.json"
            if sc3_status_path.exists():
                try:
                    _st = json.loads(sc3_status_path.read_text(encoding="utf-8"))
                    sc3_ok = bool(_st.get('sc3_ok', True))
                except Exception:
                    sc3_ok = True
            s_data['sc3_ok'] = sc3_ok  # _build_final_order_table 가 참조
            strong_cnt  = s_data.get('strong_count', 0)
            t_sco       = s_data.get('top3_avg_sco')
            t_pos       = s_data.get('top3_avg_pos')
            t_sco_str   = f"{t_sco:.2f}" if t_sco is not None else "-"
            t_pos_str   = f"{t_pos:.2f}" if t_pos is not None else "-"

            k_trend   = s_data.get('kospi_trend',  '-')
            kd_trend  = s_data.get('kosdaq_trend', '-')
            sp_trend  = s_data.get('sp500_trend',  '-')
            us_trend  = s_data.get('nasdaq_trend', '-')
            euro_trend  = s_data.get('euro_trend',  '-')
            india_trend = s_data.get('india_trend', '-')
            nikkei_trend = s_data.get('nikkei_trend', '-')
            k_mult    = s_data.get('kospi_mult',  '-')
            us_mult   = s_data.get('nasdaq_mult', '-')
            k_mult_str  = f"×{k_mult}"  if k_mult  != '-' else '-'
            us_mult_str = f"×{us_mult}" if us_mult != '-' else '-'

            TREND_COLOR = {
                'LIME':   '#2ecc71',
                'GREEN':  '#27ae60',
                'PURPLE': '#9b59b6',
                'RED':    '#e74c3c',
            }

            def bench_cell(label, trend, code, scope):
                color = TREND_COLOR.get((trend or '').upper(), '#95a5a6')
                return (
                    f'<td class="index-trigger" data-index-code="{code}" data-index-scope="{scope}" '
                    f'title="{label}: {trend or "-"}" '
                    f'style="background:{color};color:white;font-weight:bold;'
                    f'padding:4px 10px;text-align:center;border-radius:4px;'
                    f'font-size:1.0em;white-space:nowrap;cursor:pointer;">'
                    f'{label}</td>'
                )

            bench_table_html = f"""
<table style="border-collapse:separate;border-spacing:3px;margin-bottom:6px;width:auto;">
<tr>
  {bench_cell('코', k_trend,      'KOSPI',     'kr')}
  {bench_cell('닥', kd_trend,     'KOSDAQ',    'kr')}
  {bench_cell('미', sp_trend,     'SPI@SPX',   'world')}
  {bench_cell('나', us_trend,     'NAS@IXIC',  'world')}
  {bench_cell('일', nikkei_trend, 'NII@NI225', 'world')}
  {bench_cell('유', euro_trend,   'STX@SX5E',  'world')}
  {bench_cell('인', india_trend,  'INI@BSE30', 'world')}
</tr>
</table>"""

            # 색상은 sc3 (운영 대표) 기준
            if invest_pct_sc3 >= 80:
                pct_color = "#27ae60"
            elif invest_pct_sc3 >= 50:
                pct_color = "#e67e22"
            elif invest_pct_sc3 > 0:
                pct_color = "#c0392b"
            else:
                pct_color = "#7f8c8d"

            paa_suffix = f' &nbsp;<span style="color:#2c3e50;font-size:0.9em;">/ 연금 {paa_invest_pct_str}</span>' if paa_invest_pct_str else ''

            # sc3 / s1 비교 표시
            sc3_s1_html = (
                f'<b style="color:{pct_color};">총 투자비중={invest_pct_sc3:.1f}%</b>'
                f' &nbsp;/&nbsp; <span style="color:#7f8c8d;">{invest_pct_s1:.1f}%</span>'
                f' <span style="font-size:0.78em;color:#7f8c8d;">(sc3 / s1)</span>'
            )
            sc3_warn_html = '' if sc3_ok else (
                '<p style="margin:6px 0 4px 0; padding:6px 10px; background:#fdecea; color:#c0392b; '
                'border-left:3px solid #c0392b; font-size:0.9em;">⚠️ sc3 계산 실패 — 주문 파일 미갱신 '
                '(전일 값 유지). 수량(sc3) 컬럼은 직전 성공 값 기준입니다.</p>'
            )

            # 📊 SCO 분포 막대 (coin게시판 스타일) — sco≥11 / 0~11 / <0
            _sco_pos    = s_data.get('sco_pos') or 0
            _sco_neg    = s_data.get('sco_neg') or 0
            _sco_strong = s_data.get('sco_strong') or 0
            _sco_mid    = _sco_pos - _sco_strong
            _sco_den    = _sco_pos + _sco_neg
            def _scopct(n):
                return f'{n / _sco_den * 100:.1f}%' if _sco_den else '0%'
            sco_bars_html = _sco_dist_bars(
                [
                    ("sco ≥ 11", f'{_sco_strong}', _scopct(_sco_strong), "#2ecc71"),
                    ("0 ~ 11",   f'{_sco_mid}',    _scopct(_sco_mid),    "#95a5a6"),
                    ("sco < 0",  f'{_sco_neg}',    _scopct(_sco_neg),    "#e74c3c"),
                ],
                total=_sco_den,
                title="📊 SCO 기준 종목 분포",
            )

            stats_html = f"""
{bench_table_html}
{sc3_warn_html}
<div class="stats-summary-box">
    <p style="margin:0; font-size:1.05em; margin-bottom:4px;">
        📊 &nbsp;{sc3_s1_html}{paa_suffix} &nbsp;/&nbsp;
        <span class="label">top3_avg_sco=</span><b>{t_sco_str}</b> &nbsp;/&nbsp;
        <span class="label">top3_avg_pos=</span><b>{t_pos_str}</b>
    </p>
    <p style="margin:0; font-size:0.95em; margin-bottom:4px; color:#7f8c8d;">
        &nbsp;&nbsp;&nbsp; 📉 <span class="label">Top3 vol63 중앙값:</span>
        <b style="color:#e67e22;">{f"{s_data['vol63_median']:.1f}%" if s_data.get('vol63_median') is not None else "-"}</b>
    </p>
    <p style="margin:0; font-size:1.0em; margin-bottom:3px;">
        <span class="label">전체 종목 Signal_sco 평균:</span> <b>{s_data.get('avg_sco', '0.0')}</b>
        <span style="font-size:0.85em; color: #7f8c8d;"> (전체 {s_data.get('total_cnt')}개 / 유효 {s_data.get('valid_cnt')}개 / ATR제외 {s_data.get('atr_excl_cnt')}개 포함)</span>
    </p>
    {sco_bars_html}
</div>
<div class="stats-summary-mobile" style="display:none; font-size:0.9em; color:#34495e; margin:8px 0;">
  📊 &nbsp;{sc3_s1_html}{paa_suffix} &nbsp;/&nbsp;
  <span style="font-weight:bold; color:#2c3e50;">top3_avg_sco=</span><b>{t_sco_str}</b> &nbsp;/&nbsp;
  <span style="font-weight:bold; color:#2c3e50;">top3_avg_pos=</span><b>{t_pos_str}</b>
</div>
"""
        except:
            pass

    low_history = update_low_history(low_signals_dict)

    rank_html = text_to_html_table(rank_block, held_list,
        add_header=True,
        header_cols=["Ticker", "Name", "등락", "위치", "Sco", "RSI", "정", "5", "10", "20", "60", "120", "136평", "3M(%)", "Score", "Base", "Stab", "하방%", "MDD%", "Spike", "저점", "지수대비", "전환가"],
        low_signals_dict=low_signals_dict,
        idx_rel_map=idx_rel_map,
        lime_thresh_map=lime_thresh_map,
        gann_fire_set=gann_fire_set,
        low_history=low_history,
        stab_map=stab_map,
        low_amt_set=low_amt_set
    )

    final_order_html = _build_final_order_table(held_list, rank_block, s_data, idx_rel_map)

    # ── 🆕 Top3 카드 섹션 생성 ──
    top3_section_html = build_top3_section(rank_block)

    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Korea ETF Report (변동성조정)</title>
<style>
body {{
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  padding: 15px;
  margin: 0;
  background-color: #f4f7f6;
}}
.container-all {{ max-width: 1200px; margin: 0; }}
h1 {{ margin: 0 0 4px 0; padding: 0; font-size: 1.2em; color: #2c3e50; }}
h2 {{
  margin: 10px 0 4px 0;
  padding-bottom: 3px;
  color: #2c3e50;
  border-bottom: 2px solid #3498db;
  font-size: 1.0em;
}}
.styled-table {{
  width: auto;
  min-width: 400px;
  max-width: 100%;
  border-collapse: collapse;
  margin: 4px 0 12px 0;
  font-size: 12px;
  background: white;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  border-radius: 8px;
  overflow: hidden;
}}
.styled-table thead tr {{
  background: linear-gradient(135deg, #3498db, #2980b9);
  color: #ffffff;
  text-align: center;
}}
.styled-table th, .styled-table td {{
  padding: 6px 10px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
}}
.styled-table td.narrow {{ font-weight: bold; color: #2980b9; text-align: left; }}
.styled-table td.name-col {{ max-width: 150px; overflow: hidden; text-overflow: ellipsis; text-align: left; }}
.styled-table td {{ text-align: center; }}

.up, .sig-up {{ color: #27ae60; font-weight: bold; }}
.down, .sig-down {{ color: #e74c3c; font-weight: bold; }}

.pos-badge {{
  display: inline-block;
  width: 22px; height: 22px; line-height: 22px;
  border-radius: 50%; font-size: 0.75rem;
  font-weight: bold; color: white; text-align: center;
}}
.pos-1 {{ background-color: #16a34a !important; }}
.pos-2 {{ background-color: #65a30d !important; }}
.pos-3 {{ background-color: #d97706 !important; }}
.pos-4 {{ background-color: #ea580c !important; }}
.pos-5 {{ background-color: #dc2626 !important; }}

.sig-jung {{ background-color: #e8f5e9; color: #27ae60 !important; font-weight: bold; }}
.sig-yeok {{ background-color: #ffebee; color: #e74c3c !important; font-weight: bold; }}

.held-bold {{ background-color: #fff9c4 !important; color: #d32f2f !important; font-weight: bold !important; }}
.held-plain {{ background-color: #fff9c4 !important; }}

.warn-x td {{ opacity: 0.55; }}
.warn-x td.narrow, .warn-x td.name-col {{ text-decoration: line-through; color: #999 !important; }}

/* 10일 평균 거래대금 50억 미만 — 행 전체 옅은 회색 */
tr.low-amt td {{ background-color: #f2f2f2; }}

.stats-summary-box {{
    background-color: #fffde7;
    border: 1px solid #fbc02d;
    padding: 12px 18px;
    border-radius: 10px;
    margin: 15px 0;
    font-size: 14px;
    line-height: 1.6;
    color: #34495e;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    display: inline-block;
    min-width: 400px;
}}
.stats-summary-box b {{ color: #d32f2f; }}
.stats-summary-box span.label {{ font-weight: bold; color: #2c3e50; }}

.trend-badge {{
    padding: 2px 6px; border-radius: 4px;
    font-size: 10px; font-weight: bold; color: white;
    display: inline-block; min-width: 45px; text-align: center;
}}
.trend-lime {{ background-color: #2ecc71; }}
.trend-green {{ background-color: #27ae60; }}
.trend-green-light {{ background-color: #a5d6a7; color: #1b5e20; }}
.trend-red {{ background-color: #e74c3c; }}
.trend-red-light {{ background-color: #ef9a9a; color: #b71c1c; }}
.trend-purple {{ background-color: #9b59b6; }}

.low-badge {{
    display: inline-block; padding: 3px 8px;
    border-radius: 12px; font-size: 10px;
    font-weight: bold; color: white;
    text-align: center; min-width: 35px;
}}
.low-jeo   {{ background-color: #2ecc71; }}
.low-jeo2  {{ background-color: #3498db; }}
.low-both  {{ background-color: #e74c3c; }}
.low-track {{ background-color: #95a5a6; }}

.top-layout {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 20px;
    margin-bottom: 10px;
}}
.left-content {{ flex: 0 1 auto; }}
.right-sidebar {{
    display: flex; flex-direction: row;
    gap: 10px; flex-wrap: wrap;
}}
.small-board {{
    background: white; padding: 8px;
    border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    min-width: 200px;
}}
.small-board h3 {{
    margin: 0 0 5px 0; font-size: 0.9em; color: #2c3e50;
    border-bottom: 1px solid #3498db; padding-bottom: 2px;
}}

.top-nav-container {{ display: flex; margin-bottom: 10px; }}
.top-nav {{
    display: flex; background-color: #2c3e50;
    border-radius: 8px; overflow: hidden; width: fit-content;
}}
.nav-item {{
    padding: 8px 15px; color: #bdc3c7; text-align: center;
    cursor: pointer; font-weight: bold; text-decoration: none;
    transition: all 0.3s; font-size: 0.9em;
}}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}

/* ══ 🆕 Top3 카드 섹션 스타일 ══════════════════════════════ */
.t3-section {{
  margin: 0 0 12px 0;
}}
.t3-section-title {{
  font-size: 0.92em;
  font-weight: bold;
  color: #2c3e50;
  border-bottom: 2px solid #8e44ad;
  padding-bottom: 4px;
  margin-bottom: 8px;
}}
.t3-cards-row {{
  display: flex;
  gap: 8px;
  flex-wrap: nowrap;
  align-items: flex-start;
}}
.t3-card {{
  background: white;
  border-radius: 7px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.09);
  min-width: 130px;
  max-width: 180px;
  flex: 0 0 auto;
  overflow: hidden;
}}
.t3-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 9px 4px 9px;
  background: #fafafa;
  border-bottom: 1px solid #eee;
  gap: 4px;
}}
.t3-title {{
  font-size: 0.8em;
  font-weight: bold;
  color: #2c3e50;
  white-space: nowrap;
}}
.t3-label {{
  font-size: 0.72em;
  color: #888;
  white-space: nowrap;
  background: #f0f0f0;
  border-radius: 3px;
  padding: 1px 5px;
}}
.t3-body {{
  padding: 5px 9px 6px 9px;
}}
.t3-row {{
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 0;
  border-bottom: 1px solid #f5f5f5;
  font-size: 0.8em;
}}
.t3-row:last-child {{ border-bottom: none; }}
.t3-medal {{
  font-size: 0.9em;
  flex-shrink: 0;
}}
.t3-name {{
  flex: 1;
  color: #2c3e50;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.95em;
}}
.t3-ticker {{
  font-size: 0.78em;
  color: #2980b9;
  text-decoration: none;
  white-space: nowrap;
  flex-shrink: 0;
}}
.t3-ticker:hover {{ text-decoration: underline; }}
.t3-empty {{
  font-size: 0.78em;
  color: #aaa;
  padding: 6px 0;
}}

@media (max-width: 600px) {{
  .t3-cards-row {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 4px;
  }}
  .t3-card {{ min-width: 120px; max-width: 150px; }}
  .pc-only {{ display: none !important; }}
}}
/* ══ End Top3 카드 ══════════════════════════════════════════ */

@media (max-width: 800px) {{
  .top-layout {{ flex-direction: column; }}
  .right-sidebar {{ width: 100%; }}
  .final-order-table {{ min-width: unset; width: 100%; }}
  .final-order-table td {{ padding: 5px 4px; font-size: 11px; }}
  .final-order-table td.name-col {{ max-width: 80px; }}
  .stats-summary-box {{
    font-size: 11px; padding: 7px 10px;
    min-width: unset; width: 100%;
    box-sizing: border-box; line-height: 1.5;
  }}
  .stats-summary-box p:first-child {{ font-size: 1.05em; }}
  .stats-summary-box p {{ font-size: 0.95em; }}
}}
@media (max-width: 480px) {{
  .stats-summary-box {{ display: none !important; }}
  .stats-summary-mobile {{ display: block !important; }}
}}

@media screen and (max-width: 767px) and (orientation: landscape) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}

#naverChartPopup {{
  display: none; position: fixed; z-index: 99999;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; overflow-y: auto;
  max-height: 90dvh; overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}}
body.naver-popup-open {{ overflow: hidden; }}
#naverPopupClose {{
  display: flex; background: #e74c3c; color: white;
  border: none; border-radius: 50%;
  width: 28px; height: 28px;
  font-size: 18px; line-height: 1;
  cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center;
  font-weight: bold;
}}
.popup-header {{
  display: flex; align-items: center;
  gap: 8px; margin-bottom: 8px;
}}
.popup-title {{ font-weight: 700; color: #2c3e50; font-size: 14px; white-space: nowrap; }}
.popup-link {{ font-size: 12px; color: #2980b9; text-decoration: none; white-space: nowrap; margin-left: 1em; }}
.popup-link:hover {{ text-decoration: underline; }}
td[data-code], td[data-code] + td {{ cursor: pointer; }}
td[data-code] + td:hover {{ background-color: #e8f4f8 !important; }}
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.chart-card {{ border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }}
.chart-card-header {{ display: none; }}
.chart-wrap {{ position: relative; width: 100%; height: 300px; background: white; }}
.chart-wrap img {{ width: 100%; height: 100%; display: block; object-fit: fill; background: white; }}
.chart-loading {{
  display: none; position: absolute; inset: 0;
  background: rgba(255,255,255,0.75);
  align-items: center; justify-content: center;
  font-size: 12px; color: #64748b;
}}
.chart-loading.show {{ display: flex; }}
@media (max-width: 767px) {{
  #naverChartPopup {{
    position: fixed !important; left: 2vw !important;
    top: 50% !important; transform: translateY(-50%);
    width: 96vw !important; max-height: 80dvh !important;
    overflow-y: auto !important; padding: 8px !important;
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

/* 지수 팝업 (코/닥/미/나/일/유/인) */
#naverChartPopupIndex {{
  display: none; position: fixed; z-index: 99998;
  width: 860px; background: #fff;
  border: 1px solid #bdc3c7; border-radius: 10px;
  padding: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
  pointer-events: auto; overflow-y: auto; max-height: 90dvh;
  overscroll-behavior: contain; -webkit-overflow-scrolling: touch;
}}
#naverPopupCloseIndex {{
  display: flex; background: #e74c3c; color: white;
  border: none; border-radius: 50%; width: 28px; height: 28px;
  font-size: 18px; line-height: 1; cursor: pointer; flex-shrink: 0;
  align-items: center; justify-content: center; font-weight: bold;
}}
.index-trigger {{ cursor: pointer; }}
@media (max-width: 767px) {{
  #naverChartPopupIndex {{
    position: fixed !important; left: 2vw !important; top: 50% !important;
    transform: translateY(-50%); width: 96vw !important;
    max-height: 80dvh !important; overflow-y: auto !important;
    padding: 8px !important; box-sizing: border-box;
  }}
}}
@media (min-width: 768px) and (max-width: 1000px) {{
  #naverChartPopupIndex {{ width: min(96vw, 860px); left: 2vw !important; }}
}}
</style>
</head>
<body>
<div class="container-all">
    <div class="top-nav-container">
        <div class="top-nav">
            <a href="kor_etf.html" class="nav-item active">한국 ETF</a>
            <a href="top3_etf_daily_result.html" class="nav-item">Top3추세</a>
            <a href="adv_momentum.html" class="nav-item">연금 ETF</a>
        </div>
    </div>

    <div class="top-layout">
        <div class="left-content">
            <h1>🇰🇷 Korea ETF Report</h1>
            <p style="margin: 0 0 2px 0; padding: 0; font-size: 0.85em; color: #7f8c8d;">최종 업데이트: {now}</p>
            {investor_html}
        </div>
    </div>

    {stats_html}

    {top3_section_html}

    <h2 style="border-bottom: 2px solid #e67e22;">🧾 주문용 최종 보유 목록 ({s_data.get('invest_pct_sc3', s_data.get('invest_pct', 0)):.1f}% / {s_data.get('invest_pct_s1', 0):.1f}%, sc3 / s1) <span style="font-size:0.7em; color:#000; font-weight:normal;">- {int(ASSET_8042 / 10000):,}만원 기준 {int(ASSET_8042 * s_data.get('invest_pct_sc3', s_data.get('invest_pct', 0)) / 100 / 10000):,}만원 ({int(ASSET_8042 * s_data.get('invest_pct_s1', 0) / 100 / 10000):,}만원)</span></h2>
    {final_order_html}

    <h2>📊 종목 랭킹 (★: 랭킹상승) <span style="font-size:0.7em; color:#000; font-weight:normal;">- 취소선:코스피하락, 노랑/주황:전환임박, 회색바탕: 50억미만(10일평균)</span></h2>
    {rank_html}

    <div class="right-sidebar" style="margin-top: 20px;">
        <div class="small-board">
            <h3>⚠️ ATR 트리거 (2주)</h3>
            {text_to_html_table(atr_trigger, add_header=True, header_cols=["Ticker", "산업", "ATR"])}
        </div>
        <div class="small-board">
            <h3>🛡 ATR 제외</h3>
            {text_to_html_table(atr_exclude, add_header=True, header_cols=["Ticker", "산업", "ATR"])}
        </div>
    </div>
</div>
<div id="naverChartPopup">
  <div class="popup-header">
    <button id="naverPopupClose" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitle">-</div>
    <a id="popupLink" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-card-header">
        <div class="chart-card-title">일봉</div>
        <div class="chart-status" id="statusDaily">대기중</div>
      </div>
      <div class="chart-wrap">
        <img id="imgDaily" alt="일봉 차트">
        <div class="chart-loading" id="loadingDaily">불러오는 중...</div>
      </div>
    </div>
    <div class="chart-card">
      <div class="chart-card-header">
        <div class="chart-card-title">주봉</div>
        <div class="chart-status" id="statusWeekly">대기중</div>
      </div>
      <div class="chart-wrap">
        <img id="imgWeekly" alt="주봉 차트">
        <div class="chart-loading" id="loadingWeekly">불러오는 중...</div>
      </div>
    </div>
  </div>
</div>

<script>
(function () {{ return;
  var popup   = document.getElementById('naverChartPopup');
  var popupTitle  = document.getElementById('popupTitle');
  var popupLink   = document.getElementById('popupLink');
  var imgDaily    = document.getElementById('imgDaily');
  var imgWeekly   = document.getElementById('imgWeekly');
  var loadingDaily    = document.getElementById('loadingDaily');
  var loadingWeekly   = document.getElementById('loadingWeekly');
  var statusDaily     = document.getElementById('statusDaily');
  var statusWeekly    = document.getElementById('statusWeekly');
  var hoverTimer = null;
  var pinned = false;

  var TS = Date.now();
  function withTs(url) {{ return url + '?t=' + TS; }}
  function dailyCandleUrl(code)  {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/day/'  + code + '.png'); }}
  function weeklyCandleUrl(code) {{ return withTs('https://ssl.pstatic.net/imgfinance/chart/item/candle/week/' + code + '.png'); }}
  function itemPageUrl(code)     {{ return 'https://finance.naver.com/item/main.naver?code=' + code; }}

  function setStatus(el, text, color) {{ el.textContent = text; el.style.color = color || '#94a3b8'; }}

  function loadInto(imgEl, loadingEl, statusEl, url, label) {{
    loadingEl.classList.add('show');
    imgEl.style.opacity = '0.35';
    setStatus(statusEl, '로딩중...', '#f59e0b');
    var probe = new Image();
    probe.onload = function () {{
      imgEl.src = url; imgEl.style.opacity = '1';
      loadingEl.classList.remove('show');
      setStatus(statusEl, '로드 성공', '#22c55e');
    }};
    probe.onerror = function () {{
      imgEl.removeAttribute('src'); imgEl.style.opacity = '1';
      loadingEl.classList.remove('show');
      setStatus(statusEl, label + ' 실패', '#ef4444');
    }};
    probe.src = url;
  }}

  function loadCharts(code, name) {{
    popupTitle.textContent = code + '  ' + (name || '');
    popupLink.href = itemPageUrl(code);
    loadInto(imgDaily,   loadingDaily,   statusDaily,   dailyCandleUrl(code),  '일봉');
    loadInto(imgWeekly,  loadingWeekly,  statusWeekly,  weeklyCandleUrl(code), '주봉');
  }}

  function placePopup(cx, cy) {{
    var isMobile = window.innerWidth <= 767;
    if (isMobile) return;
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
    popup.style.transform = 'none';
  }}

  function openPopup() {{
    popup.style.display = 'block';
    document.body.classList.add('naver-popup-open');
  }}

  function closePopup() {{
    popup.style.display = 'none';
    pinned = false;
    document.body.classList.remove('naver-popup-open');
  }}

  document.getElementById('naverPopupClose').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

  document.querySelectorAll('td[data-naver-off]').forEach(function (td) {{  /* 종목명 hover는 V4 팝업이 담당 → naver PNG 팝업 비활성 */
    var hot = (td.nextElementSibling && td.nextElementSibling.tagName === 'TD') ? td.nextElementSibling : td;
    hot.addEventListener('mouseenter', function (e) {{
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        loadCharts(td.dataset.code, td.dataset.name || '');
      }}, 140);
    }});
    hot.addEventListener('mousemove', function (e) {{
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    hot.addEventListener('mouseleave', function () {{
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    hot.addEventListener('click', function (e) {{
      if (window.innerWidth > 767) return;
      e.stopPropagation();
      openPopup();
      loadCharts(td.dataset.code, td.dataset.name || '');
    }});
  }});
  (function () {{
    var seen = {{}}, queue = [];
    document.querySelectorAll('td[data-naver-off]').forEach(function (td) {{  /* naver PNG 프리로드 비활성 */
      var c = td.dataset.code;
      if (!c || seen[c]) return;
      seen[c] = true; queue.push(c);
    }});
    var idx = 0, CONCURRENCY = 3;
    function next() {{
      if (idx >= queue.length) return;
      var c = queue[idx++], done = 0;
      function step() {{ if (++done >= 2) next(); }}
      [dailyCandleUrl(c), weeklyCandleUrl(c)].forEach(function (u) {{
        var im = new Image(); im.onload = step; im.onerror = step; im.src = u;
      }});
    }}
    setTimeout(function () {{ for (var i = 0; i < CONCURRENCY && i < queue.length; i++) next(); }}, 300);
  }})();
  document.addEventListener('click', function(e) {{
    if (window.innerWidth <= 767 && popup.style.display === 'block') {{
      if (!popup.contains(e.target)) closePopup();
    }}
  }});
  // === D/S 단축키 (D/↓=다음, S/↑=이전, Tab/ESC=닫기) · PNG라 A(슈퍼트렌드)는 제외 ===
  (function(){{
    var SEL = 'td[data-code]';
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

<!-- 지수 팝업 (코/닥/미/나/일/유/인) -->
<div id="naverChartPopupIndex">
  <div class="popup-header">
    <button id="naverPopupCloseIndex" title="닫기">&#215;</button>
    <div class="popup-title" id="popupTitleIndex">-</div>
    <a id="popupLinkIndex" class="popup-link" href="#" target="_blank" rel="noopener noreferrer">네이버 열기</a>
  </div>
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-wrap">
        <img id="imgDailyIndex" alt="일봉 차트">
        <div class="chart-loading" id="loadingDailyIndex">불러오는 중...</div>
      </div>
    </div>
    <div class="chart-card">
      <div class="chart-wrap">
        <img id="imgWeeklyIndex" alt="주봉 차트">
        <div class="chart-loading" id="loadingWeeklyIndex">불러오는 중...</div>
      </div>
    </div>
  </div>
</div>
<script>
(function () {{
  var popup       = document.getElementById('naverChartPopupIndex');
  var popupTitle  = document.getElementById('popupTitleIndex');
  var popupLink   = document.getElementById('popupLinkIndex');
  var imgDaily    = document.getElementById('imgDailyIndex');
  var imgWeekly   = document.getElementById('imgWeeklyIndex');
  var loadingDaily   = document.getElementById('loadingDailyIndex');
  var loadingWeekly  = document.getElementById('loadingWeeklyIndex');
  var hoverTimer = null;
  var pinned = false;

  function withTs(u) {{ return u + '?t=' + Date.now(); }}
  function chartUrl(code, scope, period) {{
    if (scope === 'kr') {{
      return withTs('https://ssl.pstatic.net/imgfinance/chart/mobile/candle/' + period + '/' + code + '_end.png');
    }}
    return withTs('https://ssl.pstatic.net/imgfinance/chart/world/candle/' + period + '/' + code + '.png');
  }}
  function pageUrl(code, scope) {{
    if (scope === 'kr') {{
      return 'https://finance.naver.com/sise/sise_index.naver?code=' + code;
    }}
    return 'https://finance.naver.com/world/sise.naver?symbol=' + code;
  }}

  function loadInto(imgEl, loadingEl, url) {{
    loadingEl.classList.add('show');
    imgEl.style.opacity = '0.35';
    var p = new Image();
    p.onload  = function () {{ imgEl.src = url; imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.onerror = function () {{ imgEl.removeAttribute('src'); imgEl.style.opacity = '1'; loadingEl.classList.remove('show'); }};
    p.src = url;
  }}

  function loadCharts(code, scope) {{
    popupTitle.textContent = code;
    popupLink.href = pageUrl(code, scope);
    loadInto(imgDaily,  loadingDaily,  chartUrl(code, scope, 'day'));
    loadInto(imgWeekly, loadingWeekly, chartUrl(code, scope, 'week'));
  }}

  function placePopup(cx, cy) {{
    if (window.innerWidth <= 767) return;
    popup.style.transform = 'none';
    var rectW = Math.min(860, window.innerWidth - 20);
    var rectH = window.innerWidth <= 1000 ? 650 : 430;
    var x = cx + 18, y = cy + 18;
    if (x + rectW > window.innerWidth  - 8) x = cx - rectW - 12;
    if (y + rectH > window.innerHeight - 8) y = cy - rectH - 12;
    if (x < 8) x = 8; if (y < 8) y = 8;
    popup.style.left = x + 'px'; popup.style.top = y + 'px';
  }}

  function openPopup()  {{ popup.style.display = 'block'; document.body.classList.add('naver-popup-open'); }}
  function closePopup() {{ popup.style.display = 'none';  pinned = false; document.body.classList.remove('naver-popup-open'); }}

  document.getElementById('naverPopupCloseIndex').addEventListener('click', closePopup);
  popup.addEventListener('mouseenter', function () {{ pinned = true; }});
  popup.addEventListener('mouseleave', function () {{ pinned = false; closePopup(); }});

  document.querySelectorAll('.index-trigger[data-index-code]').forEach(function (el) {{
    var code  = el.getAttribute('data-index-code');
    var scope = el.getAttribute('data-index-scope') || 'world';
    el.addEventListener('mouseenter', function (e) {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () {{
        placePopup(e.clientX, e.clientY);
        openPopup();
        loadCharts(code, scope);
      }}, 140);
    }});
    el.addEventListener('mousemove', function (e) {{
      if (window.innerWidth <= 767) return;
      if (popup.style.display === 'block' && !pinned) placePopup(e.clientX, e.clientY);
    }});
    el.addEventListener('mouseleave', function () {{
      if (window.innerWidth <= 767) return;
      clearTimeout(hoverTimer);
      setTimeout(function () {{ if (!pinned) closePopup(); }}, 120);
    }});
    el.addEventListener('click', function (e) {{
      e.stopPropagation();
      clearTimeout(hoverTimer);
      placePopup(e.clientX, e.clientY);
      openPopup();
      loadCharts(code, scope);
    }});
  }});

  document.addEventListener('click', function (e) {{
    if (window.innerWidth <= 767) {{
      if (!e.target.closest('#naverChartPopupIndex')) closePopup();
    }} else {{
      if (!e.target.closest('#naverChartPopupIndex') && !e.target.closest('.index-trigger')) closePopup();
    }}
  }});
}})();
</script>

<script>
document.addEventListener('DOMContentLoaded', function() {{
    var titles = Array.from(document.querySelectorAll('h2, h3'));
    var targetTitle = titles.find(t => t.innerText.includes('종목 랭킹') || t.innerText.includes('ETF 랭킹'));
    if (!targetTitle) return;
    var table = targetTitle.nextElementSibling;
    while (table && table.tagName !== 'TABLE' && !table.querySelector('table')) {{
        table = table.nextElementSibling;
    }}
    if (table && table.tagName !== 'TABLE') table = table.querySelector('table');
    if (!table) return;

    var tbody = table.querySelector('tbody');
    if (!tbody) return;
    
    var originalRows = Array.from(tbody.querySelectorAll('tr')).map(function(r) {{ return r.cloneNode(true); }});
    var sortState = {{ col: null, asc: true }};

    function getCellValue(row, col) {{
        var cells = row.querySelectorAll('td');
        if (!cells[col]) return '';
        return cells[col].innerText.trim();
    }}

    function toNum(str) {{
        var n = parseFloat(str.replace(/[^0-9.\x2D]/g, ''));
        if (isNaN(n) || str.trim() === '-' || str.trim() === '') return null;
        return n;
    }}

    table.querySelectorAll('th').forEach(function(th, index) {{
        th.style.cursor = 'pointer';
        th.addEventListener('click', function() {{
            if (sortState.col === index) {{
                if (!sortState.asc) {{
                    sortState = {{ col: null, asc: true }};
                    tbody.innerHTML = '';
                    originalRows.forEach(function(r) {{ tbody.appendChild(r.cloneNode(true)); }});
                    return;
                }}
                sortState.asc = false;
            }} else {{
                sortState.col = index;
                sortState.asc = true;
            }}
            var rows = Array.from(tbody.querySelectorAll('tr'));
            rows.sort(function(a, b) {{
                var va = getCellValue(a, index);
                var vb = getCellValue(b, index);
                var na = toNum(va), nb = toNum(vb);
                if (na !== null && nb !== null) {{
                    return sortState.asc ? na - nb : nb - na;
                }}
                var cmp = va.localeCompare(vb, 'ko');
                return sortState.asc ? cmp : -cmp;
            }});
            tbody.innerHTML = '';
            rows.forEach(function(r) {{ tbody.appendChild(r); }});
        }});
    }});
}});
</script>
</body>
</html>
"""

    import re as _re
    from chart_popup_v4 import build_chart_popup as _bcp_v4, move_kr_trigger_to_name as _mv2name
    page = _mv2name(page)  # 한국종목: 티커 대신 종목명에 hover → 차트
    _codes = sorted(set(_re.findall(r'data-code="([^"]+)"', page)))
    page = page.replace(
        "</body>",
        _bcp_v4(_codes, market="KR", trigger_attr="data-code", include_kospi=False) + "\n</body>",
        1,
    )
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] kor_etf.html updated at {OUT_HTML} (V4 차트 {len(_codes)}종목)")


if __name__ == "__main__":
    main()
