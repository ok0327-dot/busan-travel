// 금요일 스냅샷 재생(weekend replay) 공용 로더 — tests/js/*.test.mjs 가 쓴다.
// Shared loader for the weekend replay tests.
//
// 하는 일 / What it does
//   1) 지금의 frontend/public/main.js 를 테스트 시점에 읽어, 최상위 함수·상수 선언을 이름으로 뽑아낸다
//      (문자열·템플릿·정규식·주석을 건너뛰는 괄호 짝 맞추기 / brace matching that skips strings, templates,
//      regex literals and comments). 꼭 필요한 함수가 없으면 이름을 밝혀 바로 실패한다 → 리팩터링을 놓치지 않는다.
//   2) node:vm 샌드박스에 시계를 고정한 Date(목·금 20:00 KST)와 작은 가짜 DOM 을 넣고
//      진짜 renderTodayHighlights(target) 를 그대로 실행한다. 대상 날짜는 앱처럼 resolvePreset(defaultPreset()).
//   3) 렌더된 HTML(.hero-card / .chip / .urgent-alert)을 파싱하고, 버튼을 실제로 "클릭"해
//      showDetail 로 넘어가는 행사 객체를 받아 온다 → data-idx 가 맞는지 행동 단위로 검사할 수 있다.
//      renderTodayHighlights 안의 지역 변수(combined, reservationsUrgent …)는 `$list.innerHTML =` 바로 앞에
//      심은 캡처 호출로 꺼낸다.
//
// 시간대 / Timezone: 모든 날짜 계산은 KST 로컬 시간이어야 한다. 이 모듈이 맨 처음에 TZ 를 Asia/Seoul 로
// 맞추고 확인하지만, 명령도 `TZ=Asia/Seoul node --test tests/js/` 로 돌리는 것을 권장한다.
// Env: MAIN_JS=<path> 로 다른 main.js(예: 수정 전 버전)를 재생할 수 있다.
//      REPLAY_INCLUDE_ONGOING=0 이면 진행 중 행사 파일(events-ongoing.json)을 풀에서 뺀다 — 기본은 앱처럼 넣는다
//      (아래 buildPool 참고). / set REPLAY_INCLUDE_ONGOING=0 to leave events-ongoing.json out of the pool.
process.env.TZ = "Asia/Seoul";

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, "../..");
export const FIXTURE_DIR = path.join(REPO_ROOT, "tests/fixtures/weekend_replay");
export const DEFAULT_MAIN_JS = path.join(REPO_ROOT, "frontend/public/main.js");
export const EVENT_CATEGORIES = ["festival", "exhibition", "performance"];
export const DAY_MS = 86400000;

// 재생 하네스가 이름으로 직접 부르거나 꼭 있어야 하는 함수 — 없으면 바로 실패
// Functions the harness calls by name; a missing one means main.js was refactored → update this file.
export const REQUIRED_FUNCTIONS = [
  "renderTodayHighlights", "parseDate", "classifyFestival", "resolvePreset", "defaultPreset",
  "_bookingRequired", "_bookingPool", "heroCardHTML", "chipHTML", "escape", "_sameEventLikely",
];
// renderTodayHighlights 안에서 이 문장 바로 앞에 지역 변수 캡처를 심는다
export const CAPTURE_MARKER = "$list.innerHTML =";
export const CAPTURE_LOCALS = ["combined", "hero", "tail", "reservationsUrgent", "reservations", "opensToday", "today"];

// 진행 중 장기 행사 파일(events-ongoing.json)을 풀에 넣을지 — PR #79 이후 main.js init 은 넣는다(true).
// REPLAY_INCLUDE_ONGOING=0 이면 끈다 (PR #79 이전 init 과 비교할 때).
// Since PR #79 main.js init merges events-ongoing.json → on by default; REPLAY_INCLUDE_ONGOING=0 turns it off.
export const INCLUDE_ONGOING_DEFAULT = process.env.REPLAY_INCLUDE_ONGOING !== "0";

{
  const probe = new Date(Date.UTC(2026, 10, 20, 11, 0, 0));  // 2026-11-20 20:00 KST
  if (probe.getHours() !== 20 || probe.getTimezoneOffset() !== -540) {
    throw new Error("[replay_lib] local timezone is not Asia/Seoul — run: TZ=Asia/Seoul node --test tests/js/");
  }
}

