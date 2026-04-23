"""gov-api-kr 어댑터 — data.go.kr API 호출을 통일 경로로.

이 모듈은 gov-api-kr 프로젝트의 `call_api`를 import 해서 rate limiter + 24h
cache + 재시도 + 에러분류 + applied_pending pre-flight 을 공짜로 얻는다.

필요 조건:
- GOV_API_KR_HOME 환경변수 또는 아래 자동탐지 경로 중 하나에 gov-api-kr 체크아웃
- 해당 프로젝트의 .env 에 DATA_GO_KR_KEY 또는 이 프로세스의 env 에 주입

BUSAN_FESTIVAL_API_KEY 가 세팅돼 있으면 하위 호환으로 DATA_GO_KR_KEY 로 승격.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_CANDIDATES = (
    Path.home() / "my_playground" / "gov-api-kr",                 # 로컬 dev (monorepo sibling)
    Path("/root/workspace/gov-api-kr"),                           # RunPod 기타
    Path(__file__).resolve().parent.parent / "vendor" / "gov-api-kr",  # CI/배포 (vendored)
)


def _resolve_home() -> Path:
    env = os.environ.get("GOV_API_KR_HOME")
    if env:
        p = Path(env)
        if (p / "snippets" / "_caller_template.py").exists():
            return p
        raise RuntimeError(f"GOV_API_KR_HOME={env} 에 snippets/_caller_template.py 없음")
    for p in _CANDIDATES:
        if (p / "snippets" / "_caller_template.py").exists():
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
