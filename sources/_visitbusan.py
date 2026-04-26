"""VisitBusan.net 공통 HTTP 클라이언트 + HTML 파서.

정책 / Policy:
- 공식 부산관광포털에서 **사실 데이터만** 흡수 (좌표/주소/시간/요금/태그/평점).
- 본문 스토리는 1~2문장 발췌(story_excerpt)만 저장, 본문 full body 는 미저장.
- 디테일 페이지 deep-link(story_url) 필수 제공 → 원문 트래픽 보호.
- robots.txt 전체 허용이지만 정중한 rate limit 필수 (기본 0.5초/req).
- User-Agent 에 대시보드 URL 명시 (identifiable bot).

사용:
    from sources._visitbusan import VisitBusanClient, parse_list_page, parse_detail_page

    c = VisitBusanClient()
    soup = c.get_soup("/index.do", {"menuCd": "DOM_000000201001000000", "currentPage": 1, "listCntPerPage2": 100})
    items = parse_list_page(soup)
    for it in items:
        d_soup = c.get_soup("/kr/index.do", {"menuCd": "...001000", "uc_seq": it["uc_seq"], "lang_cd": "ko"})
        detail = parse_detail_page(d_soup, it["uc_seq"])
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE = "https://www.visitbusan.net"
UA = "BusanTravelDashboard/1.0 (+https://busan-travel.dk0327.workers.dev)"
DEFAULT_TIMEOUT = 20
DEFAULT_RATE_S = 0.5
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / ".vb_cache"

# ─────────── HTTP 클라이언트 ───────────


class VisitBusanClient:
    def __init__(self, rate_limit_s: float = DEFAULT_RATE_S, cache: bool = True):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.session.headers["Accept-Language"] = "ko-KR,ko;q=0.9,en;q=0.8"
        self.rate_limit_s = rate_limit_s
        self._last_t = 0.0
        self.cache = cache
        if cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self):
        dt = time.monotonic() - self._last_t
        if dt < self.rate_limit_s:
            time.sleep(self.rate_limit_s - dt)
        self._last_t = time.monotonic()

    def _cache_path(self, path: str, params: dict) -> Path:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        h = hashlib.md5(key.encode()).hexdigest()
        return CACHE_DIR / f"{h}.html"

    def get_html(self, path: str, params: dict | None = None) -> str:
        params = params or {}
        if self.cache:
            cp = self._cache_path(path, params)
            if cp.exists():
                return cp.read_text(encoding="utf-8")
        self._rate_limit()
        url = BASE + path if path.startswith("/") else path
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
                if r.status_code == 200 and r.text:
                    html = r.text
                    if self.cache:
                        self._cache_path(path, params).write_text(html, encoding="utf-8")
                    return html
                if r.status_code in (500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Unreachable: {url} {params}")

    def get_soup(self, path: str, params: dict | None = None) -> BeautifulSoup:
        return BeautifulSoup(self.get_html(path, params), "lxml")


# ─────────── 파서 ───────────

_UC_SEQ_RE = re.compile(r"uc_seq=(\d+)")
_LAT_RE = re.compile(r"lat\s*=\s*(\d+\.\d+)")
_LNG_RE = re.compile(r"lng\s*=\s*(\d+\.\d+)")
_RATING_RE = re.compile(r"평점\s*([\d.]+)")
_VIEW_RE = re.compile(r"조회\s*([\d,]+)")
_REVIEW_RE = re.compile(r"리뷰\s*(\d+)")
_LIKE_RE = re.compile(r"좋아요\s*\(?\s*(\d+)")
_TOTAL_RE = re.compile(r"총\s*\(?\s*전체\s*\)?[\s\n]*(\d+)\s*건")
_TAG_RE = re.compile(r"#([\w\dㄱ-힣·&]+)")


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def extract_uc_seq(href: str | None) -> int | None:
    if not href:
        return None
    m = _UC_SEQ_RE.search(href)
    return int(m.group(1)) if m else None


def extract_latlng(html: str) -> tuple[float | None, float | None]:
    lat_m = _LAT_RE.search(html)
    lng_m = _LNG_RE.search(html)
    if not (lat_m and lng_m):
        return None, None
    try:
        return float(lat_m.group(1)), float(lng_m.group(1))
    except ValueError:
        return None, None


def total_count(html_or_text: str) -> int | None:
    # Normalize whitespace to make the regex resilient to inline linebreaks
    normalized = re.sub(r"\s+", " ", html_or_text)
    m = _TOTAL_RE.search(normalized)
    return int(m.group(1)) if m else None


def parse_list_page(soup: BeautifulSoup) -> list[dict]:
    """명소/음식/축제 리스트 페이지에서 {uc_seq, title, image_url, href, view_count} 추출.

    uc_seq 가 있는 a 를 앵커로 각 카드 추출 (페이지네이션 a 는 ucl_seq 등만 있고 uc_seq 없음 → 자연 배제).
    """
    items: list[dict] = []
    seen: set[int] = set()
    for a in soup.select('a[href*="uc_seq="]'):
        uc = extract_uc_seq(a.get("href") or "")
        if not uc or uc in seen:
            continue
        # 썸네일 이미지 alt 에 title 이 있음 (list_type=TYPE_SMALL_CARD)
        img_el = a.select_one("img[alt]")
        title = None
        image_url = None
        if img_el:
            title = _clean(img_el.get("alt"))
            image_url = img_el.get("src") or img_el.get("data-src")
            if image_url and image_url.startswith("/"):
                image_url = BASE + image_url
        # fallback: 앵커 텍스트 또는 부모 카드에서
        if not title:
            t = _clean(a.get_text(" ", strip=True))
            if t and len(t) >= 2 and not t.startswith(("http", "/")):
                title = t
        if not title:
            card = a.find_parent(["li", "div"])
            if card:
                title_el = card.select_one("strong, p.title, .title, h3, h4")
                if title_el:
                    title = _clean(title_el.get_text(" ", strip=True))
        # 목록 페이지네이션의 uc_seqs= (복수) 링크를 걸러냄 — 제목도 없고 uc_seq 추출도 안 됨
        if not title:
            continue
        seen.add(uc)
        items.append({
            "uc_seq": uc,
            "title": title,
            "image_url": image_url,
            "href": a.get("href"),
        })
    return items


def _extract_info_block(text: str) -> dict[str, str | None]:
    """이용안내 라벨 블록을 텍스트 기반으로 파싱.

    패턴: 라벨 줄 + 다음 줄들이 값. 다음 라벨이 나올 때까지.
    """
    labels = [
        "주소", "전화번호", "홈페이지", "휴무일", "운영요일 및 시간",
        "이용요금", "교통정보", "여행꿀팁", "여행 에티켓", "여행에티켓",
    ]
    # 알고리즘: text 를 줄 단위로, 라벨로 시작하는 줄을 찾으면 그 뒤 다음 라벨 전까지의 줄을 값으로
    lines = [ln.strip() for ln in text.split("\n")]
    result: dict[str, str | None] = {lbl: None for lbl in labels}
    label_set = set(labels)
    i = 0
    while i < len(lines):
        if lines[i] in label_set:
            label = lines[i]
            j = i + 1
            buf = []
            while j < len(lines) and lines[j] not in label_set and lines[j] not in ("연관태그", "추천여행지", "관련여행지"):
                if lines[j]:
                    buf.append(lines[j])
                j += 1
            if buf:
                result[label] = " ".join(buf).strip()[:500]
            i = j
        else:
            i += 1
    # 정규화
    result["etiquette"] = result.pop("여행 에티켓") or result.pop("여행에티켓")
    result["hours"] = result.pop("운영요일 및 시간")
    result["tip"] = result.pop("여행꿀팁")
    result["address"] = result.pop("주소")
    result["phone"] = result.pop("전화번호")
    result["homepage"] = result.pop("홈페이지")
    result["holiday"] = result.pop("휴무일")
    result["fee"] = result.pop("이용요금")
    result["transport"] = result.pop("교통정보")
    return result


def _extract_content_tags(text: str) -> list[str]:
    """본문 말미 '연관태그' 블록의 태그만 추출 (사이드바 전역 태그 배제)."""
    m = re.search(r"연관태그\s*(.+?)(?:추천여행지|관련여행지|\Z)", text, re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    tags = _TAG_RE.findall(block)
    # dedupe keep order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:30]


_INFO_SENTINEL_RE = re.compile(r"(이용안내|이용정보|찾아오시는 길)")
_NAV_BOILERPLATE = (
    "본문 바로가기", "추천여행", "부산에가면", "부산시 공식",
    "Visit Busan", "찜하기", "좋아요", "상세정보", "지도/주변관광지",
    "여행사진", "리뷰", "블로그리뷰", "평점", "조회",
)


def _extract_story_excerpt(soup: BeautifulSoup) -> str | None:
    """title~'이용안내' 사이의 첫 유의미 문장 1~2개 발췌 (저작권 안전).

    본문 전체 저장 금지 — 발췌는 법적 fair-use + 미리보기 목적.
    """
    text = soup.get_text("\n", strip=True)
    # 문장 단위로 분리 후 필터
    # '이용안내' 이후는 자르기
    cut = _INFO_SENTINEL_RE.search(text)
    if cut:
        text = text[: cut.start()]
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # 50자 이상 + 보일러플레이트 아닌 첫 줄을 서사 본문으로 간주
    for ln in lines:
        if len(ln) < 50:
            continue
        if any(b in ln for b in _NAV_BOILERPLATE):
            continue
        if ln.startswith(("주소", "전화", "홈페이지", "휴무", "운영", "이용", "Copyright")):
            continue
        sentences = re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=요\.)\s+|(?<=자!)\s+", ln)
        excerpt = " ".join(sentences[:2])[:200]
        return excerpt
    return None


def parse_detail_page(soup: BeautifulSoup, uc_seq: int, menu_cd: str) -> dict[str, Any]:
    """디테일 페이지 → 구조화된 dict.

    반환:
        {
          uc_seq, title, subtitle,
          lat, lon,
          address, phone, homepage, holiday, hours, fee, transport, tip, etiquette,
          tags (list[str]),
          rating (float), view_count (int), review_count (int), like_count (int),
          image_url (대표), image_urls (list),
          story_url (deep-link), story_excerpt,
        }
    """
    # Title: 디테일 페이지는 h4.tit 에 위치 (h4 또는 .tit 전부 스캔 후 네비/모달 제외)
    title = None
    for h in soup.select("h4.tit, h3.tit, h2.tit, h1.tit, .detailTit, .view_tit"):
        txt = _clean(h.get_text(" ", strip=True))
        if txt and txt not in ("인기검색어", "검색영역"):
            title = txt
            break
    # fallback: document title 에서 ":" 앞쪽만
    if not title:
        t = soup.find("title")
        if t:
            title = _clean(t.get_text())
            if title:
                title = re.sub(r"\s*[|:·].+$", "", title)

    # Subtitle
    subtitle_el = soup.select_one(".subTit, [class*=sub_tit], p.desc")
    subtitle = _clean(subtitle_el.get_text(" ", strip=True)) if subtitle_el else None

    # 좌표
    html = str(soup)
    lat, lon = extract_latlng(html)

    # 이용안내 블록
    full_text = soup.get_text("\n", strip=False)
    info = _extract_info_block(full_text)

    # 태그
    tags = _extract_content_tags(full_text)

    # 평점/조회/리뷰/좋아요
    rating_m = _RATING_RE.search(full_text)
    view_m = _VIEW_RE.search(full_text)
    review_m = _REVIEW_RE.search(full_text)
    like_m = _LIKE_RE.search(full_text)

    def _to_float(s):
        try:
            return float(s.replace(",", "")) if s else None
        except (ValueError, AttributeError):
            return None

    def _to_int(s):
        try:
            return int(s.replace(",", "")) if s else None
        except (ValueError, AttributeError):
            return None

    rating = _to_float(rating_m.group(1)) if rating_m else None
    view_count = _to_int(view_m.group(1)) if view_m else None
    review_count = _to_int(review_m.group(1)) if review_m else None
    like_count = _to_int(like_m.group(1)) if like_m else None

    # 이미지 — 디테일 페이지는 og:image 비어있고 이미지는 JS 지연 로드됨.
    # 리스트 페이지 썸네일은 호출자가 전달 → 여기서는 img[id^=imgItem] 만 수집 (id로 참조)
    image_url = None
    image_ids: list[str] = []
    for img in soup.select('img[id^="imgItem"]'):
        iid = img.get("id")
        if iid:
            image_ids.append(iid)
    image_urls: list[str] = []  # 실제 URL 은 list page 경유 또는 비워둠

    # Deep-link (정규화)
    story_url = f"{BASE}/index.do?menuCd={menu_cd}&uc_seq={uc_seq}&lang_cd=ko"

    excerpt = _extract_story_excerpt(soup)

    return {
        "uc_seq": uc_seq,
        "title": title,
        "subtitle": subtitle,
        "lat": lat,
        "lon": lon,
        "rating": rating,
        "view_count": view_count,
        "review_count": review_count,
        "like_count": like_count,
        "image_url": image_url,
        "image_urls": image_urls[:10],
        "image_ids": image_ids[:10],
        "story_url": story_url,
        "story_excerpt": excerpt,
        "tags": tags,
        **info,
    }


# ─────────── 제너릭 리스트 크롤러 ───────────


def iterate_list(
    client: VisitBusanClient,
    menu_cd: str,
    page_size: int = 16,
    max_pages: int = 40,
    extra_params: dict | None = None,
) -> list[dict]:
    """리스트 페이지 전체 순회. 반환: list of {uc_seq, title, image_url, href}.

    주의: visitbusan 서버는 실제로는 listCntPerPage2 를 무시하고 페이지당 16 고정 반환.
    페이지네이션은 URL 파라미터 `page_no=N` 사용.
    """
    all_items: list[dict] = []
    seen: set[int] = set()
    expected_total: int | None = None
    empty_streak = 0
    for page in range(1, max_pages + 1):
        params = {
            "menuCd": menu_cd,
            "page_no": page,
            "listCntPerPage2": page_size,
            "list_type": "TYPE_SMALL_CARD",
            "order_type": "NEW",
        }
        if extra_params:
            params.update(extra_params)
        soup = client.get_soup("/index.do", params)
        if expected_total is None:
            expected_total = total_count(soup.get_text(" ", strip=True))
        items = parse_list_page(soup)
        fresh = [it for it in items if it["uc_seq"] not in seen]
        if not fresh:
            empty_streak += 1
            if empty_streak >= 2:
                break
            continue
        empty_streak = 0
        for it in fresh:
            seen.add(it["uc_seq"])
        all_items.extend(fresh)
        if expected_total and len(all_items) >= expected_total:
            break
    return all_items