export const mainJsPath = () => path.resolve(process.env.MAIN_JS || DEFAULT_MAIN_JS);

// ─────────────────────────── JS 소스 스캐너 / source scanner ───────────────────────────
const REGEX_AFTER_WORD = new Set(["return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
  "throw", "case", "do", "else", "yield", "await"]);

function skipString(src, i) {
  const q = src[i];
  for (let j = i + 1; j < src.length; j++) {
    if (src[j] === "\\") { j++; continue; }
    if (src[j] === q) return j + 1;
    if (src[j] === "\n") return j;  // 깨진 문자열 — 줄 끝에서 멈춤
  }
  return src.length;
}

function skipTemplate(src, i) {
  for (let j = i + 1; j < src.length; j++) {
    if (src[j] === "\\") { j++; continue; }
    if (src[j] === "`") return j + 1;
    if (src[j] === "$" && src[j + 1] === "{") {
      const close = matchPair(src, j + 1);
      if (close < 0) return src.length;
      j = close;
    }
  }
  return src.length;
}

function skipRegex(src, i) {
  let inClass = false;
  for (let j = i + 1; j < src.length; j++) {
    const c = src[j];
    if (c === "\\") { j++; continue; }
    if (c === "\n") return i + 1;  // 정규식이 아니었다 — 나눗셈으로 취급
    if (inClass) { if (c === "]") inClass = false; continue; }
    if (c === "[") { inClass = true; continue; }
    if (c === "/") {
      let k = j + 1;
      while (k < src.length && /[a-z]/i.test(src[k])) k++;
      return k;
    }
  }
  return src.length;
}

// 문자열·템플릿·정규식·주석을 건너뛰며 "코드 문자"만 visit(c, i) 에 넘긴다. visit 이 true 면 그 위치를 돌려준다.
function scanCode(src, start, visit) {
  let i = start, lastSig = "", lastWord = "";
  while (i < src.length) {
    const c = src[i], n = src[i + 1];
    if (c === "/" && n === "/") { const j = src.indexOf("\n", i); i = j < 0 ? src.length : j; continue; }
    if (c === "/" && n === "*") { const j = src.indexOf("*/", i + 2); i = j < 0 ? src.length : j + 2; continue; }
    if (c === '"' || c === "'") { i = skipString(src, i); lastSig = c; lastWord = ""; continue; }
    if (c === "`") { i = skipTemplate(src, i); lastSig = "`"; lastWord = ""; continue; }
    if (c === "/") {
      const regexOk = lastSig === "" || (lastSig === "w" ? REGEX_AFTER_WORD.has(lastWord) : !")]}`\"'".includes(lastSig));
      if (regexOk) { i = skipRegex(src, i); lastSig = "/"; lastWord = ""; continue; }
    }
    if (/[\w$]/.test(c)) {
      let j = i + 1;
      while (j < src.length && /[\w$]/.test(src[j])) j++;
      lastWord = src.slice(i, j); lastSig = "w"; i = j;
      continue;
    }
    if (visit(c, i)) return i;
    if (!/\s/.test(c)) { lastSig = c; lastWord = ""; }
    i++;
  }
  return -1;
}

// src[open] 이 ( [ { 중 하나일 때 짝이 되는 닫는 괄호 위치
function matchPair(src, open) {
  let depth = 0;
  return scanCode(src, open, (c) => {
    if (c === "(" || c === "[" || c === "{") depth++;
    else if ((c === ")" || c === "]" || c === "}") && --depth === 0) return true;
    return false;
  });
}

