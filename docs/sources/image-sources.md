# 부산 관광 이미지 source 매트릭스

> **Step 5.1** — 본 문서는 Step 5 (관광공사 royalty-free 이미지 수집) 의 plan-of-record.
> Hybrid 전략 (KTO 1,200 + 부산 archive 800 = Phase A 2,000) 의 결정 근거 + 라이센스 enforce 기준 + 자동화 의사 코드.
>
> **작성**: 2026-05-02 / **상태**: 정찰 완료, Step 5.2 수집 파이프라인 진입 직전

---

## 1. Hybrid 전략 — 두 source 의 강점 보완적

| 항목 | KTO Photo Korea (1차) | 부산 archive (2차) |
|---|---|---|
| **URL** | https://phoko.visitkorea.or.kr | https://archive.visitbusan.net |
| **CDN** | https://conlab.visitkorea.or.kr/api/depot/public/depot-flow/query/download-image/{uuid}/it22 | https://www.visitbusan.net/upload/{date-path}/{타임스탬프}_{크기}.png |
| **부산 콘텐츠 규모 (전체)** | **4,181건** (전국 안에서 부산 부분, `allRegnCd=23`) | **13,876건** (이미지만, 부산 100%) |
| **사용 가능 풀 (라이센스 필터 후)** | 4,181 (KTO 1유형 다수 가정) | **10,680건** (실측 1유형만 — 77%) ⭐ |
| **자동화 마찰** | ✅ 익명 GET (회원가입 우회, CDN public path) | POST 폼 (사용목적/사용처 명시) |
| **원본 해상도** | ✅ 18 MB 4K (`it22` 또는 그 외 suffix → fallback default) | mixed (일부 17 MB+ 확인) |
| **퀄리티** | ✅ 공식 큐레이션 (시적 제목, 공식 사진작가) | mixed (시민사진기자 다수) |
| **메타 풍부도** | ❌ 제목 위주 (촬영자·촬영일은 detail 페이지) | ✅ 풍부 (제목·촬영자·발행자·**주소**·카테고리 3계층·태그) |
| **POI 자동 매핑** | ❌ 위치 메타 빈약 → 시각 매칭 필요 | ✅ 주소 → 1300+ POI 직접 매핑 강함 |
| **라이센스** | 공공누리 1~4 mixed | **공공누리 1유형 only** (실측: 1유형 77% / 2유형 5% / 3유형 0.4% / 4유형 19%) |
| **robots.txt** | ✅ `Disallow: /*search*` 만 (CDN 허용) | 미발견 (관례상 default 허용) |
| **Phase A 큐레이션 size** | 1,200 (4,181 의 29%) | 800 (10,680 의 7.5%) |

### 활용 분장 — Phase A (총 2,000장)

```
KTO 1,200장 — 글 발행 시 자동 매칭 주력
  ✓ 공식 퀄리티 → HERO/PW 인페인트 base 안전
  ✓ 익명 GET → 발행 자동화 매끄럼
  ✓ 시적 제목 → 의미 검색(임베딩) 매칭 정확
  ✓ 4,181 중 29% → 운영 절제 + 라이센스 sampling 신뢰도 충분

부산 archive 800장 — POI 매핑 + KTO 약점 보충
  ✓ 정확한 주소 → POI ID 자동 매핑 (글에서 POI 언급 시 즉시 사진 추천)
  ✓ 카테고리 3계층 → 음식·시장 등 KTO 약한 영역 보충
  ✓ 시민기자 사진 → 로컬 분위기 (KTO 의 공식 톤 보완)
  ✓ 13,876 중 6% → 매우 절제 (사이트 부담 minimum)
```

### 단계 확장 전략

```
Phase A — 시작 풀 2,000장 (이번 Step 5.2)
  KTO 1,200 + archive 800 / R2 ~$0.20/월 / 수집 ~24분
  글 발행 다양성 160~250 글까지 중복 없음

Phase B — 글 발행 운영 후 확장 (~6개월 후) → 4,000장
  실제 use case 검증 후 부족 카테고리/지역 정밀 보충
  KTO 2,400 + archive 1,600 / R2 ~$0.40/월

Phase C — 마이크로사이트 6동 라이브 후 → 6,000~8,000장
  트래픽 검증 후 본격 풍부 풀
  R2 ~$0.60~0.80/월
```

