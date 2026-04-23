"""부산 해수욕장 수질 정보 (data.go.kr 15034080) — 월별 측정 데이터.

API 는 좌표 미제공 → 부산 주요 7개 해수욕장 좌표 하드코딩 (BEACHES).
events 테이블에 POI 로 추가, 수질 측정값은 beach_water 테이블에 저장.

필드:
    inspecYm        측정연월 (YYYY-MM)
    inspecArea      지점 (예: '해운대 2', '송정 3')
    water01         장구균 (엔테로코커스)
    water02         대장균
    waterComment    판정 코멘트
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

from sources._gov_api import call_api
from storage.db import Event

SOURCE = "busan_beach"
API_ID = "15034080"
OP = "getBeachInfo"

# (이름, lat, lon, gov_beach inspecArea 매칭 prefix)
# 좌표: 위키/kakao places 공개값. 해수욕장 중앙.
BEACHES = [
    ("해운대해수욕장", 35.1587, 129.1604, "해운대"),
    ("광안리해수욕장", 35.1531, 129.1188, "광안리"),
    ("송정해수욕장",   35.1777, 129.1994, "송정"),
    ("다대포해수욕장", 35.0431, 128.9676, "다대포"),
    ("일광해수욕장",   35.2697, 129.2314, "일광"),
    ("임랑해수욕장",   35.3146, 129.2641, "임랑"),
    ("송도해수욕장",   35.0757, 129.0173, "송도"),
]


def seed_beach_poi(conn: sqlite3.Connection) -> int:
    """beach_poi 테이블에 7개 해수욕장 좌표 + events POI insert."""
    from sources._kma_grid import latlon_to_grid

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = 0
    for name, lat, lon, inspec_key in BEACHES:
        conn.execute(
            "INSERT OR REPLACE INTO beach_poi (name, lat, lon, inspec_key) VALUES (?,?,?,?)",
            (name, lat, lon, inspec_key),
        )
        # events 에도 POI 로
        source_id = f"beach:{name}"
        nx, ny = latlon_to_grid(lat, lon)
        exists = conn.execute(
            "SELECT id FROM events WHERE source=? AND source_id=?", (SOURCE, source_id)
        ).fetchone()
        if exists:
            conn.execute(
                """UPDATE events SET lat=?, lon=?, nx=?, ny=?, last_seen=? WHERE id=?""",
                (lat, lon, nx, ny, now, exists[0]),
            )
        else:
            conn.execute(
                """INSERT INTO events (
                    source, source_id, category, title,
                    lat, lon, nx, ny, geocoded_at,
                    raw_json, first_seen, last_seen
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    SOURCE, source_id, "beach", name,
                    lat, lon, nx, ny, now,
                    json.dumps({"seeded": True}, ensure_ascii=False),
                    now, now,
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def fetch_water(conn: sqlite3.Connection, max_pages: int = 5, page_size: int = 100) -> int:
    """수질 데이터 수집 → beach_water 테이블."""
    rows = 0
    for page in range(1, max_pages + 1):
        r = call_api(API_ID, OP, pageNo=page, numOfRows=page_size)
        code = r["result_code"]
        if code == "PENDING":
            print(f"[{SOURCE}] water SKIP: {r['result_msg']}", file=sys.stderr)
            return rows
        if code != "00":
            print(f"[{SOURCE}] water err={code} {r['result_msg']}", file=sys.stderr)
            break
        items = r["items"]
        if not items:
            break
        for it in items:
            inspec_area = it.get("inspecArea") or ""
            # 해수욕장 이름 매핑 (prefix 매칭)
            beach_name = None
            for name, _, _, key in BEACHES:
                if inspec_area.startswith(key):
                    beach_name = name
                    break
            if not beach_name:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO beach_water
                   (beach, inspec_ym, inspec_area, water01, water02, comment, raw_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    beach_name,
                    it.get("inspecYm") or "",
                    inspec_area,
                    it.get("water01"),
                    it.get("water02"),
                    it.get("waterComment"),
                    json.dumps(dict(it), ensure_ascii=False),
                ),
            )
            rows += 1
        if len(items) < page_size:
            break
    conn.commit()
    return rows


def fetch() -> list[Event]:
    """SOURCES 호환. POI seeding + water 수집. events 는 seed 내부에서 직접 insert."""
    from config import DB_PATH
    from storage.db import connect
    conn = connect(DB_PATH)
    ins = seed_beach_poi(conn)
    water = fetch_water(conn)
    print(f"[{SOURCE}] seeded_new={ins}, water_rows={water}", file=sys.stderr)
    return []


if __name__ == "__main__":
    fetch()
