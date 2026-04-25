"""영화의전당 공연 어댑터.

list: https://www.dureraum.org/bcc/ccontents/cCaleList.do?rbsIdx=39 (월 캘린더)
- 캘린더 표 td 의 a[href*=contentsCode] + a.text 에서 시간 + title 직접 추출
- detail page (view.do) 는 referer/tab 검증으로 빈 응답 → 사용 안 함
- year/month 는 페이지 헤더의 'YYYY.MM' 패턴에서 추출
- day 는 td 의 첫 숫자 (1~31)
- 같은 contentsCode 가 여러 셀에 있으면 시작/종료일 합쳐서 산출
"""
from __future__ import annotations

import re
import sys

import requests
from bs4 import BeautifulSoup

from storage.db import Event

LIST_URL = "https://www.dureraum.org/bcc/ccontents/cCaleList.do?rbsIdx=39"
HEADERS = {"User-Agent": "Mozilla/5.0 (busan-travel-bot)"}
SOURCE = "dureraum"

LAT, LON = 35.1717, 129.1286
VENUE_NAME = "영화의전당"  # MAJOR_VENUES 매칭용
ADDRESS = "부산광역시 해운대구 수영강변대로 120"

CODE_RE = re.compile(r"contentsCode=([\w]+)")
YM_RE = re.compile(r"(20\d{2})[.\s\-/]+(\d{1,2})")
TIME_PREFIX_RE = re.compile(r"^[\d;:\s,~ㅣ월화수목금토일토요일\|\(\)앙코르]+")


def _clean_title(raw_text: str) -> str:
    """a.text 의 시간/요일 prefix 제거. '19:30제44회 부산연극제…' → '제44회 부산연극제…'."""
    s = raw_text.strip()
    # 시간 패턴 (HH:MM 또는 HH;MM) 후 모든 한글 시작점까지 prefix 제거
    s = re.sub(r"^(\d{1,2}[:;]\d{2}\s*)+", "", s)
    # 요일/구분자 prefix
    s = re.sub(r"^[ㅣ\|토일월화수목금\s\d:;,~]+", "", s)
    return s.strip()


def fetch() -> list[Event]:
    try:
        r = requests.get(LIST_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as exc:
        print(f"[{SOURCE}] list fail: {exc}", file=sys.stderr)
        return []
    soup = BeautifulSoup(r.text, "html.parser")

    # year/month 추출 — 페이지 첫 'YYYY.MM' 매칭
    page_text = soup.get_text(" ", strip=True)
    ym_m = YM_RE.search(page_text)
    if not ym_m:
        print(f"[{SOURCE}] year/month not found", file=sys.stderr)
        return []
    year, month = int(ym_m.group(1)), int(ym_m.group(2))

    # 같은 contentsCode 가 여러 td 셀에 있을 수 있음 → 시작/종료일 합산
    by_code: dict[str, dict] = {}
    for td in soup.find_all("td"):
        a = td.find("a", href=re.compile(r"contentsCode="))
        if not a:
            continue
        code_m = CODE_RE.search(a["href"])
        if not code_m:
            continue
        code = code_m.group(1)

        # 첫 숫자 = day (1~31)
        td_text = td.get_text(" ", strip=True)
        day_m = re.match(r"^[^\d]*(\d{1,2})", td_text)
        if not day_m:
            continue
        day = int(day_m.group(1))
        if not (1 <= day <= 31):
            continue
        date_iso = f"{year:04d}-{month:02d}-{day:02d}"

        title = _clean_title(a.get_text(strip=True))
        if not title or len(title) < 3:
            continue

        rec = by_code.get(code)
        if rec:
            rec["days"].add(date_iso)
            # title 더 긴 게 있으면 채택 (정보 풍부)
            if len(title) > len(rec["title"]):
                rec["title"] = title
        else:
            by_code[code] = {"title": title, "days": {date_iso}}

    events: list[Event] = []
    for code, rec in by_code.items():
        days = sorted(rec["days"])
        events.append(Event(
            source=SOURCE,
            source_id=code,
            category="performance",
            title=rec["title"],
            start_date=days[0],
            end_date=days[-1] if len(days) > 1 else days[0],
            venue=VENUE_NAME,
            address=ADDRESS,
            url=f"https://www.dureraum.org/bcc/ccontents/view.do?rbsIdx=40&contentsCode={code}",
            lat=LAT,
            lon=LON,
            trust_tier="S",
            raw={"code": code, "year": year, "month": month, "days": days},
        ))
    print(f"[{SOURCE}] fetched={len(events)} (year={year} month={month})", file=sys.stderr)
    return events


if __name__ == "__main__":
    for e in fetch():
        print(f"  {e.start_date} ~ {e.end_date}  [{e.subtype or '-':<8}] {e.title}")
