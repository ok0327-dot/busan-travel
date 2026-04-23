"""한국관광공사 TourAPI 4.0 (data.go.kr 15101578) — searchFestival2, 부산 areaCode=6.

전국 축제 DB 로 부산시 15063500 축제와 교차검증·확장.
TourAPI 특이사항:
- resultCode 가 "0000" (4자) — 일반 data.go.kr 의 "00" 과 다름
- JSON 은 _type=json (resultType 아님)
- MobileOS / MobileApp 필수
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from sources._gov_api import call_api
from sources._parsers import busan_latlon
from storage.db import Event

SOURCE = "tour_api"
API_ID = "15101578"
OP = "searchFestival2"
MOBILE_APP = "busan-travel"
BUSAN_AREA = "6"
OK_CODES = {"00", "0000"}  # TourAPI 는 0000


def _ymd(s: str | None) -> str | None:
    """TourAPI YYYYMMDD → YYYY-MM-DD."""
    if not s or len(s) != 8 or not s.isdigit():
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _parse_item(raw: dict) -> Event:
    lat, lon = busan_latlon(raw.get("mapy"), raw.get("mapx"))
    return Event(
        source=SOURCE,
        source_id=str(raw.get("contentid") or ""),
        category="festival",
        title=(raw.get("title") or "").strip(),
        start_date=_ymd(raw.get("eventstartdate")),
        end_date=_ymd(raw.get("eventenddate")),
        venue=raw.get("eventplace"),
        address=raw.get("addr1"),
        url=None,
        image_url=raw.get("firstimage"),
        description=None,
        lat=lat,
        lon=lon,
        raw=dict(raw),
    )


def fetch(max_pages: int = 10, page_size: int = 100, lookback_days: int = 365) -> list[Event]:
    """과거 lookback_days 전부터 시작하는 부산(areaCode=6) 축제 전체.

    1년 전부터 잡으면 진행 중 축제도 포함됨 (eventstartdate <= today <= eventenddate).
    """
    start = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    events: list[Event] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        r = call_api(
            API_ID, OP,
            pageNo=page, numOfRows=page_size,
            MobileOS="ETC", MobileApp=MOBILE_APP, _type="json",
            eventStartDate=start, areaCode=BUSAN_AREA,
        )
        code = r["result_code"]
        if code == "PENDING":
            print(f"[{SOURCE}] SKIP: {r['result_msg']}", file=sys.stderr)
            return events
        if code not in OK_CODES:
            print(f"[{SOURCE}] page={page} err={code} {r['result_msg']}", file=sys.stderr)
            break
        items = r["items"]
        if not items:
            break
        for it in items:
            cid = str(it.get("contentid") or "")
            if cid and cid not in seen:
                seen.add(cid)
                events.append(_parse_item(it))
        if len(items) < page_size:
            break
    return events
