// 금요일 스냅샷 재생 회귀 테스트 — "목·금 저녁에 이번 주말 계획" 화면이 망가지지 않았는지.
// Weekend replay regression tests: replays real Friday data snapshots (tests/fixtures/weekend_replay)
// through the CURRENT frontend/public/main.js renderTodayHighlights at 20:00 KST.
//
// 정확한 순서 스냅샷이 아니라 "불변 조건(invariant)" 만 검사한다 → 랭킹·예약 상자 정렬을 고쳐도 계속 통과해야 한다.
// Invariants only (no exact order snapshots), so ranking / urgent-box ordering changes keep passing.
//
// run:  TZ=Asia/Seoul node --test tests/js/
//       MAIN_JS=/tmp/old-main.js TZ=Asia/Seoul node --test tests/js/   # 다른 main.js 재생
import { describe, test } from "node:test";
import assert from "node:assert/strict";
import * as R from "./replay_lib.mjs";

const fixtures = R.loadFixtures();
const { labels, baseline, minTotal } = R.loadLabels();
const bySnap = Object.fromEntries(fixtures.map(fx => [fx.snapshot, fx]));
// Top 5 P@5 는 금요일 시각(fixture.days 의 마지막)으로 잰다. 11-19 목요일 데이터는 11-20(금) 20:00 으로.
const primaryDay = (fx) => fx.days[fx.days.length - 1];
const isFamilyPick = (fx, p) => (labels[fx.snapshot] || []).some(k => (p?.title || "").includes(k));
const short = (s, n = 28) => (s || "").slice(0, n);
// 화면 제목과 행사 제목 비교 — 공백은 정규화 / compare shown title vs event title, whitespace-normalized
const sameTitle = (shown, poi) => !!poi && R.normText(shown) === R.normText(poi.title || shown);

function fixtureOrFail(snapshot) {
  const fx = bySnap[snapshot];
  assert.ok(fx, `fixture ${snapshot}.json missing — rebuild with tests/js/build_replay_fixtures.mjs`);
  return fx;
}

test("fixtures present and main.js loads", (t) => {
  assert.ok(fixtures.length >= 7, `expected >= 7 weekend fixtures, found ${fixtures.length}`);
  const v = R.replay(fixtures[0], fixtures[0].days[0]);
  assert.ok(Array.isArray(v.locals.combined), "renderTodayHighlights no longer has a local `combined` — update CAPTURE_LOCALS in replay_lib");
  assert.ok(v.list.querySelector(".hero-card"), "no .hero-card rendered — hero markup changed? update heroItems() in replay_lib");
  t.diagnostic(`main.js = ${R.mainJsPath()}`);
  if (v.declErrors.length) t.diagnostic(`top-level declarations that failed in the sandbox: ${v.declErrors.join("; ")}`);
});

describe("⭐ Top 5 — 그 주말에 열리는 행사만 / only events held on the target weekend", () => {
  for (const fx of fixtures) {
    for (const day of fx.days) {
      test(`${fx.snapshot} @ ${day} 20:00 KST`, () => {
        const v = R.replay(fx, day);
        const hero = R.heroItems(v);
        assert.ok(hero.length > 0, "no Top-5 cards rendered");
        const unresolved = hero.filter(h => !h.poi);
        assert.deepEqual(unresolved.map(h => h.title), [], "Top-5 card click did not open a detail");
        const [t0, t1] = R.targetWindow(v.target);
        const notThisWeekend = hero.filter(h => !R.heldOnTarget(h.poi, v.target))
          .map(h => `${short(h.poi.title)} (${h.poi.start}~${h.poi.end || ""})`);
        assert.deepEqual(notThisWeekend, [],
          `Top 5 has events not held on ${R.localIso(t0)}~${R.localIso(t1)}`);
      });
    }
  }
});

describe("⭐ Top 5 — 가족 라벨 적중 P@5 / family-label hits (single-rater labels)", () => {
  for (const fx of fixtures) {
    test(`${fx.snapshot}: P@5 >= baseline`, (t) => {
      if (!labels[fx.snapshot]) { t.skip(`no labels for ${fx.snapshot} in labels.json`); return; }
      const v = R.replay(fx, primaryDay(fx));
      const hero = R.heroItems(v);
      const hits = hero.filter(h => isFamilyPick(fx, h.poi)).length;
      t.diagnostic(`P@5=${hits} :: ` + hero.map(h => `${isFamilyPick(fx, h.poi) ? "✓" : "✗"}${short(h.title, 16)}`).join(" | "));
      const base = baseline[fx.snapshot];
      if (base !== undefined) assert.ok(hits >= base, `P@5 ${hits} < baseline ${base} for ${fx.snapshot}`);
    });
  }
  test(`total P@5 >= ${minTotal}`, (t) => {
    const labelled = fixtures.filter(fx => labels[fx.snapshot]);
    let total = 0;
    for (const fx of labelled) {
      const v = R.replay(fx, primaryDay(fx));
      total += R.heroItems(v).filter(h => isFamilyPick(fx, h.poi)).length;
    }
    t.diagnostic(`total P@5 = ${total} / ${labelled.length * 5}`);
    assert.ok(total >= minTotal, `total P@5 ${total} < ${minTotal}`);
  });
});

