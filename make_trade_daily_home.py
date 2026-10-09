# -*- coding: utf-8 -*-
"""
make_trade_daily_home.py ── 자동일지차트 첫 화면 '날짜별' (2026-10-09 사용자 요청)
─────────────────────────────────────────────────────────────────────────────
위: 일별 손익 최근 7일 + 월별 집계 + 보유 코인 2줄  (매매 MASTER 창 맨 끝과 같은 숫자)
아래: 고른 날짜의 매매차트를 메뉴(성과 tag)별로 쫙 펼침. 날짜 줄을 누르면 그 날짜로 바뀐다.
      일봉 봇 묶음을 먼저, 5분봉 메뉴(2X단타·삼닉v3·저사다리 …)는 맨 끝에 따로.

손익 숫자의 원천 = 0order/0_trade_master.py 의 Watcher 를 그대로 불러서 '수익금 칸'을
  날짜(달력일)·시장별로 더한다 — MASTER 창 daily_pnl_lines() 와 같은 규칙(매도·dup 제외).
  그래서 창과 웹이 늘 같다. 주식은 주문접수 기준(MASTER 와 동일), 체결 기준인 주간성과와 다를 수 있다.
월별은 봇 로그가 지워져도 남도록 report-us/daily_pnl_history.json 에 날마다 쌓는다:
  최근 7일은 매번 다시 쓰고, 그보다 옛날은 처음 한 번만 적고 얼린다(로그가 잘려 작아지는 걸 막음).
보유 코인 2줄 = coin/0txt/holdings_coin.json 스냅샷(코인 마스터 슬롯마다 갱신). API 호출 없음.

카드 = 게시판 차트 페이지를 iframe 으로 띄운다(?card=1&focus=날짜). 차트 데이터를 따로 저장하지
  않아서 git 용량이 늘지 않고, 화면에 들어온 카드만 불러온다(loading=lazy).
호출: make_index_trade_chart.main() → build(day_cards, boards)
"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
OUT_HTML = os.path.join(BASE_DIR, "trade_daily.html")
HISTORY_JSON = os.path.join(BASE_DIR, "daily_pnl_history.json")
HOLD_SNAP = os.path.join(ROOT_DIR, "coin", "0txt", "holdings_coin.json")
MASTER_PY = os.path.join(ROOT_DIR, "0order", "0_trade_master.py")

PNL_DAYS = 7
FREEZE_DAYS = 7          # 이보다 옛날 날짜는 history 에 한 번 적히면 다시 안 고친다
MARKETS = [("국내", "한국", "KRW"), ("미국", "미국", "USD"), ("업비트", "업비트", "KRW"), ("바이낸스", "바낸", "USD")]
WEEKDAY_KO = "월화수목금토일"
HOLD_DUST_KRW = 5000
HOLD_SKIP = {"USDT"}


# ───────────────────────── 손익 (MASTER 와 같은 계산) ─────────────────────────
def _load_master():
    spec = importlib.util.spec_from_file_location("trade_master_for_web", MASTER_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trade_master_for_web"] = mod          # dataclass 가 모듈을 찾는다
    spec.loader.exec_module(mod)
    return mod


def master_pnl_by_day():
    """MASTER Watcher 로 전 기록을 읽어 {date: {시장: 금액}}, usdkrw."""
    tm = _load_master()
    w = tm.Watcher(ROOT_DIR)
    w.poll()
    by_day = {}
    for e in w.events:
        if e.side != "SELL" or e.kind not in ("fill", "order") or e.dup:
            continue
        v = tm.pnl_amount(e)
        if v is None:
            continue
        d = e.ts.strftime("%Y-%m-%d")
        by_day.setdefault(d, {})
        by_day[d][e.market] = by_day[d].get(e.market, 0.0) + v
    if w.errors:
        print(f"     [손익] MASTER 기록원 오류 {len(w.errors)}건 (나머지는 정상 집계)")
    return by_day, tm.load_usdkrw(ROOT_DIR)


def _load_history():
    try:
        with open(HISTORY_JSON, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_history(hist):
    """날짜당 한 줄(정렬) — 두 PC 가 git 으로 주고받을 때 충돌 범위를 줄인다. 바뀔 때만 쓴다."""
    keys = sorted(hist)
    lines = ["{"]
    for i, k in enumerate(keys):
        lines.append(f'"{k}": {json.dumps(hist[k], ensure_ascii=False, sort_keys=True)}'
                     + ("," if i < len(keys) - 1 else ""))
    lines.append("}")
    text = "\n".join(lines) + "\n"
    try:
        with open(HISTORY_JSON, encoding="utf-8") as f:
            if f.read() == text:
                return
    except OSError:
        pass
    tmp = HISTORY_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, HISTORY_JSON)


def update_history(by_day, fx, today):
    hist = _load_history()
    fresh_from = (today - timedelta(days=FREEZE_DAYS)).strftime("%Y-%m-%d")
    for d, m in by_day.items():
        if d > today.strftime("%Y-%m-%d"):
            continue
        if d >= fresh_from or d not in hist:
            row = {k: round(v, 2) for k, v in m.items()}
            row["fx"] = round(fx, 2) if fx else (hist.get(d) or {}).get("fx")
            hist[d] = row
    _save_history(hist)
    return hist


def _krw_total(m, fx):
    tot, any_ = 0.0, False
    for mkt, _lab, ccy in MARKETS:
        v = m.get(mkt)
        if v is None:
            continue
        if ccy == "USD":
            if not fx:
                continue
            v *= fx
        tot += v
        any_ = True
    return tot if any_ else None


# ───────────────────────── 보유 코인 스냅샷 ─────────────────────────
def hold_lines():
    try:
        with open(HOLD_SNAP, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return [], ""
    at = str(snap.get("generated_at", ""))[5:16]
    out = []
    up = snap.get("upbit") or {}
    if up.get("ok"):
        rows = [h for h in up.get("holdings") or []
                if h.get("cur") not in HOLD_SKIP and (h.get("eval") or 0) >= HOLD_DUST_KRW]
        rows.sort(key=lambda h: h.get("eval") or 0, reverse=True)
        pnls = [h.get("pnl") for h in up.get("holdings") or []
                if h.get("cur") not in HOLD_SKIP and h.get("pnl") is not None]
        out.append(("업비트", sum(pnls) if pnls else None, "KRW",
                    [(h["cur"], h.get("pnl_rate")) for h in rows]))
    bn = snap.get("binance") or {}
    if bn.get("ok"):
        items = []
        for p in sorted(bn.get("positions") or [],
                        key=lambda p: abs((p.get("amt") or 0) * (p.get("mark") or 0)), reverse=True):
            sym = str(p.get("symbol") or "")
            sym = sym[:-4] if sym.endswith("USDT") else sym
            entry, mark = p.get("entry") or 0, p.get("mark") or 0
            pct = (mark / entry - 1) * 100 if entry and mark else None
            if pct is not None and p.get("side") == "SHORT":
                pct = -pct
            items.append((sym + ("숏" if p.get("side") == "SHORT" else ""), pct))
        pnl = bn.get("pnl")
        out.append(("바이낸스", float(pnl) if pnl is not None else None, "USD", items))
    return out, at


# ───────────────────────── HTML ─────────────────────────
def _money(v, ccy):
    if v is None:
        return "-"
    if ccy == "KRW":
        return f"{v:+,.0f}원"
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def _cls(v):
    if v is None:
        return "z"
    return "p" if v > 0.005 else "m" if v < -0.005 else "z"


def _day_label(d):
    dt = datetime.strptime(d, "%Y-%m-%d")
    return f"{dt.month}/{dt.day}({WEEKDAY_KO[dt.weekday()]})"


def _pnl_rows_html(days, hist, by_day, fx, card_days):
    out = []
    for d in days:
        m = by_day.get(d) or {k: v for k, v in (hist.get(d) or {}).items() if k != "fx"}
        tot = _krw_total(m, fx)
        cells = "".join(f'<td class="{_cls(m.get(mk))}">{_money(m.get(mk), ccy)}</td>'
                        for mk, _l, ccy in MARKETS)
        has = d in card_days
        out.append(f'<tr data-day="{d}" class="{"go" if has else "nogo"}">'
                   f'<td class="d">{_day_label(d)}</td>'
                   f'<td class="t {_cls(tot)}">{_money(tot, "KRW")}</td>{cells}'
                   f'<td class="n">{len(card_days.get(d, [])) or ""}</td></tr>')
    return "".join(out)


def _month_rows_html(hist):
    months = {}
    for d, row in hist.items():
        mon = d[:7]
        fxd = row.get("fx")
        agg = months.setdefault(mon, {"tot": 0.0, "days": 0})
        tot = _krw_total(row, fxd)
        if tot is not None:
            agg["tot"] += tot
            agg["days"] += 1
        for mk, _l, _c in MARKETS:
            if row.get(mk) is not None:
                agg[mk] = agg.get(mk, 0.0) + row[mk]
    out = []
    for mon in sorted(months, reverse=True)[:12]:
        a = months[mon]
        cells = "".join(f'<td class="{_cls(a.get(mk))}">{_money(a.get(mk), ccy)}</td>'
                        for mk, _l, ccy in MARKETS)
        out.append(f'<tr><td class="d">{int(mon[5:7])}월 <span class="y">{mon[:4]}</span></td>'
                   f'<td class="t {_cls(a["tot"])}">{_money(a["tot"], "KRW")}</td>{cells}</tr>')
    return "".join(out)


def _hold_html(lines, at):
    if not lines:
        return ""
    out = []
    for label, total, ccy, items in lines:
        its = " ".join(f'<span class="hi">{sym}<i class="{_cls(p)}">'
                       f'{"" if p is None else f"({p:+.2f}%)"}</i></span>' for sym, p in items) or "-"
        tot = "-" if total is None else (f"{total:+,.0f}원" if ccy == "KRW" else f"{total:+,.2f}$")
        out.append(f'<div class="hold"><b>{label}:</b> <b class="{_cls(total)}">{tot}</b> {its}</div>')
    return ("".join(out) + f'<div class="note">보유 코인 = 스냅샷 {at} (코인 마스터 슬롯마다 갱신)</div>')


PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>날짜별 매매</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f7f6;--card:#fff;--line:#e5e7eb;--ink:#1f2937;--mute:#8a8f98;--p:#e11d48;--m:#2563eb;--sel:#fff7d6}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:'Segoe UI','Malgun Gothic',sans-serif;padding:12px 16px 40px}
.top{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.box{background:var(--card);border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.06);padding:10px 12px}
.box h2{font-size:13px;font-weight:700;margin-bottom:6px;display:flex;align-items:baseline;gap:8px}
.box h2 small{font-size:11px;font-weight:400;color:var(--mute)}
table{border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:12px}
th{font-size:11px;font-weight:600;color:var(--mute);text-align:right;padding:2px 8px;border-bottom:1px solid var(--line);font-family:'Segoe UI','Malgun Gothic',sans-serif}
th:first-child{text-align:left}
td{text-align:right;padding:3px 8px;white-space:nowrap}
td.d{text-align:left;font-family:'Segoe UI','Malgun Gothic',sans-serif;font-weight:600}
td.d .y{font-weight:400;color:var(--mute);font-size:10px}
td.t{font-weight:700}
td.n{color:var(--mute);font-size:11px}
.p{color:var(--p)}.m{color:var(--m)}.z{color:#b0b4ba}
tr.go{cursor:pointer}
tr.go:hover td{background:#f3f4f6}
tr.sel td{background:var(--sel)!important}
tr.nogo td.d{color:#b0b4ba}
.hold{font-size:12px;margin-top:4px;font-family:'JetBrains Mono',monospace}
.hold .hi{margin-right:6px}.hold i{font-style:normal}
.note{font-size:10.5px;color:var(--mute);margin-top:5px}
.dayhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:18px 0 4px}
.dayhead h1{font-size:17px}
.dayhead select{font-size:12px;padding:2px 6px;border:1px solid #ccc;border-radius:4px;background:#fff}
.dayhead .hint{font-size:11px;color:var(--mute)}
.sec{font-size:12.5px;font-weight:700;margin:16px 0 6px 2px;padding-left:7px;border-left:4px solid #888;display:flex;gap:8px;align-items:baseline}
.sec .st{font-weight:400;color:var(--mute);font-family:'JetBrains Mono',monospace;font-size:11.5px}
.sec .st b{font-weight:700}
.bigsec{font-size:14px;font-weight:700;margin:26px 0 2px;padding-top:10px;border-top:2px dashed #c4b5fd;color:#5b21b6}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.grid>.cc:nth-child(4n+2){margin-left:22px}
.cc{background:var(--card);border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;min-width:0}
.ct{padding:6px 10px;font-size:12.5px;border-bottom:1px solid #eee;display:flex;gap:6px;align-items:baseline;white-space:nowrap;cursor:pointer}
.ct:hover{background:#f9fafb}.ct:hover .nm{text-decoration:underline}
.ct .nm{font-weight:700;overflow:hidden;text-overflow:ellipsis}
.ct .cd{font-size:10px;color:#999;font-family:monospace}
.ct .bs{font-size:11px;color:#555;font-family:'JetBrains Mono',monospace}
.ct .pl{margin-left:auto;font-weight:700;font-family:'JetBrains Mono',monospace;font-size:11.5px}
.cc iframe{display:block;width:100%;height:300px;border:0}
.cc .nd{height:300px;display:flex;align-items:center;justify-content:center;color:#991b1b;font-size:12px}
.empty{color:var(--mute);font-size:13px;padding:30px 0}
@media (max-width:1100px) and (min-width:768px){.grid{grid-template-columns:repeat(2,1fr)}.grid>.cc:nth-child(4n+2){margin-left:0}}
@media (max-width:767px){
  body{padding:8px 10px 30px}
  .top{gap:10px}.box{width:100%;overflow-x:auto}
  table{font-size:11px}td,th{padding:3px 5px}
  .grid{grid-template-columns:1fr;gap:10px}.grid>.cc:nth-child(4n+2){margin-left:0}
  .cc iframe,.cc .nd{height:260px}
}
</style>
</head>
<body>
<div class="top">
  <div class="box">
    <h2>일별 손익 <small>최근 __NDAYS__일 · 수익금 칸 합계 · __FX__ · 주식은 주문접수 기준 · 날짜 누르면 아래 차트</small></h2>
    <table><thead><tr><th>날짜</th><th>합계</th><th>한국</th><th>미국</th><th>업비트</th><th>바낸</th><th>차트</th></tr></thead>
    <tbody>__DAYROWS__</tbody></table>
    __HOLD__
  </div>
  <div class="box">
    <h2>월별 집계 <small>날짜별 기록 누적 · 원화 합계는 그날 환율</small></h2>
    <table><thead><tr><th>월</th><th>합계</th><th>한국</th><th>미국</th><th>업비트</th><th>바낸</th></tr></thead>
    <tbody>__MONTHROWS__</tbody></table>
    <div class="note">__MONTHNOTE__</div>
  </div>
</div>

<div class="dayhead">
  <h1 id="dtitle"></h1>
  <select id="dsel"></select>
  <span class="hint">종목명 줄을 누르면 큰 차트(RSI 포함) · 차트 안은 휠=확대 드래그=이동 · 노란 띠 = 그날 봉</span>
</div>
<div id="cards"></div>
<div class="note" style="margin-top:20px">make_trade_daily_home.py · 생성 __NOW__</div>

<script>
var DATA=__DATA__, BOARDS=__BOARDS__;
var WD='일월화수목금토';
function dl(d){var t=new Date(d+'T00:00:00');return (t.getMonth()+1)+'/'+t.getDate()+'('+WD[t.getDay()]+')';}
function money(v,c){if(v==null)return '';if(c==='KRW')return (v>=0?'+':'')+Math.round(v).toLocaleString()+'원';
  return (v>=0?'+':'-')+'$'+Math.abs(v).toFixed(2);}
function cls(v){return v>0.005?'p':v<-0.005?'m':'z';}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function openBig(url,key){
  try{if(parent&&parent!==window&&parent.openBoardChart){parent.openBoardChart(url,key);return;}}catch(e){}
  location.href=url;}
function card(c,day){
  var bs='B'+c.nB+(c.nA?' A'+c.nA:'')+(c.nS?' S'+c.nS:'');
  var pl=c.nS?'<span class="pl '+cls(c.pnl)+'">'+money(c.pnl,c.ccy)+'</span>':'';
  var body=c.nodata?'<div class="nd">5분봉 데이터 없음</div>':
    '<iframe loading="lazy" src="'+c.url+'?card=1&focus='+day+'" title="'+esc(c.name)+'"></iframe>';
  return '<div class="cc"><div class="ct" onclick="openBig(\''+c.url+'\',\''+c.key+'\')">'+
    '<span class="nm">'+esc(c.name)+'</span>'+(c.code!==c.name?'<span class="cd">'+esc(c.code)+'</span>':'')+
    '<span class="bs">'+bs+'</span>'+pl+'</div>'+body+'</div>';
}
function render(day){
  var cs=DATA[day]||[],box=document.getElementById('cards'),html='',cur=null,grp=[],min5=false;
  document.getElementById('dtitle').textContent=day?('📅 '+dl(day)+' 매매차트 '+cs.length+'개'):'📅 매매차트';
  document.querySelectorAll('tr[data-day]').forEach(function(r){r.classList.toggle('sel',r.getAttribute('data-day')===day);});
  var sel=document.getElementById('dsel');if(sel.value!==day)sel.value=day;
  function flush(){
    if(!grp.length)return;var b=BOARDS[cur]||{label:cur,color:'#888'},w=0,l=0;
    grp.forEach(function(c){if(c.nS){if(c.pnl>0)w++;else if(c.pnl<0)l++;}});
    html+='<div class="sec" style="border-left-color:'+b.color+'">📌 '+esc(b.label)+
      ' <span class="st">'+grp.length+(w||l?' · <b class="p">익'+w+'</b>/<b class="m">손'+l+'</b>':'')+'</span></div>'+
      '<div class="grid">'+grp.map(function(c){return card(c,day);}).join('')+'</div>';
    grp=[];}
  cs.forEach(function(c){
    if(c.kind==='5min'&&!min5){flush();min5=true;html+='<div class="bigsec">5분봉 메뉴</div>';}
    if(c.key!==cur){flush();cur=c.key;}
    grp.push(c);});
  flush();
  box.innerHTML=html||'<div class="empty">이 날짜엔 차트로 볼 매매가 없습니다.</div>';
  try{history.replaceState(null,'','#'+day);}catch(e){}
}
(function(){
  var days=Object.keys(DATA).sort().reverse(),sel=document.getElementById('dsel');
  sel.innerHTML=days.map(function(d){return '<option value="'+d+'">'+dl(d)+' · '+DATA[d].length+'개</option>';}).join('');
  sel.onchange=function(){render(sel.value);};
  document.querySelectorAll('tr.go').forEach(function(r){r.onclick=function(){render(r.getAttribute('data-day'));
    document.getElementById('dtitle').scrollIntoView({behavior:'smooth',block:'start'});};});
  var h=(location.hash||'').slice(1);
  render(DATA[h]?h:(days[0]||''));
})();
</script>
</body>
</html>
"""