**단계 확장의 가치**: 한 번에 5K+ 다 모으는 것보다 (a) 큐레이션 부담 분산, (b) 실제 use case 본 후 정밀 보충, (c) 풀이 너무 크면 검색 noise — 천천히 정제 가능.

---

## 2. 라이센스 × 4-tier 매트릭스 (코드 enforce 기준)

```
공공누리 제1유형: 출처표시 / ✅ 영리 / ✅ 변형
공공누리 제2/3/4유형 + 자유이용불가: SKIP
  — 제3유형은 RAW tier 만 사용 가능하나 archive 실측 60건뿐(0.4%)
    → 코드 단순화 위해 무시. 부산 archive 운영 결정 (2026-05-02)
```

### 단일 라이센스 적용 — 1유형 only

| Tier | 변형 정도 | KOGL-1 | 비고 |
|---|---|---|---|
| **HERO** (char_I 40~60% 인페인트) | 큰 변형 | ✅ | 인페인트 input |
| **PW** (char_I 5~15% 인페인트) | 변형 있음 | ✅ | 인페인트 input |
| **DETAIL** (음식·소품 크롭) | 크롭 | ✅ | 크롭/리사이즈 OK |
| **RAW** (그대로 게시) | 변형 0 | ✅ | 출처 표기 |

→ R2 customMetadata 의 `allowed_tiers` 는 사실상 항상 `"HERO,PW,DETAIL,RAW"`. 코드 enforce 단순화.

### 코드 enforce — R2 customMetadata `allowed_tiers` 자동 가드

```python
# 인페인트 파이프라인 안전장치
def select_inpaint_base(tier: str, area: str = None) -> R2Object:
    candidates = vectorize.query(
        prompt,
        filter={
            "allowed_tiers__contains": tier,    # license enforce
            "gugun": area,                       # 메타 필터
        }
    )
    # KOGL-3 자료가 HERO 인페인트 input 으로 들어가는 사고 자동 차단
    return candidates[0]
```

---

## 3. 자동화 메커니즘 — 의사 코드

### 3.1 KTO 수집 파이프라인 (1차 source)

```python
# 1. List 크롤
GET https://phoko.visitkorea.or.kr/media/mediaList.kto?allRegnCd=23&page=N
  → BeautifulSoup
  → 각 카드에서 UUID + 제목 추출
    UUID 패턴: 8-4-4-4-12 (UUID4)
    예: 6epjys8y-wbrc-ibct-af6m-unsg8mbyoox

# 2. Detail 크롤 (촬영자·촬영일·라이센스 정확값)
GET https://phoko.visitkorea.or.kr/media/mediaView.kto?galleryNo={N}
  → 메타 추출: 촬영자, 촬영일, 카테고리, 라이센스 유형

# 3. 이미지 GET (익명, 18MB 원본)
GET https://conlab.visitkorea.or.kr/api/depot/public/depot-flow/query/download-image/{uuid}/it22
  Headers:
    User-Agent: busan-travel-archive-collector/1.0 (+https://busan-travel.dk0327.workers.dev)
  → status 200, content-type: image/jpeg, ~18MB

# 4. R2 업로드 + customMetadata
PUT R2 key: busan-archive/kto/{uuid}.jpg
  customMetadata:
    source: "kto"
    source_id: "{uuid}"
    license_type: "kogl-1" | "kogl-3"
    allowed_tiers: "HERO,PW,DETAIL,RAW" | "RAW"
    attribution: "©한국관광공사 포토코리아 - {촬영자명}"
    title: "{시적 제목}"
    category: "{카테고리}"
    width: int
    height: int
    archived_at: ISO8601

# 5. Rate limit
time.sleep(0.5)  # ≤ 2 RPS
```

### 3.2 부산 archive 수집 파이프라인 (2차 source, POI 매핑)

