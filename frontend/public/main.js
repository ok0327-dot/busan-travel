// 부산 트래블 MVP — Kakao Maps 기반 지도 대시보드
// Task #8 스캐폴드 + Task #9 마커/클러스터러/상세 드로어 + 날씨 배지.

const cfg = window.APP_CONFIG;
if (!cfg || !cfg.KAKAO_JS_KEY) {
  alert("config.js 가 없거나 KAKAO_JS_KEY 가 비어있어요.");
  throw new Error("Missing APP_CONFIG");
}

const CATEGORIES = {
  festival:    { label: "축제",     emoji: "🎪", color: "#ef4444" },
  attraction:  { label: "명소",     emoji: "🏛", color: "#3b82f6" },
  food:        { label: "맛집",     emoji: "🍜", color: "#f97316" },
  beach:       { label: "해수욕장", emoji: "🏖", color: "#06b6d4" },
  shopping:    { label: "쇼핑",     emoji: "🛍", color: "#a855f7" },
  lodging:     { label: "숙박",     emoji: "🏨", color: "#10b981" },
  theme:       { label: "테마",     emoji: "💡", color: "#f59e0b" },
  info_office: { label: "안내소",   emoji: "ℹ️", color: "#6b7280" },
};
const HOTEL_GRADE_BADGE = {
  "관광호텔 5성": "⭐⭐⭐⭐⭐",
  "관광호텔 4성": "⭐⭐⭐⭐",
  "관광호텔 3성": "⭐⭐⭐",
  "관광호텔 2성": "⭐⭐",
  "관광호텔 1성": "⭐",
};

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

// ───────── SVG 마커 생성 ─────────
function svgMarker(color, emoji) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="42" viewBox="0 0 32 42">
    <path d="M16 0C7.2 0 0 7.2 0 16c0 11.5 16 26 16 26s16-14.5 16-26C32 7.2 24.8 0 16 0z" fill="${color}" stroke="white" stroke-width="2"/>
    <circle cx="16" cy="16" r="9" fill="white"/>
    <text x="16" y="21" text-anchor="middle" font-size="14">${emoji}</text>
  </svg>`;
  return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
}

function markerImageFor(category) {
  const cat = CATEGORIES[category] || CATEGORIES.attraction;
  return new kakao.maps.MarkerImage(
    svgMarker(cat.color, cat.emoji),
    new kakao.maps.Size(32, 42),
    { offset: new kakao.maps.Point(16, 42) }
  );
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

  const image = markerImageFor(cat);
  const markers = items.map(poi => {
    const marker = new kakao.maps.Marker({
      position: new kakao.maps.LatLng(poi.lat, poi.lon),
      image,
      title: poi.title,
    });
    kakao.maps.event.addListener(marker, "click", () => showDetail(poi));
    return { marker, poi };
  });

  const clusterer = new kakao.maps.MarkerClusterer({
    map,
    averageCenter: true,
    minLevel: 7,
    gridSize: 80,
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

function renderMarkers(places, beaches, festivalEvents, lodging) {
  // beaches → POI 형태
  const beachRows = (beaches.beaches || []).map(b => ({
    id: "beach:" + b.name,
    category: "beach",
    title: b.name,
    lat: b.lat, lon: b.lon,
    address: "",
    latest_water: b.latest_water,
  }));

  // places 는 food/attraction/info_office/shopping/theme 혼합
  const all = [
    ...(places.places || []),
    ...(lodging?.lodging || []).map(l => ({ ...l, category: "lodging" })),
    ...beachRows,
    ...festivalEvents.map(e => ({ ...e, category: "festival" })),
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
  if (!clusterer) return;

  let active = 0, upcoming = 0, unknown = 0;
  const showMarkers = [];
  for (const { marker, poi } of allMarkers.festival || []) {
    const kind = classifyFestival(poi, target);
    if (kind === "active")   { active++;   showMarkers.push(marker); marker.setOpacity(1.0); }
    else if (kind === "upcoming") { upcoming++; showMarkers.push(marker); marker.setOpacity(0.55); }
    else if (kind === "unknown")  { unknown++;  showMarkers.push(marker); marker.setOpacity(0.55); }
  }
  clusterer.clear();
  clusterer.addMarkers(showMarkers);

  const ymd = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}-${String(target.getDate()).padStart(2, "0")}`;
  const total = (allMarkers.festival || []).length;
  $status.textContent = `📅 ${ymd} · 진행 ${active} · 2개월내 ${upcoming} · 미상 ${unknown} · 전체 ${total}`;
}

