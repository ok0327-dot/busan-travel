"""Naver 블로그 리뷰 수 enrichment — food/cafe POI 대상.

Naver Search API (블로그) 호출 → "{식당명} {구군}" 검색 → total 을 리뷰 수로 DB 업데이트.

호출량 (657개 food/cafe 가정): 무료 (일 25,000 한도 내)

필요 환경변수:
  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET (기존 .env)

실행:
  python scripts/enrich_ratings.py            # 미수집 + 7일 이상 지난 것
  python scripts/enrich_ratings.py --force    # 전체 재수집
  python scripts/enrich_ratings.py --limit 10 # 10개만 (테스트)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import DB_PATH  # noqa: E402

NAVER_BLOG_SEARCH_URL = "https://openapi.naver.com/v1/search/blog"
ENRICH_STALE_DAYS = 7


def _naver_lookup(name: str, gugun: str | None, cid: str, csec: str) -> int | None:
    """Naver Blog Search → total 을 언급 수로 사용.

    쿼리 전략: 따옴표(phrase match)로 정확한 이름 매칭 + "부산" 으로 타지 동명 제외.
    따옴표 없으면 '우리돼지국밥'이 '우리 돼지 국밥'으로 토큰화돼 수십만 건이 잡힘.
    """
    query = f'"{name}" 부산'
    headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec}
    try:
        r = requests.get(
            NAVER_BLOG_SEARCH_URL,
            params={"query": query, "display": 1},
            headers=headers,
            timeout=10,
        )
        if r.status_code != 200:
            print(f"  [naver] HTTP {r.status_code}: {r.text[:120]}", file=sys.stderr)
            return None
        return r.json().get("total")
    except requests.RequestException as e:
        print(f"  [naver] err: {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="이미 enrich 된 것도 전체 재수집")
    parser.add_argument("--limit", type=int, default=0, help="N개만 처리 (테스트용)")
    args = parser.parse_args()

    load_dotenv()
    naver_id = os.getenv("NAVER_CLIENT_ID")
    naver_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not (naver_id and naver_secret):
        print("ERR: NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정", file=sys.stderr)
        return 2

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now(timezone.utc) - timedelta(days=ENRICH_STALE_DAYS)).isoformat()
    where = "category IN ('food','cafe') AND lat IS NOT NULL"
    if not args.force:
        where += f" AND (ratings_enriched_at IS NULL OR ratings_enriched_at < '{cutoff}')"

    sql = f"SELECT id, title, gugun FROM events WHERE {where} ORDER BY id"
    if args.limit:
        sql += f" LIMIT {args.limit}"

    rows = list(conn.execute(sql))
    print(f"대상 POI: {len(rows)}건")
    if not rows:
        return 0

    ok = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for i, r in enumerate(rows, 1):
        name = r["title"]
        if not name:
            continue
        total = _naver_lookup(name, r["gugun"], naver_id, naver_secret)
        if total is not None:
            conn.execute(
                "UPDATE events SET naver_review_count=?, ratings_enriched_at=? WHERE id=?",
                (total, now_iso, r["id"]),
            )
            ok += 1
        time.sleep(0.1)  # 10 RPS 보수적
        if i % 50 == 0:
            conn.commit()
            print(f"  진행 {i}/{len(rows)} · ok={ok}")

    conn.commit()
    print(f"\n완료: {len(rows)}건 중 {ok}건 수집")
    return 0


if __name__ == "__main__":
    sys.exit(main())
