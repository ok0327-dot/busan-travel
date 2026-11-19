"""Official Busan Naver blogs via RSS.

- cooolbusan  : 부산광역시 대표 블로그
- bscf2009    : 부산문화재단
- hudpr       : 해운대구청

RSS pattern: https://rss.blog.naver.com/{id}.xml
Each entry: title, link (.../{blogid}/{postid}), pubDate, category, description(HTML)

날짜 / dates: pubDate 는 게시일이다. 본문에 '일시: 2026. 10. 24.(토)' 같은 행사 일시가 있으면
start_date/end_date 를 그 기간으로 쓰고(sources/_event_dates.py), 게시일은 raw["published"] 에 남는다.
행사 일시를 확실히 찾은 '가볼 만한 행사' blog_post 는 festival 로 올린다(_promote).
"""
from __future__ import annotations

import re
from datetime import date
from email.utils import parsedate_to_datetime

import feedparser

from config import NAVER_OFFICIAL_BLOGS
from sources._adapter import HTTPSession, report
from sources._event_dates import EventPeriod, extract_event_period
from storage.db import Event

SOURCE = "naver_blogs"
SOURCE_PREFIX = "naver_blog"
RSS_TEMPLATE = "https://rss.blog.naver.com/{id}.xml"

# v3.9 계약 (audit 2026-04-25 P1-3). 예전엔 feedparser.parse(URL) 이 직접 받아서 재시도가 없었고,
# 피드가 죽으면 bozo 로 조용히 0건이 됐다 → 이제 재시도 + stderr 로그.
# / previously feedparser fetched the URL itself: no retry, and a dead feed silently became 0 rows.
session = HTTPSession(SOURCE)

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

# 행사 날짜를 찾은 blog_post 를 festival 로 올리는 조건 (보수적 — 잘못 올리면 주말 추천이 오염된다).
# festival 로만 올린다: performance/exhibition 은 export 의 is_major_venue 필터가 블로그 venue
# ('Haeundae-gu' 등)를 떨어뜨려 화면에서 아예 사라진다.
# / Promote only to festival — blog performance/exhibition rows are dropped by export's venue filter.
_ATTENDABLE_TITLE = re.compile(
    r"축제|페스티벌|페스타|연극|인형극|공연|음악회|콘서트|버스킹|체험|행사|마켓|장터|놀이|놀자|"
    r"전시|영화제|예술제|문화제|한마당|운동회|야시장"
)
_NOT_ATTENDABLE_TITLE = re.compile(
    r"모집|공모|후기|결과|성료|취소|연기|수상|선정|접수|신청|교육|강좌|강의|수강|특강|아카데미|"
    r"프로그램|설명회|간담회|포럼|세미나|채용|일자리|취업|창업|휴관|휴무|통제|공사|점검|스케치|"
    r"다녀왔|다녀온|훈련|설문|조사|투표|환급|유치|혜택|이벤트|챌린지|모음|총정리|라인업|가볼만한|"
    r"추천|임산부|어르신|시니어|중장년"
)
# 여러 행사를 묶은 글·소식지 — 날짜를 하나로 줄일 수 없다 / multi-event roundups & newsletters
_ROUNDUP_TITLE = re.compile(r"모음|총정리|라인업|알리미|한눈에")
# 본문이 '참가자 모집' 글이면 날짜가 있어도 누구나 가는 행사가 아니다 / sign-up-only programmes
_RECRUIT_BODY = re.compile(
    r"모집합니다|모집해요|모집\s*중|참여자\s*모집|참가자\s*모집|수강\s*신청|수강생|선정\s*가[족정]|선발"
)
PROMOTE_MAX_SPAN_DAYS = 31  # 한 달 넘게 이어지는 건 대개 강좌·프로그램 / longer = programme series


def _strip_html(s: str | None, limit: int | None = 400) -> str | None:
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


def _event_period(title: str, text: str | None, post_date: str | None) -> EventPeriod | None:
    """글에서 행사 기간을 찾는다. 항목명 없이 문장 속에서만 찾은 날짜(basis='text')는
    제목이 행사 안내일 때만(후기·모음·모집 글 제외) 믿는다.
    / Unlabelled dates count only for event-announcement titles."""
    if _ROUNDUP_TITLE.search(title):
        return None  # '7월 행사 모음.zip' — 첫 행사 날짜가 글 전체의 날짜가 아니다 / roundup posts
    period = extract_event_period(title, text, post_date)
    if period and period.basis == "text" and (
        not _ATTENDABLE_TITLE.search(title) or _NOT_ATTENDABLE_TITLE.search(title)
    ):
        return None
    return period


