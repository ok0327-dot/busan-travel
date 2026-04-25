// 주말부산 — Kakao Maps 기반 지도 대시보드

const cfg = window.APP_CONFIG;
if (!cfg || !cfg.KAKAO_JS_KEY) {
  alert("config.js 가 없거나 KAKAO_JS_KEY 가 비어있어요.");
  throw new Error("Missing APP_CONFIG");
}

const CATEGORIES = {
  festival:    { label: "축제",   emoji: "🎪", icon: "ph-confetti",       color: "#ef4444", letter: "축" },
  exhibition:  { label: "전시",   emoji: "🎨", icon: "ph-palette",        color: "#8b5cf6", letter: "전" },
  performance: { label: "공연",   emoji: "🎭", icon: "ph-music-notes",    color: "#db2777", letter: "공" },
  attraction:  { label: "명소",   emoji: "🏛", icon: "ph-buildings",      color: "#3b82f6", letter: "명" },
  food:        { label: "맛집",   emoji: "🍜", icon: "ph-bowl-food",      color: "#f97316", letter: "맛" },
  cafe:        { label: "카페",   emoji: "☕", icon: "ph-coffee",         color: "#a16207", letter: "카" },
  blog:        { label: "블로그", emoji: "📝", icon: "ph-notebook",       color: "#ec4899", letter: "블" },
  // guide 는 visitbusan 매거진 가이드 글. 지도 마커 X, 읽을거리 탭 카드용 (CATEGORIES 에 두면 라벨/색 재사용 가능)
  guide:       { label: "가이드", emoji: "📖", icon: "ph-book-open-text", color: "#94a3b8", letter: "가" },
};

