// 주말부산 — Kakao Maps 기반 지도 대시보드

const cfg = window.APP_CONFIG;
if (!cfg || !cfg.KAKAO_JS_KEY) {
  alert("config.js 가 없거나 KAKAO_JS_KEY 가 비어있어요.");
  throw new Error("Missing APP_CONFIG");
}

const CATEGORIES = {
  festival:    { label: "축제",   emoji: "🎪", icon: "ph-confetti",      color: "#ef4444", letter: "축" },
  attraction:  { label: "명소",   emoji: "🏛", icon: "ph-buildings",     color: "#3b82f6", letter: "명" },  // 해변 포함
  food:        { label: "맛집",   emoji: "🍜", icon: "ph-bowl-food",     color: "#f97316", letter: "맛" },
  cafe:        { label: "카페",   emoji: "☕", icon: "ph-coffee",        color: "#a16207", letter: "카" },
  theme:       { label: "테마",   emoji: "💡", icon: "ph-compass-rose",  color: "#f59e0b", letter: "테" },
  blog:        { label: "블로그", emoji: "📝", icon: "ph-notebook",      color: "#ec4899", letter: "블" },
};

// Phosphor 아이콘 HTML helper — 카드/상세 렌더에서 이모지 대신 사용
function icon(name) {
  return `<i class="ph-bold ${name}" aria-hidden="true"></i>`;
}

const SKY_TXT = { 1: "☀️ 맑음", 3: "⛅ 구름많음", 4: "☁️ 흐림" };
const PTY_TXT = { 0: "", 1: "🌧 비", 2: "🌨 비/눈", 3: "❄️ 눈", 4: "🌦 소나기" };

const $status = document.getElementById("status");
const $list = document.getElementById("card-list");

let map;
let clusterers = {}; // category → MarkerClusterer
let allMarkers = {}; // category → [{marker, poi}]
let weatherIndex = null; // cellKey(`nx_ny`) → sorted list
let weatherOverlays = []; // CustomOverlay[] 현재 표시 중 날씨 배지
let currentTargetDate = new Date(); // 현재 선택된 날짜 (chip preset)
let coursesData = null; // courses.json
let activeCourseId = null; // 현재 활성 코스 uc_seq
let courseOverlay = { polyline: null, highlights: [] }; // 활성 코스 시각화

// ───────── SDK + 데이터 로딩 ─────────
function loadKakaoSDK() {
  return new Promise((resolve, reject) => {
    const url = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${cfg.KAKAO_JS_KEY}&libraries=clusterer,services&autoload=false`;
    const s = document.createElement("script");
    s.src = url;
    s.onload = () => {
      if (!window.kakao || !window.kakao.maps) {
        reject(new Error("Kakao SDK 스크립트는 로드됐으나 kakao.maps 네임스페이스 없음 (앱키 또는 도메인 등록 확인)"));
        return;
      }
      window.kakao.maps.load(resolve);
    };
    s.onerror = () => reject(new Error("Kakao SDK 스크립트 로드 실패 — 네트워크/도메인 등록 확인"));
    document.head.appendChild(s);
  });
}

async function fetchJson(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

// ───────── SVG 마커 생성 — 한글 단일문자 라벨 + 별표 배지 ─────────
function svgMarker(color, letter, isFavorite = false) {
  const starBadge = isFavorite
    ? `<circle cx="33" cy="7" r="7" fill="#facc15" stroke="white" stroke-width="1.5"/><text x="33" y="10.5" text-anchor="middle" font-size="9" font-weight="700" fill="white">★</text>`
    : '';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="52" viewBox="0 0 40 52">
    <path d="M20 0C9 0 0 9 0 20c0 14 20 32 20 32s20-18 20-32C40 9 31 0 20 0z" fill="${color}" stroke="white" stroke-width="2"/>
    <circle cx="20" cy="20" r="12" fill="white"/>
    <text x="20" y="25.5" text-anchor="middle" font-size="15" font-weight="700" fill="${color}" font-family="Pretendard, -apple-system, system-ui, sans-serif">${letter}</text>
    ${starBadge}
  </svg>`;
  return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
}

// 이미지 캐시 — 카테고리 × 별표여부 조합별 1회만 생성
const _markerImageCache = {};
function markerImageFor(category, isFavorite = false) {
  const key = `${category}:${isFavorite ? 1 : 0}`;
  if (!_markerImageCache[key]) {
    const cat = CATEGORIES[category] || CATEGORIES.attraction;
    _markerImageCache[key] = new kakao.maps.MarkerImage(
      svgMarker(cat.color, cat.letter || cat.emoji, isFavorite),
      new kakao.maps.Size(40, 52),
      { offset: new kakao.maps.Point(20, 52) }
    );
  }
  return _markerImageCache[key];
}

// ───────── 날씨 인덱스 빌드 ─────────
function buildWeatherIndex(weatherShort) {
  const idx = {};
  for (const [cellKey, list] of Object.entries(weatherShort.data || {})) {
    // fcst_ts 기준 정렬
    idx[cellKey] = [...list].sort((a, b) => a.ts.localeCompare(b.ts));
  }
  return idx;
}

function parseTs(ts) {
  // "20260425T15:00" → Date
  const m = ts.match(/(\d{4})(\d{2})(\d{2})T(\d{2}):?(\d{2})?/);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5] || 0));
}

function nearestForecast(nx, ny, targetDate) {
  if (!weatherIndex) return null;
  const key = `${nx}_${ny}`;
  const list = weatherIndex[key];
  if (!list || !list.length) return null;
  const target = targetDate.getTime();
  let best = null, bestDiff = Infinity;
  for (const f of list) {
    const t = parseTs(f.ts);
    if (!t) continue;
    const diff = Math.abs(t.getTime() - target);
    if (diff < bestDiff) { bestDiff = diff; best = f; }
  }
  // 2일 이상 차이면 매칭 안함
  if (bestDiff > 48 * 3600 * 1000) return null;
  return best;
}

function weatherBadge(f) {
  if (!f) return "";
  const pty = PTY_TXT[f.pty] || "";
  const sky = SKY_TXT[f.sky] || "";
  return pty || sky;
}

