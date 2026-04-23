"""기상청 중기예보 (data.go.kr 15059468, MidFcstInfoService) — D+3 ~ D+10.

부산 전역 단일 예보 (regId=11H20000 육상 / stnId=11H20201 기온).
격자 불가, 광역 단위. 발표 시각: 06:00, 18:00 (하루 2회).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from sources._gov_api import call_api

SOURCE = "weather_kma_mid"
API_ID = "15059468"
OP_LAND = "getMidLandFcst"
OP_TA = "getMidTa"

REG_LAND = "11H20000"  # 부산·울산·경남
STN_TA = "11H20201"    # 부산

KST = timezone(timedelta(hours=9))


def _latest_tm_fc() -> str:
    """가장 최근 발표 tmFc (YYYYMMDDHHMM). 06/18시 발표."""
    now = datetime.now(KST) - timedelta(minutes=30)
    base = now.replace(minute=0, second=0, microsecond=0)
    if base.hour >= 18:
        base = base.replace(hour=18)
    elif base.hour >= 6:
        base = base.replace(hour=6)
    else:
        base = (base - timedelta(days=1)).replace(hour=18)
    return base.strftime("%Y%m%d%H%M")


def upsert_forecasts(conn: sqlite3.Connection) -> int:
    """중기예보 수집 (승인 전에는 PENDING SKIP)."""
    tm_fc = _latest_tm_fc()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    r_land = call_api(API_ID, OP_LAND, pageNo=1, numOfRows=10, regId=REG_LAND, tmFc=tm_fc, dataType="JSON")
    if r_land["result_code"] == "PENDING":
        print(f"[{SOURCE}] SKIP: {r_land['result_msg']}", file=sys.stderr)
        return 0
    r_ta = call_api(API_ID, OP_TA, pageNo=1, numOfRows=10, regId=STN_TA, tmFc=tm_fc, dataType="JSON")

    land_items = r_land.get("items", [])
    ta_items = r_ta.get("items", [])
    if not land_items or not ta_items:
        print(f"[{SOURCE}] no items", file=sys.stderr)
        return 0
    land = land_items[0]
    ta = ta_items[0]

    # D+3 ~ D+10 (API 응답은 수준별 필드: wf3Am/wf3Pm/...Wf10, taMin3/taMax3/...)
    today = datetime.now(KST).date()
    rows = 0
    for d in range(3, 11):
        date = today + timedelta(days=d)
        ts = f"{date.strftime('%Y%m%d')}T12:00"
        tmp_min = ta.get(f"taMin{d}")
        tmp_max = ta.get(f"taMax{d}")
        tmp = None
        try:
            if tmp_min is not None and tmp_max is not None:
                tmp = (float(tmp_min) + float(tmp_max)) / 2
        except (TypeError, ValueError):
            pass
        # 하늘상태 매핑: "맑음"/"구름많음"/"흐림" etc.
        wf = land.get(f"wf{d}Pm") if d <= 7 else land.get(f"wf{d}")
        sky = 1 if wf and "맑음" in wf else 3 if wf and "구름" in wf else 4 if wf and "흐림" in wf else None
        pty = 1 if wf and ("비" in wf or "소나기" in wf) else 3 if wf and "눈" in wf else 0
        pop = land.get(f"rnSt{d}Pm") if d <= 7 else land.get(f"rnSt{d}")
        try:
            pop = int(pop) if pop is not None else None
        except (TypeError, ValueError):
            pop = None

        # 격자 표기는 부산 대표(98,76) — 중기는 광역값이라 동일 좌표에 씀
        conn.execute(
            """INSERT OR REPLACE INTO weather_fcst
               (nx, ny, fcst_ts, source, tmp, pty, sky, pop, reh, wsd, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (98, 76, ts, "mid", tmp, pty, sky, pop, None, None, now),
        )
        rows += 1
    conn.commit()
    return rows


def fetch() -> list:
    from config import DB_PATH
    from storage.db import connect
    conn = connect(DB_PATH)
    n = upsert_forecasts(conn)
    print(f"[{SOURCE}] rows={n}", file=sys.stderr)
    return []


if __name__ == "__main__":
    fetch()