// Phosphor Bold 아이콘 SVG path (viewBox 0 0 256 256) — 지도 마커 내부에 inline 삽입.
// letter 기반 한글 1글자 대신 아이콘 경로를 직접 렌더해 폰트/플랫폼 의존 제거.
const PHOSPHOR_MARKER_PATHS = {
  festival:    'M114.32,49.8A19.79,19.79,0,0,0,81.72,57L29.22,201.41A19.82,19.82,0,0,0,47.75,228a20,20,0,0,0,6.84-1.22L199,174.28a19.79,19.79,0,0,0,7.24-32.6ZM104.19,183.21l-31.4-31.4L82.94,123.9l49.16,49.16Zm-52.42,26.4Zm12-32.91L79.3,192.26l-24.45,8.89ZM157,164,92,99l10-27.58L184.57,154ZM128,40V16a12,12,0,0,1,24,0V40a12,12,0,0,1-24,0Zm116.48,83.51a12,12,0,0,1-17,17l-16-16a12,12,0,0,1,17-17Zm-.69-40.13-24,8a12,12,0,0,1-7.59-22.77l24-8a12,12,0,1,1,7.59,22.77ZM156.6,65.93C159.83,47.47,173.39,36,192,36c6.45,0,8.69-2.49,10-4.92a18,18,0,0,0,2-7.22V24a12,12,0,0,1,24,0c0,14.47-9.59,36-36,36-4.94,0-10.21,1.19-11.76,10.06A12,12,0,0,1,168.43,80a12.35,12.35,0,0,1-2.08-.18A12,12,0,0,1,156.6,65.93Z',
  exhibition:  'M203.57,51A107.9,107.9,0,0,0,20,128c0,44.72,27.6,82.25,72,97.94A36,36,0,0,0,140,192a12,12,0,0,1,12-12h46.21a35.79,35.79,0,0,0,35.1-28A108.6,108.6,0,0,0,236,127.09,107.23,107.23,0,0,0,203.57,51Zm6.34,95.67a11.91,11.91,0,0,1-11.7,9.3H152a36,36,0,0,0-36,36,12,12,0,0,1-16,11.3c-16.65-5.88-30.65-15.76-40.48-28.56A76,76,0,0,1,44,128a84,84,0,0,1,83.13-84H128a84.35,84.35,0,0,1,84,83.29A84.72,84.72,0,0,1,209.91,146.71ZM144,76a16,16,0,1,1-16-16A16,16,0,0,1,144,76Zm-44,24A16,16,0,1,1,84,84,16,16,0,0,1,100,100Zm0,56a16,16,0,1,1-16-16A16,16,0,0,1,100,156Zm88-56a16,16,0,1,1-16-16A16,16,0,0,1,188,100Z',
  performance: 'M215.38,14.54a12,12,0,0,0-10.29-2.18l-128,32A12,12,0,0,0,68,56V159.35A40,40,0,1,0,92,196V113.37l104-26v40A40,40,0,1,0,220,164V24A12,12,0,0,0,215.38,14.54ZM52,212a16,16,0,1,1,16-16A16,16,0,0,1,52,212ZM92,88.63V65.37l104-26V62.63ZM180,180a16,16,0,1,1,16-16A16,16,0,0,1,180,180Z',
  attraction:  'M240,204H228V96a20,20,0,0,0-20-20H172V32a20,20,0,0,0-28.45-18.12l-104,48.54A20.06,20.06,0,0,0,28,80.55V204H16a12,12,0,0,0,0,24H240a12,12,0,0,0,0-24ZM204,100V204H172V100ZM52,83.09,148,38.3V204H52ZM132,112v12a12,12,0,0,1-24,0V112a12,12,0,0,1,24,0Zm-40,0v12a12,12,0,0,1-24,0V112a12,12,0,0,1,24,0Zm0,52v12a12,12,0,0,1-24,0V164a12,12,0,0,1,24,0Zm40,0v12a12,12,0,0,1-24,0V164a12,12,0,0,1,24,0Z',
  food:        'M224,100h-4.78a92,92,0,0,0-182.44,0H32a12,12,0,0,0-12,12,108.38,108.38,0,0,0,56,94.68V208a20,20,0,0,0,20,20h64a20,20,0,0,0,20-20v-1.32A108.38,108.38,0,0,0,236,112,12,12,0,0,0,224,100ZM170.29,60.06A92,92,0,0,0,127.19,100H106a68.27,68.27,0,0,1,62-40C168.76,60,169.52,60,170.29,60.06Zm17.22,19.08A67.66,67.66,0,0,1,194.92,100H156.13A67.91,67.91,0,0,1,187.51,79.14ZM128,44c.83,0,1.65,0,2.48.06A92.3,92.3,0,0,0,80.37,100H61.08A68.1,68.1,0,0,1,128,44Zm35,144.39a12,12,0,0,0-7,10.91V204H100v-4.7a12,12,0,0,0-7-10.91A84.32,84.32,0,0,1,44.87,124H211.13A84.32,84.32,0,0,1,163,188.39Z',
  cafe:        'M212,76H32A12,12,0,0,0,20,88v48a100.24,100.24,0,0,0,26.73,68H32a12,12,0,0,0,0,24H208a12,12,0,0,0,0-24H193.27a100.75,100.75,0,0,0,20-32A44,44,0,0,0,256,128v-8A44.05,44.05,0,0,0,212,76Zm-16,60a76.27,76.27,0,0,1-42,68H86a76.27,76.27,0,0,1-42-68V100H196Zm36-8a20,20,0,0,1-12.57,18.55A97.17,97.17,0,0,0,220,136V101.68A20,20,0,0,1,232,120ZM68,48V24a12,12,0,0,1,24,0V48a12,12,0,0,1-24,0Zm40,0V24a12,12,0,0,1,24,0V48a12,12,0,0,1-24,0Zm40,0V24a12,12,0,0,1,24,0V48a12,12,0,0,1-24,0Z',
  theme:       'M247,116.39l-20.47-5.34A100.27,100.27,0,0,0,145,29.44L139.61,9a12,12,0,0,0-23.22,0l-5.34,20.47a100.27,100.27,0,0,0-81.61,81.61L9,116.39a12,12,0,0,0,0,23.22L29.44,145a100.27,100.27,0,0,0,81.61,81.61L116.39,247a12,12,0,0,0,23.22,0L145,226.56A100.27,100.27,0,0,0,226.56,145L247,139.61a12,12,0,0,0,0-23.22Zm-46.88-12.23l-38.31-10-10-38.31A76.32,76.32,0,0,1,200.15,104.16Zm-82.8-3.78L128,59.54l10.65,40.84L128,111ZM128,145l10.65,10.65L128,196.46l-10.65-40.84Zm-27.62-27.62L111,128l-10.65,10.65L59.54,128Zm55.24,21.3L145,128l10.65-10.65L196.46,128Zm-51.46-82.8l-10,38.31l-38.31,10A76.32,76.32,0,0,1,104.16,55.85Zm-48.31,96l38.31,10l10,38.31A76.32,76.32,0,0,1,55.85,151.84Zm96,48.31l10-38.31l38.31-10A76.32,76.32,0,0,1,151.84,200.15Z',
  blog:        'M108,108a12,12,0,0,1,12-12h56a12,12,0,0,1,0,24H120A12,12,0,0,1,108,108Zm68,28H120a12,12,0,0,0,0,24h56a12,12,0,0,0,0-24Zm52-88V208a20,20,0,0,1-20,20H48a20,20,0,0,1-20-20V48A20,20,0,0,1,48,28H208A20,20,0,0,1,228,48ZM52,204H68V52H52ZM204,52H92V204H204Z',
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

// ───────── SVG 마커 생성 — Phosphor Bold 아이콘 path + 별표 배지 ─────────
// Phosphor path viewBox=256 → 마커 원(반지름 12, 중심 20,20) 안에 크기 18 로 배치:
// scale 18/256 ≈ 0.0703, translate(11,11) 로 중앙 정렬.
function svgMarker(color, category, isFavorite = false) {
  const starBadge = isFavorite
    ? `<circle cx="33" cy="7" r="7" fill="#facc15" stroke="white" stroke-width="1.5"/><text x="33" y="10.5" text-anchor="middle" font-size="9" font-weight="700" fill="white">★</text>`
    : '';
  const iconPath = PHOSPHOR_MARKER_PATHS[category];
  const iconGroup = iconPath
    ? `<g transform="translate(11 11) scale(0.0703)" fill="${color}"><path d="${iconPath}"/></g>`
    : `<text x="20" y="25.5" text-anchor="middle" font-size="15" font-weight="700" fill="${color}" font-family="Pretendard, -apple-system, system-ui, sans-serif">${(CATEGORIES[category] || {}).letter || "?"}</text>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="52" viewBox="0 0 40 52">
    <path d="M20 0C9 0 0 9 0 20c0 14 20 32 20 32s20-18 20-32C40 9 31 0 20 0z" fill="${color}" stroke="white" stroke-width="2"/>
    <circle cx="20" cy="20" r="12" fill="white"/>
    ${iconGroup}
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
      svgMarker(cat.color, category, isFavorite),
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
    // festivalEvents 는 festival/exhibition/performance 섞여 있음 — 각자 자신의 category 유지
    ...festivalEvents,
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

// venue group 포함 통합 분류 — venue 내 이벤트 중 하나라도 active/upcoming 면 그 레벨
function classifyPoi(poi, target) {
  if (poi && poi.isVenueGroup) {
    let hasActive = false, hasUpcoming = false;
    for (const e of poi.events || []) {
      const k = classifyFestival(e, target);
      if (k === "active") { hasActive = true; break; }
      if (k === "upcoming") hasUpcoming = true;
    }
    if (hasActive) return "active";
    if (hasUpcoming) return "upcoming";
    return "unknown";
  }
  return classifyFestival(poi, target);
}

function applyDateFilter(target) {
  currentTargetDate = target;

  // 지도 마커 — festival/exhibition/performance 세 카테고리 모두 날짜 필터 적용
  // exhibition/performance 는 venue 그룹이므로 classifyPoi 가 그룹 내 집계
  for (const cat of ["festival", "exhibition", "performance"]) {
    const clusterer = clusterers[cat];
    if (!clusterer) continue;
    const showMarkers = [];
    for (const { marker, poi } of allMarkers[cat] || []) {
      const kind = classifyPoi(poi, target);
      if (kind === "active")        { showMarkers.push(marker); marker.setOpacity(1.0); }
      else if (kind === "upcoming") { showMarkers.push(marker); marker.setOpacity(0.55); }
      else if (kind === "unknown")  { showMarkers.push(marker); marker.setOpacity(0.55); }
    }
    clusterer.clear();
    clusterer.addMarkers(showMarkers);
  }

  // Phase 3: 시트·배지 카운트는 좌표 無 이벤트 포함 전체 기준
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
// ───────── 데이터 freshness 가시화 (P0, v3.8) ─────────
function renderFreshness(manifest) {
  const ts = manifest?.generated_at;
  const dot = document.querySelector(".freshness-dot");
  const text = document.querySelector(".freshness-text");
  const detail = document.getElementById("freshness-detail");
  const btn = document.getElementById("freshness-toggle");
  if (!ts || !dot || !text) return;

  const generated = new Date(ts);
  const ageMin = (Date.now() - generated) / 60000;
  const ageH = ageMin / 60;
  const kst = new Date(generated.getTime() + 9 * 3600000);
  const ymd = kst.toISOString().slice(0, 10);
  const hm = kst.toISOString().slice(11, 16);

  let level, label;
  if (ageH >= 48) { level = "stale-error"; label = `🚨 ${Math.floor(ageH)}시간 전 — 점검 필요`; }
  else if (ageH >= 24) { level = "stale-warn"; label = `⚠ ${Math.floor(ageH)}시간 전 갱신`; }
  else if (ageMin < 60) { level = "fresh"; label = `🔄 ${Math.max(1, Math.floor(ageMin))}분 전 갱신`; }
  else { level = "fresh"; label = `🔄 ${ymd} ${hm} KST`; }
  dot.classList.remove("is-fresh", "is-stale-warn", "is-stale-error");
  dot.classList.add(`is-${level}`);
  text.textContent = label;

  // 어댑터별 detail 테이블
  const adapters = manifest.adapters || {};
  if (detail && Object.keys(adapters).length) {
    const sorted = Object.entries(adapters)
      .sort((a, b) => (b[1].last_seen || "").localeCompare(a[1].last_seen || ""));
    const rows = sorted.map(([src, info]) => {
      let cls = "";
      let ageLabel = "—";
      if (info.last_seen) {
        const aH = (Date.now() - new Date(info.last_seen)) / 3600000;
        if (aH < 24) ageLabel = "<24h";
        else if (aH < 48) { ageLabel = `${Math.floor(aH)}h`; cls = "fresh-warn"; }
        else { ageLabel = `${Math.floor(aH / 24)}d`; cls = "fresh-stale"; }
      }
      return `<tr class="${cls}"><td>${escape(src)}</td><td class="num">${info.rows ?? 0}</td><td>${ageLabel}</td></tr>`;
    }).join("");
    detail.innerHTML = `<table class="freshness-table">
      <thead><tr><th>소스</th><th class="num">건수</th><th>갱신</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }
  if (btn) {
    btn.onclick = () => {
      const open = detail?.hidden;
      if (detail) detail.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      const caret = btn.querySelector(".freshness-caret");
      if (caret) caret.textContent = open ? "⏶" : "⏷";
    };
  }
}