const DECL_RE = /(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(|class\s+([A-Za-z_$][\w$]*)[\s{]|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[=;]/y;

// 최상위(괄호 깊이 0, 줄 맨 앞) 선언만 뽑는다 → { functions: Map(name → code), decls: [{name, code}] }
export function extractTopLevel(src) {
  const starts = [];
  let depth = 0;
  const tryDecl = (at) => {
    DECL_RE.lastIndex = at;
    const m = DECL_RE.exec(src);
    if (m) starts.push({ at, m });
  };
  tryDecl(0);
  scanCode(src, 0, (c, i) => {
    if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === "\n" && depth === 0) tryDecl(i + 1);
    return false;
  });
  const functions = new Map(), decls = [];
  for (const { at, m } of starts) {
    if (m[1] || m[2]) {
      const name = m[1] || m[2];
      let bodyOpen;
      if (m[1]) {
        const paramsClose = matchPair(src, at + m[0].length - 1);
        bodyOpen = scanCode(src, paramsClose + 1, (c) => c === "{");
      } else {
        bodyOpen = scanCode(src, at + m[0].length - 1, (c) => c === "{");
      }
      const end = bodyOpen < 0 ? -1 : matchPair(src, bodyOpen);
      if (end < 0) throw new Error(`[replay_lib] could not brace-match top-level "${name}" in main.js`);
      if (functions.has(name)) throw new Error(`[replay_lib] duplicate top-level function "${name}" in main.js`);
      functions.set(name, src.slice(at, end + 1));
    } else {
      let d = 0;
      const end = scanCode(src, at, (c, i) => {
        if (c === "(" || c === "[" || c === "{") d++;
        else if (c === ")" || c === "]" || c === "}") d--;
        else if (d === 0 && (c === ";" || (c === "\n" && /\S/.test(src[i + 1] || "")))) return true;
        return false;
      });
      decls.push({ name: m[3], code: src.slice(at, end < 0 ? src.length : end + 1) });
    }
  }
  return { functions, decls };
}

// ─────────────────────────── 가짜 DOM / tiny fake DOM ───────────────────────────
const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
export const decodeEntities = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (all, e) =>
  e[0] === "#" ? String.fromCodePoint(e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : Number(e.slice(1)))
    : ENTITIES[e.toLowerCase()] ?? all);

class TextNode {
  constructor(text, parent) { this.nodeType = 3; this.text = text; this.parentNode = parent; }
  get textContent() { return this.text; }
}

function parseAttrs(s) {
  const attrs = {};
  for (const m of s.matchAll(/([^\s"'>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g)) {
    attrs[m[1].toLowerCase()] = decodeEntities(m[2] ?? m[3] ?? m[4] ?? "");
  }
  return attrs;
}

const TAG_RE = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*(\/?)>/g;

function parseInto(parent, html) {
  for (const n of parent.childNodes) n.parentNode = null;
  parent.childNodes = [];
  const stack = [parent];
  const top = () => stack[stack.length - 1];
  const text = (s) => { if (s) top().childNodes.push(new TextNode(decodeEntities(s), top())); };
  let last = 0;
  for (const m of html.matchAll(TAG_RE)) {
    text(html.slice(last, m.index));
    last = m.index + m[0].length;
    if (m[0].startsWith("<!--")) continue;
    if (m[1]) {
      const tag = m[1].toUpperCase();
      const k = stack.findLastIndex(e => e.tagName === tag);
      if (k > 0) stack.length = k;
      continue;
    }
    const el = new El(m[2], parseAttrs(m[3] || ""), top());
    top().childNodes.push(el);
    if (!VOID_TAGS.has(m[2].toLowerCase()) && !m[4]) stack.push(el);
  }
  text(html.slice(last));
}

// 간단 선택자: 쉼표 목록, 자손(공백)·자식(>) 결합자, 태그/.class/#id/[attr]/[attr="v"]
function parseCompound(s, full) {
  const re = /^(?:([a-zA-Z][\w-]*|\*))?((?:\.[\w-]+|#[\w-]+|\[[\w-]+(?:[~^$*|]?=(?:"[^"]*"|'[^']*'|[^\]]*))?\])*)$/;
  const m = re.exec(s);
  if (!m || !s) throw new Error(`[replay_lib] fake DOM: unsupported selector "${full}" — extend parseCompound()`);
  const parts = { tag: m[1] && m[1] !== "*" ? m[1].toUpperCase() : null, classes: [], id: null, attrs: [] };
  for (const p of m[2].matchAll(/\.([\w-]+)|#([\w-]+)|\[([\w-]+)(?:([~^$*|]?=)(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/g)) {
    if (p[1]) parts.classes.push(p[1]);
    else if (p[2]) parts.id = p[2];
    else parts.attrs.push({ name: p[3].toLowerCase(), op: p[4] || null, value: p[5] ?? p[6] ?? p[7] ?? "" });
  }
  return parts;
}
function parseSelector(sel) {
  return sel.split(",").map(s => s.trim()).filter(Boolean).map(complex => {
    const tokens = complex.replace(/\s*>\s*/g, " > ").split(/\s+/);
    const steps = [];
    let comb = " ";
    for (const t of tokens) {
      if (t === ">") { comb = ">"; continue; }
      steps.push({ comb, c: parseCompound(t, sel) });
      comb = " ";
    }
    return steps;
  });
}
function matchCompound(el, c) {
  if (!el || el.nodeType !== 1) return false;
  if (c.tag && el.tagName !== c.tag) return false;
  if (c.id && el.attrs.id !== c.id) return false;
  const cls = (el.attrs.class || "").split(/\s+/);
  if (!c.classes.every(x => cls.includes(x))) return false;
  return c.attrs.every(({ name, op, value }) => {
    const v = el.attrs[name];
    if (v === undefined) return false;
    if (!op) return true;
    if (op === "=") return v === value;
    if (op === "~=") return v.split(/\s+/).includes(value);
    if (op === "^=") return v.startsWith(value);
    if (op === "$=") return v.endsWith(value);
    if (op === "*=") return v.includes(value);
    if (op === "|=") return v === value || v.startsWith(value + "-");
    return false;
  });
}
function matchSteps(el, steps, k = steps.length - 1) {
  if (!matchCompound(el, steps[k].c)) return false;
  if (k === 0) return true;
  if (steps[k].comb === ">") return matchSteps(el.parentNode, steps, k - 1);
  for (let a = el.parentNode; a && a.nodeType === 1; a = a.parentNode) if (matchSteps(a, steps, k - 1)) return true;
  return false;
}

export class El {
  constructor(tag, attrs = {}, parent = null) {
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.attrs = attrs; this.parentNode = parent;
    this.childNodes = []; this.listeners = {}; this.style = {}; this._html = "";
  }
  get children() { return this.childNodes.filter(n => n.nodeType === 1); }
  get id() { return this.attrs.id || ""; }
  get className() { return this.attrs.class || ""; }
  set className(v) { this.attrs.class = String(v); }
  get classList() {
    const list = () => (this.attrs.class || "").split(/\s+/).filter(Boolean);
    const set = (arr) => { this.attrs.class = arr.join(" "); };
    return {
      contains: c => list().includes(c),
      add: (...cs) => set([...new Set([...list(), ...cs])]),
      remove: (...cs) => set(list().filter(x => !cs.includes(x))),
      toggle: (c, force) => {
        const on = force ?? !list().includes(c);
        set(on ? [...new Set([...list(), c])] : list().filter(x => x !== c));
        return on;
      },
    };
  }
  get dataset() {
    const d = {};
    for (const [k, v] of Object.entries(this.attrs)) {
      if (k.startsWith("data-")) d[k.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())] = v;
    }
    return d;
  }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get textContent() { return this.childNodes.map(n => n.textContent).join(""); }
  set textContent(v) { this.childNodes = [new TextNode(String(v ?? ""), this)]; }
  get innerHTML() { return this._html; }
  set innerHTML(html) { this._html = String(html ?? ""); parseInto(this, this._html); }
  insertAdjacentHTML(_pos, html) { const tmp = new El("div"); parseInto(tmp, String(html)); for (const n of tmp.childNodes) { n.parentNode = this; this.childNodes.push(n); } }
  appendChild(child) { child.parentNode = this; this.childNodes.push(child); return child; }
  append(...cs) { for (const c of cs) this.appendChild(typeof c === "string" ? new TextNode(c, this) : c); }
  remove() { const p = this.parentNode; if (p) p.childNodes = p.childNodes.filter(n => n !== this); this.parentNode = null; }
  getAttribute(n) { return this.attrs[n.toLowerCase()] ?? null; }
  setAttribute(n, v) { this.attrs[n.toLowerCase()] = String(v); }
  hasAttribute(n) { return n.toLowerCase() in this.attrs; }
  removeAttribute(n) { delete this.attrs[n.toLowerCase()]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter(f => f !== fn); }
  dispatchEvent(ev) {
    ev.target ??= this;
    for (let n = this; n && !ev._stopped; n = n.parentNode) {
      ev.currentTarget = n;
      for (const fn of [...(n.listeners?.[ev.type] || [])]) fn.call(n, ev);
    }
    return !ev.defaultPrevented;
  }
  click() {
    return this.dispatchEvent({
      type: "click", key: undefined, defaultPrevented: false, _stopped: false,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this._stopped = true; },
    });
  }
  *_descendants() { for (const n of this.childNodes) if (n.nodeType === 1) { yield n; yield* n._descendants(); } }
  matches(sel) { return parseSelector(sel).some(steps => matchSteps(this, steps)); }
  closest(sel) { for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.matches(sel)) return n; return null; }
  querySelectorAll(sel) { const list = parseSelector(sel); return [...this._descendants()].filter(el => list.some(steps => matchSteps(el, steps))); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  focus() {} blur() {} scrollIntoView() {} scrollTo() {}
  getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
}

function makeDocument() {
  const html = new El("html"), body = new El("body", {}, html);
  html.childNodes.push(body);
  const byId = new Map();
  return {
    documentElement: html, body,
    getElementById(id) {
      if (!byId.has(id)) { const el = new El("div", { id }, body); body.childNodes.push(el); byId.set(id, el); }
      return byId.get(id);
    },
    querySelector: (s) => html.querySelector(s),
    querySelectorAll: (s) => html.querySelectorAll(s),
    createElement: (t) => new El(t),
    addEventListener() {}, removeEventListener() {},
  };
}

function makeStorage() {
  const m = new Map();
  return {
    getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k), clear: () => m.clear(), key: i => [...m.keys()][i] ?? null,
    get length() { return m.size; },
  };
}

// ─────────────────────────── fixtures ───────────────────────────
export function loadFixtures() {
  return fs.readdirSync(FIXTURE_DIR)
    .filter(f => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).sort()
    .map(f => JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, f), "utf8")));
}

export function loadLabels() {
  const j = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, "labels.json"), "utf8"));
  return { labels: j.labels || {}, baseline: j.baseline_p_at_5 || {}, minTotal: j.min_total_p_at_5 ?? 0, raw: j };
}

