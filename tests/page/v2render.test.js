'use strict';
// Page v2 (live-rc14): the canvas in the page language and the page-only corrections (DESIGN.md §7, §8, §12 T2, T3, T4, T9, T17,
// T18). States from the TEST streams only (tests/page/fixtures, page_helpers.js states()); never the real rover's data.
const test = require('node:test');
const assert = require('node:assert');
const {Con, Live, events} = require('./helpers.js');
const {TB, tx, opts, hasText, findText, states, waitingStates, LABELS, I18N} = require('./page_helpers.js');

const STATES = states();
function render(S, lang, extra) { const b = new Uint8Array(640 * 360), boxes = []; Live.renderLive(b, S, null, opts(lang, Object.assign({boxes}, extra || {}))); return {b, boxes}; }

test('T2 English table without page options = the parity drawing, byte for byte, on every compared frame of the fixtures', () => {
  let n = 0;
  for (const stage of [0, 1, 2, 3, 4, 5, 'fake5']) {
    const S = Live.newView(), a = new Uint8Array(640 * 360), b = new Uint8Array(640 * 360);
    events(stage).forEach((e, k) => {
      Live.applyEvent(S, e, 1000 * k);
      if (e.e !== 'tick' || k % 10) return;
      Con.renderConsole(a, S, {scanlines: true});
      Con.renderConsole(b, S, {scanlines: true, t: TB.en, en: TB.en, dec: '.'});
      assert.ok(Buffer.from(a).equals(Buffer.from(b)), `stage ${stage} tick ${e.t}`);
      n++;
    });
  }
  assert.ok(n >= 70, `${n} frames`);
});

// T3: the page corrections (EN, o.page) change pixels only where a correction lives: header band, CAM-1 picture (outline, SUN,
// LAST FRAME, night), brain panel (locked texts M10, pause views), telemetry (D1) and arm / scan (M4, M10, D8); never the map
const ZONES = [[0, 0, 640, 21], [7, 23, 329, 225], [336, 24, 632, 224], [136, 232, 384, 352], [392, 232, 632, 352]];
test('T3 page corrections stay inside their zones (English, live states of every stage)', () => {
  for (const [name, S] of Object.entries(STATES)) {
    if (!S.hasTick || !S.camDims || Live.pauseTitle(S) !== null) continue;
    const a = new Uint8Array(640 * 360);
    Con.renderConsole(a, S, {scanlines: true});
    const {b} = render(S, 'en');
    for (let y = 0; y < 360; y++) for (let x = 0; x < 640; x++) {
      if (a[y * 640 + x] === b[y * 640 + x]) continue;
      assert.ok(ZONES.some((z) => x >= z[0] && x < z[2] && y >= z[1] && y < z[3]), `${name}: pixel ${x},${y} changed outside the correction zones`);
    }
  }
});

function inter(a, b) { return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h; }
// a text box is strictly inside a frame (not on its border) or entirely outside it
function clearOf(t, f) { return !inter(t, f) || (t.x > f.x && t.y > f.y && t.x + t.w < f.x + f.w && t.y + t.h < f.y + f.h); }   // borders: rows f.y, f.y + f.h - 1
function check(all, tag) {
  const texts = all.filter((p) => !p.frame), frames = all.filter((p) => p.frame);
  for (let i = 0; i < texts.length; i++) {
    const p = texts[i];
    assert.ok(p.x >= 0 && p.y >= 0 && p.x + p.w <= 640 && p.y + p.h <= 360, `${tag}: ${p.s} outside`);
    for (let j = i + 1; j < texts.length; j++) assert.ok(!inter(p, texts[j]), `${tag}: «${p.s}» overlaps «${texts[j].s}»`);
    for (const f of frames) assert.ok(clearOf(p, f), `${tag}: «${p.s}» ${JSON.stringify([p.x, p.y, p.w, p.h])} crosses the frame ${JSON.stringify([f.x, f.y, f.w, f.h])}`);
  }
  return texts.length;
}
test('T4 no text box overlaps another or crosses a frame, accents included, in every state x {en, fr} x states of the link', () => {
  Con.setStrict(true);                  // T10: an unknown character is an error, not a '?'
  let checked = 0;
  try {
    for (const [name, S] of Object.entries(STATES)) for (const lang of ['en', 'fr']) for (const label of LABELS) {
      const {boxes} = render(S, lang, {label});
      assert.ok(check(boxes, `${name} ${lang} ${label}`) >= 5, `${name} ${lang}: too few texts`);
      checked++;
    }
    for (const [label, S] of waitingStates()) for (const lang of ['en', 'fr']) {
      const boxes = [], b = new Uint8Array(640 * 360);
      Con.setBoxes(boxes); Live.renderWaiting(b, S, opts(lang, {label})); Con.setBoxes(null);
      check(boxes, `waiting ${label} ${lang}`);
    }
  } finally { Con.setStrict(false); }
  assert.ok(checked >= 400, `${checked} renders`);
});

