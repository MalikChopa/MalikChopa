'use strict';
// Honest engine state (brief 43): silence is a time, the snapshot replayed after `hello` never revives a silent engine.
const test = require('node:test');
const assert = require('node:assert');
const {Live} = require('./helpers.js');

const T0 = 1_000_000;                       // arbitrary receive time of hello (ms)
const SRV = '2026-11-13T10:00:00Z';
function visit(silentS, nowMs) {
  const S = Live.newView(), link = Live.makeLink();
  link.onOk();
  const feed = (ev, t) => { Live.applyEvent(S, ev, t); if (ev.e === 'hello') link.onHello(); else if (ev.e !== 'status') link.onEvent(S, ev); };
  feed({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: silentS}, nowMs === undefined ? T0 : nowMs);
  return {S, link, feed, label: (t) => Live.label(link, S, t)};
}
const TICK = (t, extra) => Object.assign({e: 'tick', t, hr: 8, m: 'DRIVE', p: [0, 0, 1, 0], tg: null, b: 0.5, v: 0, pi: 0, ro: 0, sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: [], hd: [], y: [0, 0], ev: 0, dr: 0, nd: 0}, extra || {});
// The real snapshot shape, as measured by Diapason on web.py (2026-11-13): sol, poses (all t of the sol), then the last lm, cam and
// tick lines (three DIFFERENT t: 1152, 1192, 1199 in the measured stream), then learn lines, sol_end, phase; all in one burst.
function snapshot(v, t, lastT) {
  const last = lastT === undefined ? 100 : lastT;
  v.feed({e: 'sol', s: 5, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700}, t);
  v.feed({e: 'poses', s: 5, t: Array.from({length: last + 1}, (_, i) => i), p: []}, t + 1);
  v.feed(TICK(last - 47), t + 2);
  v.feed(TICK(last - 7), t + 3);
  v.feed(TICK(last), t + 4);
  v.feed({e: 'phase', ph: 'episode'}, t + 6);
}

test('(a) hello 1000000 only: ENGINE SILENT, not CONNECTING, honest text FR + EN', () => {
  const v = visit(1000000);
  assert.strictEqual(v.link.state, 'LIVE');
  assert.strictEqual(v.label(T0 + 10), 'ENGINE SILENT');
  assert.strictEqual(Live.silentText(v.S, T0 + 10, 'fr'), 'Le moteur ne tourne pas en ce moment : aucune donnée depuis le démarrage du serveur.');
  assert.strictEqual(Live.silentText(v.S, T0 + 10, 'en'), 'The engine is not running right now: no data since the server started.');
});

test('silent for 150 s: text with the duration, FR + EN; formats', () => {
  const v = visit(150);
  assert.strictEqual(v.label(T0 + 10), 'ENGINE SILENT');
  assert.strictEqual(Live.silentText(v.S, T0, 'en'), 'The engine has been silent for 2 min 30 s.');
  assert.strictEqual(Live.silentText(v.S, T0, 'fr'), 'Le moteur est silencieux depuis 2 min 30 s.');
  assert.strictEqual(Live.fmtDuration(45), '45 s');
  assert.strictEqual(Live.fmtDuration(3900), '1 h 5 min');
});

test('(b) hello 150 + snapshot, then a fresh tick 0.6 s later: LIVE', () => {
  const v = visit(150);
  snapshot(v, T0 + 5);
  assert.strictEqual(v.label(T0 + 20), 'ENGINE SILENT');         // the replay alone proves nothing
  v.feed(TICK(101), T0 + 600);
  assert.strictEqual(v.label(T0 + 650), 'LIVE');
});

test('regression rc7: three replayed ticks with different t never revive a silent engine (measured snapshot shape)', () => {
  const v = visit(3797);
  snapshot(v, T0 + 5, 1199);                                      // replays t = 1152, 1192, 1199
  v.feed({e: 'sol_end', s: 5}, T0 + 8);
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T10:15:00Z'}, T0 + 9);
  assert.strictEqual(v.label(T0 + 1000), 'ENGINE SILENT');
  assert.strictEqual(v.label(T0 + 100000), 'ENGINE SILENT');
});

