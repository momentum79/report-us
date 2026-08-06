@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ===============================
echo [1/5] Run Minervini Analysis
echo ===============================
cd /d "D:\py"
python -X utf8 mark1_kr_vol.py

if errorlevel 1 (
    echo WARNING: mark1_kr_vol.py failed, continuing anyway...
)

echo ===============================
echo [2/5] Run Korea Stock Analysis
echo ===============================
REM Move to execution directory for correct relative path resolution (e.g. kr.csv)
cd /d "D:\py\korea"

REM Run and capture output to the report directory
python -X utf8 chu_korea_final_all_tic.py > "D:\py\report-us\report_kr.txt" 2>&1

if errorlevel 1 (
    echo ERROR: chu_korea_final_all_tic.py failed
    type "D:\py\report-us\report_kr.txt"
    pause
    exit /b 1
)

REM Move to kr report directory
cd /d "D:\py\report-us\kr"

echo ===============================
echo [3/5] Make index.html
echo ===============================
python -X utf8 make_index_kr.py
if errorlevel 1 (
    echo ERROR: make_index_kr.py failed
    pause
    exit /b 1
)

REM Move to parent directory for git operations
cd /d "D:\py\report-us"

echo ===============================
echo [4/5] Git add / status
echo ===============================
git add report_kr.txt kr/index.html
git status

echo ===============================
echo [5/5] Commit and push
echo ===============================
git commit -m "auto update (KR stock + Minervini)" || echo (no changes to commit)
git push

echo.
echo [DONE] KR Web updated:
echo https://momentum79.github.io/report-us/kr/

REM pause
endlocal
