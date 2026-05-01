// Content endpoints
// Wave 1 — read only (handleContentList / handleContentGet)
// Wave 2 — POST /api/v1/content/ingest (GitHub Contents API + PAT)
// 빌드 시점 (scripts/export_content.py) 이 frontend/public/data/content/ 를 만들어 둠.

const SCHEMA_VERSION = "1.0";

const SLUG_RE = /^[a-z0-9_-]{1,80}$/;
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
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

// ────────────────────────────────────────────────────────────────────────────
// Wave 2 — POST /api/v1/content/ingest
// blog-automation → busan-travel/content/{yyyy-mm}/{slug}.md commit (GitHub Contents API).
// 신규 파일은 PUT 만으로 생성, 기존 파일은 sha 조회 후 PUT 으로 업데이트.
// secrets: INGEST_API_KEY (X-API-Key 검증), GITHUB_TOKEN_INGEST (PAT, contents:write).
// vars (wrangler.toml): GITHUB_OWNER, GITHUB_REPO, INGEST_BRANCH (default main).
// ────────────────────────────────────────────────────────────────────────────

const ALLOWED_FRONTMATTER_KEYS = [
  "slug", "title", "persona", "area_codes", "poi_refs",
  "ai_assisted", "ai_disclosure", "hero_image", "excerpt",
  "tags", "status", "published_at", "updated_at",
];

// YAML 안전 인용 — 한글/이모지/콜론/대시 안전. 문자열은 항상 double-quote, escape는 \" \\ \n.
function yamlQuote(s) {
  return '"' + String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n") + '"';
}

function yamlList(arr, kind) {
  if (!arr.length) return "[]";
  if (kind === "int") return "[" + arr.map((x) => String(parseInt(x, 10))).join(", ") + "]";
  return "[" + arr.map(yamlQuote).join(", ") + "]";
}

function buildFrontmatter(meta) {
  const lines = ["---"];
  lines.push(`slug: ${yamlQuote(meta.slug)}`);
  lines.push(`title: ${yamlQuote(meta.title)}`);
  lines.push(`persona: ${meta.persona ? yamlQuote(meta.persona) : "null"}`);
  lines.push(`area_codes: ${yamlList(meta.area_codes || [], "string")}`);
  lines.push(`poi_refs: ${yamlList(meta.poi_refs || [], "int")}`);
  lines.push(`ai_assisted: ${meta.ai_assisted ? "true" : "false"}`);
  lines.push(`ai_disclosure: ${meta.ai_disclosure ? yamlQuote(meta.ai_disclosure) : "null"}`);
  lines.push(`hero_image: ${meta.hero_image ? yamlQuote(meta.hero_image) : "null"}`);
  lines.push(`excerpt: ${yamlQuote(meta.excerpt || "")}`);
  lines.push(`tags: ${yamlList(meta.tags || [], "string")}`);
  lines.push(`status: ${yamlQuote(meta.status || "published")}`);
  lines.push(`published_at: ${yamlQuote(meta.published_at)}`);
  lines.push(`updated_at: ${yamlQuote(meta.updated_at)}`);
  lines.push("---");
  return lines.join("\n") + "\n";
}

// UTF-8 string → base64 (Workers 표준 btoa 는 latin-1 만 — TextEncoder 거쳐야 함).
function b64encodeUtf8(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

function ghRepoUrl(env, slug, yyyymm) {
  const owner = env.GITHUB_OWNER || "ok0327-dot";
  const repo = env.GITHUB_REPO || "busan-travel";
  return `https://api.github.com/repos/${owner}/${repo}/contents/content/${yyyymm}/${slug}.md`;
}

function ghHeaders(env) {
  return {
    "authorization": `Bearer ${env.GITHUB_TOKEN_INGEST}`,
    "accept": "application/vnd.github+json",
    "x-github-api-version": "2022-11-28",
    "user-agent": "busan-travel-ingest/1.0",
    "content-type": "application/json",
  };
}

async function fetchExistingSha(env, slug, yyyymm) {
  const r = await fetch(ghRepoUrl(env, slug, yyyymm), { headers: ghHeaders(env) });
  if (r.status === 404) return null;
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`github GET ${r.status}: ${text.slice(0, 200)}`);
  }
  const j = await r.json();
  return j.sha;
}

function nowIso() {
  return new Date().toISOString();
}

function deriveYyyymm(publishedAt) {
  const m = /^(\d{4})-(\d{2})/.exec(publishedAt);
  if (!m) return null;
  return `${m[1]}-${m[2]}`;
}