test('a new sol after the snapshot is fresh, and so are its ticks from t = 0', () => {
  const v = visit(150);
  snapshot(v, T0 + 5, 1199);
  v.feed({e: 'sol', s: 6, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700}, T0 + 30000);
  assert.strictEqual(v.label(T0 + 30500), 'LIVE');
  v.feed(TICK(0), T0 + 31000);
  assert.strictEqual(v.label(T0 + 31500), 'LIVE');
});

test('a sol replayed before any tick (no poses): its first tick is fresh', () => {
  const v = visit(150);
  v.feed({e: 'sol', s: 5, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700}, T0 + 2);
  assert.strictEqual(v.label(T0 + 100), 'ENGINE SILENT');
  v.feed(TICK(0), T0 + 700);
  assert.strictEqual(v.label(T0 + 800), 'LIVE');
});

test('(c) hello 150 + snapshot only (even a 2 s old replayed tick): ENGINE SILENT, then still after seconds', () => {
  const v = visit(150);
  snapshot(v, T0 + 5);
  assert.strictEqual(v.label(T0 + 30), 'ENGINE SILENT');
  assert.strictEqual(v.label(T0 + 2000), 'ENGINE SILENT');
  assert.strictEqual(v.label(T0 + 60000), 'ENGINE SILENT');
});

test('(d) hello 0, fresh ticks, then 6 s without tick in episode: ENGINE SILENT', () => {
  const v = visit(0);
  const tick = (t) => ({e: 'tick', t, hr: 8, m: 'DRIVE', p: [0, 0, 1, 0], tg: null, b: 0.5, v: 0, pi: 0, ro: 0, sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: [], hd: [], y: [0, 0], ev: 0, dr: 0, nd: 0});
  v.feed({e: 'sol', s: 5, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700}, T0 + 2);
  for (let i = 0; i < 5; i++) v.feed(tick(i), T0 + 1000 + 700 * i);
  assert.strictEqual(v.label(T0 + 4000), 'LIVE');
  assert.strictEqual(v.label(T0 + 3800 + 6000), 'ENGINE SILENT');
});

test('(e) idle with next in the future: status lines every 60 s keep LIVE; 120 s without any line is ENGINE SILENT', () => {
  const v = visit(0);
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T10:10:00Z'}, T0 + 1000);   // replayed, 600 s ahead
  v.feed({e: 'status', phase: 'idle'}, T0 + 2000);                              // fresh
  assert.strictEqual(v.label(T0 + 62000), 'LIVE');
  v.feed({e: 'status', phase: 'idle'}, T0 + 62000);
  assert.strictEqual(v.label(T0 + 150000), 'LIVE');                             // 88 s since the last line
  assert.strictEqual(v.label(T0 + 185000), 'ENGINE SILENT');                    // 123 s, next still ahead
  v.feed({e: 'status', phase: 'idle'}, T0 + 190000);
  assert.strictEqual(v.label(T0 + 191000), 'LIVE');
});

test('slow link: replayed lines spread over seconds never revive a silent engine', () => {
  const v = visit(150);
  v.feed({e: 'sol', s: 5, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700}, T0 + 100);
  v.feed({e: 'poses', s: 5, t: Array.from({length: 101}, (_, i) => i), p: []}, T0 + 800);   // web.py always sends poses before replayed ticks
  v.feed({e: 'tick', t: 100, hr: 8, m: 'DRIVE', p: [0, 0, 1, 0], tg: null, b: 0.5, v: 0, pi: 0, ro: 0, sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: [], hd: [], y: [0, 0], ev: 0, dr: 0, nd: 0}, T0 + 1500);
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T10:02:00Z'}, T0 + 3000);
  v.feed({e: 'tick', t: 100, hr: 8, m: 'DRIVE', p: [0, 0, 1, 0], tg: null, b: 0.5, v: 0, pi: 0, ro: 0, sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: [], hd: [], y: [0, 0], ev: 0, dr: 0, nd: 0}, T0 + 4500);
  assert.strictEqual(v.label(T0 + 5000), 'ENGINE SILENT');
});

