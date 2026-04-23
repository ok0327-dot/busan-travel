"""
gov-api-kr 공통 호출 템플릿 — 공공데이터포털(data.go.kr) 범용 API 호출기.

기능:
- registry.json 기반 API 스펙 로드, DATA_GO_KR_KEY 환경변수/.env 통합 키 로드
- 공통 파라미터(ServiceKey/pageNo/numOfRows/resultType) 자동 주입
- XML/JSON 응답 공통 래퍼 표준화 (_deep_find 재귀 탐색)
- per-API 일일 rate limit + 24h 디스크 캐시 (이용약관 제14조 제5항)
- H1: 네트워크·5xx 재시도 (지수 백오프 3회)
- H2: data.go.kr 에러코드 테이블 기반 분류 예외
- H3: 구조화 로깅 → .cache/calls.log

사용:
    from _caller_template import call_api
    r = call_api("15063472", "getFoodKr", pageNo=1, numOfRows=10)
    if r["result_code"] != "00":
        print(r["result_msg"])

    # 예외로 받고 싶을 때
    from _caller_template import call_api, GovApiAuthError, GovApiRateLimitError
    try:
        r = call_api("15063472", "getFoodKr", raise_on_error=True)
    except GovApiAuthError as e:
        print(f"키 문제: {e}")
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
import xmltodict

# ─── 경로·상수 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "registry.json"
ENV_PATH = PROJECT_ROOT / ".env"
CACHE_DIR = PROJECT_ROOT / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

CACHE_TTL_SEC = 24 * 60 * 60
MAX_RETRIES = 3
BACKOFF_BASE = 1  # seconds — 1, 2, 4 = 총 최대 7초 대기

# ─── 예외 계층 (H2) ─────────────────────────────────────────
class GovApiError(Exception):
    """data.go.kr API 호출 실패의 최상위 예외."""

    def __init__(self, message: str, code: str = "", api_id: str = ""):
        super().__init__(message)
        self.code = code
        self.api_id = api_id


class GovApiAuthError(GovApiError):
    """인증키 미등록·정지·IP 미등록 등 키 관련 오류."""


class GovApiRateLimitError(GovApiError):
    """일일 한도 초과."""


class GovApiTransportError(GovApiError):
    """네트워크·서버(5xx)·타임아웃."""


class GovApiParseError(GovApiError):
    """응답 파싱 실패 (JSON/XML 둘 다 실패)."""


# ─── data.go.kr 에러코드 테이블 (H2) ─────────────────────────
# 공공데이터포털 전 API 공통 resultCode. 분류 가능한 것만 예외 클래스 매핑.
ERROR_CODE_TABLE: dict[str, tuple[str, type[GovApiError] | None]] = {
    "00": ("NORMAL_CODE", None),
    "01": ("APPLICATION_ERROR", GovApiError),
    "02": ("DB_ERROR", GovApiError),
    "03": ("NODATA_ERROR", GovApiError),
    "10": ("INVALID_REQUEST_PARAMETER_ERROR", GovApiError),
    "11": ("NO_MANDATORY_REQUEST_PARAMETERS_ERROR", GovApiError),
    "12": ("NO_OPENAPI_SERVICE_ERROR", GovApiError),
    "20": ("SERVICE_ACCESS_DENIED_ERROR", GovApiAuthError),
    "21": ("TEMPORARILY_DISABLE_THE_SERVICEKEY_ERROR", GovApiAuthError),
    "22": ("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", GovApiRateLimitError),
    "30": ("SERVICE_KEY_IS_NOT_REGISTERED_ERROR", GovApiAuthError),
    "31": ("DEADLINE_HAS_EXPIRED_ERROR", GovApiAuthError),
    "32": ("UNREGISTERED_IP_ERROR", GovApiAuthError),
    "33": ("UNSIGNED_CALL_ERROR", GovApiAuthError),
    "99": ("UNKNOWN_ERROR", GovApiError),
}

# ─── 로깅 설정 (H3) ─────────────────────────────────────────
def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("gov_api_kr")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(CACHE_DIR / "calls.log", encoding="utf-8")
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    logger.addHandler(fh)
    logger.propagate = False
    return logger


logger = _setup_logger()


# ─── 키·레지스트리 로드 ──────────────────────────────────────
def _load_key() -> str:
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATA_GO_KR_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        raise GovApiAuthError(
            f"DATA_GO_KR_KEY 미설정. {ENV_PATH}에 적거나 환경변수로 주입."
        )
    return key


def _load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


# ─── 캐시 ────────────────────────────────────────────────────
def _cache_file(api_id: str, operation: str, params: dict) -> Path:
    digest = hashlib.sha256(
        f"{api_id}:{operation}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}".encode()
    ).hexdigest()[:16]
    return CACHE_DIR / f"cache_{api_id}_{operation}_{digest}.json"


def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - blob["ts"] < CACHE_TTL_SEC:
            return blob["data"]
    except Exception:
        return None
    return None


def _write_cache(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps({"ts": time.time(), "data": data}, ensure_ascii=False),
        encoding="utf-8",
    )


# ─── Rate Limit (이용약관 제14조 제5항) ──────────────────────
def _check_rate_limit(api_id: str, daily_limit: int) -> None:
    today = date.today().isoformat()
    counter_file = CACHE_DIR / f"rate_{api_id}.json"
    blob = {"date": today, "count": 0}
    if counter_file.exists():
        try:
            loaded = json.loads(counter_file.read_text(encoding="utf-8"))
            if loaded.get("date") == today:
                blob = loaded
        except Exception:
            pass
    if blob["count"] >= daily_limit:
        raise GovApiRateLimitError(
            f"일일 한도 초과: api={api_id} ({blob['count']}/{daily_limit})",
            api_id=api_id,
        )
    blob["count"] += 1
    counter_file.write_text(json.dumps(blob), encoding="utf-8")


# ─── HTTP 재시도 (H1) ────────────────────────────────────────
def _call_with_retry(url: str, params: dict, timeout: int = 30) -> requests.Response:
    """네트워크·5xx 오류에 대한 지수 백오프 재시도.

    HTTP 4xx 처리:
    - 401/403 → GovApiAuthError (재시도 의미 없음, 키·권한 문제)
    - 429     → GovApiRateLimitError
    - 기타 4xx → 그대로 반환 (본문 파싱 후 resultCode로 분류 시도)
    5xx는 재시도.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code in (401, 403):
                body = resp.text[:200]
                raise GovApiAuthError(
                    f"HTTP {resp.status_code}: {body}",
                    code=f"HTTP{resp.status_code}",
                )
            if resp.status_code == 429:
                raise GovApiRateLimitError(
                    f"HTTP 429 Too Many Requests: {resp.text[:200]}",
                    code="HTTP429",
                )
            if 500 <= resp.status_code < 600:
                raise requests.HTTPError(
                    f"server {resp.status_code}", response=resp
                )
            if attempt > 1:
                logger.info(f"recovered attempt={attempt} url={url}")
            return resp
        except (GovApiAuthError, GovApiRateLimitError):
            # 재시도 불필요 — 즉시 전파
            raise
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == MAX_RETRIES:
                logger.error(f"exhausted attempts={attempt} url={url} error={e}")
                raise GovApiTransportError(
                    f"네트워크·서버 오류 {MAX_RETRIES}회 실패: {e}"
                ) from e
            wait = BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                f"retry {attempt}/{MAX_RETRIES} wait={wait}s url={url} error={e}"
            )
            time.sleep(wait)
    raise GovApiTransportError("unreachable")  # pragma: no cover


