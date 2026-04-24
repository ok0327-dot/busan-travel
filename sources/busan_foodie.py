"""Busan Foodie Tour API — 부산 향토음식 에세이·대표 지역 먹거리.

End Point: https://apis.data.go.kr/6260000/FoodieService/getFoodieKr
데이터명: 부산광역시_부산푸디투어정보 서비스 (활용기간 2026-04-24 ~ 2028-04-24)

특징 / Notes:
- 맛집 API(FoodService) 와 달리 **위·경도·주소 필드가 없음**
- "밀면", "초량 돼지갈비 골목", "동래파전" 처럼 **지역·대표 음식 에세이** 성격
- 지도 마커 대신 시트 '오늘의 부산' 하이라이트 리스트로 노출
- 향후 Phase 3: Kakao 주소검색 API 로 PLACE 문자열 → 좌표 자동화 가능

응답 필드 (실측):
  UC_SEQ / TITLE / MAIN_TITLE / SUBTITLE / PLACE / ITEMCNTNTS
  MAIN_IMG_NORMAL / MAIN_IMG_THUMB

정식 API_ID(data.go.kr 8자리) 는 사용자 공유 대기 중. 받는 즉시 registry.json
등록 + gov-api-kr call_api 기반으로 전환 예정. 현재는 requests 직접 호출.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

from storage.db import Event

SOURCE = "busan_foodie"
ENDPOINT = "https://apis.data.go.kr/6260000/FoodieService/getFoodieKr"
PAGE_SIZE = 100
MAX_PAGES = 5


def _load_key() -> str | None:
    """DATA_GO_KR_KEY 를 env 또는 gov-api-kr/.env 에서 로드."""
    k = os.environ.get("DATA_GO_KR_KEY")
    if k:
        return k
    candidates = (
        Path.home() / "my_playground" / "gov-api-kr" / ".env",
        Path(__file__).resolve().parent.parent / "vendor" / "gov-api-kr" / ".env",
    )
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            s = line.strip()
            if s.startswith("DATA_GO_KR_KEY="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _parse_item(raw: dict) -> Event:
    # SUBTITLE 을 subtype 에 저장 (UI 배지로 노출: "초량에서 고기 즐기기" 등)
    subtitle = (raw.get("SUBTITLE") or "").strip() or None
    return Event(
        source=SOURCE,
        source_id=str(raw.get("UC_SEQ") or raw.get("TITLE") or ""),
        category="foodie",
        title=(raw.get("TITLE") or raw.get("MAIN_TITLE") or "").strip(),
        venue=raw.get("PLACE"),
        image_url=raw.get("MAIN_IMG_NORMAL") or raw.get("MAIN_IMG_THUMB"),
        description=raw.get("ITEMCNTNTS") or raw.get("SUBTITLE"),
        subtype=subtitle,
        raw=dict(raw),
    )


def fetch(page_size: int = PAGE_SIZE, max_pages: int = MAX_PAGES) -> list[Event]:
    key = _load_key()
    if not key:
        print(f"[{SOURCE}] SKIP: DATA_GO_KR_KEY 미설정", file=sys.stderr)
        return []

    events: list[Event] = []
    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                ENDPOINT,
                params={
                    "ServiceKey": key,
                    "pageNo": page,
                    "numOfRows": page_size,
                    "resultType": "json",
                },
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[{SOURCE}] page={page} err: {e}", file=sys.stderr)
            break

        root = data.get("getFoodieKr", {}) if isinstance(data, dict) else {}
        header = root.get("header", {})
        code = header.get("code")
        if code != "00":
            print(f"[{SOURCE}] page={page} err code={code} {header.get('message')}", file=sys.stderr)
            break

        items = root.get("item") or []
        if isinstance(items, dict):
            items = [items]
        if not items:
            break

        total = int(root.get("totalCount") or 0)
        events.extend(_parse_item(it) for it in items)
        if len(items) < page_size or (total and len(events) >= total):
            break

    return events
