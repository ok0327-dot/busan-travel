"""Entry point: fetch all sources → upsert to SQLite → print summary.

TODO next sources: kopis, tour_api, visitbusan, bscf, yes24, rss_feeds
"""
from __future__ import annotations

import sys
from datetime import date

from dotenv import load_dotenv

from config import DB_PATH
from sources import (
    busan_attraction,
    busan_festival,
    busan_food,
    gov_info_office,
    gov_tour,
    naver_blogs,
)
from storage.db import Event, connect, upsert_events

# KOPIS 는 공연시설/기획제작사만 가입 가능해 사용 불가 — sources/kopis.py 는 보존
# 해수욕장(gov_beach)은 측정 시계열이라 별도 cron, 기상/대기질도 별도
SOURCES = [
    ("busan_festival",    busan_festival.fetch),
    ("busan_food",        busan_food.fetch),
    ("busan_attraction",  busan_attraction.fetch),
    ("busan_info_office", gov_info_office.fetch),
    ("tour_api",          gov_tour.fetch),
    ("naver_blogs",       naver_blogs.fetch),
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
