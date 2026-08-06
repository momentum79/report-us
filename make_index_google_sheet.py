import pandas as pd
import requests
import time
import os
import ssl
from datetime import datetime
from pathlib import Path

# 보안 인증서 검사 건너뛰기 (회사 네트워크용)
ssl._create_default_https_context = ssl._create_unverified_context

# 설정
SHEET_ID = "1V7saARZh2eLo4On7yaAgnfmIAIrUBNAmBXWl8eVKAV8"
GID = "2096343292"
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_HTML = BASE_DIR / "google_sheet.html"

def get_sheet_data():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 구글 시트 갱신을 위해 60초 대기 중...")
    # 시트가 갱신될 시간을 벌어줍니다.
    time.sleep(60)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 데이터 로드 중...")
    try:
        # CSV 전체 로드 (header=None으로 해서 모든 행 가져옴)
        df = pd.read_csv(EXPORT_URL, header=None)
        
        # B1:K30 -> index 1~10, rows 0~29
        # O1:O30 -> index 14, rows 0~29
        
        # B to K (1 to 10)
        cols_bk = df.iloc[0:30, 1:11] 
        # O (14)
        col_o = df.iloc[0:30, 14:15]
        
        # 합치기
        final_df = pd.concat([cols_bk, col_o], axis=1)
        return final_df
    except Exception as e:
        print(f"데이터 로드 실패: {e}")
        return None