// ───────── 날씨 배지 (지도 level <= 5 에서 festival/beach 에만) ─────────
function refreshWeatherBadges(targetDate) {
  // 기존 overlay 제거
  for (const o of weatherOverlays) o.setMap(null);
  weatherOverlays = [];

  if (map.getLevel() > 5) return; // 너무 멀면 생략

  for (const cat of ["festival", "beach"]) {
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

function showDetail(poi) {
  const catDef = CATEGORIES[poi.category] || {};
  const now = new Date();
  const f = poi.nx && poi.ny ? nearestForecast(poi.nx, poi.ny, now) : null;
  const weatherLine = f
    ? `<div class="card-meta">${weatherBadge(f)} ${f.tmp ? f.tmp + "°C " : ""}${f.pop ? "POP " + f.pop + "%" : ""}</div>`
    : "";
  const dateLine = poi.start
    ? `<div class="card-meta">📅 ${poi.start}${poi.end && poi.end !== poi.start ? " ~ " + poi.end : ""}</div>`
    : "";
  const beachLine = poi.latest_water?.comment
    ? `<div class="card-meta">🌊 ${escape(poi.latest_water.comment)}</div>`
    : "";
  const hotelGrade = poi.subtype && HOTEL_GRADE_BADGE[poi.subtype]
    ? `<span style="margin-left:6px">${HOTEL_GRADE_BADGE[poi.subtype]}</span>`
    : "";
  const ratingLine = poi.rating
    ? `<div class="card-meta" style="margin-top:4px">${renderStars(poi.rating)}${poi.views ? ` · 조회 ${poi.views.toLocaleString()}` : ""}${poi.reviews ? ` · 리뷰 ${poi.reviews}` : ""}</div>`
    : "";
  const excerpt = poi.excerpt || poi.description;

  const mapLink = `https://map.kakao.com/link/to/${encodeURIComponent(poi.title)},${poi.lat},${poi.lon}`;

  $list.innerHTML = `
    <div class="card" style="border-left:3px solid ${catDef.color || "#888"}">
      <div class="card-title">${catDef.emoji || ""} ${escape(poi.title)}${hotelGrade}</div>
      <div class="card-meta">${catDef.label || poi.category}${poi.subtype && !HOTEL_GRADE_BADGE[poi.subtype] ? " · " + escape(poi.subtype) : ""}${poi.address ? " · " + escape(poi.address) : ""}</div>
      ${ratingLine}
      ${dateLine}
      ${weatherLine}
      ${beachLine}
      ${excerpt ? `<div class="card-excerpt">${escape(excerpt.slice(0, 280))}</div>` : ""}
      ${renderTags(poi.tags)}
      ${infoRow("🕐 영업", poi.hours)}
      ${infoRow("🚫 휴무", poi.holiday)}
      ${infoRow("💰 요금", poi.fee || poi.price)}
      ${infoRow("🚌 교통", poi.transport)}
      ${infoRow("💡 팁", poi.tip)}
      ${infoRow("📞 전화", poi.phone)}
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <a href="${mapLink}" target="_blank" style="padding:6px 10px;background:#fee500;color:#000;border-radius:6px;text-decoration:none;font-size:12px">🗺️ 카카오맵 길찾기</a>
        ${poi.story_url ? `<a href="${escape(poi.story_url)}" target="_blank" style="padding:6px 10px;background:#0ea5e9;color:#fff;border-radius:6px;text-decoration:none;font-size:12px">📖 비짓부산</a>` : ""}
        ${poi.url && poi.url !== poi.story_url ? `<a href="${escape(poi.url)}" target="_blank" style="padding:6px 10px;background:#374151;color:#fff;border-radius:6px;text-decoration:none;font-size:12px">🔗 홈페이지</a>` : ""}
      </div>
    </div>
  `;

  // 시트 half 로 올려서 상세 보이게
  const sheet = document.getElementById("sheet");
  if (sheet.classList.contains("sheet-peek")) {
    sheet.classList.replace("sheet-peek", "sheet-half");
  }

  // 지도 중심 이동
  map.panTo(new kakao.maps.LatLng(poi.lat, poi.lon));
}

// ───────── init ─────────
async function init() {
  $status.textContent = "지도 로딩 중…";
  await loadKakaoSDK();

  const mapEl = document.getElementById("map");
  const center = new kakao.maps.LatLng(cfg.BUSAN_CENTER.lat, cfg.BUSAN_CENTER.lon);
  map = new kakao.maps.Map(mapEl, { center, level: cfg.DEFAULT_LEVEL });
  window.__map = map;

  $status.textContent = "데이터 로딩 중…";
  const [manifest, places, weatherShort, beaches, lodging, courses] = await Promise.all([
    fetchJson("./data/manifest.json"),
    fetchJson("./data/places.json"),
    fetchJson("./data/weather-short.json"),
    fetchJson("./data/beaches.json"),
    fetchJson("./data/lodging.json").catch(() => ({ lodging: [] })),
    fetchJson("./data/courses.json").catch(() => ({ courses: [] })),
  ]);
  coursesData = courses;

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
  const allFestivalEvents = allEvents.filter(e => e.category === "festival" && e.lat && e.lon);
  const allBlogPosts = allEvents
    .filter(e => e.category === "blog_post" || (e.source && e.source.startsWith("naver_blog")))
    .sort((a, b) => (b.start || "").localeCompare(a.start || ""));
  window.__blogPosts = allBlogPosts;

  weatherIndex = buildWeatherIndex(weatherShort);
  window.__data = { manifest, places, weatherShort, beaches, lodging, courses, festivalEvents: allFestivalEvents };

  renderMarkers(places, beaches, allFestivalEvents, lodging);

  const totalPoi = (places.places?.length || 0) + (beaches.beaches?.length || 0);
  $status.textContent = `${totalPoi}개 POI · 날씨 격자 ${weatherShort.cells || 0}개 · ${manifest.generated_at?.slice(0, 10) || ""}`;

  // 초기 카드: 카테고리 요약
  renderCategorySummary();

  // 카테고리 필터 토글
  document.querySelectorAll(".filter input[data-cat]").forEach(chk => {
    chk.addEventListener("change", () => {
      const cat = chk.dataset.cat;
      const clusterer = clusterers[cat];
      if (!clusterer) return;
      if (chk.checked) clusterer.setMap(map);
      else clusterer.setMap(null);
    });
    // 초기: info_office 는 off (너무 많음 + 낮은 가치)
    if (!chk.checked && clusterers[chk.dataset.cat]) {
      clusterers[chk.dataset.cat].setMap(null);
    }
  });

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
    });
  });

  // 언어 토글: URL ?lang=en/ja/zh 면 모든 비짓부산 deep-link 를 해당 언어 경로로 다시 씀
  const urlLang = new URLSearchParams(location.search).get("lang") || "ko";
  window.__lang = urlLang;
  document.querySelectorAll(".lang-toggle a").forEach(a => {
    const isActive = a.dataset.lang === urlLang;
    a.classList.toggle("active", isActive);
  });
  if (urlLang !== "ko") {
    rewriteStoryUrls(urlLang);
  }
}

