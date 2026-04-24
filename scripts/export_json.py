"""SQLite events.db → frontend/public/data/ JSON export.

출력:
  places.json          고정 POI (맛집/명소/테마)
  beaches.json         해수욕장 (수질 정보 포함, 명소로 병합 렌더)
  events-YYYY-MM.json  월별 이벤트 (축제/공연, start_date 기준)
  weather-short.json   단기예보 (모든 격자 × 3시간 간격)
  weather-mid.json     중기예보 (부산 단일, D+3~D+10)
  air-quality.json     대기질 측정소별 최신값
  manifest.json        version, generated_at, counts
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "events.db"
OUT_DIR = ROOT / "frontend" / "public" / "data"

sys.path.insert(0, str(ROOT))
from sources._tour_filter import importance_score, SCALE_POSITIVE_KEYWORDS  # noqa: E402

# 읽을거리 탭 전용 소스 가중치 — 공식 블로그 강가점, 일반 보도 감점
# 공식 블로그는 depth/trust 높고, 일반 뉴스는 단순 홍보 반복이 많음.
BLOG_SOURCE_WEIGHTS = {
    # 공식 네이버 블로그 (신뢰 + 큐레이션)
    "naver_blog:bscf2009":     +3,   # 부산문화재단
    "naver_blog:hudpr":        +3,   # 해운대구청
    "naver_blog:moca_busan":   +3,   # 부산현대미술관
    "naver_blog:bsbukgusns":   +2,   # 북구청 (행정 혼재)
    "naver_blog:bsjunggu":     +2,   # 중구청
    "naver_blog:yeonjegu":     +2,   # 연제구청
    "naver_blog:bsdonggublog": +2,   # 동구청
    # 일반 수집 채널
    "naver_search:news":       -2,   # 보도 단발성 + 중복 도배
    "naver_search:blog":       -1,   # 개인 블로그 편차
}


def _duration_days(start: str | None, end: str | None) -> int | None:
    """YYYY-MM-DD 문자열 페어 → 기간 일수 (포함). 미정 값은 None."""
    if not start:
        return None
    try:
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat((end or start)[:10])
        return max(1, (e - s).days + 1)
    except ValueError:
        return None


def _hero_tags(title: str | None, description: str | None) -> list[str]:
    """제목/설명에 매칭되는 규모 태그 추출 ('국제', '전국', 'BIFF' 등)."""
    blob = f"{title or ''} {description or ''}"
    tags = [kw for kw in SCALE_POSITIVE_KEYWORDS if kw in blob]
    # 중복 축소 + 최대 2개
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 2:
            break
    return out

PLACE_CATEGORIES = {"food", "cafe", "attraction", "theme"}
EVENT_CATEGORIES = {"festival", "blog_post"}

# blog_post 필터 — 부산 공식 블로그(cooolbusan/bscf2009/hudpr) 피드에는 관광과 무관한
# 시정·정책·보도자료·공모·지원금·산업박람회가 섞임. "읽을거리" 탭이 여행 맥락이므로
# 아래 키워드 중 하나라도 title/description 에 포함되면 제외.
# 원칙: 보수적 블랙리스트 — 애매하면 포함. festival/exhibition/performance 는 필터 대상 아님.
TOUR_NEGATIVE_KEYWORDS = (
    # 행정·정책·홍보
    "정책 종합계획", "정책 종합", "마스터 플랜", "마스터플랜",
    "종합계획 발표", "시정보고", "의정보고", "중점 추진",
    "인증 확산", "가족친화인증", "미래유산 시민제안",
    # 공모·모집 (여행 무관)
    "참가업체 모집", "참가 기업·기관 모집", "명문향토기업 모집",
    "입주작가 공모", "서포터즈 모집", "작가 양성", "작가 모집",
    "예술가 모집", "조사요원 모집", "합창단 단원 모집",
    "인증 모집", "UNDER 39", "창작클래스",
    "대관 일정", "정기대관", "포럼",
    "청년 아트페어 참여 작가",
    # 신청·지원금·혜택
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
    "정책간담회", "사업설명회", "의견청취", "주민설명회",
    "포용적인 부산", "외국인 유학생",
    "자매결연", "자매도시",
)


def _is_tour_friendly_blog(title: str | None, description: str | None) -> bool:
    """blog_post 가 여행 맥락에 적합한지 판정. 제외 키워드 매칭 시 False."""
    blob = f"{title or ''} {description or ''}"
    for kw in TOUR_NEGATIVE_KEYWORDS:
        if kw in blob:
            return False
    return True


def _col(row: sqlite3.Row, key: str, default=None):
    try:
        v = row[key]
        return v if v is not None else default
    except (IndexError, KeyError):
        return default


def _jsonable(row: sqlite3.Row) -> dict:
    """Whitelist-safe dict (raw_json/민감 필드 제외) + VisitBusan enrichment.

    이벤트 카테고리에는 Hero Top 3 용 priority 필드 추가 (importance_score 결과).
    """
    import json as _json
    tags = None
    tj = _col(row, "tags_json")
    if tj:
        try:
            tags = _json.loads(tj)
        except (ValueError, TypeError):
            tags = None

    # 이벤트 우선순위 스코어링 (festival/exhibition/performance/blog_post 에만 의미)
    priority = None
    blog_priority = None
    hero_tags: list[str] = []
    cat = row["category"]
    if cat in ("festival", "exhibition", "performance", "blog_post"):
        dur = _duration_days(row["start_date"], row["end_date"])
        priority = importance_score(
            title=row["title"],
            description=row["description"],
            venue=row["venue"],
            image_url=row["image_url"],
            lat=row["lat"],
            lon=row["lon"],
            rating=_col(row, "rating"),
            view_count=_col(row, "view_count"),
            duration_days=dur,
        )
        hero_tags = _hero_tags(row["title"], row["description"])
        # 읽을거리 전용 priority — 소스 가중치 반영
        blog_priority = priority + BLOG_SOURCE_WEIGHTS.get(row["source"], 0)

    return {
        "id": row["id"],
        "source": row["source"],
        "category": row["category"],
        "subtype": _col(row, "subtype"),
        "title": row["title"],
        "venue": row["venue"],
        "address": row["address"],
        "url": row["url"],
        "image": row["image_url"],
        "description": (row["description"] or "")[:400] if row["description"] else None,
        "lat": row["lat"],
        "lon": row["lon"],
        "nx": row["nx"],
        "ny": row["ny"],
        "start": row["start_date"],
        "end": row["end_date"],
        "price": _col(row, "price"),
        # VisitBusan enrichment
        "rating": _col(row, "rating"),
        "views": _col(row, "view_count"),
        "reviews": _col(row, "review_count"),
        "tags": tags,
        "story_url": _col(row, "story_url"),
        "excerpt": _col(row, "story_excerpt"),
        "hours": _col(row, "hours"),
        "holiday": _col(row, "holiday"),
        "fee": _col(row, "fee"),
        "transport": _col(row, "transport"),
        "tip": _col(row, "tip"),
        "phone": _col(row, "phone"),
        # Hero Top 3 재설계용 (이벤트에만 값, places 는 None)
        "priority": priority,
        "blog_priority": blog_priority,
        "hero_tags": hero_tags or None,
    }


def export_places(conn: sqlite3.Connection) -> int:
    """Places: food + cafe + attraction + theme. (해변은 beaches.json 으로 별도 export)

    중복 제거 (dedup): 같은 POI 를 여러 source (KTO + VisitBusan) 에서 수집할 수 있음.
    → 좌표 근접성(소수 3자리) + 제목 첫 4글자 로 dedup. visitbusan 소스 우선(스토리 풍부).
    """
    rows_raw = list(conn.execute(
        "SELECT * FROM events WHERE category IN ('food','cafe','attraction','theme') "
        "AND lat IS NOT NULL "
        # vb_* source 우선 정렬 → 같은 dedup 키에서 먼저 들어온 vb_ 가 채택됨
        "ORDER BY CASE WHEN source LIKE 'vb_%' THEN 0 ELSE 1 END, category, title"
    ))
    seen: dict[tuple, dict] = {}
    for r in rows_raw:
        if r["lat"] is None or r["lon"] is None:
            continue
        key = (round(r["lat"], 3), round(r["lon"], 3), (r["title"] or "")[:4])
        if key in seen:
            continue
        seen[key] = _jsonable(r)
    rows = list(seen.values())
    (OUT_DIR / "places.json").write_text(
        json.dumps({"count": len(rows), "places": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(rows)


def export_courses(conn: sqlite3.Connection) -> int:
    """vb_courses → courses.json. 일정여행 코스 + 포함 POI 리스트."""
    import json as _json
    rows = []
    for r in conn.execute(
        "SELECT uc_seq, title, subtitle, duration, rating, view_count, image_url, "
        "       story_url, story_excerpt, tags_json, pois_json "
        "FROM vb_courses ORDER BY view_count DESC NULLS LAST"
    ):
        rows.append({
            "uc_seq": r[0],
            "title": r[1],
            "subtitle": r[2],
            "duration": r[3],
            "rating": r[4],
            "views": r[5],
            "image": r[6],
            "story_url": r[7],
            "excerpt": r[8],
            "tags": _json.loads(r[9]) if r[9] else [],
            "pois": _json.loads(r[10]) if r[10] else [],
        })
    (OUT_DIR / "courses.json").write_text(
        json.dumps({"count": len(rows), "courses": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(rows)


def export_events(conn: sqlite3.Connection) -> dict[str, int]:
    """월별 분할 + 날짜 없는 것은 events-undated.json.

    blog_post 는 TOUR_NEGATIVE_KEYWORDS 로 1차 필터링해 관광 무관 시정 공지 제거.
    festival/exhibition/performance 는 필터 대상 아님 (행사 성격이라 관광 가치 있음).
    """
    by_month: dict[str, list] = defaultdict(list)
    blog_kept = blog_dropped = 0
    for r in conn.execute(
        "SELECT * FROM events WHERE category IN ('festival','blog_post','exhibition','performance') "
        "ORDER BY start_date"
    ):
        row = _jsonable(r)
        if row["category"] == "blog_post" and not _is_tour_friendly_blog(row["title"], row.get("description")):
            blog_dropped += 1
            continue
        if row["category"] == "blog_post":
            blog_kept += 1
        if row["start"] and len(row["start"]) >= 7:
            key = row["start"][:7]  # YYYY-MM
        else:
            key = "undated"
        by_month[key].append(row)
    print(f"[blog filter] kept={blog_kept} dropped={blog_dropped}")
    result = {}
    for key, rows in by_month.items():
        fname = f"events-{key}.json"
        (OUT_DIR / fname).write_text(
            json.dumps({"count": len(rows), "events": rows}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        result[key] = len(rows)
    return result


def export_weather_short(conn: sqlite3.Connection) -> int:
    """격자별 시간순 예보 그룹."""
    by_cell: dict[str, list] = defaultdict(list)
    for r in conn.execute(
        "SELECT nx, ny, fcst_ts, tmp, pty, sky, pop, reh, wsd FROM weather_fcst "
        "WHERE source='short' ORDER BY nx, ny, fcst_ts"
    ):
        key = f"{r[0]}_{r[1]}"
        by_cell[key].append({
            "ts": r[2], "tmp": r[3], "pty": r[4], "sky": r[5],
            "pop": r[6], "reh": r[7], "wsd": r[8],
        })
    (OUT_DIR / "weather-short.json").write_text(
        json.dumps({"cells": len(by_cell), "data": by_cell}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return sum(len(v) for v in by_cell.values())


def export_weather_mid(conn: sqlite3.Connection) -> int:
    rows = [
        {"ts": r[0], "tmp": r[1], "pty": r[2], "sky": r[3], "pop": r[4]}
        for r in conn.execute(
            "SELECT fcst_ts, tmp, pty, sky, pop FROM weather_fcst "
            "WHERE source='mid' ORDER BY fcst_ts"
        )
    ]
    (OUT_DIR / "weather-mid.json").write_text(
        json.dumps({"count": len(rows), "data": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(rows)


def export_air_quality(conn: sqlite3.Connection) -> int:
    """측정소별 최근 24시간 시계열."""
    by_station: dict[str, list] = defaultdict(list)
    for r in conn.execute(
        "SELECT station, ts, pm10, pm25, o3, grade_pm10, grade_pm25 FROM air_quality "
        "ORDER BY station, ts DESC"
    ):
        if len(by_station[r[0]]) >= 24:
            continue
        by_station[r[0]].append({
            "ts": r[1], "pm10": r[2], "pm25": r[3], "o3": r[4],
            "grade_pm10": r[5], "grade_pm25": r[6],
        })
    # 측정소 좌표
    stations = [
        {"code": s[0], "name": s[1], "lat": s[2], "lon": s[3], "recent": by_station.get(s[0], [])}
        for s in conn.execute("SELECT code, name, lat, lon FROM air_station")
    ]
    (OUT_DIR / "air-quality.json").write_text(
        json.dumps({"count": len(stations), "stations": stations}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return sum(len(v) for v in by_station.values())


def export_beaches(conn: sqlite3.Connection) -> int:
    """beach_poi + 최신 수질 요약."""
    rows = []
    for r in conn.execute("SELECT name, lat, lon, inspec_key FROM beach_poi"):
        latest = conn.execute(
            "SELECT inspec_ym, water01, water02, comment FROM beach_water "
            "WHERE beach=? ORDER BY inspec_ym DESC LIMIT 1",
            (r[0],),
        ).fetchone()
        rows.append({
            "name": r[0], "lat": r[1], "lon": r[2],
            "latest_water": {
                "ym": latest[0], "water01": latest[1], "water02": latest[2], "comment": latest[3]
            } if latest else None,
        })
    (OUT_DIR / "beaches.json").write_text(
        json.dumps({"count": len(rows), "beaches": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    places = export_places(conn)
    events = export_events(conn)
    courses = export_courses(conn)
    w_short = export_weather_short(conn)
    w_mid = export_weather_mid(conn)
    air = export_air_quality(conn)
    beaches = export_beaches(conn)

    manifest = {
        "generated_at": now,
        "version": now.replace(":", "").replace("-", "")[:15],
        "counts": {
            "places": places,
            "courses": courses,
            "events_by_month": events,
            "weather_short_rows": w_short,
            "weather_mid_rows": w_mid,
            "air_quality_rows": air,
            "beaches": beaches,
        },
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
