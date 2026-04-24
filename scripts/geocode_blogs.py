"""Phase 4: 네이버 블로그 포스트 지오코딩 (Gemini + Kakao Places).

공식 부산 블로그 RSS 185 건(cooolbusan/bscf2009/hudpr) 에서 장소명을 추출해
지도 마커로 뜨게 한다.

파이프라인 / Pipeline:
  1) DB 에서 source LIKE 'naver_blog%' AND lat IS NULL 로드
  2) Gemini 2.5 Flash 로 제목+본문 → {place_name, confidence, reason} 구조화 추출
     - 행정 공지/건강정보는 null 반환 → 건너뜀
     - confidence < 0.6 은 버림
  3) Kakao Places keywordSearch 로 place_name → (lat, lon)
     - 부산 bbox 필터 (34.9~35.5, 128.7~129.4)
  4) DB UPDATE events SET lat/lon/geocoded_at WHERE id=?

비용 / Cost:
  - Gemini 2.5 Flash (AI Studio 무료 티어): 1,500 req/day, 15 RPM, 1M tok/min
  - Kakao Places REST: 일 10만 호출 무료
  - 185건 전체 실행: $0

필요 환경변수:
  - GEMINI_API_KEY (AI Studio 발급, AI... 로 시작)
  - KAKAO_REST_KEY (Kakao Developers REST 키, JS 키와 별개)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from config import DB_PATH

BUSAN_BBOX = (34.9, 35.5, 128.7, 129.4)  # lat_min, lat_max, lon_min, lon_max
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
KAKAO_PLACES_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
RATE_LIMIT_S = 6.5  # 2.5 Flash 무료: 10 RPM 한도 기준 안전 마진 (실제 9.2 req/min)
CONFIDENCE_THRESHOLD = 0.6

EXTRACT_PROMPT = """다음 네이버 블로그 포스트에서 **부산 내 방문 가능한 구체적 장소(관광지/맛집/카페/공원/축제장소)** 하나만 추출해줘.

판단 기준:
- 관광 가치 있는 구체적 장소명만 (예: "해운대 모래축제" → "해운대해수욕장", "광안리 카페거리" → "광안리해수욕장")
- 행정 공지 (예: "반송보건지소 방사선 촬영 중단") → null
- 건강/복지 정보 (예: "봄 알레르기 예방법") → null
- 일반 시정 소식 (예: "하하캠퍼스 이용 가이드") → null, 단 구체 장소 언급 시 그 장소
- 모호한 일반 명사 (예: "부산 시내") → null

출력은 반드시 아래 JSON 스키마로:
{"place_name": string|null, "confidence": 0.0~1.0, "reason": string}

예시:
입력: "2026 해운대 모래축제 개최 안내"
출력: {"place_name": "해운대해수욕장", "confidence": 0.95, "reason": "모래축제는 해수욕장에서 개최"}

입력: "반송보건지소 방사선 촬영 일시중단"
출력: {"place_name": null, "confidence": 1.0, "reason": "보건소 행정 공지, 관광 장소 아님"}