// ───────── 마커 렌더링 ─────────
function buildMarkerSet(items, cat) {
  const catDef = CATEGORIES[cat];
  if (!catDef) return { markers: [], clusterer: null };

  // per-POI 이미지 — 별표인 것만 배지 추가. 캐시되므로 cost 작음.
  const markers = items.map(poi => {
    const marker = new kakao.maps.Marker({
      position: new kakao.maps.LatLng(poi.lat, poi.lon),
      image: markerImageFor(cat, !!poi.is_favorite),
      title: poi.title,
    });
    kakao.maps.event.addListener(marker, "click", () => showDetail(poi));
    return { marker, poi };
  });

  const clusterer = new kakao.maps.MarkerClusterer({
    map,
    averageCenter: true,
    // Phase 2: 7→6 (더 빨리 개별 마커 표출) + 80→60 (겹친 마커 분리 쉬움)
    minLevel: 6,
    gridSize: 60,
    styles: [{
      width: "40px", height: "40px",
      background: catDef.color,
      borderRadius: "20px",
      color: "white",
      textAlign: "center",
      lineHeight: "40px",
      fontWeight: "bold",
      fontSize: "13px",
      opacity: "0.85",
    }],
  });
  return { markers, clusterer };
}

function renderMarkers(places, beaches, festivalEvents, blogMarkers = [], favorites = []) {
  // beaches → 명소(attraction) 로 병합. 수질 정보는 latest_water 로 detail 카드에 유지.
  const beachRows = (beaches.beaches || []).map(b => ({
    id: "beach:" + b.name,
    category: "attraction",
    subtype: "해변",
    title: b.name,
    lat: b.lat, lon: b.lon,
    address: "",
    latest_water: b.latest_water,
  }));

  // places + favorites (각 favorite 는 자기 실제 category 유지, is_favorite 플래그로 ★ 배지만)
  const all = [
    ...favorites,  // favorites 는 이미 category=cafe/food/attraction + is_favorite:true
    ...(places.places || []),
    ...beachRows,
    ...festivalEvents.map(e => ({ ...e, category: "festival" })),
    ...blogMarkers,  // 네이버 블로그 → category='blog'
  ];

  const byCategory = {};
  for (const p of all) {
    if (!p.lat || !p.lon) continue;
    (byCategory[p.category] ||= []).push(p);
  }

  for (const [cat, items] of Object.entries(byCategory)) {
    const { markers, clusterer } = buildMarkerSet(items, cat);
    if (clusterer) {
      clusterer.addMarkers(markers.map(m => m.marker));
      clusterers[cat] = clusterer;
      allMarkers[cat] = markers;
    }
  }
}

