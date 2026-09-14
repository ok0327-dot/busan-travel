"""부산축제조직위(festivalbusan.com) 8개 메인 축제 어댑터.

8개 축제는 hardcoded URL 리스트 (각각 별도 페이지 / 일부는 별도 도메인).
detail 페이지에서 정규식으로 날짜 범위 + og:image 추출. 기본 메타는 hardcoded fallback.
"""
from __future__ import annotations

import re
from datetime import date

from sources._adapter import HTTPSession, report
from storage.db import Event

SOURCE_PREFIX = "festivalbusan"
session = HTTPSession(SOURCE_PREFIX, rate_limit_s=0.4)

# (key, url, title_default, venue, lat, lon)
FESTIVALS: list[tuple[str, str, str, str, float, float]] = [
    ("wheat",       "https://festivalbusan.com/wheat/",         "부산 밀 페스티벌",      "화명생태공원",      35.2305, 128.9968),
    ("taxchelin",   "https://festivalbusan.com/taxchelin/",     "택슐랭",              "원도심 일원",       35.0966, 129.0306),
    ("busanbell",   "https://festivalbusan.com/busanbell/",     "부산벨",              "부산 일원",         35.1796, 129.0756),
    ("busanport",   "https://festivalbusan.com/busanport/",     "부산항축제",           "북항 일원",         35.1147, 129.0410),
    ("seafestival", "https://festivalbusan.com/seafestival/",   "부산바다축제",         "해운대해수욕장",     35.1587, 129.1604),
    ("rockfest",    "https://busanrockfestival.com/",           "부산국제록페스티벌",    "삼락생태공원",       35.1859, 128.9617),
    ("fireworks",   "https://busanfireworks.com/",              "부산불꽃축제",         "광안리해수욕장",     35.1531, 129.1187),
    ("7bridges",    "https://busan7bridges.com/",               "세븐브릿지 투어",      "부산 전역",         35.1796, 129.0756),
    ("biennale",    "https://busanbiennale2026.com/",           "2026 부산비엔날레",    "부산현대미술관 · 영도",  35.1021, 128.9991),
]

DATE_RE = re.compile(r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})")
RANGE_RE = re.compile(
    r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})"
    r"\s*[~\-–]\s*"
    r"(?:(\d{4})[.\-/]\s*)?(\d{1,2})[.\-/]\s*(\d{1,2})"
)
# 의심 title 패턴 — 팝업/알림 등은 hardcoded default 로 fallback
SUSPICIOUS_TITLE = re.compile(r"팝업|알림|오류|404|에러|로딩|준비|업데이트")


def _iso(y, m, d) -> str | None:
    """(y,m,d) → 'YYYY-MM-DD'. 월 1-12·일 1-31 검증 실패 시 None.

    시각(12:54)·잘못된 매칭(일=54 등)이 깨진 날짜 문자열로 저장되는 것 방지.
    """
    try:
        from datetime import date as _date

        return _date(int(y), int(m), int(d)).isoformat()
    except (TypeError, ValueError):
        return None


def _parse_detail(url: str) -> dict:
    soup = session.soup(url)
    if not soup:
        return {}
    text = soup.get_text("\n", strip=True)

    # 제목 — og:title 또는 첫 h1
    title = None
    og_t = soup.find("meta", property="og:title")
    if og_t:
        title = (og_t.get("content") or "").strip()
    if not title:
        h1 = soup.find(["h1", "h2"])
        if h1:
            title = h1.get_text(strip=True)
    # 너무 길거나 sitewide 메타 / 팝업·알림 패턴이면 버림 (hardcoded default 사용)
    if title and (len(title) > 80 or SUSPICIOUS_TITLE.search(title)):
        title = None

    # 날짜 범위 매칭 — 본문 첫 8000자에서 모든 매칭 후 미래 일정만 채택
    head = text[:8000]
    today_iso = date.today().isoformat()
    start = end = None

    # 1. 범위 매칭 — 미래 시작일 우선
    for rm in RANGE_RE.finditer(head):
        y1, m1, d1, y2, m2, d2 = rm.groups()
        s = _iso(y1, m1, d1)  # 월/일 범위 검증 (시각 12:54 등 오인식 → None)
        if s and s >= today_iso:
            e = _iso(y2 or y1, m2, d2)
            start = s
            end = e if (e and e >= s) else None
            break

    # 2. 단일 날짜 (range 매칭 실패 시) — 미래 첫 매칭
    if not start:
        for dm in DATE_RE.finditer(head):
            y, m, d = dm.groups()
            s = _iso(y, m, d)
            if s and s >= today_iso:
                start = s
                break

    # og:image
    image = None
    og_i = soup.find("meta", property="og:image")
    if og_i:
        image = og_i.get("content")

    return {"title": title, "start": start, "end": end, "image": image}


def fetch() -> list[Event]:
    events: list[Event] = []
    for key, url, title_default, venue, lat, lon in FESTIVALS:
        meta = _parse_detail(url)
        title = (meta.get("title") or title_default).strip() or title_default
        events.append(Event(
            source=f"{SOURCE_PREFIX}:{key}",
            source_id=key,
            category="festival",
            title=title,
            start_date=meta.get("start"),
            end_date=meta.get("end"),
            venue=venue,
            url=url,
            image_url=meta.get("image"),
            lat=lat,
            lon=lon,
            trust_tier="S",
            raw={"key": key, "title_default": title_default},
        ))
    return report(SOURCE_PREFIX, events)


if __name__ == "__main__":
    for e in fetch():
        print(f"  {e.start_date} ~ {e.end_date}  {e.title}  @ {e.venue}")