포스트:
제목: {title}
본문: {description}
"""


# ─────────── Gemini 추출 ───────────


class Gemini:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.last_t = 0.0

    def extract_place(self, title: str, description: str | None) -> dict:
        now = time.monotonic()
        dt = now - self.last_t
        if dt < RATE_LIMIT_S:
            time.sleep(RATE_LIMIT_S - dt)
        self.last_t = time.monotonic()

        prompt = EXTRACT_PROMPT.replace("{title}", title).replace(
            "{description}", (description or "")[:500]
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 256,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "place_name": {"type": "STRING", "nullable": True},
                        "confidence": {"type": "NUMBER"},
                        "reason": {"type": "STRING"},
                    },
                    "required": ["confidence", "reason"],
                },
                # 2.5 Flash thinking 비활성화 — 단순 추출 태스크, 토큰 절약
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        for attempt in range(5):
            try:
                r = requests.post(
                    GEMINI_URL,
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=30,
                )
                if r.status_code == 429:
                    # Google 은 response body 에 "Please retry in Xs" 힌트를 담음
                    try:
                        msg = r.json().get("error", {}).get("message", "")
                        import re as _re
                        m = _re.search(r"retry in ([\d.]+)", msg)
                        wait_s = min(90, float(m.group(1)) + 2) if m else 20 * (attempt + 1)
                    except (ValueError, AttributeError):
                        wait_s = 20 * (attempt + 1)
                    print(f"  [gemini 429] wait {wait_s:.0f}s (attempt {attempt+1}/5)", file=sys.stderr)
                    time.sleep(wait_s)
                    continue
                r.raise_for_status()
                data = r.json()
                cand = data["candidates"][0]
                finish = cand.get("finishReason")
                parts = cand.get("content", {}).get("parts")
                if not parts:
                    return {"place_name": None, "confidence": 0.0, "reason": f"no-parts({finish})"}
                return json.loads(parts[0]["text"])
            except (requests.HTTPError, requests.Timeout, KeyError, ValueError) as exc:
                if attempt == 4:
                    print(f"  [gemini] FAILED: {exc}", file=sys.stderr)
                    return {"place_name": None, "confidence": 0.0, "reason": f"error: {exc}"}
                time.sleep(5)
        return {"place_name": None, "confidence": 0.0, "reason": "unreachable"}


# ─────────── Kakao Places 지오코딩 ───────────


def kakao_search(rest_key: str, query: str) -> tuple[float | None, float | None]:
    """Kakao keywordSearch 로 장소명 → (lat, lon). 부산 bbox 밖은 None."""
    try:
        r = requests.get(
            KAKAO_PLACES_URL,
            headers={"Authorization": f"KakaoAK {rest_key}"},
            params={"query": query, "size": 5},
            timeout=15,
        )
        r.raise_for_status()
        docs = r.json().get("documents", [])
    except (requests.HTTPError, requests.Timeout, ValueError) as exc:
        print(f"  [kakao] {query}: {exc}", file=sys.stderr)
        return None, None

    # 부산 bbox 안의 첫 결과 채택
    for doc in docs:
        try:
            lat = float(doc["y"])
            lon = float(doc["x"])
        except (KeyError, ValueError):
            continue
        if BUSAN_BBOX[0] <= lat <= BUSAN_BBOX[1] and BUSAN_BBOX[2] <= lon <= BUSAN_BBOX[3]:
            return lat, lon
    return None, None


# ─────────── 메인 ───────────


def main(limit: int = 0, dry_run: bool = False):
    load_dotenv()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip('"\'')
    kakao_key = os.environ.get("KAKAO_REST_KEY", "").strip('"\'')
    if not gemini_key:
        print("ERROR: GEMINI_API_KEY 미설정. .env 확인.", file=sys.stderr)
        return 1
    kakao_available = bool(kakao_key)
    if not kakao_available:
        print("WARNING: KAKAO_REST_KEY 미설정 → 장소명만 추출, 좌표 해소는 건너뜀.", file=sys.stderr)
    gemini = Gemini(gemini_key)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # extraction 결과 캐시: tags_json 컬럼 재활용 (기존에 비어있음)
    rows = conn.execute(
        "SELECT id, source, title, description, tags_json FROM events "
        "WHERE source LIKE 'naver_blog%' AND lat IS NULL "
        "ORDER BY id"
    ).fetchall()
    if limit:
        rows = rows[:limit]
    print(f"대상: {len(rows)} 포스트", file=sys.stderr)

    stats = {"extracted": 0, "skipped_low_conf": 0, "skipped_no_place": 0, "geocoded": 0, "oob": 0, "awaiting_kakao": 0}
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for i, r in enumerate(rows):
        # 캐시 체크: 이미 Gemini 돌렸으면 재추출 건너뜀 (tags_json 에 저장)
        cached = None
        if r["tags_json"]:
            try:
                c = json.loads(r["tags_json"])
                if isinstance(c, dict) and "place_name" in c:
                    cached = c
            except (ValueError, TypeError):
                pass

        # 캐시는 성공 결과만 (error/unreachable reason 은 재시도)
        is_valid_cache = cached and not str(cached.get("reason", "")).startswith(("error", "unreachable", "no-parts"))
        if is_valid_cache:
            result = cached
        else:
            result = gemini.extract_place(r["title"] or "", r["description"])
            stats["extracted"] += 1
            # 성공 응답만 캐시 (재시도 가능하도록)
            reason = str(result.get("reason", ""))
            if not dry_run and not reason.startswith(("error", "unreachable", "no-parts")):
                conn.execute(
                    "UPDATE events SET tags_json=? WHERE id=?",
                    (json.dumps(result, ensure_ascii=False), r["id"]),
                )
                conn.commit()

        place = result.get("place_name")
        conf = result.get("confidence", 0.0)
        if not place:
            stats["skipped_no_place"] += 1
            print(f"  [{i+1:3d}/{len(rows)}] SKIP(no-place): {r['title'][:50]}", file=sys.stderr)
            continue
        if conf < CONFIDENCE_THRESHOLD:
            stats["skipped_low_conf"] += 1
            print(f"  [{i+1:3d}/{len(rows)}] SKIP(conf={conf:.2f}): {place} ← {r['title'][:40]}", file=sys.stderr)
            continue

        if not kakao_available:
            stats["awaiting_kakao"] += 1
            print(f"  [{i+1:3d}/{len(rows)}] {place} (Kakao 스킵)", file=sys.stderr)
            continue

        lat, lon = kakao_search(kakao_key, place)
        time.sleep(0.15)  # Kakao 정중 rate limit
        if lat is None:
            stats["oob"] += 1
            print(f"  [{i+1:3d}/{len(rows)}] OOB/miss: {place}", file=sys.stderr)
            continue

        stats["geocoded"] += 1
        print(f"  [{i+1:3d}/{len(rows)}] ✓ {place} → ({lat:.5f}, {lon:.5f}) — {r['title'][:40]}", file=sys.stderr)
        if not dry_run:
            conn.execute(
                "UPDATE events SET lat=?, lon=?, geocoded_at=? WHERE id=?",
                (lat, lon, now_iso, r["id"]),
            )
            conn.commit()

    print("\n=== 결과 ===", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="샘플링 (0=전체)")
    p.add_argument("--dry-run", action="store_true", help="DB 업데이트 안 함")
    args = p.parse_args()
    sys.exit(main(limit=args.limit, dry_run=args.dry_run))
