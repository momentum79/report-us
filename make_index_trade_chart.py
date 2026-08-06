import csv
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import journal_summary          # 게시판 첫 화면용 매매일지 요약표 생성
import make_trade_chart_boards   # 성과 tag별 종목 차트 생성
from make_trade_chart_boards import BOARDS, CHART_WIDTH

# Paths
BASE_DIR       = Path(__file__).resolve().parent
SOURCE_DIR     = Path(r"D:\py\0tradechart")
SOURCE_DIR_20D = Path(r"D:\py\0tradechart\20days")
TARGET_DIR     = BASE_DIR / "charts"
TARGET_DIR_20D = BASE_DIR / "charts" / "20days"
OUTPUT_HTML    = BASE_DIR / "trade_chart_list.html"
SUMMARY_HTML   = BASE_DIR / "trade_journal_summary.html"   # 첫 화면(매매일지)

JOURNAL_8042 = SOURCE_DIR / "0_매매일지_8042.csv"
JOURNAL_1887 = SOURCE_DIR / "0_매매일지.csv"

# 생성기 4종과 동일한 파일명 약어 규칙 (ETF 접두어 제거 + 5자)
ETF_PREFIXES = ["KODEX", "TIGER", "KBSTAR", "HANARO", "ARIRANG", "KOSEF",
                "TREX", "FOCUS", "SOL", "ACE", "PLUS", "TIMEFOLIO",
                "KCGI", "WON", "SMART", "RISE", "1Q", "TIME"]

RIGHT_SCALE_WIDTH = 82
COMPACT_CHART_WIDTH = 700          # 매매일지 hover 폴백(20days)용 — 게시판 차트와 별개
COMPACT_LOOKBACK_BARS = 75
COMPACT_RIGHT_OFFSET = 6

# 메뉴 줄바꿈 기준 폭. 브라우저 오른쪽 끝까지 메뉴가 붙지 않도록 여기서 끊고
# 다음 줄로 넘긴다(한 줄에 대략 8~9개). 1400px 이하 화면에선 전체 폭 사용.
HEADER_MAX_WIDTH = "72%"
CONTENT_WIDTH = CHART_WIDTH + 30   # 이보다 좁은 창이면 iframe 전체를 축소

# 게시판에 노출할 최근 거래일 범위(일). 최신 거래(매수/매도)가 이보다 오래된
# 종목은 게시판에서 숨김. 재매수하면 최신일이 갱신돼 자동 재노출.
RECENT_DAYS = 30


def clean_stale(target: Path) -> None:
    """타깃 폴더의 이전 차트 복사본만 제거 (다른 html은 보존).
    30일 지나 빠진 종목이 배포 폴더에 잔존하지 않게 매 실행 시 비운다."""
    for pat in ("*_1887*.html", "*_8042*.html"):
        for f in target.glob(pat):   # glob(비재귀) → 20days 하위폴더는 건드리지 않음
            try:
                f.unlink()
            except OSError:
                pass


def copy_chart(file: Path, target: Path, compact: bool = False) -> None:
    """Copy chart HTML and apply small renderer fixes for embedded charts."""
    text = file.read_text(encoding="utf-8")
    needle = "function mk(el,opts){return LightweightCharts.createChart"
    if needle in text:
        replacement = (
            "function mk(el,opts){"
            "opts=opts||{};"
            f"opts.rightPriceScale=Object.assign({{minimumWidth:{RIGHT_SCALE_WIDTH}}},"
            "opts.rightPriceScale||{});"
            "return LightweightCharts.createChart"
        )
        text = text.replace(needle, replacement)
        if compact:
            text = text.replace(
                ".chartbox{position:relative;background:#fff;border:1px solid #e0e0e0;border-radius:10px;overflow:hidden;flex:1;min-height:0;display:flex;flex-direction:column}",
                f".chartbox{{position:relative;background:#fff;border:1px solid #e0e0e0;border-radius:10px;overflow:hidden;flex:none;min-height:0;display:flex;flex-direction:column;width:min({COMPACT_CHART_WIDTH}px,100%);height:calc(100vh - 110px)}}",
            )
            text = text.replace(
                "timeScale:{borderColor:'#ddd',rightOffset:6,minBarSpacing:1.5},",
                f"timeScale:{{borderColor:'#ddd',rightOffset:{COMPACT_RIGHT_OFFSET},minBarSpacing:1.5}},",
            )
            text = text.replace(
                "var tot=D.ohlc.length,from=Math.max(0,tot-120),to=tot-1+6;",
                f"var tot=D.ohlc.length,lookback=Math.min({COMPACT_LOOKBACK_BARS},tot),from=Math.max(0,tot-lookback),to=tot-1+{COMPACT_RIGHT_OFFSET};",
            )
        (target / file.name).write_text(text, encoding="utf-8")
    else:
        shutil.copy2(file, target / file.name)


