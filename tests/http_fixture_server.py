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

import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


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
        self._saved_env = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
        for k in self._saved_env:
            os.environ[k] = ",".join(filter(None, ["127.0.0.1", os.environ.get(k)]))
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
