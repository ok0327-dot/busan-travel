"""부산광역시 관광안내소 정보 (data.go.kr 15063445) — POI 데이터.

이벤트가 아닌 POI (관광안내소 위치) 라 start_date 는 None.
명소·축제와 지도상 결합용. 기본 SOURCES 에서는 제외 (main.py 에서 수동 추가 필요).
"""
from __future__ import annotations

import sys

from sources._gov_api import call_api
from sources._parsers import busan_latlon
from storage.db import Event

SOURCE = "busan_info_office"
API_ID = "15063445"
OP = "getInfoOfficeKr"


def _parse_item(raw: dict) -> Event:
    lat, lon = busan_latlon(raw.get("LAT"), raw.get("LNG"))
    return Event(
        source=SOURCE,
        source_id=str(raw.get("UC_SEQ") or raw.get("TITLE") or ""),
        category="info_office",
        title=(raw.get("TITLE") or raw.get("MAIN_TITLE") or "").strip(),
        start_date=None,
        venue=raw.get("PLACE") or raw.get("MAIN_TITLE"),
        address=raw.get("ADDR1"),
        url=raw.get("HOMEPAGE_URL"),
        image_url=raw.get("MAIN_IMG_NORMAL") or raw.get("MAIN_IMG_THUMB"),
        description=raw.get("ITEMCNTNTS") or raw.get("SUBTITLE"),
        lat=lat,
        lon=lon,
        raw=dict(raw),
    )


def fetch(max_pages: int = 3, page_size: int = 100) -> list[Event]:
    events: list[Event] = []
    for page in range(1, max_pages + 1):
        r = call_api(API_ID, OP, pageNo=page, numOfRows=page_size)
        code = r["result_code"]
        if code == "PENDING":
            print(f"[{SOURCE}] SKIP: {r['result_msg']}", file=sys.stderr)
            return events
        if code != "00":
            print(f"[{SOURCE}] err={code} {r['result_msg']}", file=sys.stderr)
            break
        items = r["items"]
        if not items:
            break
        events.extend(_parse_item(it) for it in items)
        if len(items) < page_size:
            break
    return events
