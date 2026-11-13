'use strict';
// Page v2 (live-rc14): layout maths (DESIGN.md §3, §12 T5, T6) and the anchor router (§6, T12). Pure functions, no browser.
const test = require('node:test');
const assert = require('node:assert');
const {fs, path, PAGE} = require('./helpers.js');
const Lay = require(path.join(PAGE, 'layout.js'));
const Route = require(path.join(PAGE, 'route.js'));

// DESIGN.md §3.6 (computed there with the same rules; ± 1 px: the design table rounds to the pixel). VERIF-rc14 I2 (live-rc15): the
// three compact rows (phone in landscape) have a header row of 32 px AND a status row of 26 px above the console, « Details » under
// the fold: DESIGN's one 32 px row (484x272, 581x327, 537x302) does not hold the header and the bar side by side on a phone's width.
const ROWS = [
  // [vw, vh, dpr, insets, mode, compact, {id: [cssW, cssH, integer]}, overlay {cam, brain, map: [w, h]}]
  [320, 568, 2, null, 'panels', false, {cam: [304, 191], brain: [296, 200, true], map: [304, 304], tel: [304, 147], inst: [304, 152]}, {cam: [304, 190], brain: [296, 200], map: [304, 304]}],
  [375, 667, 2, null, 'panels', false, {cam: [359, 225], brain: [359, 243], map: [359, 359], tel: [359, 174], inst: [359, 180]}, {cam: [359, 225], brain: [359, 242], map: [359, 359]}],
  [390, 664, 3, null, 'panels', false, {cam: [374, 235], brain: [374, 253], map: [366, 366, true], tel: [374, 181], inst: [374, 187]}, {cam: [374, 235], brain: [374, 253], map: [366, 366]}],
  [568, 320, 2, null, 'console', true, {console: [459, 258, false]}, {cam: [414, 260], brain: [384, 260], map: [244, 244]}],
  [667, 375, 2, null, 'console', true, {console: [556, 313, false]}, {cam: [483, 303], brain: [444, 300], map: [305, 305]}],
  [844, 350, 3, {l: 47, r: 47}, 'console', true, {console: [512, 288, false]}, {cam: [429, 269], brain: [395, 267], map: [285, 285]}],
  [768, 954, 2, null, 'panels', false, {cam: [752, 472], brain: [740, 500, true], map: [244, 244, true], tel: [496, 240, true], inst: [720, 360, true]}, {cam: [752, 472], brain: [740, 500], map: [732, 732]}],
  [1024, 698, 2, null, 'console', false, {console: [960, 540, true]}, {cam: [966, 606], brain: [888, 600], map: [610, 610]}],
  [1024, 768, 1, null, 'console', false, {console: [1008, 567, false]}, {cam: [966, 606], brain: [888, 600], map: [610, 610]}],
  [1440, 789, 2, null, 'console', false, {console: [1189, 669, false]}, {cam: [1127, 707], brain: [1036, 700], map: [671, 671]}],
  [1440, 900, 1, null, 'console', false, {console: [1280, 720, true]}, {cam: [1288, 808], brain: [1184, 800], map: [732, 732]}],
  [1920, 969, 1, null, 'console', false, {console: [1280, 720, true]}, {cam: [1288, 808], brain: [1184, 800], map: [854, 854]}],
  [2560, 1305, 1, null, 'console', false, {console: [1920, 1080, true]}, {cam: [1932, 1212], brain: [1776, 1200], map: [1220, 1220]}],
  [2560, 1440, 2, null, 'console', false, {console: [2240, 1260, true]}, {cam: [2093, 1313], brain: [1924, 1300], map: [1342, 1342]}]];

