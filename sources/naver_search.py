"""Naver Search API (openapi.naver.com) — 부산 행사/전시/공연 힌트 수집.

공식 엔드포인트에는 '전시' 전용 카테고리가 없어, 블로그/뉴스/카페 검색을
키워드 매트릭스로 돌려 최근 게시물에서 행사 힌트를 뽑는다.

Tier 2(네이버 통합검색 '전시/공연' 탭 큐레이션 스크래핑)는 별도 모듈 예정.

필드 매핑:
- title       : HTML 태그 제거한 검색 결과 제목
- description : HTML 태그 제거한 스니펫 (~300자)
- start_date  : 본문/제목에서 날짜 정규식으로 추출. 실패 시 postdate(작성일).
- url         : 블로그/뉴스/카페 원문 링크
- category    : 제목 키워드로 festival/exhibition/performance/blog_post 분류
- source      : 'naver_search:blog' / 'naver_search:news' / 'naver_search:cafe'
- source_id   : 링크 MD5 앞 16자 (중복 제거 키)

필터:
- TOUR_NEGATIVE_KEYWORDS (export_json.py 와 동일 규칙 재구현, import 순환 회피)
- '부산' 언급 필수 (other 지역 노이즈 제거)
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

from sources._venues import guess_venue_coords
from storage.db import Event

SOURCE_PREFIX = "naver_search"

# 엔드포인트: blog(최근 블로그), news(뉴스), cafearticle(카페 글)
ENDPOINTS = {
    "blog": "https://openapi.naver.com/v1/search/blog.json",
    "news": "https://openapi.naver.com/v1/search/news.json",
    "cafe": "https://openapi.naver.com/v1/search/cafearticle.json",
}

# 키워드 매트릭스 — 부산 중심 + 계절성 + 세부 지역
def _build_queries() -> list[str]:
    today = date.today()
    ym = f"{today.year}년 {today.month}월"
    next_m = today.month + 1 if today.month < 12 else 1
    next_ym_label = f"{today.year}년 {next_m}월" if today.month < 12 else f"{today.year + 1}년 1월"
    return [
        "부산 전시",
        "부산 팝업",
        "부산 페스티벌",
        "부산 공연",
        "부산 축제",
        f"부산 {ym} 행사",
        f"부산 {next_ym_label} 행사",
        "부산 원데이클래스",
        "부산 플리마켓",
        "해운대 전시",
        "서면 팝업",
        "광안리 행사",
        "감천문화마을 이벤트",
        "F1963 전시",
        "부산현대미술관",
        "영화의전당 공연",
    ]

# 일부 쿼리는 시정 홍보/채용/지원금 블로그가 섞여 들어옴. export_json.py 의
# TOUR_NEGATIVE_KEYWORDS 와 동일 철학, 일부 추가.
_NEG_KEYWORDS = (
    # 행정·정책
    "정책 종합", "마스터플랜", "시정보고", "사업설명회",
    "미래유산 시민", "인증 확산",
    # 모집·공모·지원금
    "지원금 신청", "신청 안내", "청년수당", "기초연금",
    "월세 지원", "인턴지원금", "장학금", "참가업체 모집",
    "입주작가 공모", "서포터즈 모집", "참가자 모집",
    "봉사자 모집", "심사위원 모집",
    # 산업·경제·박람회(관광 아님)
    "원자력산업전", "K-ICT", "일자리박람회", "채용박람회",
    # 보건·의료 공지
    "예방접종", "보건지소", "건강생활지원센터",
    # 행정 인프라
    "종량제", "승용차 5부제", "공사 착수",
    # 교육
    "평생학습", "더배움학교",
    # 기타 쇼핑몰·광고성 노이즈
    "쿠팡", "11번가", "네이버스토어", "지마켓", "옥션",
    "최저가", "할인쿠폰", "파트너스",
)

_TAG_RE = re.compile(r"<[^>]+>")
_DATE_FULL_RE = re.compile(r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})")
_DATE_MD_RE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
_DATE_RANGE_RE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일\s*[~\-–]\s*(?:(\d{1,2})월\s*)?(\d{1,2})일")


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return html.unescape(_TAG_RE.sub("", s)).strip()


def _classify(title: str, desc: str) -> str:
    blob = f"{title} {desc}".lower()
    if any(k in blob for k in ["축제", "페스티벌", "festival", "플리마켓"]):
        return "festival"
    if any(k in blob for k in ["전시", "아트페어", "exhibition"]):
        return "exhibition"
    if any(k in blob for k in ["공연", "콘서트", "뮤지컬", "연극", "performance"]):
        return "performance"
    return "blog_post"


def _extract_date(title: str, desc: str, postdate_yyyymmdd: str | None) -> tuple[str | None, str | None]:
    """(start_iso, end_iso). 실패 시 (postdate, None) or (None, None)."""
    blob = f"{title} {desc}"
    this_year = date.today().year

    # 범위 '4월 3일 ~ 5월 31일'
    m = _DATE_RANGE_RE.search(blob)
    if m:
        sm, sd, em, ed = m.groups()
        start = f"{this_year:04d}-{int(sm):02d}-{int(sd):02d}"
        end_m = int(em) if em else int(sm)
        end = f"{this_year:04d}-{end_m:02d}-{int(ed):02d}"
        return start, end

    # 풀 날짜 '2026-04-27'
    m = _DATE_FULL_RE.search(blob)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", None

    # 짧은 '4월 27일'
    m = _DATE_MD_RE.search(blob)
    if m:
        mo, d = m.groups()
        return f"{this_year:04d}-{int(mo):02d}-{int(d):02d}", None

    # 폴백: postdate (YYYYMMDD)
    if postdate_yyyymmdd and len(postdate_yyyymmdd) == 8 and postdate_yyyymmdd.isdigit():
        return f"{postdate_yyyymmdd[:4]}-{postdate_yyyymmdd[4:6]}-{postdate_yyyymmdd[6:8]}", None

    return None, None


def _is_tour_busan(title: str, desc: str) -> bool:
    blob = f"{title} {desc}"
    if "부산" not in blob and "해운대" not in blob and "광안" not in blob and "서면" not in blob and "영도" not in blob:
        return False
    for neg in _NEG_KEYWORDS:
        if neg in blob:
            return False
    return True


def _load_creds() -> tuple[str | None, str | None]:
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if cid and csec:
        return cid, csec
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            s = line.strip()
            if s.startswith("NAVER_CLIENT_ID="):
                cid = cid or s.split("=", 1)[1].strip().strip('"').strip("'")
            elif s.startswith("NAVER_CLIENT_SECRET="):
                csec = csec or s.split("=", 1)[1].strip().strip('"').strip("'")
    return cid, csec


def _fetch_kind(kind: str, query: str, cid: str, csec: str, display: int = 30) -> list[dict]:
    try:
        r = requests.get(
            ENDPOINTS[kind],
            params={"query": query, "display": display, "sort": "date"},
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
            timeout=12,
        )
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"[naver_search:{kind}] '{query}' err: {e}", file=sys.stderr)
        return []


def _parse_item(item: dict, kind: str, query: str) -> Event | None:
    title = _clean(item.get("title"))
    desc = _clean(item.get("description"))
    if not title:
        return None
    if not _is_tour_busan(title, desc):
        return None

    link = item.get("link") or item.get("originallink") or ""
    postdate = item.get("postdate")  # blog: YYYYMMDD. news 는 pubDate 별도.
    start_iso, end_iso = _extract_date(title, desc, postdate)

    # 2개월 이전/8개월 이후 이벤트는 관련성 낮음 → 드롭
    if start_iso:
        try:
            sd = date.fromisoformat(start_iso)
            today = date.today()
            if sd < today - timedelta(days=60) or sd > today + timedelta(days=240):
                return None
        except ValueError:
            pass

    source_id = hashlib.md5(link.encode("utf-8")).hexdigest()[:16] if link else hashlib.md5(title.encode("utf-8")).hexdigest()[:16]

    # Phase 3b: 제목/설명에서 부산 주요 공연·전시장 매칭 → 좌표 부여
    venue_name, lat, lon = guess_venue_coords(title, desc)

    return Event(
        source=f"{SOURCE_PREFIX}:{kind}",
        source_id=source_id,
        category=_classify(title, desc),
        title=title[:200],
        start_date=start_iso,
        end_date=end_iso,
        venue=venue_name,
        address=None,
        url=link,
        description=desc[:300] if desc else None,
        image_url=None,
        lat=lat,
        lon=lon,
        raw={"kind": kind, "query": query, "postdate": postdate},
    )


def fetch() -> list[Event]:
    cid, csec = _load_creds()
    if not cid or not csec:
        print("[naver_search] SKIP: NAVER_CLIENT_ID/SECRET 미설정", file=sys.stderr)
        return []

    queries = _build_queries()
    events: list[Event] = []
    seen_ids: set[str] = set()
    for query in queries:
        for kind in ("blog", "news"):  # cafe 는 2차 — 블로그/뉴스만으로 시작
            items = _fetch_kind(kind, query, cid, csec, display=30)
            for it in items:
                ev = _parse_item(it, kind, query)
                if not ev:
                    continue
                if ev.source_id in seen_ids:
                    continue
                seen_ids.add(ev.source_id)
                events.append(ev)
    print(f"[naver_search] fetched={len(events)} queries={len(queries)}", file=sys.stderr)
    return events
