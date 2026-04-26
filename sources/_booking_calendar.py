"""부산 연례 축제 사전 예약 정적 캘린더 매칭.

`data/booking_calendar.json` 의 title_keywords 와 행사 title 을 매칭해서
booking_opens_at (= start_date - booking_offset_days) 를 자동 채움.

본행사 1~2개월 전 사전 예약이 시작되는 축제들을 미리 등록해두는 전략 —
description 에 "사전예약" 같은 키워드가 박힐 때 까지 기다리지 않고
선견지명으로 사용자에게 알림.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

CALENDAR_PATH = Path(__file__).parent.parent / "data" / "booking_calendar.json"

_cache: list[dict] | None = None


def _load() -> list[dict]:
    global _cache
    if _cache is None:
        try:
            data = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
            _cache = data.get("festivals", [])
        except (OSError, ValueError):
            _cache = []
    return _cache


def _match_calendar(title: str) -> dict | None:
    """행사 title 이 캘린더 title_keywords 매치되면 entry 반환."""
    if not title:
        return None
    blob = title.lower()
    for entry in _load():
        for kw in entry.get("title_keywords", []):
            if kw.lower() in blob:
                return entry
    return None


def apply_calendar(ev: Any, *, anchor: date | None = None) -> bool:
    """Event 에 정적 캘린더 매칭 → booking_opens_at 추정 채움.

    Returns True = 매칭됨 (booking_required=1 보장).
    """
    if getattr(ev, "category", None) != "festival":
        return False
    title = getattr(ev, "title", None)
    entry = _match_calendar(title)
    if not entry:
        return False
    anchor = anchor or date.today()
    start_date = getattr(ev, "start_date", None)
    offset = entry.get("booking_offset_days", 30)

    # booking_opens_at: start_date 가 있으면 - offset, 없으면 annual_month 로 추정
    opens = None
    if start_date:
        try:
            sd = date.fromisoformat(start_date[:10])
            opens = (sd - timedelta(days=offset)).isoformat()
        except ValueError:
            pass
    elif entry.get("annual_month"):
        # 올해 또는 내년의 annual_month 1일 추정
        am = int(entry["annual_month"])
        for year in (anchor.year, anchor.year + 1):
            try:
                approx_start = date(year, am, 15)
                if approx_start >= anchor:
                    opens = (approx_start - timedelta(days=offset)).isoformat()
                    break
            except ValueError:
                continue

    ev.booking_required = 1
    if opens and not getattr(ev, "booking_opens_at", None):
        ev.booking_opens_at = opens
    # description 에 캘린더 메모 prepend (사용자가 어떤 종류의 예약인지 알도록)
    note = entry.get("note", "")
    booking_type = entry.get("booking_type", "")
    if booking_type and getattr(ev, "description", None):
        prefix = f"[🎪 {booking_type}] {note} | "
        if prefix.strip() not in (ev.description or ""):
            ev.description = prefix + (ev.description or "")
    return True


__all__ = ["apply_calendar"]
