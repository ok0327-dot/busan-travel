"""어댑터 공통 헬퍼 — HTTP session + retry + rate-limit + 표준 로그.

설계 / Design:
- BaseAdapter 클래스가 아닌 작은 함수형 헬퍼 — 어댑터별 파싱이 80% 고유 가치.
- HTTPSession 으로 boilerplate 5-10줄/어댑터 절감 + retry/rate-limit 무료 획득.
- 모든 어댑터가 동일한 UA(_http.DEFAULT_HEADERS), 동일한 timeout, 동일한 로그 포맷.

사용 예 / Usage:
    from sources._adapter import HTTPSession, report

    SOURCE = "art_busan"
    session = HTTPSession(SOURCE)

    def fetch():
        events = []
        soup = session.soup("https://art.busan.go.kr/.../listNowClient.nm")
        if not soup:
            return events
        for ...:
            d_soup = session.soup(detail_url)
            ...
            events.append(Event(...))
        return report(SOURCE, events)
"""
from __future__ import annotations

import sys
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

from sources._http import DEFAULT_HEADERS


class HTTPSession:
    """어댑터용 HTTP 세션 — 표준 헤더·timeout·retry·rate-limit 내장.

    요청 간 최소 간격(rate_limit_s) 보장 + 일시 실패 시 지수 백오프 retry.
    실패 시 None 반환 (어댑터는 None 체크만 하면 됨, try/except 불필요).
    """

    def __init__(
        self,
        source: str,
        *,
        timeout: float = 15,
        rate_limit_s: float = 0.3,
        retries: int = 2,
    ) -> None:
        self.source = source
        self.timeout = timeout
        self.rate_limit_s = rate_limit_s
        self.retries = retries
        self.s = requests.Session()
        self.s.headers.update(DEFAULT_HEADERS)
        self._last_call: float = 0.0

    def _throttle(self) -> None:
        if self.rate_limit_s <= 0:
            return
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit_s:
            time.sleep(self.rate_limit_s - elapsed)

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> requests.Response | None:
        """GET 요청. 성공 시 Response, 실패 시 None.

        retry 횟수만큼 지수 백오프 후 None 리턴. 에러는 stderr 로그.
        """
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                r = self.s.get(url, params=params, timeout=timeout or self.timeout)
                r.raise_for_status()
                self._last_call = time.time()
                return r
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))  # 1s, 2s, ...
                    continue
        print(f"[{self.source}] GET {url}: {last_exc}", file=sys.stderr)
        return None

    def soup(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        parser: str = "html.parser",
    ) -> BeautifulSoup | None:
        """GET → BeautifulSoup. 실패 시 None."""
        r = self.get(url, params=params)
        return BeautifulSoup(r.text, parser) if r else None


def report(source: str, events: list, **extras: Any) -> list:
    """어댑터 종료 시 표준 summary 로그. events 그대로 리턴 (chaining)."""
    extra_s = " ".join(f"{k}={v}" for k, v in extras.items())
    print(
        f"[{source}] fetched={len(events)}" + (" " + extra_s if extra_s else ""),
        file=sys.stderr,
    )
    return events
