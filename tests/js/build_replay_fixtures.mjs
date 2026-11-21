#!/usr/bin/env node
// 금요일 스냅샷 재생(weekend replay) 테스트용 fixture 생성기.
// Builds compact fixtures for tests/js/weekend_replay.test.mjs straight from git history:
//   git show <sha>:frontend/public/data/{manifest.json, events-YYYY-MM.json}
//
// usage (repo root):
//   node tests/js/build_replay_fixtures.mjs                    # 기본 8개 + 이미 있는 fixture 전부 다시 생성
//                                                              # (각 fixture 에 기록된 commit·days 로) / rebuild all
//   node tests/js/build_replay_fixtures.mjs 2026-11-27=abc1234 # 새 금요일 추가 / add one Friday (clock = that day 20:00 KST)
//   node tests/js/build_replay_fixtures.mjs 2026-11-26=abc1234@2026-11-26,2026-11-27
//                                                              # 목요일 데이터를 목·금 두 시각으로 재생 / Thu data replayed Thu+Fri
//   node tests/js/build_replay_fixtures.mjs --hour=10 2026-11-21=17c4524
//                                                              # 재생 시각(KST 시) 지정 — 기본 20시 / replay hour (default 20)
//
// 무엇을 담나 / What goes into a fixture:
//   shards          — 앱 init 이 그 주에 실제로 불러오는 달(오늘 −1 ~ +6개월, manifest.events_by_month 의 n>0 키)의
//                     festival/exhibition/performance 행사. 이미 끝난 행사(end < 첫 재생일)는 빼서 크기를 줄인다 —
//                     classifyFestival 이 "past" 로 버리므로 오늘 탭 어디에도 나올 수 없다. 순서는 원본 그대로 유지
//                     (정렬이 안정 정렬이라 동점일 때 원본 순서가 결과를 정한다).
//                     The months main.js init loads that week; past events are dropped (they can never be
//                     active/upcoming); original order is preserved because the ranking sort is stable.
//   ongoing_shards  — 그보다 오래된 달의 행사 중 end >= 첫 재생일인 것 (장기 진행 행사).
//                     events-ongoing.json 이 없던 커밋(PR #79 이전)에서는 replay_lib 가 이것으로 그 파일을 흉내 낸다.
//                     Older-month events still running on replay day; replay_lib simulates events-ongoing.json from them.
//   ongoing_file    — 커밋에 events-ongoing.json 이 있으면(PR #79 이후) 그 내용 그대로 + manifest 의
//                     counts.events_ongoing (앱은 이 값이 0 보다 클 때만 파일을 받는다). 없으면 키 자체를 넣지 않는다
//                     → 옛 fixture 는 다시 만들어도 바이트가 같다.
//                     The real events-ongoing.json when the commit has one (key omitted otherwise).
//   events_by_month — manifest 의 월별 개수 (앱이 불러올 달을 정하는 근거).
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../..");
const OUT_DIR = path.join(REPO, "tests/fixtures/weekend_replay");
const DATA = "frontend/public/data";
const CATEGORIES = ["festival", "exhibition", "performance"];
// 오늘 탭(랭킹·예약·렌더)이 읽는 필드만 남긴다 — main.js 를 grep 해서 고름.
// Fields the today tab reads (ranking, booking, hero/chip/urgent HTML, 🎭/🆕 sections).
// description 은 _bookingRequired 의 키워드 폴백이 읽으므로 자르지 않는다. image 는 <img> 에만 쓰여 뺀다.
const FIELDS = [
  "id", "title", "category", "subtype", "start", "end", "priority", "hero_tags",
  "booking_required", "booking_deadline", "booking_opens_at", "url", "venue", "address",
  "source", "first_seen", "description", "popularity_score",
];
// 기본 스냅샷 — 각 금요일(11-19 는 목요일 데이터) 자동 수집 커밋.
// 11-21 은 PR #79(events-ongoing.json)·#82 병합 뒤 첫 데이터를 토요일 오전 10시에 재생한다.
// Default snapshots: the auto-update data commit of each Friday (11-19 is Thursday data);
// 11-21 = first post-#79 data, replayed Saturday 10:00 KST.
const DEFAULTS = [
  { snapshot: "2026-10-09", sha: "652f27f" },
  { snapshot: "2026-10-16", sha: "de2eac0" },
  { snapshot: "2026-10-23", sha: "35ff1d3" },
  { snapshot: "2026-10-30", sha: "f7ca4b7" },
  { snapshot: "2026-11-06", sha: "399be0e" },
  { snapshot: "2026-11-13", sha: "9b91097" },
  { snapshot: "2026-11-19", sha: "b4aa9b8", days: ["2026-11-19", "2026-11-20"] },
  { snapshot: "2026-11-21", sha: "17c4524", hour: 10 },
];

