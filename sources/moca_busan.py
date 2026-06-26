"""부산현대미술관(MoCA) 전시 어댑터.

URL: https://www.busan.go.kr/moca/exhibition01 (현재 + 예정 + 상설 전시)
detail: /moca/exhibition01/{id} → 전시시작일/전시종료일/전시장소/참여작가 라벨 파싱

좌표는 sources/_venues.py 의 부산현대미술관 (35.1021, 128.9991) 사용.
"""
from __future__ import annotations

import re
import sys

from sources._adapter import HTTPSession, report
from storage.db import Event

LIST_URL = "https://www.busan.go.kr/moca/exhibition01"
BASE = "https://www.busan.go.kr"
SOURCE = "moca_busan"
session = HTTPSession(SOURCE, rate_limit_s=0.3, timeout=25, retries=3)

LAT, LON = 35.1021, 128.9991
VENUE_NAME = "부산현대미술관"
ADDRESS = "부산광역시 사하구 낙동남로 1191"

DATE_RE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")
LABELS = ("전시시작일", "전시종료일", "전시장소", "참여작가", "전시담당", "출품작")


def _parse_date(s: str | None) -> str | None:
    if not s:
        return None
    m = DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def _line_after(text: str, label: str) -> str | None:
    """detail text 에서 label 다음 줄 값. label 만 단독 줄에 있는 경우 매칭."""
    m = re.search(rf"^{re.escape(label)}\s*$\n([^\n]+)", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _parse_detail(detail_url: str) -> dict:
    soup = session.soup(detail_url)
    if not soup:
        return {}
    text = soup.get_text("\n", strip=True)
    return {
        "start":   _parse_date(_line_after(text, "전시시작일")),
        "end":     _parse_date(_line_after(text, "전시종료일")),
        "place":   _line_after(text, "전시장소"),
        "artists": _line_after(text, "참여작가"),
    }


def fetch() -> list[Event]:
    soup = session.soup(LIST_URL)
    if not soup:
        return []
    wrap = soup.find("div", class_="thumbListType1Wrap")
    if not wrap:
        print(f"[{SOURCE}] no thumbListType1Wrap in list page", file=sys.stderr)
        return []

    events: list[Event] = []
    for li in wrap.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        m = re.search(r"/exhibition01/(\d+)", a["href"])
        if not m:
            continue
        ex_id = m.group(1)
        detail_url = (BASE + a["href"]) if a["href"].startswith("/") else a["href"]
        title_el = li.find(["strong", "h3", "h4", "dt"])
        title = (title_el.get_text(strip=True) if title_el else "").strip()
        if not title:
            continue
        img = li.find("img")
        image_url = None
        if img and img.get("src"):
            image_url = (BASE + img["src"]) if img["src"].startswith("/") else img["src"]

        detail = _parse_detail(detail_url)

        # description: 참여작가 + 전시장소 (장소 정보가 detail 본문에 풍부)
        desc_bits = []
        if detail.get("artists"):
            desc_bits.append(f"참여작가: {detail['artists']}")
        if detail.get("place"):
            desc_bits.append(f"전시장소: {detail['place']}")
        description = " · ".join(desc_bits) if desc_bits else None

        events.append(Event(
            source=SOURCE,
            source_id=ex_id,
            category="exhibition",
            title=title,
            start_date=detail.get("start"),
            end_date=detail.get("end"),
            venue=VENUE_NAME,
            address=ADDRESS,
            url=detail_url,
            image_url=image_url,
            description=description,
            lat=LAT,
            lon=LON,
            trust_tier="S",
            raw={"detail": detail, "href": a["href"]},
        ))
    return report(SOURCE, events)


if __name__ == "__main__":
    for e in fetch():
        print(f"  {e.start_date} ~ {e.end_date}  {e.title}")
