// busan-travel JSON API v1 — 외부 콘텐츠 사이트가 read 하는 백본 인터페이스.
// spec: docs/api/openapi.yaml (Step 1.1)

const SCHEMA_VERSION = "1.0";

// 부산 16 자치구 — gugun 한글명 ↔ slug ↔ 중심 좌표 (대표 지점)
const AREAS = [
  { code: "haeundae",  name_ko: "해운대구", lat: 35.163, lon: 129.163 },
  { code: "suyeong",   name_ko: "수영구",   lat: 35.145, lon: 129.114 },
  { code: "busanjin",  name_ko: "부산진구", lat: 35.163, lon: 129.053 },
  { code: "jung",      name_ko: "중구",     lat: 35.106, lon: 129.032 },
  { code: "gijang",    name_ko: "기장군",   lat: 35.245, lon: 129.222 },
  { code: "dongnae",   name_ko: "동래구",   lat: 35.205, lon: 129.083 },
  { code: "dong",      name_ko: "동구",     lat: 35.130, lon: 129.045 },
  { code: "nam",       name_ko: "남구",     lat: 35.137, lon: 129.084 },
  { code: "yeongdo",   name_ko: "영도구",   lat: 35.091, lon: 129.068 },
  { code: "gangseo",   name_ko: "강서구",   lat: 35.212, lon: 128.981 },
  { code: "yeonje",    name_ko: "연제구",   lat: 35.176, lon: 129.080 },
  { code: "sasang",    name_ko: "사상구",   lat: 35.151, lon: 128.991 },
  { code: "geumjeong", name_ko: "금정구",   lat: 35.243, lon: 129.092 },
  { code: "saha",      name_ko: "사하구",   lat: 35.105, lon: 128.974 },
  { code: "buk",       name_ko: "북구",     lat: 35.197, lon: 129.012 },
  { code: "seo",       name_ko: "서구",     lat: 35.097, lon: 129.024 },
];
const AREA_LOOKUP = (() => {
  const m = {};
  for (const a of AREAS) {
    m[a.code] = a.name_ko;
    m[a.name_ko] = a.name_ko;
  }
  return m;
})();

// 백본 = 외부 사이트 가져가는 전제, * 허용. write 도입(Step 2) 시 origin 제한.
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "access-control-allow-headers": "content-type, x-api-key",
  "access-control-max-age": "86400",
};

// Module-level cache — Worker isolate 동안 메모리 보관. manifest.generated_at 변경 시 invalidate.
const _cache = { manifest: null, places: null, events: {} };

async function fetchAssetJson(env, path) {
  const r = await env.ASSETS.fetch(new Request(`https://placeholder${path}`));
  if (!r.ok) throw new Error(`asset ${path}: ${r.status}`);
  return await r.json();
}

async function getManifest(env) {
  return await fetchAssetJson(env, "/data/manifest.json");
}

async function getPlaces(env) {
  const manifest = await getManifest(env);
  if (_cache.places && _cache.manifest?.generated_at === manifest.generated_at) {
    return { places: _cache.places, manifest };
  }
  const data = await fetchAssetJson(env, "/data/places.json");
  _cache.places = data.places || [];
  _cache.manifest = manifest;
  _cache.events = {};
  return { places: _cache.places, manifest };
}

async function getEventsForMonth(env, yyyymm) {
  const manifest = await getManifest(env);
  if (_cache.events[yyyymm] && _cache.manifest?.generated_at === manifest.generated_at) {
    return { events: _cache.events[yyyymm], manifest };
  }
  let data;
  try {
    data = await fetchAssetJson(env, `/data/events-${yyyymm}.json`);
  } catch {
    data = { events: [] };
  }
  _cache.events[yyyymm] = data.events || [];
  _cache.manifest = manifest;
  return { events: _cache.events[yyyymm], manifest };
}

async function getAllEvents(env) {
  const manifest = await getManifest(env);
  const months = [];
  const now = new Date();
  for (let i = -12; i <= 6; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
    months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  months.push("undated");
  const all = [];
  for (const m of months) {
    try {
      const data = await fetchAssetJson(env, `/data/events-${m}.json`);
      all.push(...(data.events || []));
    } catch { /* skip missing months */ }
  }
  return { events: all, manifest };
}

function jsonResponse(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "x-api-schema-version": SCHEMA_VERSION,
      ...CORS,
      ...extraHeaders,
    },
  });
}

function ok(data, meta) {
  return jsonResponse({ data, meta });
}

function err(status, code, message) {
  return jsonResponse(
    { error: { code, message }, meta: { schema_version: SCHEMA_VERSION } },
    status,
  );
}

