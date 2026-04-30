"""Info flow 정합성 회귀 테스트 (audit 2026-04-25 P0/P1).

검사 항목 / Checks:
- P1-2: lint_overrides 통과 (어댑터별 apply_override 호출 cover)
- P0-2: main.py 에서 filter_events() 호출 잔존
- P1-1: NEGATIVE_KEYWORDS 단일소스 (export_json import 일관)
- P1-4: 최근 30일 RSS 글 좌표 해소율 ≥ 50%
- P1-7: places.json count sanity (silent overwrite 검출)
- 일반: lodging 폐기 결정(P0-3) 잔재 — DB 에 lodging row 0건 유지

CI 통합 가정 — exit 1 on violations.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "events.db"
PLACES_JSON = ROOT / "frontend" / "public" / "data" / "places.json"


def check_overrides_lint() -> list[str]:
    r = subprocess.run(
        [sys.executable, "scripts/lint_overrides.py"],
        capture_output=True, text=True, cwd=ROOT,
    )
    return [] if r.returncode == 0 else [f"override lint 실패:\n{r.stderr.strip()}"]


def check_filter_events_called() -> list[str]:
    main_py = (ROOT / "main.py").read_text(encoding="utf-8")
    return [] if "filter_events" in main_py else ["main.py 에서 filter_events() 호출 누락 (P0-2 회귀)"]


def check_negative_keywords_unified() -> list[str]:
    export_py = (ROOT / "scripts" / "export_json.py").read_text(encoding="utf-8")
    if "NEGATIVE_KEYWORDS as TOUR_NEGATIVE_KEYWORDS" not in export_py:
        return ["export_json.py 가 _tour_filter.NEGATIVE_KEYWORDS 를 import 하지 않음 (P1-1 회귀)"]
    return []


def check_blog_geocoded(conn: sqlite3.Connection) -> list[str]:
    total = conn.execute(
        "SELECT COUNT(*) FROM events WHERE source LIKE 'naver_blog%' "
        "AND first_seen > datetime('now', '-30 days')"
    ).fetchone()[0]
    if total == 0:
        return []
    geo = conn.execute(
        "SELECT COUNT(*) FROM events WHERE source LIKE 'naver_blog%' "
        "AND first_seen > datetime('now', '-30 days') AND lat IS NOT NULL"
    ).fetchone()[0]
    rate = geo / total
    if rate < 0.5:
        return [
            f"최근 30일 RSS 좌표 해소율 {rate:.0%} ({geo}/{total}) < 50% — "
            "geocode_blogs cron 또는 KAKAO_REST_KEY 점검 (P1-4)"
        ]
    return []


def check_lodging_purged(conn: sqlite3.Connection) -> list[str]:
    cnt = conn.execute("SELECT COUNT(*) FROM events WHERE category='lodging'").fetchone()[0]
    return [] if cnt == 0 else [f"lodging row {cnt}건 — P0-3 폐기 결정 잔재 정정 필요"]


def check_places_sanity() -> list[str]:
    if not PLACES_JSON.exists():
        return []
    p = json.loads(PLACES_JSON.read_text(encoding="utf-8"))
    if p.get("count", 0) < 200:
        return [f"places.json count {p.get('count')} < 200 — silent overwrite 의심 (P0-1/P1-7)"]
    return []


def main() -> int:
    errors: list[str] = []
    errors += check_overrides_lint()
    errors += check_filter_events_called()
    errors += check_negative_keywords_unified()
    errors += check_places_sanity()

    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        errors += check_blog_geocoded(conn)
        errors += check_lodging_purged(conn)
        conn.close()
    else:
        print("[verify] DB 미존재 — DB 의존 검사 skip (CI 첫 실행)", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"❌ {e}", file=sys.stderr)
        print(f"\n{len(errors)}건 위반", file=sys.stderr)
        return 1
    print("✅ verify_info_flow OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
