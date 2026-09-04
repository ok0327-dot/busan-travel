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


def _resolve_exact_dates(mapping: Any, anchor: date) -> tuple[str, str | None] | None:
    """exact_dates = {"2026": ["2026-06-26", "2026-06-28"], ...} 에서 아직 끝나지 않은
    (end >= 오늘) 가장 이른 회차를 (start, end) 로 반환. 없으면 None.

    visitbusan 큐레이션이 작년판 날짜를 보여줄 때, 우리가 아는 올해 정확 일정으로 덮어쓰기 위함.
    """
    if not isinstance(mapping, dict):
        return None
    today_iso = anchor.isoformat()
    best: tuple[str, str | None] | None = None
    for pair in mapping.values():
        if not pair:
            continue
        start = pair[0]
        end = pair[1] if len(pair) > 1 and pair[1] else start
        if end >= today_iso and (best is None or start < best[0]):
            best = (start, pair[1] if len(pair) > 1 else None)
    return best


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

    # booking_opens_at + 날짜 보강: start_date 있으면 -offset, 없으면
    #   (1) 올해 정확 일정(exact_dates) → (2) annual_month 추정 순.
    opens = None
    approx_start: date | None = None
    exact: tuple[str, str | None] | None = None
    if start_date:
        try:
            sd = date.fromisoformat(start_date[:10])
            opens = (sd - timedelta(days=offset)).isoformat()
        except ValueError:
            pass
        # end_date 보강: 소스가 end_date 를 주지 않았을 때 exact_dates 로 보완.
        # start_date 기준 ±7일 이내에 exact_dates 일치 → end_date 확정 채움.
        if not getattr(ev, "end_date", None) and entry.get("exact_dates"):
            exact_for_end = _resolve_exact_dates(entry["exact_dates"], anchor)
            if exact_for_end and exact_for_end[1]:
                try:
                    exact_sd = date.fromisoformat(exact_for_end[0])
                    event_sd = date.fromisoformat(start_date[:10])
                    if abs((event_sd - exact_sd).days) <= 7:
                        ev.end_date = exact_for_end[1]
                except ValueError:
                    pass
    else:
        # (1) 올해 정확 일정 — visitbusan 이 작년판이어도 정확한 날짜로 노출
        exact = _resolve_exact_dates(entry.get("exact_dates"), anchor)
        if exact:
            try:
                opens = (date.fromisoformat(exact[0]) - timedelta(days=offset)).isoformat()
            except ValueError:
                pass
        elif entry.get("annual_month"):
            # (2) 올해 또는 내년의 annual_month 15일 추정 (다가오는 회차)
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
    # venue 보강: 소스가 venue 를 비워둔 경우(예: vb_schedule 모빌리티쇼)만 채움
    if entry.get("venue") and not getattr(ev, "venue", None):
        ev.venue = entry["venue"]

    # 날짜 보강: 공식 일정 미발표인 연례 축제도 월별 캘린더에 노출되도록.
    #   exact = 확정 일정(정확) / approx = annual_month 잠정(subtype=tentative_date).
    #   (정확한 일정이 추후 소스에서 들어오면 upsert 가 덮어씀.)
    tentative = False
    if not start_date and exact is not None:
        ev.start_date = exact[0]
        if exact[1] and not getattr(ev, "end_date", None):
            ev.end_date = exact[1]
    elif not start_date and approx_start is not None:
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