function validateIngestBody(body) {
  if (!body || typeof body !== "object") return "body must be JSON object";
  if (typeof body.slug !== "string" || !SLUG_RE.test(body.slug)) {
    return "slug must match [a-z0-9_-]{1,80}";
  }
  if (typeof body.title !== "string" || !body.title.trim()) {
    return "title required (non-empty string)";
  }
  if (typeof body.markdown !== "string" || !body.markdown.trim()) {
    return "markdown required (non-empty string)";
  }
  if (body.markdown.length > 200000) {
    return "markdown too large (max 200000 chars)";
  }
  if (body.area_codes != null && !Array.isArray(body.area_codes)) {
    return "area_codes must be array";
  }
  if (body.poi_refs != null && !Array.isArray(body.poi_refs)) {
    return "poi_refs must be array of integers";
  }
  if (body.tags != null && !Array.isArray(body.tags)) {
    return "tags must be array";
  }
  if (body.status && !["published", "draft", "archived"].includes(body.status)) {
    return "status must be one of published/draft/archived";
  }
  return null;
}

export async function handleContentIngest(request, env, url) {
  // Auth — shared secret
  const apiKey = request.headers.get("x-api-key");
  if (!env.INGEST_API_KEY) {
    return err(503, "NOT_CONFIGURED", "INGEST_API_KEY 미설정 — wrangler secret put 필요");
  }
  if (!apiKey || apiKey !== env.INGEST_API_KEY) {
    return err(401, "UNAUTHORIZED", "X-API-Key 헤더 누락 또는 불일치");
  }
  if (!env.GITHUB_TOKEN_INGEST) {
    return err(503, "NOT_CONFIGURED", "GITHUB_TOKEN_INGEST 미설정 — wrangler secret put 필요");
  }

  // Parse + validate
  let body;
  try {
    body = await request.json();
  } catch {
    return err(400, "INVALID_PARAM", "request body must be valid JSON");
  }
  const e = validateIngestBody(body);
  if (e) return err(400, "INVALID_PARAM", e);

  const now = nowIso();
  const publishedAt = body.published_at || now;
  const yyyymm = deriveYyyymm(publishedAt);
  if (!yyyymm) return err(400, "INVALID_PARAM", "published_at must be ISO8601 (yyyy-mm-...)");

  const meta = {
    slug: body.slug,
    title: body.title,
    persona: body.persona ?? null,
    area_codes: body.area_codes || [],
    poi_refs: (body.poi_refs || []).map((x) => parseInt(x, 10)).filter((x) => !isNaN(x)),
    ai_assisted: !!body.ai_assisted,
    ai_disclosure: body.ai_disclosure ?? null,
    hero_image: body.hero_image ?? null,
    excerpt: body.excerpt ?? "",
    tags: body.tags || [],
    status: body.status || "published",
    published_at: publishedAt,
    updated_at: body.updated_at || now,
  };

  const fileText = buildFrontmatter(meta) + "\n" + body.markdown.trimEnd() + "\n";
  const contentB64 = b64encodeUtf8(fileText);

  // GitHub PUT — 기존 파일이면 sha 조회 후 업데이트, 없으면 신규 생성
  let sha;
  try {
    sha = await fetchExistingSha(env, meta.slug, yyyymm);
  } catch (e2) {
    return err(502, "UPSTREAM_ERROR", `github GET 실패: ${e2.message}`);
  }
  const action = sha ? "update" : "create";

  const ghBody = {
    message: `content: ${action === "create" ? "publish" : "update"} ${meta.slug}`,
    content: contentB64,
    branch: env.INGEST_BRANCH || "main",
    ...(sha ? { sha } : {}),
  };

  const r = await fetch(ghRepoUrl(env, meta.slug, yyyymm), {
    method: "PUT",
    headers: ghHeaders(env),
    body: JSON.stringify(ghBody),
  });
  if (!r.ok) {
    const text = await r.text();
    return err(502, "UPSTREAM_ERROR", `github PUT ${r.status}: ${text.slice(0, 300)}`);
  }
  const j = await r.json();

  return jsonResponse({
    data: {
      content_id: meta.slug,
      action,
      file_path: `content/${yyyymm}/${meta.slug}.md`,
      github_commit_sha: j.commit?.sha || null,
      github_html_url: j.commit?.html_url || null,
      public_url: `https://busan-travel.dk0327.workers.dev/content/${meta.slug}`,
      note: "정적 빌드 후 노출 — daily cron 또는 다음 push 가 export_content.py 실행 시점에 read API 노출",
    },
    meta: {
      schema_version: SCHEMA_VERSION,
      last_updated: meta.updated_at,
    },
  }, action === "create" ? 201 : 200);
}
