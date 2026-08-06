import requests
from pathlib import Path
from datetime import datetime
import shutil
import csv
import json
import re
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # For Python < 3.7
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ====== 설정 ======
BOT_TOKEN = "8530193490:AAEfFfROoVCQ9e3dS2dfKzOAwN_Na-qkaiQ"
CHAT_ID = 1909192815

BASE_US = Path(__file__).resolve().parent  # D:\py\report-us
BASE_KR = Path("D:/py")                    # D:\py

# 1. 미국 주식
TODAY_US_STOCK = BASE_US / "buy_us_stock.txt"
PREV_US_STOCK  = BASE_US / "prev_buy_us.txt"

# 2. 통합 주문목록 — jasantop4_global_softcap.py 출력
TOTAL_STATS_JSON  = BASE_US / "kr_signal_stats_total.json"
TOTAL_TOP30_CSV   = BASE_KR / "0txt" / "total_top30.csv"
TOTAL_REBAL_TXT   = BASE_KR / "0order" / "00_totaletf_korea_rebalancing.txt"  # ticker,수량

# 3. 추세 — top3_etf_track_total.json
ETF_TRACK_TOTAL   = BASE_US / "top3_etf_track_total.json"

# 4. 세계지수 sco — world_sco_track.json
WORLD_SCO_TRACK   = BASE_US / "world_sco_track.json"
WORLD_RANK_JSON   = BASE_US / "world_rank.json"   # QQQ/IWM(RTY) 등 티커별 sco
AI_SCORE_JSON     = BASE_US / "ai_basket_scores_total_AI.json"

# 5. 해선 모멘텀 — report_futures.txt
FUTURES_REPORT    = BASE_US / "report_futures.txt"

# 6. 미우량주 주문목록 — report_us_finviz.txt
FINVIZ_REPORT     = BASE_US / "report_us_finviz.txt"
US_VCP_FINAL_TXT  = BASE_KR / "us_vcp2_final.txt"
KR_CONVERGE_V2_JSON = BASE_US / "kr_converge_data_v2.json"

# 7. KR 관련 추가
LEADER_TXT_00     = Path("D:/py/0txt/00_1887_leader.txt")
REPORT_KR_150     = BASE_US / "report_kr_150.txt"
JSON_KR_150       = BASE_US / "report_kr_150.json"
LEADER_TRACK_150  = BASE_US / "leader_tracking_150.json"

TICKER_FILES = [
    BASE_KR / "korea" / "kr150.csv",
    BASE_KR / "korea" / "kr.csv",
    BASE_KR / "korea" / "koreaetf.csv",
    BASE_KR / "korea" / "data.csv"
]
# ==================

def load_ticker_names():
    """여러 CSV 파일에서 티커-종목명 매핑 로드"""
    mapping = {}
    for csv_path in TICKER_FILES:
        if not csv_path.exists():
            continue
        try:
            for encoding in ['utf-8-sig', 'cp949', 'utf-8']:
                try:
                    with open(csv_path, mode='r', encoding=encoding) as f:
                        reader = csv.reader(f)
                        header = next(reader, None)
                        if not header: continue
                        try:
                            t_idx = next(i for i, h in enumerate(header) if '코드' in h or 'ticker' in h.lower())
                            n_idx = next(i for i, h in enumerate(header) if '명' in h or 'Name' in h)
                        except StopIteration:
                            t_idx, n_idx = 0, 1
                        for row in reader:
                            if len(row) > max(t_idx, n_idx):
                                ticker = row[t_idx].strip().zfill(6)
                                name = row[n_idx].strip()
                                mapping[ticker] = name
                    break
                except (UnicodeDecodeError, StopIteration):
                    continue
        except Exception as e:
            print(f"Error loading {csv_path.name}: {e}")
    return mapping

