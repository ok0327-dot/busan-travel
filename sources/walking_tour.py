"""부산 도보여행정보 어댑터 (data.go.kr WalkingService/getWalkingKr).

51 코스 매거진 콘텐츠 (코스 단위, ITEMCNTNTS 평균 2021자).
**enrich 우선** 전략 (갈맷길 패턴과 동일):
- 51건 모두 visitbusan UC_SEQ 와 매칭 (vb_theme 100%) → 같은 row 의
  transport / tip (휠체어 접근성) / story_excerpt (긴 본문) 만 보강
- title/category 등은 안 건드림. UNIQUE(source, source_id) 충돌 회피.

응답 구조: getWalkingKr.item[] (root 직접 item, response.body 아님)
키 컬럼: UC_SEQ, MAIN_TITLE/SUBTITLE, PLACE, LAT/LNG,
TRFC_INFO (대중교통), MIDDLE_SIZE_RM1 (휠체어 접근성), MAIN_IMG_NORMAL/THUMB,
ITEMCNTNTS (매거진 본문)

NOTE: data.go.kr API ID 미확정 → registry 우회 직접 호출.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone

import requests

from sources._parsers import busan_latlon
from storage.db import Event, upsert_events

SOURCE = "walking_tour"
BASE_URL = "http://apis.data.go.kr/6260000/WalkingService/getWalkingKr"
PAGE_SIZE = 100


def _fetch_raw() -> list[dict]:
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        print(f"[{SOURCE}] FAIL: DATA_GO_KR_KEY 미설정", file=sys.stderr)
        return []
    try:
        r = requests.get(
            BASE_URL,
            params={
                "ServiceKey": key,
                "pageNo": 1,
                "numOfRows": PAGE_SIZE,
                "resultType": "json",
            },
            timeout=20,
        )
        r.raise_for_status()
    except Exception as exc:
        print(f"[{SOURCE}] FAILED: {exc}", file=sys.stderr)
        return []
    payload = r.json()
    body = payload.get("getWalkingKr", {})
    if (body.get("header") or {}).get("code") != "00":
        print(f"[{SOURCE}] non-OK: {body.get('header')}", file=sys.stderr)
        return []
    items = body.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items


def _parse_standalone(raw: dict) -> Event | None:
    """vb_* 매칭 실패 stop → source='walking_tour' 단독 guide (현재 0건)."""
    uc_seq = str(raw.get("UC_SEQ") or "").strip()
    title = (raw.get("TITLE") or raw.get("MAIN_TITLE") or "").strip()
    if not uc_seq or not title:
        return None
    lat, lon = busan_latlon(raw.get("LAT"), raw.get("LNG"))
    full_body = (raw.get("ITEMCNTNTS") or "").strip()
    return Event(
        source=SOURCE,
        source_id=uc_seq,
        category="guide",
        title=title,
        start_date=None,
        venue=raw.get("PLACE") or None,
        image_url=raw.get("MAIN_IMG_NORMAL") or raw.get("MAIN_IMG_THUMB"),
        description=full_body[:600] or None,
        story_excerpt=full_body[:240] or None,
        tip=(raw.get("MIDDLE_SIZE_RM1") or "").strip() or None,
        transport=(raw.get("TRFC_INFO") or "").strip() or None,
        lat=lat,
        lon=lon,
        trust_tier="S",
    )


def enrich_and_upsert(conn: sqlite3.Connection) -> tuple[int, int]:
    """도보여행 51건 → vb_* enrich (transport/tip/story_excerpt) + 매칭 실패는 단독 추가.

    Returns (enriched_vb, new_standalone).
    """
    raw_items = _fetch_raw()
    if not raw_items:
        return (0, 0)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    enriched = 0
    unmatched: list[Event] = []
    for raw in raw_items:
        uc_seq = str(raw.get("UC_SEQ") or "").strip()
        if not uc_seq:
            continue
        transport = (raw.get("TRFC_INFO") or "").strip() or None
        tip = (raw.get("MIDDLE_SIZE_RM1") or "").strip() or None
        full_body = (raw.get("ITEMCNTNTS") or "").strip()
        excerpt = full_body[:240] or None
        # vb_* 매칭
        vb_row = conn.execute(
            "SELECT id FROM events WHERE source LIKE 'vb_%' AND source_id=? LIMIT 1",
            (uc_seq,),
        ).fetchone()
        if vb_row:
            # transport/tip/story_excerpt 보강 + subtype='도보코스' 식별 마킹
            conn.execute(
                """UPDATE events SET
                    transport = COALESCE(?, transport),
                    tip = COALESCE(?, tip),
                    story_excerpt = COALESCE(?, story_excerpt),
                    subtype = '도보코스',
                    last_seen=?
                   WHERE id=?""",
                (transport, tip, excerpt, now, vb_row["id"]),
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
