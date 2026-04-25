"""네이버 동네 신상 식당/카페 어댑터 — Naver local search API.

`https://openapi.naver.com/v1/search/local.json` (NAVER_CLIENT_ID/SECRET 필요).
'부산 신상 카페' / '부산 새로 생긴 맛집' 같은 키워드 매트릭스로 신상 가게 발굴.
trust_tier='B' (검색 기반, 단 신상 정보로서 가치 있음 — UI 에 '🆕 신규' 라벨).

좌표: mapx/mapy 가 WGS84 * 10000000 정수형. lat = mapy/1e7, lon = mapx/1e7.
category: "음식점>한식" / "카페,디저트>카페" 형식 → food/cafe 매핑.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import sys
from pathlib import Path

import requests

from sources._parsers import busan_latlon
from storage.db import Event

ENDPOINT = "https://openapi.naver.com/v1/search/local.json"
SOURCE_PREFIX = "naver_local"

# 신상 키워드 매트릭스 — 카페 + 음식 종류별 specific (식당 hit rate ↑) + 지역별
KEYWORDS = [
    # 카페 일반·지역
    "부산 신상 카페", "부산 새로 생긴 카페", "부산 신규 카페",
    "해운대 신상 카페", "광안리 신상 카페", "서면 신상 카페",
    "전포 신상 카페", "기장 신상 카페", "영도 신상 카페",
    # 식당 — 음식 종류별 specific (일반 '맛집' 키워드는 카페로 편향됨)
    "부산 신상 한식", "부산 신상 일식", "부산 신상 양식",
    "부산 신상 분식", "부산 신상 횟집", "부산 신상 고깃집",
    "부산 신상 라멘", "부산 신상 파스타", "부산 신상 베이커리",
    "부산 새로 오픈 식당", "부산 새로 오픈 맛집",
    # 지역별 식당
    "해운대 신상 맛집", "광안리 신상 맛집", "서면 신상 맛집",
    "남포동 신상 맛집",
]

_TAG_RE = re.compile(r"<[^>]+>")
_KOREAN_RE = re.compile(r"[가-힣]")


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return html.unescape(_TAG_RE.sub("", s)).strip()


def _load_creds() -> tuple[str | None, str | None]:
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if cid and csec:
        return cid, csec
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            s = line.strip()
            if s.startswith("NAVER_CLIENT_ID="):
                cid = cid or s.split("=", 1)[1].strip().strip('"').strip("'")
            elif s.startswith("NAVER_CLIENT_SECRET="):
                csec = csec or s.split("=", 1)[1].strip().strip('"').strip("'")
    return cid, csec


def _classify(category: str) -> str | None:
    """NAVER category path → food/cafe. 음식·카페가 아니면 None (drop).

    "카페,디저트>*" 또는 "음식점>카페,디저트" → cafe
    "음식점>한식/일식/중식/..." → food
    그 외 (PC방/경영컨설팅/병원/오락 등) → None
    """
    c = category or ""
    if any(k in c for k in ("카페", "디저트", "베이커리", "빵집")):
        return "cafe"
    # 명시적 음식 카테고리만 food (NAVER category 첫 path 가 '음식점' 인 경우)
    if c.startswith("음식점") or any(k in c for k in ("한식", "일식", "중식", "양식", "분식", "주점", "패스트푸드", "뷔페")):
        return "food"
    return None  # 음식/카페가 아닌 결과 (PC방/오락/서비스 등) → drop


def _coord(mapx: str | None, mapy: str | None) -> tuple[float | None, float | None]:
    """mapx/mapy(WGS84*1e7 정수형) → (lat, lon). 부산 bbox 검증."""
    try:
        lon = float(mapx) / 1e7
        lat = float(mapy) / 1e7
    except (ValueError, TypeError):
        return None, None
    return busan_latlon(lat, lon)  # bbox 검증 + 정상화


def _fetch_one(query: str, cid: str, csec: str, display: int = 5) -> list[dict]:
    """단일 키워드 — display=5 (NAVER local 최대), sort=comment(정확도)."""
    try:
        r = requests.get(
            ENDPOINT,
            params={"query": query, "display": display, "sort": "comment"},
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
            timeout=12,
        )
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as exc:
        print(f"[{SOURCE_PREFIX}] '{query}' err: {exc}", file=sys.stderr)
        return []


def _to_event(item: dict, query: str) -> Event | None:
    title = _clean(item.get("title"))
    if not title or not _KOREAN_RE.search(title):
        return None
    addr = _clean(item.get("roadAddress")) or _clean(item.get("address"))
    if "부산" not in addr:
        return None  # 부산 외 결과 (다른 도시 체인점) 제외
    lat, lon = _coord(item.get("mapx"), item.get("mapy"))
    if lat is None or lon is None:
        return None  # 좌표 없거나 부산 bbox 외 — drop
    cat_raw = _clean(item.get("category"))
    category = _classify(cat_raw)
    if category is None:
        return None  # 음식/카페 외 카테고리 (PC방/경영컨설팅 등) drop
    link = _clean(item.get("link"))
    # source_id: link MD5 (link 있으면) 또는 title+addr MD5
    key = link if link else f"{title}|{addr}"
    sid = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    # gugun 추출 (주소 두 번째 단어)
    gugun = None
    parts = addr.split()
    if len(parts) >= 2 and parts[1].endswith(("구", "군")):
        gugun = parts[1]
    return Event(
        source=SOURCE_PREFIX,
        source_id=sid,
        category=category,
        title=title,
        venue=None,
        address=addr,
        url=link or None,
        description=cat_raw,  # NAVER 카테고리 그대로 (음식점>카페,디저트 등)
        lat=lat,
        lon=lon,
        gugun=gugun,
        trust_tier="B",  # 검색기반 — 단 신상 정보 가치
        subtype="신상",   # UI 에서 🆕 라벨 트리거
        raw={"q": query, "category": cat_raw, "phone": item.get("telephone")},
    )


def fetch() -> list[Event]:
    cid, csec = _load_creds()
    if not cid or not csec:
        print(f"[{SOURCE_PREFIX}] SKIP: NAVER_CLIENT_ID/SECRET 미설정", file=sys.stderr)
        return []
    seen_ids: set[str] = set()
    events: list[Event] = []
    for q in KEYWORDS:
        for item in _fetch_one(q, cid, csec):
            ev = _to_event(item, q)
            if not ev or ev.source_id in seen_ids:
                continue
            seen_ids.add(ev.source_id)
            events.append(ev)
    print(f"[{SOURCE_PREFIX}] fetched={len(events)} from {len(KEYWORDS)} keywords", file=sys.stderr)
    return events


if __name__ == "__main__":
    for e in fetch():
        print(f"  [{e.category}] {e.title:<25} | {e.gugun or '?':<5} | {e.address[:40]}")