def extract_tickers_from_report(text, section_header):
    """report_kr_150.txt에서 특정 섹션의 티커들을 추출"""
    lines = text.splitlines()
    start_idx = -1
    for i, line in enumerate(lines):
        if section_header in line:
            start_idx = i
            break
    if start_idx == -1: return []
    tickers = []
    for i in range(start_idx + 2, len(lines)):
        line = lines[i].strip()
        if not line or "【" in line or "===" in line or "📊" in line: break
        if "없음" in line: break
        match = re.search(r'(\d{6}(?:\*\*)?)', line)
        if match: tickers.append(match.group(1))
        elif len(line) >= 6 and line[:6].isdigit(): tickers.append(line)
    return tickers

def format_with_name(ticker_list, name_map):
    formatted = []
    for t in ticker_list:
        clean_t = t.replace('*', '')
        name = name_map.get(clean_t, "미등록")
        formatted.append(f"{t}({name})")
    return formatted

def read_list(path, limit=None):
    """파일을 읽어 리스트로 반환"""
    if not path.exists():
        return []
    try:
        lines = [line.strip() for line in path.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()]
        clean = [t.split()[0] for t in lines if not t.startswith('#')]
        return clean[:limit] if limit else clean
    except Exception:
        return []


def _load_total_qty():
    """00_totaletf_korea_rebalancing.txt 에서 {ticker: 수량str} 로드."""
    qty = {}
    if TOTAL_REBAL_TXT.exists():
        try:
            for ln in TOTAL_REBAL_TXT.read_text(encoding='utf-8', errors='ignore').splitlines():
                ln = ln.strip()
                if not ln or ',' not in ln:
                    continue
                tk, q = ln.split(',', 1)
                qty[tk.strip()] = q.strip()
        except Exception:
            pass
    return qty


def read_total_order_block():
    """
    📈 통합Top6 라인 리스트 반환 (웹 통합ETF 기준).
    - holdings_tickers + final_ratios : kr_signal_stats_total.json
    - 단축명(산업) + 당일등락률(%) + Signal_sco : total_top30.csv
    - 수량 : 00_totaletf_korea_rebalancing.txt
    KR(6자리): 티커(종목명), 등락률, 수량
    US(알파):  티커, 등락률, sco, 비중%, 수량
    """
    if not TOTAL_STATS_JSON.exists():
        return []
    try:
        stats = json.loads(TOTAL_STATS_JSON.read_text(encoding='utf-8'))
    except Exception:
        return []

    holdings     = stats.get("holdings_tickers", [])
    final_ratios = stats.get("final_ratios", {})
    if not holdings:
        return []

    # CSV에서 단축명·등락률·sco 로드
    csv_map = {}
    if TOTAL_TOP30_CSV.exists():
        try:
            with open(TOTAL_TOP30_CSV, encoding='utf-8-sig', errors='ignore', newline='') as f:
                for row in csv.DictReader(f):
                    raw = row.get('티커', '').strip()
                    if not raw:
                        continue
                    intensity = '**' in raw
                    ticker = raw.replace('**', '')
                    try:    chg = float(row.get('당일등락률(%)', '') or 0)
                    except: chg = None
                    try:    sco = float(row.get('Signal_sco', '') or 0)
                    except: sco = None
                    name = re.sub(r'\(.*?\)\s*$', '', (row.get('산업', '') or '').strip())
                    csv_map[ticker] = {'chg': chg, 'sco': sco, 'intensity': intensity, 'name': name}
        except Exception:
            pass

    qty_map   = _load_total_qty()
    total_pct = sum(v for v in (final_ratios.get(tk) for tk in holdings) if v is not None)

    order_lines = [f"📈 통합Top6 ({total_pct:.1f}%)"]
    for tk in holdings:
        info      = csv_map.get(tk, {})
        intensity = info.get('intensity', False)
        chg       = info.get('chg')
        sco       = info.get('sco')
        name      = info.get('name', '')
        ticker_d  = tk + ("**" if intensity else "")
        chg_str   = f"{chg:+.1f}%" if chg is not None else "-"
        qty_str   = qty_map.get(tk, "x")
        if tk.isdigit():
            nm = f"({name})" if name else ""
            order_lines.append(f"{ticker_d}{nm}, {chg_str}, {qty_str}")
        else:
            sco_str = f"sco:{sco:.0f}" if sco is not None else "sco:-"
            pct     = final_ratios.get(tk)
            pct_str = f"{pct:.1f}%" if pct is not None else "-"
            order_lines.append(f"{ticker_d}, {chg_str}, {sco_str}, {pct_str}, {qty_str}")

    return order_lines


