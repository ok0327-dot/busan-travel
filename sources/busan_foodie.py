"""Busan Foodie Tour API (data.go.kr) — 부산 향토음식·대표 메뉴 정보.

부산광역시가 제공하는 '부산푸디투어정보 서비스' API.
현재 registry.json 에 API_ID 등록 대기 중 (TBD). 등록 완료 후 FOODIE_API_ID 상수 교체.

부산 6260000 기관 API 표준 필드 (맛집·명소 API 와 동일 패턴):
- TITLE / PLACE / ADDR1 / LAT / LNG
- MAIN_IMG_NORMAL / MAIN_IMG_THUMB
- ITEMCNTNTS (설명) / SUBTITLE
- HOMEPAGE_URL / CNTCT_TEL
- UC_SEQ (고유 식별자)
- USAGE_DAY_WEEK_AND_TIME / HLDY_INFO (영업시간/휴무)
- ReceNTMN / RPRSNTV_MENU (대표메뉴) — foodie 특화 추정 필드
"""
from __future__ import annotations

import sys

from sources._gov_api import call_api
from sources._parsers import busan_latlon
from storage.db import Event

SOURCE = "busan_foodie"

# TODO: data.go.kr 등록 후 확정. registry.json 에도 함께 등록 필요.
FOODIE_API_ID = "TBD"
FOODIE_OP = "getFoodieTourKr"  # 부산 API 네이밍 패턴(getFoodKr/getAttractionKr) 기반 추정
PAGE_SIZE = 100
MAX_PAGES = 20


def _parse_item(raw: dict) -> Event:
    lat, lon = busan_latlon(raw.get("LAT"), raw.get("LNG"))
    # 대표 메뉴는 subtype 에 담아 UI 에서 배지로 표시 가능
    rpr_menu = (raw.get("RPRSNTV_MENU") or raw.get("REPRESENT_MENU") or "").strip() or None
    return Event(
        source=SOURCE,
        source_id=str(raw.get("UC_SEQ") or raw.get("TITLE") or ""),
        category="foodie",
        title=(raw.get("TITLE") or "").strip(),
        venue=raw.get("PLACE"),
        address=raw.get("ADDR1"),
        url=raw.get("HOMEPAGE_URL"),
        phone=raw.get("CNTCT_TEL"),
        image_url=raw.get("MAIN_IMG_NORMAL") or raw.get("MAIN_IMG_THUMB"),
        description=raw.get("ITEMCNTNTS") or raw.get("SUBTITLE"),
        hours=raw.get("USAGE_DAY_WEEK_AND_TIME"),
        holiday=raw.get("HLDY_INFO"),
        subtype=rpr_menu,
        lat=lat,
        lon=lon,
        raw=dict(raw),
    )


def fetch(page_size: int = PAGE_SIZE, max_pages: int = MAX_PAGES) -> list[Event]:
    if FOODIE_API_ID == "TBD":
        print(
            f"[{SOURCE}] SKIP: FOODIE_API_ID 미확정 — registry.json 등록 후 실행",
            file=sys.stderr,
        )
        return []

    events: list[Event] = []
    for page in range(1, max_pages + 1):
        r = call_api(FOODIE_API_ID, FOODIE_OP, pageNo=page, numOfRows=page_size)
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