// 비짓부산 URL 의 lang_cd 파라미터 교체 (en/ja/zhs/zht 지원)
function rewriteStoryUrls(lang) {
  const map = { en: "en", ja: "ja", zh: "zhs" };
  const target = map[lang] || "ko";
  const rewrite = (url) => {
    if (!url || !url.includes("visitbusan.net")) return url;
    return url
      .replace(/\/kr\//, `/${target}/`)
      .replace(/lang_cd=ko/, `lang_cd=${target}`);
  };
  // places + lodging + courses 의 URL 들 일괄 재작성
  const d = window.__data;
  for (const p of (d.places?.places || [])) {
    p.story_url = rewrite(p.story_url);
    p.url = rewrite(p.url);
  }
  for (const l of (d.lodging?.lodging || [])) {
    l.story_url = rewrite(l.story_url);
    l.url = rewrite(l.url);
  }
  for (const c of (d.courses?.courses || [])) {
    c.story_url = rewrite(c.story_url);
  }
}

function setViewMode(mode) {
  document.body.classList.toggle("view-read", mode === "read" || mode === "course");
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
    renderCategorySummary();
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
    return `<div class="card course-card ${active}" data-uc="${c.uc_seq}">
      <div class="card-title">
        ${c.duration ? `<span class="course-badge">${escape(c.duration)}</span>` : ""}
        ${escape(c.title || "")}
      </div>
      <div class="card-meta">${poisCount}개 POI${c.views ? ` · 조회 ${c.views.toLocaleString()}` : ""}${c.rating ? ` · ★${c.rating}` : ""}</div>
      ${c.excerpt ? `<div class="card-excerpt">${escape(c.excerpt.slice(0, 160))}</div>` : ""}
      ${(c.tags || []).length ? `<div class="tag-chips">${c.tags.slice(0, 5).map(t => `<span class="tag-chip">#${escape(t)}</span>`).join("")}</div>` : ""}
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
  const allPlaces = [
    ...(window.__data.places.places || []),
    ...(window.__data.lodging?.lodging || []).map(l => ({ ...l, category: "lodging" })),
  ];
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
  $list.innerHTML = posts.slice(0, 100).map(p => {
    const src = (p.source || "").replace("naver_blog:", "");
    const date = p.start || "";
    return `<div class="card">
      <div class="card-title">${escape(p.title)}</div>
      <div class="card-meta">${src} · ${date}</div>
      ${p.description ? `<div class="card-meta" style="margin-top:4px">${escape(p.description.slice(0,120))}</div>` : ""}
      ${p.url ? `<a href="${escape(p.url)}" target="_blank" style="display:inline-block;margin-top:8px;padding:4px 10px;background:#374151;color:#fff;border-radius:6px;text-decoration:none;font-size:11px">원문 보기</a>` : ""}
    </div>`;
  }).join("");
}

function renderCategorySummary() {
  const counts = Object.fromEntries(
    Object.keys(CATEGORIES).map(c => [c, (allMarkers[c] || []).length])
  );
  $list.innerHTML = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([c, n]) => {
      const cd = CATEGORIES[c];
      return `<div class="card"><div class="card-title">${cd.emoji} ${cd.label}</div><div class="card-meta">${n}개 · 지도 마커를 탭하면 상세 보기</div></div>`;
    }).join("");
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

init().catch(err => {
  console.error("[busan-travel] init failed:", err);
  const msg = err?.message || err?.toString() || "알 수 없는 에러 (DevTools Console 확인)";
  $status.textContent = `로딩 실패: ${msg}`;
});
