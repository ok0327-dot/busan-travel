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
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "events.db"
OUT_DIR = ROOT / "frontend" / "public" / "data"

sys.path.insert(0, str(ROOT))
from sources._tour_filter import (  # noqa: E402
    importance_score,
    SCALE_POSITIVE_KEYWORDS,
    NEGATIVE_KEYWORDS as TOUR_NEGATIVE_KEYWORDS,
)
from sources._venues import is_major_venue  # noqa: E402

# 읽을거리 탭 전용 소스 가중치 — 공식 블로그만 채택 (Phase A 정비, 2026-04-25)
BLOG_SOURCE_WEIGHTS = {
    "naver_blog:bscf2009":     +3,   # 부산문화재단
    "naver_blog:hudpr":        +3,   # 해운대구청
    "naver_blog:moca_busan":   +3,   # 부산현대미술관
    "naver_blog:bsbukgusns":   +2,   # 북구청
    "naver_blog:bsjunggu":     +2,   # 중구청
    "naver_blog:yeonjegu":     +2,   # 연제구청
    "naver_blog:bsdonggublog": +2,   # 동구청
    "naver_blog:cooolbusan":   +1,   # 부산광역시 공식
}


def compute_popularity(row, priority: int | None = None) -> int:
    """카테고리별 0~100 popularity score.

    food/cafe   : naver_review_count log10 + vb rating ±10 + naver_local +8
    attraction  : view_count log10 + vb rating ±16
    festival/exhibition/performance : importance_score (priority) × 8
    """
    cat = row["category"]
    if cat in ("food", "cafe"):
        # 블로그 언급이 주 신호 (변별력), vb rating 은 거의 5.0 이라 보조만
        nrv = _col(row, "naver_review_count") or 0
        if nrv > 0:
            base = min(85.0, 20 * math.log10(nrv))  # 1K→60, 10K→80, 100K→85
        else:
            base = 0.0  # enrich 안 된 POI 는 후순위
        rating = _col(row, "rating") or 0
        if rating:
            base += (rating - 3) * 2  # 약한 보정
        if row["source"] == "naver_local":
            base += 10  # 신상 가산점
        return max(0, min(100, round(base)))
    if cat == "attraction":
        views = _col(row, "view_count") or 0
        base = min(80.0, 15 * math.log10(views + 1)) if views > 0 else 30.0
        rating = _col(row, "rating") or 0
        if rating:
            base += (rating - 3) * 8
        return max(0, min(100, round(base)))
    if cat in ("festival", "exhibition", "performance"):
        p = priority or 0
        return max(0, min(100, round(p * 8)))
    return 0


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

PLACE_CATEGORIES = {"food", "cafe", "attraction"}  # bar 는 food 에 흡수 (사용자 결정)
EVENT_CATEGORIES = {"festival", "blog_post"}
# guide = visitbusan 매거진 가이드 글. 지도 마커 X, 읽을거리 탭에 매거진 카드로 노출

