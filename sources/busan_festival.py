"""Busan city festival API (data.go.kr 15063500) — via gov-api-kr.

Previously this module did raw requests.get + ElementTree.
Now it routes through gov-api-kr's call_api which provides:
- per-API daily rate limit counter (약관 제14조 제5항)
- 24h disk cache
- exponential backoff retry on 5xx / network
- error code table → typed exceptions
- applied_pending pre-flight check (no HTTP call if 승인 대기)

Docs: https://www.data.go.kr/data/15063500/openapi.do
"""
from __future__ import annotations

import re
import sys

from sources._gov_api import call_api
from sources._parsers import busan_latlon
from storage.db import Event

SOURCE = "busan_festival"
API_ID = "15063500"
OP = "getFestivalKr"
PAGE_SIZE = 100
MAX_PAGES = 10

_DATE_FULL_RE = re.compile(r"(\d{4})\.?\s*(\d{1,2})\.?\s*(\d{1,2})")
_DATE_SHORT_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})")


def _normalize_dates(raw_text: str | None) -> tuple[str | None, str | None]:
    """'2025. 8. 1.(금) ~ 8. 3.(일)' → ('2025-08-01', '2025-08-03').

    Handles both 'YYYY.M.D ~ YYYY.M.D' and 'YYYY.M.D ~ M.D' (year-omitted end).
    Returns (start, end) in YYYY-MM-DD; end is None if not parsable.
    """
    if not raw_text:
        return None, None
    m1 = _DATE_FULL_RE.search(raw_text)
    if not m1:
        return None, None
    y1, mo1, d1 = m1.groups()
    start = f"{int(y1):04d}-{int(mo1):02d}-{int(d1):02d}"
    rest = raw_text[m1.end():]
    m2 = _DATE_FULL_RE.search(rest)
    if m2:
        y2, mo2, d2 = m2.groups()
        return start, f"{int(y2):04d}-{int(mo2):02d}-{int(d2):02d}"
    m3 = _DATE_SHORT_RE.search(rest)
    if m3:
        mo3, d3 = m3.groups()
        return start, f"{int(y1):04d}-{int(mo3):02d}-{int(d3):02d}"
    return start, None


def _parse_item(raw: dict) -> Event:
    start_raw = raw.get("USAGE_DAY_WEEK_AND_TIME") or raw.get("USAGE_DAY")
    start, end = _normalize_dates(start_raw)
    lat, lon = busan_latlon(raw.get("LAT"), raw.get("LNG"))
    return Event(
        source=SOURCE,
        source_id=str(raw.get("UC_SEQ") or raw.get("TITLE") or ""),
        category="festival",
        title=(raw.get("TITLE") or "").strip(),
        start_date=start,
        end_date=end,
        venue=raw.get("PLACE") or raw.get("MAIN_PLACE"),
        address=raw.get("ADDR1"),
        url=raw.get("HOMEPAGE_URL"),
        price=raw.get("USAGE_AMOUNT"),
        image_url=raw.get("MAIN_IMG_NORMAL") or raw.get("MAIN_IMG_THUMB"),
        description=raw.get("ITEMCNTNTS") or raw.get("SUBTITLE"),
        lat=lat,
        lon=lon,
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
        page_items = r["items"]
        if not page_items:
            break
        events.extend(_parse_item(it) for it in page_items)
        if len(page_items) < page_size or len(events) >= r["total_count"]:
            break
    return events