// ───────── 날짜 기반 축제 필터링 ─────────
function parseDate(s) {
  if (!s) return null;
  // YYYY-MM-DD
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function classifyFestival(poi, target) {
  // 반환: "active" | "upcoming" | "past" | "unknown"
  if (!poi.start) return "unknown";
  const start = parseDate(poi.start);
  if (!start) return "unknown";
  const end = parseDate(poi.end) || start;
  const t = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  if (start <= t && t <= end) return "active";
  const horizon = new Date(t); horizon.setDate(horizon.getDate() + 60);
  if (start > t && start <= horizon) return "upcoming";
  return "past";
}

function applyDateFilter(target) {
  currentTargetDate = target;
  const clusterer = clusterers.festival;

  // 지도 마커 (좌표 있는 festival 만) — opacity 조정 + past 제거
  if (clusterer) {
    const showMarkers = [];
    for (const { marker, poi } of allMarkers.festival || []) {
      const kind = classifyFestival(poi, target);
      if (kind === "active")   { showMarkers.push(marker); marker.setOpacity(1.0); }
      else if (kind === "upcoming") { showMarkers.push(marker); marker.setOpacity(0.55); }
      else if (kind === "unknown")  { showMarkers.push(marker); marker.setOpacity(0.55); }
    }
    clusterer.clear();
    clusterer.addMarkers(showMarkers);
  }

  // Phase 3: 시트·배지 카운트는 좌표 無 이벤트 포함 전체 기준 (naver_search 포함)
  const all = window.__data?.allEventPoi || [];
  let active = 0, upcoming = 0;
  for (const poi of all) {
    const kind = classifyFestival(poi, target);
    if (kind === "active") active++;
    else if (kind === "upcoming") upcoming++;
  }

  const ymd = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}-${String(target.getDate()).padStart(2, "0")}`;
  $status.textContent = `📅 ${ymd} · 진행 ${active} · 2개월내 ${upcoming}`;

  renderDateBadge(target, active, upcoming);
  const isMapView = !document.body.classList.contains("view-read") && !document.body.classList.contains("view-course");
  if (isMapView) renderTodayHighlights(target);
}

// ───────── 날씨 배지 (지도 level <= 5 에서 festival/beach 에만) ─────────
function refreshWeatherBadges(targetDate) {
  // 기존 overlay 제거
  for (const o of weatherOverlays) o.setMap(null);
  weatherOverlays = [];

  if (map.getLevel() > 5) return; // 너무 멀면 생략

  for (const cat of ["festival"]) {
    if (!clusterers[cat]) continue;
    for (const { marker, poi } of allMarkers[cat] || []) {
      if (!poi.nx || !poi.ny) continue;
      const f = nearestForecast(poi.nx, poi.ny, targetDate);
      const badge = weatherBadge(f);
      if (!badge) continue;
      const overlay = new kakao.maps.CustomOverlay({
        position: marker.getPosition(),
        content: `<div style="background:#0b1220cc;color:#fff;padding:2px 6px;border-radius:10px;font-size:11px;border:1px solid #ffffff30;transform:translate(20px,-40px);white-space:nowrap">${badge}${f.pop ? " " + f.pop + "%" : ""}</div>`,
        yAnchor: 1,
        clickable: false,
      });
      overlay.setMap(map);
      weatherOverlays.push(overlay);
    }
  }
}

// ───────── 상세 드로어 (enriched) ─────────
function renderStars(rating) {
  if (!rating) return "";
  const n = Math.round(rating);
  return `<span class="rating-stars">${"★".repeat(n)}${"☆".repeat(5 - n)}</span> <span class="card-meta">${rating.toFixed(1)}</span>`;
}

function renderTags(tags) {
  if (!tags || !tags.length) return "";
  return `<div class="tag-chips">${tags.slice(0, 8).map(t => `<span class="tag-chip">#${escape(t)}</span>`).join("")}</div>`;
}

function infoRow(label, value) {
  if (!value) return "";
  return `<div class="info-row"><strong>${label}</strong>${escape(String(value).slice(0, 300))}</div>`;
}

// P0/P2 — 이미지 태그 생성 (onerror 로 자동 숨김). URL 이 없으면 빈 문자열.
// visitbusan.net thumbL 썸네일(417×320) → Worker 프록시로 원본(최대 4K) 로드.
function busanImgUrl(url) {
  if (!url) return url;
  const m = String(url).match(/visitbusan\.net\/uploadImgs\/files\/cntnts\/(\d{14,20})(?:_thumb[LMS])?/);
  if (m) return `/img-proxy/visitbusan/${m[1]}`;
  return url;
}
function imageTag(url, cls = "card-image") {
  if (!url) return "";
  const src = busanImgUrl(url);
  return `<img class="${cls}" src="${escape(src)}" loading="lazy" decoding="async" onerror="this.style.display='none'" alt="">`;
}

function showDetail(poi) {
  const catDef = CATEGORIES[poi.category] || {};
  const isBlog = poi.category === "blog" || poi.category === "blog_post";
  const isFavorite = !!poi.is_favorite;

  // 블로그는 별도 레이아웃 — 출처·날짜 + 발췌 + 원문 보기 중심으로 명확히
  if (isBlog) {
    $list.innerHTML = renderBlogDetail(poi);
    const sheet = document.getElementById("sheet");
    if (sheet.classList.contains("sheet-peek")) sheet.classList.replace("sheet-peek", "sheet-half");
    return;
  }

  // 별표는 카테고리 색 유지하면서 골드 kicker 로 "내가 별표한 곳" 표시
  const favKicker = isFavorite
    ? `<div class="favorite-kicker">${icon("ph-star-fill")} 내가 별표한 곳${poi.subtype ? " · " + escape(poi.subtype) : ""}</div>`
    : "";
  const favNote = isFavorite && poi.note
    ? `<div class="favorite-note">💬 ${escape(poi.note)}</div>`
    : "";

  const now = new Date();
  const f = poi.nx && poi.ny ? nearestForecast(poi.nx, poi.ny, now) : null;
  const weatherLine = f
    ? `<div class="card-meta">${weatherBadge(f)} ${f.tmp ? f.tmp + "°C " : ""}${f.pop ? "POP " + f.pop + "%" : ""}</div>`
    : "";
  const dateLine = poi.start
    ? `<div class="card-meta">${icon("ph-calendar-blank")} ${poi.start}${poi.end && poi.end !== poi.start ? " ~ " + poi.end : ""}</div>`
    : "";
  const beachLine = poi.latest_water?.comment
    ? `<div class="card-meta">${icon("ph-waves")} ${escape(poi.latest_water.comment)}</div>`
    : "";
  const ratingLine = poi.rating
    ? `<div class="card-meta" style="margin-top:4px">${renderStars(poi.rating)}${poi.views ? ` · 조회 ${poi.views.toLocaleString()}` : ""}${poi.reviews ? ` · 리뷰 ${poi.reviews}` : ""}</div>`
    : "";
  const excerpt = poi.excerpt || poi.description;

  const mapLink = `https://map.kakao.com/link/to/${encodeURIComponent(poi.title)},${poi.lat},${poi.lon}`;

  $list.innerHTML = `
    <div class="card${isFavorite ? " favorite-detail" : ""}" style="border-left:3px solid ${catDef.color || "#888"}">
      ${favKicker}
      ${imageTag(poi.image)}
      <div class="card-title">${catDef.icon ? icon(catDef.icon) : (catDef.emoji || "")} ${escape(poi.title)}</div>
      ${favNote}
      <div class="card-meta">${catDef.label || poi.category}${poi.subtype ? " · " + escape(poi.subtype) : ""}${poi.address ? " · " + escape(poi.address) : ""}</div>
      ${ratingLine}
      ${dateLine}
      ${weatherLine}
      ${beachLine}
      ${excerpt ? `<div class="card-excerpt">${escape(excerpt.slice(0, 280))}</div>` : ""}
      ${renderTags(poi.tags)}
      ${infoRow(icon("ph-clock") + " 영업", poi.hours)}
      ${infoRow(icon("ph-prohibit") + " 휴무", poi.holiday)}
      ${infoRow(icon("ph-currency-krw") + " 요금", poi.fee || poi.price)}
      ${infoRow(icon("ph-bus") + " 교통", poi.transport)}
      ${infoRow(icon("ph-lightbulb") + " 팁", poi.tip)}
      ${infoRow(icon("ph-phone") + " 전화", poi.phone)}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <a href="${mapLink}" target="_blank" style="padding:6px 10px;background:#fee500;color:#000;border-radius:6px;text-decoration:none;font-size:12px">${icon("ph-map-pin")} 카카오맵 길찾기</a>
        ${poi.story_url ? `<a href="${escape(poi.story_url)}" target="_blank" style="padding:6px 10px;background:#0ea5e9;color:#fff;border-radius:6px;text-decoration:none;font-size:12px">${icon("ph-book-open")} 비짓부산</a>` : ""}
        ${poi.url && poi.url !== poi.story_url ? `<a href="${escape(poi.url)}" target="_blank" style="padding:6px 10px;background:#374151;color:#fff;border-radius:6px;text-decoration:none;font-size:12px">${icon("ph-globe")} 홈페이지</a>` : ""}
      </div>
    </div>
  `;

  // 시트 half 로 올려서 상세 보이게 (클릭 피드백 강화)
  const sheet = document.getElementById("sheet");
  if (sheet.classList.contains("sheet-peek")) {
    sheet.classList.replace("sheet-peek", "sheet-half");
  }

  // Phase 2: 펄스 오버레이로 클릭 시각 피드백 + 시트가 가리지 않도록 offset pan
  if (poi.lat && poi.lon) {
    pulseMarker(new kakao.maps.LatLng(poi.lat, poi.lon));
    panToWithSheetOffset(poi.lat, poi.lon);
  }
}

// ───────── 블로그 상세 (출처·날짜 + 발췌 + 원문 링크 중심) ─────────
function renderBlogDetail(poi) {
  const sourceLabel = formatBlogSource(poi.source);
  const dateText = poi.start || poi.end || "";
  const excerpt = poi.excerpt || poi.description || "";
  const tags = renderTags(poi.tags);
  const fullUrl = poi.url || poi.story_url;
  const blogColor = CATEGORIES.blog?.color || "#ec4899";

  const metaLine = [
    sourceLabel ? `<span>${icon("ph-notebook")} ${escape(sourceLabel)}</span>` : "",
    dateText ? `<span>${icon("ph-calendar-blank")} ${escape(dateText)}</span>` : "",
    poi.venue && !isBoilerplateVenue(poi.venue) ? `<span>${icon("ph-map-pin")} ${escape(poi.venue)}</span>` : "",
  ].filter(Boolean).join(" · ");

  return `
    <div class="card blog-detail" style="border-left:3px solid ${blogColor}">
      <div class="blog-kicker">블로그 포스트</div>
      <div class="card-title">${escape(poi.title || "(제목 없음)")}</div>
      ${metaLine ? `<div class="card-meta blog-meta">${metaLine}</div>` : ""}
      ${imageTag(poi.image)}
      ${excerpt ? `<div class="card-excerpt blog-excerpt">${escape(excerpt.slice(0, 600))}${excerpt.length > 600 ? "…" : ""}</div>` : ""}
      ${tags}
      <div class="blog-note">※ 발췌문은 네이버 블로그 원문에서 일부만 가져온 것입니다.</div>
      ${fullUrl ? `
        <div style="margin-top:12px">
          <a href="${escape(fullUrl)}" target="_blank" rel="noopener"
             style="display:inline-block;padding:10px 16px;background:${blogColor};color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px">
            ${icon("ph-arrow-square-out")} 네이버 블로그 원문 보기 →
          </a>
        </div>` : ""}
    </div>
  `;
}

