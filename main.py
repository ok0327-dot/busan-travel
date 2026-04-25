"""Entry point: fetch all sources → upsert to SQLite → print summary.

소스 수집 전략 (Phase A 정비, 2026-04-25):
- 공식만 채택: 정부 API + 부산관광공사(visitbusan) + 부산시 직속 공식 블로그 8개.
- 부산푸디(15063472) = '부산광역시_부산맛집정보' API 재활성화: visitbusan 큐레이션엔
  없는 대표메뉴(RPRSNTV_MENU)·구군(GUGUN_NM) 메타를 enrich 보강.
"""
from __future__ import annotations

import sys
from datetime import date

from dotenv import load_dotenv

from config import DB_PATH
from sources import (
    art_busan,
    busan_festival,
    busan_food,
    dabom,
    dureraum,
    festivalbusan,
    gov_tour,
    moca_busan,
    naver_blogs,
    naver_local,
    visitbusan,
)
from storage.db import Event, connect, upsert_events

# KOPIS 는 공연시설/기획제작사만 가입 가능해 사용 불가 — sources/kopis.py 는 보존
# 해수욕장(gov_beach)은 측정 시계열이라 별도 cron, 기상/대기질도 별도
SOURCES = [
    ("busan_festival",         busan_festival.fetch),       # 정부 API: 부산축제정보
    ("busan_food",             busan_food.fetch),            # 정부 API: 부산푸디(부산맛집정보) 15063472 — 대표메뉴/구군 enrich
    ("tour_api",               gov_tour.fetch),              # 정부 API: TourAPI 4.0 부산 축제
    ("naver_blogs",            naver_blogs.fetch),           # 공식 지자체 블로그 8개 RSS
    # VisitBusan.net 큐레이션 (부산관광공사)
    ("vb_attraction",          visitbusan.fetch_attractions),
    ("vb_food_curated",        visitbusan.fetch_food_curated),
    ("vb_festival_curated",    visitbusan.fetch_festival_curated),
    ("vb_theme",               visitbusan.fetch_themes),
    ("vb_schedule_board",      visitbusan.fetch_schedule_board),
    # Phase v3.4 — 메인 venue + 부산축제조직위 직접 스크래핑
    ("moca_busan",             moca_busan.fetch),     # 부산현대미술관 전시
    ("dureraum",               dureraum.fetch),       # 영화의전당 공연
    ("festivalbusan",          festivalbusan.fetch),  # 부산축제조직위 8개 메인 축제
    # Phase v3.5 — 네이버 동네 신상 식당/카페
    ("naver_local",            naver_local.fetch),    # NAVER local API 신상 키워드
    # Phase v3.6 — 부산시립미술관 추가 (Sprint 1 / A2)
    ("art_busan",              art_busan.fetch),      # 부산시립미술관 전시
    # Sprint 2 — 부산문화포털 다봄 (부산 전체 공연 통합, 159건)
    ("dabom",                  dabom.fetch),
]


def run() -> int:
    load_dotenv()
    conn = connect(DB_PATH)
    total_new = total_upd = 0
    for name, fetch_fn in SOURCES:
        try:
            events: list[Event] = fetch_fn()
        except Exception as exc:
            print(f"[{name}] FAILED: {exc}", file=sys.stderr)
            continue
        ins, upd = upsert_events(conn, events)
        total_new += ins
        total_upd += upd
        print(f"[{name}] fetched={len(events)} new={ins} updated={upd}")

    # 일정여행 코스 — 별도 vb_courses 테이블 사용
    try:
        c_ins, c_upd = visitbusan.fetch_courses_as_table()
        print(f"[vb_courses] new={c_ins} updated={c_upd}")
    except Exception as exc:
        print(f"[vb_courses] FAILED: {exc}", file=sys.stderr)

    today = date.today().isoformat()
    upcoming = conn.execute(
        "SELECT title, start_date, venue FROM events "
        "WHERE start_date IS NULL OR start_date >= ? "
        "ORDER BY start_date LIMIT 20",
        (today,),
    ).fetchall()
    print(f"\n=== Upcoming / undated ({len(upcoming)}) ===")
    for row in upcoming:
        print(f"  {row['start_date'] or '?':<12} {row['title']}  @ {row['venue'] or '-'}")

    print(f"\nTotal new={total_new} updated={total_upd}  db={DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
