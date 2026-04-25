"""AI 일일 요약 — Gemini 2.5 Flash 기반 (Phase D).

DB의 오늘/이번주말 행사 + 부산 중심 날씨 + 제철 컨텍스트를 종합해
"부산에서 뭐할지" 한 문단 요약 + 페르소나별 반나절~1일 코스 3종을 생성.

출력: frontend/public/data/ai-summary.json (latest, 매일 갱신)
호출: GitHub Actions cron 후처리 (또는 로컬 수동).
GEMINI_API_KEY 미설정 시 silent skip — 프론트는 ai-pick 카드 hidden.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "events.db"
OUT_PATH = ROOT / "frontend" / "public" / "data" / "ai-summary.json"
SEASONAL_PATH = ROOT / "frontend" / "public" / "data" / "seasonal.json"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
SKY_MAP = {1: "맑음", 3: "구름많음", 4: "흐림"}
PTY_MAP = {1: "비", 2: "비/눈", 3: "눈", 4: "소나기"}

_SEG_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["title", "why"],
            },
        },
    },
    "required": ["summary", "picks"],
}
SCHEMA = {
    "type": "object",
    "properties": {
        "today":         _SEG_SCHEMA,
        "tomorrow":      _SEG_SCHEMA,
        "weekend":       _SEG_SCHEMA,
        "next_weekend":  _SEG_SCHEMA,
        "courses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "title": {"type": "string"},
                    "stops": {"type": "array", "items": {"type": "string"}},
                    "note": {"type": "string"},
                },
                "required": ["label", "title", "stops"],
            },
        },
    },
    "required": ["today", "tomorrow", "weekend", "next_weekend", "courses"],
}


def fetch_events_for_window(conn: sqlite3.Connection, start_d: date, days: int, limit: int = 12):
    """start_d ~ start_d+days 범위에 active 또는 upcoming 인 행사.

    필터:
    - 공식 출처(trust_tier S/A)만
    - duration > 60일 = 상설/정기 행사 (광안리 드론쇼 등 365일짜리) 제외
    - title 에 '정기/매주/매달/월 공연/월 프로그램/상설/운영 안내' 패턴 = 정기 행사 제외
    """
    end = start_d + timedelta(days=days)
    s_iso, e_iso = start_d.isoformat(), end.isoformat()
    rows = conn.execute(
        """SELECT title, category, start_date, end_date, venue, address, description
           FROM events
           WHERE category IN ('festival','exhibition','performance')
             AND start_date IS NOT NULL
             AND trust_tier IN ('S','A')
             AND (
                  (start_date <= ? AND COALESCE(end_date, start_date) >= ?)
                  OR (start_date BETWEEN ? AND ?)
                 )
             AND lat IS NOT NULL
             -- duration > 60일 = 상설/정기 행사 제외
             AND (julianday(COALESCE(end_date, start_date)) - julianday(start_date)) <= 60
             -- 정기 패턴 제외
             AND title NOT LIKE '%정기%'
             AND title NOT LIKE '%매주%'
             AND title NOT LIKE '%매달%'
             AND title NOT LIKE '%월 공연%'
             AND title NOT LIKE '%월 프로그램%'
             AND title NOT LIKE '%월별 프로그램%'
             AND title NOT LIKE '%상설%'
             AND title NOT LIKE '%운영 안내%'
             AND title NOT LIKE '%운영안내%'
           ORDER BY
             CASE WHEN start_date <= ? AND COALESCE(end_date, start_date) >= ? THEN 0 ELSE 1 END,
             start_date""",
        (s_iso, s_iso, s_iso, e_iso, s_iso, s_iso),
    ).fetchall()
    return rows[:limit]


def fetch_weather(conn: sqlite3.Connection, target_date: date) -> str | None:
    """부산 중심(nx=97, ny=74) 격자에서 target_date 정오 직후 첫 예보.

    fcst_ts 형식은 'YYYYMMDDThh:00' (KMA 단기예보 raw). isoformat 과 다름 — 형식 일치 필수.
    """
    ymd = target_date.strftime("%Y%m%d")
    target_ts = f"{ymd}T12:00"
    row = conn.execute(
        "SELECT tmp, pty, sky, pop FROM weather_fcst "
        "WHERE source='short' AND nx=97 AND ny=74 AND fcst_ts >= ? "
        "ORDER BY fcst_ts LIMIT 1",
        (target_ts,),
    ).fetchone()
    if not row:
        return None
    tmp, pty, sky, pop = row
    bits = []
    if sky in SKY_MAP:
        bits.append(SKY_MAP[sky])
    if pty and pty in PTY_MAP:
        bits.append(PTY_MAP[pty])
    if tmp is not None:
        bits.append(f"{round(tmp)}°")
    if pop:
        bits.append(f"강수 {pop}%")
    return " · ".join(bits) if bits else None


def load_season(month: int) -> dict | None:
    if not SEASONAL_PATH.exists():
        return None
    try:
        data = json.loads(SEASONAL_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return (data.get("months") or {}).get(f"{month:02d}")


def format_event_line(row, anchor: date) -> str:
    """LLM 이 title 만 깔끔히 추출하도록 파이프 구분: TITLE | kind | venue | period.

    title 을 첫 칼럼에 단독 배치 → 모델이 "[..]" 같은 부수 마커를 title 에 끌어오지 않음.
    """
    title, cat, start, end, venue, addr, _desc = row
    cat_label = {"festival": "축제", "exhibition": "전시", "performance": "공연"}.get(cat, cat or "")
    end_eff = end or start
    if start and start <= anchor.isoformat() <= end_eff:
        kind = "진행중"
    else:
        try:
            d = (date.fromisoformat(start) - anchor).days
            kind = f"D-{d}" if d > 0 else "오늘"
        except (ValueError, TypeError):
            kind = ""
    period = start + (f"~{end}" if end and end != start else "")
    place = venue or addr or ""
    return f"TITLE: {title} | {cat_label} | {kind} | {place} | {period}"


def fetch_top_places(conn: sqlite3.Connection, category: str, limit: int = 8) -> list:
    """공식 출처(S) places 중 view_count 상위 — AI 후보 보강용 (행사 부족 시 명소 fallback)."""
    return conn.execute(
        """SELECT title, venue, address, gugun, menu, rating, view_count
           FROM events WHERE category=? AND trust_tier='S' AND lat IS NOT NULL
           ORDER BY view_count DESC NULLS LAST LIMIT ?""",
        (category, limit),
    ).fetchall()


def format_place_line(row) -> str:
    title, venue, addr, gugun, menu, rating, views = row
    where = gugun or venue or (addr or "").split()[0] if addr else ""
    extra = []
    if menu: extra.append(f"메뉴 {menu[:30]}")
    if rating: extra.append(f"★{rating}")
    return f"- {title}{' (' + where + ')' if where else ''}{' · ' + ' '.join(extra) if extra else ''}"


def build_prompt(today: date, tomorrow: date, weekend_start: date, next_weekend_start: date,
                 weather: dict, season: dict | None,
                 events_by_seg: dict, places_pool: dict) -> str:
    season_str = ""
    if season:
        foods = ", ".join(f.get("name", "") for f in (season.get("foods") or [])[:5])
        scenes = ", ".join((season.get("scenes") or [])[:3])
        bits = []
        if foods: bits.append(f"제철 음식 — {foods}")
        if scenes: bits.append(f"풍경 — {scenes}")
        season_str = " / ".join(bits)

    def evt_block(label: str, anchor: date, events: list) -> str:
        if not events:
            return f"[{label} ({anchor.isoformat()}) 행사 후보]\n- (없음 — 행사 한산. picks 는 명소·맛집 대안 후보에서 골라도 OK)"
        lines = "\n".join(f"- {format_event_line(r, anchor)}" for r in events)
        return f"[{label} ({anchor.isoformat()}) 행사 후보]\n{lines}"

    blocks = [
        evt_block("오늘", today, events_by_seg.get("today", [])),
        evt_block("내일", tomorrow, events_by_seg.get("tomorrow", [])),
        evt_block("이번 주말", weekend_start, events_by_seg.get("weekend", [])),
        evt_block("다음 주말", next_weekend_start, events_by_seg.get("next_weekend", [])),
    ]
    place_block = (
        "[명소·맛집·카페 인기 Top — 행사 부족 시 picks 또는 courses 에 활용]\n"
        + "\n".join(format_place_line(p) for p in places_pool.get("attractions", [])[:6])
        + "\n— 맛집:\n"
        + "\n".join(format_place_line(p) for p in places_pool.get("foods", [])[:6])
    )

    weekday = WEEKDAYS[today.weekday()]
    return f"""당신은 부산 여행 큐레이터입니다. 두 페르소나를 동시에 고려하세요:
