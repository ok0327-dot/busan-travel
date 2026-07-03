"""부산 근교(경남 + 경주) 축제 — 한국관광공사 TourAPI 4.0 searchFestival2.

부산 이벤트 DB(SQLite)와 완전히 분리된 독립 파이프라인.
Standalone from the Busan events DB — this feeds a dedicated
`nearby-festivals.json` consumed by a separate "근교 축제" section, so it never
pollutes the Busan map markers / category filters / month shards.

지역 커버리지 / Region coverage:
- 경상남도(Gyeongnam) 전역: areaCode=36 (김해·양산·창원·거제·통영 등 부산 인접 도시 포함)
- 경주(Gyeongju): 경상북도(areaCode=35) sigunguCode=2

TourAPI 특이사항(gov_tour.py 와 동일):
- resultCode 가 "0000" (4자)
- JSON 은 _type=json / MobileOS·MobileApp 필수
- 좌표는 mapx=경도(lon), mapy=위도(lat), WGS84 → 그대로 사용 (부산 bbox clamp 금지)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from sources._gov_api import call_api
from sources._parsers import to_float

API_ID = "15101578"
OP = "searchFestival2"
MOBILE_APP = "busan-travel"
OK_CODES = {"00", "0000"}

# (라벨, areaCode, sigunguCode) — sigunguCode=None 이면 도(道) 전역
REGIONS = [
    ("경남", "36", None),   # 경상남도 전역
    ("경주", "35", "2"),    # 경상북도 경주시
]


def _ymd(s: str | None) -> str | None:
    """TourAPI YYYYMMDD → YYYY-MM-DD."""
    if not s or len(s) != 8 or not s.isdigit():
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _short_region(default_label: str, addr1: str | None) -> str:
    """도(道) 전역 수집 시 주소에서 시/군을 뽑아 짧은 라벨로.

    "경상남도 김해시 …" → "김해", "경상남도 거제시 …" → "거제".
    경주처럼 이미 시 단위면 default_label 그대로.
    """
    if default_label != "경남":
        return default_label
    if not addr1:
        return default_label
    parts = addr1.split()
    if len(parts) >= 2 and (parts[1].endswith("시") or parts[1].endswith("군")):
        return parts[1][:-1]  # "김해시" → "김해"
    return default_label


def _parse_item(raw: dict, region_label: str) -> dict:
    lat = to_float(raw.get("mapy"))
    lon = to_float(raw.get("mapx"))
    addr1 = (raw.get("addr1") or "").strip() or None
    return {
        "id": f"nearby-{raw.get('contentid') or ''}",
        "category": "festival",
        "region": _short_region(region_label, addr1),
        "title": (raw.get("title") or "").strip(),
        "start": _ymd(raw.get("eventstartdate")),
        "end": _ymd(raw.get("eventenddate")),
        "venue": (raw.get("eventplace") or "").strip() or None,
        "address": addr1,
        "image": (raw.get("firstimage") or "").strip() or None,
        "tel": (raw.get("tel") or "").strip() or None,
        "lat": lat,
        "lon": lon,
    }


def _fetch_region(label: str, area_code: str, sigungu: str | None,
                  start_ymd: str, max_pages: int, page_size: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        params = dict(
            pageNo=page, numOfRows=page_size,
            MobileOS="ETC", MobileApp=MOBILE_APP, _type="json",
            arrange="C", eventStartDate=start_ymd, areaCode=area_code,
        )
        if sigungu:
            params["sigunguCode"] = sigungu
        r = call_api(API_ID, OP, **params)
        code = r["result_code"]
        if code == "PENDING":
            print(f"[nearby_festival:{label}] SKIP: {r['result_msg']}", file=sys.stderr)
            return out
        if code not in OK_CODES:
            print(f"[nearby_festival:{label}] page={page} err={code} {r['result_msg']}", file=sys.stderr)
            break
        items = r["items"]
        if not items:
            break
        for it in items:
            cid = str(it.get("contentid") or "")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(_parse_item(it, label))
        if len(items) < page_size:
            break
    return out


def fetch(max_pages: int = 10, page_size: int = 100, lookback_days: int = 30) -> list[dict]:
    """진행 중 + 다가오는 경남·경주 축제.

    eventStartDate 를 lookback_days 전으로 잡아 '진행 중'(start<=today<=end) 축제도 포함하고,
    최종적으로 end_date >= today 인 것만 남긴다(이미 끝난 축제 제거).
    반환은 프론트가 바로 쓰는 dict(JSON) 리스트, 시작일 오름차순 정렬.
    """
    start_ymd = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    today = date.today().isoformat()

    merged: dict[str, dict] = {}
    for label, area, sigungu in REGIONS:
        for ev in _fetch_region(label, area, sigungu, start_ymd, max_pages, page_size):
            if ev["id"] not in merged:
                merged[ev["id"]] = ev

    # 이미 종료된 축제 제거 (end 없으면 start 기준으로 판단, 둘 다 없으면 유지)
    def _alive(ev: dict) -> bool:
        end = ev.get("end") or ev.get("start")
        return (end is None) or (end >= today)

    festivals = [ev for ev in merged.values() if ev["title"] and _alive(ev)]
    festivals.sort(key=lambda e: (e.get("start") or "9999-99-99", e.get("title") or ""))
    return festivals
