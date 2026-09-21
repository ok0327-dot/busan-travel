"""호스트별 회로 차단기 회귀 테스트 — 네트워크 0 (닫힌 로컬 포트 + 로컬 재생 서버만).

Circuit-breaker regression tests. The failure mode they pin (2026-09-20 run): the GitHub runner
could not connect to Korean public hosts; every call waited connect 30s × 3 and the next call did the
same, so KMA short spent 93s per grid until the 45-minute job cap killed the whole run.

    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import contextlib
import io
import os
import runpy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from sources import _gov_api, weather_kma_short
from sources._adapter import HTTPSession
from sources._circuit import BREAKER, CONNECT_TIMEOUT_S, HostCircuitBreaker
from sources._gov_api import CircuitOpenError, GovApiTransportError, call_api
from tests.http_fixture_server import FixtureServer, dead_local_url, local_no_proxy

import _caller_template as vendor  # noqa: E402  (_gov_api 가 sys.path 에 올린 vendor 모듈)


def _quiet():
    return contextlib.redirect_stderr(io.StringIO())


class BreakerUnit(unittest.TestCase):
    def test_opens_after_consecutive_connect_failures_per_host(self):
        b = HostCircuitBreaker(threshold=2)
        with _quiet():
            self.assertFalse(b.record_unreachable("http://h.example/a"))
            self.assertTrue(b.allow("http://h.example/a"), "1회로는 안 막는다")
            self.assertTrue(b.record_unreachable("http://h.example/b"), "경로가 달라도 같은 호스트")
        self.assertFalse(b.allow("http://h.example/anything"))
        self.assertTrue(b.allow("http://other.example/a"), "다른 호스트는 영향 없음")

    def test_any_answer_resets_the_streak(self):
        b = HostCircuitBreaker(threshold=2)
        with _quiet():
            b.record_unreachable("http://h.example/a")
            b.record_reachable("http://h.example/a")
            b.record_unreachable("http://h.example/a")
        self.assertTrue(b.allow("http://h.example/a"))


@mock.patch("sources._adapter.time.sleep", lambda s: None)  # 재시도 백오프 생략 / skip backoff
class HTTPSessionBreaker(unittest.TestCase):
    """스크래퍼 경로 / scraper path."""

    def setUp(self):
        BREAKER.reset()
        self.addCleanup(BREAKER.reset)  # 닫힌 포트 번호가 나중에 재생 서버에 재사용될 수 있다
        self.enterContext(local_no_proxy())

    def test_unreachable_host_is_skipped_without_network_after_two_failures(self):
        base = dead_local_url()
        sess = HTTPSession("t", retries=1, rate_limit_s=0)
        spy = self.enterContext(mock.patch.object(sess.s, "get", wraps=sess.s.get))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(sess.get(base + "a"))
            self.assertIsNone(sess.get(base + "b"))
            self.assertEqual(spy.call_count, 4, "2 URL × (1회 + 재시도 1회)")
            self.assertIsNone(sess.get(base + "c"))
        self.assertEqual(spy.call_count, 4, "차단 뒤에는 네트워크를 타지 않는다 / no network once open")
        self.assertIn("[circuit]", err.getvalue())
        self.assertIn("SKIP", err.getvalue())

    def test_connect_timeout_is_capped_separately_from_read_timeout(self):
        sess = HTTPSession("t", timeout=25, retries=0, rate_limit_s=0)
        with FixtureServer({"/ok": (200, "text/plain", b"ok")}) as srv, \
                mock.patch.object(sess.s, "get", wraps=sess.s.get) as spy:
            self.assertIsNotNone(sess.get(srv.url("/ok")))
        self.assertEqual(spy.call_args.kwargs["timeout"], (CONNECT_TIMEOUT_S, 25))

    def test_server_errors_do_not_open_the_circuit(self):
        sess = HTTPSession("t", retries=0, rate_limit_s=0)
        with FixtureServer({"/boom": (500, "text/plain", b"x")}) as srv, _quiet():
            for _ in range(4):
                self.assertIsNone(sess.get(srv.url("/boom")))
        self.assertEqual(srv.hits["/boom"], 4, "5xx 는 서버가 살아 있다는 뜻 — 계속 시도한다")


def _fake_registry(base_url: str) -> dict:
    return {"apis": {"T1": {"base_url": base_url, "operations": {"op": {"path": "/x"}}}}}


@mock.patch.object(vendor.time, "sleep", lambda s: None)  # vendor 재시도 백오프 생략
@mock.patch.object(vendor, "_check_rate_limit", lambda *a, **k: None)  # .cache 일일 카운터 안 건드림
class GovApiBreaker(unittest.TestCase):
    """공공데이터 경로 — vendor call_api 를 그대로 태운다 / data.go.kr path through the real call_api."""

    def setUp(self):
        BREAKER.reset()
        self.addCleanup(BREAKER.reset)
        self.enterContext(local_no_proxy())
        self.enterContext(mock.patch.dict(os.environ, {"DATA_GO_KR_KEY": "dummy"}))

    def test_wrapper_is_installed_on_vendor(self):
        self.assertIs(vendor._call_with_retry, _gov_api._guarded_call_with_retry)

    def test_unreachable_host_fails_fast_after_two_calls(self):
        registry = _fake_registry(dead_local_url().rstrip("/"))
        with mock.patch.object(vendor, "_load_registry", return_value=registry), \
                mock.patch.object(vendor.requests, "get", wraps=vendor.requests.get) as spy, _quiet():
            for _ in range(2):
                with self.assertRaises(GovApiTransportError) as cm:
                    call_api("T1", "op")
                self.assertNotIsInstance(cm.exception, CircuitOpenError)
            self.assertEqual(spy.call_count, 2 * vendor.MAX_RETRIES)
            with self.assertRaises(CircuitOpenError):
                call_api("T1", "op")
        self.assertEqual(spy.call_count, 2 * vendor.MAX_RETRIES, "차단 뒤에는 네트워크를 타지 않는다")
        self.assertEqual(spy.call_args.kwargs["timeout"], (CONNECT_TIMEOUT_S, 30), "연결 10s · 응답 30s")

    def test_server_errors_do_not_open_the_circuit(self):
        with FixtureServer({"/x": (500, "text/plain", b"x")}) as srv, \
                mock.patch.object(vendor, "_load_registry", return_value=_fake_registry(srv.url(""))), _quiet():
            for _ in range(3):
                with self.assertRaises(GovApiTransportError) as cm:
                    call_api("T1", "op")
                self.assertNotIsInstance(cm.exception, CircuitOpenError)
        self.assertEqual(srv.hits["/x"], 3 * vendor.MAX_RETRIES)


def _grid_db(path: Path, n: int) -> sqlite3.Connection:
    from storage.db import connect
    conn = connect(path)
    for i in range(n):
        conn.execute(
            "INSERT INTO events (source, source_id, title, first_seen, last_seen, nx, ny) VALUES (?,?,?,?,?,?,?)",
            ("t", str(i), f"e{i}", "x", "x", 90 + i, 70),
        )
    conn.commit()
    return conn


_ONE_FORECAST = {"20260922T09:00": {"TMP": "21", "SKY": "1", "PTY": "0", "POP": "10", "REH": "60", "WSD": "2.1"}}


class KmaShortLoop(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "t.db"

    def test_stops_iterating_grids_once_circuit_opens(self):
        conn = _grid_db(self.db, 6)
        down = GovApiTransportError("connect failed")
        side = [down, down, CircuitOpenError("open")] + [AssertionError("called after open")] * 3
        err = io.StringIO()
        with mock.patch.object(weather_kma_short, "fetch_grid", side_effect=side) as fg, \
                contextlib.redirect_stderr(err):
            self.assertEqual(weather_kma_short.upsert_forecasts(conn), (0, 0))
        self.assertEqual(fg.call_count, 3, "차단 이후 격자는 부르지 않는다")
        self.assertIn("남은 격자 4개", err.getvalue())

    def test_time_budget_stops_early_and_commits_what_was_fetched(self):
        conn = _grid_db(self.db, 3)
        ticks = [0.0, 0.0, 999.0]  # deadline 계산 · 1번째 격자 전 · 2번째 격자 전(초과)

        def fake_monotonic():
            return ticks.pop(0) if len(ticks) > 1 else ticks[0]

        err = io.StringIO()
        with mock.patch.object(weather_kma_short.time, "monotonic", fake_monotonic), \
                mock.patch.object(weather_kma_short, "fetch_grid", return_value=_ONE_FORECAST) as fg, \
                contextlib.redirect_stderr(err):
            self.assertEqual(weather_kma_short.upsert_forecasts(conn, time_budget_s=60), (1, 1))
        self.assertEqual(fg.call_count, 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM weather_fcst").fetchone()[0], 1, "받은 만큼은 커밋")
        self.assertIn("시간 예산", err.getvalue())

    def _run_main(self, call_api_mock) -> int:
        with mock.patch.object(config, "DB_PATH", self.db), \
                mock.patch.object(_gov_api, "call_api", call_api_mock), \
                mock.patch.object(sys, "argv", ["weather_kma_short", "--time-budget-min", "6"]), _quiet():
            with self.assertRaises(SystemExit) as cm:
                runpy.run_module("sources.weather_kma_short", run_name="__main__")
        return cm.exception.code

    def test_main_exits_1_when_every_grid_fails(self):
        _grid_db(self.db, 2).close()
        self.assertEqual(self._run_main(mock.Mock(side_effect=GovApiTransportError("down"))), 1)

    def test_main_exits_0_when_grids_succeed(self):
        _grid_db(self.db, 2).close()
        ok = {"result_code": "00", "total_count": 1, "items": [
            {"category": "TMP", "fcstDate": "20260922", "fcstTime": "0900", "fcstValue": "21"}]}
        self.assertEqual(self._run_main(mock.Mock(return_value=ok)), 0)


if __name__ == "__main__":
    unittest.main()