def read_money_flow_block():
    """
    📈 비중 블록 반환 (상황판 Money Flow 도넛 = 오늘 US/KR 비중).
    make_index_main_hub.compute_leadership() 의 scores_today / total_today 재사용.
    형식:
      📈 비중 (US/KR)
      73% / 27%
    """
    try:
        sys.path.insert(0, str(BASE_US))
        from make_index_main_hub import compute_leadership
    except Exception:
        return []
    try:
        data = compute_leadership()
    except Exception:
        return []
    if not data:
        return []
    scores = data.get("scores_today", {})
    total  = data.get("total_today", 0)
    if not total:
        return []
    us_pct = round(scores.get("US", 0) / total * 100)
    kr_pct = round(scores.get("KR", 0) / total * 100)
    return [
        "📈 비중 (US/KR)",
        f"{us_pct}% / {kr_pct}%",
    ]


def read_trend_block():
    """
    📈추세 블록 반환.
    top3_etf_track_total.json 의 마지막 항목에서 kospi_trend / nasdaq_trend 읽기.
    """
    if not ETF_TRACK_TOTAL.exists():
        return []
    try:
        d = json.loads(ETF_TRACK_TOTAL.read_text(encoding='utf-8'))
        # dict(날짜→데이터) 또는 list 모두 대응
        if isinstance(d, dict):
            last = d[list(d.keys())[-1]]
        elif isinstance(d, list):
            last = d[-1]
        else:
            return []
        kospi  = last.get("kospi_trend", "-")
        nasdaq = last.get("nasdaq_trend", "-")
        spy = "-"
        if WORLD_RANK_JSON.exists():
            try:
                wr = json.loads(WORLD_RANK_JSON.read_text(encoding='utf-8'))
                for row in (wr.get("data") or []):
                    if row.get("Ticker") == "SPY":
                        spy = row.get("추세", "-")
                        break
            except Exception:
                pass
        return [
            "📈추세",
            f"코스피: {kospi}",
            f"에센피: {spy}",
            f"나스닥: {nasdaq}",
        ]
    except Exception:
        return []


def read_world_sco_block():
    """
    📈 세계지수 sco 블록 반환.
    world_sco_track.json 의 마지막 항목에서 spy_sco / avg_sco / avg_final_sco 읽기.
    소수점 1자리.
    """
    if not WORLD_SCO_TRACK.exists():
        return []
    try:
        d = json.loads(WORLD_SCO_TRACK.read_text(encoding='utf-8'))
        if isinstance(d, dict):
            last = d[list(d.keys())[-1]]
        elif isinstance(d, list):
            last = d[-1]
        else:
            return []
        spy_sco   = last.get("spy_sco")
        ewy_sco   = last.get("ewy_sco")
        avg_sco   = last.get("avg_sco")
        final_sco = last.get("avg_final_sco")

        # QQQ / RTY(IWM) sco 는 world_rank.json 의 티커별 sco 에서 읽음
        rank_sco = {}
        if WORLD_RANK_JSON.exists():
            try:
                wr = json.loads(WORLD_RANK_JSON.read_text(encoding='utf-8'))
                for row in (wr.get("data") or []):
                    t = row.get("Ticker")
                    if t:
                        rank_sco[t] = row.get("sco")
            except Exception:
                pass
        qqq_sco = rank_sco.get("QQQ")
        rty_sco = rank_sco.get("IWM")   # RTY = Russell 2000 → IWM ETF
        ai_sco = None
        if AI_SCORE_JSON.exists():
            try:
                ai = json.loads(AI_SCORE_JSON.read_text(encoding='utf-8'))
                ai_sco = ai.get("ai_core_score")
            except Exception:
                pass

        def fmt(v):
            try:    return f"{float(v):.1f}"
            except: return "-"
        def fmt_ai(v):
            try:    return f"{float(v):.2f}"
            except: return "-"

        return [
            "📈 세계지수 sco",
            f"SPY : {fmt(spy_sco)}",
            f"QQQ : {fmt(qqq_sco)}",
            f"RTY : {fmt(rty_sco)}",
            f"AI  : {fmt_ai(ai_sco)}",
            f"EWY : {fmt(ewy_sco)}",
            f"전체 sco: {fmt(avg_sco)}",
            f"Final sco: {fmt(final_sco)}",
        ]
    except Exception:
        return []


