'use strict';
// Page v2 test helpers (not a *.test.js file): the i18n table, texts looked for on the canvas, and a bench of real-shaped states
// built from the TEST streams only (tests/page/fixtures = test seeds; never the real rover's data).
const {Con, Live, events, fs, path, PAGE} = require('./helpers.js');

const I18N = JSON.parse(fs.readFileSync(path.join(PAGE, 'i18n.json'), 'utf8')).strings;
const TB = {en: {}, fr: {}};
for (const k of Object.keys(I18N)) { TB.en[k] = I18N[k].en; TB.fr[k] = I18N[k].fr; }
function tx(lang, id, v) {
  if (!(id in I18N)) throw new Error('no text id ' + id);
  return Live.tr({t: TB[lang]}, id, I18N[id].en, v);
}
// `now`: the page's clock (VERIF-rc14 M4: the waiting card draws the next sol's time only while it is ahead); a fixed test time,
// before the `next` of the test states (2026-11-13T12:15:00Z), so that every render is the same whatever the machine's clock
const TEST_NOW = Date.parse('2026-11-13T12:00:00Z');
function opts(lang, extra) {
  return Object.assign({page: true, scanlines: true, t: TB[lang], en: TB.en, dec: lang === 'fr' ? ',' : '.', lang, label: 'LIVE', now: TEST_NOW}, extra || {});
}
// glyph pixels of `s` (accents included), relative to its (x, y)
function glyphOffsets(s, color, scale) {
  const c = new Uint8Array(640 * 360), ox = 10, oy = 10;
  Con.text(c, ox, oy, s, color, scale || 1);
  const out = [];
  for (let i = 0; i < c.length; i++) if (c[i]) out.push([(i % 640) - ox, Math.floor(i / 640) - oy]);
  return out;
}
function hasText(buf, x, y, s, color, scale) {
  const g = glyphOffsets(s, color, scale);
  return g.length > 0 && g.every(([dx, dy]) => buf[(y + dy) * 640 + x + dx] === color);
}
// first position where every glyph pixel of `s` is `color` (optionally inside rect [x0, y0, x1, y1]); null if none
function findText(buf, s, color, rect, scale) {
  const g = glyphOffsets(s, color, scale);
  if (!g.length) return null;
  const r = rect || [0, 0, 640, 360];
  for (let y = r[1]; y < r[3]; y++) for (let x = r[0]; x < r[2]; x++) {
    let ok = true;
    for (let i = 0; i < g.length && ok; i++) {
      const px = x + g[i][0], py = y + g[i][1];
      ok = px >= 0 && px < 640 && py >= 0 && py < 360 && buf[py * 640 + px] === color;
    }
    if (ok) return [x, y];
  }
  return null;
}

