import requests
from pathlib import Path
from datetime import datetime
import shutil
import re
import json
import csv
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

# 1. 한국 ETF (Top 3만)
TODAY_KR_ETF = BASE_KR / "buy_list.txt"
PREV_KR_ETF  = BASE_US / "prev_buy_kr_etf.txt"

# 2. KR 150 신호 (report_kr_150.txt 분석)
REPORT_KR_150 = BASE_US / "report_kr_150.txt"
REPORT_KR     = BASE_US / "report_kr.txt"  # 전체 종목 리포트 추가

# 3. 저점 신호 데이터 (JSON)
LOW_POINT_JSON = BASE_US / "kr_low_point_data.json"

# 4. 연금 ETF 비중 파일
WEIGHT_TXT = Path("D:/py/0txt/0weight_buy.txt")

# 5. 당일 거래대금 상위 티커 파일 (topvolume30.py 생성)
TOPVOLUME_TXT = Path("D:/py/topvolume30.txt")
LEADER_TXT_00   = Path("D:/py/0txt/00_1887_leader.txt")
A_GRADE_TXT_00  = Path("D:/py/0txt/00_1887_a_grade_leader.txt")
B_GRADE_TXT_00  = Path("D:/py/0txt/00_1887_b_grade_leader.txt")
C_GRADE_TXT_00  = Path("D:/py/0txt/00_1887_c_grade_leader.txt")

# 6. 주문용 최종 보유 목록 (한국 ETF 게시판 기준)
REBAL_KR_TXT    = Path("D:/py/0order/00_etf_korea_rebalancing.txt")  # ticker,수량(sc3)
TOTAL_TOP30_CSV = Path("D:/py/0txt/total_top30.csv")                 # 당일등락률(%)

# 5. 종목명 매핑 파일들
TICKER_FILES = [
    BASE_KR / "korea" / "kr150.csv",
    BASE_KR / "korea" / "kr.csv",
    BASE_KR / "korea" / "etf.csv"      # 연금ETF 종목명 (KODEX/ACE/RISE 등)
]

# CSV에 없는 ETF 종목명 보충 (adv_momentum 유니버스 중 etf.csv 미수록분)
EXTRA_NAMES = {
    "147970": "TIGER 모멘텀",
    "195930": "TIGER 유로스탁스50(합성 H)",
}
# ==================

def load_ticker_names():
    """여러 CSV 파일에서 티커-종목명 매핑 로드 (캐싱을 통해 속도 저하 방지)"""
    mapping = {}
    for csv_path in TICKER_FILES:
        if not csv_path.exists():
            continue
        try:
            # 다양한 엔코딩 시도 (utf-8-sig는 BOM 제거용)
            for encoding in ['utf-8-sig', 'cp949', 'utf-8']:
                try:
                    with open(csv_path, mode='r', encoding=encoding) as f:
                        reader = csv.reader(f)
                        header = next(reader, None)
                        if not header: continue
                        
                        # 컬럼 인덱스 찾기
                        try:
                            t_idx = next(i for i, h in enumerate(header) if '코드' in h or 'ticker' in h.lower())
                            n_idx = next(i for i, h in enumerate(header) if '명' in h or 'Name' in h)
                        except StopIteration:
                            # 헤더가 없거나 컬럼을 못 찾으면 0, 1번 사용
                            t_idx, n_idx = 0, 1
                        
                        for row in reader:
                            if len(row) > max(t_idx, n_idx):
                                ticker = row[t_idx].strip().zfill(6)
                                name = row[n_idx].strip()
                                mapping[ticker] = name
                    break # 성공하면 다음 파일로
                except (UnicodeDecodeError, StopIteration):
                    continue
        except Exception as e:
            print(f"Error loading {csv_path.name}: {e}")
    # CSV 미수록 ETF 종목명 보충 (CSV 값이 있으면 CSV 우선)
    for tk, nm in EXTRA_NAMES.items():
        mapping.setdefault(tk, nm)
    return mapping

def read_list(path, limit=None):
    if not path.exists():
        return []
    try:
        lines = [line.strip() for line in path.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()]
        clean_lines = [t.split()[0] for t in lines if not t.startswith('#')]
        if limit:
            return clean_lines[:limit]
        return clean_lines
    except Exception:
        return []

