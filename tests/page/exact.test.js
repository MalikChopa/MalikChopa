'use strict';
// Exact engine state (brief 44, live-rc11): hello says how many snapshot lines follow (snap_n), in ingest order, and how old the
// last tick and the last phase line are (tick_age_s, phase_age_s). The page uses only these facts, no guess.
const test = require('node:test');
const assert = require('node:assert');
const {Live, Con} = require('./helpers.js');

const T = 5_000_000;                                  // receive time of hello (page clock, ms)
const SRV = '2026-11-13T10:00:00Z';                   // server clock at hello
const TICK = (t, extra) => Object.assign({e: 'tick', s: 9, t, hr: 8, m: 'DRIVE', p: [0, 0, 1, 0], tg: null, b: 0.5, v: 0, pi: 0, ro: 0, sl: 0,
  so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: [], hd: [], y: [0, 0], dr: 0, nd: 0}, extra || {});
const SOL = (s) => ({e: 'sol', s: s || 9, stage: 0, now: SRV, cam: {w: 8, h: 6}, tick_ms: 700, slot0: 0});
const POSES = (n) => ({e: 'poses', s: 9, t: Array.from({length: n}, (_, i) => i), p: []});

// Feed like app.js: hello -> applyEvent + onHello; status -> applyEvent; others -> applyEvent + onEvent.
function visit(hello, snap, at) {
  const S = Live.newView(), link = Live.makeLink();
  link.onOk();
  const feed = (ev, t) => { Live.applyEvent(S, ev, t); if (ev.e === 'hello') link.onHello(); else if (ev.e !== 'status') link.onEvent(S, ev); };
  const h = Object.assign({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: snap.length, tick_age_s: null, phase_age_s: null}, hello);
  const t0 = at === undefined ? T : at;
  feed(h, t0);
  snap.forEach((ev) => feed(ev, t0));
  return {S, link, feed, label: (t) => Live.label(link, S, t), age: (t) => Live.dataAgeS(S, t)};
}

test('normal mid-episode visit: replayed last tick dated by tick_age_s, LIVE, then the 5 s tick gap applies to it', () => {
  const v = visit({engine_silent_s: 0, tick_age_s: 0.3, phase_age_s: 280},
    [{e: 'phase', ph: 'idle', next: '2026-11-13T09:55:00Z'}, SOL(), POSES(401), TICK(352, {cam: ''}), TICK(400)]);
  assert.strictEqual(v.S.phase, 'episode');            // the stale idle came first: the last applied line is the true current one
  assert.strictEqual(v.S.lastTickMs, T - 300);
  assert.strictEqual(v.label(T + 10), 'LIVE');
  assert.strictEqual(v.label(T + 4690), 'LIVE');        // 4.99 s after the tick
  assert.strictEqual(v.label(T + 4710), 'ENGINE SILENT');
  v.feed(TICK(401), T + 400);                           // fresh
  assert.strictEqual(v.S.lastTickMs, T + 400);
  assert.strictEqual(v.label(T + 4710), 'LIVE');
  assert.strictEqual(Live.nextLeftS(v.S, T), null);     // episode: no countdown
});

test('engine frozen mid-episode 7 s ago: a new visitor sees ENGINE SILENT as soon as the snapshot is applied', () => {
  const v = visit({engine_silent_s: 7, tick_age_s: 7.2, phase_age_s: 300},
    [{e: 'phase', ph: 'idle', next: '2026-11-13T09:55:00Z'}, SOL(), POSES(401), TICK(400)]);
  assert.strictEqual(v.label(T + 1), 'ENGINE SILENT');
  assert.strictEqual(v.age(T + 1), 8);                  // ceil(7.201)
  assert.strictEqual(Live.silentText(v.S, T + 1, 'en'), null);   // a frame is shown: no text instead of it
});

test('engine frozen 2 s ago: LIVE for 3 s more, then ENGINE SILENT, exactly like a visitor already connected', () => {
  const v = visit({engine_silent_s: 2, tick_age_s: 2.0}, [SOL(), POSES(11), TICK(10)]);
  assert.strictEqual(v.label(T + 2990), 'LIVE');
  assert.strictEqual(v.label(T + 3010), 'ENGINE SILENT');
});

