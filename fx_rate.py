# fx_rate.py
# 환율 단일 원천. bat 앞단에서 `python -X utf8 fx_rate.py --save` 1회 실행 →
# report-us/fx_rate.json 갱신. 게시판 생성기들은 get_usdkrw() 로 파일만 읽는다(API 무호출).
#
#   저장:  python -X utf8 D:\py\report-us\fx_rate.py --save
#   사용:  from fx_rate import get_usdkrw
#          USD_KRW = get_usdkrw(1450)
#
# 조회 순서: ust21120(계좌 적용환율 crnc_rt) → ust31301(시장 기준환율).
# 실패해도 예외를 던지지 않는다 — 게시판 생성이 환율 때문에 죽으면 안 되므로
# 소비처는 fallback 으로 계속 진행한다(단, 콘솔에 경고를 남긴다).
#
# ※ 고정 환율을 의도적으로 쓰는 곳은 여기로 옮기지 말 것:
#   jasantop4_global_softcap.LIQ_USD_KRW / lev2_order_overlay.LIQ2_USD_KRW
#   → 유동성 게이트 '문턱 기준선'이라 환율 따라 흔들리면 종목이 깜빡인다.

import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
FX_FILE = BASE / "fx_rate.json"

# 이 시간 넘게 묵은 값은 신뢰하지 않고 fallback 을 쓴다(주말·bat 미실행 대비 넉넉히).
MAX_AGE_SEC = 24 * 3600


# ────────────────────────────── 읽기 (게시판용) ──────────────────────────────
def load(quiet=False):
    """저장된 환율 dict 반환. 없거나 만료면 None."""
    try:
        d = json.loads(FX_FILE.read_text(encoding="utf-8"))
    except Exception:
        if not quiet:
            print(f"⚠ 환율 캐시 없음: {FX_FILE}")
        return None
    age = time.time() - float(d.get("ts") or 0)
    if age > MAX_AGE_SEC:
        if not quiet:
            print(f"⚠ 환율 캐시 만료({age / 3600:.1f}시간 경과, {d.get('asof')})")
        return None
    return d


def _get(key, fallback, quiet):
    d = load(quiet=quiet)
    if not d:
        if not quiet:
            print(f"  → fallback {fallback} 사용")
        return float(fallback)
    v = d.get(key)
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = 0.0
    if v <= 0:
        if not quiet:
            print(f"⚠ 환율 캐시에 {key} 없음 → fallback {fallback} 사용")
        return float(fallback)
    return v


def get_usdkrw(fallback=1450.0, quiet=False):
    return _get("usdkrw", fallback, quiet)


def get_jpykrw(fallback=900.0, quiet=False):
    """100엔당 원. 키움 crnc_rt 가 100엔 기준으로 내려온다."""
    return _get("jpykrw", fallback, quiet)


# ────────────────────────────── 쓰기 (bat 앞단 1회) ──────────────────────────────
def _fetch():
    """키움 API 로 환율 조회. (usdkrw, jpykrw, source) 반환, 실패 시 (None, None, 사유)."""
    import requests
    from dotenv import load_dotenv

    load_dotenv()
    BASE_DOMAIN = "https://api.kiwoom.com"

    app_key = os.getenv("KIWOOM_APP_KEY_8042")
    secret_key = os.getenv("KIWOOM_SECRET_KEY_8042")
    if not app_key or not secret_key:
        return None, None, "8042 API 키 없음"

    res = requests.post(
        BASE_DOMAIN + "/oauth2/token",
        headers={"Content-Type": "application/json;charset=UTF-8"},
        data=json.dumps({
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": secret_key,
        }),
        timeout=10,
    )
    res.raise_for_status()
    token = res.json().get("token")
    if not token:
        return None, None, "토큰 발급 실패"

    def call(api_id, payload):
        r = requests.post(
            BASE_DOMAIN + "/api/us/acnt",
            headers={
                "api-id": api_id,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json;charset=UTF-8",
            },
            data=json.dumps(payload),
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        if d.get("return_code") not in (0, "0", None):
            raise RuntimeError(f"{api_id} 실패: {d.get('return_msg', d)}")
        return d

    def num(v):
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return 0.0

    usd = jpy = 0.0
    try:
        for row in call("ust21120", {}).get("result_list") or []:
            crnc = str(row.get("crnc_code", "")).upper()
            rate = num(row.get("crnc_rt"))
            if rate <= 0:
                continue
            if crnc == "USD":
                usd = rate
            elif crnc == "JPY":
                jpy = rate
    except Exception as e:
        print(f"  ⚠ ust21120 조회 실패: {e}")

    if usd > 0:
        return usd, (jpy or None), "ust21120"

    # 폴백: 시장 기준환율. 계좌에 달러 줄이 아예 없을 때(예: 잔고 0) 대비.
    try:
        d = call("ust31301", {"exch_tp": "1"})
        for row in d.get("result_list") or [d]:
            if str(row.get("crnc_code", "")).upper() in ("USD", ""):
                rate = num(row.get("bas_exrt") or row.get("crnc_rt"))
                if rate > 0:
                    return rate, (jpy or None), "ust31301"
    except Exception as e:
        print(f"  ⚠ ust31301 조회 실패: {e}")

    return None, None, "USD 환율 확보 실패"


def save():
    """조회 후 fx_rate.json 저장. 실패하면 기존 파일을 건드리지 않는다."""
    try:
        usd, jpy, src = _fetch()
    except Exception as e:
        usd, jpy, src = None, None, str(e)

    if not usd:
        print(f"❌ 환율 저장 실패({src}) → 기존 캐시 유지")
        old = load(quiet=True)
        if old:
            print(f"   기존값: USD {old.get('usdkrw')} ({old.get('asof')})")
        return False

    now = time.time()
    data = {
        "usdkrw": round(usd, 2),
        "jpykrw": round(jpy, 2) if jpy else None,   # 100엔당 원
        "source": src,
        "ts": now,
        "asof": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
    }
    FX_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 환율 저장: USD {data['usdkrw']} / JPY(100) {data['jpykrw']} [{src}] → {FX_FILE.name}")
    return True


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--save" in sys.argv:
        sys.exit(0 if save() else 0)   # 실패해도 bat 을 멈추지 않는다
    d = load()
    print(json.dumps(d, ensure_ascii=False, indent=2) if d else "(캐시 없음/만료)")
