# asset_donut.py
# 투자비중 + 통화비중 도넛 카드를 서버사이드(파이썬)로 렌더링.
#   원본은 holdings.html 의 JS(computeAssetParts / currencyBuckets / renderDonutCard).
#   holdings.html 은 계좌 탭이 있는 SPA 라 JS 로 남기고, 정적 게시판용으로 이 모듈을 쓴다.
#   ★ 어느 한쪽 산식·색상·지오메트리를 고치면 반드시 다른 쪽도 같이 고칠 것.
#
# 입력: report-us/holdings_{계좌}.json  (make_holdings_json.py 산출물)
# 출력: build_card_html() → 카드 HTML 문자열 / CSS 는 DONUT_CSS 를 페이지 CSS 에 붙일 것.

import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parent

# 3계좌 합산. 자녀계좌(8458/1943)는 제외 — holdings.html 의 COMBINED_DONUT_ACCS 와 동일.
COMBINED_ACCOUNTS = ("1887", "8042", "2773")

INVEST_COLORS = {"kr": "#4a7ac7", "us": "#e74c3c", "jp": "#f1c40f", "cash": "#bdc3c7"}
CURRENCY_COLORS = {"KR": "#4a7ac7", "US": "#e74c3c", "JP": "#f1c40f", "ETC": "#27ae60"}
# 링 바깥 글자용. 노랑은 흰 배경에서 안 보여 어둡게 낮춘다.
CURRENCY_LABEL_COLORS = {"KR": "#4a7ac7", "US": "#e74c3c", "JP": "#b7930b", "ETC": "#27ae60"}

# 도넛 링 지오메트리 — 가운데 홀 지름이 도넛 지름의 35% (= r±sw/2 → 바깥 49, 안쪽 17.15)
R, SW, CX, CY = 33.075, 31.85, 50, 50
C = 2 * math.pi * R
MIN_INSIDE_PCT = 7      # 이보다 얇은 조각은 글자가 안 들어가 링 바깥에 표기


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_account(acc, base=None):
    p = (base or BASE) / f"holdings_{acc}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if d.get("success") else None


def compute_parts(summ, us_summ):
    """자산 분해. 투자비중·통화비중 두 도넛이 이 하나를 같이 쓴다 → 분모(total)가 반드시 일치한다.

    KR: 국내주식 평가 + 원화 예수금.
        원화예수금은 kt00001.entr(D+0)가 아니라 kt00003 추정예탁자산에서 역산한다.
        추정예탁자산은 D+2 정산 반영이라 '오늘 판 주식'이 평가액에서 빠진 뒤 현금으로
        들어오기 전 2일 공백을 이미 메워준다(= 매도대금 미수금 포함).
    US: 미국주식(ust21070 합) + 달러예수금(ust21120 USD 줄).
    JP: ust21120 의 USD 외 통화 줄. 통합증거금으로 매수하면 그 통화 예수금이 음수가 되므로
        예수금과 주식평가를 같이 봐야 순포지션이 된다.
        ※ 일본 보유는 ust21070(해외잔고)에 안 나오고 ust21120 JPY 줄에만 존재한다.
        ※ jp_invest 는 'USD 외 통화 주식평가' 전체다. 현재 실보유는 일본뿐이라 JP 로 표기한다.
    """
    summ = summ or {}
    us = us_summ or {}
    kr_invest = _num(summ.get("tot_evlt_amt"))
    kr_total = _num(summ.get("total_asset"))
    kr_cash = max(kr_total - kr_invest, 0.0) if kr_total > 0 else _num(summ.get("cash"))
    us_invest = _num(us.get("us_stock_krw"))
    us_cash = _num(us.get("usd_cash_krw"))
    fx_net = _num(us.get("fx_other_krw"))            # USD 외 통화 순자산
    jp_invest = _num(us.get("fx_other_stock_krw"))   # 그중 주식평가
    fx_cash = fx_net - jp_invest                     # 그중 예수금(음수 가능)
    jpy = (us.get("fx") or {}).get("JPY") or {}
    jp_net = _num(jpy.get("cash_krw")) + _num(jpy.get("stock_krw"))
    return {
        "kr_invest": kr_invest, "us_invest": us_invest, "jp_invest": jp_invest,
        "kr_cash": kr_cash, "us_cash": us_cash, "fx_cash": fx_cash,
        "cash": kr_cash + us_cash + fx_cash,
        "jp_net": jp_net, "etc_net": fx_net - jp_net,
        "total": kr_invest + us_invest + kr_cash + us_cash + fx_net,
    }


