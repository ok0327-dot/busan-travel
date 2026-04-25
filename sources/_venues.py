"""부산 주요 venue 단일 진실 소스 (Single Source of Truth).

좌표 부여(`guess_venue_coords`) + exhibition/performance 화이트리스트
(`is_major_venue`) 두 기능 모두 한 VENUE_MAP 리스트에서 파생.

매칭 규칙:
- 정규화: 공백/점 제거 + 소문자 (양쪽 모두) — 표기 흔들림(공백·괄호·대소문자) 흡수
- 매칭 순서: 정규화된 키워드 길이 내림차순 (구체성 우선) — 선언 순서와 무관
- 좌표 None 인 venue 도 화이트리스트 매칭은 가능 (좌표 부여만 스킵)

큐레이션 가이드:
- 추가는 적절한 Tier 블록에 (선언 순서는 가독성 용도, 매칭 우선순위는 자동)
- `is_major=True` 는 exhibition/performance 화이트리스트 대상만
  (= 동네 갤러리/카페 전시 drop 시키지 않을 규모의 venue)
- 좌표 모를 때는 lat/lon=None — Kakao REST keyword search 로 자동 보강 권장
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Venue:
    keyword: str
    lat: float | None = None
    lon: float | None = None
    is_major: bool = False  # exhibition/performance 화이트리스트 자격


# ─────────────────────────────────────────────────────────────────────
# 단일 진실 소스 — 좌표 + 화이트리스트 양쪽 도출
# ─────────────────────────────────────────────────────────────────────
VENUE_MAP: list[Venue] = [
    # ── Tier 1A — 국공립 미술관·박물관 (is_major=True)
    Venue("부산현대미술관",       35.1021, 128.9991, True),
    Venue("부산시립미술관",       35.1699, 129.1385, True),
    Venue("부산박물관",           35.1296, 129.0944, True),
    Venue("국립해양박물관",       35.0829, 129.0848, True),
    Venue("이우환공간",           35.1658, 129.1369, True),
    Venue("아세안문화원",         35.1752, 129.1820, True),
    Venue("부산근현대역사관",     35.1027, 129.0312, True),
    Venue("국립부산국악원",       35.1713, 129.0542, True),

    # ── Tier 1B — 대형 공연장·컨벤션 (is_major=True)
    Venue("부산문화회관",         35.1277, 129.0946, True),
    Venue("부산시민회관",         35.1144, 129.0740, True),
    Venue("영화의전당",           35.1717, 129.1286, True),
    Venue("벡스코",               35.1682, 129.1313, True),
    Venue("BEXCO",                35.1682, 129.1313, True),
    Venue("F1963",                35.1489, 129.0848, True),
    Venue("부산콘서트홀",         35.1694, 129.0544, True),
    Venue("낙동아트센터",         35.1020, 128.9040, True),
    Venue("드림씨어터",           35.1481, 129.0658, True),
    Venue("소향씨어터",           35.1728, 129.1272, True),
    Venue("KBS홀",                35.1451, 129.1087, True),
    Venue("KBS부산홀",            35.1451, 129.1087, True),
    Venue("센텀아트홀",           35.1750, 129.1247, True),
    Venue("가온아트홀",           35.1381, 129.0650, True),
    Venue("뮤지엄원",             35.1713, 129.1290, True),
    # 동서대 캠퍼스 내 공연장 — 좌표 캠퍼스(동서대학교 entry) 로 fallback
    Venue("민석 소극장",          None,    None,     True),

    # ── Tier 1C — 민간 주요 복합 문화공간 (is_major=True)
    Venue("BNK부산은행 조은극장", 35.0983, 129.0323, True),
    Venue("KT&G 상상마당",        35.1543, 129.0573, True),
    Venue("어댑터씨어터",         35.1509, 129.1157, True),
    Venue("신세계갤러리",         35.1688, 129.1295, True),
    Venue("신세계 문화홀",        35.1687, 129.1290, True),

    # ── Tier 1D — 구·군 문화회관 (is_major=True)
    Venue("해운대문화회관",       35.1630, 129.1687, True),
    Venue("동래문화회관",         35.2119, 129.0898, True),
    Venue("금정문화회관",         35.2452, 129.0902, True),
    Venue("을숙도문화회관",       35.1102, 128.9446, True),
    Venue("북구문화회관",         35.2134, 129.0058, True),
    Venue("영도문화예술회관",     35.0756, 129.0660, True),
    Venue("차성아트홀",           35.2446, 129.2226, True),

    # ── Tier 1E — 대형 야외 공공 공간 (정기 공연 장소, is_major=True)
    Venue("부산시민공원",         35.1684, 129.0574, True),
    Venue("APEC나루공원",         35.1581, 129.1416, True),
    Venue("송상현광장",           35.1627, 129.0669, True),
    Venue("북항친수공원",         35.1144, 129.0464, True),

    # ── Tier 1F — 소·중규모 공연장·전시 (좌표만 부여, is_major=False)
    # 실제 카탈로그에 등장하나 화이트리스트에서 제외해 export drop 유도
    Venue("부산예술회관",             35.1594, 129.0530),
    Venue("서부산영상미디어센터",     35.2133, 128.9820),
    Venue("북두칠성도서관",           35.1164, 129.0459),
    Venue("효로인디아트홀",           35.1738, 129.0964),
    Venue("유어타입 본점",            35.1553, 129.1183),
    Venue("초콜릿팩토리",             35.1367, 129.0989),
    Venue("초록마술극장",             35.2420, 129.0957),
    Venue("수영사적공원",             35.1709, 129.1143),
    Venue("일터 소극장",              35.1385, 129.0657),
    Venue("가마골소극장",             35.2676, 129.2349),
    Venue("KNN시어터",                35.1719, 129.1286),
    Venue("다누림센터",               35.1476, 128.9948),
    Venue("오방가르드",               35.1372, 129.1010),

    # ── Tier 2 — 쇼핑·팝업 스페이스 (is_major=False, 좌표 보조용)
    Venue("신세계센텀시티",       35.1694, 129.1300),
    Venue("롯데백화점 부산본점",  35.1562, 129.0593),
    Venue("롯데백화점 동래점",    35.2039, 129.0785),
    Venue("현대백화점 부산점",    35.1584, 129.0611),
    Venue("부산아쿠아리움",       35.1584, 129.1612),
    Venue("센텀시티",             35.1694, 129.1300),

    # ── Tier 3 — 대학교 (is_major=False, 좌표 보조용)
    Venue("부산대학교",           35.2332, 129.0795),
    Venue("동아대학교",           35.1151, 128.9669),
    Venue("부경대학교",           35.1345, 129.1050),
    Venue("경성대학교",           35.1372, 129.1029),
    Venue("동서대학교",           35.1411, 129.0186),

    # ── Tier 4 — 해변·도시공원 (해운대해수욕장만 is_major=True, 대형 축제장)
    Venue("해운대해수욕장",       35.1586, 129.1603, True),
    Venue("광안리해수욕장",       35.1533, 129.1182),
    Venue("송정해수욕장",         35.1780, 129.1999),
    Venue("다대포해수욕장",       35.0466, 128.9650),
    Venue("수영강휴먼브릿지",     35.1680, 129.1291),
    Venue("삼락생태공원",         35.1516, 128.9705),
    Venue("대저생태공원",         35.1762, 128.9538),
    Venue("용두산공원",           35.1005, 129.0329),
    Venue("중앙공원",             35.1062, 129.0263),
    Venue("을숙도",               35.1148, 128.9441),
    Venue("온천천",               35.2239, 129.0797),

    # ── Tier 5 — 랜드마크·관광 (is_major=False)
    Venue("감천문화마을",         35.0977, 129.0107),
    Venue("자갈치시장",           35.0970, 129.0307),
    Venue("BIFF광장",             35.0983, 129.0294),
    Venue("국제시장",             35.0998, 129.0289),
    Venue("해동용궁사",           35.1883, 129.2234),
    Venue("다릿돌전망대",         35.1573, 129.1811),
    Venue("스카이캡슐",           35.1563, 129.1891),
    Venue("흰여울문화마을",       35.0820, 129.0358),
    Venue("해월전망대",           35.1610, 129.1842),
    Venue("태종대",               35.0526, 129.0863),
    Venue("오륙도",               35.0954, 129.1229),
    Venue("동백섬",               35.1554, 129.1568),
    Venue("청사포",               35.1609, 129.1811),
    Venue("달맞이길",             35.1595, 129.1791),
    Venue("이기대",               35.1266, 129.1196),
    Venue("장산",                 35.1940, 129.1745),
    Venue("황령산",               35.1362, 129.0824),
    Venue("범어사",               35.2835, 129.0690),
    Venue("통도사",               35.4883, 129.0637),

    # ── Tier 6 — 핫플/상권 (is_major=False, 좌표 보조용)
    Venue("전포카페거리",         35.1493, 129.0644),
    Venue("해리단길",             35.1547, 129.1636),
    Venue("밀락더마켓",           35.1500, 129.1289),
    Venue("서면",                 35.1573, 129.0595),
    Venue("남포동",               35.0983, 129.0294),
    Venue("광복동",               35.0994, 129.0289),
    Venue("해운대",               35.1586, 129.1603),
    Venue("광안리",               35.1533, 129.1182),
    Venue("광안대교",             35.1511, 129.1301),
    Venue("영도",                 35.0912, 129.0498),
    Venue("기장",                 35.2444, 129.2222),
    Venue("송도",                 35.0751, 129.0197),
    Venue("다대포",               35.0466, 128.9650),
]


# ─────────────────────────────────────────────────────────────────────
# 매칭 헬퍼
# ─────────────────────────────────────────────────────────────────────
def _normalize(text: str | None) -> str:
    """공백/점 제거 + 소문자. 표기 흔들림 흡수용."""
    if not text:
        return ""
    return "".join(text.split()).replace(".", "").lower()


# 모듈 로드 시 1회 — 정규화 길이 내림차순 (구체성 우선)
_VENUES_BY_LEN: list[tuple[Venue, str]] = sorted(
    ((v, _normalize(v.keyword)) for v in VENUE_MAP),
    key=lambda t: -len(t[1]),
)


def guess_venue_coords(*texts: str | None) -> tuple[str | None, float | None, float | None]:
    """여러 텍스트 블록에서 venue 키워드 매칭 → (키워드, lat, lon).

    좌표 미보유 venue 는 자동 스킵. 매칭 실패 시 (None, None, None).
    """
    blob = _normalize(" ".join(t or "" for t in texts))
    if not blob:
        return None, None, None
    for v, kw_norm in _VENUES_BY_LEN:
        if v.lat is None or v.lon is None:
            continue
        if kw_norm and kw_norm in blob:
            return v.keyword, v.lat, v.lon
    return None, None, None


def is_major_venue(venue: str | None) -> bool:
    """venue 텍스트가 주요 규모 venue (is_major=True) 와 substring 매칭되는지.

    정규화된 양쪽으로 매칭 — "신세계 갤러리" / "신세계갤러리" 동치.
    """
    if not venue:
        return False
    blob = _normalize(venue)
    if not blob:
        return False
    for v, kw_norm in _VENUES_BY_LEN:
        if not v.is_major:
            continue
        if kw_norm and kw_norm in blob:
            return True
    return False
