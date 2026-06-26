"""BEXCO (부산전시컨벤션센터) 전시·박람회 어댑터.

list: https://www.bexco.co.kr/kor/CMS/EventScheduleMgr/list.do?mCode=MN214
- 서버렌더 HTML. <li> (event_seq=) 단위로 제목/기간/장소/구분 아이콘 추출.
- 구분 아이콘: ic01=전시(박람회), ic02=회의, ic03=이벤트(공연 등).
  → 전시/박람회(ic01)만 채택. 회의(ic02)는 일반인 무관, 이벤트(ic03 공연)는
  dabom 의 벡스코 콘서트와 중복되므로 제외. ic01 = 모터쇼/보트쇼/엑스포 등
  '어떤 소스도 안 잡던' 카테고리라 순수 신규 커버리지.
- WAF: 브라우저 UA + Referer 필수 (없으면 403).
"""
from __future__ import annotations

import re
import sys
from datetime import date

from sources._adapter import HTTPSession, report
from storage.db import Event

SOURCE = "bexco"
BASE = "https://www.bexco.co.kr"
LIST_URL = BASE + "/kor/CMS/EventScheduleMgr/list.do"
# 행사는 날짜 오름차순(진행중/임박 먼저) → 앞쪽 몇 페이지면 향후 행사 충분히 커버.
MAX_PAGES = 6
# 벡스코 좌표 (해운대 우동)
LAT, LON = 35.1693, 129.1342
ADDRESS = "부산광역시 해운대구 APEC로 55"
NOIMG = "event_noimg"

DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
# 관광·여행 무관 B2B/교육/학술 행사 제외 (소비자 박람회·전시만 남김)
SKIP_RE = re.compile(
    r"콘퍼런스|컨퍼런스|세미나|학술|총회|교사|대입|입시|유학|학원|채용|취업|"
    r"정기총회|워크숍|워크샵|교육혁신|학회|상담캠프"
)

session = HTTPSession(SOURCE, rate_limit_s=0.3, timeout=25, retries=3)
session.s.headers.update({"Referer": BASE + "/kor/Main.do"})


def _iso(y: str, m: str, d: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (TypeError, ValueError):
        return None


def _parse_dates(text: str) -> tuple[str | None, str | None]:
    """'2026-06-27 ~ 2026-07-05' → (start, end). 단일 날짜면 end=start."""
    ms = DATE_RE.findall(text or "")
    if not ms:
        return None, None
    start = _iso(*ms[0])
    end = _iso(*ms[1]) if len(ms) > 1 else start
    return start, end


def _fetch_page(page: int) -> list[Event]:
    r = session.get(LIST_URL, params={"mCode": "MN214", "page": page, "searchID": "sch005"})
    if not r:
        return []
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(r.text, "html.parser")
    events: list[Event] = []
    today = date.today().isoformat()
    for a in soup.find_all("a", href=re.compile(r"event_seq=")):
        li = a.find_parent("li") or a
        m = re.search(r"event_seq=(\d+)", a.get("href", ""))
        if not m:
            continue
        seq = m.group(1)

        # 구분 아이콘 — 전시(ic01)만 채택
        icon = li.select_one(".eventIcon")
        icon_cls = " ".join(icon.get("class", [])) if icon else ""
        icon_txt = icon.get_text(strip=True) if icon else ""
        is_exhibition = ("ic01" in icon_cls) or (icon_txt == "전시")
        if not is_exhibition:
            continue

        title_el = li.select_one(".subject")
        title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
        if not title or len(title) < 2:
            continue
        if SKIP_RE.search(title):  # 관광 무관 B2B/교육 행사 제외
            continue

        date_el = li.select_one(".date")
        start, end = _parse_dates(date_el.get_text(" ", strip=True) if date_el else "")
        # 완전히 지난 행사는 제외 (end < 오늘)
        if end and end < today:
            continue

        place_el = li.select_one(".place")
        place = place_el.get_text(" ", strip=True) if place_el else ""
        venue = f"벡스코 (BEXCO) {place}".strip() if place else "벡스코 (BEXCO)"

        img_el = li.select_one("img[src]")
        img = img_el.get("src") if img_el else None
        if img:
            if NOIMG in img:
                img = None
            elif img.startswith("/"):
                img = BASE + img

        href = a.get("href", "")
        detail = (BASE + "/kor/CMS/EventScheduleMgr/" + href.lstrip("/")) if "view.do" in href else None
        status_el = li.select_one(".day")
        status = status_el.get_text(strip=True) if status_el else None

        events.append(Event(
            source=SOURCE,
            source_id=seq,
            category="festival",
            subtype="박람회",
            title=title,
            start_date=start,
            end_date=end,
            venue=venue,
            address=ADDRESS,
            url=detail,
            image_url=img,
            description=f"벡스코 {place}".strip() + (f" · {status}" if status else ""),
            lat=LAT,
            lon=LON,
            trust_tier="S",
            raw={"event_seq": seq, "place": place, "status": status},
        ))
    return events


def fetch() -> list[Event]:
    events: list[Event] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        page_evs = _fetch_page(page)
        if not page_evs:
            # 빈 페이지 = 더 볼 것 없음 (단, 첫 페이지가 전부 비전시면 계속)
            if page > 1:
                break
            continue
        new = [e for e in page_evs if e.source_id not in seen]
        for e in new:
            seen.add(e.source_id)
        events.extend(new)
    return report(SOURCE, events, pages=min(page, MAX_PAGES))


if __name__ == "__main__":
    for e in fetch():
        print(f"  {e.start_date} ~ {e.end_date}  {e.title:<34} @ {e.venue}")