def combined_parts(accounts=COMBINED_ACCOUNTS, base=None):
    """계좌별 분해를 합산. 조회 실패한 계좌는 조용히 건너뛴다."""
    tot = {k: 0.0 for k in (
        "kr_invest", "us_invest", "jp_invest", "kr_cash", "us_cash", "fx_cash",
        "cash", "jp_net", "etc_net", "total")}
    ok = []
    for acc in accounts:
        d = load_account(acc, base)
        if not d:
            continue
        p = compute_parts(d.get("summary"), d.get("us_summary"))
        for k in tot:
            tot[k] += p[k]
        ok.append(acc)
    return tot, ok


def _seg(length, offset, color):
    return (f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="transparent" stroke="{color}" '
            f'stroke-width="{SW}" stroke-dasharray="{length:.4f} {C - length:.4f}" '
            f'stroke-dashoffset="{-offset:.4f}"></circle>')


def _mid_point(mid_pct, radius):
    """조각 중앙 좌표. svg 를 통째로 돌리는 대신 각도에서 -90 을 빼서 글자는 똑바로 세운다."""
    a = (mid_pct / 100.0) * 2 * math.pi - math.pi / 2
    return CX + radius * math.cos(a), CY + radius * math.sin(a)


def _slice_label(mid_pct, label, pct):
    x, y = _mid_point(mid_pct, R)
    return (f'<text class="adn-lbl" x="{x:.2f}" y="{y - 4.5:.2f}">{label}</text>'
            f'<text class="adn-lbl" x="{x:.2f}" y="{y + 4.5:.2f}">{round(pct)}%</text>')


def _donut(slices, title, hole_text="", label_colors=None):
    """slices = [(pct, color, label), ...]. 얇은 조각은 링 바깥 HTML 오버레이로 뺀다."""
    acc, segs, labels, outside = 0.0, "", "", ""
    for pct, color, label in slices:
        if pct <= 0:
            continue
        segs += _seg((pct / 100.0) * C, (acc / 100.0) * C, color)
        mid = acc + pct / 2
        if pct >= MIN_INSIDE_PCT:
            labels += _slice_label(mid, label, pct)
        else:
            x, y = _mid_point(mid, 55)
            col = (label_colors or {}).get(label, color)
            outside += (f'<span class="adn-out" style="left:{x:.2f}%; top:{y:.2f}%; color:{col};">'
                        f'{label} {round(pct)}%</span>')
        acc += pct
    center = f'<div class="adn-center"><div class="adn-num">{hole_text}</div></div>' if hole_text else ""
    return (
        f'<div class="adn-unit">'
        f'<div class="adn-title">{title}</div>'
        f'<div class="adn-wrap">'
        f'<svg viewBox="0 0 100 100">'
        f'<g transform="rotate(-90 {CX} {CY})">'
        f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="transparent" stroke="#f1f1f1" stroke-width="{SW}"></circle>'
        f'{segs}</g>{labels}</svg>{center}{outside}</div></div>'
    )


def _man(v):
    """원 → '#,###만'"""
    return f"{round(v / 10000):,}만"


