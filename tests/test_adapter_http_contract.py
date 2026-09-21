"""v3.9 어댑터 계약(HTTPSession+report) 회귀 테스트 — 네트워크 0, 비용 0.

Regression tests for the adapters migrated to the HTTPSession+report contract
(audit 2026-04-25 P1-3). Recorded real responses are replayed on 127.0.0.1, so each
adapter's real HTTP stack runs end-to-end.

1) 출력 불변 / output unchanged — expected.json 은 **교체 전 코드**가 같은 녹화본에서 낸 출력이다.
   교체 후 코드가 한 필드라도 다르게 내면 빨간불.
2) 계약 동작 / contract behaviour — 일시 실패 재시도, 실패를 stderr 로 알림, API 키 비노출.
   저장소가 public 이라 Actions 로그도 공개다. requests 예외 문구는 쿼리스트링(ServiceKey 포함)을
   그대로 담고, GitHub 시크릿 마스킹은 URL 인코딩된 키(%2B·%2F·%3D)를 못 잡는다.

    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from config import NAVER_OFFICIAL_BLOGS
from sources import foodie_tour, naver_blogs, walking_tour
from sources._adapter import redact
from tests.http_fixture_server import FixtureServer

FIX = Path(__file__).parent / "fixtures" / "http_contract"
EXPECTED = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))
# URL 인코딩 대상 문자(+ / =)를 일부러 넣은 가짜 키 / fake key with chars that get percent-encoded
FAKE_KEY = "Fake+Key/For==Test"
FAKE_KEY_ENCODED = "Fake%2BKey%2FFor%3D%3DTest"


def _routes(overrides: dict[str, tuple[int, str, bytes]] | None = None) -> dict:
    manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    routes = {}
    for blog_id, _ in NAVER_OFFICIAL_BLOGS:
        m = manifest[f"rss_{blog_id}"]
        routes[f"/rss/{blog_id}.xml"] = (m["status"], m["headers"]["content-type"],
                                         (FIX / f"rss_{blog_id}.body").read_bytes())
    for name in ("foodie_tour", "walking_tour"):
        m = manifest[name]
        routes[f"/{name}"] = (m["status"], m["headers"]["content-type"], (FIX / f"{name}.body").read_bytes())
    routes.update(overrides or {})
    return routes


@contextlib.contextmanager
def _serving(overrides=None):
    """녹화본 서버를 띄우고 세 어댑터의 URL 을 그쪽으로 돌린다 / point the adapters at the replay server."""
    with FixtureServer(_routes(overrides)) as srv, \
            mock.patch.object(naver_blogs, "RSS_TEMPLATE", srv.url("/rss/{id}.xml")), \
            mock.patch.object(foodie_tour, "BASE_URL", srv.url("/foodie_tour")), \
            mock.patch.object(walking_tour, "BASE_URL", srv.url("/walking_tour")), \
            mock.patch.dict(os.environ, {"DATA_GO_KR_KEY": FAKE_KEY}):
        yield srv


def _as_dicts(events) -> list[dict]:
    return [dataclasses.asdict(e) for e in events]


class OutputUnchanged(unittest.TestCase):
    """교체 전 코드와 같은 출력 / same output as the pre-migration code."""

    def assertMatchesGolden(self, actual: list[dict], expected: list[dict]):
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            # Event 에 새 필드가 생겨도 깨지지 않게, 정답지에 있는 키만 비교 / compare golden keys only
            self.assertEqual({k: a.get(k) for k in e}, e)

    def test_naver_blogs(self):
        with _serving():
            self.assertMatchesGolden(_as_dicts(naver_blogs.fetch()), EXPECTED["naver_blogs"])

    def test_foodie_tour(self):
        with _serving():
            self.assertMatchesGolden(_as_dicts(foodie_tour.fetch()), EXPECTED["foodie_tour"])

    def test_walking_tour_raw(self):
        with _serving():
            self.assertMatchesGolden(walking_tour._fetch_raw(), EXPECTED["walking_tour_raw"])


@mock.patch("sources._adapter.time.sleep", lambda s: None)  # 재시도 백오프 생략 / skip backoff waits
class ContractBehaviour(unittest.TestCase):
    """HTTPSession 계약이 주는 것 / what the HTTPSession contract adds."""

    def _run(self, fn, overrides):
        err = io.StringIO()
        with _serving(overrides) as srv, contextlib.redirect_stderr(err):
            result = fn()
        return result, err.getvalue(), srv.hits

    def test_naver_blogs_one_feed_down_is_retried_logged_and_isolated(self):
        down = "/rss/hudpr.xml"
        events, err, hits = self._run(naver_blogs.fetch, {down: (500, "text/plain", b"boom")})
        self.assertEqual(hits[down], 3, "1회 + 재시도 2회 / 1 try + 2 retries")
        self.assertIn("hudpr", err, "죽은 피드가 조용히 0건이 되면 안 된다 / a dead feed must be reported")
        self.assertFalse(any(e.raw["blog"] == "hudpr" for e in events))
        self.assertEqual(len(events), len(EXPECTED["naver_blogs"]) - 2, "다른 피드 7개는 그대로 / others unaffected")

    def test_foodie_tour_failure_is_retried_and_does_not_leak_key(self):
        events, err, hits = self._run(foodie_tour.fetch, {"/foodie_tour": (500, "text/plain", b"boom")})
        self.assertEqual(events, [])
        self.assertEqual(hits["/foodie_tour"], 3)
        self.assertIn("foodie_tour", err)
        self.assertNotIn(FAKE_KEY, err)
        self.assertNotIn(FAKE_KEY_ENCODED, err)

    def test_walking_tour_failure_is_retried_and_does_not_leak_key(self):
        items, err, hits = self._run(walking_tour._fetch_raw, {"/walking_tour": (500, "text/plain", b"boom")})
        self.assertEqual(items, [])
        self.assertEqual(hits["/walking_tour"], 3)
        self.assertIn("walking_tour", err)
        self.assertNotIn(FAKE_KEY, err)
        self.assertNotIn(FAKE_KEY_ENCODED, err)


class Redact(unittest.TestCase):
    def test_masks_secret_query_values_in_any_form(self):
        for raw, want in [
            ("for url: http://h/p?ServiceKey=Fake%2BKey%3D%3D&pageNo=1",
             "for url: http://h/p?ServiceKey=***&pageNo=1"),
            ("http://h/p?pageNo=1&serviceKey=Fake+Key==", "http://h/p?pageNo=1&serviceKey=***"),
            ("http://h/list.json?crtfc_key=abc123&corp_code=00126380",
             "http://h/list.json?crtfc_key=***&corp_code=00126380"),
            ("https://h/x?access_token=t0k3n", "https://h/x?access_token=***"),
        ]:
            self.assertEqual(redact(raw), want)

    def test_leaves_ordinary_params_alone(self):
        s = "http://h/search?keyword=부산&pageNo=2&numOfRows=100"
        self.assertEqual(redact(s), s)


if __name__ == "__main__":
    unittest.main()