def build(day_cards, boards):
    """day_cards = make_trade_chart_boards.DAY_CARDS, boards = BOARDS. → OUT_HTML 경로."""
    now = datetime.now()
    try:
        by_day, fx = master_pnl_by_day()
    except Exception as e:                       # noqa: BLE001 - 손익표가 죽어도 차트는 나온다
        print(f"     [WARN] MASTER 손익 집계 실패: {type(e).__name__}: {e}")
        by_day, fx = {}, None
    hist = update_history(by_day, fx, now) if by_day else _load_history()
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(PNL_DAYS - 1, -1, -1)]
    first = min(hist) if hist else ""
    month_note = (f"기록 시작 {first} — 그 전 달은 일부 시장만 있다(봇 로그가 남아 있는 범위)."
                  if first else "기록 없음")
    holds, hat = hold_lines()
    board_meta = {b["key"]: {"label": b["label"], "color": b["color"]} for b in boards}
    html = (PAGE
            .replace("__NDAYS__", str(PNL_DAYS))
            .replace("__FX__", f"$1={fx:,.0f}원" if fx else "환율 없음")
            .replace("__DAYROWS__", _pnl_rows_html(days, hist, by_day, fx, day_cards))
            .replace("__MONTHROWS__", _month_rows_html(hist))
            .replace("__MONTHNOTE__", month_note)
            .replace("__HOLD__", _hold_html(holds, hat))
            .replace("__NOW__", now.strftime("%Y-%m-%d %H:%M"))
            .replace("__BOARDS__", json.dumps(board_meta, ensure_ascii=False))
            .replace("__DATA__", json.dumps(day_cards, ensure_ascii=False, separators=(",", ":"))))
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    n = sum(len(v) for v in day_cards.values())
    print(f"     날짜별   : {os.path.basename(OUT_HTML)} ({len(day_cards)}일 / 카드 {n}개, 손익 {len(hist)}일 기록)")
    return OUT_HTML