# ─── 응답 파서 (H6 개선 포함) ────────────────────────────────
def _deep_find(obj: Any, keys: tuple[str, ...]) -> Any:
    """dict 트리에서 주어진 키 중 하나를 첫 번째로 매치. BFS로 얕은 depth 우선 → 오탐 감소."""
    queue: list[Any] = [obj]
    while queue:
        cur = queue.pop(0)
        if isinstance(cur, dict):
            for k in keys:
                if k in cur:
                    return cur[k]
            queue.extend(cur.values())
        elif isinstance(cur, list):
            queue.extend(cur)
    return None


def _parse_response(raw: str, prefer_json: bool) -> dict:
    """응답 표준화. XML/JSON 구조 차이를 재귀 탐색으로 흡수.

    XML:  {response: {header: {resultCode, resultMsg}, body: {items: {item: [...]}, totalCount}}}
    JSON: {<opName>: {header: {code, message}, item: [...], totalCount}}
    """
    body: Any
    if prefer_json:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            try:
                body = xmltodict.parse(raw)
            except Exception as e:
                raise GovApiParseError(f"JSON/XML 둘 다 파싱 실패: {e}") from e
    else:
        try:
            body = xmltodict.parse(raw)
        except Exception as e:
            raise GovApiParseError(f"XML 파싱 실패: {e}") from e

    header = _deep_find(body, ("header",)) or {}
    if not isinstance(header, dict):
        header = {}

    # TourAPI flat error: {"resultCode":"10","resultMsg":"...","responseTime":"..."}
    top = body if isinstance(body, dict) else {}
    result_code = (
        header.get("resultCode") or header.get("code")
        or top.get("resultCode") or top.get("code")
        or "unknown"
    )
    result_msg = (
        header.get("resultMsg") or header.get("message")
        or top.get("resultMsg") or top.get("message")
        or ""
    )

    items_section = _deep_find(body, ("items",))
    if isinstance(items_section, dict) and "item" in items_section:
        raw_items = items_section["item"]
        items = raw_items if isinstance(raw_items, list) else [raw_items]
    elif isinstance(items_section, list):
        items = items_section
    else:
        raw_items = _deep_find(body, ("item",))
        if isinstance(raw_items, list):
            items = raw_items
        elif isinstance(raw_items, dict):
            items = [raw_items]
        else:
            items = []

    def _safe_int(val: Any, default: int) -> int:
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    return {
        "result_code": result_code,
        "result_msg": result_msg,
        "total_count": _safe_int(_deep_find(body, ("totalCount",)), 0),
        "page_no": _safe_int(_deep_find(body, ("pageNo",)), 1),
        "num_of_rows": _safe_int(_deep_find(body, ("numOfRows",)), len(items)),
        "items": items,
        "raw": body,
    }


