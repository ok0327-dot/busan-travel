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

SCHEMA = {
    "type": "object",
    "properties": {
        "today": {
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
        },
        "weekend": {
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
        },
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
    "required": ["today", "weekend", "courses"],
}


def fetch_events_for_window(conn: sqlite3.Connection, start_d: date, days: int, limit: int = 12):
    """start_d ~ start_d+days 범위에 active 또는 upcoming 인 행사."""
    end = start_d + timedelta(days=days)
    s_iso, e_iso = start_d.isoformat(), end.isoformat()
    # AI Pick 후보는 공식 출처(S=정부 API, A=공식 지자체 블로그)만 — naver_search:news 같은 단발 보도 제외
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
           ORDER BY
             CASE WHEN start_date <= ? AND COALESCE(end_date, start_date) >= ? THEN 0 ELSE 1 END,
             start_date""",
        (s_iso, s_iso, s_iso, e_iso, s_iso, s_iso),
    ).fetchall()
    return rows[:limit]


def fetch_weather(conn: sqlite3.Connection, target_date: date) -> str | None:
    """부산 중심(nx=97, ny=74) 격자에서 target_date 정오 직후 첫 예보."""
    target_ts = f"{target_date.isoformat()}T1200"
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


def build_prompt(today: date, weekend_start: date,
                 today_weather: str | None, weekend_weather: str | None,
                 season: dict | None,
                 today_events: list, weekend_events: list) -> str:
    season_str = ""
    if season:
        foods = ", ".join(f.get("name", "") for f in (season.get("foods") or [])[:5])
        scenes = ", ".join((season.get("scenes") or [])[:3])
        bits = []
        if foods: bits.append(f"제철 음식 — {foods}")
        if scenes: bits.append(f"풍경 — {scenes}")
        season_str = " / ".join(bits)
    today_lines = "\n".join(f"- {format_event_line(r, today)}" for r in today_events) or "- (없음)"
    weekend_lines = "\n".join(f"- {format_event_line(r, weekend_start)}" for r in weekend_events) or "- (없음)"
    weekday = WEEKDAYS[today.weekday()]
    return f"""당신은 부산 여행 큐레이터입니다. 두 페르소나를 동시에 고려하세요:
A) 매주 금요일 서울에서 부산 가족(아내·9세 아들)을 만나러 오는 가장 — 가족 시간 우선
B) 부산 거주민으로 주말 뭐할지 고민하는 사람 — 평소 안 가본 동네 발굴 선호

오늘은 {today.isoformat()} ({weekday}요일).
오늘 부산 날씨: {today_weather or "정보 없음"}
이번 주말 부산 날씨({weekend_start.isoformat()}~): {weekend_weather or "정보 없음"}
{today.month}월 부산 — {season_str or "(제철 정보 없음)"}

[오늘/임박 행사 후보]
{today_lines}

[이번 주말 행사 후보]
{weekend_lines}

응답 규칙:
- 한국어 자연체, 친근하지만 정보가 명확.
- summary 는 110자 이내. 날씨 한 마디 + 추천 1-2개를 한 문장으로 압축.
- picks 는 위 후보 리스트에서만 선택. 후보가 빈약하면 picks 를 0~1건으로 줄여도 됨 (창작 금지).
- picks.title 은 후보 리스트 라인의 'TITLE:' 다음 ' | ' 앞 부분을 그대로 복사. 카테고리·진행상태·D-x·장소·날짜 같은 메타는 절대 title 에 포함하지 마세요.
- picks.why 는 30자 이내. 액션 가이드 ("9세 아이 좋아함" / "비 와도 OK").
- courses 는 정확히 3개: label="가족(9세 아이)" / label="연인" / label="혼자/거주민".
  각 stops 3~4개. 부산 실제 지명/명소를 사용. 비·눈 예보면 실내 옵션 강조.
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
        print("[ai_summary] SKIP: GEMINI_API_KEY 미설정")
        return 0

    today = date.today()
    # 다가오는 토요일 — 오늘이 토요일이면 그대로
    delta_to_sat = (5 - today.weekday()) % 7
    weekend_start = today + timedelta(days=delta_to_sat)

    conn = sqlite3.connect(DB_PATH)
    # today=오늘+1일 (D-1까지), weekend=토+일
    today_events = fetch_events_for_window(conn, today, days=1, limit=10)
    weekend_events = fetch_events_for_window(conn, weekend_start, days=2, limit=10)
    today_weather = fetch_weather(conn, today)
    weekend_weather = fetch_weather(conn, weekend_start)
    season = load_season(today.month)

    prompt = build_prompt(today, weekend_start, today_weather, weekend_weather,
                          season, today_events, weekend_events)
    print(f"[ai_summary] today_evts={len(today_events)} weekend_evts={len(weekend_events)} prompt={len(prompt)}c")

    try:
        result = call_gemini(api_key, prompt)
    except Exception as exc:
        print(f"[ai_summary] FAILED: {exc}", file=sys.stderr)
        return 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "valid_for": today.isoformat(),
        "weekend_for": weekend_start.isoformat(),
        "weather": {"today": today_weather, "weekend": weekend_weather},
        **result,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ai_summary] wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
