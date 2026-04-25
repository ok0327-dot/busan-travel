"""부산문화포털 다봄 (busandabom.net) — 부산 전체 공연·전시 통합 포털.

정적 HTML 리스트 페이지 + 페이지네이션(page=1..N).
각 카드에서 res_no, 카테고리(연극/뮤지컬/전시/…), 제목, 기간, 장소, 이미지 추출.
좌표는 sources/_venues.py 의 guess_venue_coords 로 부여.
동적 JS 없음 → requests 만으로 충분.
"""
from __future__ import annotations

import html as _html
import re
import sys

import requests

from sources._venues import guess_venue_coords
from storage.db import Event

LIST_URL = "https://busandabom.net/play/list.nm"
BASE = "https://busandabom.net"
from sources._http import DEFAULT_HEADERS as HEADERS  # 한국 사이트 봇 차단 우회
SOURCE = "dabom"
MAX_PAGES = 30  # 총 16페이지(159건) 전후, 여유 있게

DATE_RANGE_RE = re.compile(r"(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})")
FN_VIEW_RE = re.compile(r"fn_view\('(\d+)'\)")
IMG_RE = re.compile(r'src="(/images/contents/[^"]+)"')
LI_RE = re.compile(r"<li[^>]*>.*?</li>", re.DOTALL)

# 다봄 카테고리 라벨 → 우리 카테고리
EXHIBITION_TAGS = ("전시", "미술", "조각", "사진전")
PERFORMANCE_TAGS = (
    "연극", "뮤지컬", "콘서트", "클래식", "국악", "무용",
    "공연", "오페라", "발레", "대중음악", "복합",
)


def _classify(category_tag: str | None, title: str) -> str:
    blob = f"{category_tag or ''} {title}"
    if any(k in blob for k in EXHIBITION_TAGS):
        return "exhibition"
    return "performance"


def _parse_date(s: str | None) -> str | None:
    return s.replace(".", "-") if s else None


def _extract_list_section(html: str) -> str:
    start = html.find('class="boardlist type1">')
    if start < 0:
        return ""
    end = html.find("</ul>", start)
    return html[start:end] if end > start else ""


def _parse_li(li: str) -> dict | None:
    m = FN_VIEW_RE.search(li)
    if not m:
        return None
    res_no = m.group(1)
    text = re.sub(r"<[^>]+>", "|", li)
    text = re.sub(r"\|+", "|", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _html.unescape(text)
    # 카테고리 (장르 태그 단독 블록) — 텍스트 초반 pipe-split 토큰 중 매칭
    cat_tag = None
    tokens = [t.strip() for t in text.split("|") if t.strip()]
    for tok in tokens[:8]:
        if tok in EXHIBITION_TAGS + PERFORMANCE_TAGS:
            cat_tag = tok
            break
    # 제목: 꺾쇠 감싼 부분 우선, 아니면 기간 직전 토큰
    m_title = re.search(r"<([^<>]+)>", text)
    title = m_title.group(1).strip() if m_title else None
    if not title:
        m_dt_idx = None
        for i, tok in enumerate(tokens):
            if DATE_RANGE_RE.search(tok):
                m_dt_idx = i
                break
        if m_dt_idx and m_dt_idx > 0:
            title = tokens[m_dt_idx - 1].strip("<>")
    # 기간
    m_dt = DATE_RANGE_RE.search(text)
    start_d = _parse_date(m_dt.group(1)) if m_dt else None
    end_d = _parse_date(m_dt.group(2)) if m_dt else None
    # 장소: 기간 토큰 이후의 가장 가까운 비어있지 않은 토큰
    venue = None
    if m_dt:
        after = text[m_dt.end():]
        after_tokens = [t.strip() for t in after.split("|") if t.strip()]
        for tok in after_tokens[:4]:
            if re.fullmatch(r"[\d.]+", tok):
                continue  # 평점 0.0
            if len(tok) > 1 and not tok.startswith("D-") and "후" not in tok:
                venue = tok
                break
    # 이미지
    m_img = IMG_RE.search(li)
    image = f"{BASE}{m_img.group(1)}" if m_img else None
    return {
        "res_no": res_no,
        "cat_tag": cat_tag,
        "title": title,
        "start": start_d,
        "end": end_d,
        "venue": venue,
        "image": image,
    }


def _fetch_page(page: int) -> list[dict]:
    try:
        r = requests.get(
            LIST_URL,
            params={"menuCd": 5, "page": page},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"[{SOURCE}] page {page} fail: {exc}", file=sys.stderr)
        return []
    section = _extract_list_section(r.text)
    if not section:
        return []
    items = []
    for li in LI_RE.findall(section):
        parsed = _parse_li(li)
        if parsed:
            items.append(parsed)
    return items


def fetch() -> list[Event]:
    events: list[Event] = []
    seen_ids: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        items = _fetch_page(page)
        if not items:
            break
        # 페이지네이션 끝 감지: 첫 ID 가 이전에 본 것이면 순환
        if items[0]["res_no"] in seen_ids:
            break
        new_count = 0
        for it in items:
            if not it["title"] or not it["res_no"]:
                continue
            if it["res_no"] in seen_ids:
                continue
            seen_ids.add(it["res_no"])
            new_count += 1
            category = _classify(it["cat_tag"], it["title"])
            venue = it["venue"]
            _, lat, lon = guess_venue_coords(venue, it["title"])
            detail_url = f"{BASE}/play/view.nm?menuCd=5&res_no={it['res_no']}"
            events.append(Event(
                source=SOURCE,
                source_id=it["res_no"],
                category=category,
                title=it["title"],
                start_date=it["start"],
                end_date=it["end"],
                venue=venue,
                address=None,
                url=detail_url,
                image_url=it["image"],
                description=(f"[{it['cat_tag']}] {venue}" if it["cat_tag"] and venue else None),
                lat=lat,
                lon=lon,
                trust_tier="S",
                raw={"cat_tag": it["cat_tag"]},
            ))
        if new_count == 0:
            break
    print(f"[{SOURCE}] fetched={len(events)}", file=sys.stderr)
    return events


if __name__ == "__main__":
    for e in fetch()[:10]:
        print(f"  {e.start_date}~{e.end_date}  [{e.category}] {e.title}  @ {e.venue}")