def read_futures_block():
    """
    📊 해선모멘텀 블록 반환.
    report_futures.txt 의 '=== 주문용 Top4 (오늘) ===' 섹션을 파싱.
    출력 형식: "ZL**, 13.0, 94.5"
    """
    if not FUTURES_REPORT.exists():
        return []
    try:
        text = FUTURES_REPORT.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []

    # '=== 주문용 Top4 (오늘) ===' 섹션 추출
    lines = text.splitlines()
    in_section = False
    rows = []
    for line in lines:
        if '=== 주문용 Top4 (오늘) ===' in line:
            in_section = True
            continue
        if in_section:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('===') or stripped.startswith('이전'):
                break
            # 헤더 행 건너뜀 (Ticker로 시작)
            if stripped.startswith('Ticker'):
                continue
            # 데이터 파싱: Ticker  Sco  3M(%)  Score  신호
            parts = stripped.split()
            if len(parts) >= 4:
                ticker = parts[0]         # ZL** or CL
                sco    = parts[1]         # 13.0
                score  = parts[3]         # 94.50
                try:    sco_f   = float(sco)
                except: sco_f   = None
                try:    score_f = float(score)
                except: score_f = None
                sco_str   = f"{sco_f:.1f}" if sco_f is not None else sco
                score_str = f"{score_f:.2f}" if score_f is not None else score
                rows.append(f"{ticker}, {sco_str}, {score_str}")

    if not rows:
        return []
    return ["📊 해선모멘텀"] + rows


def read_us_stock_block():
    """
    📊미우량주 주문목록 블록 반환.
    report_us_finviz.txt 의 '=== 주문용 Top4 (오늘) ===' 섹션 파싱.
    컬럼: Ticker, Industry, Signal_sco, NewSig  (3M%, Final_sco 제외)
    Industry 및 NewSig 의 이모지 제거.
    """
    import re
    # 유니코드 이모지 전체 제거 패턴
    EMOJI_RE = re.compile(
        "["
        u"\U0001F300-\U0001FFFF"
        u"\U00002700-\U000027BF"
        u"\U000024C2-\U00002BFF"
        u"\u26A0-\u26FF"
        u"\u2600-\u26FF"
        "]+", flags=re.UNICODE
    )
    def strip_emoji(s):
        return EMOJI_RE.sub('', s).strip()

    if not FINVIZ_REPORT.exists():
        return []
    try:
        text = FINVIZ_REPORT.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []

    lines = text.splitlines()
    in_section = False
    rows = []
    for line in lines:
        if '=== 주문용 Top4 (오늘) ===' in line:
            in_section = True
            continue
        if in_section:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('===') or stripped.startswith('이전'):
                break
            if stripped.startswith('Ticker'):
                continue
            # 데이터 파싱: Ticker Industry Signal_sco 수익률(%) Final_score NewSig
            parts = stripped.split()
            if len(parts) >= 6:
                ticker   = parts[0]
                industry = strip_emoji(parts[1])  # ⚡ENER → ENER
                sco      = parts[2]
                newsig   = strip_emoji(parts[5])  # 🆕GRN → GRN,  - → -
                try:    sco_f = float(sco)
                except: sco_f = None
                sco_str = f"{sco_f:.1f}" if sco_f is not None else sco
                sig_str = newsig if newsig else '-'
                rows.append(f"{ticker}, {industry}, {sco_str}, {sig_str}")

    if not rows:
        return []
    return ["📊미우량주 주문목록"] + rows