test('a visitor arriving during an idle gap sees LIVE again at the first engine line', () => {
  const v = visit(150);
  v.feed({e: 'sol', s: 5, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700}, T0 + 2);
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T10:02:00Z'}, T0 + 4);   // replayed
  assert.strictEqual(v.label(T0 + 5000), 'ENGINE SILENT');
  v.feed({e: 'status', phase: 'idle'}, T0 + 40000);
  assert.strictEqual(v.label(T0 + 41000), 'LIVE');
});

test('silentText is null once a tick was shown; OFFLINE and SERVER BUSY labels are unchanged', () => {
  const v = visit(0);
  snapshot(v, T0 + 5);
  v.feed({e: 'status', phase: 'episode'}, T0 + 3000);
  assert.strictEqual(Live.silentText(v.S, T0 + 200000, 'en'), null);
  const L = Live.makeLink(), S = Live.newView();
  L.onHttp(503); assert.strictEqual(Live.label(L, S, 5), 'SERVER BUSY');
  const O = Live.makeLink(); O.onNetworkError(); O.onNetworkError(); O.onNetworkError(); assert.strictEqual(Live.label(O, S, 5), 'OFFLINE');
  assert.strictEqual(Live.label(Live.makeLink(), S, 5), 'CONNECTING');
});

// rc11 (brief 44): the data age is the age of what is DRAWN (the last tick), no longer of the engine's last line (RC10-verif I1:
// a status every minute showed "30 s" over a 1 h old image). Old server (no snap_n): a replayed tick is dated at most at the
// engine's last line, as in rc10.
test('fallback (old server): data age is the age of the drawn tick, a fresh status does not make the image younger', () => {
  const v = visit(3797);
  snapshot(v, T0 + 5, 1199);
  assert.strictEqual(Live.dataAgeS(v.S, T0 + 5000), 3802);           // 3797 s at hello + 5 s since
  assert.strictEqual(Live.fmtDuration(Live.dataAgeS(v.S, T0 + 5000)), '1 h 3 min');
  v.feed({e: 'status', phase: 'idle'}, T0 + 6000);                   // a fresh line: the engine speaks, the image is still old
  assert.strictEqual(Live.dataAgeS(v.S, T0 + 8000), 3805);
  const w = visit(40);                                               // no tick at all: age of the engine's last line
  assert.strictEqual(Live.dataAgeS(w.S, T0 + 2000), 42);
});

// Audit rc8 I1: a NEW visitor must not see LIVE for ~110 s when the engine froze mid-episode a few seconds ago.
function frozenMidEpisode(v, t) {      // what web.py replays during an episode: no sol_end yet, last phase line is the stale 'idle'
  v.feed({e: 'sol', s: 9, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700}, t);
  v.feed({e: 'poses', s: 9, t: Array.from({length: 401}, (_, i) => i), p: []}, t + 1);
  v.feed(TICK(352), t + 2); v.feed(TICK(392), t + 3); v.feed(TICK(400), t + 4);
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T10:15:00Z'}, t + 5);
}
test('engine frozen mid-episode 10 s ago: a new visitor sees ENGINE SILENT at once (tick gap), not LIVE for 110 s', () => {
  const v = visit(10);
  frozenMidEpisode(v, T0 + 5);
  assert.strictEqual(v.S.phase, 'episode');                         // the stale replayed 'idle' is ignored
  assert.strictEqual(v.label(T0 + 1000), 'ENGINE SILENT');
});
test('same snapshot with a live engine: LIVE, then still LIVE with fresh ticks', () => {
  const v = visit(0);
  frozenMidEpisode(v, T0 + 5);
  assert.strictEqual(v.label(T0 + 300), 'LIVE');
  v.feed(TICK(401), T0 + 600); v.feed(TICK(402), T0 + 1300);
  assert.strictEqual(v.label(T0 + 1500), 'LIVE');
});
test('a restart line is never replayed: it proves the engine is back', () => {
  const v = visit(150);
  snapshot(v, T0 + 5, 1199);
  assert.strictEqual(v.label(T0 + 1000), 'ENGINE SILENT');
  v.feed({e: 'restart', code_version: 'x'}, T0 + 20000);
  assert.strictEqual(v.label(T0 + 20500), 'LIVE');
});
