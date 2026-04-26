"""사전 예약 메타 추출기 — description / url 에서 booking_* 필드 자동 채움.

설계 / Design:
- **Two-tier 신뢰도** (false positive 차단):
  - HIGH: 외부 예매 도메인 OR 명확한 행위 동사 ("사전예약", "신청기간", "예매하기") OR
          정적 booking_calendar 매칭 → `booking_required=1`
  - 텍스트만 매치 ("선착순", "유료") 는 booking_required 안 채움 (UI 노이즈 회피)
- **booking_deadline / booking_opens_at** 자동 추출 (날짜 정규식 + start_date fallback)
- **booking_url** 외부 예매 도메인 자동 추출

호출처 / Usage:
    from sources._booking_extractor import enrich_booking
    enrich_booking(ev)  # Event 의 booking_* 필드 in-place 채움
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

# ─────────────────────────────────────────────────────────────────────
# 1) HIGH 신뢰도 키워드 — 매칭 시 booking_required=1
# ─────────────────────────────────────────────────────────────────────
HIGH_CONFIDENCE_KEYWORDS: tuple[str, ...] = (
    # 명확한 사전 예약 행위
    "사전예약", "사전 예약", "사전신청", "사전 신청",
    "예매하기", "예매처", "예매 시작", "예매시작",
    "티켓오픈", "티켓 오픈", "티켓 예매",
    "신청기간", "접수기간", "참가 신청", "참가신청", "참가자 모집",
    "참여자 모집", "체험 신청", "체험신청",
    # 마감 시점 표현
    "예매 마감", "신청 마감", "접수 마감",
    # 인터파크/티켓링크 등 경로 명시
    "인터파크에서", "티켓링크에서", "예매 사이트",
)

# ─────────────────────────────────────────────────────────────────────
# 2) 외부 예매 도메인 — URL 매칭 시 booking_required=1 + booking_url
# ─────────────────────────────────────────────────────────────────────
EXTERNAL_BOOKING_DOMAINS: tuple[str, ...] = (
    "tickets.interpark.com",
    "ticket.interpark.com",
    "interpark.com",
    "ticketlink.co.kr",
    "ticket.melon.com",
    "ticketmelon.com",
    "tickets.coupang.com",
    "ticketing.cgv.co.kr",
    "yes24.com/tickets",
    "ticket.yes24.com",
)

# URL 정규식 (description 본문에 박힌 외부 링크 추출)
_URL_PATTERN = re.compile(
    r'(https?://(?:[a-z0-9-]+\.)?(?:'
    r'interpark\.com|ticketlink\.co\.kr|ticketmelon\.com|'
    r'ticket\.melon\.com|yes24\.com|ticketing\.cgv\.co\.kr'
    r')/\S+)',
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────
# 3) booking_deadline 추출 (마감일)
# ─────────────────────────────────────────────────────────────────────
# YYYY.MM.DD / YYYY-MM-DD / YYYY/MM/DD 형식
_FULL_DATE_PATTERN = re.compile(r'(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})')
# "M월 D일까지/마감" — 연도 없으면 올해 또는 내년
_KOREAN_DEADLINE_PATTERN = re.compile(r'(\d{1,2})월\s*(\d{1,2})일\s*(?:까지|마감)')
# "신청기간: M.D ~ M.D" — 끝 날짜만 추출
_RANGE_END_PATTERN = re.compile(r'~\s*(\d{1,2})[.\-/](\d{1,2})')
# 마감 컨텍스트 키워드 (앞에 있어야 deadline 으로 채택)
_DEADLINE_CONTEXT = re.compile(
    r'(?:신청기간|접수기간|예매\s*마감|신청\s*마감|접수\s*마감|예매기간|마감)',
)

# ─────────────────────────────────────────────────────────────────────
# 4) booking_opens_at 추출 (발매 시작)
# ─────────────────────────────────────────────────────────────────────
_OPENS_CONTEXT = re.compile(
    r'(?:티켓\s*오픈|예매\s*시작|예매\s*오픈|발매\s*시작|신청\s*시작|모집\s*시작)',
)

# ─────────────────────────────────────────────────────────────────────
# 5) 카테고리별 fallback deadline offset (start_date 부터 역산)
# ─────────────────────────────────────────────────────────────────────
FALLBACK_DEADLINE_DAYS: dict[str, int] = {
    "festival": 30,      # 축제는 보통 1개월 전부터 사전 예약
    "performance": 1,    # 공연은 당일 매진 가능 → 전날까지 예매
    "exhibition": 7,     # 전시는 일주일 전 추천 (도슨트 등)
}

# ─────────────────────────────────────────────────────────────────────
# 6) Source 기반 booking 휴리스틱
#    공식 공연장/전시장 source 이면 거의 항상 사전 예매 필요
# ─────────────────────────────────────────────────────────────────────
BOOKING_REQUIRED_SOURCES: dict[str, set[str]] = {
    "performance": {"dabom", "dureraum", "festivalbusan"},
    "exhibition":  {"art_busan", "moca_busan"},
    # festival 은 케이스별로 다양 → 정적 캘린더로 처리
}


def _to_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_korean_deadline(text: str, anchor: date) -> str | None:
    """'M월 D일까지' → ISO date. anchor 기준 가까운 미래 연도 추정."""
    m = _KOREAN_DEADLINE_PATTERN.search(text)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    # 올해 안에 있으면 올해, 이미 지났으면 내년
    for year in (anchor.year, anchor.year + 1):
        d = _to_date(year, month, day)
        if d and d >= anchor.isoformat():
            return d
    return None


def _extract_deadline(text: str, anchor: date | None = None) -> str | None:
    """description 에서 booking_deadline 추출. anchor=오늘.

    우선순위:
    1. _DEADLINE_CONTEXT 가까이 있는 full date (YYYY.MM.DD)
    2. _DEADLINE_CONTEXT 가까이 있는 한국식 (M월 D일까지)
    3. ~ 범위 표현의 끝 날짜
    """
    if not text:
        return None
    anchor = anchor or date.today()
    # context 매치 시 그 근처 날짜만 채택 (false positive 차단)
    for ctx_match in _DEADLINE_CONTEXT.finditer(text):
        # context 매치 부근 ±80자 윈도우
        s = max(0, ctx_match.start() - 30)
        e = min(len(text), ctx_match.end() + 80)
        window = text[s:e]
        # full date 우선
        m = _FULL_DATE_PATTERN.search(window)
        if m:
            d = _to_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d and d >= anchor.isoformat():
                return d
        # 한국식
        d = _parse_korean_deadline(window, anchor)
        if d:
            return d
        # 범위 끝
        rm = _RANGE_END_PATTERN.search(window)
        if rm:
            month, day = int(rm.group(1)), int(rm.group(2))
            for year in (anchor.year, anchor.year + 1):
                d = _to_date(year, month, day)
                if d and d >= anchor.isoformat():
                    return d
    return None


def _extract_opens_at(text: str, anchor: date | None = None) -> str | None:
    """booking_opens_at 추출 (발매/오픈 시작일). _OPENS_CONTEXT 근처 날짜."""
    if not text:
        return None
    anchor = anchor or date.today()
    for ctx_match in _OPENS_CONTEXT.finditer(text):
        s = max(0, ctx_match.start() - 30)
        e = min(len(text), ctx_match.end() + 80)
        window = text[s:e]
        m = _FULL_DATE_PATTERN.search(window)
        if m:
            d = _to_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d:
                return d
        m2 = _KOREAN_DEADLINE_PATTERN.search(window)
        if m2:
            month, day = int(m2.group(1)), int(m2.group(2))
            for year in (anchor.year, anchor.year + 1):
                d = _to_date(year, month, day)
                if d:
                    return d
    return None


def _extract_booking_url(text: str, fallback_url: str | None) -> str | None:
    """description 에서 외부 예매 URL 추출. 없으면 url 자체가 외부 도메인이면 채택."""
    if text:
        m = _URL_PATTERN.search(text)
        if m:
            return m.group(1)
    if fallback_url:
        for dom in EXTERNAL_BOOKING_DOMAINS:
            if dom in fallback_url.lower():
                return fallback_url
    return None


def _matches_high_confidence(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in HIGH_CONFIDENCE_KEYWORDS)


def enrich_booking(ev: Any, *, anchor: date | None = None) -> bool:
    """Event 객체의 booking_* 필드 in-place 채움.

    Args:
        ev: Event-like (booking_required, booking_deadline, booking_opens_at,
            description, url, title, category, start_date 속성 보유)
        anchor: 오늘 날짜 (기본: date.today())

    Returns:
        True = booking_required=1 로 판정 (HIGH 신뢰도). False = 정보 없음.
    """
    anchor = anchor or date.today()
    blob = " ".join(filter(None, [
        getattr(ev, "title", None),
        getattr(ev, "description", None),
        getattr(ev, "venue", None),
    ]))
    url = getattr(ev, "url", None) or ""

    # 1) booking_url 추출 (외부 도메인)
    booking_url = _extract_booking_url(blob, url)
    has_external_domain = booking_url is not None

    # 2) Source 기반 휴리스틱 (공식 공연장/전시장 → 거의 모두 예약 필요)
    source = getattr(ev, "source", None)
    cat = getattr(ev, "category", None)
    source_match = (
        cat in BOOKING_REQUIRED_SOURCES
        and source in BOOKING_REQUIRED_SOURCES[cat]
    )

    # 3) HIGH 신뢰도 판정 = 외부도메인 OR 키워드 OR source 매칭
    is_required = (
        has_external_domain
        or _matches_high_confidence(blob)
        or source_match
    )

    # 이미 booking_required 가 명시적으로 0이면 건드리지 않음
    if getattr(ev, "booking_required", None) == 1 or is_required:
        ev.booking_required = 1
        # description 에 외부 URL 박혀있으면 url 도 보강 (없을 때만)
        if booking_url and not getattr(ev, "url", None):
            ev.url = booking_url

        # 3) booking_deadline 추출
        if not getattr(ev, "booking_deadline", None):
            ddl = _extract_deadline(blob, anchor)
            if ddl:
                ev.booking_deadline = ddl
            else:
                # fallback: start_date - N일 (카테고리별)
                start = getattr(ev, "start_date", None)
                cat = getattr(ev, "category", None)
                offset = FALLBACK_DEADLINE_DAYS.get(cat or "", 0)
                if start and offset:
                    try:
                        sd = date.fromisoformat(start[:10])
                        ddl_date = sd - timedelta(days=offset)
                        if ddl_date >= anchor:
                            ev.booking_deadline = ddl_date.isoformat()
                    except ValueError:
                        pass

        # 4) booking_opens_at 추출
        if not getattr(ev, "booking_opens_at", None):
            opens = _extract_opens_at(blob, anchor)
            if opens:
                ev.booking_opens_at = opens

        return True

    return False


__all__ = [
    "enrich_booking",
    "HIGH_CONFIDENCE_KEYWORDS",
    "EXTERNAL_BOOKING_DOMAINS",
    "FALLBACK_DEADLINE_DAYS",
]