# blog_post 필터 — TOUR_NEGATIVE_KEYWORDS 는 sources/_tour_filter.NEGATIVE_KEYWORDS 단일 소스 (P1-1).
# 원칙: 보수적 블랙리스트 — 애매하면 포함. festival/exhibition/performance 는 필터 대상 아님.


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

    popularity_score = compute_popularity(row, priority=priority)
    return {
        "id": row["id"],
        "source": row["source"],
        "category": row["category"],
        "subtype": _col(row, "subtype"),
        "trust_tier": _col(row, "trust_tier"),
        "menu": _col(row, "menu"),
        "gugun": _col(row, "gugun"),
        "popularity_score": popularity_score,
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
        "booking_required": _col(row, "booking_required"),
        "booking_deadline": _col(row, "booking_deadline"),
        "booking_opens_at": _col(row, "booking_opens_at"),
        # VisitBusan enrichment
        "rating": _col(row, "rating"),
        "views": _col(row, "view_count"),
        "reviews": _col(row, "review_count"),
        # Naver 블로그 리뷰 수 (food/cafe POI enrich)
        "naver_reviews": _col(row, "naver_review_count"),
        "tags": tags,
        "first_seen": _col(row, "first_seen"),
        "story_url": _col(row, "story_url"),
        "excerpt": _col(row, "story_excerpt"),
        "hours": _col(row, "hours"),
        "holiday": _col(row, "holiday"),
        "fee": _col(row, "fee"),
        "transport": _col(row, "transport"),
        "tip": _col(row, "tip"),
        "phone": _col(row, "phone"),
        # 갈맷길 enrich (15077606): course 1~9, gugan 1~3
        "galmaet_course": _col(row, "galmaet_course"),
        "galmaet_gugan": _col(row, "galmaet_gugan"),
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
        # bar 카테고리 폐기 (2026-04-26) — 술집은 food 로 통합. 옛 bar row 가 잔존해도 export 에서 자동 제외 (UPDATE 후 cron 정합).
        "SELECT * FROM events WHERE category IN ('food','cafe','attraction') "
        "AND lat IS NOT NULL "
        # vb_* + galmaet (단독 추가) 도 명소로 export. 정렬: vb_* > galmaet > 기타
        "ORDER BY CASE WHEN source LIKE 'vb_%' THEN 0 WHEN source='galmaet' THEN 1 ELSE 2 END, category, title"
    ))
    # 카테고리 specificity (낮을수록 specific). 같은 좌표·제목 충돌 시
    # 더 specific 한 카테고리(cafe/bar)가 generic(food/attraction)을 덮어쓴다.
    # v3.9 override 이후 새 데이터가 들어와도 silent bug 재발 방지.
    SPEC_RANK = {"cafe": 0, "food": 1, "attraction": 2}

    seen: dict[tuple, dict] = {}
    for r in rows_raw:
        if r["lat"] is None or r["lon"] is None:
            continue
        key = (round(r["lat"], 3), round(r["lon"], 3), (r["title"] or "")[:4])
        if key in seen:
            existing = seen[key]
            # Phase B — 부산푸디(busan_food) 의 menu/gugun 을 vb_food 레코드에 머지
            # vb_food_curated 가 우선 채택돼도 부산푸디 고유 메타(대표메뉴/구군)는 보존
            menu = _col(r, "menu")
            gugun = _col(r, "gugun")
            if menu and not existing.get("menu"):
                existing["menu"] = menu
            if gugun and not existing.get("gugun"):
                existing["gugun"] = gugun
            # 카테고리 promotion (specific > generic)
            new_cat = r["category"]
            if SPEC_RANK.get(new_cat, 9) < SPEC_RANK.get(existing.get("category"), 9):
                existing["category"] = new_cat
            continue
        seen[key] = _jsonable(r)
    rows = list(seen.values())
    (OUT_DIR / "places.json").write_text(
        json.dumps({"count": len(rows), "places": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(rows)


def export_guides(conn: sqlite3.Connection) -> int:
    """guide 카테고리(visitbusan 매거진) → guides.json. 좌표가 있어도 마커 X, 읽을거리 탭 카드용.

    dedup: title 정규화. 우선순위: vb_theme > 기타.
    정렬: visitbusan 게시 ID(raw.list_item.uc_seq) DESC = 최신순. 없으면 view_count DESC.
    """
    import json as _json
    seen_titles: set = set()
    items = []
    for r in conn.execute(
        "SELECT * FROM events WHERE category='guide' "
        "ORDER BY CASE WHEN source='vb_theme' THEN 0 ELSE 1 END, title"
    ):
        title = (r["title"] or "").strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        # visitbusan 게시 ID 추출
        uc = 0
        try:
            raw = _json.loads(r["raw_json"] or "{}")
            uc = int((raw.get("list_item") or {}).get("uc_seq") or 0)
        except (ValueError, TypeError):
            uc = 0
        rec = _jsonable(r)
        rec["_uc"] = uc
        items.append(rec)
    # 최신 게시 ID(uc_seq) 우선, 없으면 view_count
    items.sort(key=lambda x: (x.get("_uc") or 0, x.get("views") or 0), reverse=True)
    rows = []
    for x in items:
        x.pop("_uc", None)
        rows.append(x)
    (OUT_DIR / "guides.json").write_text(
        json.dumps({"count": len(rows), "guides": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(rows)


def export_courses(conn: sqlite3.Connection) -> int:
    """vb_courses → courses.json. 일정여행 코스 + 포함 POI 리스트.

    정렬: uc_seq DESC = visitbusan 게시 ID 최신순 (사용자 요청).
    """
    import json as _json
    rows = []
    for r in conn.execute(
        "SELECT uc_seq, title, subtitle, duration, rating, view_count, image_url, "
        "       story_url, story_excerpt, tags_json, pois_json "
        "FROM vb_courses ORDER BY uc_seq DESC"
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
    exhibition/performance 는 sources/_venues.py 의 is_major venue 통과 건만 keep
    (동네 갤러리·카페 전시·지역명만 있는 소규모 건 drop).
    festival 은 전부 keep (축제 성격이라 규모 무관 관광 가치).

    P3 노이즈 정리: end_date 가 today-14일 이전인 종료 행사는 export 에서 제외.
    """
    from datetime import timedelta
    expired_cutoff = (date.today() - timedelta(days=14)).isoformat()
    by_month: dict[str, list] = defaultdict(list)
    blog_kept = blog_dropped = 0
    minor_dropped = 0
    expired_dropped = 0
    for r in conn.execute(
        "SELECT * FROM events WHERE category IN ('festival','blog_post','exhibition','performance') "
        "ORDER BY start_date"
    ):
        row = _jsonable(r)
        cat = row["category"]
        # P3: 종료된 행사 drop (end_date 명시 + 14일 지난 것만. blog_post 는 게시일이라 제외)
        if cat != "blog_post":
            end = row.get("end") or ""
            if end and end < expired_cutoff:
                expired_dropped += 1
                continue
        if cat == "blog_post" and not _is_tour_friendly_blog(row["title"], row.get("description")):
            blog_dropped += 1
            continue
        # 규모 필터 — 전시/공연만 is_major venue 화이트리스트 통과분만
        if cat in ("exhibition", "performance") and not is_major_venue(row.get("venue")):
            minor_dropped += 1
            continue
        if cat == "blog_post":
            blog_kept += 1
        if row["start"] and len(row["start"]) >= 7:
            key = row["start"][:7]  # YYYY-MM
        else:
            key = "undated"
        by_month[key].append(row)
    print(f"[blog filter] kept={blog_kept} dropped={blog_dropped}")
    print(f"[venue filter] exhibition/performance minor dropped={minor_dropped}")
    print(f"[expired filter] end_date<{expired_cutoff} dropped={expired_dropped}")
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


def export_adapter_health(conn: sqlite3.Connection) -> dict:
    """소스별 health 메타 — last_seen, row count, freshness staleness 판정용.

    last_seen 은 어댑터가 마지막으로 해당 row 를 갱신한 UTC ISO. 모든 소스가
    매 cron 마다 upsert 하므로 최근값이 어댑터 마지막 성공 시점에 해당.
    """
    rows = conn.execute(
        "SELECT source, COUNT(*) as cnt, MAX(last_seen) as last_seen "
        "FROM events GROUP BY source ORDER BY source"
    ).fetchall()
    return {r["source"]: {"rows": r["cnt"], "last_seen": r["last_seen"]} for r in rows}


def main():
    """--scope all|events|weather (default all).

    weather scope 는 cron 3시간마다 weather-only 빌드 전용:
    weather-short / weather-mid / air-quality / manifest 의 weather 카운트만 갱신.
    places.json / events-*.json 은 절대 건드리지 않음 → silent overwrite 차단.
    events scope 는 weather 측정 데이터를 만지지 않음 (수동 백필 시나리오).
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=["all", "events", "weather"],
        default="all",
        help="all=전체 / events=POI/이벤트만 / weather=날씨·대기만",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 기존 manifest 읽기 (부분 빌드 시 머지용)
    manifest_path = OUT_DIR / "manifest.json"
    prev = {}
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    counts = dict(prev.get("counts") or {})
    adapters = prev.get("adapters") or {}

    if args.scope in ("all", "events"):
        counts["places"] = export_places(conn)
        counts["events_by_month"] = export_events(conn)
        counts["courses"] = export_courses(conn)
        counts["guides"] = export_guides(conn)
        counts["beaches"] = export_beaches(conn)
        adapters = export_adapter_health(conn)

    if args.scope in ("all", "weather"):
        counts["weather_short_rows"] = export_weather_short(conn)
        counts["weather_mid_rows"] = export_weather_mid(conn)
        counts["air_quality_rows"] = export_air_quality(conn)

    manifest = {
        "generated_at": now,
        "version": now.replace(":", "").replace("-", "")[:15],
        "scope": args.scope,
        "counts": counts,
        "adapters": adapters,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