```python
# 1. List 크롤 (POST 폼 — JS filter 우회)
POST https://archive.visitbusan.net/dataSearch/list.nm
  data: {
    menuCd: 34,
    dataCdList: 202,                    # 이미지
    copyrightLicenseList: "1",          # 제1유형 우선 (3유형은 RAW 만)
    perPageNum: 60,
    page: N,
    gugunCdList: "{구군코드}",          # 16개 구군 순회
    tourTypeFirstCd: "{관광유형}",      # 자연/역사/체험/문화/축제/음식/숙박/쇼핑/레져
  }
  → BeautifulSoup
  → dataSid 추출 (METADATA######)

# 2. Detail 크롤 (풍부 메타)
GET /dataSearch/view.nm?dataSid={dataSid}&menuCd=36
  → 추출:
    - 제목, 촬영자, 발행자
    - 주소 (POI 매핑용)
    - 카테고리 3계층 (자연 > 자연경관 > 해변,해수욕장)
    - 태그
    - 라이센스 유형
    - 이미지 직접 URL: visitbusan.net/upload/{년}/{월}/{일}/{타임스탬프}_{크기}.png

# 3. 이미지 다운로드 (POST 폼)
POST {다운로드 폼 action}
  data: {
    사용목적: "홈페이지",
    사용처: "일반기업",
    dataSid: "{dataSid}",
  }
  → 또는 직접 GET 이미지 URL (page 노출된 _m suffix or 원본)

# 4. R2 업로드 + customMetadata
PUT R2 key: busan-archive/visitbusan/{dataSid}.jpg
  customMetadata:
    source: "visitbusan-archive"
    source_id: "{dataSid}"
    license_type: "kogl-1" | "kogl-3"
    allowed_tiers: "HERO,PW,DETAIL,RAW" | "RAW"
    attribution: "©부산광역시 / {촬영자명}"
    gugun: "{수영구|해운대구|...}"     # POI 매핑 키
    poi_ref: int | null                 # 1300+ POI 자동 매핑 결과
    category_l1: "자연"
    category_l2: "자연경관"
    category_l3: "해변,해수욕장"
    tags: "광안리,해수욕장"
    width: int
    height: int
    archived_at: ISO8601

# 5. Rate limit
time.sleep(1.0)  # ≤ 1 RPS (KTO 보다 보수)
```

### 3.3 POI 자동 매핑 (부산 archive 의 강점 활용)

```python
# 부산 archive 의 주소 필드 → 1300+ POI 매칭
def match_poi(address: str, category: str) -> int | None:
    # 1. 정확 매칭 (POI title 부분 일치)
    # 2. gugun + category 조합 매칭
    # 3. lat/lon 근접 매칭 (Kakao geocoding 활용)
    # 4. 신뢰 임계 미만이면 None (수동 큐레이션 단계로 이관)
    pass
```

---

## 4. 출처 표기 템플릿

### 4.1 글 footer 일괄 표기

```markdown
---

### 사진 출처

본 글의 사진은 공공누리 제1유형 라이센스로 제공되는 다음 출처를 사용합니다:
- ©한국관광공사 포토코리아 - {KTO 사진별 촬영자명 리스트}
- ©부산광역시 / {부산 archive 촬영자명 리스트}

원본은 [한국관광공사 포토코리아](https://phoko.visitkorea.or.kr) 및 [부산관광아카이브](https://archive.visitbusan.net) 에서 무료로 다운로드할 수 있습니다.
```

### 4.2 사진 캡션별 표기 (호버/모달 옵션)

```html
<figcaption>
  {제목}
  <small>©{출처} - {촬영자명}</small>
</figcaption>
```

### 4.3 frontmatter / 글 메타

```yaml
images:
  - r2_key: "busan-archive/kto/6epjys8y-wbrc-ibct-af6m-unsg8mbyoox.jpg"
    tier: "HERO"
    credit: "kto:phoko/6epjys8y..."
  - r2_key: "busan-archive/visitbusan/METADATA006340.jpg"
    tier: "RAW"
    credit: "visitbusan-archive/METADATA006340"
```

---

## 5. 약관 방어선 (자동화 절제)

> 익명 GET 가능하다고 무한 다운로드 X — 약관의 정신 존중 + sustainable 운영.

| 항목 | 값 | 이유 |
|---|---|---|
| **Phase A 큐레이션 size** | KTO 1,200 / 부산 archive 800 (총 2,000) | KTO 의 4,181 중 29%, 부산 archive 의 13K 중 6% — 운영 절제 + 사이트 부담 minimum |
| **Rate limit (KTO)** | ≤ 2 RPS | 회원가입 우회 점에서 보수적 |
| **Rate limit (archive)** | ≤ 1 RPS | POST 폼 부담 |
| **User-Agent** | `busan-travel-archive-collector/1.0 (+https://busan-travel.dk0327.workers.dev)` | 식별 + 차단 시 빠른 대응 |
| **출처 표기** | 글마다 사진 캡션 + footer 일괄 + frontmatter credit 필드 | 공공누리 1유형 의무 |
| **License 모니터** | R2 customMetadata 의 license_type 분포 dashboard | 사고 방지 |
| **Crawl 시간대** | KST 새벽 02-05 (off-peak) | 사이트 트래픽 영향 최소화 |
| **재수집 주기** | 분기 1회 (변경 자료만) | 무 의미한 fetch 회피 |