export const localIso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const parseYmd = (s) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
};

// scripts/export_json.py select_ongoing_events 와 같은 규칙 (순수 문자열 연산):
//   festival/exhibition/performance 중 start < 이번 달 1일 AND end >= 오늘 (둘 다 YYYY-MM-DD 10자),
//   정렬 (start, String(id)). 이전 달 shard 와 일부러 겹친다 — 앱이 id 로 중복 제거.
// Same rule as the exporter's select_ongoing_events.
export function selectOngoingEvents(events, todayIso) {
  const monthStart = `${todayIso.slice(0, 7)}-01`;
  const key = (e) => [(e.start || ""), String(e.id)];
  return events.filter(e => {
    if (!EVENT_CATEGORIES.includes(e.category)) return false;
    const s = (e.start || "").slice(0, 10), t = (e.end || "").slice(0, 10);
    return s.length === 10 && t.length === 10 && s < monthStart && t >= todayIso;
  }).sort((a, b) => {
    const [sa, ia] = key(a), [sb, ib] = key(b);
    return sa < sb ? -1 : sa > sb ? 1 : ia < ib ? -1 : ia > ib ? 1 : 0;
  });
}

// 앱이 받는 events-ongoing.json 의 events (받지 않으면 []):
//   fixture 에 ongoing_file(실제 파일, PR #79 이후 커밋)이 있으면 그대로 — 앱처럼 manifest counts.events_ongoing > 0
//   일 때만. 없으면(PR #79 이전 커밋) fixture 의 모든 행사(shards + ongoing_shards)에 exporter 규칙을 적용해
//   "그날 export 가 만들었을" 파일을 흉내 낸다 (기준일 = 재생일).
// The events-ongoing.json payload the app would load: the real file when the fixture has one, otherwise
// simulated from the fixture's events with the exporter rule (as of the replay day).
export function ongoingFileEvents(fx, now) {
  if (fx.ongoing_file) return (fx.ongoing_file.manifest_events_ongoing || 0) > 0 ? fx.ongoing_file.events : [];
  const all = [...Object.values(fx.shards || {}), ...Object.values(fx.ongoing_shards || {})].flat();
  return selectOngoingEvents(all, localIso(now));
}