def _promote(category: str, title: str, text: str | None, period: EventPeriod | None) -> str:
    """blog_post → festival: 항목명(일시·기간)이나 제목에서 날짜를 찾았고(한 달 이내), 제목이 가볼 수
    있는 행사이며 모집·후기·교육·프로그램 글이 아닐 때만.
    / Only with a labelled/title date (≤31 days), an attendable title and no sign-up/review signals."""
    if category != "blog_post" or period is None or period.basis not in ("title", "label"):
        return category
    span = (date.fromisoformat(period.end) - date.fromisoformat(period.start)).days
    if (
        span <= PROMOTE_MAX_SPAN_DAYS
        and _ATTENDABLE_TITLE.search(title)
        and not _NOT_ATTENDABLE_TITLE.search(title)
        and not _RECRUIT_BODY.search(text or "")
    ):
        return "festival"
    return category


def _iso(pubdate: str | None) -> str | None:
    if not pubdate:
        return None
    try:
        return parsedate_to_datetime(pubdate).date().isoformat()
    except (TypeError, ValueError):
        return None


def _parse_feed(url: str) -> feedparser.FeedParserDict | None:
    r = session.get(url)
    if not r:
        return None
    # feedparser 는 응답 헤더를 **소문자 키**로만 읽는다('content-type' → 인코딩 판정).
    # requests 헤더를 그대로 넘기면 charset 을 놓친다. content-location 은 URL 로 받던 때의
    # baseuri(상대 링크 해석 기준)를 그대로 재현한다. 바이트(r.content)를 넘겨 인코딩 추정도 feedparser 몫.
    # / feedparser looks headers up lowercase-only; content-location reproduces the old baseuri.
    headers = {k.lower(): v for k, v in r.headers.items()}
    headers["content-location"] = r.url
    return feedparser.parse(r.content, response_headers=headers)


def fetch() -> list[Event]:
    events: list[Event] = []
    for blog_id, label in NAVER_OFFICIAL_BLOGS:
        parsed = _parse_feed(RSS_TEMPLATE.format(id=blog_id))
        if parsed is None:
            continue  # HTTPSession 이 이미 stderr 에 남겼다 / already logged
        for entry in parsed.entries:
            post_id = _post_id(entry.get("link", "")) or entry.get("id") or entry.get("title", "")
            category = entry.get("category")
            # cooolbusan(시청)은 '부산여행' 카테고리만 허용 소스로 분리, 나머지는 DROP 소스 유지.
            src_id = blog_id
            if blog_id == CITY_BLOG_ID and (category or "").strip() == TRAVEL_CATEGORY:
                _title = entry.get("title", "")
                if not any(n in _title for n in _CITY_TRAVEL_NOISE):
                    src_id = CITY_TRAVEL_SOURCE_ID  # 모집/공모 아닌 알짜 여행글만 승격
            title = entry.get("title", "").strip()
            text = _strip_html(entry.get("summary") or entry.get("description"), limit=None)
            post_date = _iso(entry.get("published"))
            # 본문에 행사 일시가 있으면 그 기간을, 없으면 예전처럼 게시일을 쓴다.
            # 게시일은 raw["published"] 에 그대로 남는다.
            # / Event period from the post body when found, else the post date (kept in raw).
            period = _event_period(title, text, post_date)
            events.append(Event(
                source=f"{SOURCE_PREFIX}:{src_id}",
                source_id=str(post_id),
                category=_promote(_classify(category, entry.get("title", "")), title, text, period),
                title=title,
                start_date=period.start if period else post_date,
                end_date=period.end if period else None,
                venue=label,
                url=entry.get("link"),
                description=text[:400] if text else None,
                raw={"blog": blog_id, "category": category, "published": entry.get("published")},
            ))
    return report(SOURCE, events)


if __name__ == "__main__":  # python -m sources.naver_blogs → "[naver_blogs] fetched=N"
    fetch()
