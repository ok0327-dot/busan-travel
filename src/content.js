// Content endpoints (Step 2 Wave 1 — read only)
// POST /api/v1/content/ingest 는 Wave 2 (GitHub Contents API + PAT).
// 빌드 시점 (scripts/export_content.py) 이 frontend/public/data/content/ 를 만들어 둠.

const SCHEMA_VERSION = "1.0";

const SLUG_RE = /^[a-z0-9_-]{1,80}$/;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "access-control-allow-headers": "content-type, x-api-key",
  "access-control-expose-headers": "x-api-schema-version, x-ratelimit-remaining, x-ratelimit-reset",
  "access-control-max-age": "86400",
};

function jsonResponse(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "x-api-schema-version": SCHEMA_VERSION,
      ...CORS,
      ...extra,
    },
  });
}

function ok(data, meta) { return jsonResponse({ data, meta }); }
function err(status, code, message) {
  return jsonResponse(
    { error: { code, message }, meta: { schema_version: SCHEMA_VERSION } }, status,
  );
}

async function fetchAssetJson(env, path) {
  const r = await env.ASSETS.fetch(new Request(`https://placeholder${path}`));
  if (!r.ok) throw new Error(`asset ${path}: ${r.status}`);
  return await r.json();
}

export async function handleContentList(request, env, url) {
  let data;
  try { data = await fetchAssetJson(env, "/data/content/index.json"); }
  catch { data = { count: 0, items: [] }; }

  const persona = url.searchParams.get("persona");
  const area = url.searchParams.get("area");
  const tag = url.searchParams.get("tag");
  const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10));
  const limitRaw = parseInt(url.searchParams.get("limit") || "20", 10);
  if (isNaN(limitRaw) || limitRaw < 1 || limitRaw > 50) {
    return err(400, "INVALID_PARAM", "limit must be 1..50");
  }

  let items = data.items || [];
  if (persona) items = items.filter((p) => p.persona === persona);
  if (area) items = items.filter((p) => (p.area_codes || []).includes(area));
  if (tag) items = items.filter((p) => (p.tags || []).includes(tag));

  const total = items.length;
  const slice = items.slice((page - 1) * limitRaw, page * limitRaw);
  const lastUpdated = items[0]?.updated_at || new Date().toISOString();

  return ok(slice, {
    schema_version: SCHEMA_VERSION,
    last_updated: lastUpdated,
    total,
    page,
    limit: limitRaw,
  });
}

export async function handleContentGet(request, env, url, slug) {
  if (!SLUG_RE.test(slug)) {
    return err(400, "INVALID_PARAM", "slug must match [a-z0-9_-]{1,80}");
  }
  let data;
  try {
    data = await fetchAssetJson(env, `/data/content/${slug}.json`);
  } catch {
    return err(404, "NOT_FOUND", `content '${slug}' not found`);
  }
  return ok(data, {
    schema_version: SCHEMA_VERSION,
    last_updated: data.updated_at || data.published_at,
  });
}
