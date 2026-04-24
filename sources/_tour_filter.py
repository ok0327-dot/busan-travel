"""관광 관련성 + 중요도 필터 (공통 모듈).

두 축으로 이벤트를 분류한다:
  1) 관광 관련성  — 시정/행정/공모/복지/보건 등 비관광 정보 drop
  2) 중요도(규모) — venue·좌표·이미지·평점·조회수 등 신호를 스코어링, minor 마킹

호출 지점:
  - Ingestion: 각 sources/*.py 에서 fetch 후 `filter_events(events)` 로 걸러 upsert
  - Export  : scripts/export_json.py 에서 `classify_event(row)` 로 drop/minor/keep 판정
"""
from __future__ import annotations

from typing import Any, Iterable, Literal

Decision = Literal["keep", "minor", "drop"]

# ─────────────────────────────────────────────────────────────────────
# 1) 소스 레벨 policy
# ─────────────────────────────────────────────────────────────────────
# 관광 맥락과 구조적으로 어긋나는 피드 — 전체 차단
DROP_SOURCES: frozenset[str] = frozenset({
    "naver_blog:cooolbusan",   # 부산시청 블로그: 88% 가 시정 홍보 (일자리정책/공모/모집)
})

# blog_post 카테고리를 쓸 수 있는 공식(신뢰) 블로그 — 외 소스의 blog_post 는 drop
# 개인 블로그(naver_search:blog) 는 품질 편차 크고, 뉴스는 블로그 아님.
OFFICIAL_BLOG_SOURCES: frozenset[str] = frozenset({
    "naver_blog:bscf2009",     # 부산문화재단
    "naver_blog:hudpr",        # 부산관광공사
})

# 공식 관광 데이터 — 필터 건너뛰고 항상 keep (품질 신뢰)
TRUSTED_SOURCE_PREFIXES: tuple[str, ...] = (
    "busan_",     # data.go.kr 공식 데이터셋
    "vb_",        # VisitBusan.net 큐레이션
    "tour_api",   # 한국관광공사 API
    "gov_",       # 정부 공공데이터 (해수욕장·안내소 등)
)

# Naver 크롤 계열은 엄격 필터 대상 (DROP_SOURCES 제외)
STRICT_SOURCE_PREFIXES: tuple[str, ...] = (
    "naver_",
)