---

## 6. R2 + Vectorize 메타 schema

### 6.1 R2 키/메타 구조

```
busan-archive/
  kto/
    {uuid}.jpg              # Phase A: 1,200 KTO 큐레이션 이미지
  visitbusan/
    {dataSid}.jpg           # Phase A: 800 부산 archive 큐레이션
```

각 객체의 `customMetadata` (key-value, R2 max 4KB):

```yaml
source: "kto" | "visitbusan-archive"
source_id: "{uuid}" or "{dataSid}"
license_type: "kogl-1" | "kogl-3"
allowed_tiers: "HERO,PW,DETAIL,RAW" | "RAW"
attribution: "©한국관광공사 포토코리아 - 김XX"
title: "다대포 일몰"
gugun: "사하구"  # KTO 는 null, archive 는 정확값
poi_ref: "12345"  # int as string (R2 metadata 는 string 만)
category_l1: "자연"
category_l2: "자연경관"
category_l3: "해변,해수욕장"
tags: "다대포,일몰,해변"
width: "4032"
height: "3024"
archived_at: "2026-05-02T01:00:00Z"
```

### 6.2 Vectorize index

```yaml
name: "busan-archive-meta"
dimensions: 1024  # BGE-M3 출력
metric: cosine
embedding_source: "{title} {category_l1} {category_l2} {category_l3} {gugun} {tags} {attribution}"
embedding_model: "@cf/baai/bge-m3"  # Cloudflare Workers AI, multilingual

filter_metadata:  # vectorize.query() filter 가능 필드
  - source        # "kto" | "visitbusan-archive"
  - license_type  # "kogl-1" | "kogl-3"
  - allowed_tiers # 문자열 매칭
  - gugun         # "수영구" 등
  - category_l1   # "자연" 등
  - poi_ref       # POI ID 매칭

vector_metadata:  # 벡터 자체에 attach (검색 결과에 함께 반환)
  - r2_key        # "busan-archive/kto/{uuid}.jpg"
  - title
  - attribution
```

### 6.3 검색 use case 예시

```python
# 글 자동 발행 — scene 추출 후 자동 사진 추천
prompt = "황혼에 물든 광안대교 wide shot"
results = vectorize.query(
    embed(prompt),
    filter={
        "license_type": {"$in": ["kogl-1"]},
        "allowed_tiers__contains": "HERO",  # 인페인트 input 가능
    },
    top_k=5,
)
# → 광안대교 + 황혼 분위기 사진 5장 반환 (KOGL-3 자료 자동 제외)
```

---

## 7. 의사결정 이력 (정찰 결과 요약)

### 정찰 1차 (2026-05-02)

| 가설 | 검증 결과 |
|---|---|
| 제3유형 분포 적을 가능성 | ⚠️ JS filter 직접 측정 실패. 큐레이션 단계에서 실측 (Step 5.5) |
| KTO 퀄리티 우위 | ✅ 확인 (시적 제목 + 4계절 + 다양 카테고리) |

### 정찰 2차 (parameter 발견)

부산 archive form fields 추출:
- `copyrightLicenseList` — 라이센스 필터
- `dataCdList`, `gugunCdList`, `tourTypeFirstCd/Second/Third`
- `page`, `perPageNum`
- method=POST, action=`/dataSearch/list.nm`

### 정찰 3차 (KTO CDN 검증) ⭐

| 시도 | 결과 |
|---|---|
| `it11` | 200 / 55 KB / image/jpeg (썸네일) |
| `it22` | 200 / **18.4 MB** / image/jpeg (**원본 4K**) |
| `it33`, `it44`, `original`, `full`, `raw`, `high` 등 | 200 / **18.4 MB** (default fallback to original) |

→ **익명 GET 으로 18MB 원본 직접 다운로드 가능**. 회원가입 UI 는 detail page 의 신청서 단계에만 적용.

### 정찰 4차 (약관/robots.txt)

- KTO `robots.txt`: `Disallow: /*search*` 만 (CDN 허용)
- conlab CDN `robots.txt`: 404 (관례상 default 허용)
- 공공누리 제1유형 약관 표준 적용 가능 (출처표시 + 영리 + 변형 OK)

