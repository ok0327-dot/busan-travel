// `node --test tests/js/` 진입점. Node 22 의 --test 는 디렉터리 인자를 모듈 경로로 읽어 이 index.js 를 실행한다.
// Entry point for `node --test tests/js/` — Node 22 resolves a directory argument to its index.js.
// 같은 폴더의 *.test.mjs 를 모두 불러온다. TZ 는 어떤 Date 도 쓰기 전에 KST 로 맞춘다.
// Loads every *.test.mjs here; sets TZ to KST before any Date is used.
// (node --test tests/js/*.test.mjs 나 인자 없는 node --test 로 돌려도 된다 — 이 파일은 그때 실행되지 않는다.)
process.env.TZ = "Asia/Seoul";
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

(async () => {
  for (const f of fs.readdirSync(__dirname).filter(n => n.endsWith(".test.mjs")).sort()) {
    await import(pathToFileURL(path.join(__dirname, f)).href);
  }
})().catch((e) => { console.error(e); process.exitCode = 1; });