test('restart then catch-up of the same sol: the restart idle comes AFTER the old ticks, so the engine is not in an episode', () => {
  const v = visit({engine_silent_s: 3, tick_age_s: 14.5, phase_age_s: 3.1},
    [SOL(), POSES(601), TICK(560, {cam: ''}), TICK(600), {e: 'phase', ph: 'idle', next: '2026-11-13T09:45:00Z'}]);
  assert.strictEqual(v.S.phase, 'idle');
  assert.strictEqual(v.label(T + 1000), 'LIVE');
  assert.strictEqual(v.label(T + 116000), 'LIVE');      // 3 + 116 = 119 s since the engine's last line
  assert.strictEqual(v.label(T + 118000), 'ENGINE SILENT');
  assert.strictEqual(Live.nextLeftS(v.S, T + 1000), null);   // next (slot start) is past: no "0:00"
  assert.strictEqual(v.age(T + 1000), 16);              // the drawn frame is 14.5 s + 1 s old
  v.feed({e: 'ff', s: 9, from: 601, to: 640, why: 'restart'}, T + 20000);
  v.feed(TICK(641), T + 20000);
  assert.strictEqual(v.S.phase, 'episode');
  assert.strictEqual(v.label(T + 140000 - 116000), 'LIVE');
});

test('snap_n is a count: the lines after it are fresh whatever they are; the lines inside it never are', () => {
  const v = visit({engine_silent_s: 200, tick_age_s: 210, phase_age_s: 300}, [SOL(), POSES(11), TICK(10)]);
  assert.strictEqual(v.label(T + 1), 'ENGINE SILENT');
  v.feed({e: 'phase', ph: 'learn'}, T + 5000);          // fresh (4th line after hello): the engine speaks
  assert.strictEqual(v.S.engineLastMs, T + 5000);
  assert.strictEqual(v.label(T + 6000), 'LEARNING');
  const w = visit({engine_silent_s: 200, snap_n: 2}, []);
  w.feed({e: 'status', phase: 'idle'}, T + 10);         // counted as snapshot line 1 of 2 (never sent by a real server)
  assert.strictEqual(w.S.engineLastMs, T - 200000);
  w.feed({e: 'sol_end', s: 9}, T + 20);                 // line 2 of 2
  w.feed({e: 'status', phase: 'idle'}, T + 30);         // fresh
  assert.strictEqual(w.S.engineLastMs, T + 30);
});

test('while the snapshot is still arriving the banner says CONNECTING (or ENGINE SILENT when hello already proves it)', () => {
  const S = Live.newView(), link = Live.makeLink();
  link.onOk();
  Live.applyEvent(S, {e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: 3, tick_age_s: 9, phase_age_s: null}, T); link.onHello();
  Live.applyEvent(S, SOL(), T + 50); link.onEvent(S, SOL());
  assert.strictEqual(Live.label(link, S, T + 100), 'CONNECTING');
  Live.applyEvent(S, POSES(5), T + 60);
  Live.applyEvent(S, TICK(4), T + 70); link.onEvent(S, TICK(4));
  assert.strictEqual(Live.label(link, S, T + 100), 'ENGINE SILENT');   // complete now: last tick 9 s old, in an episode
  const Q = Live.newView(), l2 = Live.makeLink();
  Live.applyEvent(Q, {e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 500, snap_n: 3}, T); l2.onHello();
  assert.strictEqual(Live.label(l2, Q, T + 1), 'ENGINE SILENT');
});

test('end-of-sol window: data age = age of the last tick, not of the last learn / sol_end / phase line', () => {
  const v = visit({engine_silent_s: 4, tick_age_s: 163.4, phase_age_s: 4.2},
    [SOL(), POSES(1200), TICK(1199), {e: 'phase', ph: 'learn'}, {e: 'learn', s: 9, mod: 'm3', gen: 1, of: 2, best: 1, mean: 0.5},
     {e: 'learn', s: 9, mod: 'm3', gen: 2, of: 2, best: 2, mean: 0.7}, {e: 'sol_end', s: 9, stage: 0}, {e: 'phase', ph: 'idle', next: '2026-11-13T10:01:00Z'}]);
  assert.strictEqual(v.S.phase, 'idle');
  assert.strictEqual(v.age(T), 164);
  assert.strictEqual(v.label(T), 'LIVE');
  assert.strictEqual(v.S.learn.gen, 2);                 // ingest order: phase learn BEFORE its learn lines, they are kept
  assert.strictEqual(Live.nextLeftS(v.S, T), 60);
  v.feed({e: 'status', phase: 'idle'}, T + 30000);
  assert.strictEqual(v.age(T + 30000), 194);            // a status proves the engine is alive, not that the image is new
});

