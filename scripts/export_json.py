"""SQLite events.db → frontend/public/data/ JSON export.

출력:
  places.json          고정 POI (맛집/명소/안내소/해수욕장)
  events-YYYY-MM.json  월별 이벤트 (축제/공연, start_date 기준)
  weather-short.json   단기예보 (모든 격자 × 3시간 간격)
  weather-mid.json     중기예보 (부산 단일, D+3~D+10)
  air-quality.json     대기질 측정소별 최신값
  manifest.json        version, generated_at, counts
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "events.db"
OUT_DIR = ROOT / "frontend" / "public" / "data"

PLACE_CATEGORIES = {"food", "attraction", "info_office", "beach"}
EVENT_CATEGORIES = {"festival", "blog_post"}


def _jsonable(row: sqlite3.Row) -> dict:
    """Whitelist-safe dict (raw_json/민감 필드 제외)."""
    return {
        "id": row["id"],
        "source": row["source"],
        "category": row["category"],
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
        "price": row["price"] if "price" in row.keys() else None,
    }


def export_places(conn: sqlite3.Connection) -> int:
    rows = [
        _jsonable(r)
        for r in conn.execute(
            "SELECT * FROM events WHERE category IN ('food','attraction','info_office','beach') "
            "AND lat IS NOT NULL ORDER BY category, title"
        )
    ]
    (OUT_DIR / "places.json").write_text(
        json.dumps({"count": len(rows), "places": rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(rows)


def export_events(conn: sqlite3.Connection) -> dict[str, int]:
    """월별 분할 + 날짜 없는 것은 events-undated.json."""
    by_month: dict[str, list] = defaultdict(list)
    for r in conn.execute(
        "SELECT * FROM events WHERE category IN ('festival','blog_post') ORDER BY start_date"
    ):
        row = _jsonable(r)
        if row["start"] and len(row["start"]) >= 7:
            key = row["start"][:7]  # YYYY-MM
        else:
            key = "undated"
        by_month[key].append(row)
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
    w_short = export_weather_short(conn)
    w_mid = export_weather_mid(conn)
    air = export_air_quality(conn)
    beaches = export_beaches(conn)

    manifest = {
        "generated_at": now,
        "version": now.replace(":", "").replace("-", "")[:15],
        "counts": {
            "places": places,
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
