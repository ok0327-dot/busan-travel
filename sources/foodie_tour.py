"""부산 푸디투어 향토음식 매거진 어댑터 (data.go.kr FoodieService/getFoodieKr).

92건 향토음식·골목 단위 매거진. 좌표 X (음식 카테고리 단위라 마커 X).
vb_* 와 UC_SEQ 매칭 0% → 완전 새 콘텐츠.

활용: category='guide' + subtype='향토음식' + source='foodie_tour'
→ export_guides() 자동 합류, 읽을거리 탭에 매거진 카드로 노출.

응답 구조: getFoodieKr.item[]
키 컬럼: UC_SEQ, MAIN_TITLE (음식명/골목), SUBTITLE, PLACE,
MAIN_IMG_NORMAL/THUMB, ITEMCNTNTS (평균 973자, 100% 100자+ 매거진 본문)

NOTE: data.go.kr API ID 미확정 → registry 우회 직접 호출.
"""
from __future__ import annotations

import os
import re
import sys

import requests

from storage.db import Event

# 다국어 표기 접미사 제거 — 예: "M543 Cafe(한,영,중간,중번,일)" → "M543 Cafe"
_LANG_SUFFIX = re.compile(r'\s*\((?:[한영중간번일][,\s]*)+\)$')


def _clean_title(title: str) -> str:
    if not title:
        return title
    return _LANG_SUFFIX.sub("", title).strip()

SOURCE = "foodie_tour"
BASE_URL = "http://apis.data.go.kr/6260000/FoodieService/getFoodieKr"
PAGE_SIZE = 100


def _parse_item(raw: dict) -> Event | None:
    uc_seq = str(raw.get("UC_SEQ") or "").strip()
    title = _clean_title((raw.get("MAIN_TITLE") or raw.get("TITLE") or "").strip())
    if not uc_seq or not title:
        return None
    full_body = (raw.get("ITEMCNTNTS") or "").strip()
    if len(full_body) < 100:
        return None  # 매거진 가치 없는 짧은 글 스킵
    return Event(
        source=SOURCE,
        source_id=uc_seq,
        category="guide",
        title=title,
        start_date=None,
        venue=raw.get("PLACE") or None,
        image_url=raw.get("MAIN_IMG_NORMAL") or raw.get("MAIN_IMG_THUMB"),
        description=full_body or None,  # 매거진 본문 전체 (cap 없음 — 향토음식 유래는 길수록 가치 ↑)
        story_excerpt=full_body[:240] or None,
        subtype="향토음식",  # 매거진 카드에서 식별
        trust_tier="S",
    )


def fetch() -> list[Event]:
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
    body = payload.get("getFoodieKr", {})
    if (body.get("header") or {}).get("code") != "00":
        print(f"[{SOURCE}] non-OK: {body.get('header')}", file=sys.stderr)
        return []
    items = body.get("item") or []
    if isinstance(items, dict):
        items = [items]
    events: list[Event] = []
    for raw in items:
        ev = _parse_item(raw)
        if ev is not None:
            events.append(ev)
    print(f"[{SOURCE}] fetched {len(events)} foodie tour stories", file=sys.stderr)
    return events
