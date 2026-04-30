// SEO endpoints — robots.txt + sitemap.xml (Step 3.1/3.2)
// Wave 1 — 홈 + 정적 페이지만. POI/festival/area deep link 는 Wave 2 (router 도입 후).

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
# 출처 표기 + AI disclosure 페이지 운영 — 학습 데이터로 활용 시 본 사이트 표기
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

export async function handleSitemap(request, env, url) {
  const base = url.origin;
  const lastmod = new Date().toISOString().slice(0, 10);
  // Wave 1 — 안전한 URL 만 (deep link router 추가 후 Wave 2 에서 POI/festival/area 확장)
  const urls = [
    { loc: `${base}/`, priority: "1.0", changefreq: "daily" },
    { loc: `${base}/about`, priority: "0.5", changefreq: "monthly" },
    { loc: `${base}/ai-disclosure`, priority: "0.6", changefreq: "monthly" },
    { loc: `${base}/sources`, priority: "0.5", changefreq: "monthly" },
  ];
  const body =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
    urls
      .map(
        (u) =>
          `<url><loc>${u.loc}</loc><lastmod>${lastmod}</lastmod>` +
          `<changefreq>${u.changefreq}</changefreq><priority>${u.priority}</priority></url>`,
      )
      .join("") +
    "</urlset>";
  return new Response(body, {
    headers: {
      "content-type": "application/xml; charset=utf-8",
      "cache-control": "public, max-age=1800",
    },
  });
}