function pageMeta(manifest, total, page, limit) {
  return {
    schema_version: SCHEMA_VERSION,
    last_updated: manifest.generated_at,
    total, page, limit,
  };
}

function listMeta(manifest, total, extras = {}) {
  return {
    schema_version: SCHEMA_VERSION,
    last_updated: manifest.generated_at,
    total,
    ...extras,
  };
}

function itemMeta(manifest, freshness) {
  return {
    schema_version: SCHEMA_VERSION,
    last_updated: manifest.generated_at,
    ...(freshness ? { freshness } : {}),
  };
}

function parsePage(url) {
  const page = parseInt(url.searchParams.get("page") || "1", 10);
  const limit = parseInt(url.searchParams.get("limit") || "50", 10);
  if (isNaN(page) || page < 1) return { error: "page must be >= 1" };
  if (isNaN(limit) || limit < 1 || limit > 200) return { error: "limit must be 1..200" };
  return { page, limit };
}

function resolveArea(raw) {
  if (!raw) return null;
  return AREA_LOOKUP[raw] || raw;
}

function poiSummary(p) {
  return {
    id: p.id,
    title: p.title,
    category: p.category,
    subtype: p.subtype || null,
    venue: p.venue || null,
    address: p.address || "",
    gugun: p.gugun || null,
    lat: p.lat,
    lon: p.lon,
    popularity_score: p.popularity_score ?? 0,
    trust_tier: p.trust_tier || "B",
    rating: p.rating ?? null,
    image: p.image || null,
    tags: p.tags || [],
  };
}

function poiDetail(p) {
  return {
    ...poiSummary(p),
    description: p.description || null,
    excerpt: p.excerpt || null,
    url: p.url || null,
    story_url: p.story_url || null,
    hours: p.hours || null,
    holiday: p.holiday || null,
    phone: p.phone || null,
    transport: p.transport || null,
    tip: p.tip || null,
    menu: p.menu || null,
    views: p.views ?? 0,
    reviews: p.reviews ?? 0,
    first_seen: p.first_seen || null,
  };
}

function festivalProj(e) {
  return {
    id: e.id,
    title: e.title,
    category: e.category,
    venue: e.venue || null,
    address: e.address || null,
    gugun: e.gugun || null,
    lat: e.lat ?? null,
    lon: e.lon ?? null,
    start: e.start || null,
    end: e.end || null,
    price: e.price || null,
    booking_required: e.booking_required ?? null,
    url: e.url || null,
    image: e.image || null,
    excerpt: e.excerpt || null,
    tags: e.tags || [],
  };
}

async function handlePoiList(request, env, url) {
  const pg = parsePage(url);
  if (pg.error) return err(400, "INVALID_PARAM", pg.error);
  const area = resolveArea(url.searchParams.get("area"));
  const category = url.searchParams.get("category");
  const popMinRaw = url.searchParams.get("popularity_min");
  const popMin = popMinRaw == null ? null : parseInt(popMinRaw, 10);
  if (popMinRaw != null && (isNaN(popMin) || popMin < 0 || popMin > 100)) {
    return err(400, "INVALID_PARAM", "popularity_min must be 0..100");
  }
  if (category && !["food", "cafe", "attraction"].includes(category)) {
    return err(400, "INVALID_PARAM", "category must be food/cafe/attraction");
  }
  const { places, manifest } = await getPlaces(env);
  let filtered = places;
  if (area) filtered = filtered.filter((p) => p.gugun === area);
  if (category) filtered = filtered.filter((p) => p.category === category);
  if (popMin != null) filtered = filtered.filter((p) => (p.popularity_score ?? 0) >= popMin);
  filtered = [...filtered].sort((a, b) => (b.popularity_score ?? 0) - (a.popularity_score ?? 0));
  const total = filtered.length;
  const start = (pg.page - 1) * pg.limit;
  const slice = filtered.slice(start, start + pg.limit).map(poiSummary);
  return ok(slice, pageMeta(manifest, total, pg.page, pg.limit));
}

async function handlePoiDetail(request, env, url, idStr) {
  const id = parseInt(idStr, 10);
  if (isNaN(id)) return err(400, "INVALID_PARAM", "id must be integer");
  const { places, manifest } = await getPlaces(env);
  const p = places.find((x) => x.id === id);
  if (!p) return err(404, "NOT_FOUND", `POI ${id} not found`);
  const adapters = manifest.adapters || {};
  const adapter = adapters[p.source];
  const freshness = adapter
    ? { score: null, last_verified: adapter.last_seen, drift_alerts: [] }
    : null;
  return ok(poiDetail(p), itemMeta(manifest, freshness));
}

