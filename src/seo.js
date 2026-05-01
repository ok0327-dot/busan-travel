// SEO endpoints — robots/sitemap + SPA fallback HTMLRewriter (Step 3 Wave 1+2)

import { AREAS, getPlaces, getAllEvents } from "./api.js";

export async function handleRobots(request, env, url) {
  const base = url.origin;
  const body = `# busan-travel — robots policy
# AI 사용 정책: ${base}/ai-disclosure / Data sources: ${base}/sources

User-agent: *
Allow: /
Disallow: /api/v1/_health

# 검색 엔진 명시 허용 / Search engines (explicit allow)
User-agent: Googlebot
Allow: /
User-agent: Bingbot
Allow: /
User-agent: NaverBot
Allow: /
User-agent: Yeti
Allow: /
User-agent: DuckDuckBot
Allow: /

# AI training crawlers — allow with attribution policy
User-agent: GPTBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: anthropic-ai
Allow: /
User-agent: CCBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Applebot-Extended
Allow: /

Sitemap: ${base}/sitemap.xml
`;
  return new Response(body, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=3600",
    },
  });
}

function urlEntry(loc, lastmod, priority, changefreq) {
  return `<url><loc>${loc}</loc><lastmod>${lastmod}</lastmod>` +
    `<changefreq>${changefreq}</changefreq><priority>${priority}</priority></url>`;
}

export async function handleSitemap(request, env, url) {
  const base = url.origin;
  const today = new Date().toISOString().slice(0, 10);

  // 정적 페이지 (Wave 1)
  const staticUrls = [
    urlEntry(`${base}/`, today, "1.0", "daily"),
    urlEntry(`${base}/about`, today, "0.5", "monthly"),
    urlEntry(`${base}/ai-disclosure`, today, "0.6", "monthly"),
    urlEntry(`${base}/sources`, today, "0.5", "monthly"),
  ];

  // Wave 2 — POI / festival / area deep link
  let dynamicUrls = [];
  try {
    const { places } = await getPlaces(env);
    for (const p of places) {
      dynamicUrls.push(urlEntry(`${base}/poi/${p.id}`, today, "0.7", "weekly"));
    }
  } catch { /* fall back to static only */ }

  try {
    const { events } = await getAllEvents(env);
    for (const e of events) {
      if (e.id) dynamicUrls.push(urlEntry(`${base}/festival/${e.id}`, today, "0.6", "weekly"));
    }
  } catch { /* skip */ }

  for (const a of AREAS) {
    dynamicUrls.push(urlEntry(`${base}/area/${a.code}`, today, "0.6", "weekly"));
  }

  // content posts
  try {
    const r = await env.ASSETS.fetch(new Request(`${base}/data/content/index.json`));
    if (r.ok) {
      const data = await r.json();
      for (const c of data.items || []) {
        const lm = (c.updated_at || c.published_at || "").slice(0, 10) || today;
        dynamicUrls.push(urlEntry(`${base}/content/${c.slug}`, lm, "0.8", "weekly"));
      }
    }
  } catch { /* skip */ }

  const body =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
    staticUrls.join("") + dynamicUrls.join("") +
    "</urlset>";
  return new Response(body, {
    headers: {
      "content-type": "application/xml; charset=utf-8",
      "cache-control": "public, max-age=1800",
    },
  });
}

// === Step 3 Wave 2 — SPA fallback + HTMLRewriter per-path 메타 ===

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function buildPoiMeta(poi, origin) {
  const url = `${origin}/poi/${poi.id}`;
  const catLabel = poi.category === "cafe" ? "카페" : poi.category === "food" ? "맛집" : "관광지";
  const title = `${poi.title} — ${poi.gugun || "부산"} ${catLabel} | 주말부산`;
  const desc = (poi.description || poi.excerpt ||
    `${poi.title} (${poi.gugun || "부산"}) ${catLabel}. ${poi.address || ""}`).slice(0, 200);
  const image = poi.image || `${origin}/icon.svg`;
  const schemaType = poi.category === "food" ? "Restaurant"
    : poi.category === "cafe" ? "CafeOrCoffeeShop" : "TouristAttraction";
  const schema = {
    "@context": "https://schema.org",
    "@type": schemaType,
    name: poi.title,
    description: desc,
    address: poi.address || undefined,
    geo: { "@type": "GeoCoordinates", latitude: poi.lat, longitude: poi.lon },
    image: poi.image || undefined,
    url: poi.url || undefined,
    containedInPlace: { "@type": "AdministrativeArea", name: poi.gugun || "부산광역시" },
  };
  return { title, desc, url, image, schema };
}

