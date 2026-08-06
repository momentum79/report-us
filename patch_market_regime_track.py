"""
patch_market_regime_track.py
────────────────────────────────────────────────────────────────────
역할:
  1) [요청1] top3_etf_track_total.json의 sco_zone_* 값을
             market_regime_track_total.json의 sco_strong/mid/weak/neg에 병합
  2) [요청2] QQQ 가격 수동 입력값을 market_regime_track_total.json에 채워넣기

실행 위치: D:\\py\\report-us\\ 폴더에 복사 후 실행
────────────────────────────────────────────────────────────────────
"""

import json
import math
from pathlib import Path

# ── 파일 경로 ──────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent

TRACK_FILE  = BASE / "market_regime_track_total.json"   # 리스트 형태
TOP3_FILE   = BASE / "top3_etf_track_total.json"        # 딕셔너리 형태

# ── [요청2] 수동 QQQ 가격 입력 ─────────────────────────────────────
# 형식: "YYYY-MM-DD": 종가
MANUAL_QQQ = {
    "2026-03-27": 562.58,
    "2026-03-28": None,       # 주말/휴장 → None 유지 (market_regime에 없는 날)
    "2026-03-29": None,       # 주말
    "2026-03-30": 558.28,
    "2026-03-31": 577.18,
    "2026-04-01": 584.31,
    "2026-04-02": 584.98,
    "2026-04-03": None,       # 주말
    "2026-04-04": None,       # 주말
    "2026-04-05": None,       # 주말 (일부 날짜는 market_regime에 있을 수도 있으므로 None 처리)
    "2026-04-06": 588.50,
    # 2026-04-07은 이미 들어가 있음 (588.5)
}

# ── [요청1] top3 → regime 필드 매핑 ───────────────────────────────
# top3_etf_track_total.json    →   market_regime_track_total.json
# sco_zone_strong              →   sco_strong
# sco_zone_mid                 →   sco_mid
# sco_zone_weak                →   sco_weak
# sco_zone_neg                 →   sco_neg
ZONE_MAP = {
    "sco_zone_strong": "sco_strong",
    "sco_zone_mid":    "sco_mid",
    "sco_zone_weak":   "sco_weak",
    "sco_zone_neg":    "sco_neg",
}

def is_nan(v):
    """NaN 또는 None 체크"""
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def main():
    # ── 파일 로드 ──────────────────────────────────────────────────
    if not TRACK_FILE.exists():
        print(f"❌ 파일 없음: {TRACK_FILE}")
        return
    if not TOP3_FILE.exists():
        print(f"❌ 파일 없음: {TOP3_FILE}")
        return

    with open(TRACK_FILE, "r", encoding="utf-8") as f:
        regime_list = json.load(f)   # list of dict

    with open(TOP3_FILE, "r", encoding="utf-8") as f:
        top3_dict = json.load(f)     # dict keyed by date string

    # ── 패치 카운터 ────────────────────────────────────────────────
    zone_patched  = 0
    qqq_patched   = 0

    for entry in regime_list:
        date = entry.get("date", "")

        # ── [요청1] sco_zone 병합 ──────────────────────────────────
        if date in top3_dict:
            top3 = top3_dict[date]
            for top3_key, regime_key in ZONE_MAP.items():
                top3_val = top3.get(top3_key)
                # top3에 값이 있고, regime에는 NaN/None인 경우만 덮어쓰기
                if not is_nan(top3_val) and is_nan(entry.get(regime_key)):
                    entry[regime_key] = int(top3_val)
                    zone_patched += 1

        # ── [요청2] QQQ 가격 병합 ─────────────────────────────────
        if date in MANUAL_QQQ:
            qqq_val = MANUAL_QQQ[date]
            if qqq_val is not None and is_nan(entry.get("QQQ_close")):
                entry["QQQ_close"] = qqq_val
                qqq_patched += 1

    # ── 저장 ───────────────────────────────────────────────────────
    # NaN → null 변환을 위해 custom encoder 사용
    class NaNEncoder(json.JSONEncoder):
        def iterencode(self, o, _one_shot=False):
            # float NaN → null 치환
            chunks = super().iterencode(o, _one_shot)
            for chunk in chunks:
                yield chunk.replace("NaN", "null")

    out_path = TRACK_FILE   # 원본 덮어쓰기
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(regime_list, f, ensure_ascii=False, indent=2, cls=NaNEncoder)

    print(f"✅ 패치 완료 → {out_path}")
    print(f"   [요청1] sco_zone 필드 패치: {zone_patched}건")
    print(f"   [요청2] QQQ_close 필드 패치: {qqq_patched}건")

    # ── 결과 확인: 패치된 날짜 출력 ───────────────────────────────
    print("\n[확인] sco_zone 값이 채워진 날짜:")
    for entry in regime_list:
        if not is_nan(entry.get("sco_strong")):
            print(f"  {entry['date']}  strong={entry.get('sco_strong')}  "
                  f"mid={entry.get('sco_mid')}  "
                  f"weak={entry.get('sco_weak')}  "
                  f"neg={entry.get('sco_neg')}")

    print("\n[확인] QQQ_close가 채워진 최근 10개 날짜:")
    filled_qqq = [e for e in regime_list if not is_nan(e.get("QQQ_close"))]
    for entry in filled_qqq[-10:]:
        print(f"  {entry['date']}  QQQ={entry.get('QQQ_close')}")


if __name__ == "__main__":
    main()