const git = (...args) => execFileSync("git", args, { cwd: REPO, maxBuffer: 256 * 1024 * 1024, encoding: "utf8" });
const showJson = (sha, file) => JSON.parse(git("show", `${sha}:${DATA}/${file}`));

// "YYYY-MM-DD" 기준 −1 ~ +6 개월 (main.js init 의 horizonMonths 와 같은 계산, 단 순수 문자열 연산)
function horizonMonths(day) {
  const y = Number(day.slice(0, 4)), m = Number(day.slice(5, 7)) - 1;
  const out = [];
  for (let off = -1; off <= 6; off++) {
    const t = y * 12 + m + off;
    out.push(`${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`);
  }
  return out;
}

function trim(e) {
  const o = {};
  for (const k of FIELDS) if (e[k] !== null && e[k] !== undefined) o[k] = e[k];
  return o;
}

function parseArg(arg, hour) {
  const m = /^(\d{4}-\d{2}-\d{2})=([0-9a-fA-F]{7,40})(?:@([\d,-]+))?$/.exec(arg);
  if (!m) throw new Error(`bad argument "${arg}" — expected YYYY-MM-DD=<sha>[@day1,day2]`);
  return { snapshot: m[1], sha: m[2], days: m[3] ? m[3].split(",") : undefined, hour };
}

// 행사 배열을 한 줄에 한 건씩 — diff 를 읽기 쉽게 / one event per line for readable diffs
function serialize(fx) {
  const lines = ["{"];
  const keys = Object.keys(fx);
  keys.forEach((k, ki) => {
    const comma = ki < keys.length - 1 ? "," : "";
    const v = fx[k];
    if (k === "ongoing_file") {
      lines.push(`  ${JSON.stringify(k)}: {`);
      const { events, ...meta } = v;
      for (const [mk, mv] of Object.entries(meta)) lines.push(`    ${JSON.stringify(mk)}: ${JSON.stringify(mv)},`);
      if (!events.length) lines.push(`    "events": []`);
      else {
        lines.push(`    "events": [`);
        events.forEach((e, ei) => lines.push(`      ${JSON.stringify(e)}${ei < events.length - 1 ? "," : ""}`));
        lines.push(`    ]`);
      }
      lines.push(`  }${comma}`);
    } else if (k === "shards" || k === "ongoing_shards") {
      const months = Object.keys(v);
      lines.push(`  ${JSON.stringify(k)}: {`);
      months.forEach((mo, mi) => {
        const evs = v[mo];
        const mc = mi < months.length - 1 ? "," : "";
        if (!evs.length) { lines.push(`    ${JSON.stringify(mo)}: []${mc}`); return; }
        lines.push(`    ${JSON.stringify(mo)}: [`);
        evs.forEach((e, ei) => lines.push(`      ${JSON.stringify(e)}${ei < evs.length - 1 ? "," : ""}`));
        lines.push(`    ]${mc}`);
      });
      lines.push(`  }${comma}`);
    } else {
      lines.push(`  ${JSON.stringify(k)}: ${JSON.stringify(v)}${comma}`);
    }
  });
  lines.push("}");
  return lines.join("\n") + "\n";
}