def _raise_for_result_code(parsed: dict, api_id: str) -> None:
    """resultCode가 00이 아니면 테이블 기반 예외 발생."""
    code = parsed["result_code"]
    if code == "00":
        return
    name, exc_class = ERROR_CODE_TABLE.get(code, (parsed["result_msg"] or "UNKNOWN", GovApiError))
    if exc_class is None:
        return
    raise exc_class(
        f"[{code}] {name} — {parsed['result_msg']}", code=code, api_id=api_id
    )


# ─── 메인 호출 함수 ──────────────────────────────────────────
def call_api(
    api_id: str,
    operation: str,
    *,
    pageNo: int = 1,
    numOfRows: int = 10,
    as_json: bool = True,
    use_cache: bool = True,
    raise_on_error: bool = False,
    **extra_params: Any,
) -> dict:
    """공공데이터포털 범용 호출.

    Args:
        api_id: registry.json에 등록된 ID (예: "15063472")
        operation: 오퍼레이션명 (예: "getFoodKr")
        pageNo, numOfRows: 공통 페이징
        as_json: True면 resultType=json 추가
        use_cache: 24h 디스크 캐시 사용
        raise_on_error: True면 result_code != "00" 시 분류 예외 발생 (default False, 기존 호환)
        extra_params: API별 추가 파라미터

    Returns:
        dict(result_code, result_msg, total_count, page_no, num_of_rows, items, raw)

    Raises:
        GovApiAuthError: 키 문제 (raise_on_error=True + 코드 20/21/30-33)
        GovApiRateLimitError: 한도 초과 (raise_on_error=True + 코드 22)
        GovApiTransportError: 네트워크/5xx (항상)
        GovApiParseError: 응답 파싱 실패 (항상)
        GovApiError: 기타 resultCode != 00 (raise_on_error=True)
    """
    registry = _load_registry()
    api_spec = registry.get("apis", {}).get(api_id)
    if not api_spec:
        raise GovApiError(
            f"{api_id} 미등록. `/gov-api register-confirm {api_id}` 먼저.",
            api_id=api_id,
        )
    op_spec = api_spec.get("operations", {}).get(operation)
    if not op_spec:
        raise GovApiError(
            f"operation '{operation}' not found in api {api_id}", api_id=api_id
        )

    if api_spec.get("applied_pending"):
        note = api_spec.get("applied_pending_note", "사용자 활용신청 클릭 필요")
        msg = (
            f"[PENDING_APPROVAL] {api_id} 활용신청 대기 중 — {note} "
            f"(https://www.data.go.kr/data/{api_id}/openapi.do)"
        )
        logger.warning(f"pending api={api_id} — skipping HTTP call")
        if raise_on_error:
            raise GovApiAuthError(msg, code="PENDING_APPROVAL", api_id=api_id)
        return {
            "result_code": "PENDING",
            "result_msg": msg,
            "total_count": 0,
            "page_no": pageNo,
            "num_of_rows": 0,
            "items": [],
            "raw": None,
        }

    url = api_spec["base_url"].rstrip("/") + op_spec["path"]
    daily_limit = op_spec.get("daily_limit_dev", 1000)

    params: dict[str, Any] = {
        "ServiceKey": _load_key(),
        "pageNo": pageNo,
        "numOfRows": numOfRows,
    }
    # resultType 은 부처마다 이름 다름: 대부분 "resultType", TourAPI "_type", 기상청 "dataType".
    # 사용자가 extra_params 로 provider-specific 키를 이미 주면 resultType 주입 생략
    has_provider_format = any(k in extra_params for k in ("_type", "dataType"))
    if as_json and not has_provider_format:
        params["resultType"] = "json"
    params.update(extra_params)

    cache_params = {k: v for k, v in params.items() if k != "ServiceKey"}
    cpath = _cache_file(api_id, operation, cache_params)

    if use_cache:
        cached = _read_cache(cpath)
        if cached is not None:
            logger.info(f"cache hit api={api_id} op={operation}")
            if raise_on_error:
                _raise_for_result_code(cached, api_id)
            return cached

    _check_rate_limit(api_id, daily_limit)
    logger.info(f"call api={api_id} op={operation} params={cache_params}")

    try:
        resp = _call_with_retry(url, params)
    except GovApiAuthError:
        logger.warning(f"auth error api={api_id} — 활용신청 승인 확인 필요")
        if raise_on_error:
            raise
        # backward-compat: dict 형태로 반환
        return {
            "result_code": "HTTP403",
            "result_msg": "Forbidden — 활용신청 미승인 또는 키 문제",
            "total_count": 0,
            "page_no": pageNo,
            "num_of_rows": 0,
            "items": [],
            "raw": None,
        }
    parsed = _parse_response(resp.text, prefer_json=as_json)

    if parsed["result_code"] != "00":
        logger.warning(
            f"result_code={parsed['result_code']} api={api_id} msg={parsed['result_msg']}"
        )
    else:
        logger.info(
            f"ok api={api_id} total={parsed['total_count']} rows={len(parsed['items'])}"
        )

    if use_cache and parsed["result_code"] == "00":
        # 에러 응답은 캐시하지 않음 (일시적일 수 있음)
        _write_cache(cpath, parsed)

    if raise_on_error:
        _raise_for_result_code(parsed, api_id)

    return parsed


if __name__ == "__main__":
    r = call_api("15063472", "getFoodKr", pageNo=1, numOfRows=3)
    print(f"resultCode={r['result_code']} total={r['total_count']}")
    for item in r["items"]:
        print(f"  - {item.get('MAIN_TITLE')} ({item.get('GUGUN_NM')}) {item.get('ADDR1')}")