def generate_html(df):
    if df is None:
        return
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 헤더와 데이터 분리
    headers = df.iloc[0].values
    data = df.iloc[1:].values
    
    html_content = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>Moving Average Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f4f7f6;
            margin: 0;
            padding: 15px;
            display: flex;
            flex-direction: column;
            align-items: flex-start;
        }}
        
        .card {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            width: auto;
            max-width: 100%;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        
        .card-header {{
            padding: 8px 12px;
            border-bottom: 1px solid #eee;
            background: white;
        }}
        
        .update-time {{
            font-size: 0.8rem;
            color: #7f8c8d;
        }}
        
        .table-container {{
            overflow-x: auto;
        }}
        
        table {{
            border-collapse: collapse;
            font-size: 12px;
            width: auto;
        }}
        
        th {{
            background-color: #3498db;
            color: #ffffff;
            padding: 5px 10px;
            font-weight: 600;
            text-align: center;
            white-space: nowrap;
        }}
        
        td {{
            padding: 4px 8px;
            border-bottom: 1px solid #eee;
            white-space: nowrap;
            text-align: center;
        }}
        
        tr:nth-of-type(even) {{
            background-color: #f9f9f9;
        }}

        .up {{ color: #27ae60; font-weight: bold; }}
        .down {{ color: #e74c3c; font-weight: bold; }}
        
        .pos-top {{ background-color: #e74c3c; color: white; font-weight: bold; border-radius: 4px; }}
        .pos-high {{ background-color: #f39c12; color: white; font-weight: bold; border-radius: 4px; }}
        
        .sig-jung {{ background-color: #e8f5e9; color: #27ae60; font-weight: bold; }}
        .sig-yeok {{ background-color: #ffebee; color: #e74c3c; font-weight: bold; }}

        .ticker {{ font-weight: bold; text-align: left; color: #2c3e50; }}
        .etf-name {{ text-align: left; color: #34495e; max-width: 120px; overflow: hidden; text-overflow: ellipsis; }}
        
        .trend-up-3 {{ background: #00ff00; color: #000; font-weight: bold; border-radius: 3px; padding: 1px 3px; }}
        .trend-up-2 {{ background: #b7e1cd; color: #000; font-weight: bold; border-radius: 3px; padding: 1px 3px; }}
        .trend-down-3 {{ background: #ff0000; color: #fff; font-weight: bold; border-radius: 3px; padding: 1px 3px; }}
        .trend-down-2 {{ background: #ff9900; color: #fff; font-weight: bold; border-radius: 3px; padding: 1px 3px; }}
        
        @media (max-width: 600px) {{
            body {{ padding: 10px; }}
            td, th {{ padding: 3px 5px; font-size: 11px; }}
        }}
    @media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
  .top-nav-container, .top-nav {{ display: none !important; }}
}}
</style>
</head>
<body>
    <div class="card">
        <div class="card-header">
            <div class="update-time">마지막 업데이트: {now}</div>
        </div>
        <div class="table-container">
            <table id="maTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">Ticker</th>
                        <th onclick="sortTable(1)">Name</th>
                        <th onclick="sortTable(2)">위치</th>
                        <th onclick="sortTable(3)">정/역</th>
                        <th onclick="sortTable(4)">5</th>
                        <th onclick="sortTable(5)">10</th>
                        <th onclick="sortTable(6)">20</th>
                        <th onclick="sortTable(7)">60</th>
                        <th onclick="sortTable(8)">120</th>
                        <th onclick="sortTable(9)">추세</th>
                        <th onclick="sortTable(10)">1/3/6</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for row in data:
        html_content += "<tr>"
        for i, val in enumerate(row):
            val_str = str(val) if pd.notna(val) else ""
            cls = ""
            
            # 컬럼별 특징적 스타일링
            if i == 0: cls = "ticker"
            elif i == 1: cls = "etf-name"
            
            # 위치 (index 2)
            if i == 2:
                if val_str == "5": cls = "pos-top"
                elif val_str == "4": cls = "pos-high"
            
            # 정/역배 (index 3) - NEW!
            if i == 3:
                if "정배" in val_str: cls = "sig-jung"
                elif "역배" in val_str: cls = "sig-yeok"

            # '하' (주황색), '상' (파란색) - 5~120 컬럼 (index 4~8)
            if 4 <= i <= 8:
                if "하" in val_str: cls = "down"
                elif "상" in val_str: cls = "up"
            
            # 추세 (index 9)
            if i == 9:
                if val_str == "3": cls = "trend-up-3"
                elif val_str == "2": cls = "trend-up-2"
                elif val_str == "-3": cls = "trend-down-3"
                elif val_str == "-2": cls = "trend-down-2"

            # 1/3/6 평균 (index 10)
            if i == 10:
                try:
                    num_val = float(val_str.replace('%', '').replace(',', ''))
                    if num_val > 0: cls = "up"
                    elif num_val < 0: cls = "down"
                except:
                    pass

            html_content += f'<td class="{cls}">{val_str}</td>'
        html_content += "</tr>"
        
    html_content += """
                </tbody>
            </table>
        </div>
    </div>
    <script>
    function sortTable(n) {{
        var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
        table = document.getElementById("maTable");
        switching = true;
        dir = "asc";
        while (switching) {{
            switching = false;
            rows = table.rows;
            for (i = 1; i < (rows.length - 1); i++) {{
                shouldSwitch = false;
                x = rows[i].getElementsByTagName("TD")[n];
                y = rows[i + 1].getElementsByTagName("TD")[n];
                
                var xVal = x.textContent || x.innerText;
                var yVal = y.textContent || y.innerText;
                
                // Clean values for numeric comparison
                xVal = xVal.replace(/[%,원]/g, '').trim();
                yVal = yVal.replace(/[%,원]/g, '').trim();
                
                if (!isNaN(parseFloat(xVal)) && isFinite(xVal) && !isNaN(parseFloat(yVal)) && isFinite(yVal)) {{
                    xVal = parseFloat(xVal);
                    yVal = parseFloat(yVal);
                }} else {{
                    xVal = xVal.toLowerCase();
                    yVal = yVal.toLowerCase();
                }}

                if (dir == "asc") {{
                    if (xVal > yVal) {{
                        shouldSwitch = true;
                        break;
                    }}
                }} else if (dir == "desc") {{
                    if (xVal < yVal) {{
                        shouldSwitch = true;
                        break;
                    }}
                }}
            }}
            if (shouldSwitch) {{
                rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                switching = true;
                switchcount++;
            }} else {{
                if (switchcount == 0 && dir == "asc") {{
                    dir = "desc";
                    switching = true;
                }}
            }}
        }}
    }}
    </script>
</body>
</html>
    """
    
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[성공] {OUTPUT_HTML} 생성 완료")

if __name__ == "__main__":
    df = get_sheet_data()
    generate_html(df)