# ─────────────────────────────────────────────────────────────────────
# 2) 네거티브 키워드 — 적중 시 즉시 drop
#    ※ 기존 scripts/export_json.py 의 TOUR_NEGATIVE_KEYWORDS 를 흡수 + 확장
# ─────────────────────────────────────────────────────────────────────
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    # 행정·정책·홍보
    "정책 종합계획", "정책 종합", "마스터 플랜", "마스터플랜",
    "종합계획 발표", "시정보고", "의정보고", "중점 추진",
    "인증 확산", "가족친화인증", "미래유산 시민제안",
    "정책간담회", "사업설명회", "의견청취", "주민설명회",
    # 공모·모집 (관광 무관)
    "참가업체 모집", "참가 기업·기관 모집", "명문향토기업 모집",
    "입주작가 공모", "서포터즈 모집", "작가 양성", "작가 모집",
    "예술가 모집", "조사요원 모집", "합창단 단원 모집",
    "인증 모집", "UNDER 39", "창작클래스",
    "대관 일정", "정기대관", "포럼",
    "청년 아트페어 참여 작가",
    "참여 예술가 모집", "참여 기업 모집", "참여 단체 모집",
    "참여기관 모집", "참여작가",
    # 신청·지원금·복지
    "피해지원금", "지원금 신청", "청년수당", "기초연금",
    "월세 지원", "월세지원", "고용인센티브", "장학금", "장학생",
    "진료비·장례비", "진료비 지원", "교육지원포인트",
    "희망두배통장", "두배통장",
    # 보건·의료·돌봄
    "예방접종", "방사선 촬영", "일시중단",
    "보건지소", "거점병원", "건강생활지원센터", "심폐소생술",
    "돌봄 서비스", "통합돌봄", "돌봄사업", "소아 야간 휴일 진료",
    "소아 야간", "달빛어린이병원",
    # 산업·경제·사업 홍보
    "앵커기업", "스마트밸리", "경제의 뿌리", "인턴사업", "인턴지원금",
    "원자력산업전", "K-ICT WEEK", "ICT WEEK", "도시지원센터",
    "일자리정책", "잡(JOB)매칭", "잡(JOB)카페", "일자리정보망",
    "일자리 창출", "소상공인 해결사", "기업가형 소상공인",
    "해결사 지원사업", "B-스타", "Beyond B-Star",
    # 안전·점검·공사·교통 행정
    "중대시민재해", "중대산업재해", "의무이행 집중 점검",
    "안전보강", "전면 통제", "5부제 시행", "승용차 5부제",
    "불법행위 사전예방", "유니버설디자인 개선 공사", "공사 착수",
    "태그리스", "교통카드 안 찍",
    # 조사·위원회·법령
    "조사요원", "총조사", "실태조사", "위원회 구성",
    "조례", "선거",
    # 교육·평생학습 (시정)
    "평생학습", "더배움학교", "고전의 창",
    # 행정 인프라·공지
    "봉투 가격", "종량제", "터미널 유니버설",
    "플랫폼 구축", "앱 하나로", "앱으로",
    "스마트 안전 산단", "스마트 관문", "행정 마스터",
    # 환경·기후 행정
    "기후대응 도시숲", "자녀안심 그린숲", "탄소중립 실천",
    # 기타 행정·이벤트
    "당첨자 안내", "당첨자 발표", "댓글 요정",
    "댓글만 달면", "예산", "결산", "납세",
    "자원안보위기", "에너지 캐시백",
    "반려견 순찰대", "반려동물 진료비",
    "반려문화공원 건립", "건립 안내",
    "전자아카이브 개편", "전자아카이브",
    "교육사업 공모", "교육 지원사업",
    "컨설팅 지원", "거점시설",
    "시범 운영 시작", "확대 안내",
    "인공지능 맞춤 추천", "1인 가구 돌봄",
    "빅데이터 기반",
    "포용적인 부산", "외국인 유학생",
    "자매결연", "자매도시",
    # 보도·홍보 자료
    "보도자료", "기자회견",
)

# ─────────────────────────────────────────────────────────────────────
# 3) 중요도 스코어링 신호
# ─────────────────────────────────────────────────────────────────────
# 대형 이벤트 힌트 (제목/설명에 있으면 가산)
SCALE_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "국제", "전국", "대규모", "개막", "메가",
    "아시아", "월드", "페스티벌", "BIFF", "부산국제",
)

# 소규모/제한적 이벤트 힌트 (감점)
SCALE_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "회원 한정", "회원만", "조합원", "동호회",
    "주민 대상", "소규모", "소수 인원", "내부 행사",
    "사전 신청자", "선착순 20", "선착순 30",
    "사내", "비공개",
)

# naver_blog* 소스가 venue 자리에 블로그 계정 설명을 넣어둠 — 실장소 아님
BOILERPLATE_VENUES: frozenset[str] = frozenset({
    "Busan City",         # cooolbusan
    "Busan Culture Fdn",  # bscf2009
    "hudpr",              # hudpr (블로그 계정)
    "부산관광공사",         # 명시 venue 아닌 publisher
    "부산시",
    "부산광역시",
})

# minor 분기 임계값 (합산 스코어 < 이 값 이면 minor)
MINOR_THRESHOLD: int = 2


# ─────────────────────────────────────────────────────────────────────
# 4) Accessor — Event dataclass / sqlite3.Row / dict 공통
# ─────────────────────────────────────────────────────────────────────
def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    # dataclass / object attribute
    if hasattr(obj, key):
        v = getattr(obj, key, None)
        if v is not None:
            return v
    # dict / sqlite3.Row
    try:
        v = obj[key]
        return v if v is not None else default
    except (KeyError, IndexError, TypeError):
        return default