function formatBlogSource(source) {
  if (!source) return "";
  const map = {
    "naver_blog:cooolbusan": "네이버 블로그 · 부산시청",
    "naver_blog:bscf2009": "네이버 블로그 · 부산문화재단",
    "naver_blog:hudpr": "네이버 블로그 · 부산관광공사",
    "naver_search:blog": "네이버 블로그 검색",
    "naver_search:news": "네이버 뉴스",
  };
  return map[source] || (source.startsWith("naver_") ? "네이버 콘텐츠" : source);
}

function isBoilerplateVenue(v) {
  const bp = new Set(["Busan City", "Busan Culture Fdn", "hudpr", "부산시", "부산광역시", "부산관광공사"]);
  return bp.has(v);
}

// ───────── Phase 2: 카테고리 가시성 토글 (cluster + 개별 marker 동시 제어) ─────────
function toggleCategoryVisibility(cat, visible) {
  const clusterer = clusterers[cat];
  if (clusterer) {
    clusterer.setMap(visible ? map : null);
  }
  // 개별 marker 도 명시 제어 — MarkerClusterer 가 minLevel 밖/직후에 놓치는 경우 즉시 숨김
  for (const { marker } of allMarkers[cat] || []) {
    marker.setMap(visible ? map : null);
  }
}

// ───────── Phase 2: 클릭 피드백 펄스 ─────────
function pulseMarker(latlng) {
  const circle = new kakao.maps.Circle({
    center: latlng,
    radius: 120,
    strokeWeight: 3,
    strokeColor: "#60a5fa",
    strokeOpacity: 0.9,
    fillColor: "#60a5fa",
    fillOpacity: 0.25,
  });
  circle.setMap(map);
  setTimeout(() => circle.setMap(null), 650);
}

// ───────── Phase 2: 시트 가림 방지 offset pan ─────────
function panToWithSheetOffset(lat, lon) {
  try {
    const proj = map.getProjection();
    const pt = proj.pointFromCoords(new kakao.maps.LatLng(lat, lon));
    const offsetY = Math.max(120, Math.floor(window.innerHeight * 0.2));
    const newPt = new kakao.maps.Point(pt.x, pt.y + offsetY);
    const newCoord = proj.coordsFromPoint(newPt);
    map.panTo(newCoord);
  } catch (e) {
    map.panTo(new kakao.maps.LatLng(lat, lon));
  }
}

