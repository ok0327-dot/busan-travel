"""한국 사이트 봇 차단 우회용 표준 HTTP 헤더.

문제: 한국 정부/문화 사이트 WAF 가 "bot" 문자열 + 외국 IP 조합 차단.
→ moca_busan / dureraum / dabom / art_busan / festivalbusan 등 cron 환경에서 0건 fetch.

해결: 실제 Chrome 브라우저 fingerprint + ko-KR Accept-Language.
모든 스크래퍼 어댑터는 `from sources._http import DEFAULT_HEADERS` 사용.
"""
from __future__ import annotations

# 실제 Chrome (Linux) — 한국 사이트 WAF 와 호환
UA_BROWSER = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": UA_BROWSER,
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}
