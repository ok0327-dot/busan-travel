"""Endpoints and region codes for Busan event sources."""
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "events.db"
REPORT_DIR = ROOT / "reports"

BUSAN_FESTIVAL_ENDPOINT = "http://apis.data.go.kr/6260000/FestivalService/getFestivalKr"

KOPIS_ENDPOINT = "http://kopis.or.kr/openApi/restful/pblprfr"
KOPIS_BUSAN_SIGNGU = "28"

TOUR_API_ENDPOINT = "https://apis.data.go.kr/B551011/KorService2/searchFestival2"
TOUR_BUSAN_AREA = "6"

YES24_AJAX_ENDPOINT = "https://ticket.yes24.com/New/Recommend/Ajax/axAreaList.aspx"
YES24_BUSAN_AREA = "4"

VISITBUSAN_BASE = "https://www.visitbusan.net"
BSCF_BASE = "https://www.bscf.or.kr"

KOOKJE_RSS = "http://www.kookje.co.kr/news2011/rss/newslist05.xml"
NAVER_NEWS_RSS = "https://rss.search.naver.com/news.xml?query=%EB%B6%80%EC%82%B0+%EC%B6%95%EC%A0%9C"

# Official Naver blogs (id → human label). RSS: rss.blog.naver.com/{id}.xml
NAVER_OFFICIAL_BLOGS = [
    ("cooolbusan", "Busan City"),        # 부산광역시 공식 — 하루 1~2건
    ("bscf2009",   "Busan Culture Fdn"), # 부산문화재단 — 행사/축제 카테고리
    ("hudpr",      "Haeundae-gu"),       # 해운대구 — 지역 행사 직보
]