function build({ snapshot, sha, days, hour }) {
  days = days || [snapshot];
  hour = hour ?? 20;
  const fullSha = git("rev-parse", "--verify", `${sha}^{commit}`).trim();
  const manifest = showJson(fullSha, "manifest.json");
  const byMonth = manifest.counts?.events_by_month || {};
  // 데이터 생성 시각이 스냅샷 날짜와 하루 넘게 어긋나면 커밋을 잘못 고른 것일 수 있다
  const gen = Date.parse(manifest.generated_at || "");
  if (!Number.isNaN(gen) && Math.abs(gen - Date.parse(`${snapshot}T12:00:00+09:00`)) > 36 * 3600 * 1000) {
    console.warn(`WARN ${snapshot}: ${sha} data generated_at=${manifest.generated_at} — is this the right commit?`);
  }
  const listed = new Set(git("ls-tree", "--name-only", `${fullSha}:${DATA}`).split("\n").filter(Boolean));
  // main.js init 과 같은 규칙: n>0 이고 YYYY-MM 형식인 키, 정렬
  const months = Object.entries(byMonth)
    .filter(([k, n]) => n > 0 && /^\d{4}-\d{2}$/.test(k))
    .map(([k]) => k).sort();
  const horizon = new Set(days.flatMap(horizonMonths));
  const firstDay = [...days].sort()[0];
  const horizonStart = [...horizon].sort()[0];
  const load = (mo) => {
    const f = `events-${mo}.json`;
    if (!listed.has(f)) return null;  // 앱에선 fetch 실패 → 빈 배열 / app: fetch fails → []
    return (showJson(fullSha, f).events || []).filter(e => CATEGORIES.includes(e.category));
  };
  const shards = {}, ongoing = {};
  let dropped = 0;
  for (const mo of months) {
    if (horizon.has(mo)) {
      const evs = load(mo);
      if (!evs) { shards[mo] = []; continue; }
      const keep = evs.filter(e => (e.end || e.start || "9999") >= firstDay);
      dropped += evs.length - keep.length;
      shards[mo] = keep.map(trim);
    } else if (mo < horizonStart) {
      const evs = (load(mo) || []).filter(e => (e.end || "") >= firstDay);
      if (evs.length) ongoing[mo] = evs.map(trim);
    }
  }
  const fx = {
    _about: "weekend replay fixture — generated by tests/js/build_replay_fixtures.mjs; do not edit by hand",
    snapshot,
    commit: fullSha,
    data_generated_at: manifest.generated_at || null,
    days,
    replay_hour_kst: hour,
    dropped_past_events: dropped,
    fields: FIELDS,
    events_by_month: byMonth,
    shards,
    ongoing_shards: ongoing,
  };
  // PR #79 이후 커밋: 앱이 실제로 받는 events-ongoing.json 을 그대로 담는다 (main.js init 과 같은 파일)
  // Post-#79 commits: keep the real events-ongoing.json the app fetches.
  if (listed.has("events-ongoing.json")) {
    const of = showJson(fullSha, "events-ongoing.json");
    fx.ongoing_file = {
      manifest_events_ongoing: manifest.counts?.events_ongoing ?? 0,
      as_of: of.as_of ?? null,
      events: (of.events || []).filter(e => CATEGORIES.includes(e.category)).map(trim),
    };
  }
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const file = path.join(OUT_DIR, `${snapshot}.json`);
  const text = serialize(fx);
  JSON.parse(text);  // 직렬화 검증 / sanity check
  fs.writeFileSync(file, text);
  const n = Object.values(shards).reduce((a, v) => a + v.length, 0);
  const no = Object.values(ongoing).reduce((a, v) => a + v.length, 0);
  const nf = fx.ongoing_file ? ` ongoing_file=${fx.ongoing_file.events.length}` : "";
  console.log(`${snapshot} ${fullSha.slice(0, 7)} days=${days.join(",")} @${hour}h months=${Object.keys(shards).join(",")} ` +
    `events=${n} (dropped past ${dropped}) ongoing_extra=${no}${nf} -> ${path.relative(REPO, file)} ${(Buffer.byteLength(text) / 1024).toFixed(0)}KB`);
}

// 이미 만들어 둔 fixture 도 기록된 commit·days 로 다시 만들 수 있게 / existing fixtures rebuild from their own commit
function existing() {
  if (!fs.existsSync(OUT_DIR)) return [];
  return fs.readdirSync(OUT_DIR).filter(f => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).map(f => {
    const j = JSON.parse(fs.readFileSync(path.join(OUT_DIR, f), "utf8"));
    return { snapshot: j.snapshot, sha: j.commit, days: j.days, hour: j.replay_hour_kst };
  });
}

const argv = process.argv.slice(2);
const hourArg = argv.find(a => a.startsWith("--hour="));
const hour = hourArg ? Number(hourArg.slice(7)) : undefined;
if (hourArg && !(Number.isInteger(hour) && hour >= 0 && hour <= 23)) throw new Error(`bad ${hourArg} — expected --hour=0..23`);
const args = argv.filter(a => !a.startsWith("--hour="));
let targets;
if (args.length) targets = args.map(a => parseArg(a, hour));
else {
  const bySnap = new Map(existing().map(t => [t.snapshot, t]));
  for (const t of DEFAULTS) bySnap.set(t.snapshot, t);
  targets = [...bySnap.values()].sort((a, b) => a.snapshot.localeCompare(b.snapshot));
}
for (const t of targets) build(t);