// ---- bench of states (DESIGN.md §12): name -> S (fresh object each call) ----
const SRV = '2026-11-13T10:00:00Z';
function fixtureState(stage, pick) {     // the state after the tick `pick` ('first', 'night', 'day', 'last' or a predicate)
  const ev = events(stage), S = Live.newView();
  let n = 0, chosen = null;
  for (const e of ev) {
    Live.applyEvent(S, e, 1000 * n++);
    if (e.e !== 'tick') continue;
    if (typeof pick === 'function' ? pick(e, S) : (pick === 'first' || (pick === 'night' && e.m === 'SLEEP') || (pick === 'day' && e.m !== 'SLEEP'))) { chosen = true; break; }
  }
  if (!chosen && pick !== 'last') return null;
  return S;
}
function aug(S, extra) {                // the stage fixtures predate `sun`, `season_sols` and a real `slot0` in the sol line (test values)
  S.sunTimes = S.sunTimes || {lever: 5.99, coucher: 18.01}; S.seasonSols = S.seasonSols || 150;
  S.slot0 = Date.parse('2026-11-13T12:15:00Z');
  return Object.assign(S, extra || {});
}
function states() {
  const out = {};
  for (const st of [0, 1, 2, 3, 4, 5]) {
    const d = fixtureState(st, 'day'), n = fixtureState(st, 'night'), l = fixtureState(st, 'last');
    if (d) out[`st${st}-day`] = aug(d);
    if (n) out[`st${st}-night`] = aug(n);
    if (l) out[`st${st}-last`] = aug(l);
  }
  for (const m of ['DRILL', 'ANALYZE', 'SEEK_SUN', 'SLEEP', 'DRIVE']) {
    const s = fixtureState('fake5', (e) => e.m === m);
    if (s) out[`fake5-${m.toLowerCase()}`] = aug(s);
  }
  const flags = aug(fixtureState(2, 'day') || fixtureState(2, 'last'));
  flags.stuck = true; flags.tipped = true; out['st2-stuck-tipped'] = flags;
  const noimg = aug(fixtureState(1, 'night')); noimg.cam = null; out['st1-night-noimage'] = noimg;
  // pause views (phases applied on a real state)
  const learn = aug(fixtureState(5, 'last'));
  Live.applyEvent(learn, {e: 'phase', ph: 'learn'}, 1e6);
  Live.applyEvent(learn, {e: 'learn', mod: 'm4', gen: 7, of: 12, best: 0.42, mean: -0.13, val: {}}, 1e6);
  Live.applyEvent(learn, {e: 'learn', mod: 'm5', gen: 1, of: 2, best: 0.2, mean: 0.1, val: {k: 4, ari: 0.61}}, 1e6);
  Live.applyEvent(learn, {e: 'learn', mod: 'battery', gen: 1, of: 1, best: 1, mean: 1, val: {successes: 20}}, 1e6);
  out['pause-learn'] = learn;
  const check = aug(fixtureState(3, 'last'));
  ['learn', 'render', 'save', 'check'].forEach((ph) => Live.applyEvent(check, {e: 'phase', ph}, 1e6));
  Live.applyEvent(check, {e: 'learn', mod: 'm1', gen: 2, of: 2, best: 0.3, mean: 0.2, val: {r2: 0.53}}, 1e6);
  out['pause-check'] = check;
  const idle = aug(fixtureState(4, 'last'));
  ['learn', 'render', 'check', 'save', 'idle'].forEach((ph) => Live.applyEvent(idle, {e: 'phase', ph, next: ph === 'idle' ? '2026-11-13T12:30:00Z' : undefined}, 1e6));
  Live.applyEvent(idle, {e: 'sol_end', stage: 4, progress: {fraction: 0.4, label: 'drills', value: '4/10 SAMPLES', blocking: null}, distance_m: 735.1325,
    targets: 3, attempts: 1, battery_successes: 20}, 1e6);
  out['pause-endofsol'] = idle;
  const hold = aug(fixtureState(5, 'day'));
  Live.applyEvent(hold, {e: 'phase', ph: 'hold', why: 'check'}, 1e6);
  out['pause-hold'] = hold;
  const res = aug(fixtureState(3, 'day'));
  res.resuming = true; out['pause-resuming'] = res;
  // bare views: a sol line, no tick yet; a tick without any sol line
  const bare = Live.newView();
  Live.applyEvent(bare, {e: 'sol', s: 1234, stage: 2, stage_name: 'LEARNING TO DRIVE', now: SRV, slot0: Date.parse('2026-11-13T12:15:00Z'), cam: {w: 32, h: 20, D: 1}, tick_ms: 650,
    sun: {lever: 5.99, coucher: 18.01}, season_sols: 150}, 0);
  out['bare-solline'] = bare;
  const bare2 = Live.newView();
  const t0 = events(2).find((e) => e.e === 'tick');
  Live.applyEvent(bare2, Object.assign({}, t0, {s: 77}), 0);
  out['bare-notick-sol'] = bare2;
  return out;
}
// waiting cards (nothing drawable): label -> S
function waitingStates() {
  const a = Live.newView();
  const b = Live.newView(); Live.applyEvent(b, {e: 'phase', ph: 'idle', next: '2026-11-13T12:15:00Z'}, 0);
  const c = Live.newView(); Live.applyEvent(c, {e: 'phase', ph: 'learn'}, 0);
  return [['CONNECTING', a], ['LIVE', b], ['LIVE', c], ['LIVE', a], ['ENGINE SILENT', a], ['ENGINE HOLD', a], ['SERVER BUSY', a], ['RESUMING', a], ['REPLAY', a]];
}
const LABELS = ['LIVE', 'LEARNING', 'REPLAY', 'ENGINE SILENT', 'ENGINE HOLD', 'RESUMING', 'CONNECTING', 'SERVER BUSY'];

module.exports = {I18N, TB, TEST_NOW, tx, opts, glyphOffsets, hasText, findText, states, waitingStates, LABELS, fixtureState, aug};
