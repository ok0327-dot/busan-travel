"""부산시립미술관 (Busan Museum of Art) 전시 어댑터.

list:   https://art.busan.go.kr/tblTsite07Display/listNowClient.nm   (현재)
        https://art.busan.go.kr/tblTsite07Display/listFutureClient.nm (예정)
detail: /tblTsite07Display/viewNowClient.nm?id=XXX (또는 viewFutureClient.nm)

좌표는 _venues.py 의 부산시립미술관 (35.1699, 129.1385) 사용.
"""
from __future__ import annotations

import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from storage.db import Event

BASE = "https://art.busan.go.kr"
LIST_URLS = [
    (BASE + "/tblTsite07Display/listNowClient.nm",    "viewNowClient"),
    (BASE + "/tblTsite07Display/listFutureClient.nm", "viewFutureClient"),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (busan-travel-bot)"}
SOURCE = "art_busan"

LAT, LON = 35.1699, 129.1385
VENUE_NAME = "부산시립미술관"
ADDRESS = "부산광역시 해운대구 APEC로 58"

# 날짜 범위 형식: "2025-04-15 – 2025-06-29" (em-dash) 또는 "2025-04-15 ~ 2025-06-29"
RANGE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})\s*[–~\-]\s*(\d{4})-(\d{1,2})-(\d{1,2})")


def _parse_detail(detail_url: str) -> dict:
    try:
        r = requests.get(detail_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as exc:
        print(f"[{SOURCE}] detail fail {detail_url}: {exc}", file=sys.stderr)
        return {}
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    # 날짜 범위 — detail 본문 첫 발견 기준
    rm = RANGE_RE.search(text)
    start = end = None
    if rm:
        y1, m1, d1, y2, m2, d2 = rm.groups()
        start = f"{int(y1):04d}-{int(m1):02d}-{int(d1):02d}"
        end   = f"{int(y2):04d}-{int(m2):02d}-{int(d2):02d}"

    # 라벨 기반: '전시장소', '전시부문', '작품수'
    def line_after(label: str) -> str | None:
        m = re.search(rf"^{re.escape(label)}\s*$\n([^\n]+)", text, re.MULTILINE)
        return m.group(1).strip() if m else None

    return {
        "start":   start,
        "end":     end,
        "place":   line_after("전시장소"),
        "section": line_after("전시부문"),
        "works":   line_after("작품수"),
    }


def _fetch_list(list_url: str, view_keyword: str) -> list[Event]:
    try:
        r = requests.get(list_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as exc:
        print(f"[{SOURCE}] list fail {list_url}: {exc}", file=sys.stderr)
        return []
    soup = BeautifulSoup(r.text, "html.parser")

    # title 이 있는 a 태그 (id=N&...) 만 — 빈 wrapper a 는 제외
    seen_ids: set[str] = set()
    events: list[Event] = []
    for a in soup.find_all("a", href=re.compile(view_keyword)):
        href = a.get("href", "")
        m = re.search(r"\?id=(\w+)", href)
        if not m:
            continue
        ex_id = m.group(1)
        if ex_id in seen_ids:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue
        seen_ids.add(ex_id)

        detail_url = (BASE + href) if href.startswith("/") else href
        detail = _parse_detail(detail_url)
        time.sleep(0.3)

        # description 에 작가/장소/부문 합성
        desc_bits = []
        if detail.get("section"):
            desc_bits.append(f"부문: {detail['section']}")
        if detail.get("place"):
            desc_bits.append(f"장소: {detail['place']}")
        if detail.get("works"):
            desc_bits.append(f"작품수: {detail['works']}")
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
            description=description,
            lat=LAT,
            lon=LON,
            trust_tier="S",
            raw={"detail": detail, "view": view_keyword},
        ))
    return events


def fetch() -> list[Event]:
    all_events: list[Event] = []
    for list_url, view_kw in LIST_URLS:
        evs = _fetch_list(list_url, view_kw)
        all_events.extend(evs)
        print(f"[{SOURCE}] {view_kw}: {len(evs)}건", file=sys.stderr)
    print(f"[{SOURCE}] fetched={len(all_events)}", file=sys.stderr)
    return all_events


if __name__ == "__main__":
    for e in fetch():
        print(f"  {e.start_date} ~ {e.end_date}  {e.title:<30} | {(e.description or '')[:50]}")