A) 매주 금요일 서울에서 부산 가족(아내·9세 아들)을 만나러 오는 가장 — 가족 시간 우선
B) 부산 거주민으로 주말 뭐할지 고민하는 사람 — 평소 안 가본 동네 발굴 선호

오늘은 {today.isoformat()} ({weekday}요일).
부산 날씨:
- 오늘({today.isoformat()}): {weather.get('today') or '정보 없음'}
- 내일({tomorrow.isoformat()}): {weather.get('tomorrow') or '정보 없음'}
- 이번 주말({weekend_start.isoformat()}~): {weather.get('weekend') or '정보 없음'}
- 다음 주말({next_weekend_start.isoformat()}~): {weather.get('next_weekend') or '정보 없음'}
{today.month}월 부산 — {season_str or "(제철 정보 없음)"}

{chr(10).join(blocks)}

{place_block}

응답 규칙 (4 segment 모두 작성 필수: today / tomorrow / weekend / next_weekend):
- 4 segment 는 반드시 서로 다른 내용 — 같은 picks/summary 반복 금지.
- summary 는 110자 이내. 해당 segment 의 날씨 + 추천 1-2개를 한 문장으로.
- picks 는 위 [행사 후보] 또는 [명소·맛집 인기 Top] 에서만 선택 (창작 금지).
  행사가 한산한 segment 면 명소·맛집을 picks 로 골라도 됨.
