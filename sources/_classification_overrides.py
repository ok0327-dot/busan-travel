"""Naver Local API 검증으로 확정된 visitbusan 카테고리 정정.

visitbusan API contentTypeId=39(음식점) 가 카페·바를 포함, attraction 큐레이션도
일부 외식업소가 섞임. 이름만으로 구분 어려워 좌표+카테고리 매칭으로 검증.

False positive 0 보장:
- 좌표 거리 ≤ 5m (vb_food) / ≤ 300m (vb_attraction)
- Naver Local 응답 category 가 "카페,디저트", "베이커리", "주점", "와인" 등 명확

같은 POI 가 vb_* 와 busan_* 양쪽에 있을 수 있어 둘 다 정정.
신규 데이터가 같은 (source, source_id) 로 들어와도 어댑터 후처리에서 강제 적용.

검증일 / Verified: 2026-04-25, openapi.naver.com/v1/search/local.json
"""
from __future__ import annotations

# (source, source_id) → 정정 카테고리 / Override category
CATEGORY_OVERRIDES: dict[tuple[str, str], str] = {
    # bar 카테고리 폐기 (2026-04-26) — 지도 표시 단순화. 술집 6건 모두 food 로 통합
    # (이전 v3.9 분리 결정 → 사용자 결정으로 통합 변경)
    ('busan_food', '1497'): 'food',  # 노는바다
    ('busan_food', '2360'): 'food',  # 아펙트
    ('busan_food', '2361'): 'food',  # 야키토리 백탄
    ('vb_food', '1497'): 'food',  # 노는바다
    ('vb_food', '2360'): 'food',  # 아펙트
    ('vb_food', '2361'): 'food',  # 야키토리 백탄

    # → cafe (from attraction)
    ('busan_attraction', '2119'): 'cafe',  # 2만여 장 LP 속으로 풍덩! 뮤직컴플렉스 서울 부산점
    ('busan_food', '1251'): 'cafe',  # 톤쇼우 광안점
    ('busan_food', '1448'): 'cafe',  # 칠암사계
    ('busan_food', '1450'): 'cafe',  # 초량온당
    ('busan_food', '1452'): 'cafe',  # 이흥용과자점 부산대직영점
    ('busan_food', '1459'): 'cafe',  # 용호동할매팥빙수단팥죽 본점
    ('busan_food', '1460'): 'cafe',  # 올드머그
    ('busan_food', '1461'): 'cafe',  # 아데초이
    ('busan_food', '1462'): 'cafe',  # 빌라빌레쿨라
    ('busan_food', '1463'): 'cafe',  # 브리타니
    ('busan_food', '1466'): 'cafe',  # 보리종파티세리 본점
    ('busan_food', '1467'): 'cafe',  # 바우노바
    ('busan_food', '1475'): 'cafe',  # 명란브랜드연구소
    ('busan_food', '1581'): 'cafe',  # 맥퀸즈라운지
    ('busan_food', '1611'): 'cafe',  # 백구당
    ('busan_food', '1627'): 'cafe',  # 레망파티쓰리
    ('busan_food', '1629'): 'cafe',  # 무슈뱅상
    ('busan_food', '1631'): 'cafe',  # 브레드365
    ('busan_food', '1632'): 'cafe',  # 브리앙
    ('busan_food', '1815'): 'cafe',  # 칙투칙
    ('busan_food', '1816'): 'cafe',  # 프랑스 과자점 브리앙
    ('busan_food', '1831'): 'cafe',  # 무슈뱅상
    ('busan_food', '1838'): 'cafe',  # 그리다부부
    ('busan_food', '1840'): 'cafe',  # 연경재
    ('busan_food', '1845'): 'cafe',  # 비비비당
    ('busan_food', '2354'): 'cafe',  # 보느파티쓰리
    ('busan_food', '2358'): 'cafe',  # 데일리럭키
    ('busan_food', '2371'): 'cafe',  # 연화제과
    ('busan_food', '245'): 'cafe',  # 초량 1941
    ('busan_food', '959'): 'cafe',  # 홍옥당
    ('vb_attraction', '2119'): 'cafe',  # 2만여 장 LP 속으로 풍덩! 뮤직컴플렉스 서울 부산점
    ('vb_food', '1251'): 'cafe',  # 톤쇼우 광안점
    ('vb_food', '1475'): 'cafe',  # 명란브랜드연구소

    # → food (from attraction)
    ('busan_attraction', '832'): 'food',  # 오션블루 가덕휴게소
    ('vb_attraction', '832'): 'food',  # 오션블루 가덕휴게소
}


def apply_override(source: str, source_id: str | int, default: str | None) -> str | None:
    """어댑터 후처리에서 호출. override 가 있으면 그 값, 없으면 default 반환."""
    return CATEGORY_OVERRIDES.get((source, str(source_id)), default)