# ─────────────────────────────────────────────────────────────────────
# 5) Public API
# ─────────────────────────────────────────────────────────────────────
def is_tour_relevant(title: str | None, description: str | None = None) -> bool:
    """네거티브 키워드 적중 시 False. 적중 안 하면 True."""
    blob = f"{title or ''} {description or ''}"
    return not any(kw in blob for kw in NEGATIVE_KEYWORDS)


def importance_score(
    *,
    title: str | None = None,
    description: str | None = None,
    venue: str | None = None,
    image_url: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    rating: float | None = None,
    view_count: int | None = None,
    duration_days: int | None = None,
) -> int:
    """양수 = 대형/신뢰, 음수 = 자잘함. 기본 0."""
    score = 0
    # 위치/장소 신호
    if venue and venue.strip() and venue not in BOILERPLATE_VENUES:
        score += 2
    if lat is not None and lon is not None:
        score += 2
    # 시각 자산
    if image_url:
        score += 1
    # 설명 밀도
    if description and len(description) > 100:
        score += 1
    # 품질/인기
    if rating is not None and rating >= 4.0:
        score += 1
    if view_count is not None and view_count > 1000:
        score += 1
    # 키워드 기반 규모
    title_blob = title or ""
    desc_blob = description or ""
    for kw in SCALE_POSITIVE_KEYWORDS:
        if kw in title_blob:
            score += 2
            break
    for kw in SCALE_NEGATIVE_KEYWORDS:
        if kw in title_blob or kw in desc_blob:
            score -= 3
            break
    # 1일짜리 + 좌표 없음 = 자잘한 확률 높음
    if duration_days is not None and duration_days <= 1 and (lat is None or lon is None):
        score -= 2
    return score


def classify_event(event: Any) -> Decision:
    """이벤트 → 'keep' | 'minor' | 'drop'.

    event 는 Event dataclass, sqlite3.Row, dict 중 무엇이든 OK.
    sqlite3.Row 는 필드명이 image_url/description/view_count 로 오고,
    export 후 dict 는 image/description/views 일 수 있으니 양쪽 키 모두 시도.
    """
    source = _get(event, "source", "") or ""
    category = _get(event, "category", "") or ""

    # A) 소스 차단
    if source in DROP_SOURCES:
        return "drop"

    # A-2) 공식 블로그만 — blog_post 카테고리는 OFFICIAL_BLOG_SOURCES 만 허용
    if category == "blog_post" and source not in OFFICIAL_BLOG_SOURCES:
        return "drop"

    # B) 공식 소스는 품질 신뢰 — 중요도만 체크해서 minor 판정 가능
    is_trusted = any(source.startswith(p) for p in TRUSTED_SOURCE_PREFIXES)

    title = _get(event, "title", "")
    description = _get(event, "description", "")

    # C) 네거티브 키워드 필터 (Trusted 소스는 적용 X — 공식 카테고리 신뢰)
    if not is_trusted and not is_tour_relevant(title, description):
        return "drop"

    # D) 중요도 스코어
    score = importance_score(
        title=title,
        description=description,
        venue=_get(event, "venue"),
        image_url=_get(event, "image_url") or _get(event, "image"),
        lat=_get(event, "lat"),
        lon=_get(event, "lon"),
        rating=_get(event, "rating"),
        view_count=_get(event, "view_count") or _get(event, "views"),
    )

    # Trusted 소스는 기본 가점 (공식이라는 것만으로도 신뢰)
    if is_trusted:
        score += 2

    return "minor" if score < MINOR_THRESHOLD else "keep"


def filter_events(events: Iterable[Any], *, drop_minor: bool = False) -> tuple[list[Any], dict[str, int]]:
    """이벤트 리스트 → (유지 리스트, stats).

    drop_minor=True 면 minor 도 제거, False 면 유지하되 호출부에서 subtype 태깅 가능.
    """
    kept: list[Any] = []
    stats = {"keep": 0, "minor": 0, "drop": 0}
    for ev in events:
        d = classify_event(ev)
        stats[d] += 1
        if d == "drop":
            continue
        if d == "minor" and drop_minor:
            continue
        kept.append(ev)
    return kept, stats
