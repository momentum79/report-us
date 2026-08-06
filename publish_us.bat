@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set PYTHONUTF8=1

echo ===============================
echo [1/8] Run US STOCK python
echo ===============================
python -X utf8 usa_jasan_trview_batchver.py > report_us.txt 2>&1
if errorlevel 1 (
    echo ERROR: usa_jasan_trview_batchver.py failed
    type report_us.txt
    pause
    exit /b 1
)

echo ===============================
echo [2/8] Run US ETF python
echo ===============================
python -X utf8 usa_jasantop4_ETF.py > report_us_etf.txt 2>&1
if errorlevel 1 (
    echo ERROR: usa_jasantop4_ETF.py failed
    type report_us_etf.txt
    pause
    exit /b 1
)

echo ===============================
echo [3/8] Run US Interest python
echo ===============================
python -X utf8 usa_jasantop4_interest.py > report_us_interest.txt 2>&1
if errorlevel 1 (
    echo ERROR: usa_jasantop4_interest.py failed
    type report_us_interest.txt
    pause
    exit /b 1
)

echo ===============================
echo [4/8] Make us_stock.html (US STOCK)
echo ===============================
python -X utf8 make_index_us.py
if errorlevel 1 (
    echo ERROR: make_index_us.py failed
    pause
    exit /b 1
)

echo ===============================
echo [5/8] Make us_etf.html (US ETF)
echo ===============================
python -X utf8 make_index_us_etf.py
if errorlevel 1 (
    echo ERROR: make_index_us_etf.py failed
    pause
    exit /b 1
)

echo ===============================
echo [6/8] Make us_interest.html (US Interest)
echo ===============================
python -X utf8 make_index_us_interest.py
if errorlevel 1 (
    echo ERROR: make_index_us_interest.py failed
    pause
    exit /b 1
)

echo ===============================
echo [7/8] Git add / status
echo ===============================
git add report_us.txt report_us_etf.txt report_us_interest.txt index.html us_stock.html us_etf.html us_interest.html
git status

echo ===============================
echo [8/8] Commit and push
echo ===============================
git commit -m "auto update (US stock + ETF + Interest)" || echo (no changes to commit)
git push

python notify_telegram_if_changed.py || echo (telegram notification skipped)

echo.
echo [DONE] US Web updated:
echo https://momentum79.github.io/report-us/
echo https://momentum79.github.io/report-us/us_etf.html
echo https://momentum79.github.io/report-us/us_stock.html
echo https://momentum79.github.io/report-us/us_interest.html

REM pause
endlocal