test('idle countdown uses the server clock of hello, a later line does not shift it; it disappears once next is past', () => {
  const v = visit({engine_silent_s: 1, phase_age_s: 1}, [SOL(), POSES(1200), TICK(1199), {e: 'phase', ph: 'idle', next: '2026-11-13T10:10:00Z'}]);
  assert.strictEqual(Live.nextLeftS(v.S, T), 600);
  v.feed({e: 'status', phase: 'idle'}, T + 60000);
  assert.strictEqual(Live.nextLeftS(v.S, T + 60000), 540);   // rc10 counted from the last event: 600 again here
  assert.strictEqual(Live.nextLeftS(v.S, T + 599000), 1);
  assert.strictEqual(Live.nextLeftS(v.S, T + 600000), null);
  assert.strictEqual(Live.nextLeftS(v.S, T + 900000), null);
});

test('hold: ENGINE HOLD banner (FR + EN), honest text with the hold duration, no countdown, data age of the last frame', () => {
  const v = visit({engine_silent_s: 30, tick_age_s: 3734, phase_age_s: 3600},
    [SOL(), POSES(1200), TICK(1199), {e: 'phase', ph: 'idle', next: '2026-11-13T09:00:00Z'}, {e: 'phase', ph: 'hold', why: 'check', utc: '2026-11-13T09:00:00Z'}]);
  assert.strictEqual(v.label(T), 'ENGINE HOLD');
  assert.strictEqual(Live.extraLabel('ENGINE HOLD', 'fr'), 'MOTEUR EN PAUSE');
  assert.strictEqual(Live.extraLabel('ENGINE HOLD', 'en'), 'ENGINE ON HOLD');
  assert.strictEqual(Live.holdText(v.S, T, 'fr'), 'Le moteur est en pause depuis 1 h 0 min : aucun nouveau sol avant un redémarrage du moteur.');
  assert.strictEqual(Live.holdText(v.S, T, 'en'), 'The engine has been on hold for 1 h 0 min: no new sol until the engine is restarted.');
  assert.strictEqual(v.S.nextUtc, null);
  assert.strictEqual(Live.nextLeftS(v.S, T), null);
  assert.strictEqual(v.age(T), 3734);
  assert.strictEqual(v.label(T + 89000), 'ENGINE HOLD');         // 119 s without a status
  assert.strictEqual(v.label(T + 91000), 'ENGINE SILENT');       // the engine stopped writing its status
  v.feed({e: 'status', phase: 'hold', h: 'hold'}, T + 95000);
  assert.strictEqual(v.label(T + 95000), 'ENGINE HOLD');
  assert.strictEqual(v.age(T + 95000), 3829);
  v.feed({e: 'restart', code_version: 'x'}, T + 200000);         // restarted by someone: the hold is over
  assert.strictEqual(v.label(T + 200000), 'LIVE');
  assert.strictEqual(Live.holdText(v.S, T + 200000, 'en'), null);
});

test('hold seen live by a connected visitor: duration counted from the fresh phase line; older server: no duration', () => {
  const v = visit({engine_silent_s: 0, tick_age_s: 0.5}, [SOL(), POSES(5), TICK(4)]);
  v.feed({e: 'phase', ph: 'hold', why: 'prepare', utc: SRV}, T + 1000);
  assert.strictEqual(Live.holdText(v.S, T + 61000, 'en'), 'The engine has been on hold for 1 min 0 s: no new sol until the engine is restarted.');
  const S = Live.newView();                                       // older server: hello without snap_n, replayed hold
  Live.applyEvent(S, {e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 20}, T);
  Live.applyEvent(S, {e: 'phase', ph: 'hold', why: 'check'}, T);
  assert.strictEqual(Live.holdText(S, T, 'fr'), 'Le moteur est en pause : aucun nouveau sol avant un redémarrage du moteur.');
});

test('hold drawn on the canvas as ENGINE HOLD, not END OF SOL | WAITING', () => {
  const v = visit({engine_silent_s: 0, tick_age_s: 1}, [SOL(), POSES(5), TICK(4, {cam: Buffer.alloc(48).toString('base64')})]);
  const a = new Uint8Array(640 * 360), b = new Uint8Array(640 * 360);
  v.feed({e: 'phase', ph: 'idle', next: SRV}, T + 1);
  Live.renderLive(a, v.S, null);
  v.feed({e: 'phase', ph: 'hold', why: 'check'}, T + 2);
  Live.renderLive(b, v.S, null);
  assert.notDeepStrictEqual(Buffer.from(a), Buffer.from(b));
  const c = new Uint8Array(640 * 360);
  Con.text(c, 160, 6, 'ENGINE HOLD', Con.hud(10), 1);
  let same = 0, set = 0;
  for (let i = 0; i < c.length; i++) if (c[i]) { set++; if (b[i] === c[i]) same++; }
  assert.ok(set > 0 && same === set, 'ENGINE HOLD title not drawn');
});

