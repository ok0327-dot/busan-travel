"""영화의전당 영화/기획전·특별전 어댑터 (dureraum 공연과 별개 서브시스템).

list: http://mobile.dureraum.org/bccm/mcontents/moList.do?rbsIdx=26
- rbsIdx=26 = '현재상영프로그램' = 기획전·특별전·시네마테크·영화제 등 '기간 단위 프로그램'
  (개별 상영 시간표가 아님). 부산푸드필름페스타 같은 영화 행사가 여기 잡힘.
- 기존 dureraum.py(공연, rbsIdx=39) 가 놓치던 영화 프로그램 보강.
- <li>(img.poster) 단위로 제목/기간/progCode/포스터 추출.
- 1년 내내 도는 정기상영 시리즈(시니어극장 등)는 행사가 아니므로 제외.
"""
from __future__ import annotations

import re
from datetime import date

from sources._adapter import HTTPSession, report
from storage.db import Event

SOURCE = "dureraum_film"
BASE = "http://mobile.dureraum.org/bccm/mcontents/"
LIST_URL = BASE + "moList.do?rbsIdx=26"

LAT, LON = 35.1717, 129.1286
VENUE_NAME = "영화의전당"
ADDRESS = "부산광역시 해운대구 수영강변대로 120"

# 'YYYY-MM-DD(요일)' 두 개 (시작 ~ 종료)
DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
# 연중 상시 시리즈 판별: 기간이 이만큼 길면 행사가 아닌 정기상영으로 보고 제외
MAX_SPAN_DAYS = 180

session = HTTPSession(SOURCE, rate_limit_s=0.3, timeout=25, retries=3)


def _iso(y: str, m: str, d: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (TypeError, ValueError):
        return None


def fetch() -> list[Event]:
    soup = session.soup(LIST_URL)
    if not soup:
        return report(SOURCE, [])

    today = date.today()
    today_iso = today.isoformat()
    events: list[Event] = []
    seen: set[str] = set()

    for li in soup.select("li:has(img.poster)"):
        title_el = li.select_one(".info h2") or li.select_one("h2")
        title = title_el.get_text(" ", strip=True) if title_el else None
        if not title or len(title) < 2:
            continue

        term_el = li.select_one("li.term div") or li.select_one(".term")
        dates = DATE_RE.findall(term_el.get_text(" ", strip=True)) if term_el else []
        if not dates:
            continue
        start = _iso(*dates[0])
        end = _iso(*dates[1]) if len(dates) > 1 else start
        if not start:
            continue
        # 완전히 지난 프로그램 제외
        if end and end < today_iso:
            continue
        # 연중 상시 정기상영 시리즈 제외 (행사가 아님)
        if end:
            try:
                span = (date.fromisoformat(end) - date.fromisoformat(start)).days
                if span > MAX_SPAN_DAYS:
                    continue
            except ValueError:
                pass

        a = li.select_one("a[href]")
        href = a.get("href", "") if a else ""
        pm = re.search(r"progCode=(\w+)", href)
        prog = pm.group(1) if pm else title
        if prog in seen:
            continue
        seen.add(prog)
        detail = (BASE + href.lstrip("/")) if href else LIST_URL

        img_el = li.select_one("img.poster[src]")
        img = img_el.get("src") if img_el else None
        if img and "no_image" in img:
            img = None

        events.append(Event(
            source=SOURCE,
            source_id=str(prog),
            category="festival",
            subtype="영화",
            title=title,
            start_date=start,
            end_date=end,
            venue=VENUE_NAME,
            address=ADDRESS,
            url=detail,
            image_url=img,
            lat=LAT,
            lon=LON,
            trust_tier="S",
            raw={"progCode": prog},
        ))
    return report(SOURCE, events)


if __name__ == "__main__":
    for e in fetch():
        print(f"  {e.start_date} ~ {e.end_date}  {e.title}")
