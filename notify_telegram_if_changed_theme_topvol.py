import json
from pathlib import Path
import csv
import sys
import requests

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ====== 설정 ======
BOT_TOKEN = "8530193490:AAEfFfROoVCQ9e3dS2dfKzOAwN_Na-qkaiQ"
CHAT_ID = 1909192815

BASE_KR = Path("D:/py")
# 종목명 매핑 파일들
TICKER_FILES = [
    BASE_KR / "korea" / "kr150.csv",
    BASE_KR / "korea" / "kr.csv",
    BASE_KR / "korea" / "koreaetf.csv"
]

NAVER_DEBUG_CSV = Path("D:/py/0txt/00_1887_naver_thema_debug.csv")
TOP_VOLUME_TXT = Path("D:/py/topvolume30.txt")
LEADER_TXT = Path("D:/py/0txt/00_1887_leader.txt")


def load_naver_top_themes(top_n=3):
    """네이버 크롤링 디버그 CSV → 통과종목 기준 테마 집계 (거래대금 합 내림차순 Top N)."""
    if not NAVER_DEBUG_CSV.exists():
        return []
    groups = {}
    try:
        with open(NAVER_DEBUG_CSV, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                if str(row.get('passed', '')).strip().lower() not in ('1', 'true', 't', 'yes', 'y'):
                    continue
                theme = (row.get('theme') or '네이버테마').strip()
                try:
                    chg = float(str(row.get('chg_pct', '0')).replace('%', '').replace('+', '').strip() or 0)
                except ValueError:
                    chg = 0.0
                try:
                    trade = float(str(row.get('trade_eok', '0')).replace(',', '').strip() or 0)
                except ValueError:
                    trade = 0.0
                g = groups.setdefault(theme, {'chg_sum': 0.0, 'cnt': 0, 'trade': 0.0})
                g['chg_sum'] += chg
                g['cnt']     += 1
                g['trade']   += trade
    except Exception:
        return []
    ranked = sorted(groups.items(), key=lambda kv: kv[1]['trade'], reverse=True)
    out = []
    for rank, (theme, g) in enumerate(ranked[:top_n], start=1):
        avg = g['chg_sum'] / g['cnt'] if g['cnt'] else 0.0
        out.append({'rank': rank, 'thema_nm': theme, 'flu_rt': f"{avg:.2f}"})
    return out

def load_ticker_names():
    mapping = {}
    for csv_path in TICKER_FILES:
        if not csv_path.exists(): continue
        try:
            for encoding in ['utf-8-sig', 'cp949', 'utf-8']:
                try:
                    with open(csv_path, mode='r', encoding=encoding) as f:
                        reader = csv.reader(f)
                        header = next(reader, None)
                        if not header: continue
                        t_idx, n_idx = 0, 1
                        try:
                            t_idx = next(i for i, h in enumerate(header) if '코드' in h or 'ticker' in h.lower())
                            n_idx = next(i for i, h in enumerate(header) if '명' in h or 'Name' in h)
                        except StopIteration: pass
                        for row in reader:
                            if len(row) > max(t_idx, n_idx):
                                ticker = row[t_idx].strip().zfill(6)
                                name = row[n_idx].strip()
                                mapping[ticker] = name
                    break
                except (UnicodeDecodeError, StopIteration): continue
        except Exception: pass
    return mapping

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"Telegram send failed: {e}")

def main():
    name_map = load_ticker_names()
    lines = []
    
    # 1. 당일테마 (네이버 크롤링)
    lines.append("🎯 [당일테마 (Top 3)]")
    naver_themes = load_naver_top_themes(3)
    if naver_themes:
        for t in naver_themes:
            lines.append(f"{t['rank']}위. {t['thema_nm']} ({t['flu_rt']}%)")
    else:
        lines.append("데이터 없음")
        
    # 2. 당일거래대금 (상위 10개)
    lines.append("\n📊 [당일거래대금 상위 10종목]")
    VOLUME_JSON = Path("D:/py/report-us/report_volume.json")
    if VOLUME_JSON.exists():
        try:
            with open(VOLUME_JSON, 'r', encoding='utf-8') as f:
                v_data = json.load(f)
            v_stocks = v_data.get('stocks', [])[:10]
            if v_stocks:
                for s in v_stocks:
                    ticker = str(s['ticker']).zfill(6)
                    name = s.get('name', name_map.get(ticker, "미등록"))
                    amt_eok = int(s.get('trade_amount', 0) / 100)
                    lines.append(f"{ticker} ({name}) {amt_eok:,}억")
            else:
                lines.append("데이터 없음")
        except Exception as e:
            lines.append(f"오류: {e}")
    elif TOP_VOLUME_TXT.exists():
        try:
            vol_tickers = [line.strip() for line in TOP_VOLUME_TXT.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()][:10]
            if vol_tickers:
                for t in vol_tickers:
                    name = name_map.get(t.zfill(6), "미등록")
                    lines.append(f"{t.zfill(6)} ({name})")
            else:
                lines.append("데이터 없음")
        except Exception as e:
            lines.append(f"오류: {e}")
    else:
        lines.append("데이터 파일 없음")
        
    # 3. 당일주도주
    lines.append("\n🔥 [당일주도주]")
    if LEADER_TXT.exists():
        try:
            leader_tickers = [line.strip() for line in LEADER_TXT.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()]
            if leader_tickers:
                for t in leader_tickers:
                    name = name_map.get(t.zfill(6), "미등록")
                    lines.append(f"{t.zfill(6)} ({name})")
            else:
                lines.append("데이터 없음")
        except Exception as e:
            lines.append(f"오류: {e}")
    else:
        lines.append("데이터 파일 없음")
        
    full_msg = "\n".join(lines).strip()
    send(full_msg)
    print("Telegram notification sent.")
    print(full_msg)

if __name__ == "__main__":
    main()