test('T5 the 14 windows of DESIGN.md §3.6: mode, compact, sizes (± 1 px), integer scale where the design says so, never wider than the space', () => {
  for (const [vw, vh, dpr, ins, mode, compact, want, ov] of ROWS) {
    const p = Lay.plan(vw, vh, dpr, ins), tag = `${vw}x${vh}@${dpr}`;
    assert.strictEqual(p.mode, mode, tag); assert.strictEqual(p.compact, compact, tag);
    const avail = vw - Math.max(8, (ins && ins.l) || 0) - Math.max(8, (ins && ins.r) || 0);
    for (const [id, [w, h, integer]] of Object.entries(want)) {
      const f = id === 'console' ? p.console : p.panels[id];
      assert.ok(Math.abs(f.cssW - w) <= 1 && Math.abs(f.cssH - h) <= 1, `${tag} ${id}: ${f.cssW}x${f.cssH}, design ${w}x${h}`);
      if (integer !== undefined) assert.strictEqual(f.integer, integer, `${tag} ${id} integer`);
      assert.ok(f.cssW <= avail + 1e-9, `${tag} ${id} wider than the space`);
      assert.ok(f.scale * dpr >= 1 - 1e-9, `${tag} ${id}: under one device pixel per console pixel`);
    }
    for (const [id, [w, h]] of Object.entries(ov)) {
      const f = p.overlay[id];
      assert.ok(Math.abs(f.cssW - w) <= 1 && Math.abs(f.cssH - h) <= 1, `${tag} overlay ${id}: ${f.cssW}x${f.cssH}, design ${w}x${h}`);
    }
    if (mode === 'panels') {
      const g = p.groups.find((x) => x.ids.length === 2);
      assert.strictEqual(g.split, vw < 600, `${tag} map + telemetry side by side only when wide enough`);
    }
  }
  // B6: the floor, one device pixel per console pixel at least (a 300 px wide window at density 1)
  const f = Lay.fit(640, 360, 300, 600, 1);
  assert.ok(f.floor && f.scale === 1 && f.cssW === 640);
  // integer scale: exact multiples of the device pixel
  for (const [vw, vh, dpr] of [[1440, 900, 1], [2560, 1440, 2], [1024, 698, 2]]) { const c = Lay.plan(vw, vh, dpr).console; assert.ok(Number.isInteger(c.scale * dpr)); }
  // rotate hint: portrait, a panel wider than high, under 1.5x
  assert.strictEqual(Lay.plan(375, 667, 2).overlay.cam.rotate, true);
  assert.strictEqual(Lay.plan(1440, 900, 1).overlay.cam.rotate, false);
});

test('T6 the clickable zones of live.css are the panel rectangles (± 0.001 %)', () => {
  const css = fs.readFileSync(path.join(PAGE, 'live.css'), 'utf8');
  for (const id of Lay.ORDER) {
    const m = new RegExp(`\\.hit-${id} \\{ left: ([\\d.]+)%; top: ([\\d.]+)%; width: ([\\d.]+)%; height: ([\\d.]+)%; \\}`).exec(css);
    assert.ok(m, `.hit-${id} missing`);
    const want = Lay.cssPercents(id);
    ['left', 'top', 'width', 'height'].forEach((k, i) => assert.ok(Math.abs(+m[i + 1] - want[k]) <= 0.001, `${id} ${k} ${m[i + 1]} vs ${want[k]}`));
  }
  // the canvases of the panels have the panel's natural size (index.html)
  const html = fs.readFileSync(path.join(PAGE, 'index.html'), 'utf8');
  for (const id of Lay.ORDER) {
    const p = Lay.PANELS[id];
    assert.ok(html.includes(`<canvas id="pc-${id}" width="${p[2]}" height="${p[3]}"`), id);
  }
});

