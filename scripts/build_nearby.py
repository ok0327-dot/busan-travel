#!/usr/bin/env python3
"""부산 근교(경남·경주) 축제 → frontend/public/data/nearby-festivals.json.

부산 이벤트 파이프라인(main.py/export_json.py)과 독립적으로 실행된다.
collect.yml 에서 export_json 뒤 한 스텝으로 호출하면, 기존 data/ 커밋 스텝이
자동으로 nearby-festivals.json 을 함께 커밋한다.

Standalone from the Busan events pipeline — call it after export_json in
collect.yml; the existing "commit data/" step picks the JSON up automatically.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from sources import nearby_festival  # noqa: E402

OUT = ROOT / "frontend" / "public" / "data" / "nearby-festivals.json"


def main() -> int:
    load_dotenv()
    festivals = nearby_festival.fetch()
    n_est = sum(1 for f in festivals if f.get("estimated"))
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "count": len(festivals),
        "confirmed_count": len(festivals) - n_est,
        "estimated_count": n_est,
        "regions": ["경남", "울산", "경주"],
        "festivals": festivals,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    by_region: dict[str, int] = {}
    for f in festivals:
        by_region[f["region"]] = by_region.get(f["region"], 0) + 1
    print(f"[build_nearby] {len(festivals)}건(확정 {len(festivals)-n_est}·추정 {n_est}) "
          f"→ {OUT.relative_to(ROOT)} · {by_region}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
