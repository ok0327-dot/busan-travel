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
    approx_start: date | None = None
    if start_date:
        try:
            sd = date.fromisoformat(start_date[:10])
            opens = (sd - timedelta(days=offset)).isoformat()
        except ValueError:
            pass
    elif entry.get("annual_month"):
        # 올해 또는 내년의 annual_month 15일 추정 (다가오는 회차)
        am = int(entry["annual_month"])
        for year in (anchor.year, anchor.year + 1):
            try:
                cand = date(year, am, 15)
                if cand >= anchor:
                    approx_start = cand
                    opens = (cand - timedelta(days=offset)).isoformat()
                    break
            except ValueError:
                continue

    ev.booking_required = 1
    if opens and not getattr(ev, "booking_opens_at", None):
        ev.booking_opens_at = opens

    # 잠정 start_date 부여: 공식 일정 미발표인 연례 축제도 월별 캘린더에 노출되도록
    # annual_month 기준 추정일을 채운다. subtype='tentative_date' 로 '예정' 표시 가능.
    # (정확한 일정이 추후 소스에서 들어오면 upsert 가 덮어씀.)
    tentative = False
    if not start_date and approx_start is not None:
        ev.start_date = approx_start.isoformat()
        if not getattr(ev, "subtype", None):
            ev.subtype = "tentative_date"
        tentative = True
    # description 에 캘린더 메모 prepend (사용자가 어떤 종류의 예약인지 알도록)
    note = entry.get("note", "")
    booking_type = entry.get("booking_type", "")
    tag = "[🗓 일정 예정]" if tentative else f"[🎪 {booking_type}]" if booking_type else ""
    if tag and getattr(ev, "description", None) is not None:
        prefix = f"{tag} {note} | "
        if prefix.strip() not in (ev.description or ""):
            ev.description = prefix + (ev.description or "")
    elif tag and not getattr(ev, "description", None):
        # description 이 비어도 예정 안내는 남긴다.
        ev.description = f"{tag} {note}".strip()
    return True


__all__ = ["apply_calendar"]