def abbr_name(stock_name: str) -> str:
    name = (stock_name or "").strip()
    up = name.upper()
    for p in ETF_PREFIXES:
        if up.startswith(p):
            name = name[len(p):].lstrip()
            break
    name = name[:5]
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "")
    return name


def _to_full_ymd(s: str, year: int) -> str:
    """매매일지 날짜(mm/dd 또는 yyyy-mm-dd) → 'YYYYMMDD'. 빈값 ''."""
    nums = re.findall(r"\d+", str(s or ""))
    if len(nums) >= 3 and len(nums[0]) == 4:
        return f"{int(nums[0]):04d}{int(nums[1]):02d}{int(nums[2]):02d}"
    if len(nums) >= 2:
        m, d = int(nums[0]), int(nums[1])
        y = year - 1 if m > datetime.now().month + 1 else year
        return f"{y:04d}{m:02d}{d:02d}"
    return ""


def latest_dates(journal: Path) -> dict:
    """약어명 → 최신 거래일 'YYYYMMDD' (매수/매도 중 최대)."""
    out = {}
    if not journal.exists():
        return out
    year = datetime.now().year
    with open(journal, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ab = abbr_name(row.get("종목명", ""))
            if not ab:
                continue
            for col in ("날짜", "매도날짜"):
                ymd = _to_full_ymd(row.get(col, ""), year)
                if ymd and ymd > out.get(ab, ""):
                    out[ab] = ymd
    return out


def _label(ymd: str, abbr: str) -> str:
    """'YYYYMMDD' + 약어 → 'M/D 약어' (날짜 없으면 약어만)."""
    if ymd and len(ymd) == 8:
        return f"{int(ymd[4:6])}/{int(ymd[6:8])} {abbr}"
    return abbr


def collect(folder: Path, target: Path, date_8042: dict, date_1887: dict,
            cutoff: str, compact: bool = False) -> tuple:
    """폴더 스캔/복사 → (1887목록, 8042목록). 각 항목 (ymd, label, stem), 최신순 정렬.
    최신 거래일(ymd)이 cutoff(YYYYMMDD) 이후인 종목만 복사·노출 (오래된/날짜미상은 제외)."""
    c1887, c8042 = [], []
    if folder.exists():
        for file in folder.glob("*.html"):
            stem = file.stem
            m = re.match(r"^(?P<abbr>.+)_1887_[WL]_(?P<d>\d{6})$", stem)
            if m:  # 1887 20봉 세션차트 (파일명에 매도일)
                ymd, abbr, bucket = "20" + m.group("d"), m.group("abbr"), c1887
            elif stem.endswith("_1887"):
                abbr = stem[:-5]
                ymd, bucket = date_1887.get(abbr, ""), c1887
            elif stem.endswith("_8042"):
                abbr = stem[:-5]
                ymd, bucket = date_8042.get(abbr, ""), c8042
            else:
                continue
            if not ymd or ymd < cutoff:   # 최근 N일 외(또는 날짜 미상) → 게시판 제외
                continue
            copy_chart(file, target, compact=compact)
            bucket.append((ymd, _label(ymd, abbr), stem))
    c1887.sort(key=lambda x: x[0], reverse=True)  # 최신일자 위로
    c8042.sort(key=lambda x: x[0], reverse=True)
    return c1887, c8042


def main():
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    TARGET_DIR_20D.mkdir(parents=True, exist_ok=True)

    # 이전 실행분 차트 복사본 정리 → 30일 지나 빠진 종목이 배포 폴더에 안 남게
    clean_stale(TARGET_DIR)
    clean_stale(TARGET_DIR_20D)

    cutoff = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%Y%m%d")

    date_8042 = latest_dates(JOURNAL_8042)
    date_1887 = latest_dates(JOURNAL_1887)

    # 20일 세션차트는 게시판 드롭다운에선 빠졌지만, 매매일지 요약표의 종목 hover
    # 미리보기 폴백(journal_summary._chart_url)이 charts/20days 를 쓰므로 계속 복사한다.
    collect(SOURCE_DIR_20D, TARGET_DIR_20D, date_8042, date_1887, cutoff, compact=True)

    # 성과 tag별 종목 차트 생성 → {key: [(latest_iso, label, value), ...] 최신순}
    boards = make_trade_chart_boards.generate()

    # 거래가 있는 tag 만 드롭다운 생성 (BOARDS 정의 순서 유지)
    active = [(b, boards.get(b["key"], [])) for b in BOARDS if boards.get(b["key"])]
    select_ids = [f"select-{b['key']}" for b, _ in active]

    groups = []
    for b, items in active:
        sid = f"select-{b['key']}"
        opts = "".join(f'<option value="{value}">{label}</option>'
                       for _iso, label, value in items)
        groups.append(
            '<div class="acct-group">'
            f'<span class="acct-label" style="background:{b["color"]}">{b["label"]}</span>'
            f"<select id=\"{sid}\" onchange=\"updateChart(this.value, '{sid}')\">"
            f'<option value="">-- 종목 선택 --</option>{opts}</select></div>')

    # 첫 화면: 매매일지 요약표(차트 대신). 상단 select 에서 종목 고르면 차트로 전환.
    summary_ok = False
    try:
        days, n_rows = journal_summary.build_summary_file(str(SUMMARY_HTML), charts_dir=str(TARGET_DIR))
        print(f"     매매일지 : {SUMMARY_HTML.name} ({days}거래일 / {n_rows}건)")
        default_src = SUMMARY_HTML.name
        summary_ok = True
    except Exception as e:
        print(f"     [WARN] 매매일지 요약 생성 실패 → 차트로 fallback: {e}")
        default_src = active[0][1][0][2] if active else ""

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ids_json = json.dumps(select_ids)
    first_id = select_ids[0] if select_ids else ""
    groups_html = "".join(groups)

    summary_btn = (
        '<div class="acct-group"><span class="acct-label summary-btn" '
        'onclick="showSummary()">■ 매매일지</span></div>' if summary_ok else ""
    )

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>매매 일지 차트</title>
    <style>
        body, html {{
            margin: 0;
            padding: 0;
            height: 100%;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f4f7f6;
            overflow: hidden;
        }}
        body {{ display: flex; flex-direction: column; }}
        /* 메뉴가 브라우저 오른쪽 끝까지 붙지 않게 {HEADER_MAX_WIDTH} 에서 끊고 다음 줄로 넘긴다
           (한 줄 대략 8~9개). 줄 사이 여백은 0 — 여러 단이어도 위아래로 붙어 보이게. */
        .header {{
            flex: 0 0 auto;
            padding: 3px 12px 4px;
            background: #fff;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 0 12px;
            max-width: {HEADER_MAX_WIDTH};
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            z-index: 10;
            position: relative;
        }}
        @media screen and (max-width: 1400px) {{
            .header {{ max-width: 100%; }}
        }}
        .acct-group {{
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 1px 0;
        }}
        .acct-label {{
            font-size: 12px;
            font-weight: 700;
            color: #fff;
            padding: 2px 9px;
            border-radius: 20px;
            white-space: nowrap;
        }}
        .acct-label.summary-btn {{ background: #1d1d1f; cursor: pointer; }}
        .acct-label.summary-btn:hover {{ background: #000; }}
        .updated {{
            font-size: 11px;
            color: #8a8a8a;
            white-space: nowrap;
            margin-left: auto;
            padding-left: 12px;
        }}
        select {{
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid #ccc;
            font-size: 12px;
            color: #2c3e50;
            outline: none;
            background-color: #f9f9f9;
            width: 108px;
        }}
        .iframe-container {{
            flex: 1 1 auto;
            min-height: 0;
            width: 100%;
            position: relative;
            overflow: auto;
            -webkit-overflow-scrolling: touch;
        }}
        iframe {{
            width: 100%;
            height: 100%;
            border: none;
            display: block;
            transform-origin: 0 0;
        }}
        @media screen and (max-width: 950px) and (orientation: landscape) and (hover: none) and (pointer: coarse) {{
            .top-nav-container, .top-nav {{ display: none !important; }}
        }}
    </style>
    <script>
        var SELECT_IDS = {ids_json};        // 거래 있는 tag 게시판만
        var activeSelectId = null;          // 키보드 D/S 이동 대상(현재 게시판)
        var SUMMARY_SRC = "{default_src}";  // 첫 화면(매매일지 요약)

        // 차트 → 매매일지 요약으로 복귀. 모든 select 초기화.
        function showSummary() {{
            document.getElementById('chart-frame').src = SUMMARY_SRC;
            activeSelectId = null;
            SELECT_IDS.forEach(function(id) {{
                var el = document.getElementById(id);
                if (el) el.value = '';
            }});
            adjustScale();
        }}

        function updateChart(url, activeId) {{
            if (!url) return;
            document.getElementById('chart-frame').src = url;
            activeSelectId = activeId;
            SELECT_IDS.forEach(function(id) {{
                if (id !== activeId) {{
                    var el = document.getElementById(id);
                    if (el) el.value = '';
                }}
            }});
            adjustScale();
        }}

        function adjustScale() {{
            const iframe = document.getElementById('chart-frame');
            const winW = window.innerWidth;
            const contentW = {CONTENT_WIDTH};
            if (winW < contentW) {{
                const scale = winW / contentW;
                iframe.style.width = contentW + 'px';
                iframe.style.height = (100 / scale) + '%';
                iframe.style.transform = 'scale(' + scale + ')';
            }} else {{
                iframe.style.width = '100%';
                iframe.style.height = '100%';
                iframe.style.transform = 'none';
            }}
        }}

        window.addEventListener('resize', adjustScale);
        window.addEventListener('load', adjustScale);

        // 시작 시: 현재 표시중인 차트와 일치하는 select를 활성 게시판으로 동기화
        window.addEventListener('load', function() {{
            var ds = document.getElementById('chart-frame').getAttribute('src');
            SELECT_IDS.forEach(function(id) {{
                var s = document.getElementById(id);
                if (!s) return;
                for (var i = 0; i < s.options.length; i++) {{
                    if (s.options[i].value === ds) {{ s.selectedIndex = i; activeSelectId = id; break; }}
                }}
            }});
        }});

        // 키보드 D/↓=다음, S/↑=이전. 단, '현재 게시판(select)' 안에서만 이동.
        function moveWithinBoard(dir) {{
            var id = activeSelectId;
            if (!id) {{  // 아직 아무것도 안 골랐으면 값이 있는 select를 찾고, 없으면 첫 게시판
                SELECT_IDS.some(function(x) {{
                    var el = document.getElementById(x);
                    if (el && el.value) {{ id = x; return true; }}
                    return false;
                }});
                if (!id) id = "{first_id}";
            }}
            var sel = document.getElementById(id);
            if (!sel || sel.options.length <= 1) return;  // 빈 게시판
            var idx = sel.selectedIndex;
            if (idx < 1) idx = (dir > 0 ? 0 : 1);  // index 0 = '-- 종목 선택 --' 플레이스홀더는 건너뜀
            var ni = idx + dir;
            if (ni < 1) ni = 1;
            if (ni > sel.options.length - 1) ni = sel.options.length - 1;
            if (ni === sel.selectedIndex) return;
            sel.selectedIndex = ni;
            updateChart(sel.value, id);
        }}
        document.addEventListener('keydown', function(e) {{
            var t = e.target, tag = t && t.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || (t && t.isContentEditable)) return;
            var k = e.key, dir = 0;
            if (k === 's' || k === 'S' || k === 'ArrowUp') dir = -1;
            else if (k === 'd' || k === 'D' || k === 'ArrowDown') dir = 1;
            if (dir === 0) return;
            // 매매일지 요약이 떠 있으면(종목 미선택) D/S 를 표 내부 행 이동으로 위임
            var fr = document.getElementById('chart-frame');
            if (!activeSelectId && fr.getAttribute('src') === SUMMARY_SRC) {{
                try {{
                    if (fr.contentWindow && typeof fr.contentWindow.journalNav === 'function') {{
                        e.preventDefault();
                        fr.contentWindow.journalNav(dir);
                        return;
                    }}
                }} catch (err) {{}}
            }}
            e.preventDefault();  // select가 포커스됐을 때 네이티브 이동/타입어헤드 중복 방지
            moveWithinBoard(dir);
        }});
    </script>
</head>
<body>
    <div class="header">
        {summary_btn}{groups_html}<span class="updated">Updated: {now_str}</span>
    </div>
    <div class="iframe-container">
        <iframe id="chart-frame" src="{default_src}" onload="adjustScale()"></iframe>
    </div>
</body>
</html>
"""
    OUTPUT_HTML.write_text(html_content, encoding="utf-8")
    print(f"[OK] {OUTPUT_HTML} updated  (최근 {RECENT_DAYS}일: {cutoff}~ 거래분만)")
    for b in BOARDS:
        n = len(boards.get(b["key"], []))
        print(f"     {b['label']:12s} {n:3d}개" + ("" if n else "   (거래 없음 → 메뉴 숨김)"))


if __name__ == "__main__":
    main()
