// busan-travel Cloudflare Worker
// /api/v1/* → JSON API v1 (백본, src/api.js — Step 1.2)
// /img/*    → R2 (busan-travel-images) pre-generated variants 직접 서빙
// /img-proxy/visitbusan/{id} → visitbusan.net 원본 + 엣지 캐시
// 그 외     → 정적 에셋 (frontend/public)

import { handleApi } from "./api.js";

const API_PREFIX = "/api/v1/";
const IMG_PREFIX = "/img/";
const IMG_PREFIX_LEN = IMG_PREFIX.length;
const PROXY_PREFIX = "/img-proxy/visitbusan/";
const PROXY_PREFIX_LEN = PROXY_PREFIX.length;

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, OPTIONS",
};

// visitbusan 이미지 ID 패턴: 17자리 숫자 (YYYYMMDDHHMMSSxxx) — SSRF 방지
const VISITBUSAN_ID_RE = /^\d{14,20}$/;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // /api/v1/* → JSON API v1 (Step 1.2)
    if (url.pathname.startsWith(API_PREFIX)) {
      return handleApi(request, env, ctx, url);
    }

    // /img/* → R2 (pre-gen variants)
    if (url.pathname.startsWith(IMG_PREFIX)) {
      return serveImage(request, env, ctx, url);
    }

    // /img-proxy/visitbusan/{id} → visitbusan.net 원본 프록시 + 엣지 캐시
    // `_thumbL` 썸네일 대신 원본(최대 4K) 을 Cloudflare 엣지에서 캐시하여 빠르게 서빙.
    if (url.pathname.startsWith(PROXY_PREFIX)) {
      return proxyVisitBusan(request, env, ctx, url);
    }

    // 그 외 모두 정적 에셋으로 위임
    return env.ASSETS.fetch(request);
  },
};

async function serveImage(request, env, ctx, url) {
  const method = request.method;
  if (method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  if (method !== "GET" && method !== "HEAD") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const key = decodeURIComponent(url.pathname.slice(IMG_PREFIX_LEN));
  if (!key || key.includes("..")) {
    return new Response("Bad Request", { status: 400, headers: CORS_HEADERS });
  }

  // 엣지 캐시 먼저 조회
  const cache = caches.default;
  const cacheKey = new Request(url.toString(), request);
  let response = await cache.match(cacheKey);
  if (response) return response;

  const obj = await env.IMAGES.get(key);
  if (!obj) {
    return new Response("Not Found", { status: 404, headers: CORS_HEADERS });
  }

  const headers = new Headers(CORS_HEADERS);
  obj.writeHttpMetadata(headers);
  headers.set("etag", obj.httpEtag);
  // 1년 immutable 캐시 (slug 에 버전 포함 시 무효화 용이)
  headers.set("cache-control", "public, max-age=31536000, immutable");

  response = new Response(method === "HEAD" ? null : obj.body, { headers });
  // 비동기로 엣지 캐시에 저장 (응답 반환 지연 없음)
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

async function proxyVisitBusan(request, env, ctx, url) {
  const method = request.method;
  if (method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  if (method !== "GET" && method !== "HEAD") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const id = url.pathname.slice(PROXY_PREFIX_LEN);
  if (!VISITBUSAN_ID_RE.test(id)) {
    return new Response("Bad Request", { status: 400, headers: CORS_HEADERS });
  }

  // 엣지 캐시 먼저 조회 (Cloudflare 데이터센터당 1번만 원본 요청)
  const cache = caches.default;
  const cacheKey = new Request(url.toString(), { method: "GET" });
  let response = await cache.match(cacheKey);
  if (response) {
    // HEAD 요청이면 바디 제거
    return method === "HEAD" ? new Response(null, { headers: response.headers }) : response;
  }

  // 원본 요청 — _thumbL 없는 베이스 URL = 고화질 원본
  const upstreamUrl = `https://www.visitbusan.net/uploadImgs/files/cntnts/${id}`;
  let upstream;
  try {
    upstream = await fetch(upstreamUrl, {
      cf: { cacheTtl: 86400, cacheEverything: true },
      headers: { "user-agent": "busan-travel-worker/1.0" },
    });
  } catch (e) {
    return new Response("Upstream Error", { status: 502, headers: CORS_HEADERS });
  }
  if (!upstream.ok) {
    return new Response("Not Found", { status: 404, headers: CORS_HEADERS });
  }
  // visitbusan 은 원본에 content-type 을 비우는 경우가 있음 → 기본 image/jpeg.
  const rawCt = upstream.headers.get("content-type") || "";
  const ct = rawCt.startsWith("image/") ? rawCt : "image/jpeg";

  const headers = new Headers(CORS_HEADERS);
  headers.set("content-type", ct);
  // 30일 브라우저 캐시, 영구 엣지 캐시
  headers.set("cache-control", "public, max-age=2592000, s-maxage=31536000, immutable");
  const etag = upstream.headers.get("etag");
  if (etag) headers.set("etag", etag);

  response = new Response(upstream.body, { status: 200, headers });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return method === "HEAD" ? new Response(null, { headers }) : response;
}