test('an engine attempt failure ends the tick flow of the sol (no false silence); a publisher attempt (k = -1) does not', () => {
  const v = visit({engine_silent_s: 0, tick_age_s: 0.2}, [SOL(), POSES(301), TICK(300)]);
  v.feed({e: 'attempt', k: -1, err: 'publish lease refused'}, T + 500);
  assert.strictEqual(v.S.phase, 'episode');
  v.feed({e: 'attempt', k: 0, err: 'ValueError: x'}, T + 600);
  assert.strictEqual(v.S.phase, null);
  assert.strictEqual(v.label(T + 60000), 'LIVE');                // status lines (every 60 s) keep it alive, no 5 s tick gap
  assert.strictEqual(v.label(T + 121000), 'ENGINE SILENT');
  const w = visit({engine_silent_s: 2, tick_age_s: 40}, [SOL(), POSES(301), TICK(300), {e: 'attempt', k: 0, err: 'x'}]);
  assert.strictEqual(w.label(T + 1), 'LIVE');                    // a new visitor gets the same answer (attempt is in the snapshot)
});

test('sol rollover: a fresh sol keeps the visit fields; its ticks are fresh', () => {
  const v = visit({engine_silent_s: 1, tick_age_s: 100, phase_age_s: 1}, [SOL(8), POSES(1200), TICK(1199, {s: 8}), {e: 'phase', ph: 'idle', next: SRV}]);
  v.feed({e: 'status', phase: 'idle'}, T + 1000);
  v.feed(SOL(9), T + 2000);
  assert.ok(v.S.exact && v.S.snapLeft === 0 && v.S.engineLastMs === T + 2000 && v.S.hasTick === false);
  v.feed(TICK(0), T + 2700);
  assert.strictEqual(v.S.sol, 9);
  assert.strictEqual(v.label(T + 3000), 'LIVE');
  assert.strictEqual(v.age(T + 3000), 1);
});

test('data age is rounded up and never below the time since the frame was received', () => {
  const v = visit({engine_silent_s: 0}, [SOL()]);
  v.feed(TICK(0), T + 1000);
  assert.strictEqual(v.age(T + 1000), 0);
  assert.strictEqual(v.age(T + 1001), 1);
  assert.strictEqual(v.age(T + 3999), 3);
  assert.strictEqual(v.age(T + 4000), 3);
});

test('same lines without snap_n (older server): the rc10 fallback is used, with snap_n: the exact rule', () => {
  const snap = [{e: 'phase', ph: 'idle', next: SRV}, SOL(), POSES(401), TICK(400)];
  const old = Live.newView(), neu = Live.newView();
  Live.applyEvent(old, {e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 2}, T);
  Live.applyEvent(neu, {e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 2, snap_n: 4, tick_age_s: 2.5, phase_age_s: 280}, T);
  snap.forEach((e) => { Live.applyEvent(old, e, T); Live.applyEvent(neu, e, T); });
  assert.strictEqual(old.exact, false);
  assert.strictEqual(old.burst, true);                            // rc10: still in the replay until a provably fresh line
  assert.strictEqual(old.lastTickMs, T - 2000);                   // rc10: a replayed tick is dated at the engine's last line
  assert.strictEqual(neu.exact, true);
  assert.strictEqual(neu.lastTickMs, T - 2500);
  Live.applyEvent(old, TICK(400), T + 100);                       // rc10: a tick not newer than poses is still replay
  assert.strictEqual(old.engineLastMs, T - 2000);
  Live.applyEvent(neu, TICK(400), T + 100);                       // exact: after snap_n lines, fresh
  assert.strictEqual(neu.engineLastMs, T + 100);
});

test('an unreadable line is still counted (app.js calls countLine), so the next line is fresh', () => {
  const v = visit({engine_silent_s: 50, tick_age_s: 50}, []);
  const S = Live.newView();
  Live.applyEvent(S, {e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 50, snap_n: 1, tick_age_s: null, phase_age_s: null}, T);
  assert.strictEqual(Live.countLine(S, T + 1), false);              // the snapshot's only line, unreadable
  Live.applyEvent(S, {e: 'status', phase: 'idle'}, T + 2000);
  assert.strictEqual(S.engineLastMs, T + 2000);
  assert.strictEqual(v.S.snapLeft, 0);
  const src = require('fs').readFileSync(require('path').join(__dirname, '..', '..', 'pages', 'live', 'app.js'), 'utf8');
  assert.ok(/catch \(e\) \{ Live\.countLine\(S, now\(\)\); return; \}/.test(src));
});
