"""SQLite storage for collected events."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    category    TEXT,
    title       TEXT NOT NULL,
    start_date  TEXT,
    end_date    TEXT,
    event_date  TEXT,
    booking_opens_at  TEXT,
    booking_deadline  TEXT,
    booking_required  INTEGER,
    venue       TEXT,
    address     TEXT,
    url         TEXT,
    price       TEXT,
    image_url   TEXT,
    description TEXT,
    family_score         INTEGER,
    couple_evening_score INTEGER,
    hype_level  TEXT,
    last_alerted_at TEXT,
    alert_history   TEXT,
    raw_json    TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    UNIQUE(source, source_id)
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_events_start      ON events(start_date);
CREATE INDEX IF NOT EXISTS idx_events_event_date ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_category   ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_source     ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_family     ON events(family_score);
CREATE INDEX IF NOT EXISTS idx_events_latlon     ON events(lat, lon);
CREATE INDEX IF NOT EXISTS idx_events_nxny       ON events(nx, ny);
"""

_MIGRATIONS = {
    "event_date":           "TEXT",
    "booking_opens_at":     "TEXT",
    "booking_deadline":     "TEXT",
    "booking_required":     "INTEGER",
    "family_score":         "INTEGER",
    "couple_evening_score": "INTEGER",
    "hype_level":           "TEXT",
    "last_alerted_at":      "TEXT",
    "alert_history":        "TEXT",
    "lat":                  "REAL",
    "lon":                  "REAL",
    "nx":                   "INTEGER",
    "ny":                   "INTEGER",
    "geocoded_at":          "TEXT",
    # VisitBusan enrichment (Phase 5)
    "rating":               "REAL",
    "view_count":           "INTEGER",
    "review_count":         "INTEGER",
    "tags_json":            "TEXT",
    "story_url":            "TEXT",
    "story_excerpt":        "TEXT",
    "hours":                "TEXT",
    "holiday":              "TEXT",
    "fee":                  "TEXT",
    "transport":            "TEXT",
    "tip":                  "TEXT",
    "etiquette":            "TEXT",
    "phone":                "TEXT",
    "subtype":              "TEXT",  # 호텔 등급, 음식 장르 등 세부 분류
    # Phase A — 데이터 신뢰도 메타 (S=공식 정부/공공 API, A=공식 지자체 블로그, B=뉴스 매체, X=비공식/검색기반)
    "trust_tier":           "TEXT",
    # Phase B — 부산푸디(15063472) enrichment: 대표메뉴, 구군
    "menu":                 "TEXT",
    "gugun":                "TEXT",
    # v3.7 — 외부 평점 enrichment (food/cafe POI 대상)
    "google_rating":        "REAL",     # Google Places rating 1.0~5.0
    "google_user_ratings":  "INTEGER",  # Google user_ratings_total
    "google_place_id":      "TEXT",     # Places place_id (재호출용)
    "naver_review_count":   "INTEGER",  # 네이버 블로그 검색 결과 수
    "ratings_enriched_at":  "TEXT",     # 마지막 enrich 일시 (ISO)
    # 갈맷길 enrich (15077606): 부산 영구 도보 코스 9개 + 구간 1~3
    "galmaet_course":       "INTEGER",  # 1~9 (갈맷길 코스 번호)
    "galmaet_gugan":        "INTEGER",  # 1~3 (코스 내 구간)
}

