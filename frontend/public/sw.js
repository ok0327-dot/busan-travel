// 최소 service worker — installable PWA 조건 충족용 (Chrome beforeinstallprompt 트리거).
// 캐시 전략은 단순 network-first (오프라인 fallback 없음).
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  // pass-through — Chrome 의 PWA installable 판정은 fetch 핸들러 존재 여부만 체크
});
