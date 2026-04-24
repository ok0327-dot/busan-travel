"""Phase 4 검증: 지오코딩된 72건이 실제 포스트 문맥과 일치하는지 재확인.

각 포스트에서:
  1. 제목/본문에서 명시된 구/동 힌트 추출
  2. Kakao keywordSearch 로 후보 5건 조회
  3. 후보 주소의 부산 구/동 vs 포스트 힌트 매칭
  4. 현재 DB 좌표 대비 최적 후보 비교
  5. 불일치 / 개선 여지 있는 건 report.json 에 기록

문맥 매칭 로직:
- 포스트가 구/동을 명시 → 해당 구/동 내 후보 우선
- 없으면 Kakao 기본 첫 결과 유지
- 여러 후보 중 place_name 유사도 + 구 일치도로 스코어링
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from config import DB_PATH

KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
BUSAN_GU = [
    "중구", "동구", "서구", "영도구", "부산진구", "동래구", "남구", "북구",
    "해운대구", "사하구", "금정구", "강서구", "연제구", "수영구", "사상구", "기장군",
]
BUSAN_SPECIFIC_DONG = {
    # 동/지명 → 구 매핑 (blog 포스트에 자주 등장하는 것 위주)
    "보수동": "중구", "중앙공원": "중구", "광복로": "중구", "용두산": "중구", "남포": "중구",
    "자갈치": "중구", "영주동": "중구", "대청로": "중구",
    "해운대": "해운대구", "송정": "해운대구", "청사포": "해운대구", "미포": "해운대구",
    "동백섬": "해운대구", "달맞이길": "해운대구", "센텀": "해운대구", "센텀시티": "해운대구",
    "반여": "해운대구", "반송": "해운대구", "좌동": "해운대구", "우동": "해운대구",
    "광안": "수영구", "광안리": "수영구", "민락": "수영구", "망미": "수영구", "F1963": "수영구",
    "영도": "영도구", "흰여울": "영도구", "태종대": "영도구", "봉래동": "영도구", "동삼동": "영도구",
    "다대포": "사하구", "하단": "사하구", "감천": "사하구", "홍티": "사하구",
    "사상": "사상구",
    "기장": "기장군", "철마": "기장군",
    "부산진": "부산진구", "서면": "부산진구", "전포": "부산진구", "부전": "부산진구",
    "범일": "동구", "초량": "동구", "수정동": "동구", "부산역": "동구", "북항": "동구",
    "화명": "북구", "덕천": "북구", "만덕": "북구", "금곡": "북구",
    "금정": "금정구", "범어사": "금정구", "온천동": "동래구",
    "감만": "남구", "대연": "남구", "용호동": "남구", "유엔기념공원": "남구",
    "낙동강": "강서구", "명지": "강서구", "가덕도": "강서구",
    "연제": "연제구",
}


def _post_gu_hint(title: str, desc: str) -> str | None:
    """포스트 텍스트에서 명시된 부산 구 추출. 없으면 None."""
    text = f"{title} {desc}"
    for gu in BUSAN_GU:
        if gu in text:
            return gu
    # 특정 지명을 통해 추정
    for key, gu in BUSAN_SPECIFIC_DONG.items():
        if key in text:
            return gu
    return None


def _extract_gu_from_address(address: str) -> str | None:
    for gu in BUSAN_GU:
        if gu in address:
            return gu
    return None


def kakao_candidates(key: str, query: str) -> list[dict]:
    try:
        r = requests.get(
            KAKAO_URL,
            headers={"Authorization": f"KakaoAK {key}"},
            params={"query": query, "size": 10},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("documents", [])
    except (requests.HTTPError, requests.Timeout, ValueError):
        return []


def pick_best(candidates: list[dict], expected_gu: str | None) -> dict | None:
    """후보 중 (a) 부산 내 + (b) 예상 구 일치하는 것 우선."""
    in_busan = [c for c in candidates if "부산" in (c.get("address_name") or c.get("road_address_name") or "")]
    if not in_busan:
        return None
    if expected_gu:
        matching = [c for c in in_busan if expected_gu in (c.get("address_name") or "") or expected_gu in (c.get("road_address_name") or "")]
        if matching:
            return matching[0]
    return in_busan[0]


def main():
    load_dotenv()
    kakao_key = os.environ.get("KAKAO_REST_KEY", "").strip('"\'')
    if not kakao_key:
        print("ERROR: KAKAO_REST_KEY 미설정", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH if isinstance(DB_PATH, Path) else Path(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, source, title, description, lat, lon, tags_json
        FROM events
        WHERE source LIKE 'naver_blog%' AND lat IS NOT NULL
        ORDER BY id
    """).fetchall()

    report = {"ok": [], "mismatch": [], "no_candidate": []}

    for i, r in enumerate(rows):
        tj = json.loads(r["tags_json"]) if r["tags_json"] else {}
        place = tj.get("place_name")
        if not place:
            continue
        title = r["title"] or ""
        desc = r["description"] or ""
        expected_gu = _post_gu_hint(title, desc)
        current = {"lat": r["lat"], "lon": r["lon"]}

        # Kakao 재조회: 첫째 raw place_name, 둘째 부산 prefix
        cands = kakao_candidates(kakao_key, place)
        time.sleep(0.12)
        if not cands:
            cands = kakao_candidates(kakao_key, f"부산 {place}")
            time.sleep(0.12)

        best = pick_best(cands, expected_gu)
        if not best:
            report["no_candidate"].append({
                "id": r["id"], "title": title[:60], "place": place,
                "expected_gu": expected_gu,
            })
            continue

        best_lat = float(best["y"])
        best_lon = float(best["x"])
        best_addr = best.get("address_name") or best.get("road_address_name") or ""
        best_gu = _extract_gu_from_address(best_addr)

        # 현재 좌표 vs best 좌표 거리
        d_deg = ((current["lat"] - best_lat) ** 2 + (current["lon"] - best_lon) ** 2) ** 0.5
        d_km = d_deg * 111  # 위도 1deg ≈ 111km

        entry = {
            "id": r["id"], "title": title[:60], "place": place,
            "expected_gu": expected_gu, "best_gu": best_gu,
            "current": current, "best": {"lat": best_lat, "lon": best_lon, "address": best_addr, "name": best.get("place_name")},
            "km_diff": round(d_km, 3),
            "cands_top3": [
                {"name": c.get("place_name"), "addr": c.get("address_name") or c.get("road_address_name")}
                for c in cands[:3]
            ],
        }
        # 판정
        issue = None
        if expected_gu and best_gu != expected_gu:
            issue = f"구 불일치: 예상 {expected_gu} vs 실제 {best_gu}"
        elif d_km > 2.0:
            issue = f"현재-best 거리 {d_km:.2f} km"
        if issue:
            entry["issue"] = issue
            report["mismatch"].append(entry)
        else:
            report["ok"].append({"id": r["id"], "place": place, "gu": best_gu})

        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(rows)} 검증 중...", file=sys.stderr)

    # 리포트 저장
    out_path = Path("/tmp/validation_report.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== 결과 ===")
    print(f"  OK:           {len(report['ok'])}")
    print(f"  불일치:        {len(report['mismatch'])}")
    print(f"  후보 없음:     {len(report['no_candidate'])}")
    print(f"\n상세: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