function renderStars(rating) {
  if (!rating) return "";
  const n = Math.round(rating);
  return `<span class="rating-stars">${"★".repeat(n)}${"☆".repeat(5 - n)}</span> <span class="card-meta">${rating.toFixed(1)}</span>`;
}

// Naver 블로그 언급 수 (food/cafe 에만 enrich 됨) — 정확 일치 검색 기반
function renderExternalRatings(poi) {
  if (!poi.naver_reviews) return "";
  const n = poi.naver_reviews;
  const pretty = n >= 1000 ? `${(n / 1000).toFixed(1)}K` : n.toLocaleString();
  return `<div class="card-meta ext-rating-row"><span class="ext-rating ext-naver"><b>N</b> 블로그 언급 ${pretty}건</span></div>`;
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

// 마커 클릭 → detail → "← 목록으로" 버튼으로 카드 리스트 즉시 복귀
function _detailHeader() {
  return `<button class="detail-back" type="button" aria-label="목록으로 돌아가기">← 목록으로</button>`;
}
function _bindDetailBack() {
  const btn = $list.querySelector(".detail-back");
  if (btn) btn.addEventListener("click", () => {
    const view = document.body.dataset.view || "map";
    if (view === "course") renderCourseList();
    else if (view === "read") renderBlogFeed();
    else renderTodayHighlights(currentTargetDate);
    // sheet peek 복귀
    const sheet = document.getElementById("sheet");
    if (sheet?.classList.contains("sheet-full")) sheet.classList.replace("sheet-full", "sheet-half");
  });
}

function showDetail(poi) {
  const catDef = CATEGORIES[poi.category] || {};
  const isBlog = poi.category === "blog" || poi.category === "blog_post";
  const isFavorite = !!poi.is_favorite;

  // 블로그는 별도 레이아웃 — 출처·날짜 + 발췌 + 원문 보기 중심으로 명확히
  if (isBlog) {
    $list.innerHTML = _detailHeader() + renderBlogDetail(poi);
    _bindDetailBack();
    const sheet = document.getElementById("sheet");
    if (sheet.classList.contains("sheet-peek")) sheet.classList.replace("sheet-peek", "sheet-half");
    return;
  }

  // 전시/공연 venue 그룹 — 그 venue 에서 현재 열리는 행사 목록으로 렌더
  if (poi.isVenueGroup) {
    $list.innerHTML = _detailHeader() + renderVenueDetail(poi);
    _bindDetailBack();
    const sheet = document.getElementById("sheet");
    if (sheet.classList.contains("sheet-peek")) sheet.classList.replace("sheet-peek", "sheet-half");
    if (poi.lat && poi.lon) {
      pulseMarker(new kakao.maps.LatLng(poi.lat, poi.lon));
      panToWithSheetOffset(poi.lat, poi.lon);
    }
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
  const externalRatingLine = renderExternalRatings(poi);
  const excerpt = poi.excerpt || poi.description;

  const mapLink = `https://map.kakao.com/link/to/${encodeURIComponent(poi.title)},${poi.lat},${poi.lon}`;

  $list.innerHTML = _detailHeader() + `
    <div class="card${isFavorite ? " favorite-detail" : ""}" style="border-left:3px solid ${catDef.color || "#888"}">
      ${favKicker}
      ${imageTag(poi.image)}
      <div class="card-title">${catDef.icon ? icon(catDef.icon) : (catDef.emoji || "")} ${escape(poi.title)}</div>
      ${favNote}
      <div class="card-meta">${catDef.label || poi.category}${poi.subtype ? " · " + escape(poi.subtype) : ""}${poi.address ? " · " + escape(poi.address) : ""}</div>
      ${ratingLine}
      ${externalRatingLine}
      ${dateLine}
      ${weatherLine}
      ${beachLine}
      ${poi.menu ? `<div class="card-meta foody-menu">${icon("ph-bowl-food")} 대표메뉴 · ${escape(poi.menu)}</div>` : ""}
      ${poi.gugun && !poi.address?.includes(poi.gugun) ? `<div class="card-meta">${icon("ph-map-pin")} ${escape(poi.gugun)}</div>` : ""}
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
  _bindDetailBack();

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

// ───────── 전시/공연 venue 그룹 상세 — 현재 열리는 행사 목록 ─────────
function renderVenueDetail(poi) {
  const target = currentTargetDate || new Date();
  const active = [], upcoming = [], past = [];
  for (const e of poi.events || []) {
    const k = classifyFestival(e, target);
    if (k === "active") active.push(e);
    else if (k === "upcoming") upcoming.push(e);
    else past.push(e);
  }
  active.sort((a, b) => (a.end || a.start || "").localeCompare(b.end || b.start || ""));
  upcoming.sort((a, b) => (a.start || "").localeCompare(b.start || ""));
  const catDef = CATEGORIES[poi.category] || {};
  const catLabel = poi.category === "exhibition" ? "전시" : "공연";
  const MS = 86400000;
  const t = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  const venueEventRow = (e, kind) => {
    const start = (e.start || "").slice(5);
    const end = (e.end || "").slice(5);
    const dateRange = start && end && end !== start ? `${start}~${end}` : (start || "");
    let dBadge = "";
    if (kind === "active") {
      const endD = parseDate(e.end) || parseDate(e.start);
      if (endD) {
        const left = Math.max(0, Math.round((endD - t) / MS));
        dBadge = left === 0 ? "오늘 종료" : `D-${left} 종료`;
      } else dBadge = "진행중";
    } else if (kind === "upcoming") {
      const startD = parseDate(e.start);
      const d = Math.max(0, Math.round((startD - t) / MS));
      dBadge = d === 0 ? "오늘 시작" : `D-${d}`;
    }
    return `<div class="venue-event">
      <div class="venue-event-title">${escape(e.title || "")}</div>
      <div class="venue-event-meta">
        ${dBadge ? `<span class="venue-event-d${kind === "active" ? " is-active" : ""}">${escape(dBadge)}</span>` : ""}
        <span>${escape(dateRange)}</span>
        ${e.url ? `<a href="${escape(e.url)}" target="_blank" rel="noopener">원문 →</a>` : ""}
      </div>
    </div>`;
  };
  const section = (title, items, kind) => items.length ? `
    <div class="venue-section">
      <div class="venue-section-title">${title}</div>
      ${items.map(e => venueEventRow(e, kind)).join("")}
    </div>` : "";
  const mapLink = `https://map.kakao.com/link/to/${encodeURIComponent(poi.title)},${poi.lat},${poi.lon}`;
  return `
    <div class="card" style="border-left:3px solid ${catDef.color}">
      <div class="card-title">${icon(catDef.icon || "ph-map-pin")} ${escape(poi.title)}</div>
      <div class="card-meta">${escape(catLabel)} 공간 · 진행 ${active.length} · 예정 ${upcoming.length}${past.length ? " · 지난 " + past.length : ""}</div>
      ${poi.address ? `<div class="card-meta">${icon("ph-map-pin")} ${escape(poi.address)}</div>` : ""}
      ${section(`🔴 지금 진행중 ${active.length}건`, active, "active")}
      ${section(`📅 예정 ${upcoming.length}건`, upcoming, "upcoming")}
      ${!active.length && !upcoming.length ? `<div class="card-meta" style="margin-top:12px">현재/예정 행사 없음 ${past.length ? `(지난 행사 ${past.length}건)` : ""}</div>` : ""}
      <div style="margin-top:12px">
        <a href="${mapLink}" target="_blank" style="padding:6px 10px;background:#fee500;color:#000;border-radius:6px;text-decoration:none;font-size:12px">${icon("ph-map-pin")} 카카오맵 길찾기</a>
      </div>
    </div>
  `;
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
    "naver_blog:cooolbusan": "네이버 블로그 · 부산광역시",
    "naver_blog:bscf2009":   "네이버 블로그 · 부산문화재단",
    "naver_blog:hudpr":      "네이버 블로그 · 해운대구청",
    "naver_blog:moca_busan": "네이버 블로그 · 부산현대미술관",
    "naver_blog:bsbukgusns": "네이버 블로그 · 북구청",
    "naver_blog:bsjunggu":   "네이버 블로그 · 중구청",
    "naver_blog:yeonjegu":   "네이버 블로그 · 연제구청",
    "naver_blog:bsdonggublog": "네이버 블로그 · 동구청",
  };
  return map[source] || (source.startsWith("naver_") ? "네이버 공식 콘텐츠" : source);
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
  const [manifest, places, weatherShort, beaches, courses, seasonal, favorites, guides] = await Promise.all([
    fetchJson("./data/manifest.json"),
    fetchJson("./data/places.json"),
    fetchJson("./data/weather-short.json"),
    fetchJson("./data/beaches.json"),
    fetchJson("./data/courses.json").catch(() => ({ courses: [] })),
    fetchJson("./data/seasonal.json").catch(() => ({ months: {} })),
    fetchJson("./data/my-favorites.json").catch(() => ({ favorites: [] })),  // 구글 별표 import (파일 없으면 빈 배열)
    fetchJson("./data/guides.json").catch(() => ({ guides: [] })),  // visitbusan 매거진 가이드 (지도 마커 X, 읽을거리 카드)
  ]);
  coursesData = courses;
  window.__seasonal = seasonal;
  window.__favorites = favorites;
  window.__guides = guides?.guides || [];

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
  // festival 은 이벤트 단위 마커, exhibition/performance 는 venue 로 aggregate
  // → 한 venue(F1963, 영화의전당 등) 에 여러 전시가 있을 때 마커 1개로 묶고
  //   클릭 시 현재 열리는 전시/공연 목록을 보여주기 위함
  const festivalOnly = allEvents.filter(e =>
    e.category === "festival" && e.lat && e.lon
  );
  const exhibPerfRaw = allEvents.filter(e =>
    ["exhibition", "performance"].includes(e.category) && e.lat && e.lon
  );
  const venueGroupsMap = new Map();
  for (const e of exhibPerfRaw) {
    const latKey = e.lat.toFixed(4), lonKey = e.lon.toFixed(4);
    const key = `${e.category}|${latKey}_${lonKey}|${e.venue || ""}`;
    let g = venueGroupsMap.get(key);
    if (!g) {
      g = {
        id: `venue:${key}`,
        isVenueGroup: true,
        category: e.category,
        title: e.venue || e.title || "장소 미정",
        venue: e.venue,
        address: e.address,
        lat: e.lat,
        lon: e.lon,
        events: [],
      };
      venueGroupsMap.set(key, g);
    }
    g.events.push(e);
  }
  const venueGroups = [...venueGroupsMap.values()];
  const allFestivalEvents = [...festivalOnly, ...venueGroups];
  // 네이버 블로그 — category=blog_post/exhibition/performance 인 것만 (festival 은 위에 포함됨)
  const allBlogMarkers = allEvents
    .filter(e =>
      (e.source || "").startsWith("naver_blog") &&
      e.category !== "festival" &&
      e.lat && e.lon
    )
    .map(e => ({ ...e, category: "blog" }));
  // 읽을거리 탭 — 소스 신뢰도 반영된 blog_priority 기반 정렬 + 동일 제목군 디덕스
  const rawBlog = allEvents.filter(e =>
    (e.source && e.source.startsWith("naver_blog"))
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
  // 정렬: 게시일(start) DESC = 최신순. 같은 날짜는 blog_priority 보조키.
  const allBlogPosts = [...bestByKey.values()].sort((a, b) => {
    const cmp = (b.start || "").localeCompare(a.start || "");
    if (cmp !== 0) return cmp;
    const pa = a.blog_priority ?? a.priority ?? 0;
    const pb = b.blog_priority ?? b.priority ?? 0;
    return pb - pa;
  });
  window.__blogPosts = allBlogPosts;

  // Phase 3: 좌표 없는 행사도 시트에 노출하기 위해 카테고리 기반 전체 수집
  const allEventPoi = allEvents.filter(e =>
    ["festival", "exhibition", "performance"].includes(e.category)
  );

  weatherIndex = buildWeatherIndex(weatherShort);
  const favArr = favorites?.favorites || [];

  // Phase D — AI 요약 fetch (Gemini 2.5 Flash 매일 갱신, 미존재 시 무시)
  window.__aiSummary = await fetchJson("./data/ai-summary.json").catch(() => null);

  window.__data = { manifest, places, weatherShort, beaches, courses, favorites: favArr, festivalEvents: allFestivalEvents, blogMarkers: allBlogMarkers, allEventPoi };

  renderMarkers(places, beaches, allFestivalEvents, allBlogMarkers, favArr);

  const totalPoi = (places.places?.length || 0) + (beaches.beaches?.length || 0);
  $status.textContent = `${totalPoi}개 POI · 날씨 격자 ${weatherShort.cells || 0}개`;
  renderFreshness(manifest);

  // 초기: 오늘의 부산 하이라이트 (applyDateFilter 가 곧 다시 호출)
  renderTodayHighlights(new Date());

  // Phase E — 카테고리 필터 collapse 토글 (default 닫힘, 헤더 슬림화)
  const filterToggle = document.getElementById("filter-toggle");
  const filterRow = document.getElementById("filter-row");
  if (filterToggle && filterRow) {
    filterToggle.addEventListener("click", () => {
      const opening = filterRow.hidden;
      filterRow.hidden = !opening;
      filterToggle.setAttribute("aria-expanded", String(opening));
      const caret = filterToggle.querySelector(".ft-caret");
      if (caret) caret.textContent = opening ? "⏶" : "⏷";
    });
  }

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

  // 초기 뷰: URL 해시 우선, 없으면 'today' (default)
  const hashView = (location.hash || "").replace("#", "");
  const initView = (["today", "map", "course", "read"].includes(hashView)) ? hashView : "today";
  const initBtn = document.querySelector(`.tab[data-view="${initView}"]`);
  if (initBtn) {
    document.querySelectorAll(".tab[data-view]").forEach(b => b.classList.remove("active"));
    initBtn.classList.add("active");
    setViewMode(initView);
  }
}

function setViewMode(mode) {
  // body.dataset.view 가 "today/map/course/read" — CSS 가 #map hidden 등 자동 처리
  document.body.dataset.view = mode;
  document.body.classList.toggle("view-read", mode === "read" || mode === "course");
  document.body.classList.toggle("view-blog", mode === "read");
  document.body.classList.toggle("view-course", mode === "course");
  document.body.classList.toggle("view-today", mode === "today");
  const sheet = document.getElementById("sheet");
  if (mode === "today") {
    // 핵심 정보 풀 — sheet 가 화면 전체 차지하도록 full 스냅
    ["sheet-peek", "sheet-half"].forEach(c => sheet.classList.remove(c));
    sheet.classList.add("sheet-full");
    renderTodayHighlights(currentTargetDate);
    clearCourseOverlay();
  } else if (mode === "read") {
    ["sheet-peek", "sheet-half"].forEach(c => sheet.classList.remove(c));
    sheet.classList.add("sheet-full");
    renderBlogFeed();
  } else if (mode === "course") {
    ["sheet-peek", "sheet-half"].forEach(c => sheet.classList.remove(c));
    sheet.classList.add("sheet-full");
    renderCourseList();
  } else {
    // map 뷰 — 마커 보기 위주, sheet 는 peek 으로
    sheet.classList.remove("sheet-full");
    sheet.classList.add("sheet-peek");
    // 마커 상호작용 위해 카드는 비워둠 (마커 클릭 시 detail 노출)
    $list.innerHTML = `<div class="map-hint card"><div class="card-meta">${icon("ph-cursor-click")} 지도 마커를 눌러 상세를 확인하세요.</div></div>`;
    clearCourseOverlay();
    // Kakao Map relayout — 숨겼다가 보이면 paint 갱신
    if (window.kakao?.maps?.Map && map) setTimeout(() => map.relayout(), 50);
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
    const storyBtn = c.story_url
      ? `<a class="course-link" href="${escape(c.story_url)}" target="_blank" rel="noopener">${icon("ph-book-open-text")} 비짓부산에서 보기 →</a>`
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
        ${storyBtn}
      </div>
    </div>`;
  }).join("");

  // 카드 본문 클릭 → 지도에 POI 폴리라인. story 링크 클릭은 stopPropagation 으로 새 탭만.
  $list.querySelectorAll(".course-link").forEach(a => {
    a.addEventListener("click", e => e.stopPropagation());
  });
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
  const blogs = window.__blogPosts || [];
  const guides = window.__guides || [];
  // 가이드는 view_count(rating·views) 우선, 블로그는 blog_priority 정렬됨. 합쳐서 가이드 먼저 + 블로그.
  const guideItems = guides.map(g => ({ ...g, _kind: "guide" }));
  const blogItems = blogs.map(b => ({ ...b, _kind: "blog" }));
  const posts = [...guideItems, ...blogItems];
  if (!posts.length) {
    $list.innerHTML = `<div class="card"><div class="card-meta">읽을거리 데이터 없음</div></div>`;
    return;
  }

  // P3 — 중요도 정렬(priority → 이미지 → 날짜). Top 3 은 hero_tags 칩으로 규모 강조
  $list.innerHTML = posts.slice(0, 120).map((p, i) => {
    const isGuide = p._kind === "guide";
    const src = isGuide ? "비짓부산 매거진" : (p.source || "").replace("naver_blog:", "");
    const date = (p.start || "").slice(0, 10);
    const label = isGuide ? "GUIDE · 비짓부산 매거진"
                : p.category === "festival" ? "FESTIVAL · 축제"
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
    const url = p.url || p.story_url;
    const linkLabel = isGuide ? "📖 비짓부산 →" : "원문 →";
    return `<article class="blog-card${featured}${isGuide ? " blog-card-guide" : ""}">
      <div class="blog-card-category">${escape(label)}</div>
      ${tagHTML}
      <h3 class="blog-card-title">${escape(p.title)}</h3>
      ${lead ? `<p class="blog-card-lead">${lead}</p>` : ""}
      <div class="blog-card-meta">
        <span>${escape(src)}${date ? " · " + escape(date) : ""}</span>
        ${url ? `<a class="blog-card-readmore" href="${escape(url)}" target="_blank" rel="noopener">${linkLabel}</a>` : ""}
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

// ───────── 사전 예약 휴리스틱 ─────────
// description/url/title 키워드로 booking_required 추정. DB 의 booking_required=1 우선.
const _BOOKING_KEYWORDS = /예매|티켓팅|티켓 오픈|사전신청|사전 신청|선착|온라인 신청|예약 필수|예약필수|선예매|티켓 예매/;
function _bookingRequired(p) {
  if (p.booking_required === 1 || p.booking_required === true) return true;
  const blob = `${p.title || ""} ${p.description || ""} ${p.url || ""}`;
  return _BOOKING_KEYWORDS.test(blob);
}

// ───────── AI Pick 카드 (Phase D) — ai-summary.json 4 segment ─────────
function _aiSegmentKey(target) {
  const ai = window.__aiSummary;
  if (!ai?.dates) return "today";
  const tStr = `${target.getFullYear()}-${String(target.getMonth()+1).padStart(2,"0")}-${String(target.getDate()).padStart(2,"0")}`;
  if (tStr === ai.dates.today) return "today";
  if (tStr === ai.dates.tomorrow) return "tomorrow";
  if (tStr === ai.dates.weekend) return "weekend";
  if (tStr === ai.dates.next_weekend) return "next_weekend";
  return "today";
}
const _AI_SEG_LABEL = { today: "오늘", tomorrow: "내일", weekend: "이번 주말", next_weekend: "다음 주말" };

// B3 — AI picks title → places 의 menu/gugun lookup
function _buildPlaceIndex() {
  if (window._placeMenuIdx) return window._placeMenuIdx;
  const idx = {};
  for (const p of (window.__data?.places?.places || [])) {
    if (p.title && (p.menu || p.gugun)) {
      idx[p.title] = { menu: p.menu, gugun: p.gugun, category: p.category };
    }
  }
  window._placeMenuIdx = idx;
  return idx;
}

function renderAiPickCard(target) {
  const ai = window.__aiSummary;
  if (!ai) return "";
  const segKey = _aiSegmentKey(target);
  const seg = ai[segKey] || ai.today;
  if (!seg || !seg.summary) return "";
  const tag = _AI_SEG_LABEL[segKey] || "오늘";
  const wx = ai.weather?.[segKey];
  const placeIdx = _buildPlaceIndex();
  const picksHTML = (seg.picks || []).slice(0, 3).map(p => {
    const meta = placeIdx[p.title];
    const menuLine = meta?.menu ? `<span class="ai-pick-menu">🍴 ${escape(meta.menu.slice(0, 40))}</span>` : "";
    const gugunLine = meta?.gugun ? `<span class="ai-pick-gugun">📍 ${escape(meta.gugun)}</span>` : "";
    const extras = [menuLine, gugunLine].filter(Boolean).join(" ");
    return `<li><strong>${escape(p.title || "")}</strong>${p.why ? ` — ${escape(p.why)}` : ""}${extras ? `<br>${extras}` : ""}</li>`;
  }).join("");
  const courses = (ai.courses || []).slice(0, 3);
  const courseTabs = courses.length
    ? `<div class="ai-courses">${courses.map((c, i) =>
        `<details class="ai-course"${i === 0 ? " open" : ""}>
          <summary>${escape(c.label || "코스")}${c.title ? ` · ${escape(c.title)}` : ""}</summary>
          ${(c.stops || []).length ? `<ol class="ai-stops">${c.stops.map(s => `<li>${escape(s)}</li>`).join("")}</ol>` : ""}
          ${c.note ? `<p class="ai-course-note">${escape(c.note)}</p>` : ""}
        </details>`).join("")}</div>`
    : "";
  return `<article class="ai-pick" aria-label="AI ${escape(tag)}의 부산 추천">
    <div class="ai-pick-label">🤖 AI Pick · ${escape(tag)}의 부산${wx ? ` · ${escape(wx)}` : ""}</div>
    <p class="ai-pick-summary">${escape(seg.summary)}</p>
    ${picksHTML ? `<ul class="ai-pick-list">${picksHTML}</ul>` : ""}
    ${courseTabs}
  </article>`;
}

// ───────── 🆕 신규 추가 섹션 (Phase v3.5) — 식당/카페/공연/전시/축제 통합 ─────────
// 데이터: source='naver_local' (네이버 동네 신상) + first_seen 최근 14일 모든 카테고리
function _newItemsPool() {
  const places = window.__data?.places?.places || [];
  const events = window.__data?.allEventPoi || [];
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 14);
  const cutoffIso = cutoff.toISOString().slice(0, 10);
  const pool = [];
  // food/cafe — naver_local source 우선, 그 외는 first_seen 최근만
  for (const p of places) {
    if (p.source === "naver_local") {
      pool.push({ ...p, _newKind: "신상" });
      continue;
    }
    if ((p.first_seen || "").slice(0, 10) >= cutoffIso) {
      pool.push({ ...p, _newKind: "최근 추가" });
    }
  }
  // events — first_seen 최근만
  for (const e of events) {
    if ((e.first_seen || "").slice(0, 10) >= cutoffIso) {
      pool.push({ ...e, _newKind: "최근 추가" });
    }
  }
  // dedup by id
  const seen = new Set();
  const unique = [];
  for (const x of pool) {
    if (seen.has(x.id)) continue;
    seen.add(x.id);
    unique.push(x);
  }
  // 정렬: ① 공연/전시/축제 우선 → ② 신상 source → ③ first_seen DESC
  const CAT_RANK = { performance: 0, exhibition: 0, festival: 1, attraction: 2, food: 3, cafe: 4 };
  unique.sort((a, b) => {
    const ra = CAT_RANK[a.category] ?? 5;
    const rb = CAT_RANK[b.category] ?? 5;
    if (ra !== rb) return ra - rb;
    const sa = a._newKind === "신상" ? 1 : 0;
    const sb = b._newKind === "신상" ? 1 : 0;
    if (sa !== sb) return sb - sa;
    return (b.first_seen || "").localeCompare(a.first_seen || "");
  });
  return unique;
}

function _newItemHTML(p, idx) {
  const cat = CATEGORIES[p.category] || {};
  const emoji = cat.emoji || "📌";
  const venue = p.gugun || p.venue || (p.address || "").split(" ").slice(1, 2).join("") || "";
  const meta = p.description ? p.description.slice(0, 35) : (p.start ? p.start.slice(5) : "");
  return `<button class="new-card" data-idx="${idx}">
    <span class="new-badge ${p._newKind === "신상" ? "is-naver" : ""}">🆕 ${escape(p._newKind)}</span>
    <div class="new-title">${emoji} ${escape(p.title || "(제목 없음)")}</div>
    <div class="new-meta">${escape(venue)}${meta ? " · " + escape(meta) : ""}</div>
  </button>`;
}

// ───────── 🔥 인기 큐레이션 (popularity_score 기반, v3.7) ─────────
function _formatK(n) {
  if (!n) return "";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : n.toLocaleString();
}

function _popularFoodPool(limit = 10) {
  const places = window.__data?.places?.places || [];
  return places
    .filter(p => (p.category === "food" || p.category === "cafe") && (p.popularity_score || 0) > 0)
    .sort((a, b) => (b.popularity_score || 0) - (a.popularity_score || 0))
    .slice(0, limit);
}

function _popularEventsPool(target, limit = 10) {
  const events = window.__data?.allEventPoi || [];
  const t = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  const weekEnd = new Date(t);
  weekEnd.setDate(weekEnd.getDate() + 7);

  const isCultural = e => e.category === "exhibition" || e.category === "performance";
  const cand = events.filter(e => {
    if (!isCultural(e)) return false;
    const start = parseDate(e.start); if (!start) return false;
    const end = parseDate(e.end) || start;
    return !(end < t || start > weekEnd);
  });
  let pool = cand;
  if (pool.length < limit) {
    // 폴백: 향후 3개월 upcoming 공연/전시 TOP
    const horizon = new Date(t); horizon.setMonth(horizon.getMonth() + 3);
    const future = events.filter(e => {
      if (!isCultural(e)) return false;
      const start = parseDate(e.start); if (!start) return false;
      return start >= t && start <= horizon;
    });
    pool = future;
  }
  return pool
    .sort((a, b) => (b.popularity_score || 0) - (a.popularity_score || 0))
    .slice(0, limit);
}

function _popularItemHTML(p, idx, kind) {
  const cat = CATEGORIES[p.category] || {};
  const emoji = cat.emoji || "📌";
  const trailing = kind === "food"
    ? (p.naver_reviews ? `📝 ${_formatK(p.naver_reviews)}` : (p.gugun || ""))
    : (p.start ? `${(p.start || "").slice(5)}${p.end && p.end !== p.start ? "~" + (p.end || "").slice(5) : ""}` : (p.venue || ""));
  const sub = kind === "food"
    ? (p.gugun ? escape(p.gugun) : "")
    : (p.venue ? escape(p.venue) : "");
  const thumb = p.image
    ? `<img class="popular-thumb" src="${escape(p.image)}" loading="lazy" onerror="this.style.display='none'" alt="">`
    : `<div class="popular-thumb popular-thumb-empty">${emoji}</div>`;
  return `<button class="popular-card" data-idx="${idx}" data-kind="${kind}">
    ${thumb}
    <div class="popular-rank">${idx + 1}</div>
    <div class="popular-body">
      <div class="popular-title">${escape(p.title || "(제목 없음)")}</div>
      <div class="popular-meta">${trailing}${sub ? " · " + sub : ""}</div>
    </div>
  </button>`;
}

// ───────── Phase E 재배치: 한눈에 들어오는 "오늘/이번주말 뭐할지" ─────────
// 새 순서: ① AI Pick → ② Hero Top 3 → ③ 🆕 신규 → ④ D-30 사전예약 → ⑤ 제철 → ⑥ 그 외 → ⑦ STORY
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

  // D-30 사전 예약 — combined 인덱스 보존(클릭 시 detail 매핑)
  const t = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  const reservations = [];
  for (let i = 0; i < combined.length; i++) {
    const p = combined[i];
    if (p._k !== "upcoming") continue;
    if (!_bookingRequired(p)) continue;
    const start = parseDate(p.start);
    if (!start) continue;
    const daysTo = Math.round((start - t) / 86400000);
    if (daysTo < 1 || daysTo > 30) continue;
    reservations.push({ poi: p, idx: i, daysTo });
  }
  reservations.sort((a, b) => a.daysTo - b.daysTo);

  const season = (window.__seasonal?.months || {})[month];
  const today = new Date();
  const isToday = target.toDateString() === today.toDateString();
  const days = ["일", "월", "화", "수", "목", "금", "토"];
  const heroDate = isToday ? "오늘" : `${target.getMonth() + 1}월 ${target.getDate()}일 (${days[target.getDay()]})`;
  const heroSub = season?.title || "부산 여행";

  const topBar = `<div class="highlight-hero">
    <div class="hh-date">${escape(heroDate)} · 부산</div>
    <div class="hh-sub">${escape(heroSub)} · 추천 ${combined.length}건${reservations.length ? ` · 🗓 사전예약 ${reservations.length}` : ""}</div>
  </div>`;

  // ① AI Pick
  const aiPickHTML = renderAiPickCard(target);

  // ② Hero Top 3
  let heroHTML;
  if (hero.length) {
    heroHTML = `<div class="highlight-section hl-hero-section">
      <div class="hs-title">⭐ ${isToday ? "오늘의" : "이 날의"} 추천 Top ${hero.length}</div>
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

  // ③ 🔥 인기 맛집 TOP 10 (popularity_score 기반)
  const popularFood = _popularFoodPool(10);
  const popularFoodHTML = popularFood.length >= 3
    ? `<div class="highlight-section popular-section">
        <div class="hs-title">🔥 인기 맛집·카페 TOP ${popularFood.length}</div>
        <div class="hs-note">네이버 블로그 언급 수 + 평점 종합</div>
        <div class="popular-grid">${popularFood.map((p, i) => _popularItemHTML(p, i, "food")).join("")}</div>
      </div>`
    : "";

  // ④ 🎭 이번주 공연/전시 TOP 10
  const popularEvents = _popularEventsPool(target, 10);
  const popularEventsHTML = popularEvents.length >= 2
    ? `<div class="highlight-section popular-section popular-events">
        <div class="hs-title">🎭 이번주 공연·전시 TOP ${popularEvents.length}</div>
        <div class="hs-note">부산 메이저 venue 중심 · ${popularEvents.some(e => parseDate(e.start) && parseDate(e.start) >= new Date(target.getFullYear(), target.getMonth(), target.getDate() + 7)) ? "다가오는 3개월 포함" : "이번주 진행 중"}</div>
        <div class="popular-grid">${popularEvents.map((p, i) => _popularItemHTML(p, i, "event")).join("")}</div>
      </div>`
    : "";

  // ⑤ 🆕 신규 추가 (식당/카페/공연/전시/축제 통합)
  const newItems = _newItemsPool();
  let newHTML = "";
  if (newItems.length) {
    const initial = 6;
    const head = newItems.slice(0, initial);
    const extra = newItems.slice(initial);
    const extraHTML = extra.length
      ? `<div class="new-extra" hidden>${extra.map((p, i) => _newItemHTML(p, i + initial)).join("")}</div>
         <button class="new-more chip-more" type="button">+${extra.length}건 더 보기</button>`
      : "";
    newHTML = `<div class="highlight-section new-section">
      <div class="hs-title">🆕 새로 추가된 곳 ${newItems.length}건 — 공연·전시·식당·카페</div>
      <div class="hs-note">최근 2주 신규 등록 행사 + 네이버 동네 신상 (공연/전시 우선)</div>
      <div class="new-grid">${head.map((p, i) => _newItemHTML(p, i)).join("")}</div>
      ${extraHTML}
    </div>`;
  }

  // ④ D-30 사전 예약
  let reservationHTML = "";
  if (reservations.length) {
    reservationHTML = `<div class="highlight-section reservation-section">
      <div class="hs-title">🗓 사전 예약 권장 · D-30 이내 ${reservations.length}건</div>
      <div class="hs-note">예매·티켓팅·사전신청 키워드 매칭. 미리 알아둬야 자리 잡혀요.</div>
      <div class="chip-list">${reservations.map(({ poi, idx, daysTo }) =>
        reservationChipHTML(poi, idx, daysTo)
      ).join("")}</div>
    </div>`;
  }

  // ④ 제철
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

  // ⑤ 그 외 행사
  let tailHTML = "";
  if (tail.length) {
    const initial = 6;
    const firstBatch = tail.slice(0, initial);
    const extra = tail.slice(initial);
    const extraHTML = extra.length
      ? `<div class="chip-extra" hidden>${extra.map((p, i) => chipHTML(p, i + initial + 3, target)).join("")}</div>
         <button class="chip-more" type="button">+${extra.length}건 더 보기</button>`
      : "";
    tailHTML = `<div class="highlight-section">
      <div class="hs-title">📋 그 외 행사 ${tail.length}건</div>
      <div class="chip-list">${firstBatch.map((p, i) => chipHTML(p, i + 3, target)).join("")}</div>
      ${extraHTML}
    </div>`;
  }

  // ⑥ STORY
  const storyHero = renderNarrativeHero();

  $list.innerHTML = aiPickHTML + topBar + heroHTML + popularFoodHTML + popularEventsHTML + newHTML + reservationHTML + seasonHTML + tailHTML + storyHero;

  // 🔥/🎭 인기 카드 클릭 → showDetail
  $list.querySelectorAll(".popular-card").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.idx);
      const kind = btn.dataset.kind;
      const item = kind === "food" ? popularFood[idx] : popularEvents[idx];
      if (item) showDetail(item);
    });
  });

  // 🆕 신규 카드 클릭 → showDetail (places/events 의 원래 객체 사용)
  $list.querySelectorAll(".new-card").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.idx);
      const item = newItems[idx];
      if (item) showDetail(item);
    });
  });
  // 신규 더보기
  const newMoreBtn = $list.querySelector(".new-more");
  if (newMoreBtn) {
    newMoreBtn.addEventListener("click", () => {
      const ext = $list.querySelector(".new-extra");
      if (ext) ext.hidden = false;
      newMoreBtn.remove();
    });
  }

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

// Phase C — D-30 마일스톤 색상 차별화 (D-7 빨강 / D-14 주황 / D-30 마젠타)
function reservationChipHTML(p, idx, daysTo) {
  const mile = daysTo <= 7 ? "d-7" : daysTo <= 14 ? "d-14" : "d-30";
  return `<button class="chip chip-reservation chip-${mile}" data-idx="${idx}">
    <span class="chip-d chip-d-${mile}">D-${daysTo}</span>
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
  // C1: 라벨 명확화 — 진행중 / 임박(2개월내) / 제철 분리 표시
  const activeN = active || 0, upcomingN = upcoming || 0;
  const bits = [];
  if (activeN) bits.push(`진행중 ${activeN}`);
  if (upcomingN) bits.push(`임박 ${upcomingN}`);
  if (!bits.length) bits.push("행사 0");
  const eventsStr = `🎪 ${bits.join(" · ")}`;
  const seasonStr = seasonCount ? ` · 🍽 제철 ${seasonCount}가지` : "";
  parts.push(`<span class="db-sep">·</span><span class="db-stats">${eventsStr}${seasonStr}</span>`);

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