EXTRA_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS point_map (
    point_id     TEXT PRIMARY KEY,
    nx           INTEGER,
    ny           INTEGER,
    station_code TEXT,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS weather_fcst (
    nx          INTEGER NOT NULL,
    ny          INTEGER NOT NULL,
    fcst_ts     TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    tmp         REAL,
    pty         INTEGER,
    sky         INTEGER,
    pop         INTEGER,
    reh         INTEGER,
    wsd         REAL,
    updated_at  TEXT,
    PRIMARY KEY(nx, ny, fcst_ts, source)
);
CREATE TABLE IF NOT EXISTS air_station (
    code  TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    sido  TEXT,
    addr  TEXT,
    lat   REAL,
    lon   REAL,
    tm_x  REAL,
    tm_y  REAL
);
CREATE TABLE IF NOT EXISTS air_quality (
    station    TEXT NOT NULL,
    ts         TEXT NOT NULL,
    pm10       INTEGER,
    pm25       INTEGER,
    o3         REAL,
    no2        REAL,
    so2        REAL,
    co         REAL,
    grade_pm10 INTEGER,
    grade_pm25 INTEGER,
    PRIMARY KEY(station, ts)
);
CREATE TABLE IF NOT EXISTS beach_water (
    beach       TEXT NOT NULL,
    inspec_ym   TEXT NOT NULL,
    inspec_area TEXT NOT NULL,
    water01     TEXT,
    water02     TEXT,
    comment     TEXT,
    raw_json    TEXT,
    PRIMARY KEY(beach, inspec_ym, inspec_area)
);
CREATE TABLE IF NOT EXISTS beach_poi (
    name       TEXT PRIMARY KEY,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    inspec_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_weather_ts ON weather_fcst(fcst_ts);
CREATE INDEX IF NOT EXISTS idx_air_ts     ON air_quality(ts);

-- VisitBusan 일정여행 코스 (Phase 5)
CREATE TABLE IF NOT EXISTS vb_courses (
    uc_seq        INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    subtitle      TEXT,
    duration      TEXT,
    rating        REAL,
    view_count    INTEGER,
    image_url     TEXT,
    story_url     TEXT,
    story_excerpt TEXT,
    tags_json     TEXT,
    pois_json     TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vb_courses_dur ON vb_courses(duration);
"""


@dataclass
class Event:
    source: str
    source_id: str
    title: str
    category: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    event_date: str | None = None
    booking_opens_at: str | None = None
    booking_deadline: str | None = None
    booking_required: int | None = None
    venue: str | None = None
    address: str | None = None
    url: str | None = None
    price: str | None = None
    image_url: str | None = None
    description: str | None = None
    family_score: int | None = None
    couple_evening_score: int | None = None
    hype_level: str | None = None
    lat: float | None = None
    lon: float | None = None
    nx: int | None = None
    ny: int | None = None
    geocoded_at: str | None = None
    # VisitBusan enrichment
    rating: float | None = None
    view_count: int | None = None
    review_count: int | None = None
    tags_json: str | None = None
    story_url: str | None = None
    story_excerpt: str | None = None
    hours: str | None = None
    holiday: str | None = None
    fee: str | None = None
    transport: str | None = None
    tip: str | None = None
    etiquette: str | None = None
    phone: str | None = None
    subtype: str | None = None
    trust_tier: str | None = None
    menu: str | None = None
    gugun: str | None = None
    galmaet_course: int | None = None
    galmaet_gugan: int | None = None
    raw: dict = field(default_factory=dict)


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    for col, typ in _MIGRATIONS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {typ}")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(TABLE_SQL)
    _migrate(conn)
    conn.executescript(INDEX_SQL)
    conn.executescript(EXTRA_TABLES_SQL)
    return conn


def upsert_course(conn: sqlite3.Connection, course: dict) -> None:
    """vb_courses 테이블 upsert. course dict 는 어댑터에서 만든 형식."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT uc_seq FROM vb_courses WHERE uc_seq=?", (course["uc_seq"],)
    ).fetchone()
    fields = (
        course.get("title"), course.get("subtitle"), course.get("duration"),
        course.get("rating"), course.get("view_count"),
        course.get("image_url"), course.get("story_url"), course.get("story_excerpt"),
        json.dumps(course.get("tags", []), ensure_ascii=False),
        json.dumps(course.get("pois", []), ensure_ascii=False),
    )
    if row:
        conn.execute(
            """UPDATE vb_courses SET
                title=?, subtitle=?, duration=?, rating=?, view_count=?,
                image_url=?, story_url=?, story_excerpt=?, tags_json=?, pois_json=?,
                last_seen=?
               WHERE uc_seq=?""",
            (*fields, now, course["uc_seq"]),
        )
    else:
        conn.execute(
            """INSERT INTO vb_courses (
                uc_seq, title, subtitle, duration, rating, view_count,
                image_url, story_url, story_excerpt, tags_json, pois_json,
                first_seen, last_seen
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (course["uc_seq"], *fields, now, now),
        )
    conn.commit()


def upsert_events(conn: sqlite3.Connection, events: Iterable[Event]) -> tuple[int, int]:
    """Upsert events. Returns (inserted, updated)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = updated = 0
    for e in events:
        row = conn.execute(
            "SELECT id FROM events WHERE source=? AND source_id=?",
            (e.source, e.source_id),
        ).fetchone()
        payload = asdict(e)
        raw_json = json.dumps(payload.pop("raw"), ensure_ascii=False)
        core_fields = (
            e.category, e.title, e.start_date, e.end_date, e.event_date,
            e.booking_opens_at, e.booking_deadline, e.booking_required,
            e.venue, e.address, e.url, e.price, e.image_url, e.description,
            e.family_score, e.couple_evening_score, e.hype_level,
            e.lat, e.lon, e.nx, e.ny, e.geocoded_at,
        )
        vb_fields = (
            e.rating, e.view_count, e.review_count, e.tags_json,
            e.story_url, e.story_excerpt, e.hours, e.holiday, e.fee,
            e.transport, e.tip, e.etiquette, e.phone, e.subtype,
            e.trust_tier, e.menu, e.gugun,
            e.galmaet_course, e.galmaet_gugan,
        )
        if row:
            conn.execute(
                """UPDATE events SET
                    category=?, title=?, start_date=?, end_date=?, event_date=?,
                    booking_opens_at=?, booking_deadline=?, booking_required=?,
                    venue=?, address=?, url=?, price=?, image_url=?, description=?,
                    family_score=COALESCE(?, family_score),
                    couple_evening_score=COALESCE(?, couple_evening_score),
                    hype_level=COALESCE(?, hype_level),
                    lat=COALESCE(?, lat), lon=COALESCE(?, lon),
                    nx=COALESCE(?, nx), ny=COALESCE(?, ny),
                    geocoded_at=COALESCE(?, geocoded_at),
                    rating=COALESCE(?, rating),
                    view_count=COALESCE(?, view_count),
                    review_count=COALESCE(?, review_count),
                    tags_json=COALESCE(?, tags_json),
                    story_url=COALESCE(?, story_url),
                    story_excerpt=COALESCE(?, story_excerpt),
                    hours=COALESCE(?, hours),
                    holiday=COALESCE(?, holiday),
                    fee=COALESCE(?, fee),
                    transport=COALESCE(?, transport),
                    tip=COALESCE(?, tip),
                    etiquette=COALESCE(?, etiquette),
                    phone=COALESCE(?, phone),
                    subtype=COALESCE(?, subtype),
                    trust_tier=COALESCE(?, trust_tier),
                    menu=COALESCE(?, menu),
                    gugun=COALESCE(?, gugun),
                    galmaet_course=COALESCE(?, galmaet_course),
                    galmaet_gugan=COALESCE(?, galmaet_gugan),
                    raw_json=?, last_seen=?
                   WHERE id=?""",
                (*core_fields, *vb_fields, raw_json, now, row["id"]),
            )
            updated += 1
        else:
            conn.execute(
                """INSERT INTO events (
                    source, source_id, category, title, start_date, end_date, event_date,
                    booking_opens_at, booking_deadline, booking_required,
                    venue, address, url, price, image_url, description,
                    family_score, couple_evening_score, hype_level,
                    lat, lon, nx, ny, geocoded_at,
                    rating, view_count, review_count, tags_json,
                    story_url, story_excerpt, hours, holiday, fee,
                    transport, tip, etiquette, phone, subtype,
                    trust_tier, menu, gugun,
                    galmaet_course, galmaet_gugan,
                    raw_json, first_seen, last_seen
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (e.source, e.source_id, *core_fields, *vb_fields, raw_json, now, now),
            )
            inserted += 1
    conn.commit()
    return inserted, updated
