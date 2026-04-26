"""부산 갈맷길 관광정보 어댑터 (data.go.kr 15077606).

갈맷길 9코스 stops 85건 (POI 단위). 81/85 가 기존 vb_* 와 uc_seq 일치.

전략: enrich 우선
- vb_* 매칭 → 기존 row 의 galmaet_course/galmaet_gugan 메타만 UPDATE (title/category 등은 안 건드림)
- 매칭 실패 → source='galmaet' 로 단독 attraction 추가

응답 구조: response.body.items.item[]
키 컬럼: course (1~9), gugan (1~3), uc_seq, lat/lng, name, title,
itemcntnts (스토리), main_img_n/t, cate1_nm (모두 "명소"), place
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

from sources._gov_api import call_api
from sources._parsers import busan_latlon
from storage.db import Event, upsert_events

SOURCE = "galmaet"
API_ID = "15077606"
OP = "getgmgtourinfo"


def _fetch_raw() -> list[dict]:
    payload = call_api(API_ID, OP, pageNo=1, numOfRows=200)
    rows = payload.get("items") or []
    if not isinstance(rows, list):
        rows = [rows]
    return rows


def _parse_standalone(raw: dict) -> Event | None:
    """vb_* 매칭 실패 stop → source='galmaet' 단독 Event."""
    uc_seq = str(raw.get("uc_seq") or "").strip()
    if not uc_seq:
        return None
    lat, lon = busan_latlon(raw.get("lat"), raw.get("lng"))
    if lat is None or lon is None:
        return None
    title = (raw.get("name") or raw.get("title") or "").strip()
    if not title:
        return None
    course = int(raw.get("course") or 0) or None
    gugan = int(raw.get("gugan") or 0) or None
    excerpt = (raw.get("itemcntnts") or "").strip()
    return Event(
        source=SOURCE,
        source_id=uc_seq,
        category="attraction",
        title=title,
        start_date=None,
        venue=raw.get("place") or None,
        image_url=raw.get("main_img_n") or raw.get("main_img_t"),
        description=excerpt[:600] or None,
        story_excerpt=excerpt[:240] or None,
        lat=lat,
        lon=lon,
        trust_tier="S",
        galmaet_course=course,
        galmaet_gugan=gugan,
    )


def enrich_and_upsert(conn: sqlite3.Connection) -> tuple[int, int]:
    """갈맷길 85건 → vb_* enrich + 매칭 실패는 단독 추가.

    Returns (enriched_vb, new_standalone).
    """
    raw_items = _fetch_raw()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    enriched = 0
    unmatched: list[Event] = []
    for raw in raw_items:
        uc_seq = str(raw.get("uc_seq") or "").strip()
        if not uc_seq:
            continue
        course = int(raw.get("course") or 0) or None
        gugan = int(raw.get("gugan") or 0) or None
        # vb_* 매칭: 같은 uc_seq 갖는 어떤 vb_* source 든
        vb_row = conn.execute(
            "SELECT id FROM events WHERE source LIKE 'vb_%' AND source_id=? LIMIT 1",
            (uc_seq,),
        ).fetchone()
        if vb_row:
            conn.execute(
                "UPDATE events SET galmaet_course=?, galmaet_gugan=?, last_seen=? WHERE id=?",
                (course, gugan, now, vb_row["id"]),
            )
            enriched += 1
        else:
            ev = _parse_standalone(raw)
            if ev is not None:
                unmatched.append(ev)
    conn.commit()
    new_ins, _ = upsert_events(conn, unmatched) if unmatched else (0, 0)
    print(
        f"[{SOURCE}] enriched vb_*={enriched}, standalone new={new_ins} "
        f"(total raw={len(raw_items)})",
        file=sys.stderr,
    )
    return enriched, new_ins