def build_card_html(accounts=COMBINED_ACCOUNTS, base=None):
    """투자비중 + 통화비중 도넛 카드. 데이터가 없으면 빈 문자열."""
    p, ok = combined_parts(accounts, base)
    total = p["total"]
    if not ok or total <= 0:
        return ""

    kr_pct = p["kr_invest"] / total * 100
    us_pct = p["us_invest"] / total * 100
    jp_pct = p["jp_invest"] / total * 100 if p["jp_invest"] > 0 else 0.0
    cash_pct = max(100 - kr_pct - us_pct - jp_pct, 0.0)
    invested_pct = min(kr_pct + us_pct + jp_pct, 100.0)

    invest_slices = [(kr_pct, INVEST_COLORS["kr"], "KR"), (us_pct, INVEST_COLORS["us"], "US")]
    if jp_pct > 0:
        invest_slices.append((jp_pct, INVEST_COLORS["jp"], "JP"))
    invest_slices.append((cash_pct, INVEST_COLORS["cash"], "현금"))

    # 통화비중은 위 분해를 다시 묶기만 하므로 총액이 투자비중과 같다.
    # 순마이너스 통화는 조각을 그릴 수 없어 0 으로 눕힌다.
    cur = {
        "KR": max(p["kr_invest"] + p["kr_cash"], 0.0),
        "US": max(p["us_invest"] + p["us_cash"], 0.0),
        "JP": max(p["jp_net"], 0.0),
        "ETC": max(p["etc_net"], 0.0),
    }
    cur_slices = [(cur[k] / total * 100, CURRENCY_COLORS[k], k) for k in ("KR", "US", "JP", "ETC")]

    def row(color, name, pct, amt):
        return (f'<div class="adn-row"><span class="adn-name">'
                f'<span class="adn-dot" style="background:{color}"></span>{name}</span>'
                f'<span class="adn-val">{pct:.1f}%</span>'
                f'<span class="adn-amt">{_man(amt)}</span></div>')

    legend = row(INVEST_COLORS["kr"], "KR 투자", kr_pct, p["kr_invest"])
    legend += row(INVEST_COLORS["us"], "US 투자", us_pct, p["us_invest"])
    if jp_pct > 0:
        legend += row(INVEST_COLORS["jp"], "JP 투자", jp_pct, p["jp_invest"])
    legend += row(INVEST_COLORS["cash"], "현금", cash_pct, p["cash"])
    # 총자산 = 위 조각들의 합. dot 은 자리만 맞추고 색은 없앤다(조각이 아니므로).
    legend += ('<div class="adn-row adn-total"><span class="adn-name">'
               '<span class="adn-dot" style="background:transparent"></span>총자산</span>'
               f'<span class="adn-val"></span><span class="adn-amt">{_man(total)}</span></div>')

    return (
        '<div class="adn-card">'
        '<div class="adn-top">'
        + _donut(invest_slices, "💹 투자비중", hole_text=f"{invested_pct:.0f}%")
        + _donut(cur_slices, "💱 통화비중", label_colors=CURRENCY_LABEL_COLORS)
        + '</div>'
        f'<div class="adn-legend">{legend}</div>'
        '</div>'
    )


DONUT_CSS = r"""
/* ── 투자비중/통화비중 도넛 카드 (asset_donut.py) ── */
.adn-card { background:#fff; padding:14px; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1); box-sizing:border-box; width:300px; max-width:100%; }
.adn-top { display:flex; align-items:flex-start; justify-content:center; gap:8px; margin-bottom:8px; }
.adn-unit { display:flex; flex-direction:column; align-items:center; flex:0 0 auto; }
.adn-title { font-weight:bold; color:#2c3e50; font-size:0.85rem; line-height:1.3; margin-bottom:13px; white-space:nowrap; }
.adn-wrap { position:relative; width:126px; height:126px; flex:0 0 auto; }
.adn-wrap svg { width:100%; height:100%; }
.adn-lbl { font-size:8px; font-weight:bold; fill:#fff; text-anchor:middle; dominant-baseline:central; }
.adn-out { position:absolute; transform:translate(-50%,-50%); font-size:0.58rem; font-weight:bold; white-space:nowrap; pointer-events:none; }
.adn-center { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; pointer-events:none; }
.adn-num { font-size:0.9rem; font-weight:bold; color:#2c3e50; }
.adn-legend { font-size:0.9rem; border-top:1px solid #f1f1f1; padding-top:6px; }
.adn-row { display:grid; grid-template-columns:78px minmax(0,1fr) minmax(0,1fr); align-items:baseline; padding:3px 0; column-gap:6px; }
.adn-name { display:flex; align-items:center; color:#555; }
.adn-dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px; flex:0 0 auto; }
.adn-val { font-weight:bold; color:#2c3e50; white-space:nowrap; text-align:right; }
.adn-amt { color:#2c3e50; white-space:nowrap; text-align:right; font-size:0.86rem; }
.adn-total .adn-name, .adn-total .adn-amt { font-weight:bold; }
"""


if __name__ == "__main__":
    parts, accs = combined_parts()
    print("계좌:", accs)
    for k, v in parts.items():
        print(f"  {k:<10} {v:>15,.0f}")