### 정찰 5차 (부산 archive 라이센스 분포 실측) ⭐

방법: POST + `last_page × perPageNum=60` 카운팅 (HTML 카운트 텍스트 노출 안 됨, 페이지네이션 fn_page() 의 마지막 page index 활용).

| 라이센스 | 실측 카운트 | 비율 | 우리 사용 |
|---|---|---|---|
| **제1유형** | **~10,680** | **77%** | ✅ 모든 tier |
| 제2유형 | ~660 | 5% | SKIP |
| 제3유형 | **~60** | **0.4%** | SKIP (사용자 통찰 정확 — 가설 30% 였음, 실측 70배 차이) |
| 제4유형 | ~2,580 | 19% | SKIP |
| 합계 | ~13,980 | (baseline 13,876 와 거의 일치) | |

**의사결정**: archive 는 1유형 10,680건만 큐레이션 source pool. 3유형 60건은 코드 단순화를 위해 무시. 사용자 통찰의 ROI 매우 높았음 — 가설로 진행했다면 임베딩 인덱스 + 메타 schema 모두 잘못된 분포 값으로 채워졌을 것.

### 결정 매트릭스 — 정찰 전후 우선순위 반전

```
[정찰 전 가설]
1차: 부산 archive (자동화 가능, 13K)
2차: KTO (마찰 큼, 수동 보충)

[정찰 후 실측]
1차: KTO Photo Korea ⭐ — 공식 큐레이션 + 4,181건 + 익명 GET + 18MB 원본 + 시적 제목
2차: 부산 archive — 1유형 10,680건 (실측, 77%) + 메타 풍부 (POI 매핑 강함)
Hybrid Phase A: KTO 1,200 + archive 800 (= 2,000)
큐레이션 source pool: KTO 4,181 + archive 1유형 10,680 = 14,861
```

---

## 8. 다음 단계 — Step 5.2 수집 파이프라인 작업 분해

| 하위 작업 | 산출물 | Effort |
|---|---|---|
| **5.2a** KTO list 크롤러 | scripts/sources/kto_list.py — `allRegnCd=23` 페이지네이션 → UUID + 제목 list | 1d |
| **5.2b** KTO detail 크롤러 | scripts/sources/kto_detail.py — 메타 (촬영자/카테고리/라이센스) 추출 | 1d |
| **5.2c** KTO 이미지 GET → R2 | scripts/sources/kto_fetch.py — `it22` GET + customMetadata 박음 + rate limit | 1d |
| **5.2d** 부산 archive list+detail 크롤러 | scripts/sources/visitbusan_archive_list.py — POST 폼 + dataSid 추출 + 메타 | 1.5d |
| **5.2e** 부산 archive 다운로드 폼 자동화 | scripts/sources/visitbusan_archive_fetch.py — 사용목적/사용처 폼 + 이미지 GET | 1d |
| **5.2f** 메타 통합 store | data/sources.db (SQLite) — 두 source 메타 + R2 키 매핑 | 0.5d |
| **5.2g** 라이센스 enforce 가드 | scripts/sources/license_lint.py — R2 customMetadata 정합성 체크 | 0.5d |
| **5.2h** Vectorize 임베딩 | scripts/sources/embed_meta.py — BGE-M3 → Vectorize index 적재 | 1d |
| **5.2i** POI 자동 매핑 | scripts/sources/poi_match.py — 부산 archive 주소 → POI ID | 1d |

**합계 예상 작업량**: ~9일 (부분 시간 작업 가정)

### 5.2 진입 시 첫 작업

5.2a (KTO list 크롤러) 부터 시작 — 가장 가벼움 + 즉시 검증 가능 (10건 PoC).

---

## 9. 관련 문서

- `BUSAN_UNIFICATION_PLAN.md` — Step 5 마스터 플랜
- `~/.claude/projects/-home-kang-my-playground/memory/plan_busan_tourism_unification.md` — 결정 이력
- `~/.claude/projects/-home-kang-my-playground/memory/busan_travel_image_url_pattern.md` — visitbusan 기존 이미지 URL 패턴 (cntnts/{17자리ID}, archive 의 upload/{date}/{타임스탬프}_{크기}.png 패턴 추가 필요)
- `docs/api/openapi.yaml` — 현재 read API spec (Step 5 후 자산 검색 endpoint 추가 예정)
