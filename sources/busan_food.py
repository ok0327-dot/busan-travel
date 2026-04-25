"""Busan city restaurant API (data.go.kr 15063472) — via gov-api-kr.

부산 맛집 정보. POI 성격(start_date=None).
Schema identical to busan_festival/attraction (6260000 통합키).
"""
from __future__ import annotations

import sys

from sources._classification_overrides import apply_override
from sources._gov_api import call_api
from sources._parsers import busan_latlon
from storage.db import Event

SOURCE = "busan_food"
API_ID = "15063472"
OP = "getFoodKr"
PAGE_SIZE = 100
MAX_PAGES = 20


def _parse_item(raw: dict) -> Event:
    lat, lon = busan_latlon(raw.get("LAT"), raw.get("LNG"))
    menu = (raw.get("RPRSNTV_MENU") or "").strip() or None
    gugun = (raw.get("GUGUN_NM") or "").strip() or None
    base_desc = (raw.get("ITEMCNTNTS") or raw.get("SUBTITLE") or "").strip()
    # 부산푸디 고유 메타를 description 에 prepend → 카드/dedup 후에도 메뉴/구군 노출
    head_bits = []
    if menu:
        head_bits.append(f"🍴 대표메뉴 · {menu}")
    if gugun:
        head_bits.append(f"📍 {gugun}")
    head = " · ".join(head_bits)
    description = f"{head}\n{base_desc}" if head and base_desc else (head or base_desc or None)
    source_id = str(raw.get("UC_SEQ") or raw.get("TITLE") or "")
    category = apply_override(SOURCE, source_id, "food")
    return Event(
        source=SOURCE,
        source_id=source_id,
        category=category,
        title=(raw.get("TITLE") or raw.get("MAIN_TITLE") or "").strip(),
        start_date=None,
        venue=raw.get("PLACE") or gugun,
        address=raw.get("ADDR1"),
        url=raw.get("HOMEPAGE_URL"),
        image_url=raw.get("MAIN_IMG_NORMAL") or raw.get("MAIN_IMG_THUMB"),
        description=description,
        lat=lat,
        lon=lon,
        menu=menu,
        gugun=gugun,
        trust_tier="S",  # 정부 API
        raw=dict(raw),
    )


def fetch(page_size: int = PAGE_SIZE, max_pages: int = MAX_PAGES) -> list[Event]:
    events: list[Event] = []
    for page in range(1, max_pages + 1):
        r = call_api(API_ID, OP, pageNo=page, numOfRows=page_size)
        code = r["result_code"]
        if code == "PENDING":
            print(f"[{SOURCE}] SKIP: {r['result_msg']}", file=sys.stderr)
            return events
        if code != "00":
            print(f"[{SOURCE}] page={page} err={code} {r['result_msg']}", file=sys.stderr)
            break
        items = r["items"]
        if not items:
            break
        events.extend(_parse_item(it) for it in items)
        if len(items) < page_size or len(events) >= r.get("total_count", 0):
            break
    return events
