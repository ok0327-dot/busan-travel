"""VisitBusan.net 어댑터 — 8개 카테고리 통합.

카테고리 / Category mapping:
- 명소 (attractions):      201001 list → 201001001 detail, Event.category='attraction', source='vb_attraction'
- 음식 (food curated):     201002 list → 201002001 detail, Event.category='food',       source='vb_food'
- 숙박 (lodging):          201004 list → 201004001 detail, Event.category='lodging',    source='vb_lodging' ⭐신규
- 쇼핑 (shopping):         201003 list → 201003001 detail, Event.category='shopping',   source='vb_shopping' ⭐신규
- 축제 (festivals cur.):   201005 list → 201005001 detail, Event.category='festival',   source='vb_festival_curated'
- 테마여행 (themes):       202002 list → 202002001 detail, Event.category='theme',      source='vb_theme'
- 일정여행 (courses):      202012 list → 202012001 detail, vb_courses table,            source='vb_course'
- 축제·행사 보드 (월별):  /schedule/list.do BBS_0000009 → /schedule/view.do dataSid=N, category='festival', source='vb_schedule'

저작권 정책 / Copyright: 사실 데이터만 저장. 본문은 1~2 문장 발췌 + story_url deep-link.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Callable

from bs4 import BeautifulSoup

from sources._parsers import busan_latlon
from sources._visitbusan import (
    BASE,
    VisitBusanClient,
    extract_uc_seq,
    iterate_list,
    parse_detail_page,
    parse_list_page,
    total_count,
)
from storage.db import Event, upsert_course

# ─────────── 제너릭 큐레이션 카테고리 어댑터 ───────────


def _fetch_curated(
    *,
    source: str,
    category: str,
    list_menu: str,
    detail_menu: str,
    page_size: int = 100,
    max_pages: int = 20,
    enrichment: Callable[[dict, Event], None] | None = None,
) -> list[Event]:
    """리스트 → 디테일 크롤 후 Event 리스트 반환. 공통 로직.

    enrichment: 어댑터별 후처리 훅 (e.g. 숙박 subtype, 미식 subtype 추출).
    """
    client = VisitBusanClient()
    try:
        items = iterate_list(client, list_menu, page_size=page_size, max_pages=max_pages)
    except Exception as exc:
        print(f"[{source}] list iter failed: {exc}", file=sys.stderr)
        return []
    print(f"[{source}] list: {len(items)} items", file=sys.stderr)

    events: list[Event] = []
    for i, item in enumerate(items):
        uc = item["uc_seq"]
        try:
            soup = client.get_soup(
                "/kr/index.do",
                {"menuCd": detail_menu, "uc_seq": uc, "lang_cd": "ko"},
            )
            d = parse_detail_page(soup, uc, detail_menu)
        except Exception as exc:
            print(f"[{source}] detail #{uc} failed: {exc}", file=sys.stderr)
            continue

        lat, lon = busan_latlon(d["lat"], d["lon"])
        title = d["title"] or item.get("title")
        if not title:
            continue

        raw = {
            "list_item": item,
            "detail_image_ids": d.get("image_ids", []),
            "subtitle": d.get("subtitle"),
            "like_count": d.get("like_count"),
        }

        ev = Event(
            source=source,
            source_id=str(uc),
            category=category,
            title=title,
            venue=d.get("address"),  # 명소/맛집은 주소 그대로 venue
            address=d.get("address"),
            url=d.get("homepage") or d.get("story_url"),
            image_url=item.get("image_url"),  # 리스트 썸네일이 가장 안정적
            description=d.get("story_excerpt"),
            price=d.get("fee"),
            lat=lat,
            lon=lon,
            rating=d.get("rating"),
            view_count=d.get("view_count"),
            review_count=d.get("review_count"),
            tags_json=json.dumps(d.get("tags", []), ensure_ascii=False) if d.get("tags") else None,
            story_url=d.get("story_url"),
            story_excerpt=d.get("story_excerpt"),
            hours=d.get("hours"),
            holiday=d.get("holiday"),
            fee=d.get("fee"),
            transport=d.get("transport"),
            tip=d.get("tip"),
            etiquette=d.get("etiquette"),
            phone=d.get("phone"),
            raw=raw,
        )
        if enrichment:
            enrichment(d, ev)
        events.append(ev)
        if (i + 1) % 25 == 0:
            print(f"[{source}] progress {i+1}/{len(items)}", file=sys.stderr)
    print(f"[{source}] parsed events: {len(events)}", file=sys.stderr)
    return events


# ─────────── 개별 어댑터 ───────────


def fetch_attractions() -> list[Event]:
    return _fetch_curated(
        source="vb_attraction",
        category="attraction",
        list_menu="DOM_000000201001000000",
        detail_menu="DOM_000000201001001000",
    )


def fetch_food_curated() -> list[Event]:
    return _fetch_curated(
        source="vb_food",
        category="food",
        list_menu="DOM_000000201002000000",
        detail_menu="DOM_000000201002001000",
    )


def fetch_shopping() -> list[Event]:
    return _fetch_curated(
        source="vb_shopping",
        category="shopping",
        list_menu="DOM_000000201003000000",
        detail_menu="DOM_000000201003001000",
    )


def fetch_festival_curated() -> list[Event]:
    return _fetch_curated(
        source="vb_festival_curated",
        category="festival",
        list_menu="DOM_000000201005000000",
        detail_menu="DOM_000000201005001000",
    )


def fetch_themes() -> list[Event]:
    return _fetch_curated(
        source="vb_theme",
        category="theme",
        list_menu="DOM_000000202002000000",
        detail_menu="DOM_000000202002001000",
    )


# ─────────── 숙박 (다른 리스트 레이아웃: 표 형식 + 등급) ───────────


_HOTEL_CLASS_RE = re.compile(r"(관광호텔|휴양콘도|가족호텔|소형호텔|호스텔)\s*(\d성)?")


def _lodging_enrich(detail: dict, ev: Event) -> None:
    """숙박은 리스트 페이지에 등급(5성 등) 정보가 있어 item.raw 에 들어감 → subtype 으로."""
    # 리스트 HTML 의 '관광호텔 5성' 텍스트는 list 에서 별도 파싱 필요 — 여기선 detail text 에서 재추출 시도
    text = (detail.get("subtitle") or "") + " " + (detail.get("title") or "")
    m = _HOTEL_CLASS_RE.search(text)
    if m:
        ev.subtype = (m.group(1) + " " + (m.group(2) or "")).strip()


def fetch_lodging() -> list[Event]:
    """숙박 362건. 리스트 페이지 구조가 달라 별도 파싱 필요."""
    client = VisitBusanClient()
    list_menu = "DOM_000000201004000000"
    detail_menu = "DOM_000000201004001000"

    all_items: list[dict] = []
    seen: set[int] = set()
    for page in range(1, 40):
        soup = client.get_soup(
            "/index.do",
            {"menuCd": list_menu, "page_no": page, "listCntPerPage2": 16},
        )
        items = parse_list_page(soup)
        # .acm_item 래퍼 기반으로 subtype/loc 재추출
        for it in items:
            if it["uc_seq"] in seen:
                continue
            seen.add(it["uc_seq"])
            a = soup.find("a", href=lambda h: h and f"uc_seq={it['uc_seq']}" in h)
            card_text = ""
            if a:
                # .acm_item 래퍼 찾기 (일반 list는 .acm_item 없음 → fallback 상위 li/div)
                card = a.find_parent(class_="acm_item") or a.find_parent(["li", "div"])
                if card:
                    card_text = card.get_text(" | ", strip=True)[:400]
            it["_card_text"] = card_text
            m = _HOTEL_CLASS_RE.search(card_text.replace(" | ", " "))
            it["_subtype"] = (m.group(1) + " " + (m.group(2) or "")).strip() if m else None
            # 지역 추출
            loc_m = re.search(r"부산시\s*[>&gt;]*\s*(\w+구|\w+군)", card_text)
            it["_gugun"] = loc_m.group(1) if loc_m else None
            all_items.append(it)
        total = total_count(soup.get_text(" ", strip=True))
        if total and len(all_items) >= total:
            break
        if len(items) < 5:
            break
    print(f"[vb_lodging] list: {len(all_items)} items", file=sys.stderr)

    events: list[Event] = []
    for i, item in enumerate(all_items):
        uc = item["uc_seq"]
        try:
            soup = client.get_soup(
                "/kr/index.do",
                {"menuCd": detail_menu, "uc_seq": uc, "lang_cd": "ko"},
            )
            d = parse_detail_page(soup, uc, detail_menu)
        except Exception as exc:
            print(f"[vb_lodging] detail #{uc} failed: {exc}", file=sys.stderr)
            continue
        lat, lon = busan_latlon(d["lat"], d["lon"])
        title = d["title"] or item.get("title")
        if not title:
            continue
        ev = Event(
            source="vb_lodging",
            source_id=str(uc),
            category="lodging",
            title=title,
            venue=d.get("address"),
            address=d.get("address"),
            url=d.get("homepage") or d.get("story_url"),
            image_url=item.get("image_url"),
            description=d.get("story_excerpt"),
            lat=lat,
            lon=lon,
            rating=d.get("rating"),
            view_count=d.get("view_count"),
            review_count=d.get("review_count"),
            tags_json=json.dumps(d.get("tags", []), ensure_ascii=False) if d.get("tags") else None,
            story_url=d.get("story_url"),
            story_excerpt=d.get("story_excerpt"),
            phone=d.get("phone"),
            hours=d.get("hours"),
            subtype=item.get("_subtype"),
            raw={"list_item": {k: v for k, v in item.items() if k != "_card_text"}},
        )
        events.append(ev)
        if (i + 1) % 50 == 0:
            print(f"[vb_lodging] progress {i+1}/{len(all_items)}", file=sys.stderr)
    print(f"[vb_lodging] parsed: {len(events)}", file=sys.stderr)
    return events


# ─────────── 일정여행 코스 (별도 테이블 vb_courses) ───────────


_META_SKIP = ("주소", "전화", "홈페이지", "휴무", "운영", "이용", "교통", "주차", "문의")


def _extract_course_pois(soup: BeautifulSoup) -> list[dict]:
    """코스 본문에서 POI 리스트 추출.

    비짓부산 코스 페이지 패턴: 각 POI 블록이 {짧은 이름 줄} + {주소} + {부산광역시 ...} + ...
    '주소' 단독 줄을 앵커로, 바로 다음 줄에 실제 주소, 직전 ~15줄 내 가장 가까운 짧은 이름.
    """
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    pois: list[dict] = []
    seen_names: set[str] = set()
    for i, ln in enumerate(lines):
        if ln != "주소":
            continue
        # 다음 줄: 주소값 ":  부산광역시 ..." 패턴 (콜론/공백 앞쪽 제거)
        if i + 1 >= len(lines):
            continue
        raw = lines[i + 1].lstrip(":").strip()
        if not raw.startswith("부산"):
            continue
        addr = raw
        # 직전 15줄 내 짧은 이름(2~25자)
        name = None
        for back in range(i - 1, max(-1, i - 20), -1):
            candidate = lines[back]
            if not (2 <= len(candidate) <= 25):
                continue
            if any(candidate.startswith(p) for p in _META_SKIP):
                continue
            # "1일차", "2일차", "추천코스" 등 섹션 헤더 제외
            if candidate.endswith("일차") or candidate.startswith("1일") or candidate.startswith("2일"):
                continue
            name = candidate
            break
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        pois.append({"name": name, "address": addr})
    return pois


def fetch_courses_as_table() -> tuple[int, int]:
    """일정여행 48건 → vb_courses 테이블로 업서트. (inserted, updated) 반환."""
    from pathlib import Path

    from config import DB_PATH
    from storage.db import connect

    client = VisitBusanClient()
    list_menu = "DOM_000000202012000000"
    detail_menu = "DOM_000000202012001000"

    items = iterate_list(client, list_menu, page_size=100, max_pages=10)
    print(f"[vb_course] list: {len(items)} items", file=sys.stderr)

    conn = connect(DB_PATH if isinstance(DB_PATH, Path) else Path(DB_PATH))
    ins = upd = 0
    for i, item in enumerate(items):
        uc = item["uc_seq"]
        try:
            soup = client.get_soup(
                "/kr/index.do",
                {"menuCd": detail_menu, "uc_seq": uc, "lang_cd": "ko"},
            )
            d = parse_detail_page(soup, uc, detail_menu)
        except Exception as exc:
            print(f"[vb_course] #{uc} failed: {exc}", file=sys.stderr)
            continue
        pois = _extract_course_pois(soup)
        title = d["title"] or item.get("title") or ""
        # duration 추측: title 에서 "당일/1박2일/2박3일/3박4일" 추출
        dur_m = re.search(r"(당일|1박\s*2일|2박\s*3일|3박\s*4일|무박\s*2일|무박)", title)
        duration = dur_m.group(1) if dur_m else None
        before = conn.execute("SELECT 1 FROM vb_courses WHERE uc_seq=?", (uc,)).fetchone()
        upsert_course(conn, {
            "uc_seq": uc,
            "title": title,
            "subtitle": d.get("subtitle"),
            "duration": duration,
            "rating": d.get("rating"),
            "view_count": d.get("view_count"),
            "image_url": item.get("image_url"),
            "story_url": d.get("story_url"),
            "story_excerpt": d.get("story_excerpt"),
            "tags": d.get("tags", []),
            "pois": pois,
        })
        if before:
            upd += 1
        else:
            ins += 1
        if (i + 1) % 10 == 0:
            print(f"[vb_course] progress {i+1}/{len(items)}", file=sys.stderr)
    print(f"[vb_course] ins={ins} upd={upd}", file=sys.stderr)
    return ins, upd


# ─────────── 축제·행사 보드 (월별) ───────────

_SCHEDULE_DATE_RE = re.compile(r"(\d{4})[.-](\d{1,2})[.-](\d{1,2})")


def fetch_schedule_board() -> list[Event]:
    """축제·행사 보드 BBS_0000009 — 월별 실시간 축제 (현재 ~ +6개월)."""
    client = VisitBusanClient()
    events: list[Event] = []
    seen: set[str] = set()

    # 현재 날짜 기준 전/후 3개월 조회
    from datetime import date, timedelta
    today = date.today()
    months = set()
    for offset_days in range(-30, 181, 30):
        d = today + timedelta(days=offset_days)
        months.add((d.year, d.month))

    for year, month in sorted(months):
        params = {
            "boardId": "BBS_0000009",
            "menuCd": "DOM_000000204012000000",
            "year": str(year),
            "month": str(month),
        }
        try:
            soup = client.get_soup("/schedule/list.do", params)
        except Exception as exc:
            print(f"[vb_schedule] {year}-{month}: {exc}", file=sys.stderr)
            continue
        # 각 일정 카드의 dataSid + 기간 파싱
        for a in soup.select('a[href*="dataSid="]'):
            href = a.get("href") or ""
            m = re.search(r"dataSid=(\d+)", href)
            if not m:
                continue
            sid = m.group(1)
            if sid in seen:
                continue
            seen.add(sid)
            card = a.find_parent(["li", "div"])
            card_text = card.get_text(" ", strip=True) if card else a.get_text(" ", strip=True)
            # 카드 텍스트에서 첫 날짜 전까지가 제목
            first_date = _SCHEDULE_DATE_RE.search(card_text)
            if first_date:
                title = card_text[: first_date.start()].strip()
            else:
                title = card_text.strip()
            if not title or len(title) < 3:
                continue
            # 기간 추출
            dates = _SCHEDULE_DATE_RE.findall(card_text)
            start = end = None
            if len(dates) >= 2:
                start = f"{dates[0][0]}-{int(dates[0][1]):02d}-{int(dates[0][2]):02d}"
                end = f"{dates[1][0]}-{int(dates[1][1]):02d}-{int(dates[1][2]):02d}"
            elif len(dates) == 1:
                start = f"{dates[0][0]}-{int(dates[0][1]):02d}-{int(dates[0][2]):02d}"
                end = start
            detail_url = BASE + "/schedule/view.do?boardId=BBS_0000009&menuCd=DOM_000000204012000000&dataSid=" + sid
            events.append(Event(
                source="vb_schedule",
                source_id=sid,
                category="festival",
                title=title,
                start_date=start,
                end_date=end,
                url=detail_url,
                story_url=detail_url,
                raw={"card_text": card_text[:200]},
            ))
    print(f"[vb_schedule] parsed: {len(events)}", file=sys.stderr)
    return events
