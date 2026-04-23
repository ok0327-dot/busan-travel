"""한국환경공단 대기오염정보 (data.go.kr 15073861, ArpltnInforInqireSvc).

부산 전역 측정소 + 시간별 PM10/PM2.5/O3 등. 측정소 좌표는 15073877 로 별도 조회 (TM→WGS84 변환 필요).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from sources._gov_api import call_api

SOURCE = "air_korea"
API_ID_AIR = "15073861"
OP_RT = "getCtprvnRltmMesureDnsty"  # 실시간 측정
API_ID_STN = "15073877"
OP_STN = "getMsrstnList"

KST = timezone(timedelta(hours=9))


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def seed_stations(conn: sqlite3.Connection) -> int:
    """부산 측정소 목록 → air_station 테이블. TM(EPSG:5174) → WGS84 는 pyproj 필요.

    pyproj 없으면 lat/lon 은 None 으로 두고, 이름으로만 저장.
    Kakao Geocoder 로 addr 좌표 해소하는 걸 fallback 으로.
    """
    r = call_api(API_ID_STN, OP_STN, pageNo=1, numOfRows=200, addr="부산")
    if r["result_code"] == "PENDING":
        print(f"[{SOURCE}] station SKIP: {r['result_msg']}", file=sys.stderr)
        return 0
    try:
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    except ImportError:
        tr = None
        print(f"[{SOURCE}] pyproj 없음 — TM 변환 스킵", file=sys.stderr)

    rows = 0
    for it in r.get("items", []):
        tm_x = _to_float(it.get("dmX"))
        tm_y = _to_float(it.get("dmY"))
        lat = lon = None
        if tr and tm_x and tm_y:
            lon, lat = tr.transform(tm_x, tm_y)
        conn.execute(
            """INSERT OR REPLACE INTO air_station (code, name, sido, addr, lat, lon, tm_x, tm_y)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                it.get("stationName") or "",
                it.get("stationName") or "",
                "부산",
                it.get("addr"),
                lat, lon, tm_x, tm_y,
            ),
        )
        rows += 1
    conn.commit()
    return rows


def fetch_air_quality(conn: sqlite3.Connection) -> int:
    r = call_api(API_ID_AIR, OP_RT, pageNo=1, numOfRows=200, sidoName="부산", ver="1.3", returnType="json")
    if r["result_code"] == "PENDING":
        print(f"[{SOURCE}] SKIP: {r['result_msg']}", file=sys.stderr)
        return 0
    rows = 0
    for it in r.get("items", []):
        station = it.get("stationName")
        ts = it.get("dataTime")  # 'YYYY-MM-DD HH:mm'
        if not station or not ts:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO air_quality
               (station, ts, pm10, pm25, o3, no2, so2, co, grade_pm10, grade_pm25)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                station, ts,
                _to_int(it.get("pm10Value")),
                _to_int(it.get("pm25Value")),
                _to_float(it.get("o3Value")),
                _to_float(it.get("no2Value")),
                _to_float(it.get("so2Value")),
                _to_float(it.get("coValue")),
                _to_int(it.get("pm10Grade")),
                _to_int(it.get("pm25Grade")),
            ),
        )
        rows += 1
    conn.commit()
    return rows


def fetch() -> list:
    from config import DB_PATH
    from storage.db import connect
    conn = connect(DB_PATH)
    stations = seed_stations(conn)
    aq = fetch_air_quality(conn)
    print(f"[{SOURCE}] stations={stations}, aq_rows={aq}", file=sys.stderr)
    return []


if __name__ == "__main__":
    fetch()
