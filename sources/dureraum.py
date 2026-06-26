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
from datetime import date

from sources._adapter import HTTPSession, report
from storage.db import Event

LIST_URL = "https://www.dureraum.org/bcc/ccontents/cCaleList.do?rbsIdx=39"
SOURCE = "dureraum"
# 연결 지연 잦은 사이트 — timeout/retry 여유. (ConnectTimeout 으로 0건 수집되던 야간 보강)
session = HTTPSession(SOURCE, timeout=25, retries=3)

# 현재월 + 향후 N개월 캘린더 순회 (param month=M → 표시월 M+1, 연도 롤오버 정상).
# 기존엔 현재월만 긁어 ~6건뿐이었음 → 공연이 dabom 단일 소스에 95% 의존하던 문제 완화.
MONTHS_AHEAD = 5

LAT, LON = 35.1717, 129.1286
VENUE_NAME = "영화의전당"  # _venues.is_major_venue 매칭용
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
    # 현재월 + 향후 MONTHS_AHEAD 개월 순회. 같은 contentsCode 가 여러 월/셀에 걸칠 수
    # 있어 전체에서 days 를 합산(코드 단위 dedupe). 각 페이지는 자기 year/month 로 정확히
    # 날짜를 매기므로 param→표시월 오프셋과 무관하게 self-consistent.
    by_code: dict[str, dict] = {}
    pages_ok = 0
    base = today = date.today()
    for offset in range(0, MONTHS_AHEAD + 1):
        # 목표 표시월 = 현재월 + offset
        idx = (base.year * 12 + base.month - 1) + offset
        ty, tm = idx // 12, idx % 12 + 1
        # param month = 표시월의 직전월 (M-1, 0 → 전년 12월)
        pidx = ty * 12 + (tm - 1) - 1
        py, pm = pidx // 12, pidx % 12 + 1
        url = f"{LIST_URL}&year={py}&month={pm}"
        soup = session.soup(url)
        if not soup:
            continue
        page = _parse_calendar_page(soup)
        if page is None:
            continue
        pages_ok += 1
        for code, rec in page.items():
            cur = by_code.get(code)
            if cur:
                cur["days"].update(rec["days"])
                if len(rec["title"]) > len(cur["title"]):
                    cur["title"] = rec["title"]
            else:
                by_code[code] = rec

    events: list[Event] = []
    today_iso = today.isoformat()
    for code, rec in by_code.items():
        days = sorted(rec["days"])
        end = days[-1] if len(days) > 1 else days[0]
        if end < today_iso:  # 완전히 지난 공연 제외
            continue
        events.append(Event(
            source=SOURCE,
            source_id=code,
            category="performance",
            title=rec["title"],
            start_date=days[0],
            end_date=end,
            venue=VENUE_NAME,
            address=ADDRESS,
            url=f"https://www.dureraum.org/bcc/ccontents/view.do?rbsIdx=40&contentsCode={code}",
            lat=LAT,
            lon=LON,
            trust_tier="S",
            raw={"code": code, "days": days},
        ))
    return report(SOURCE, events, pages=pages_ok)


def _parse_calendar_page(soup) -> dict[str, dict] | None:
    """캘린더 한 페이지(한 달) → {contentsCode: {title, days}}.

    year/month 는 페이지가 자체 표기한 'YYYY.MM' 에서 추출(셀 day 와 동일 페이지 기준).
    YM 미발견 시 None.
    """
    page_text = soup.get_text(" ", strip=True)
    ym_m = YM_RE.search(page_text)
    if not ym_m:
        return None
    year, month = int(ym_m.group(1)), int(ym_m.group(2))

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
            if len(title) > len(rec["title"]):
                rec["title"] = title
        else:
            by_code[code] = {"title": title, "days": {date_iso}}
    return by_code


if __name__ == "__main__":
    for e in fetch():
        print(f"  {e.start_date} ~ {e.end_date}  [{e.subtype or '-':<8}] {e.title}")
