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

import _caller_template as _vendor  # noqa: E402  (위 from-import 와 같은 모듈 객체 / same module object)
import requests  # noqa: E402

from sources._circuit import BREAKER, CONNECT_TIMEOUT_S  # noqa: E402


class CircuitOpenError(GovApiTransportError):
    """이번 실행에서 연결이 연달아 실패한 호스트 — 네트워크를 타지 않고 즉시 실패.

    GovApiTransportError 하위 클래스라 기존 except 는 그대로 잡는다. 반복 호출하는 쪽
    (예: 격자 순회)은 이걸 따로 잡아 순회를 끊으면 된다 / catch it to stop a loop early.
    """


# vendor 의 실제 네트워크 호출 한 곳(_call_with_retry)을 감싼다. call_api 는 이 이름을 호출 시점에
# 모듈 전역에서 찾으므로 속성 교체로 적용된다. vendor 파일은 건드리지 않는다.
# / Wrap vendor's single network call site; call_api resolves it at call time. Vendor file untouched.
#   ① 연결 대기 30s → 10s (응답 대기는 30s 유지) — 해외 러너에서 막히는 날 호출당 93s → 33s
#   ② 연결 실패가 연달아 나면 그 호스트는 이번 실행 동안 즉시 CircuitOpenError
_vendor_call_with_retry = _vendor._call_with_retry


def _guarded_call_with_retry(url: str, params: dict, timeout=30):
    if not BREAKER.allow(url):
        raise CircuitOpenError(
            f"회로 차단 — {BREAKER.host(url)} 는 이번 실행에서 연결이 연달아 실패했다 / circuit open"
        )
    if isinstance(timeout, (int, float)):
        timeout = (min(CONNECT_TIMEOUT_S, timeout), timeout)
    try:
        resp = _vendor_call_with_retry(url, params, timeout=timeout)
    except GovApiTransportError as exc:
        if isinstance(exc.__cause__, requests.ConnectionError):
            BREAKER.record_unreachable(url)
        else:
            BREAKER.record_reachable(url)  # 5xx·응답지연 — 연결은 됐다 / connected, just failing
        raise
    except (GovApiAuthError, GovApiRateLimitError):
        BREAKER.record_reachable(url)
        raise
    BREAKER.record_reachable(url)
    return resp


_vendor._call_with_retry = _guarded_call_with_retry

__all__ = [
    "call_api",
    "CircuitOpenError",
    "GovApiAuthError",
    "GovApiError",
    "GovApiParseError",
    "GovApiRateLimitError",
    "GovApiTransportError",
]
