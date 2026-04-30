"""R2 에서 events.db 다운로드 / 업로드 (cron 영속화) + daily archive + 30일 retention.

audit P1-5 (2026-04-25): 백본 외부 의존 시 disaster recovery 필수. 매 upload 시
 latest + 일자 archive 둘 다 저장. lifecycle rule 로 30일 후 archive 자동 정리.

Usage:
    python scripts/db_sync.py download         # cron 시작 — 없으면 fresh start
    python scripts/db_sync.py upload           # latest + archive 둘 다
    python scripts/db_sync.py setup-lifecycle  # archive prefix 30일 retention rule (idempotent)

환경 변수 (GitHub Secrets):
    R2_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET                  (옵션, 기본 'busan-travel-images')
    R2_DB_KEY                  (옵션, 기본 'db/events.db')
    R2_DB_ARCHIVE_PREFIX       (옵션, 기본 'db/archive')
    R2_DB_RETENTION_DAYS       (옵션, 기본 30)

설정 미존재 시 즉시 종료 (exit 0) — workflow 가 graceful degrade 하도록.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "events.db"
BUCKET = os.environ.get("R2_BUCKET", "busan-travel-images")
KEY = os.environ.get("R2_DB_KEY", "db/events.db")
ARCHIVE_PREFIX = os.environ.get("R2_DB_ARCHIVE_PREFIX", "db/archive").rstrip("/")
RETENTION_DAYS = int(os.environ.get("R2_DB_RETENTION_DAYS", "30"))


def _client():
    """boto3 S3 client to Cloudflare R2."""
    try:
        import boto3
        from botocore.client import Config
    except ImportError:
        print("[db_sync] boto3 미설치 — R2 sync 건너뜀", file=sys.stderr)
        sys.exit(0)

    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (account_id and access_key and secret_key):
        print("[db_sync] R2 credentials 미설정 — sync 건너뜀 (정상)", file=sys.stderr)
        sys.exit(0)

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def download() -> None:
    client = _client()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(BUCKET, KEY, str(DB_PATH))
        size = DB_PATH.stat().st_size
        print(f"[db_sync] downloaded {KEY} → {DB_PATH} ({size:,} bytes)")
    except Exception as e:
        msg = str(e)
        # 첫 실행은 R2 에 db 없어서 404 — 정상
        if any(x in msg for x in ("404", "Not Found", "NoSuchKey", "does not exist")):
            print(f"[db_sync] R2 에 {KEY} 없음 — fresh start", file=sys.stderr)
            return
        # 그 외 에러는 fail 시켜서 cron 에 문제 알림 (단 workflow 의 continue-on-error 가 흡수)
        print(f"[db_sync] download FAILED: {msg}", file=sys.stderr)
        sys.exit(1)


def upload() -> None:
    if not DB_PATH.exists():
        print(f"[db_sync] {DB_PATH} 없음 — 업로드 스킵", file=sys.stderr)
        return
    client = _client()
    size = DB_PATH.stat().st_size
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_key = f"{ARCHIVE_PREFIX}/events-{today}.db"
    try:
        client.upload_file(str(DB_PATH), BUCKET, KEY)
        print(f"[db_sync] uploaded latest → {KEY} ({size:,} bytes)")
        client.upload_file(str(DB_PATH), BUCKET, archive_key)
        print(f"[db_sync] uploaded archive → {archive_key}")
    except Exception as e:
        print(f"[db_sync] upload FAILED: {e}", file=sys.stderr)
        sys.exit(1)


def setup_lifecycle() -> None:
    client = _client()
    rule_id = f"expire-{ARCHIVE_PREFIX.replace('/', '-')}-{RETENTION_DAYS}d"
    config = {
        "Rules": [
            {
                "ID": rule_id,
                "Status": "Enabled",
                "Filter": {"Prefix": f"{ARCHIVE_PREFIX}/"},
                "Expiration": {"Days": RETENTION_DAYS},
            }
        ]
    }
    try:
        client.put_bucket_lifecycle_configuration(
            Bucket=BUCKET, LifecycleConfiguration=config
        )
        print(
            f"[db_sync] lifecycle rule 적용 — prefix={ARCHIVE_PREFIX}/ retention={RETENTION_DAYS}d (id={rule_id})"
        )
    except Exception as e:
        print(f"[db_sync] lifecycle 적용 실패: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) == 2 else None
    handlers = {"download": download, "upload": upload, "setup-lifecycle": setup_lifecycle}
    if cmd not in handlers:
        print(
            "Usage: python scripts/db_sync.py {download|upload|setup-lifecycle}",
            file=sys.stderr,
        )
        sys.exit(2)
    handlers[cmd]()