- picks.title 은 'TITLE:' 다음 ' | ' 앞 부분 또는 명소/맛집 이름 그대로 복사.
  카테고리·진행상태·D-x·장소·날짜 메타는 title 에 포함 금지.
- picks.why 는 30자 이내. 액션 가이드 ("9세 아이 좋아함" / "비 와도 OK" / "구월 제철").
- courses 정확히 3개: label="가족(9세 아이)" / label="연인" / label="혼자/거주민".
  각 stops 3~4개. 위 데이터의 실제 부산 지명/명소만 사용. 비·눈 예보면 실내 강조.
- courses[i].note 는 50자 이내 팁 (이동 동선, 식사 타이밍 등).
"""


def call_gemini(api_key: str, prompt: str) -> dict:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0},
            "temperature": 0.6,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    r = requests.post(GEMINI_URL, params={"key": api_key}, json=body, timeout=60)
    r.raise_for_status()
    payload = r.json()
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        # silent skip 금지 — workflow 가 통과한 채 ai-summary.json 이 stale 로 남는 위험 차단.
        print("[ai_summary] FAIL: GEMINI_API_KEY 미설정", file=sys.stderr)
        return 1

    today = date.today()
    tomorrow = today + timedelta(days=1)
    delta_to_sat = (5 - today.weekday()) % 7
    weekend_start = today + timedelta(days=delta_to_sat)
    next_weekend_start = weekend_start + timedelta(days=7)

    conn = sqlite3.connect(DB_PATH)
    events_by_seg = {
        "today":        fetch_events_for_window(conn, today, days=0, limit=8),
        "tomorrow":     fetch_events_for_window(conn, tomorrow, days=0, limit=8),
        "weekend":      fetch_events_for_window(conn, weekend_start, days=1, limit=10),
        "next_weekend": fetch_events_for_window(conn, next_weekend_start, days=1, limit=10),
    }
    weather = {
        "today":        fetch_weather(conn, today),
        "tomorrow":     fetch_weather(conn, tomorrow),
        "weekend":      fetch_weather(conn, weekend_start),
        "next_weekend": fetch_weather(conn, next_weekend_start),
    }
    places_pool = {
        "attractions": fetch_top_places(conn, "attraction", 8),
        "foods":       fetch_top_places(conn, "food", 8),
    }
    season = load_season(today.month)

    prompt = build_prompt(today, tomorrow, weekend_start, next_weekend_start,
                          weather, season, events_by_seg, places_pool)
    counts = {k: len(v) for k, v in events_by_seg.items()}
    print(f"[ai_summary] events={counts} places=attr:{len(places_pool['attractions'])} food:{len(places_pool['foods'])} prompt={len(prompt)}c")

    try:
        result = call_gemini(api_key, prompt)
    except Exception as exc:
        print(f"[ai_summary] FAILED: {exc}", file=sys.stderr)
        return 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "valid_for": today.isoformat(),
        "dates": {
            "today": today.isoformat(),
            "tomorrow": tomorrow.isoformat(),
            "weekend": weekend_start.isoformat(),
            "next_weekend": next_weekend_start.isoformat(),
        },
        "weather": weather,
        **result,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ai_summary] wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