// ───────── init ─────────
async function init() {
  $status.textContent = "지도 로딩 중…";
  await loadKakaoSDK();

  const mapEl = document.getElementById("map");
  const center = new kakao.maps.LatLng(cfg.BUSAN_CENTER.lat, cfg.BUSAN_CENTER.lon);
  map = new kakao.maps.Map(mapEl, { center, level: cfg.DEFAULT_LEVEL });
  // Phase 3: 부산 전체가 딱 보이는 수준에서 더 축소 방지 (동아시아까지 넓어지는 것 차단)
  map.setMaxLevel(9);
  // 모바일 핀치 줌 / 더블탭 줌 / 마우스 휠 확대·축소 보장
  map.setZoomable(true);
  window.__map = map;

  $status.textContent = "데이터 로딩 중…";
  const [manifest, places, weatherShort, beaches, courses, seasonal, favorites] = await Promise.all([
    fetchJson("./data/manifest.json"),
    fetchJson("./data/places.json"),
    fetchJson("./data/weather-short.json"),
    fetchJson("./data/beaches.json"),
    fetchJson("./data/courses.json").catch(() => ({ courses: [] })),
    fetchJson("./data/seasonal.json").catch(() => ({ months: {} })),
    fetchJson("./data/my-favorites.json").catch(() => ({ favorites: [] })),  // 구글 별표 import (파일 없으면 빈 배열)
  ]);
  coursesData = courses;
  window.__seasonal = seasonal;
  window.__favorites = favorites;

  // 현재 월 ± 인접 월 축제 이벤트 로드 (manifest.events_by_month 기반)
  const monthsByCount = Object.entries(manifest.counts?.events_by_month || {})
    .filter(([k, n]) => n > 0 && /^\d{4}-\d{2}$/.test(k))
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([k]) => k);
  // 오늘 기준 과거 1개월 ~ 미래 6개월 범위의 월만 로드
  const today = new Date();
  const horizonMonths = new Set();
  for (let offset = -1; offset <= 6; offset++) {
    const d = new Date(today.getFullYear(), today.getMonth() + offset, 1);
    horizonMonths.add(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  const loadableMonths = monthsByCount.filter(m => horizonMonths.has(m));
  const eventFiles = await Promise.all(
    loadableMonths.map(m => fetchJson(`./data/events-${m}.json`).catch(() => ({ events: [] })))
  );
  const allEvents = eventFiles.flatMap(f => f.events || []);
  // Phase 3b: exhibition/performance 도 festival 마커로 통합 렌더 (지도 색 단일)
  const allFestivalEvents = allEvents.filter(e =>
    ["festival", "exhibition", "performance"].includes(e.category) && e.lat && e.lon
  );
  // 네이버 블로그 — category=blog_post/exhibition/performance 인 것만 (festival 은 위에 포함됨)
  const allBlogMarkers = allEvents
    .filter(e =>
      (e.source || "").startsWith("naver_blog") &&
      e.category !== "festival" &&
      e.lat && e.lon
    )
    .map(e => ({ ...e, category: "blog" }));
  // 읽을거리 탭 — 소스 신뢰도 반영된 blog_priority 기반 정렬 + 동일 제목군 디덕스
  // naver_search:news/blog 까지 후보에 포함해 뒤로 밀어내되, 공식 블로그가 상위 점유하게.
  const rawBlog = allEvents.filter(e =>
    (e.source && (e.source.startsWith("naver_blog") || e.source.startsWith("naver_search")))
  );
  // dedup: 제목 prefix 18자 normalize(공백/기호 제거) 같으면 blog_priority 최대 1건만
  const titleKey = (t) => (t || "")
    .replace(/[\[\]\(\)\{\}<>…·!?,.\-_~`'"'"#|:;/\\]/g, "")
    .replace(/\s+/g, "")
    .toLowerCase()
    .slice(0, 18);
  const bestByKey = new Map();
  for (const p of rawBlog) {
    const k = titleKey(p.title);
    if (!k) { bestByKey.set(Symbol(), p); continue; }
    const cur = bestByKey.get(k);
    const curBp = cur?.blog_priority ?? -99;
    const newBp = p.blog_priority ?? -99;
    if (!cur || newBp > curBp) bestByKey.set(k, p);
  }
  const allBlogPosts = [...bestByKey.values()].sort((a, b) => {
    const pa = a.blog_priority ?? a.priority ?? 0;
    const pb = b.blog_priority ?? b.priority ?? 0;
    if (pa !== pb) return pb - pa;
    const ia = a.image ? 1 : 0, ib = b.image ? 1 : 0;
    if (ia !== ib) return ib - ia;
    return (b.start || "").localeCompare(a.start || "");
  });
  window.__blogPosts = allBlogPosts;

  // Phase 3: 좌표 없는 naver_search 행사도 시트에 노출하기 위해 카테고리 기반 전체 수집
  const allEventPoi = allEvents.filter(e =>
    ["festival", "exhibition", "performance"].includes(e.category)
  );

  weatherIndex = buildWeatherIndex(weatherShort);
  const favArr = favorites?.favorites || [];
  window.__data = { manifest, places, weatherShort, beaches, courses, favorites: favArr, festivalEvents: allFestivalEvents, blogMarkers: allBlogMarkers, allEventPoi };

  renderMarkers(places, beaches, allFestivalEvents, allBlogMarkers, favArr);

  const totalPoi = (places.places?.length || 0) + (beaches.beaches?.length || 0);
  $status.textContent = `${totalPoi}개 POI · 날씨 격자 ${weatherShort.cells || 0}개 · ${manifest.generated_at?.slice(0, 10) || ""}`;

  // 초기: 오늘의 부산 하이라이트 (applyDateFilter 가 곧 다시 호출)
  renderTodayHighlights(new Date());

  // 카테고리 필터 토글 — Phase 2: toggleCategoryVisibility 로 즉시 반응 보장
  document.querySelectorAll(".filter input[data-cat]").forEach(chk => {
    chk.addEventListener("change", () => {
      toggleCategoryVisibility(chk.dataset.cat, chk.checked);
    });
    // 초기: 체크 해제 카테고리는 명시적으로 숨김 (cluster + 개별 marker 동시 제어)
    if (!chk.checked) {
      toggleCategoryVisibility(chk.dataset.cat, false);
    }
  });

  // 빈 카테고리 비활성화 (data=0 필터는 헛클릭 방지 위해 disabled + '준비 중' 툴팁)
  lockEmptyFilters();

  // Chip 토글 (날짜 preset → 축제 필터 + 날씨 배지)
  document.querySelectorAll(".chip").forEach(btn => {
    btn.addEventListener("click", () => {
      if (btn.dataset.preset === "custom") {
        openCustomDatePicker(btn);
        return;
      }
      document.querySelectorAll(".chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const target = resolvePreset(btn.dataset.preset);
      if (target) {
        applyDateFilter(target);
        refreshWeatherBadges(target);
      }
    });
  });

  // Sheet 스냅
  const sheet = document.getElementById("sheet");
  document.querySelector(".sheet-handle").addEventListener("click", () => {
    if (sheet.classList.contains("sheet-peek"))      sheet.classList.replace("sheet-peek", "sheet-half");
    else if (sheet.classList.contains("sheet-half")) sheet.classList.replace("sheet-half", "sheet-full");
    else                                              sheet.classList.replace("sheet-full", "sheet-peek");
  });

  // FAB
  document.getElementById("fab-locate").addEventListener("click", () => {
    if (!navigator.geolocation) return alert("위치 서비스 미지원");
    navigator.geolocation.getCurrentPosition(
      pos => map.panTo(new kakao.maps.LatLng(pos.coords.latitude, pos.coords.longitude)),
      err => alert(`위치 오류: ${err.message}`),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });

  // 지도 줌/이동 시 날씨 배지 재계산 (throttle)
  let zoomTimer = null;
  kakao.maps.event.addListener(map, "zoom_changed", () => {
    clearTimeout(zoomTimer);
    zoomTimer = setTimeout(() => refreshWeatherBadges(currentTargetDate), 200);
  });

  // 초기: 오늘 날짜 기준 필터 + 배지
  applyDateFilter(new Date());
  refreshWeatherBadges(new Date());

  // Bottom sheet 터치 드래그 (peek ↔ half ↔ full)
  enableSheetDrag();

  // 탭 전환 (지도 ↔ 코스 ↔ 읽을거리)
  document.querySelectorAll(".tab[data-view]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab[data-view]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      setViewMode(btn.dataset.view);
      if (btn.dataset.view !== "map") history.replaceState(null, "", "#" + btn.dataset.view);
      else history.replaceState(null, "", location.pathname + location.search);
    });
  });

  // URL 해시 기반 초기 뷰 (#read / #course / #map) — 공유용 링크 + 테스트
  const hashView = (location.hash || "").replace("#", "");
  if (hashView === "read" || hashView === "course") {
    const btn = document.querySelector(`.tab[data-view="${hashView}"]`);
    if (btn) btn.click();
  }

}

function setViewMode(mode) {
  document.body.classList.toggle("view-read", mode === "read" || mode === "course");
  document.body.classList.toggle("view-blog", mode === "read");
  document.body.classList.toggle("view-course", mode === "course");
  const sheet = document.getElementById("sheet");
  if (mode === "read") {
    ["sheet-peek", "sheet-half"].forEach(c => sheet.classList.remove(c));
    sheet.classList.add("sheet-full");
    renderBlogFeed();
  } else if (mode === "course") {
    ["sheet-peek", "sheet-half"].forEach(c => sheet.classList.remove(c));
    sheet.classList.add("sheet-full");
    renderCourseList();
  } else {
    sheet.classList.remove("sheet-full");
    sheet.classList.add("sheet-peek");
    renderTodayHighlights(currentTargetDate);
    clearCourseOverlay();
  }
}

// ───────── Course 모드 ─────────
function renderCourseList() {
  const courses = coursesData?.courses || [];
  if (!courses.length) {
    $list.innerHTML = `<div class="card"><div class="card-meta">코스 데이터가 아직 준비되지 않았습니다.</div></div>`;
    return;
  }
  $list.innerHTML = courses.slice(0, 50).map(c => {
    const poisCount = (c.pois || []).length;
    const active = c.uc_seq === activeCourseId ? "active" : "";
    const hasThumb = !!c.image;
    const thumb = hasThumb
      ? `<img class="course-thumb" src="${escape(busanImgUrl(c.image))}" loading="lazy" decoding="async" onerror="this.style.display='none'" alt="">`
      : "";
    return `<div class="card course-card ${active}${hasThumb ? " with-thumb" : ""}" data-uc="${c.uc_seq}">
      ${thumb}
      <div class="course-body">
        <div class="card-title">
          ${c.duration ? `<span class="course-badge">${escape(c.duration)}</span>` : ""}
          ${escape(c.title || "")}
        </div>
        <div class="card-meta">${poisCount}개 POI${c.views ? ` · 조회 ${c.views.toLocaleString()}` : ""}${c.rating ? ` · ★${c.rating}` : ""}</div>
        ${c.excerpt ? `<div class="card-excerpt">${escape(c.excerpt.slice(0, 160))}</div>` : ""}
        ${(c.tags || []).length ? `<div class="tag-chips">${c.tags.slice(0, 5).map(t => `<span class="tag-chip">#${escape(t)}</span>`).join("")}</div>` : ""}
      </div>
    </div>`;
  }).join("");

  $list.querySelectorAll(".course-card").forEach(el => {
    el.addEventListener("click", () => {
      const uc = Number(el.dataset.uc);
      activateCourse(uc);
    });
  });
}

function clearCourseOverlay() {
  if (courseOverlay.polyline) {
    courseOverlay.polyline.setMap(null);
    courseOverlay.polyline = null;
  }
  for (const h of courseOverlay.highlights) {
    h.setMap(null);
  }
  courseOverlay.highlights = [];
  activeCourseId = null;
}

function activateCourse(uc_seq) {
  clearCourseOverlay();
  const course = (coursesData?.courses || []).find(c => c.uc_seq === uc_seq);
  if (!course) return;
  activeCourseId = uc_seq;

  // POI 이름 기반으로 places 에서 매칭 시도 (loose: 앞 6글자 일치)
  const allPlaces = [...(window.__data.places.places || [])];
  const path = [];
  for (const p of course.pois || []) {
    const name = (p.name || "").trim();
    if (!name) continue;
    const key = name.slice(0, 6);
    const match = allPlaces.find(pl => pl.title && pl.title.includes(key));
    if (match && match.lat && match.lon) {
      path.push(new kakao.maps.LatLng(match.lat, match.lon));
      // Highlight circle
      const circle = new kakao.maps.Circle({
        center: new kakao.maps.LatLng(match.lat, match.lon),
        radius: 80,
        strokeWeight: 3,
        strokeColor: "#fbbf24",
        strokeOpacity: 0.9,
        fillColor: "#fbbf24",
        fillOpacity: 0.25,
      });
      circle.setMap(map);
      courseOverlay.highlights.push(circle);
    }
  }
  if (path.length >= 2) {
    courseOverlay.polyline = new kakao.maps.Polyline({
      path,
      strokeWeight: 4,
      strokeColor: "#fbbf24",
      strokeOpacity: 0.8,
      strokeStyle: "solid",
    });
    courseOverlay.polyline.setMap(map);
    // 지도 bounds 조정
    const bounds = new kakao.maps.LatLngBounds();
    path.forEach(p => bounds.extend(p));
    map.setBounds(bounds);
  } else if (path.length === 1) {
    map.panTo(path[0]);
  }
  renderCourseList(); // 선택 상태 반영 재렌더
}

function renderBlogFeed() {
  const posts = window.__blogPosts || [];
  if (!posts.length) {
    $list.innerHTML = `<div class="card"><div class="card-meta">읽을거리 데이터 없음</div></div>`;
    return;
  }

  // P3 — 중요도 정렬(priority → 이미지 → 날짜). Top 3 은 hero_tags 칩으로 규모 강조
  $list.innerHTML = posts.slice(0, 100).map((p, i) => {
    const src = (p.source || "").replace("naver_blog:", "");
    const date = (p.start || "").slice(0, 10);
    const label = p.category === "festival" ? "FESTIVAL · 축제"
                : p.subtype === "performance" ? "PERFORMANCE · 공연"
                : p.subtype === "exhibition" ? "EXHIBITION · 전시"
                : "JOURNAL · 에디토리얼";
    const leadLen = i === 0 ? 240 : 140;
    const lead = p.description
      ? escape(p.description.slice(0, leadLen)) + (p.description.length > leadLen ? "…" : "")
      : "";
    const featured = i === 0 ? " blog-card-featured" : "";
    const tags = (p.hero_tags || []).slice(0, 2);
    const tagHTML = (i < 3 && tags.length)
      ? `<div class="blog-card-tags">${tags.map(t => `<span class="blog-card-tag">${escape(t)}</span>`).join("")}</div>`
      : "";
    return `<article class="blog-card${featured}">
      <div class="blog-card-category">${escape(label)}</div>
      ${tagHTML}
      <h3 class="blog-card-title">${escape(p.title)}</h3>
      ${lead ? `<p class="blog-card-lead">${lead}</p>` : ""}
      <div class="blog-card-meta">
        <span>${escape(src)}${date ? " · " + escape(date) : ""}</span>
        ${p.url ? `<a class="blog-card-readmore" href="${escape(p.url)}" target="_blank" rel="noopener">원문 →</a>` : ""}
      </div>
    </article>`;
  }).join("");
}

// P3 — 월간 내러티브 Hero (Faroe 스타일): 이번 달 부산 이야기 1건 큐레이션
function renderNarrativeHero() {
  const posts = window.__blogPosts || [];
  if (!posts.length) return "";
  const now = new Date();
  const ym = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  // 이번 달 게시글 우선 → 없으면 가장 최근
  const pick = posts.find(p => (p.start || "").startsWith(ym)) || posts[0];
  if (!pick) return "";
  const lead = pick.description
    ? escape(pick.description.slice(0, 150)) + (pick.description.length > 150 ? "…" : "")
    : "";
  const monthLabel = `${now.getFullYear()}년 ${now.getMonth() + 1}월 · STORY OF THE MONTH`;
  return `<article class="narrative-hero" role="button" tabindex="0">
    <div class="narrative-hero-label">${escape(monthLabel)}</div>
    <h2 class="narrative-hero-title">${escape(pick.title)}</h2>
    ${lead ? `<p class="narrative-hero-lead">${lead}</p>` : ""}
    <span class="narrative-hero-cta">📖 이번 달의 부산 이야기 · 읽을거리에서 전체 보기 →</span>
  </article>`;
}

// ───────── Phase 2: "오늘의 부산" 하이라이트 — Hero Top 3 + Tail 칩 ─────────
// 중요도 스코어(priority) 기반 재설계. 진행중+예정 합친 후 priority 내림차순,
// 상위 3건은 이미지+D-x+태그 가진 Hero 카드, 나머지는 칩 리스트(기본 6 + 더보기).
function renderTodayHighlights(target) {
  target = target || new Date();
  const month = String(target.getMonth() + 1).padStart(2, "0");

  const pool = window.__data?.allEventPoi || [];
  const active = [], upcoming = [];
  for (const poi of pool) {
    const kind = classifyFestival(poi, target);
    if (kind === "active") active.push({ ...poi, _k: "active" });
    else if (kind === "upcoming") upcoming.push({ ...poi, _k: "upcoming" });
  }
  // Hero 통합 정렬: priority DESC, 같으면 시작일 ASC (임박 우선)
  const combined = [...active, ...upcoming];
  combined.sort((a, b) => {
    const pa = a.priority ?? 0, pb = b.priority ?? 0;
    if (pa !== pb) return pb - pa;
    return (a.start || "").localeCompare(b.start || "");
  });
  const hero = combined.slice(0, 3);
  const tail = combined.slice(3);

  const season = (window.__seasonal?.months || {})[month];
  const today = new Date();
  const isToday = target.toDateString() === today.toDateString();
  const days = ["일", "월", "화", "수", "목", "금", "토"];
  const heroDate = isToday ? "오늘" : `${target.getMonth() + 1}월 ${target.getDate()}일 (${days[target.getDay()]})`;
  const heroSub = season?.title || "부산 여행";

  const topBar = `<div class="highlight-hero">
    <div class="hh-date">${escape(heroDate)} · 부산</div>
    <div class="hh-sub">${escape(heroSub)} · 진행 ${active.length} · 2개월내 ${upcoming.length}</div>
  </div>`;

  let heroHTML;
  if (hero.length) {
    heroHTML = `<div class="highlight-section hl-hero-section">
      <div class="hs-title">⭐ 이번 주 주목 Top ${hero.length}</div>
      <div class="hero-grid">
        ${hero.map((p, i) => heroCardHTML(p, i, target)).join("")}
      </div>
    </div>`;
  } else {
    heroHTML = `<div class="highlight-section">
      <div class="hs-title">🎪 이 날짜 주목할 행사 없음</div>
      <div class="hs-note">📅 다른 날을 선택하거나 달력에서 다가오는 날짜를 눌러보세요.</div>
    </div>`;
  }

  let tailHTML = "";
  if (tail.length) {
    const initial = 6;
    const firstBatch = tail.slice(0, initial);
    const extra = tail.slice(initial);
    const extraHTML = extra.length
      ? `<div class="chip-extra" hidden>${extra.map((p, i) => chipHTML(p, i + initial, target)).join("")}</div>
         <button class="chip-more" type="button">+${extra.length}건 더 보기</button>`
      : "";
    tailHTML = `<div class="highlight-section">
      <div class="hs-title">📋 그 외 행사 ${tail.length}건</div>
      <div class="chip-list">${firstBatch.map((p, i) => chipHTML(p, i, target)).join("")}</div>
      ${extraHTML}
    </div>`;
  }

  let seasonHTML = "";
  if (season) {
    const foods = (season.foods || []).map(f =>
      `<li>${escape(f.name)}${f.where ? ` <span class="sm-where">@ ${escape(f.where)}</span>` : ""}</li>`
    ).join("");
    const blooms = (season.blooms || []).map(b => `<li>${escape(b)}</li>`).join("");
    const scenes = (season.scenes || []).map(s => `<li>${escape(s)}</li>`).join("");
    seasonHTML = `<div class="highlight-section">
      <div class="hs-title">🍽 ${target.getMonth() + 1}월 부산 제철</div>
      ${foods ? `<ul class="sm-list"><li class="sm-sub">음식</li>${foods}</ul>` : ""}
      ${blooms ? `<ul class="sm-list"><li class="sm-sub">꽃·봄빛</li>${blooms}</ul>` : ""}
      ${scenes ? `<ul class="sm-list"><li class="sm-sub">계절 풍경</li>${scenes}</ul>` : ""}
    </div>`;
  }

  const storyHero = renderNarrativeHero();

  $list.innerHTML = topBar + heroHTML + tailHTML + seasonHTML + storyHero;

  // Hero + chip 클릭 → POI 상세
  $list.querySelectorAll(".hero-card, .chip").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.idx);
      const poi = combined[idx];
      if (poi) showDetail(poi);
    });
  });

  // 칩 더 보기 펼치기
  const moreBtn = $list.querySelector(".chip-more");
  if (moreBtn) {
    moreBtn.addEventListener("click", () => {
      const extra = $list.querySelector(".chip-extra");
      if (extra) extra.hidden = false;
      moreBtn.remove();
    });
  }

  // 월간 STORY 클릭 → 읽을거리 탭
  const storyEl = $list.querySelector(".narrative-hero");
  if (storyEl) {
    const goBlog = () => {
      const btn = document.querySelector('.tab[data-view="read"]');
      if (btn) btn.click();
    };
    storyEl.addEventListener("click", goBlog);
    storyEl.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goBlog(); }
    });
  }
}

function _dBadge(p, target) {
  // D-x 배지 문자열. active 는 "진행중 · ~종료일", upcoming 은 "D-x"
  const start = parseDate(p.start);
  const end = parseDate(p.end) || start;
  if (!start) return "";
  const t = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  const MS = 86400000;
  if (p._k === "active") {
    if (!end) return "진행중";
    const daysLeft = Math.max(0, Math.round((end - t) / MS));
    return daysLeft === 0 ? "오늘 종료" : `진행중 · D-${daysLeft}`;
  }
  const daysTo = Math.max(0, Math.round((start - t) / MS));
  return daysTo === 0 ? "오늘 시작" : `D-${daysTo}`;
}

function heroCardHTML(p, idx, target) {
  const img = p.image;
  const tags = (p.hero_tags || []).slice(0, 2);
  const tagHTML = tags.length
    ? `<div class="hc-tags">${tags.map(t => `<span class="hc-tag">${escape(t)}</span>`).join("")}</div>`
    : "";
  const dBadge = _dBadge(p, target);
  const venue = p.venue || p.address || "";
  const start = (p.start || "").slice(5);
  const end = (p.end || "").slice(5);
  const dateRange = start && end && end !== start ? `${start}~${end}`
                  : start ? start : "";
  const imgHTML = img
    ? `<img class="hc-img" src="${escape(img)}" alt="" loading="lazy" onerror="this.style.display='none'">`
    : `<div class="hc-img hc-img-placeholder">${icon("ph-confetti")}</div>`;
  const activeClass = p._k === "active" ? " is-active" : "";
  return `<button class="hero-card${activeClass}" data-idx="${idx}">
    <div class="hc-media">
      ${imgHTML}
      ${dBadge ? `<span class="hc-dbadge">${escape(dBadge)}</span>` : ""}
    </div>
    <div class="hc-body">
      ${tagHTML}
      <h3 class="hc-title">${escape(p.title || "(제목 없음)")}</h3>
      <div class="hc-meta">${escape(dateRange)}${venue ? " · " + escape(venue) : ""}</div>
    </div>
  </button>`;
}

function chipHTML(p, idx, target) {
  const dBadge = _dBadge(p, target);
  const activeClass = p._k === "active" ? " is-active" : "";
  return `<button class="chip${activeClass}" data-idx="${idx}">
    ${dBadge ? `<span class="chip-d">${escape(dBadge)}</span>` : ""}
    <span class="chip-title">${escape(p.title || "(제목 없음)")}</span>
  </button>`;
}

// ───────── Phase 2: 선택 날짜 헤드라인 배지 (날씨 + 행사·제철 카운트) ─────────
function renderDateBadge(target, active, upcoming) {
  const $badge = document.getElementById("date-badge");
  if (!$badge) return;
  const days = ["일", "월", "화", "수", "목", "금", "토"];
  const label = `${target.getMonth() + 1}/${target.getDate()} (${days[target.getDay()]})`;

  // 부산 중심 격자 대표 날씨: 97_74 우선 (해운대권), 없으면 첫 셀
  let f = null;
  if (weatherIndex) {
    const key = weatherIndex["97_74"] ? "97_74" : Object.keys(weatherIndex)[0];
    if (key) {
      const [nx, ny] = key.split("_").map(Number);
      f = nearestForecast(nx, ny, target);
    }
  }
  const parts = [`<span class="db-date">📅 ${escape(label)}</span>`];
  if (f) {
    const wxBits = [];
    const skyEmo = (SKY_TXT[f.sky] || "").split(" ")[0];
    const ptyEmo = (PTY_TXT[f.pty] || "").split(" ")[0];
    if (skyEmo) wxBits.push(skyEmo);
    if (ptyEmo) wxBits.push(ptyEmo);
    if (f.tmp !== undefined && f.tmp !== null) wxBits.push(`${Math.round(f.tmp)}°`);
    if (f.pop !== undefined && f.pop !== null && f.pop > 0) wxBits.push(`💧${f.pop}%`);
    const wx = wxBits.join(" ");
    if (wx) parts.push(`<span class="db-sep">·</span><span class="db-weather">${escape(wx)}</span>`);
  }
  const month = String(target.getMonth() + 1).padStart(2, "0");
  const season = (window.__seasonal?.months || {})[month];
  const seasonCount = season
    ? ((season.foods?.length || 0) + (season.blooms?.length || 0) + (season.scenes?.length || 0))
    : 0;
  const activeN = active || 0, upcomingN = upcoming || 0;
  const stats = `🎪 ${activeN}${upcomingN ? `+${upcomingN}` : ""} · 🍽 ${seasonCount}`;
  parts.push(`<span class="db-sep">·</span><span class="db-stats">${stats}</span>`);

  $badge.innerHTML = parts.join("");
  $badge.hidden = false;
}

function openCustomDatePicker(chipBtn) {
  const input = document.createElement("input");
  input.type = "date";
  const t = new Date();
  input.min = t.toISOString().slice(0, 10);
  const max = new Date(t); max.setDate(t.getDate() + 10);
  input.max = max.toISOString().slice(0, 10);
  input.style.cssText = "position:fixed;top:60px;left:50%;transform:translateX(-50%);z-index:99;padding:10px;font-size:16px;border-radius:8px;border:1px solid #ccc";
  document.body.appendChild(input);
  input.focus();
  if (typeof input.showPicker === "function") input.showPicker();
  input.addEventListener("change", () => {
    if (!input.value) return;
    const [y, m, d] = input.value.split("-").map(Number);
    const target = new Date(y, m - 1, d);
    document.querySelectorAll(".chip").forEach(b => b.classList.remove("active"));
    chipBtn.classList.add("active");
    chipBtn.textContent = `📅 ${input.value.slice(5)}`;
    applyDateFilter(target);
    refreshWeatherBadges(target);
    input.remove();
  });
  input.addEventListener("blur", () => setTimeout(() => input.remove(), 200));
}

function enableSheetDrag() {
  const sheet = document.getElementById("sheet");
  const handle = document.querySelector(".sheet-handle");
  let startY = 0, startClass = "";
  const snaps = ["sheet-peek", "sheet-half", "sheet-full"];

  function onStart(e) {
    startY = (e.touches?.[0]?.clientY ?? e.clientY);
    startClass = snaps.find(c => sheet.classList.contains(c)) || "sheet-peek";
    document.addEventListener("pointermove", onMove, { passive: false });
    document.addEventListener("pointerup", onEnd, { once: true });
    e.preventDefault();
  }
  function onMove(e) {
    const y = (e.touches?.[0]?.clientY ?? e.clientY);
    const dy = y - startY;
    const currentIdx = snaps.indexOf(startClass);
    let targetIdx = currentIdx;
    if (dy < -40) targetIdx = Math.min(snaps.length - 1, currentIdx + 1);
    else if (dy > 40) targetIdx = Math.max(0, currentIdx - 1);
    const nextClass = snaps[targetIdx];
    if (!sheet.classList.contains(nextClass)) {
      snaps.forEach(c => sheet.classList.remove(c));
      sheet.classList.add(nextClass);
    }
  }
  function onEnd() {
    document.removeEventListener("pointermove", onMove);
  }

  handle.addEventListener("pointerdown", onStart);
  handle.style.cursor = "grab";
}

function resolvePreset(preset) {
  const now = new Date();
  const d = new Date(now);
  if (preset === "today") return d;
  if (preset === "tomorrow") { d.setDate(d.getDate() + 1); return d; }
  if (preset === "weekend") {
    const day = d.getDay();
    const addDays = day === 0 ? 6 : 6 - day; // 다음 토요일
    d.setDate(d.getDate() + addDays);
    return d;
  }
  if (preset === "next-weekend") {
    const day = d.getDay();
    const addDays = (day === 0 ? 6 : 6 - day) + 7;
    d.setDate(d.getDate() + addDays);
    return d;
  }
  return null;
}

function escape(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// ───────── Phase 1: 빈 카테고리 필터 비활성 ─────────
function lockEmptyFilters() {
  document.querySelectorAll(".filter input[data-cat]").forEach(chk => {
    const cat = chk.dataset.cat;
    const arr = allMarkers[cat];
    const n = arr ? arr.length : 0;
    if (n === 0) {
      const label = chk.closest(".filter");
      if (label) {
        label.classList.add("is-empty");
        label.title = "데이터 준비 중";
      }
      chk.checked = false;
      chk.disabled = true;
      if (clusterers[cat]) clusterers[cat].setMap(null);
    }
  });
}

init().catch(err => {
  console.error("[busan-travel] init failed:", err);
  const msg = err?.message || err?.toString() || "알 수 없는 에러 (DevTools Console 확인)";
  $status.textContent = `로딩 실패: ${msg}`;
});
