"""네이버 '우리동네' 인기 맛집/카페 어댑터 — 동(洞) 생활권 큐레이션.

naver_local(신상 발굴)과 달리, 특정 동네(대연동 등)의 **확립된 인기 맛집/카페**를
지역 키워드 × sort=comment(리뷰 많은 순)로 폭넓게 수집한다. m.naver.com '우리동네'
탭이 보여주는 동네 대표 맛집 커버리지를 근사.

- api-vault search_local(쿼리당 max 5, 페이지네이션 불가) → 동별 다양한 키워드로 보강.
- 프랜차이즈/체인 제외(_is_franchise), 보드/키즈카페 등 비식음 cafe 오분류 차단(_classify).
- subtype=None (신상 아님 → 🆕 라벨 트리거 X). trust_tier='B'.
- popularity_score 는 enrich_ratings(네이버 블로그 언급 수) 보강 후 export 에서 동적 계산.

NEIGHBORHOODS 에 동을 추가하면 그대로 확장된다(현재: 대연동+인근 경성대·부경대·못골).
"""
from __future__ import annotations

import hashlib
import sys

from api_vault.core.caller import ApiAuthError, ApiRateLimitError
from api_vault.tools.call import api_call

from sources.naver_local import (
    _KOREAN_RE,
    _classify,
    _clean,
    _coord,
    _is_franchise,
)
from storage.db import Event

SOURCE_PREFIX = "naver_neighborhood"

# 동(洞) 생활권 설정 — 확장 가능. queries 는 쿼리당 5건이므로 종류별로 분산.
NEIGHBORHOODS: dict[str, dict] = {
    "대연동": {
        "gugun": "남구",
        # 주소가 이 토큰 중 하나를 포함해야 채택(타지 동명/엉뚱한 결과 배제)
        "addr_tokens": ("대연", "경성대", "부경대", "못골", "유엔", "문현"),
        "queries": [
            "대연동 맛집", "대연동 카페", "대연동 밥집", "대연동 술집", "대연동 디저트",
            "대연동 횟집", "대연동 고기집", "대연동 국밥", "대연동 일식", "대연동 분식",
            "대연동 파스타", "대연동 베이커리",
            "경성대 맛집", "경성대 카페", "부경대 맛집", "못골시장 맛집",
        ],
    },
}


def _fetch_one(query: str, display: int = 5) -> list[dict]:
    """api-vault search_local 라우팅. display=5(max), sort=comment(리뷰 많은 순)."""
    result = api_call("search_local", "local", query=query, display=display, sort="comment")
    if result.get("result_code") != "00":
        msg = (result.get("result_msg") or "")[:80]
        print(f"[{SOURCE_PREFIX}] '{query}' err: {result.get('result_code')} {msg}", file=sys.stderr)
        return []
    return result.get("items", [])


def _to_event(item: dict, query: str, dong: str, cfg: dict) -> Event | None:
    title = _clean(item.get("title"))
    if not title or not _KOREAN_RE.search(title):
        return None
    if _is_franchise(title):
        return None  # 프랜차이즈/체인 제외
    addr = _clean(item.get("roadAddress")) or _clean(item.get("address"))
    if "부산" not in addr:
        return None
    # 동 생활권 한정 — gugun 일치 또는 주소 토큰 매칭
    if cfg["gugun"] not in addr and not any(t in addr for t in cfg["addr_tokens"]):
        return None
    lat, lon = _coord(item.get("mapx"), item.get("mapy"))
    if lat is None or lon is None:
        return None
    cat_raw = _clean(item.get("category"))
    category = _classify(cat_raw)
    if category is None:
        return None  # 음식/카페 외 (보드카페/PC/서비스 등) drop
    link = _clean(item.get("link"))
    key = link if link else f"{title}|{addr}"
    sid = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    gugun = cfg["gugun"]
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
        description=cat_raw,
        lat=lat,
        lon=lon,
        gugun=gugun,
        trust_tier="B",
        subtype=None,  # 신상 아님 — 동네 확립 맛집
        raw={"q": query, "category": cat_raw, "phone": item.get("telephone"), "neighborhood": dong},
    )


def fetch() -> list[Event]:
    seen_ids: set[str] = set()
    events: list[Event] = []
    for dong, cfg in NEIGHBORHOODS.items():
        for q in cfg["queries"]:
            try:
                items = _fetch_one(q)
            except ApiAuthError as exc:
                print(f"[{SOURCE_PREFIX}] 인증 실패 (NAVER_CLIENT_* 키/'지역' 권한 점검): {exc}", file=sys.stderr)
                return events
            except ApiRateLimitError as exc:
                print(f"[{SOURCE_PREFIX}] daily 25k limit 도달: {exc}", file=sys.stderr)
                return events
            for item in items:
                ev = _to_event(item, q, dong, cfg)
                if not ev or ev.source_id in seen_ids:
                    continue
                seen_ids.add(ev.source_id)
                events.append(ev)
    print(f"[{SOURCE_PREFIX}] fetched={len(events)} from "
          f"{sum(len(c['queries']) for c in NEIGHBORHOODS.values())} queries", file=sys.stderr)
    return events


if __name__ == "__main__":
    for e in fetch():
        print(f"  [{e.category}] {e.title:<22} | {e.gugun or '?':<4} | {e.address[:42]}")
