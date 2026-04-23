"""기상청 단기예보 (data.go.kr 15084084, VilageFcstInfoService_2.0) — getVilageFcst.

부산 내 distinct (nx, ny) 격자를 순회하며 3시간 간격 예보를 weather_fcst 테이블에 적재.
발표 시각(base_time): 02/05/08/11/14/17/20/23 (총 8회), 매 시각 +10분 이후 제공.
커버리지: 발표 기준 +3일 예보 (단기).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from sources._gov_api import call_api

SOURCE = "weather_kma_short"
API_ID = "15084084"
OP = "getVilageFcst"

# 단기예보 발표 시각 (KST). 데이터 안정 시간 여유 10분 이상 둠.
BASE_TIMES = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]

# 관심 카테고리: TMP(1시간기온), SKY(하늘), PTY(강수형태), POP(강수확률), REH(습도), WSD(풍속)
CATEGORIES = {"TMP", "SKY", "PTY", "POP", "REH", "WSD"}

KST = timezone(timedelta(hours=9))


def _latest_base() -> tuple[str, str]:
    """현재 KST 기준 가용 base_date + base_time 반환."""
    now = datetime.now(KST) - timedelta(minutes=15)  # 안정 시간 여유
    hm = now.strftime("%H%M")
    for bt in reversed(BASE_TIMES):
        if hm >= bt:
            return now.strftime("%Y%m%d"), bt
    # 새벽 02:00 이전이면 전날 23:00
    y = now - timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def fetch_grid(nx: int, ny: int, base_date: str, base_time: str) -> dict:
    """단일 격자의 3일치 예보 → {fcst_ts: {TMP,SKY,PTY,POP,REH,WSD}}."""
    forecasts: dict[str, dict] = {}
    page = 1
    while True:
        r = call_api(
            API_ID, OP,
            pageNo=page, numOfRows=1000,
            base_date=base_date, base_time=base_time,
            nx=nx, ny=ny, dataType="JSON",
        )
        code = r["result_code"]
        if code == "PENDING":
            print(f"[{SOURCE}] SKIP: {r['result_msg']}", file=sys.stderr)
            return forecasts
        if code != "00":
            print(f"[{SOURCE}] ({nx},{ny}) err={code} {r['result_msg']}", file=sys.stderr)
            break
        items = r["items"]
        if not items:
            break
        for it in items:
            cat = it.get("category")
            if cat not in CATEGORIES:
                continue
            ts = f"{it['fcstDate']}T{it['fcstTime'][:2]}:00"  # YYYYMMDDTHH:00
            forecasts.setdefault(ts, {})[cat] = it.get("fcstValue")
        if len(items) < 1000 or len(forecasts) * 6 >= r.get("total_count", 0):
            break
        page += 1
    return forecasts


def _distinct_grids(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT DISTINCT nx, ny FROM events WHERE nx IS NOT NULL"
        )
    ]


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


def upsert_forecasts(conn: sqlite3.Connection) -> tuple[int, int]:
    """모든 격자 순회 → weather_fcst 적재. Returns (cells_ok, rows_written)."""
    base_date, base_time = _latest_base()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    grids = _distinct_grids(conn)
    ok = rows = 0
    for nx, ny in grids:
        try:
            fcs = fetch_grid(nx, ny, base_date, base_time)
        except Exception as exc:
            print(f"[{SOURCE}] grid ({nx},{ny}) failed: {exc}", file=sys.stderr)
            continue
        if not fcs:
            continue
        ok += 1
        for ts, fields in fcs.items():
            conn.execute(
                """INSERT OR REPLACE INTO weather_fcst
                   (nx, ny, fcst_ts, source, tmp, pty, sky, pop, reh, wsd, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    nx, ny, ts, "short",
                    _to_float(fields.get("TMP")),
                    _to_int(fields.get("PTY")),
                    _to_int(fields.get("SKY")),
                    _to_int(fields.get("POP")),
                    _to_int(fields.get("REH")),
                    _to_float(fields.get("WSD")),
                    now,
                ),
            )
            rows += 1
    conn.commit()
    return ok, rows


def fetch() -> list:
    """main.py SOURCES 호환 stub. 실제 적재는 upsert_forecasts()."""
    from storage.db import connect
    from config import DB_PATH
    conn = connect(DB_PATH)
    ok, rows = upsert_forecasts(conn)
    print(f"[{SOURCE}] grids_ok={ok} rows_written={rows}", file=sys.stderr)
    return []


if __name__ == "__main__":
    fetch()