// main.js init 과 같은 방식으로 allEventPoi 를 만든다:
//   manifest.events_by_month 에서 n>0 & YYYY-MM 키 → 정렬 → (오늘 −1 ~ +6개월) 안의 달만 → 각 shard 의 events 이어 붙임
//   → (includeOngoing) 그 뒤에 events-ongoing.json 행사 중 id 가 shard 에 없는 것(id 가 없으면 그대로)을 이어 붙임
//   → festival/exhibition/performance 만.
// includeOngoing=false 는 PR #79 이전 init (shard 만).
// Mirrors main.js init: shard events first, then events-ongoing.json events whose id is not in the shards.
export function buildPool(fx, now, { includeOngoing = INCLUDE_ONGOING_DEFAULT } = {}) {
  const months = Object.entries(fx.events_by_month || {})
    .filter(([k, n]) => n > 0 && /^\d{4}-\d{2}$/.test(k))
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([k]) => k);
  const horizon = new Set();
  for (let off = -1; off <= 6; off++) {
    const d = new Date(now.getFullYear(), now.getMonth() + off, 1);
    horizon.add(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  const loadable = months.filter(m => horizon.has(m));
  const missing = loadable.filter(m => !(m in fx.shards));
  if (missing.length) {
    throw new Error(`[replay_lib] fixture ${fx.snapshot} has no shard for ${missing.join(", ")} (clock ${localIso(now)}) — ` +
      "rebuild it with tests/js/build_replay_fixtures.mjs including this day");
  }
  const shardEvents = loadable.flatMap(m => fx.shards[m]);
  let events = shardEvents;
  if (includeOngoing) {
    const shardIds = new Set(shardEvents.map(e => e.id));
    events = shardEvents.concat(ongoingFileEvents(fx, now).filter(e => e.id == null || !shardIds.has(e.id)));
  }
  // 앱이 행사 객체를 건드려도 다른 재생에 새지 않도록 얕은 복사 / shallow copies per replay
  return events.filter(e => EVENT_CATEGORIES.includes(e.category)).map(e => ({ ...e }));
}

// ─────────────────────────── main.js 로딩·재생 / load & replay ───────────────────────────
function compile(code, filename) {
  try { return new vm.Script(code, { filename }); }
  catch (e) { throw new Error(`[replay_lib] ${filename}: extracted code does not compile (${e.message}) — the extractor or main.js changed`); }
}

export function loadMainJs(file = mainJsPath()) {
  const src = fs.readFileSync(file, "utf8");
  const { functions, decls } = extractTopLevel(src);
  const missing = REQUIRED_FUNCTIONS.filter(n => !functions.has(n));
  if (missing.length) {
    throw new Error(`[replay_lib] ${file}: top-level function(s) not found: ${missing.join(", ")}. ` +
      "main.js was refactored — update REQUIRED_FUNCTIONS / the harness in tests/js/replay_lib.mjs.");
  }
  let rth = functions.get("renderTodayHighlights");
  const at = rth.indexOf(CAPTURE_MARKER);
  if (at < 0) {
    throw new Error(`[replay_lib] ${file}: "${CAPTURE_MARKER}" not found inside renderTodayHighlights — ` +
      "update CAPTURE_MARKER in tests/js/replay_lib.mjs");
  }
  const capture = `__replayCapture({ ${CAPTURE_LOCALS.map(n => `${n}: typeof ${n} === "undefined" ? undefined : ${n}`).join(", ")} });\n  `;
  rth = rth.slice(0, at) + capture + rth.slice(at);
  const fnCode = [...functions].map(([n, code]) => (n === "renderTodayHighlights" ? rth : code)).join("\n\n");
  let fnScript;
  try { fnScript = new vm.Script(fnCode, { filename: "main.js#functions" }); }
  catch (e) {
    // 어느 함수가 문제인지 짚어 준다 / pinpoint the offending function
    for (const [n, code] of functions) compile(code, `main.js#${n}`);
    throw e;
  }
  const declScripts = decls.map(d => {
    try { return { name: d.name, script: new vm.Script(d.code, { filename: `main.js#${d.name}` }) }; }
    catch (e) { return { name: d.name, error: e.message }; }
  });
  return {
    file, src,
    functionNames: [...functions.keys()],
    render: (fx, day, opts = {}) => render({ fnScript, declScripts }, fx, day, opts),
  };
}

function render({ fnScript, declScripts }, fx, day, { hour = fx.replay_hour_kst ?? 20, includeOngoing } = {}) {
  const ms = Date.parse(`${day}T${String(hour).padStart(2, "0")}:00:00+09:00`);
  if (Number.isNaN(ms)) throw new Error(`[replay_lib] bad replay day "${day}"`);
  class MockDate extends Date {
    constructor(...a) { if (a.length) super(...a); else super(ms); }
    static now() { return ms; }
  }
  const now = new Date(ms);
  const pool = buildPool(fx, now, includeOngoing === undefined ? undefined : { includeOngoing });
  const locals = {}, details = [];
  const sandbox = {
    console, Date: MockDate, URL, URLSearchParams, Intl,
    document: makeDocument(),
    navigator: { userAgent: "node-replay", language: "ko-KR" },
    location: { href: "http://localhost/", origin: "http://localhost", pathname: "/", search: "", hash: "" },
    localStorage: makeStorage(), sessionStorage: makeStorage(),
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
    requestAnimationFrame: () => 0, cancelAnimationFrame: () => {},
    fetch: () => Promise.reject(new Error("fetch is disabled in replay")),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    __replayCapture: (o) => Object.assign(locals, o),
    __replayDetail: (poi) => { details.push(poi); },
    __data: { allEventPoi: pool },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  fnScript.runInContext(sandbox);
  const declErrors = [];
  for (const d of declScripts) {
    if (d.error) { declErrors.push(`${d.name}: ${d.error}`); continue; }
    try { d.script.runInContext(sandbox); } catch (e) { declErrors.push(`${d.name}: ${e.message}`); }
  }
  vm.runInContext("showDetail = __replayDetail;", sandbox);
  const target = sandbox.resolvePreset(sandbox.defaultPreset());
  sandbox.renderTodayHighlights(target);
  const list = vm.runInContext("$list", sandbox);
  if (!(list instanceof El)) throw new Error("[replay_lib] `$list` is not the fake DOM element — main.js top-level changed");
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return {
    snapshot: fx.snapshot, day, now, today, target, pool, locals, list, ctx: sandbox, declErrors,
    // 버튼을 클릭해 showDetail 로 넘어간 행사를 돌려준다 (없으면 null) / click → POI passed to showDetail
    click(el) {
      const before = details.length;
      el.click();
      return details.length > before ? details[details.length - 1] : null;
    },
  };
}

const _apps = new Map(), _views = new Map();
// 같은 (main.js, fixture, 날짜, 옵션) 재생은 한 번만 / memoized replay
export function replay(fx, day, opts = {}) {
  const file = mainJsPath();
  if (!_apps.has(file)) _apps.set(file, loadMainJs(file));
  const key = JSON.stringify([file, fx.snapshot, day, opts]);
  if (!_views.has(key)) _views.set(key, _apps.get(file).render(fx, day, opts));
  return _views.get(key);
}

// ─────────────────────────── 화면 읽기 / reading the rendered view ───────────────────────────
export const normText = (s) => (s || "").replace(/\s+/g, " ").trim();
const norm = normText;

// 대상 날짜 창: 토요일이면 토~일, 아니면 그날 하루 (main.js 와 독립적으로 테스트가 직접 계산)
export function targetWindow(target) {
  const t0 = new Date(target.getFullYear(), target.getMonth(), target.getDate());
  const t1 = new Date(t0);
  if (target.getDay() === 6) t1.setDate(t1.getDate() + 1);
  return [t0, t1];
}
export function heldOnTarget(p, target) {
  const s = parseYmd(p.start);
  if (!s) return false;
  const e = parseYmd(p.end) || s;
  const [t0, t1] = targetWindow(target);
  return s <= t1 && e >= t0;
}

// ⭐ 추천 Top N 카드 → [{ title, idx, poi }]
export function heroItems(view) {
  return view.list.querySelectorAll(".hero-card").map(el => ({
    el, idx: el.dataset.idx, title: norm(el.querySelector(".hc-title")?.textContent), poi: view.click(el),
  }));
}

// .chip 버튼 전부 (📋 그 외 행사 + 🗓 사전예약 칩 — 둘 다 combined[data-idx] 로 상세를 연다)
export function chipItems(view) {
  return view.list.querySelectorAll(".chip").map(el => ({
    el, idx: el.dataset.idx, title: norm(el.querySelector(".chip-title")?.textContent),
    tail: !el.classList.contains("chip-reservation"), poi: view.click(el),
  }));
}

// 🚨 긴급 알림 상자 항목 → [{ label, kind, text, button, poi }]
export function urgentItems(view) {
  return view.list.querySelectorAll(".urgent-alert li").map(li => {
    const button = li.querySelector(".urg-item");
    return {
      li, button,
      label: norm(li.querySelector("strong")?.textContent),
      kind: norm(li.querySelector(".urg-kind")?.textContent),
      text: norm(li.textContent),
      opens: li.classList.contains("urg-opens"),
      idx: button ? button.dataset.idx : li.dataset.idx,
      poi: button ? view.click(button) : null,
    };
  });
}
