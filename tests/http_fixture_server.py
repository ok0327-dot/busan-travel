"""녹화된 HTTP 응답을 재생하는 로컬 서버 — 네트워크 0, 비용 0.

Replays recorded responses on 127.0.0.1 so an adapter's *real* HTTP stack
(requests / feedparser / HTTPSession) runs end-to-end against byte-identical input.

    with FixtureServer({"/rss/a.xml": (200, "text/xml;charset=UTF-8", body)}) as srv:
        srv.url("/rss/a.xml")   # → http://127.0.0.1:<port>/rss/a.xml
        srv.hits["/rss/a.xml"]  # 호출 횟수 (쿼리스트링 제외) / hit count, query ignored

⚠️ 서버가 떠 있는 동안 NO_PROXY 에 127.0.0.1 을 넣는다. HTTP_PROXY 가 걸린 셸(예: 폰 테더링
   프록시 전용 망)에서는 requests·urllib 이 127.0.0.1:<임의포트> 요청까지 프록시로 보내
   "Remote end closed connection" 으로 죽는다. CI 처럼 프록시가 없으면 아무 영향 없다.
   / Adds 127.0.0.1 to NO_PROXY while serving; otherwise a proxied shell routes local requests away.
"""
from __future__ import annotations

import contextlib
import os
import socket
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


@contextlib.contextmanager
def local_no_proxy():
    """이 블록 동안 127.0.0.1 을 프록시 예외로 / bypass HTTP_PROXY for 127.0.0.1 inside the block."""
    saved = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    for k in saved:
        os.environ[k] = ",".join(filter(None, ["127.0.0.1", os.environ.get(k)]))
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def dead_local_url(path: str = "/") -> str:
    """아무도 듣지 않는 127.0.0.1 포트 — 연결이 즉시 거부된다(ConnectionError), 네트워크 0.
    / a closed local port: connections are refused immediately."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}{path}"


class FixtureServer:
    def __init__(self, routes: dict[str, tuple[int, str, bytes]]):
        self.routes = routes
        self.hits: Counter[str] = Counter()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                path = urlsplit(self.path).path
                outer.hits[path] += 1
                status, ctype, body = outer.routes.get(path, (404, "text/plain", b"no fixture"))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # 테스트 출력 조용히 / keep test output quiet
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}{path}"

    def __enter__(self) -> "FixtureServer":
        self._no_proxy = local_no_proxy()
        self._no_proxy.__enter__()
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._no_proxy.__exit__(None, None, None)