test('T12 router: anchors parsed, old links kept, nothing but [a-z0-9-] tokens, canonical forms round-trip', () => {
  const C = [
    ['#fr/live', 'fr', 'live', null], ['#en/about', 'en', 'about', null], ['#fr/live/cam', 'fr', 'live', 'cam'], ['#en/about/brain', 'en', 'about', 'brain'],
    ['#fr', 'fr', 'live', null], ['#en', 'en', 'live', null], ['#FR', 'fr', 'live', null], ['#Fr/About', 'fr', 'about', null],
    ['#about', 'en', 'about', null], ['#live', 'en', 'live', null], ['', 'en', 'live', null], ['#', 'en', 'live', null],
    ['#<img src=x>', 'en', 'live', null], ['#fr/live/../about', 'fr', 'about', null], ['#fr/live/brain/cam', 'fr', 'live', 'brain'],
    ['#en/live/nope', 'en', 'live', null], ['#en/about/nope', 'en', 'about', null], ['#fr/about/map', 'fr', 'about', 'console'],
    ['#fr/about/what', 'fr', 'about', 'intro'], ['#en/about/camera', 'en', 'about', 'camera'], ['#en/live/inst', 'en', 'live', 'inst'],
    ['#en/fr/live', 'en', 'live', null], ['#x-fr-cerveau', 'en', 'live', null], ['#fr/live/cam?x=1', 'fr', 'live', null],
    ['#fr/about/faq', 'fr', 'about', 'faq'], ['#javascript:alert(1)', 'en', 'live', null], ['#' + 'a'.repeat(40), 'en', 'live', null]];
  for (const [h, lang, tab, sub] of C) assert.deepStrictEqual(Route.parse(h, 'en-US'), {lang, tab, sub}, h);
  assert.strictEqual(Route.parse('#about', 'fr-CA').lang, 'fr');
  assert.strictEqual(Route.parse('', 'fr').lang, 'fr');
  for (const h of ['#fr/live', '#en/about', '#fr/live/cam', '#en/about/brain', '#fr/about/glossary']) assert.strictEqual(Route.serialize(Route.parse(h, 'en')), h);
  // no element id of the page equals an anchor (they contain '/', ids never do): the browser never jumps by itself
  const html = fs.readFileSync(path.join(PAGE, 'index.html'), 'utf8') + fs.readFileSync(path.join(PAGE, 'about', 'fr.html'), 'utf8');
  for (const m of html.matchAll(/\sid="([^"]+)"/g)) assert.ok(!m[1].includes('/'), m[1]);
  // every section of the router exists in both fragments, with a focusable title; every panel's help section exists
  for (const l of ['fr', 'en']) {
    const f = fs.readFileSync(path.join(PAGE, 'about', l + '.html'), 'utf8');
    for (const s of Route.SECTIONS) assert.ok(f.includes(`<h3 id="${l}-${s}" tabindex="-1">`), `${l}-${s}`);
    for (const m of f.matchAll(/href="#(fr|en)\/about\/([a-z-]+)"/g)) { assert.strictEqual(m[1], l); assert.ok(Route.SECTIONS.includes(m[2]), m[2]); }
  }
  for (const id of Route.PANEL_IDS) assert.ok(Route.SECTIONS.includes(Route.HELP[id]), id);
});

test('T14a EF-87 guard: 20 requests in 1 s -> at most 3 switches applied, the last request wins', () => {
  let t = 0; const timers = [];
  const g = Route.makeGuard(350, {now: () => t, setTimer: (f, ms) => { timers.push({at: t + ms, f}); return timers.length; }});
  const applied = [];
  for (let i = 0; i < 20; i++) {
    t = i * 50;
    while (timers.length && timers[0].at <= t) timers.shift().f();
    g.request(() => applied.push([t, i]));
  }
  while (timers.length) { t = timers[0].at; timers.shift().f(); }
  assert.ok(applied.length <= 4 && applied.length >= 2, JSON.stringify(applied));
  assert.strictEqual(applied[applied.length - 1][1], 19);
  for (let i = 1; i < applied.length; i++) assert.ok(applied[i][0] - applied[i - 1][0] >= 350, JSON.stringify(applied));
  const inOneSecond = applied.filter((a) => a[0] < 1000).length;
  assert.ok(inOneSecond <= 3, `${inOneSecond} switches in the first second`);
});
