---
slug: "ingest-smoke-test-2026-05"
title: "ingest API smoke test — Step 2 Wave 2 검증"
persona: null
area_codes: []
poi_refs: []
ai_assisted: false
ai_disclosure: null
hero_image: null
excerpt: "Step 2 Wave 2 ingest API 의 end-to-end 검증용 (자동 생성 후 archive 예정)."
tags: ["meta", "smoke-test"]
status: "published"
published_at: "2026-05-02T01:30:00+09:00"
updated_at: "2026-05-01T16:29:39.534Z"
---

# ingest smoke test

이 글은 Step 2 Wave 2 ingest API 의 end-to-end 검증용 자동 생성 콘텐츠입니다.

## 검증 흐름

1. **POST /api/v1/content/ingest** 응답 201 (create)
2. **GitHub Contents API** → `content/2026-05/ingest-smoke-test-2026-05.md` commit
3. **export-content.yml** workflow 자동 trigger
4. `frontend/public/data/content/ingest-smoke-test-2026-05.json` 빌드 + commit
5. **Cloudflare Workers Builds** auto deploy
6. `/content/ingest-smoke-test-2026-05` 라이브 노출

## 결과

이 글이 보인다면 6단계 흐름이 모두 정상 작동한 것입니다.