def _read_vcp_tickers(path, limit=12):
    if not path.exists():
        return []
    try:
        rows = []
        for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ticker = line.split(",")[0].split()[0].strip()
            if ticker and ticker.lower() != "ticker":
                rows.append(ticker)
        return rows[:limit]
    except Exception:
        return []


def read_vcp_breakout_block():
    """
    ㅁ VCP돌파 블록 반환.
    미국은 티커, 한국은 kor_abc.html 오른쪽 V2 FIRE 종목명으로 표시.
    """
    us_tickers = _read_vcp_tickers(US_VCP_FINAL_TXT)
    kr_names = []
    if KR_CONVERGE_V2_JSON.exists():
        try:
            data = json.loads(KR_CONVERGE_V2_JSON.read_text(encoding='utf-8'))
            for row in (data.get("fire") or []):
                name = (row.get("name") or "").strip()
                ticker = (row.get("ticker") or "").strip()
                kr_names.append(name or ticker)
        except Exception:
            pass

    us_text = ", ".join(us_tickers) if us_tickers else "(없음)"
    kr_text = ", ".join(kr_names) if kr_names else "(없음)"
    return [
        "ㅁ VCP돌파",
        f"미VCP: {us_text}",
        f"한VCP: {kr_text}",
    ]


def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"Telegram send failed: {e}")


def safe_copy(src: Path, dst: Path):
    if src.exists():
        shutil.copyfile(src, dst)


import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--usetf_only', action='store_true')
    args = parser.parse_args()

    lines = [f"------------ {datetime.now().strftime('%y%m%d')}"]

    # 1) 통합Top6 주문목록 (맨 위)
    lines.extend(read_total_order_block())

    # 2) 비중 (US/KR Money Flow)
    money_flow = read_money_flow_block()
    if money_flow:
        lines.append("")          # 빈 줄 구분
        lines.extend(money_flow)

    # 3) 추세
    trend = read_trend_block()
    if trend:
        lines.append("")          # 빈 줄 구분
        lines.extend(trend)

    # 3) 세계지수 sco
    world = read_world_sco_block()
    if world:
        lines.append("")
        lines.extend(world)

    # 4) 해선 모멘텀
    futures = read_futures_block()
    if futures:
        lines.append("")
        lines.extend(futures)

    # 5) 미우량주 주문목록
    us_stock_blk = read_us_stock_block()
    if us_stock_blk:
        lines.append("")
        lines.extend(us_stock_blk)

    # 6) VCP 돌파종목 (미우량주 주문목록 뒤)
    vcp_blk = read_vcp_breakout_block()
    if vcp_blk:
        lines.append("")
        lines.extend(vcp_blk)

    # 7) KR150 주도주(오늘) (마지막)
    if JSON_KR_150.exists():
        try:
            lines.append("\n[KR150 Signal]")
            lines.append("- 주도주(오늘)")
            d_150 = json.loads(JSON_KR_150.read_text(encoding='utf-8'))
            leader_150 = d_150.get('leader', [])
            lines.extend([f"{s['ticker']}({s.get('name','미등록')})" for s in leader_150] if leader_150 else ["(없음)"])
        except Exception as e:
            print(f"Error adding KR150 signal: {e}")

    if lines:
        full_msg = "\n".join(lines)
        send(full_msg)
        print("Telegram notification sent.")
        print(full_msg)


if __name__ == "__main__":
    main()
