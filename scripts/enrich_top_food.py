"""인기 맛집·카페 TOP N 의 이미지/스토리 보강 (NAVER 이미지+블로그 검색).

target: events 테이블의 food/cafe 중 image_url 또는 story_excerpt 누락된 row.
- image: NAVER 이미지 검색 (/image.json) — '{title} {gugun} 부산' query
- story: NAVER 블로그 검색 (/blog.json) — '{title} 부산 후기' query

비용: NAVER search API 일 25K 무료. top-n=50 × 2 calls = 100/일 (quota 0.4%).
idempotent: 이미 채워진 row 는 skip (COALESCE 로 기존값 보존).
budget guard: --time-budget-min (workflow timeout 와 함께 2-layer 안전망).

사고 예방:
- 5/9~5/10 catch-up 사고 (Gemini quota 6h hang) 와 같은 패턴 회피용 budget.
- naver_local 49건 100% 이미지 누락 + busan_food 35% 누락이 주 타겟.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "events.db"

NAVER_BASE = "https://openapi.naver.com/v1/search"
TAG_RE = re.compile(r"<[^>]+>")
RATE_LIMIT_S = 0.2  # NAVER 25K/일 = 약 0.3s/call 평균. 0.2s 안전.


def _strip(s: str | None, cap: int = 200) -> str:
    if not s:
        return ""
    s = html.unescape(TAG_RE.sub("", s)).strip()
    return s[:cap]


def naver_search(client_id: str, secret: str, op: str, query: str,
                 *, display: int = 1, sort: str = "sim") -> list[dict]:
    """NAVER openapi 검색 직접 호출 (api-vault 우회 — workflow 환경 단순함).

    /image.json 또는 /blog.json. 실패 시 [] 반환 (silent skip — caller 가 처리).
    """
    try:
        r = requests.get(
            f"{NAVER_BASE}/{op}.json",
            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": secret},
            params={"query": query, "display": display, "sort": sort},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"  [naver {op}] '{query[:40]}' http={r.status_code}", file=sys.stderr)
            return []
        return r.json().get("items", [])
    except (requests.RequestException, ValueError) as exc:
        print(f"  [naver {op}] '{query[:40]}' err: {exc}", file=sys.stderr)
        return []


def main(time_budget_min: int = 0, dry_run: bool = False, top_n: int = 50) -> int:
    load_dotenv()
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip('"\'')
    sec = os.environ.get("NAVER_CLIENT_SECRET", "").strip('"\'')
    if not cid or not sec:
        print("ERROR: NAVER_CLIENT_ID/SECRET 미설정", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # popularity_score 는 export_json.py 동적 계산이라 DB 컬럼 X.
    # 대안: rating DESC, naver_review_count DESC — popularity 와 강한 상관.
    # (export JSON 의 `naver_reviews` 필드는 DB 컬럼 `naver_review_count` 의 alias)
    rows = conn.execute("""
        SELECT id, source, title, address, gugun, image_url, story_excerpt
        FROM events
        WHERE category IN ('food', 'cafe')
          AND (image_url IS NULL OR image_url = ''
               OR story_excerpt IS NULL OR story_excerpt = '')
        ORDER BY COALESCE(rating, 0) DESC,
                 COALESCE(naver_review_count, 0) DESC,
                 id
        LIMIT ?
    """, (top_n,)).fetchall()
    print(f"대상: {len(rows)} food/cafe rows (image 또는 story 누락)", file=sys.stderr)

    deadline = time.monotonic() + time_budget_min * 60 if time_budget_min > 0 else None
    stats = {"image_added": 0, "story_added": 0, "no_result": 0, "budget_exit": 0}

    for i, r in enumerate(rows):
        if deadline and time.monotonic() > deadline:
            stats["budget_exit"] = len(rows) - i
            print(f"\n[budget] {time_budget_min}min 초과 — row {i}/{len(rows)} 에서 종료",
                  file=sys.stderr)
            break

        title = (r["title"] or "").strip()
        gugun = (r["gugun"] or "").strip()
        if not title:
            continue

        new_image = r["image_url"]
        new_story = r["story_excerpt"]

        # 이미지 보강 — '{title} {gugun} 부산'
        if not new_image:
            q = " ".join(p for p in [title, gugun, "부산"] if p)
            items = naver_search(cid, sec, "image", q, display=1)
            if items:
                cand = items[0].get("thumbnail") or items[0].get("link")
                if cand:
                    new_image = cand
                    stats["image_added"] += 1
            time.sleep(RATE_LIMIT_S)

        # 스토리 보강 — '{title} 부산 후기'
        if not new_story:
            items = naver_search(cid, sec, "blog", f"{title} 부산 후기", display=1)
            if items:
                desc = _strip(items[0].get("description"), cap=200)
                if desc and len(desc) >= 30:
                    new_story = desc
                    stats["story_added"] += 1
            time.sleep(RATE_LIMIT_S)

        if new_image == r["image_url"] and new_story == r["story_excerpt"]:
            stats["no_result"] += 1
            continue

        if not dry_run:
            # COALESCE 는 NULL 만 다룸 → 빈 문자열 row 는 SELECT 에 잡혀도 UPDATE no-op.
            # CASE WHEN 으로 NULL · '' 둘 다 새 값으로 교체 (idempotent: 채워진 값은 보존).
            conn.execute(
                "UPDATE events SET "
                "image_url = CASE WHEN image_url IS NULL OR image_url = '' "
                "                 THEN ? ELSE image_url END, "
                "story_excerpt = CASE WHEN story_excerpt IS NULL OR story_excerpt = '' "
                "                     THEN ? ELSE story_excerpt END "
                "WHERE id = ?",
                (new_image, new_story, r["id"]),
            )
            conn.commit()

    print("\n=== enrich 결과 ===", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--time-budget-min", type=int, default=0,
                   help="시간 예산 (분, 0=무제한). 초과 시 graceful exit.")
    p.add_argument("--dry-run", action="store_true", help="DB 업데이트 안 함")
    p.add_argument("--top-n", type=int, default=50,
                   help="처리할 row 최대 (rating/reviews 정렬 후 N건)")
    args = p.parse_args()
    sys.exit(main(
        time_budget_min=args.time_budget_min,
        dry_run=args.dry_run,
        top_n=args.top_n,
    ))