async function handleFestival(request, env, url) {
  const pg = parsePage(url);
  if (pg.error) return err(400, "INVALID_PARAM", pg.error);
  const month = url.searchParams.get("month");
  if (month && !/^\d{4}-\d{2}$/.test(month)) {
    return err(400, "INVALID_PARAM", "month must be YYYY-MM");
  }
  const area = resolveArea(url.searchParams.get("area"));
  const { events, manifest } = month
    ? await getEventsForMonth(env, month)
    : await getAllEvents(env);
  let filtered = events;
  if (area) filtered = filtered.filter((e) => e.gugun === area);
  const total = filtered.length;
  const start = (pg.page - 1) * pg.limit;
  const slice = filtered.slice(start, start + pg.limit).map(festivalProj);
  return ok(slice, pageMeta(manifest, total, pg.page, pg.limit));
}

async function handleAreaList(request, env, url) {
  const { places, manifest } = await getPlaces(env);
  const counts = {};
  for (const p of places) {
    if (p.gugun) counts[p.gugun] = (counts[p.gugun] || 0) + 1;
  }
  const data = AREAS.map((a) => ({
    code: a.code,
    name_ko: a.name_ko,
    lat: a.lat,
    lon: a.lon,
    poi_count: counts[a.name_ko] || 0,
  }));
  return ok(data, listMeta(manifest, data.length));
}

async function handlePopularityRanked(request, env, url) {
  const limit = parseInt(url.searchParams.get("limit") || "20", 10);
  if (isNaN(limit) || limit < 1 || limit > 100) {
    return err(400, "INVALID_PARAM", "limit must be 1..100");
  }
  const area = resolveArea(url.searchParams.get("area"));
  const category = url.searchParams.get("category");
  if (category && !["food", "cafe", "attraction"].includes(category)) {
    return err(400, "INVALID_PARAM", "category must be food/cafe/attraction");
  }
  const { places, manifest } = await getPlaces(env);
  let filtered = places;
  if (area) filtered = filtered.filter((p) => p.gugun === area);
  if (category) filtered = filtered.filter((p) => p.category === category);
  const sorted = [...filtered]
    .sort((a, b) => (b.popularity_score ?? 0) - (a.popularity_score ?? 0))
    .slice(0, limit)
    .map(poiSummary);
  return ok(sorted, listMeta(manifest, sorted.length, { scoring_method: "v3.7-popularity" }));
}

// 어댑터 last_seen 임계 — 7d warning, 30d critical
const FRESHNESS_WARN_HOURS = 24 * 7;
const FRESHNESS_CRIT_HOURS = 24 * 30;

async function handleFreshnessAlerts(request, env, url) {
  const manifest = await getManifest(env);
  const adapters = manifest.adapters || {};
  const now = Date.now();
  const detectedAt = new Date(now).toISOString();
  const alerts = [];
  for (const [source, info] of Object.entries(adapters)) {
    const lastSeen = info.last_seen;
    if (!lastSeen) {
      alerts.push({
        source, severity: "warning",
        message: `${source}: last_seen 없음`,
        last_seen: null, threshold_hours: null, detected_at: detectedAt,
      });
      continue;
    }
    const ageHours = (now - new Date(lastSeen).getTime()) / 3600000;
    let severity = null, thresh = null;
    if (ageHours > FRESHNESS_CRIT_HOURS) { severity = "critical"; thresh = FRESHNESS_CRIT_HOURS; }
    else if (ageHours > FRESHNESS_WARN_HOURS) { severity = "warning"; thresh = FRESHNESS_WARN_HOURS; }
    if (severity) {
      alerts.push({
        source, severity,
        message: `${source}: ${Math.floor(ageHours)}시간 동안 업데이트 없음`,
        last_seen: lastSeen, threshold_hours: thresh, detected_at: detectedAt,
      });
    }
  }
  return ok(alerts, listMeta(manifest, alerts.length));
}

export async function handleApi(request, env, ctx, url) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (request.method !== "GET") {
    return err(405, "METHOD_NOT_ALLOWED", `${request.method} not allowed`);
  }
  const path = url.pathname;
  try {
    if (path === "/api/v1/poi") return await handlePoiList(request, env, url);
    const m = path.match(/^\/api\/v1\/poi\/(\d+)$/);
    if (m) return await handlePoiDetail(request, env, url, m[1]);
    if (path === "/api/v1/festival") return await handleFestival(request, env, url);
    if (path === "/api/v1/area-list") return await handleAreaList(request, env, url);
    if (path === "/api/v1/popularity-ranked") return await handlePopularityRanked(request, env, url);
    if (path === "/api/v1/freshness-alerts") return await handleFreshnessAlerts(request, env, url);
    return err(404, "NOT_FOUND", `path ${path} not found`);
  } catch (e) {
    return err(500, "SERVER_ERROR", e.message || "internal error");
  }
}