function buildFestivalMeta(ev, origin) {
  const url = `${origin}/festival/${ev.id}`;
  const catLabel = ev.category === "exhibition" ? "전시"
    : ev.category === "performance" ? "공연"
    : ev.category === "blog_post" ? "공식 블로그" : "축제";
  const title = `${ev.title} — ${ev.gugun || "부산"} ${catLabel} | 주말부산`;
  const desc = (ev.excerpt ||
    `${ev.title} ${catLabel} (${ev.start || ""} ~ ${ev.end || ""}). ${ev.venue || ev.address || "부산"}`).slice(0, 200);
  const image = ev.image || `${origin}/icon.svg`;
  const schema = ev.category === "blog_post"
    ? {
        "@context": "https://schema.org",
        "@type": "Article",
        headline: ev.title,
        description: desc,
        url: ev.url || url,
        image: ev.image || undefined,
      }
    : {
        "@context": "https://schema.org",
        "@type": "Event",
        name: ev.title,
        description: desc,
        startDate: ev.start || undefined,
        endDate: ev.end || undefined,
        location: ev.venue || ev.address
          ? { "@type": "Place", name: ev.venue || ev.address, address: ev.address || undefined }
          : undefined,
        image: ev.image || undefined,
        url: ev.url || url,
        eventStatus: "https://schema.org/EventScheduled",
      };
  return { title, desc, url, image, schema };
}

async function getContentMeta(env, slug) {
  try {
    const r = await env.ASSETS.fetch(new Request(`https://placeholder/data/content/${slug}.json`));
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

function buildContentMeta(content, origin) {
  const url = `${origin}/content/${content.slug}`;
  const title = `${content.title} | 주말부산`;
  const desc = (content.excerpt || content.title).slice(0, 200);
  const image = content.hero_image || `${origin}/icon.svg`;
  const schema = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: content.title,
    description: desc,
    image: content.hero_image || undefined,
    datePublished: content.published_at,
    dateModified: content.updated_at,
    author: content.persona
      ? { "@type": "Person", name: content.persona }
      : { "@type": "Organization", name: "주말부산" },
    publisher: {
      "@type": "Organization",
      name: "주말부산",
      url: origin,
    },
    keywords: (content.tags || []).join(", ") || undefined,
  };
  return { title, desc, url, image, schema };
}

function buildAreaMeta(area, origin) {
  const url = `${origin}/area/${area.code}`;
  const title = `${area.name_ko} — 부산 자치구 관광 가이드 | 주말부산`;
  const desc = `${area.name_ko}의 맛집·카페·관광지·축제 큐레이션. Kakao Maps 기반 주말 활동 의사결정 도구.`;
  const schema = {
    "@context": "https://schema.org",
    "@type": "Place",
    name: area.name_ko,
    description: desc,
    geo: { "@type": "GeoCoordinates", latitude: area.lat, longitude: area.lon },
    containedInPlace: { "@type": "City", name: "부산광역시" },
  };
  return { title, desc, url, image: `${origin}/icon.svg`, schema };
}

export async function handleSpaPage(request, env, ctx, url) {
  const path = url.pathname;
  let meta = null;
  try {
    let m = path.match(/^\/poi\/(\d+)$/);
    if (m) {
      const id = parseInt(m[1], 10);
      const { places } = await getPlaces(env);
      const poi = places.find((p) => p.id === id);
      if (poi) meta = buildPoiMeta(poi, url.origin);
    }
    if (!meta) {
      m = path.match(/^\/festival\/(\d+)$/);
      if (m) {
        const id = parseInt(m[1], 10);
        const { events } = await getAllEvents(env);
        const ev = events.find((e) => e.id === id);
        if (ev) meta = buildFestivalMeta(ev, url.origin);
      }
    }
    if (!meta) {
      m = path.match(/^\/area\/([a-z]+)$/);
      if (m) {
        const area = AREAS.find((a) => a.code === m[1]);
        if (area) meta = buildAreaMeta(area, url.origin);
      }
    }
    if (!meta) {
      m = path.match(/^\/content\/([a-z0-9_-]+)$/);
      if (m) {
        const c = await getContentMeta(env, m[1]);
        if (c) meta = buildContentMeta(c, url.origin);
      }
    }
  } catch { /* meta 못 만들면 fallthrough = 기본 index.html */ }

  // 정적 index 가져오기 — ASSETS 는 /index.html 직접 요청을 / 로 307 하므로
  // root path 로 요청해야 200 + index.html 본문을 받을 수 있음.
  const indexReq = new Request(url.origin + "/", request);
  const res = await env.ASSETS.fetch(indexReq);

  if (!meta) return res;

  // HTMLRewriter — per-path 메타·OG·canonical·JSON-LD 주입
  return new HTMLRewriter()
    .on("title", { element(el) { el.setInnerContent(meta.title); } })
    .on('meta[name="description"]', { element(el) { el.setAttribute("content", meta.desc); } })
    .on('link[rel="canonical"]', { element(el) { el.setAttribute("href", meta.url); } })
    .on('meta[property="og:title"]', { element(el) { el.setAttribute("content", meta.title); } })
    .on('meta[property="og:description"]', { element(el) { el.setAttribute("content", meta.desc); } })
    .on('meta[property="og:url"]', { element(el) { el.setAttribute("content", meta.url); } })
    .on('meta[property="og:image"]', { element(el) { el.setAttribute("content", meta.image); } })
    .on('meta[name="twitter:title"]', { element(el) { el.setAttribute("content", meta.title); } })
    .on('meta[name="twitter:description"]', { element(el) { el.setAttribute("content", meta.desc); } })
    .on('meta[name="twitter:image"]', { element(el) { el.setAttribute("content", meta.image); } })
    .on("head", {
      element(el) {
        const json = JSON.stringify(meta.schema).replace(/</g, "\\u003c");
        el.append(`<script type="application/ld+json">${json}</script>`, { html: true });
      },
    })
    .transform(res);
}
