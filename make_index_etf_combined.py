# make_index_etf_combined.py
import csv
import io
from pathlib import Path
from datetime import datetime

# Paths
BASE = Path(__file__).resolve().parent
PROJECT_ROOT = BASE.parent
CSV_FILE = PROJECT_ROOT / "0txt" / "total_top30.csv"
TOP6_FILE = PROJECT_ROOT / "buy_list_total.txt"
OUT_HTML = BASE / "etf_combined.html"

# Google Sheet for Indicators (사용 안 함)

def read_top6():
    if not TOP6_FILE.exists():
        return ""
    try:
        tickers = TOP6_FILE.read_text(encoding="utf-8").splitlines()
        tickers = [t.strip() for t in tickers if t.strip()]
        return ", ".join(tickers)
    except:
        return ""

def read_data():
    if not CSV_FILE.exists():
        return []
    
    data = []
    try:
        # total_top30.csv header: 티커,종목명,3M(%),score,Score
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row['티커']
                name = row['종목명']
                # Determine if KR based on ticker (6 digits)
                is_kr = ticker.isdigit() and len(ticker) == 6
                
                data.append({
                    'ticker': ticker,
                    'name': name if is_kr else '', # Only show name for KR
                    'rtn': float(row['3M(%)']),
                    'sco': float(row['score']),
                    'score_final': float(row['Score']),
                    'type': 'KR' if is_kr else 'US'
                })
    except Exception as e:
        print(f"[Error] Failed to read CSV: {e}")
    return data

def main():
    data = read_data()
    top6_line = read_top6()
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>ETF 수익률 상위</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; padding: 15px; background-color: #f4f7f6; margin: 0; line-height: 1.2; }}
h1 {{ font-size: 1.3rem; color: #2c3e50; margin: 0 0 10px 0; }}
.meta {{ color: #7f8c8d; font-size: 0.85rem; margin-bottom: 8px; }}
.top6 {{ background: #ebf5fb; padding: 8px; border-radius: 5px; font-weight: bold; font-size: 0.9rem; color: #2980b9; margin-bottom: 10px; }}
.styled-table {{ width: 100%; max-width: 600px; border-collapse: collapse; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 13px; }}
.styled-table thead tr {{ background-color: #3498db; color: #ffffff; text-align: left; }}
.styled-table th, .styled-table td {{ padding: 5px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
.type-kr {{ color: #e74c3c; font-weight: bold; font-size: 0.75rem; }}
.type-us {{ color: #3498db; font-weight: bold; font-size: 0.75rem; }}
.top-nav-container {{ display: flex; margin-bottom: 10px; }}
.top-nav {{ display: flex; background-color: #2c3e50; border-radius: 8px; overflow: hidden; width: fit-content; }}
.nav-item {{ padding: 8px 15px; color: #bdc3c7; text-align: center; cursor: pointer; font-weight: bold; text-decoration: none; transition: all 0.3s; font-size: 0.9em; }}
.nav-item:hover {{ background-color: #34495e; color: #fff; }}
.nav-item.active {{ background-color: #3498db; color: white; }}
@media (max-width: 600px) {{
    .styled-table {{ font-size: 12px; }}
    .styled-table th, .styled-table td {{ padding: 4px 6px; }}
}}

@media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
</style>
</head>
<body>
    <div class="top-nav-container">
        <div class="top-nav">
            <a href="total_etf_combined.html" class="nav-item">🌐 글로벌</a>
            <a href="etf_combined.html" class="nav-item active">📈 ETF 한미</a>
        </div>
    </div>
    <h1>📈 ETF 수익률 상위 (KR/US 통합)</h1>
    <p class="meta">Updated: {now}</p>
    {f'<div class="top6">최종 보유 (오늘): {top6_line}</div>' if top6_line else ''}
    <table class="styled-table">
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Name</th>
                <th>3M(%)</th>
                <th>sco</th>
                <th>Score</th>
            </tr>
        </thead>
        <tbody>
"""
    for idx, item in enumerate(data, 1):
        type_label = f'<span class="type-{"kr" if item["type"]=="KR" else "us"}">[{item["type"]}]</span>'
        
        # Row highlighting
        row_style = ""
        if idx <= 6:
            row_style = ' style="background-color: #FFFF99;"' # 연노랑
        elif item['sco'] >= 11:
            row_style = ' style="background-color: #CCFFFF;"' # 연하늘
        
        # Color for 3M(%)
        color = '#e74c3c' if item['rtn'] > 0 else '#3498db'
        
        html_content += f"""
            <tr{row_style}>
                <td>{type_label} {item['ticker']}</td>
                <td style="color:#7f8c8d">{item['name']}</td>
                <td style="font-weight:bold; color:{color}">{item['rtn']:.1f}%</td>
                <td>{item['sco']:.1f}</td>
                <td style="font-weight:bold">{item['score_final']:.1f}</td>
            </tr>"""

    html_content += """
        </tbody>
    </table>
</body>
</html>
"""
    OUT_HTML.write_text(html_content, encoding="utf-8")
    print(f"[OK] {OUT_HTML.name} generated ({len(data)} items)")

if __name__ == "__main__":
    main()
