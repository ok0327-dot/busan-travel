"""제철 정보 자동 갱신 — Gemini 2.5 Flash 기반.

seasonal.json 은 본래 수동 큐레이션(2026-04 고정)이라 신선도가 떨어진다.
당월·익월 2개월만 Gemini 로 재생성해 기존 12개월에 머지한다.
  - 당장 화면에 보이는 달만 갱신 → 비용 1콜, 환각 영향 최소.
  - 기존 큐레이션(기장 대변항·자갈치 등 지역지식)을 베이스로 제공 → 품질 보존.
  - 나머지 10개월은 그대로 유지.

출력: frontend/public/data/seasonal.json (당월·익월 overlay, 나머지 보존)
호출: GitHub Actions cron all-mode 의 '일요일만' 스텝 (주 1회) 또는 로컬 수동.
GEMINI_API_KEY 미설정 시 exit 1 — silent skip 금지(ai_summary.py 와 동일 정신).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
OUT_PATH = ROOT / "frontend" / "public" / "data" / "seasonal.json"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

_MONTH_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "foods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "where": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "blooms": {"type": "array", "items": {"type": "string"}},
        "scenes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "foods", "blooms", "scenes"],
}
SCHEMA = {
    "type": "object",
    "properties": {
        "current": _MONTH_SCHEMA,
        "next": _MONTH_SCHEMA,
    },
    "required": ["current", "next"],
}


def load_existing() -> dict:
    if not OUT_PATH.exists():
        return {"months": {}}
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"months": {}}


def month_baseline(months: dict, m: int) -> str:
    """기존 큐레이션을 LLM 베이스로 제공 — 검증된 지역지식 보존용."""
    cur = (months or {}).get(f"{m:02d}")
    if not cur:
        return "(기존 데이터 없음 — 새로 작성)"
    foods = ", ".join(
        f"{f.get('name','')}{'@' + f['where'] if f.get('where') else ''}"
        for f in (cur.get("foods") or [])
    )
    blooms = ", ".join(cur.get("blooms") or [])
    scenes = ", ".join(cur.get("scenes") or [])
    return (
        f"title: {cur.get('title','')}\n"
        f"  음식: {foods or '-'}\n"
        f"  꽃·봄빛: {blooms or '-'}\n"
        f"  풍경: {scenes or '-'}"
    )


def build_prompt(m_cur: int, m_next: int, months: dict) -> str:
    return f"""당신은 부산 토박이 제철 큐레이터입니다.
부산의 {m_cur}월(current)과 {m_next}월(next) 제철 정보를 작성하세요.

[기존 큐레이션 — 검증된 지역지식. 베이스로 삼고 보강/시의성만 다듬으세요]
■ {m_cur}월
{month_baseline(months, m_cur)}

■ {m_next}월
{month_baseline(months, m_next)}

작성 규칙:
- 위 기존 큐레이션의 검증된 지역 특산(예: 기장 대변항 멸치·미역, 자갈치 제철 회, 가덕도 대구, 송정·송도)은 유지하세요. 통째로 교체하지 말고 다듬으세요.
- foods: 4~6개. 각 항목 name 필수, 가능하면 where 에 실제 부산 지명(기장 대변항·자갈치·가덕도·태종대·송정 등) 1곳.
- blooms: 1~3개. 그 달 부산에서 실제 피는 꽃/봄·가을빛, 대표 장소를 괄호로(예: "수국 (태종대 수국길)").
- scenes: 2~3개. 그 달 가장 부산다운 풍경/명소(예: "다대포 일몰", "해운대 해맞이").
- title: 그 달 부산을 한 줄로 표현하는 서정적 카피(기존 톤 유지, 예: "한겨울 방어의 달").
- 전국 일반론 금지 — 반드시 부산 로컬. 창작 지명 금지 — 실재하는 곳만.
"""


def call_gemini(api_key: str, prompt: str) -> dict:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0},
            "temperature": 0.5,
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
        print("[seasonal] FAIL: GEMINI_API_KEY 미설정", file=sys.stderr)
        return 1

    today = date.today()
    m_cur = today.month
    m_next = (m_cur % 12) + 1

    existing = load_existing()
    months = dict(existing.get("months") or {})

    prompt = build_prompt(m_cur, m_next, months)
    print(f"[seasonal] refresh months={m_cur:02d},{m_next:02d} prompt={len(prompt)}c")

    try:
        result = call_gemini(api_key, prompt)
    except Exception as exc:
        print(f"[seasonal] FAILED: {exc}", file=sys.stderr)
        return 1

    # 당월·익월만 overlay — 나머지 10개월은 기존 큐레이션 보존.
    months[f"{m_cur:02d}"] = result["current"]
    months[f"{m_next:02d}"] = result["next"]

    out = {
        "generated_at": today.isoformat(),
        "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "refreshed_months": [f"{m_cur:02d}", f"{m_next:02d}"],
        "note": "월별 부산 제철 음식·꽃·풍경. 당월·익월은 매주 Gemini 자동 갱신, 나머지는 수동 큐레이션 베이스.",
        "months": months,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[seasonal] wrote {OUT_PATH} (months {m_cur:02d},{m_next:02d} refreshed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
