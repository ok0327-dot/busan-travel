"""Step 5.2a — 부산 관광 사진 source 썸네일 수집.

수집 대상:
- KTO Photo Korea (phoko.visitkorea.or.kr): 부산 4,181건 (allRegnCd=23)
- 부산관광아카이브 (archive.visitbusan.net): 1유형 ~10,680건 (실측)

저장:
- data/source_thumbs/{source}/{...}/{id}_{title}.jpg  — 시각 큐레이션 baseline
- data/sources.db (SQLite)                            — 메타 (큐레이션 후 R2 업로드용)

실행:
    python scripts/sources/fetch_thumbnails.py                    # 풀 실행 (~3시간)
    python scripts/sources/fetch_thumbnails.py --source kto       # KTO 만
    python scripts/sources/fetch_thumbnails.py --source archive   # archive 만
    python scripts/sources/fetch_thumbnails.py --limit-pages 2    # 작은 dry-run

Rate limit: KTO ≤ 2 RPS / archive ≤ 1 RPS (sources/image-sources.md 정책).
재실행 시 UNIQUE(source, source_id) 로 중복 skip — 중간 멈춤 후 재개 가능.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent.parent
THUMB_DIR = ROOT / "data" / "source_thumbs"
DB_PATH = ROOT / "data" / "sources.db"

UA = "busan-travel-archive-collector/1.0 (+https://busan-travel.dk0327.workers.dev)"
HEADERS = {"User-Agent": UA}

KTO_BASE = "https://phoko.visitkorea.or.kr"
KTO_LIST_URL = f"{KTO_BASE}/media/mediaList.kto"  # search_count 추출 (1회)
KTO_AJAX_URL = f"{KTO_BASE}/media/mediaList_ajax.kto"  # 페이지네이션 (POST)
KTO_CDN = "https://conlab.visitkorea.or.kr"
KTO_REGN_BUSAN = "23"
KTO_PER_PAGE = 35  # AJAX response 의 실제 page size (lastRecordIndex 무시되는 듯)
KTO_RPS = 2.0  # ≤ 2 RPS
KTO_SLEEP = 1.0 / KTO_RPS  # 0.5s
KTO_AJAX_HEADERS = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{KTO_LIST_URL}?allRegnCd={KTO_REGN_BUSAN}",
}

ARCHIVE_BASE = "https://archive.visitbusan.net"
ARCHIVE_LIST_URL = f"{ARCHIVE_BASE}/dataSearch/list.nm"
ARCHIVE_THUMB_BASE = "https://archive.visitbusan.net"  # /upload/... 는 archive 호스트 path. www.visitbusan.net 은 동일 path 에 200+HTML 에러를 반환해 silent fail.
ARCHIVE_RPS = 1.0
ARCHIVE_SLEEP = 1.0 / ARCHIVE_RPS  # 1.0s

UUID_RE = re.compile(r"download-image/([0-9a-f-]{36})")
DATASID_RE = re.compile(r"dataSid=(METADATA\d+)")
FN_PAGE_RE = re.compile(r"fn_page\('(\d+)'\)")
KTO_TOTAL_RE = re.compile(r'class="[^"]*search_count[^"]*">([0-9,]+)</span>')
ARCHIVE_PER_PAGE = 60

# ───────────────────── DB ─────────────────────


def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT,
            category_l1 TEXT,
            category_l2 TEXT,
            category_l3 TEXT,
            gugun TEXT,
            attribution TEXT,
            thumb_path TEXT,
            thumb_url TEXT,
            original_url TEXT,
            license_type TEXT DEFAULT 'kogl-1',
            archived_at TEXT,
            UNIQUE(source, source_id)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_photos_cat ON photos(category_l1, category_l2)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_photos_source ON photos(source)")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS fetch_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            source_id TEXT,
            stage TEXT,
            url TEXT,
            error TEXT,
            tried_at TEXT
        )
        """
    )
    con.commit()
    return con


def already_fetched(con: sqlite3.Connection, source: str, source_id: str) -> bool:
    cur = con.execute(
        "SELECT 1 FROM photos WHERE source=? AND source_id=? AND thumb_path IS NOT NULL",
        (source, source_id),
    )
    return cur.fetchone() is not None


def record_photo(con: sqlite3.Connection, **fields):
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    update = ", ".join(f"{k}=excluded.{k}" for k in fields if k not in ("source", "source_id"))
    con.execute(
        f"INSERT INTO photos ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(source, source_id) DO UPDATE SET {update}",
        tuple(fields.values()),
    )
    con.commit()


