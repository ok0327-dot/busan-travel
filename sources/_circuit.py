"""호스트별 회로 차단기(circuit breaker) — 연결이 연달아 안 되는 서버는 이번 실행 동안 즉시 포기한다.

Per-host circuit breaker: once a host fails to *connect* N times in a row, every later
request to it in this process fails immediately instead of burning timeouts.

왜 / Why (2026-09-21 실측):
  GitHub 러너(해외 IP)에서 한국 공공·문화 사이트(apis.data.go.kr·busan.go.kr·다봄·벡스코…)가
  며칠에 한 번 통째로 연결이 안 된다(전부 ConnectTimeoutError). 그런데 호출마다 연결 30s×3회를
  끝까지 기다리고 다음 호출도 똑같이 시도해서, 2026-09-20 run 은 Events+POIs 가 10→28분으로 늘고
  KMA 단기예보가 격자마다 93초씩 쓰다 job 45분 상한에 잘렸다 → 그날 수집·백업 전부 유실.

무엇을 세나 / What counts:
  - 연결 실패(requests.ConnectionError — ConnectTimeout 포함)만 센다. 서버가 응답을 줬다면
    (2xx·4xx·5xx 무엇이든) 도달 가능한 것이므로 연속 횟수를 0으로 되돌린다.
  - 응답 지연(ReadTimeout)은 세지 않는다 — 연결은 됐고 서버는 살아 있다.
  - 상태는 **프로세스 안에서만** 유지된다. CI 스텝마다 새 프로세스라 다음 스텝은 다시 시도한다.
"""
from __future__ import annotations

import sys
import threading
from urllib.parse import urlsplit

# 연결(TCP connect) 대기 상한. 응답 대기(read)와 별개다 — 정상 서버는 해외에서도 1초 안에 붙는다.
# / connect-phase timeout only; read timeouts are left as each caller sets them.
CONNECT_TIMEOUT_S = 10.0
# 연속 연결 실패 이만큼이면 차단 / consecutive connect failures that open the circuit.
FAILURE_THRESHOLD = 2


class HostCircuitBreaker:
    def __init__(self, threshold: int = FAILURE_THRESHOLD) -> None:
        self.threshold = threshold
        self._fails: dict[str, int] = {}
        self._open: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def host(url: str) -> str:
        return urlsplit(url).netloc.lower()

    def allow(self, url: str) -> bool:
        return self.host(url) not in self._open

    def record_reachable(self, url: str) -> None:
        """서버가 응답했다(상태코드 무관) → 연속 실패 초기화 / host answered: reset the streak."""
        with self._lock:
            self._fails.pop(self.host(url), None)

    def record_unreachable(self, url: str) -> bool:
        """연결 실패 1회 기록. 이번 호출로 차단이 열렸으면 True / returns True when this opens the circuit."""
        h = self.host(url)
        with self._lock:
            n = self._fails.get(h, 0) + 1
            self._fails[h] = n
            if n < self.threshold or h in self._open:
                return False
            self._open.add(h)
        print(
            f"[circuit] {h} 연결 {n}회 연속 실패 → 이번 실행 동안 차단 / circuit open for this run",
            file=sys.stderr,
        )
        return True

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()
            self._open.clear()


# 프로세스 전역 하나 — HTTPSession(스크래퍼)과 _gov_api(공공데이터)가 공유한다.
# / one per process, shared by the scraper path and the data.go.kr path (same hosts).
BREAKER = HostCircuitBreaker()
