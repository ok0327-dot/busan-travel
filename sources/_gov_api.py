"""gov-api-kr 어댑터 — data.go.kr API 호출을 통일 경로로.

이 모듈은 vendor/gov-api-kr/snippets/_caller_template.py 를 import 해서
rate limiter + 24h cache + 재시도 + 에러분류를 얻는다.

원본 gov-api-kr repo는 2026-04-28 archived (`ok0327-dot/gov-api-kr` → 후속
ok0327-dot/api-vault). vendor 카피만 유지. sibling fallback 경로는 archive
시점에 제거 — vendor 자립.

필요 조건:
- 이 프로세스의 env 에 DATA_GO_KR_KEY 주입 (api-vault/.env 또는 시스템 환경변수)
- BUSAN_FESTIVAL_API_KEY 가 세팅돼 있으면 하위 호환으로 DATA_GO_KR_KEY 로 승격
- GOV_API_KR_HOME 환경변수로 다른 경로 강제 가능 (e.g. CI에서 vendor와 별도 위치)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "vendor" / "gov-api-kr",  # vendor 카피 — 표준 경로
    Path("/root/workspace/gov-api-kr"),                                # RunPod 기타 (선택)
)


def _has_caller_template(p: Path) -> bool:
    """exists() 호출 시 PermissionError/OSError 가 나면 False 로 취급."""
    try:
        return (p / "snippets" / "_caller_template.py").exists()
    except (OSError, PermissionError):
        return False


def _resolve_home() -> Path:
    env = os.environ.get("GOV_API_KR_HOME")
    if env:
        p = Path(env)
        if _has_caller_template(p):
            return p
        raise RuntimeError(f"GOV_API_KR_HOME={env} 에 snippets/_caller_template.py 없음")
    for p in _CANDIDATES:
        if _has_caller_template(p):
            return p
    raise RuntimeError(
        "gov-api-kr 를 찾을 수 없음. GOV_API_KR_HOME 환경변수 설정 필요.\n"
        f"  탐지 시도: {[str(p) for p in _CANDIDATES]}"
    )


_HOME = _resolve_home()
sys.path.insert(0, str(_HOME / "snippets"))

if not os.environ.get("DATA_GO_KR_KEY"):
    legacy = os.environ.get("BUSAN_FESTIVAL_API_KEY")
    if legacy:
        os.environ["DATA_GO_KR_KEY"] = legacy

from _caller_template import (  # noqa: E402
    call_api,
    GovApiAuthError,
    GovApiError,
    GovApiParseError,
    GovApiRateLimitError,
    GovApiTransportError,
)

__all__ = [
    "call_api",
    "GovApiAuthError",
    "GovApiError",
    "GovApiParseError",
    "GovApiRateLimitError",
    "GovApiTransportError",
]