describe("📋 칩 클릭 → 같은 행사 상세 / every chip opens its own event", () => {
  for (const fx of fixtures) {
    for (const day of fx.days) {
      test(`${fx.snapshot} @ ${day}`, () => {
        const v = R.replay(fx, day);
        const chips = R.chipItems(v);
        assert.ok(chips.some(c => c.tail), "no tail (그 외 행사) chips rendered");
        const bad = chips.filter(c => !sameTitle(c.title, c.poi))
          .map(c => `data-idx=${c.idx} shows "${short(c.title)}" but opens "${short(c.poi?.title) || "(nothing)"}"`);
        assert.deepEqual(bad.slice(0, 5), [], `${bad.length}/${chips.length} chips open the wrong event`);
      });
    }
  }
  test("Top-5 cards open their own event", () => {
    for (const fx of fixtures) {
      const v = R.replay(fx, primaryDay(fx));
      for (const h of R.heroItems(v)) {
        assert.ok(sameTitle(h.title, h.poi), `${fx.snapshot}: hero card data-idx=${h.idx} shows "${short(h.title)}" but opens "${short(h.poi?.title) || "(nothing)"}"`);
      }
    }
  });
});

describe("🚨 예약 긴급 알림 — D-day 는 실제 오늘 기준 / booking D-day counts from the real today", () => {
  for (const fx of fixtures) {
    for (const day of fx.days) {
      test(`${fx.snapshot} @ ${day}: every booking item due today..+7 is in the urgent pool`, () => {
        const v = R.replay(fx, day);
        const { combined, reservationsUrgent } = v.locals;
        assert.ok(Array.isArray(combined), "local `combined` not captured — update CAPTURE_LOCALS in replay_lib");
        assert.ok(Array.isArray(reservationsUrgent), "local `reservationsUrgent` not captured — update CAPTURE_LOCALS in replay_lib");
        const inPool = (p) => reservationsUrgent.some(x => {
          const q = x?.poi ?? x;
          return q === p || (q?.title === p.title && q?.start === p.start);
        });
        const missing = [];
        for (const p of combined) {
          if (!v.ctx._bookingRequired(p)) continue;
          const ref = R.parseYmd(p.booking_deadline) || R.parseYmd(p.start);
          if (!ref) continue;
          const d = Math.round((ref - v.today) / R.DAY_MS);
          if (d >= 0 && d <= 7 && !inPool(p)) missing.push(`D-${d} ${short(p.title)} (deadline ${p.booking_deadline || "-"}, start ${p.start})`);
        }
        assert.deepEqual(missing, [], `booking items due within 7 days of ${R.localIso(v.today)} missing from the urgent pool`);
      });
      test(`${fx.snapshot} @ ${day}: every urgent-box item is a button that opens its own event`, () => {
        const v = R.replay(fx, day);
        const bad = R.urgentItems(v).filter(u => !u.button || !u.poi || !u.text.includes(R.normText(u.poi.title.slice(0, 40))))
          .map(u => `"${short(u.text, 40)}" → ${u.button ? `opens "${short(u.poi?.title) || "(nothing)"}"` : "not a .urg-item button"}`);
        assert.deepEqual(bad, [], "urgent-box items that do not open their own event");
      });
    }
  }

  const visible = (snapshot, day) => R.urgentItems(R.replay(fixtureOrFail(snapshot), day));

  test("11-19 (목) 20:00: 장수탕 선녀님 is shown as D-1 마감", () => {
    const items = visible("2026-11-19", "2026-11-19");
    const u = items.find(x => x.text.includes("장수탕 선녀님"));
    assert.ok(u, `장수탕 선녀님 not in the urgent box: ${items.map(x => short(x.text, 24)).join(" | ") || "(empty)"}`);
    assert.equal(u.label, "D-1");
    assert.equal(u.kind, "마감");
  });

  test("11-06 (금) 20:00: 뮤지컬 <다시,봄> is shown as 오늘 마감", () => {
    const items = visible("2026-11-06", "2026-11-06");
    const u = items.find(x => /다시, ?봄/.test(x.text));
    assert.ok(u, `'다시,봄' not in the urgent box: ${items.map(x => short(x.text, 24)).join(" | ") || "(empty)"}`);
    assert.equal(u.label, "오늘");
    assert.equal(u.kind, "마감");
  });

  test("11-06 (금) 20:00: 부산불꽃축제 (Sat 11-07) is not labelled 오늘", () => {
    const fw = visible("2026-11-06", "2026-11-06").filter(x => /부산불꽃축제|밤하늘의 하모니/.test(x.text));
    assert.deepEqual(fw.filter(x => x.label === "오늘").map(x => x.text), []);
  });
});

describe("replay_lib self-checks", () => {
  test("includeOngoing adds only older-shard events still running today", () => {
    for (const fx of fixtures) {
      const day = primaryDay(fx);
      const now = new Date(Date.parse(`${day}T20:00:00+09:00`));
      const base = R.buildPool(fx, now, { includeOngoing: false });
      const withOngoing = R.buildPool(fx, now, { includeOngoing: true });
      const extra = withOngoing.slice(0, withOngoing.length - base.length);
      assert.ok(extra.length >= 0 && withOngoing.length >= base.length);
      assert.ok(extra.every(e => (e.end || "") >= day), `${fx.snapshot}: extra event already ended`);
      assert.deepEqual(withOngoing.slice(extra.length).map(e => e.id), base.map(e => e.id));
    }
  });
  test("top-level extractor matches braces inside strings, templates and regex literals", () => {
    const src = [
      "const A = /[{}\\/]`/g;",
      "function f(a = { x: \"}\" }) {",
      "  const t = `${a.x}}{${'}'}`; // }",
      "  return /\\}/.test(t) ? t.length / 2 : 0; /* } */",
      "}",
      "let z;",
      "async function g() { return `}`; }",
    ].join("\n");
    const { functions, decls } = R.extractTopLevel(src);
    assert.deepEqual([...functions.keys()], ["f", "g"]);
    assert.ok(functions.get("f").endsWith("0; /* } */\n}"));
    assert.deepEqual(decls.map(d => d.name), ["A", "z"]);
  });
});
