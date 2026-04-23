"""KOPIS 공연예술통합전산망 — 부산(signgucode=28) 공연 목록.

data.go.kr 15097805 는 LINK 타입이라 실제 호출은 kopis.or.kr 로 가고
키도 kopis.or.kr 에서 별도 발급 → gov-api-kr 통합 키 모델과 별개.
KOPIS_API_KEY 환경변수로 읽는다.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

from config import KOPIS_BUSAN_SIGNGU, KOPIS_ENDPOINT
from storage.db import Event

SOURCE = "kopis"


def _text(el: ET.Element, tag: str) -> str | None:
    node = el.find(tag)
    if node is None or node.text is None:
        return None
    val = node.text.strip()
    return val or None


def _parse_db(db: ET.Element) -> Event:
    return Event(
        source=SOURCE,
        source_id=_text(db, "mt20id") or "",
        category="performance",
        title=_text(db, "prfnm") or "",
        start_date=_text(db, "prfpdfrom"),
        end_date=_text(db, "prfpdto"),
        venue=_text(db, "fcltynm"),
        url=None,
        image_url=_text(db, "poster"),
        description=_text(db, "genrenm"),
        raw={c.tag: c.text for c in db},
    )


def fetch(days_ahead: int = 180, rows: int = 100, max_pages: int = 5) -> list[Event]:
    key = os.environ.get("KOPIS_API_KEY")
    if not key:
        print(f"[{SOURCE}] SKIP: KOPIS_API_KEY 미설정 (kopis.or.kr 에서 별도 발급 필요)",
              file=sys.stderr)
        return []

    today = date.today()
    events: list[Event] = []
    params_base = {
        "service": key,
        "stdate": today.strftime("%Y%m%d"),
        "eddate": (today + timedelta(days=days_ahead)).strftime("%Y%m%d"),
        "rows": rows,
        "signgucode": KOPIS_BUSAN_SIGNGU,
    }
    for page in range(1, max_pages + 1):
        r = requests.get(KOPIS_ENDPOINT, params={**params_base, "cpage": page}, timeout=20)
        if not r.ok:
            print(f"[{SOURCE}] HTTP {r.status_code}: {r.text[:120]}", file=sys.stderr)
            break
        root = ET.fromstring(r.content)
        dbs = root.findall(".//db")
        if not dbs:
            break
        events.extend(_parse_db(db) for db in dbs)
        if len(dbs) < rows:
            break
    return events