def record_failure(con: sqlite3.Connection, source: str, source_id: str, stage: str, url: str, error: str):
    con.execute(
        "INSERT INTO fetch_failures (source, source_id, stage, url, error, tried_at) "
        "VALUES (?,?,?,?,?,?)",
        (source, source_id, stage, url, error, datetime.now(timezone.utc).isoformat()),
    )
    con.commit()


# ───────────────────── 공통 ─────────────────────


def safe_filename(text: str, maxlen: int = 40) -> str:
    """파일명 안전화 — 한글 그대로, 슬래시/콜론/공백 등 _ 로 치환"""
    s = re.sub(r'[/\\:*?"<>|]', "_", text or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s[:maxlen] or "untitled"


def download_image(url: str, dest: Path, session: requests.Session) -> tuple[bool, str]:
    try:
        r = session.get(url, headers=HEADERS, timeout=30, stream=True)
        r.raise_for_status()
        ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not ct.startswith("image/"):
            # 일부 origin 은 200+HTML 에러를 반환 (www.visitbusan.net silent fail 케이스 등). magic byte 도 함께 거부.
            return False, f"non-image content-type: {ct!r}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        first = b""
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                if not first:
                    first = chunk[:8]
                f.write(chunk)
        # JPEG/PNG/GIF/WebP magic byte 검증
        if not (first.startswith(b"\xff\xd8\xff") or first.startswith(b"\x89PNG") or first[:6] in (b"GIF87a", b"GIF89a") or (first[:4] == b"RIFF" and len(first) >= 8)):
            try:
                dest.unlink()
            except FileNotFoundError:
                pass
            return False, f"bad magic byte: {first!r}"
        return True, ""
    except Exception as e:
        return False, str(e)


# ───────────────────── KTO ─────────────────────


def parse_kto_list_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen_uuids = set()
    for img in soup.select("img"):
        src = img.get("src") or ""
        m = UUID_RE.search(src)
        if not m:
            continue
        uuid = m.group(1)
        if uuid in seen_uuids:
            continue
        seen_uuids.add(uuid)
        title = (img.get("alt") or "").strip()
        items.append(
            {
                "uuid": uuid,
                "title": title,
                "thumb_url": src,  # it11 (썸네일)
                "original_url": f"{KTO_CDN}/api/depot/public/depot-flow/query/download-image/{uuid}/it22",
            }
        )
    return items


def parse_kto_total_count(html: str) -> int | None:
    """첫 페이지 raw HTML 에서 '<span class=search_count>4,181</span>' 추출."""
    m = KTO_TOTAL_RE.search(html)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def fetch_kto_ajax(session: requests.Session, first: int) -> str:
    """POST /media/mediaList_ajax.kto — 페이지네이션 AJAX endpoint."""
    r = session.post(
        KTO_AJAX_URL,
        data={
            "allRegnCd": KTO_REGN_BUSAN,
            "firstRecordIndex": str(first),
            "lastRecordIndex": str(first + KTO_PER_PAGE - 1),
            "sortingField": "",
            "searchGbn": "",
            "photoCd": "",
            "keyword": "",
        },
        headers=KTO_AJAX_HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return r.text


def run_kto(con: sqlite3.Connection, session: requests.Session, *, limit_pages: int | None = None) -> tuple[int, int]:
    """KTO 부산 콘텐츠 수집 — AJAX endpoint + firstRecordIndex 35씩 증분."""
    print(f"[kto] start — busan (allRegnCd={KTO_REGN_BUSAN})")
    fetched = 0
    skipped = 0
    # 1) 첫 GET 페이지로 total count 추출
    try:
        r = session.get(f"{KTO_LIST_URL}?allRegnCd={KTO_REGN_BUSAN}", headers=HEADERS, timeout=15)
        r.raise_for_status()
        total = parse_kto_total_count(r.text)
    except Exception as e:
        print(f"[kto] initial GET fail: {e}")
        return 0, 0
    if total is None:
        print("[kto] WARNING — total count 추출 실패. fallback total=5000")
        total = 5000
    last_page = (total + KTO_PER_PAGE - 1) // KTO_PER_PAGE
    if limit_pages is not None:
        last_page = min(last_page, limit_pages)
    print(f"[kto] total={total} → last_page={last_page} (per_page={KTO_PER_PAGE})")
    # 2) AJAX 페이지네이션 — 안전망: 이전 page UUID set 과 동일하면 stop
    prev_uuids: set[str] = set()
    for page in range(1, last_page + 1):
        first = (page - 1) * KTO_PER_PAGE
        try:
            html = fetch_kto_ajax(session, first)
        except Exception as e:
            print(f"[kto] page {page} (first={first}) ajax fail: {e}")
            record_failure(con, "kto", f"ajax-{first}", "list", KTO_AJAX_URL, str(e))
            time.sleep(KTO_SLEEP)
            continue
        items = parse_kto_list_page(html)
        if not items:
            print(f"[kto] page {page} (first={first}) empty — stop")
            break
        cur_uuids = {item["uuid"] for item in items}
        if prev_uuids and cur_uuids == prev_uuids:
            print(f"[kto] page {page} same UUID set as prev — stop (page over)")
            break
        prev_uuids = cur_uuids
        for item in items:
            if already_fetched(con, "kto", item["uuid"]):
                skipped += 1
                continue
            title_safe = safe_filename(item["title"] or item["uuid"][:8])
            dest = THUMB_DIR / "kto" / f"{item['uuid'][:8]}_{title_safe}.jpg"
            ok, err = download_image(item["thumb_url"], dest, session)
            if not ok:
                record_failure(con, "kto", item["uuid"], "thumb", item["thumb_url"], err)
                continue
            record_photo(
                con,
                source="kto",
                source_id=item["uuid"],
                title=item["title"],
                category_l1=None,
                category_l2=None,
                category_l3=None,
                gugun="부산광역시",
                attribution="©한국관광공사 포토코리아",
                thumb_path=str(dest.relative_to(ROOT)),
                thumb_url=item["thumb_url"],
                original_url=item["original_url"],
                license_type="kogl-1",
                archived_at=datetime.now(timezone.utc).isoformat(),
            )
            fetched += 1
            time.sleep(KTO_SLEEP)
        if page % 10 == 0 or page == 1:
            print(f"[kto] page {page}/{last_page} done (first={first}) — got {len(items)} / fetched={fetched} skipped={skipped}")
    return fetched, skipped


# ───────────────────── archive ─────────────────────


def parse_archive_list_page(html: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    last_page = None
    fn_pages = FN_PAGE_RE.findall(html)
    if fn_pages:
        last_page = max(int(x) for x in fn_pages)
    for a in soup.select("a[href*='dataSid']"):
        href = a.get("href", "")
        m = DATASID_RE.search(href)
        if not m:
            continue
        sid = m.group(1)
        card = a.find_parent(["li", "div", "article"])
        if not card:
            continue
        text = card.get_text(strip=True, separator="|")
        parts = [p.strip() for p in text.split("|") if p.strip()]
        l1 = parts[0] if len(parts) > 0 else ""
        l2 = parts[1] if len(parts) > 1 else ""
        title = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "")
        img = card.select_one("img")
        thumb_url = img.get("src") if img else ""
        if thumb_url and thumb_url.startswith("/"):
            thumb_url = urljoin(ARCHIVE_THUMB_BASE, thumb_url)
        items.append(
            {
                "sid": sid,
                "title": title,
                "category_l1": l1,
                "category_l2": l2,
                "thumb_url": thumb_url,
                "detail_url": urljoin(ARCHIVE_BASE, href),
            }
        )
    # dedup by sid (카드 중복 방지)
    seen = set()
    unique = []
    for item in items:
        if item["sid"] in seen:
            continue
        seen.add(item["sid"])
        unique.append(item)
    return unique, last_page


def fetch_archive_list_page(session: requests.Session, page: int, license_type: int = 1) -> requests.Response:
    data = {
        "menuCd": "34",
        "dataCdList": "202",
        "copyrightLicenseList": str(license_type),
        "perPageNum": "60",
        "page": str(page),
    }
    r = session.post(ARCHIVE_LIST_URL, data=data, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r


def run_archive(con: sqlite3.Connection, session: requests.Session, *, limit_pages: int | None = None) -> tuple[int, int]:
    print(f"[archive] start — kogl=1")
    fetched = 0
    skipped = 0
    # 첫 page 로 last_page 식별
    try:
        r = fetch_archive_list_page(session, 1, 1)
    except Exception as e:
        print(f"[archive] initial fetch fail: {e}")
        return 0, 0
    items, last_page = parse_archive_list_page(r.text)
    if last_page is None:
        print("[archive] WARNING — last_page detect 실패. 단일 페이지만 처리")
        last_page = 1
    print(f"[archive] last_page={last_page}, page1 items={len(items)}")
    if limit_pages:
        last_page = min(last_page, limit_pages)
    # page 1 처리 (이미 받음)
    fetched_p1, skipped_p1 = _archive_persist_items(con, session, items)
    fetched += fetched_p1
    skipped += skipped_p1
    # page 2 ~ last_page
    for page in range(2, last_page + 1):
        try:
            r = fetch_archive_list_page(session, page, 1)
        except Exception as e:
            print(f"[archive] page {page} list fail: {e}")
            record_failure(con, "archive", f"list-page-{page}", "list", ARCHIVE_LIST_URL, str(e))
            continue
        items, _ = parse_archive_list_page(r.text)
        f, s = _archive_persist_items(con, session, items)
        fetched += f
        skipped += s
        if page % 10 == 0:
            print(f"[archive] page {page}/{last_page} done — total fetched={fetched} skipped={skipped}")
    return fetched, skipped


def _archive_persist_items(con: sqlite3.Connection, session: requests.Session, items: list[dict]) -> tuple[int, int]:
    fetched = 0
    skipped = 0
    for item in items:
        if already_fetched(con, "archive", item["sid"]):
            skipped += 1
            continue
        if not item["thumb_url"]:
            record_failure(con, "archive", item["sid"], "thumb-url-missing", item["detail_url"], "no thumb url in card")
            continue
        l1_safe = safe_filename(item["category_l1"] or "기타", 20)
        l2_safe = safe_filename(item["category_l2"] or "기타", 30)
        title_safe = safe_filename(item["title"] or item["sid"], 40)
        dest = THUMB_DIR / "archive" / l1_safe / l2_safe / f"{item['sid']}_{title_safe}.jpg"
        ok, err = download_image(item["thumb_url"], dest, session)
        if not ok:
            record_failure(con, "archive", item["sid"], "thumb", item["thumb_url"], err)
            continue
        record_photo(
            con,
            source="archive",
            source_id=item["sid"],
            title=item["title"],
            category_l1=item["category_l1"],
            category_l2=item["category_l2"],
            category_l3=None,
            gugun=None,  # detail page 에서 추가 (큐레이션 후 lazy)
            attribution="©부산광역시",
            thumb_path=str(dest.relative_to(ROOT)),
            thumb_url=item["thumb_url"],
            original_url=item["detail_url"],  # 실제 원본은 detail page 에서 추출
            license_type="kogl-1",
            archived_at=datetime.now(timezone.utc).isoformat(),
        )
        fetched += 1
        time.sleep(ARCHIVE_SLEEP)
    return fetched, skipped


# ───────────────────── main ─────────────────────


def main():
    parser = argparse.ArgumentParser(description="Step 5.2a — 부산 관광 사진 source 썸네일 수집")
    parser.add_argument("--source", choices=["kto", "archive", "all"], default="all")
    parser.add_argument("--limit-pages", type=int, default=None, help="페이지 수 제한 (dry-run 용)")
    args = parser.parse_args()

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    con = init_db()
    session = requests.Session()
    started = datetime.now(timezone.utc)

    print(f"[main] started_at={started.isoformat()} source={args.source} limit_pages={args.limit_pages}")
    print(f"[main] THUMB_DIR={THUMB_DIR}")
    print(f"[main] DB_PATH={DB_PATH}")
    print()

    total_f = 0
    total_s = 0
    if args.source in ("kto", "all"):
        f, s = run_kto(con, session, limit_pages=args.limit_pages)
        total_f += f
        total_s += s
        print(f"[kto] done — fetched={f} skipped={s}")
    if args.source in ("archive", "all"):
        f, s = run_archive(con, session, limit_pages=args.limit_pages)
        total_f += f
        total_s += s
        print(f"[archive] done — fetched={f} skipped={s}")

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print()
    print(f"[main] DONE — fetched={total_f} skipped={total_s} elapsed={elapsed:.0f}s")
    print(f"[main] DB summary:")
    cur = con.execute("SELECT source, COUNT(*) FROM photos GROUP BY source")
    for src, cnt in cur:
        print(f"  - {src}: {cnt}")
    cur = con.execute("SELECT COUNT(*) FROM fetch_failures")
    print(f"  - failures: {cur.fetchone()[0]}")


if __name__ == "__main__":
    sys.exit(main() or 0)