def extract_tickers_from_report(text, section_header):
    """report_kr_150.txt에서 특정 섹션의 티커들을 추출"""
    lines = text.splitlines()
    start_idx = -1
    for i, line in enumerate(lines):
        if section_header in line:
            start_idx = i
            break
    
    if start_idx == -1:
        return []
    
    tickers = []
    # 구분선(---) 다음 줄부터 읽기
    for i in range(start_idx + 2, len(lines)):
        line = lines[i].strip()
        if not line or "【" in line or "===" in line or "📊" in line:
            break
        if "없음" in line:
            break
        # 티커 포맷 (6자리 숫자 또는 뒤에 ** 붙은 형태)
        match = re.search(r'(\d{6}(?:\*\*)?)', line)
        if match:
            tickers.append(match.group(1))
        elif len(line) >= 6 and line[:6].isdigit(): # 단순 티커만 적힌 경우 대비
            tickers.append(line)
            
    return tickers

def format_with_name(ticker_list, name_map):
    formatted = []
    for t in ticker_list:
        clean_t = t.replace('*', '') # ** 제거하고 조회
        name = name_map.get(clean_t, "미등록")
        formatted.append(f"{t}({name})")
    return formatted

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"Telegram send failed: {e}")

def main():
    # 종목명 매핑 로드 (한 번만 로드)
    name_map = load_ticker_names()
    
    # --- 1. 한국 ETF 비교 (Top 3) ---
    kr_etf_now = read_list(TODAY_KR_ETF, limit=3)
    kr_etf_prev = read_list(PREV_KR_ETF, limit=3)

    # invest_pct (kr_signal_stats.json)
    invest_pct_str = "-"
    try:
        stats_path = BASE_US / "kr_signal_stats.json"
        if stats_path.exists():
            with open(stats_path, 'r', encoding='utf-8') as _f:
                _s = json.load(_f)
            invest_pct_str = f"{_s.get('invest_pct', 0):.0f}%"
    except Exception:
        pass

    # 개별 비중 (0weight_buy.txt 첫 번째 # 주석 라인)
    weight_pct_str = "-"
    try:
        if WEIGHT_TXT.exists():
            for _line in WEIGHT_TXT.read_text(encoding='utf-8', errors='ignore').splitlines():
                _line = _line.strip()
                if _line.startswith('#'):
                    _m = re.search(r'(\d+(?:\.\d+)?)%', _line)
                    if _m:
                        weight_pct_str = f"{_m.group(1)}%"
                    break
    except Exception:
        pass

    # --- 시장 온도 (최상단 한 줄) ---
    try:
        report_json_path = BASE_US / "report_kr_150.json"
        if report_json_path.exists():
            with open(report_json_path, 'r', encoding='utf-8') as _f:
                _jd = json.load(_f)
            _mt = _jd.get('market_temp', {})
            _mt_val = _mt.get('today')
            _mt_status = _mt.get('status', '-')
            mt_line = f"🌡 시장 온도 : {_mt_status}  {_mt_val:.1f} / 100" if _mt_val is not None else "🌡 시장 온도 : 데이터 없음"
        else:
            mt_line = "🌡 시장 온도 : 데이터 없음"
    except Exception as e:
        mt_line = f"🌡 시장 온도 : 오류({e})"

    lines = [f"------------ {datetime.now().strftime('%y%m%d')}", mt_line, f"🇰🇷 [ETF Top3] 투자비중: {invest_pct_str} / {weight_pct_str}"]
    new_in = sorted(set(kr_etf_now) - set(kr_etf_prev))
    out = sorted(set(kr_etf_prev) - set(kr_etf_now))

    # --- 주문용 최종 보유 목록: 티커(종목명), 등락률, 수량(sc3) ---
    # 단축명(산업) : kr_signal_stats.json per_ticker_alloc
    ind_map = {}
    try:
        stats_path = BASE_US / "kr_signal_stats.json"
        if stats_path.exists():
            with open(stats_path, 'r', encoding='utf-8') as _f:
                _s = json.load(_f)
            for entry in (_s.get('per_ticker_alloc_sc3') or _s.get('per_ticker_alloc') or []):
                tk = str(entry.get('ticker', '')).strip()
                if tk:
                    ind_map[tk] = entry.get('industry', '')
    except Exception:
        pass
    # 등락률 : total_top30.csv
    chg_map = {}
    if TOTAL_TOP30_CSV.exists():
        try:
            with open(TOTAL_TOP30_CSV, encoding='utf-8-sig', errors='ignore', newline='') as f:
                for row in csv.DictReader(f):
                    raw = (row.get('티커', '') or '').strip().replace('**', '')
                    if not raw:
                        continue
                    try:    chg_map[raw] = float(row.get('당일등락률(%)', '') or 0)
                    except: pass
        except Exception:
            pass
    # 보유 목록 (00_etf_korea_rebalancing.txt 순서대로)
    holding_rows = []
    if REBAL_KR_TXT.exists():
        try:
            for ln in REBAL_KR_TXT.read_text(encoding='utf-8', errors='ignore').splitlines():
                ln = ln.strip()
                if not ln or ',' not in ln:
                    continue
                tk, q = [x.strip() for x in ln.split(',', 1)]
                nm  = ind_map.get(tk) or name_map.get(tk, '미등록')
                chg = chg_map.get(tk)
                chg_str = f"{chg:+.1f}%" if chg is not None else "-"
                holding_rows.append(f"{tk}({nm}), {chg_str}, {q}")
        except Exception as e:
            print(f"Error reading rebalancing file: {e}")
    if holding_rows:
        lines.extend(holding_rows)
    else:
        lines.append("-")

    if new_in:
        new_formatted = format_with_name(new_in, name_map)
        lines.append(f"➕ NEW: {', '.join(new_formatted)}")
    if out:
        out_formatted = format_with_name(out, name_map)
        lines.append(f"➖ OUT: {', '.join(out_formatted)}")

    # --- 2-1. KR150 주도주(오늘) (웹 구성종목 테이블) ---
    try:
        json_150 = BASE_US / "report_kr_150.json"
        leader_150 = []
        if json_150.exists():
            d_150 = json.loads(json_150.read_text(encoding='utf-8'))
            leader_150 = d_150.get('leader', [])
        lines.append("\n📊 주도주 (오늘)")
        if leader_150:
            for s in leader_150:
                tk = str(s.get('ticker', '')).strip()
                name = name_map.get(tk, s.get('name', '미등록'))
                lines.append(f"{tk}({name})")
        else:
            lines.append("(없음)")
    except Exception as e:
        print(f"Error reading KR150 leader: {e}")

    # --- 2-1b. [KR150 Signal] - SPOT (📊 주도주(오늘) 바로 아래로 이동) ---
    if REPORT_KR_150.exists():
        report_text_150 = REPORT_KR_150.read_text(encoding='utf-8', errors='ignore')
        lines.append("\n[KR150 Signal]")
        spot_150 = extract_tickers_from_report(report_text_150, "【💥 SPOT")
        lines.append("- SPOT")
        lines.extend(format_with_name(spot_150, name_map) if spot_150 else ["(없음)"])

    # --- 2-2. KR 전종목 신호 추출 ---
    if REPORT_KR.exists():
        kr_text = REPORT_KR.read_text(encoding='utf-8', errors='ignore')
        
        lines.append("\n[KR전종목]")
        
        # -주도주트래킹 (비활성화)
        # lines.append("-주도주트래킹")
        # try:
        #     tk_path_kr = BASE_US / "leader_tracking.json"
        #     if tk_path_kr.exists():
        #         tk_kr = json.loads(tk_path_kr.read_text(encoding='utf-8'))
        #         lines.extend([f"{k}({v.get('name','미등록')})" for k, v in tk_kr.items()] if tk_kr else ["(없음)"])
        #     else:
        #         lines.append("(없음)")
        # except:
        #     lines.append("(오류)")

        # -주도주(오늘)
        leader_kr = extract_tickers_from_report(kr_text, "【📊 주도주")
        lines.append("-주도주(오늘)")
        lines.extend(format_with_name(leader_kr, name_map) if leader_kr else ["(없음)"])

    # --- 5. 당일거래대금 게시판 - 🎯 주도주 (A그룹 / B그룹 / C그룹) ---
    if A_GRADE_TXT_00.exists() or B_GRADE_TXT_00.exists() or C_GRADE_TXT_00.exists():
        lines.append("\n당일거래대금")
        for grade_label, grade_path in [
            ("🎯 주도주 A그룹", A_GRADE_TXT_00),
            ("🎯 주도주 B그룹", B_GRADE_TXT_00),
            ("🎯 주도주 C그룹", C_GRADE_TXT_00),
        ]:
            try:
                grade_tickers = [
                    line.strip() for line in
                    grade_path.read_text(encoding='utf-8', errors='ignore').splitlines()
                    if line.strip()
                ] if grade_path.exists() else []
                lines.append(grade_label)
                if grade_tickers:
                    for t in grade_tickers:
                        name = name_map.get(t.zfill(6), "미등록")
                        lines.append(f"{t.zfill(6)}({name})")
                else:
                    lines.append("(없음)")
            except Exception as e:
                print(f"Error reading {grade_path.name}: {e}")

    # --- 발송 ---
    full_msg = "\n".join(lines).strip()
    send(full_msg)
    print("Telegram notification sent (KR Report).")
    print(full_msg)

    # 상태 업데이트 (ETF Top3)
    if TODAY_KR_ETF.exists():
        shutil.copyfile(TODAY_KR_ETF, PREV_KR_ETF)

if __name__ == "__main__":
    main()