// T9: in French, no English word on the canvas nor in the status texts, except names, units and data (list below, from I18N.md)
const ALLOWED = new Set(['SOL', 'CAM', 'REC', 'UTC', 'PX', 'ARI', 'AX', 'BAT', 'OK', 'CONF', 'CAT', 'GAIN', 'SCAN', 'DEG', 'CM', 'GRA', 'DUR',
  'M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'R2']);
const FR_WORDS = new Set();
for (const v of Object.values(I18N)) for (const w of v.fr.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().match(/[A-Z][A-Z0-9]+/g) || []) FR_WORDS.add(w);
function englishWords(s) {
  return (s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').match(/\b[A-Z][A-Z0-9]+\b/g) || [])
    .filter((w) => !ALLOWED.has(w) && !FR_WORDS.has(w) && !/^[BKNT]\d+$/.test(w));
}
test('T9 French page: every word drawn on the canvas and written in the status texts is French, a name, a unit or data', () => {
  const bad = new Set();
  for (const [name, S] of Object.entries(STATES)) for (const label of LABELS) {
    const {boxes} = render(S, 'fr', {label});
    boxes.filter((p) => !p.frame).forEach((p) => englishWords(p.s).forEach((w) => bad.add(`${name}: ${w} in «${p.s}»`)));
    const o = opts('fr');
    [Live.barLine(S, o), Live.stageBar(S, o), Live.seasonLine(S, o) || '', Live.summaryText(S, o, '2 s', {cell_m: 5, tick_s: 72})]
      .forEach((s) => englishWords(s.toUpperCase()).forEach((w) => bad.add(`${name} DOM: ${w} in «${s}»`)));
  }
  assert.deepStrictEqual([...bad], []);
  // and the English page draws English (the FR buffer differs from the EN one in every state with words: UI-AUDIT B1)
  for (const [name, S] of Object.entries(STATES)) assert.ok(!Buffer.from(render(S, 'fr').b).equals(Buffer.from(render(S, 'en').b)), name);
});

test('T18 SOL START = the real start of the slot (slot0 of the sol line, UTC); nothing without it; never the nominal `now`', () => {
  const S = STATES['st3-day'];
  const want = tx('en', 'c.hdr.right', {hh: '12', mm: '15'});            // slot0 = 2026-11-13T12:15:00Z (test value)
  assert.strictEqual(Live.headerRight(S, opts('en'), 'LIVE'), want);
  const {b} = render(S, 'en');
  assert.ok(hasText(b, 632 - Con.textWidth(want), 6, want, Con.hud(10)));
  assert.ok(!findText(b, S.now.slice(11, 16), Con.hud(10), [0, 0, 640, 20]), 'the nominal time is drawn');
  assert.strictEqual(Live.headerRight(Object.assign({}, S, {slot0: null}), opts('en'), 'LIVE'), '');
  assert.strictEqual(Live.headerRight(S, opts('fr'), 'LIVE'), 'DÉBUT DU SOL 12:15 UTC');
  // a sol line carries slot0; a tick of another sol without its line forgets it (solChanged)
  const v = Live.newView();
  Live.applyEvent(v, {e: 'sol', s: 5, stage: 0, stage_name: 'AWAKENING', now: '2026-11-13T12:27:00Z', slot0: Date.parse('2026-11-13T12:15:00Z'), cam: {w: 8, h: 6, D: 1}}, 0);
  assert.strictEqual(v.slot0, Date.parse('2026-11-13T12:15:00Z'));
  Live.applyEvent(v, {e: 'tick', s: 6, t: 0, hr: 5, m: 'SLEEP', p: [0, 0, 1, 0], b: 1, v: 0, pi: 0, ro: 0, sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0],
    x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0]}, 1);
  assert.strictEqual(v.slot0, null);
  // D17: when the console is not live, the header says the state instead (same words as the badge)
  for (const [label, key] of [['ENGINE SILENT', 'silent'], ['ENGINE HOLD', 'hold'], ['RESUMING', 'resuming'], ['CONNECTING', 'connecting']]) {
    assert.strictEqual(Live.headerRight(S, opts('fr'), label), I18N['d.state.' + key].fr);
  }
});

test('T17 waiting card: nothing drawable yet, the frames and the announced next sol (fixed UTC time), no value of any sol', () => {
  const S = Live.newView();
  Live.applyEvent(S, {e: 'phase', ph: 'idle', next: '2026-11-13T12:15:00Z'}, 0);
  for (const lang of ['en', 'fr']) {
    const b = new Uint8Array(640 * 360);
    Live.renderWaiting(b, S, opts(lang, {label: 'LIVE'}));
    const msg = tx(lang, 'c.wait.idle'), nxt = tx(lang, 'c.wait.next', {hh: '12', mm: '15', ss: '00'});
    assert.ok(findText(b, msg, Con.MARK, [8, 24, 328, 224]), msg);
    assert.ok(findText(b, nxt, Con.MARK, [8, 24, 328, 224]), nxt);
    assert.ok(!findText(b, 'SOL ', Con.hud(10), [140, 0, 640, 20]), 'a sol number in the header');
  }
  const t = new Uint8Array(640 * 360);
  Live.renderWaiting(t, Live.newView(), opts('fr', {label: 'ENGINE SILENT'}));
  assert.ok(findText(t, 'MOTEUR SILENCIEUX', Con.MARK, [8, 24, 328, 224]));
});

test('page fixes: D1 battery « AT STAGE 3 » in the bar\'s place (no glued line), D14 REC, D12 night under NO IMAGE YET, M4, M5, D13', () => {
  const S = STATES['st0-night'];
  for (const lang of ['en', 'fr']) {
    const {b} = render(S, lang);
    const at = tx(lang, 'c.tel.atstage', {n: 3});
    assert.ok(hasText(b, 136 + 170, 232 + 30 + 22 + 3, at, Con.hud(7)), at);
    assert.ok(!findText(b, tx(lang, 'c.tel.fromstage', {n: 3}), Con.hud(7)), 'FROM STAGE line still drawn');
  }
  // REC: red only while fresh ticks are drawn (label LIVE, no pause, awake)
  const day = STATES['st3-day'], REC = 51;
  assert.strictEqual(render(day, 'en', {label: 'LIVE'}).b[10 * 640 + 115], REC);
  assert.notStrictEqual(render(day, 'en', {label: 'ENGINE SILENT'}).b[10 * 640 + 115], REC);
  assert.notStrictEqual(render(STATES['pause-learn'], 'en', {label: 'LEARNING'}).b[10 * 640 + 115], REC);
  // D12: no image and night text: the night text goes under NO IMAGE YET
  const n = STATES['st1-night-noimage'], nt = Live.nightText(n, opts('fr'));
  assert.ok(nt && /^NUIT \| SOMMEIL \| LEVER DU SOLEIL \d\d:\d\d$/.test(nt), nt);
  assert.ok(hasText(render(n, 'fr').b, 8 + Math.floor((320 - Con.textWidth(nt)) / 2), 148, nt, Con.MARK));
  // M4: no cloud -> NO SCAN YET, never « K 0 N 0 AX 0% »; M5: DISTANCE 735 M
  const sc = Object.assign({}, STATES['fake5-drive'], {scan: {pts: [], k: 0, ax: 0, names: {}}});
  if (sc.stage >= 5) assert.ok(findText(render(sc, 'en').b, 'NO SCAN YET', Con.hud(10), [392, 232, 632, 352]));
  assert.ok(findText(render(STATES['pause-endofsol'], 'fr').b, 'DISTANCE 735 M', Con.hud(10), [336, 24, 632, 224]));
  assert.ok(findText(render(STATES['pause-endofsol'], 'fr').b, 'PROGRÈS 40%', Con.hud(10), [336, 24, 632, 224]));
  // D13: LAST FRAME right-aligned above SENSOR, clear of the SUN compass
  const h = STATES['pause-hold'];
  if (h.cam) { const lf = tx('en', 'c.pause.lastframe', {n: h.camT}); assert.ok(hasText(render(h, 'en', {label: 'ENGINE HOLD'}).b, 324 - Con.textWidth(lf), 202, lf, Con.MARK)); }
});
