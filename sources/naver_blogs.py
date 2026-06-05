"""Official Busan Naver blogs via RSS.

- cooolbusan  : 부산광역시 대표 블로그
- bscf2009    : 부산문화재단
- hudpr       : 해운대구청

RSS pattern: https://rss.blog.naver.com/{id}.xml
Each entry: title, link (.../{blogid}/{postid}), pubDate, category, description(HTML)
"""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

import feedparser

from config import NAVER_OFFICIAL_BLOGS
from storage.db import Event

SOURCE_PREFIX = "naver_blog"
RSS_TEMPLATE = "https://rss.blog.naver.com/{id}.xml"

# 부산시청 블로그(cooolbusan)는 88%가 시정 홍보라 전체 DROP(_tour_filter.DROP_SOURCES).
# 단 '부산여행' 카테고리(여행탭, categoryNo=42)는 알짜 여행 콘텐츠 → 별도 허용 소스로 라우팅.
# (모집/공모 등 잔여 노이즈는 NEGATIVE_KEYWORDS 로 이중 차단)
CITY_BLOG_ID = "cooolbusan"
TRAVEL_CATEGORY = "부산여행"
CITY_TRAVEL_SOURCE_ID = "cooolbusan_travel"
# 여행 카테고리 안에 섞인 모집/공모성 노이즈는 여행 소스로 승격하지 않음(→ DROP 유지).
_CITY_TRAVEL_NOISE = ("모집", "공모", "설명회", "간담회", "위촉", "채용", "선정 결과", "선정결과")

_TAG_RE = re.compile(r"<[^>]+>")
_POST_ID_RE = re.compile(r"/(\d+)(?:\?|$)")


def _strip_html(s: str | None, limit: int = 400) -> str | None:
    if not s:
        return None
    text = _TAG_RE.sub("", s).strip()
    return text[:limit] if text else None


def _post_id(link: str) -> str | None:
    m = _POST_ID_RE.search(link or "")
    return m.group(1) if m else None


def _classify(category: str | None, title: str) -> str:
    blob = f"{category or ''} {title}".lower()
    if any(k in blob for k in ["축제", "페스티벌", "festival"]):
        return "festival"
    if any(k in blob for k in ["전시", "exhibition"]):
        return "exhibition"
    if any(k in blob for k in ["공연", "콘서트", "뮤지컬", "performance"]):
        return "performance"
    return "blog_post"


def _iso(pubdate: str | None) -> str | None:
    if not pubdate:
        return None
    try:
        return parsedate_to_datetime(pubdate).date().isoformat()
    except (TypeError, ValueError):
        return None


def fetch() -> list[Event]:
    events: list[Event] = []
    for blog_id, label in NAVER_OFFICIAL_BLOGS:
        parsed = feedparser.parse(RSS_TEMPLATE.format(id=blog_id))
        for entry in parsed.entries:
            post_id = _post_id(entry.get("link", "")) or entry.get("id") or entry.get("title", "")
            category = entry.get("category")
            # cooolbusan(시청)은 '부산여행' 카테고리만 허용 소스로 분리, 나머지는 DROP 소스 유지.
            src_id = blog_id
            if blog_id == CITY_BLOG_ID and (category or "").strip() == TRAVEL_CATEGORY:
                _title = entry.get("title", "")
                if not any(n in _title for n in _CITY_TRAVEL_NOISE):
                    src_id = CITY_TRAVEL_SOURCE_ID  # 모집/공모 아닌 알짜 여행글만 승격
            events.append(Event(
                source=f"{SOURCE_PREFIX}:{src_id}",
                source_id=str(post_id),
                category=_classify(category, entry.get("title", "")),
                title=entry.get("title", "").strip(),
                start_date=_iso(entry.get("published")),
                venue=label,
                url=entry.get("link"),
                description=_strip_html(entry.get("summary") or entry.get("description")),
                raw={"blog": blog_id, "category": category, "published": entry.get("published")},
            ))
    return events
