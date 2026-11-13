'use strict';
// Age of the IMAGE, link cuts, resumes without a `sol` line (brief 45, live-rc12; RC12-verif I1, M1, M3, M4, M5).
// CAM-1 gives an image every 8 ticks only (config/rover.toml cam_period); after an engine restart the engine broadcasts only the last
// due tick (engine.py R2), which may have no image: the image on screen can be much older than the last tick.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs'), path = require('path');
const {Live, Con, assets} = require('./helpers.js');

const T = 5_000_000;                                  // receive time of the first hello (page clock, ms)
const SRV = '2026-11-13T10:00:00Z';
const CAM = (w, h, v) => Buffer.alloc(w * h, v === undefined ? 3 : v).toString('base64');
const TICK = (t, extra) => Object.assign({e: 'tick', s: 9, t, hr: 8.5, m: 'DRIVE', p: [10, 20, 1, 0], tg: null, b: 0.5, v: 0.1, pi: 0, ro: 0,
  sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0], dr: 0, nd: 0}, extra || {});
const CTICK = (t, extra) => TICK(t, Object.assign({cam: CAM(8, 6, t % 24), z: new Array(40).fill(0)}, extra || {}));
const SOL = (s, extra) => Object.assign({e: 'sol', s: s === undefined ? 9 : s, stage: 0, stage_name: 'WAKE', now: SRV, cam: {w: 8, h: 6, D: 1},
  tick_ms: 600, slot0: 0, sun: {lever: 6, coucher: 18}, season_sols: 150}, extra || {});
const POSES = (n, s) => ({e: 'poses', s: s === undefined ? 9 : s, t: Array.from({length: n}, (_, i) => i), p: []});

// Feed like app.js: hello -> applyEvent + onHello; status -> applyEvent; others -> applyEvent + onEvent; a cut -> link.onLost().
function visitor() {
  const S = Live.newView(), link = Live.makeLink();
  link.onOk();
  const v = {S, link, labels: []};
  v.feed = (ev, t) => {
    Live.applyEvent(S, ev, t);
    if (ev.e === 'hello') link.onHello(); else if (ev.e !== 'status') link.onEvent(S, ev);
  };
  v.hello = (h, snap, t) => {
    v.feed(Object.assign({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: snap.length, tick_age_s: null, cam_age_s: null,
      phase_age_s: null}, h), t);
    snap.forEach((ev) => v.feed(ev, t));
  };
  v.label = (t) => Live.label(link, S, t);
  v.age = (t) => Live.dataAgeS(S, t);
  return v;
}
function draw(S) { const b = new Uint8Array(640 * 360); Live.renderLive(b, S, null); return b; }
// true when every pixel of `s` drawn alone at (x, y) is set to the same palette index in buf
function hasText(buf, x, y, s, color) {
  const c = new Uint8Array(640 * 360);
  Con.text(c, x, y, s, color, 1);
  let set = 0, same = 0;
  for (let i = 0; i < c.length; i++) if (c[i]) { set++; if (buf[i] === c[i]) same++; }
  return set > 0 && same === set;
}

test('I1 restart after the end of the slot: only tick 1199 (no image) is broadcast; the age is the image\'s, LAST FRAME T992', () => {
  const v = visitor();
  v.hello({tick_age_s: 0.2, cam_age_s: 0.2}, [SOL(), POSES(993), CTICK(992)], T);
  for (let t = 993; t <= 999; t++) v.feed(TICK(t), T + 600 * (t - 992));        // fresh, no image (cam every 8 ticks)
  const camMs = T - 200;                                                        // true time of the image = hello - cam_age_s
  assert.strictEqual(v.S.camT, 992);
  assert.strictEqual(v.S.camMs, camMs);
  assert.strictEqual(v.age(T + 4200), 5);                                       // ceil(4.4): the image, not the tick 999 (0 s)
  const tr = T + 4200 + 300_000;                                                // the engine was stopped 300 s, past the slot end
  v.feed({e: 'restart', code_version: 'x'}, tr);
  v.feed({e: 'status', phase: 'idle', h: 'ok', utc: SRV}, tr + 10);
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T09:45:00Z'}, tr + 20);
  v.feed({e: 'status', phase: 'episode', h: 'ok', utc: SRV}, tr + 60_000);
  v.feed({e: 'ff', s: 9, from: 1000, to: 1198, why: 'restart'}, tr + 70_000);
  v.feed(TICK(1199), tr + 70_000);                                              // the last due tick: no image
  v.feed({e: 'phase', ph: 'learn', utc: SRV}, tr + 70_300);
  for (const t of [tr + 70_000, tr + 70_500, tr + 200_000]) {
    const truth = (t - camMs) / 1000;
    assert.ok(v.age(t) >= Math.floor(truth) && v.age(t) <= truth + 1, `age ${v.age(t)} vs image ${truth}`);
  }
  assert.strictEqual(v.S.t, 1199);
  assert.strictEqual(v.S.camT, 992);
  const b = draw(v.S);                                                          // pause view (learning)
  assert.ok(hasText(b, 12, 213, 'LAST FRAME T992', Con.MARK), 'LAST FRAME T992 not drawn');
  assert.ok(!hasText(b, 12, 213, 'LAST FRAME T1199', Con.MARK), 'LAST FRAME T1199 drawn on the image of tick 992');
  // a new visitor after the restart: the server says how old the image is
  const w = visitor(), t2 = tr + 80_000;
  w.hello({engine_silent_s: 2, tick_age_s: 10.0, cam_age_s: (t2 - camMs) / 1000, phase_age_s: 9.7},
    [SOL(), POSES(1200), CTICK(992), TICK(1199), {e: 'phase', ph: 'learn', utc: SRV}], t2);
  assert.strictEqual(w.age(t2), Math.ceil((t2 - camMs) / 1000));
  assert.strictEqual(w.S.camT, 992);
  assert.strictEqual(w.label(t2), 'LEARNING');
});

test('I1 restart whose first broadcast tick has no image: the image of tick 600 keeps its own age until the next image', () => {
  const v = visitor();
  v.hello({tick_age_s: 0.1, cam_age_s: 0.1}, [SOL(), POSES(601), CTICK(600)], T);
  for (let t = 601; t <= 607; t++) v.feed(TICK(t), T + 600 * (t - 600));
  const tr = T + 20_000;
  v.feed({e: 'restart'}, tr);
  v.feed({e: 'status', phase: 'idle', utc: SRV}, tr + 5);
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T09:45:00Z'}, tr + 6);
  v.feed({e: 'ff', s: 9, from: 608, to: 633, why: 'restart'}, tr + 30_000);
  v.feed(TICK(634), tr + 30_000);                                               // first broadcast tick: no image
  assert.strictEqual(v.S.phase, 'episode');
  assert.strictEqual(v.age(tr + 30_000), Math.ceil((tr + 30_000 - (T - 100)) / 1000));
  assert.strictEqual(v.label(tr + 30_100), 'LIVE');
  for (let t = 635; t <= 640; t++) v.feed(t === 640 ? CTICK(640) : TICK(t), tr + 30_000 + 600 * (t - 634));
  assert.strictEqual(v.S.camT, 640);
  assert.strictEqual(v.age(tr + 30_000 + 600 * 6 + 1), 1);                    // the new image is fresh
  // an older server (rc11: snap_n, no cam_age_s): the image is dated like the replayed tick, never younger
  const o = visitor();
  o.hello({tick_age_s: 3.0}, [SOL(), POSES(635), CTICK(600), TICK(634)], T);
  assert.strictEqual(o.S.camMs, T - 3000);
  assert.strictEqual(o.age(T), 3);
  const x = visitor();                                                          // inconsistent ages: never younger than the tick
  x.hello({tick_age_s: 9.0, cam_age_s: 2.0}, [SOL(), POSES(635), CTICK(634)], T);
  assert.strictEqual(x.S.camMs, T - 9000);
});

test('I1 normal flow, a tick every 600 ms and an image every 8 ticks: age within one CAM period + 1 s, never under the image', () => {
  const v = visitor();
  v.hello({tick_age_s: 0, cam_age_s: 0}, [SOL(), POSES(1), CTICK(0)], T);
  let camAt = T, i = 1;
  for (let t = T + 100; t <= T + 600 * 200; t += 100) {
    while (T + 600 * i <= t) { const k = i; v.feed(k % 8 === 0 ? CTICK(k) : TICK(k), T + 600 * k); if (k % 8 === 0) camAt = T + 600 * k; i++; }
    const truth = (t - camAt) / 1000;
    assert.ok(v.age(t) >= Math.floor(truth), `age ${v.age(t)} under the image ${truth}`);
    assert.ok(v.age(t) <= 8 * 0.6 + 1, `age ${v.age(t)} at ${t - T}`);
    assert.strictEqual(v.label(t), 'LIVE');
  }
});

test('M4 a stream with no sol line at all: no exception, no image, the bare canvas says NO IMAGE YET, the sol is the tick\'s', () => {
  const v = visitor();
  v.hello({tick_age_s: 0.3, cam_age_s: 2.0}, [CTICK(8), TICK(10)], T);          // web.py kept no sol line (resume of the first sol)
  for (let t = 11; t <= 20; t++) v.feed(t === 16 ? CTICK(16) : TICK(t), T + 600 * (t - 10));
  assert.strictEqual(v.S.sol, 9);
  assert.strictEqual(v.S.cam, null);
  assert.strictEqual(v.S.camDims, null);
  assert.strictEqual(Live.noImageText(v.S, 'en'), 'no image yet');
  assert.strictEqual(Live.noImageText(v.S, 'fr'), "pas encore d'image");
  assert.strictEqual(v.age(T + 6000), 0);                                       // no image drawn: the age of the last tick
  let b;
  assert.doesNotThrow(() => { b = draw(v.S); });
  assert.ok(hasText(b, 8 + Math.floor((320 - Con.textWidth('NO IMAGE YET')) / 2), 24 + 100 + 9, 'NO IMAGE YET', Con.MARK));
  assert.ok(hasText(b, 160, 6, 'SOL 0009', Con.hud(10)));
  v.feed({e: 'phase', ph: 'learn'}, T + 7000);                                  // pause view over the bare canvas
  assert.doesNotThrow(() => draw(v.S));
  const line = Live.lineText(v.S, assets.i18n.en.line, assets.params);          // the text line of app.js (live-rc13: Live.lineText)
  assert.ok(!/null/.test(line) && /^SOL 9 /.test(line), line);
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'pages', 'live', 'app.js'), 'utf8');
  assert.ok(src.includes("$('line').textContent = Live.lineText(S, T().line, assets.params);"));
  const q0 = Live.newView();                                                    // no sol, no tick: `--`, never "null"
  assert.strictEqual(Live.lineText(q0, assets.i18n.en.line, assets.params), 'SOL -- · --:-- · -- · BATTERY --% · -- cm/s');
  const q = Live.newView();                                                     // a tick without any sol at all: still no "null"
  Live.applyEvent(q, Object.assign(CTICK(0), {s: undefined}), T);
  assert.strictEqual(q.sol, null);
  assert.doesNotThrow(() => draw(q));
  const c = new Uint8Array(640 * 360);
  Object.assign(q, {camDims: {w: 8, h: 6}});
  Con.renderConsole(c, q, {scanlines: true});
  assert.ok(hasText(c, 12, 28, '08:30', Con.MARK));
});

test('M4 the stage changes the CAM-1 size without a sol line: no image read with the wrong size, no exception', () => {
  const v = visitor();
  v.hello({tick_age_s: 0.1, cam_age_s: 0.1}, [SOL(8, {stage: 2, cam: {w: 32, h: 20, D: 1}}), POSES(1193, 8),
    CTICK(1192, {s: 8, cam: CAM(32, 20)}), TICK(1199, {s: 8})], T);
  assert.strictEqual(v.S.cam.data.length, 640);
  v.feed({e: 'restart'}, T + 1000);
  v.feed(CTICK(0, {s: 9, cam: CAM(80, 50)}), T + 2000);                         // stage 3: 80 x 50, no sol line before it
  assert.strictEqual(v.S.sol, 9);
  assert.strictEqual(v.S.cam, null);
  assert.strictEqual(v.S.camDims, null);                                        // the size proved the stage changed: stage unknown
  let b;
  assert.doesNotThrow(() => { b = draw(v.S); });
  assert.ok(hasText(b, 160, 6, 'SOL 0009', Con.hud(10)));
  for (let t = 1; t <= 9; t++) v.feed(t === 8 ? CTICK(8, {s: 9, cam: CAM(80, 50)}) : TICK(t), T + 2000 + 600 * t);
  assert.strictEqual(v.S.cam, null);
  assert.doesNotThrow(() => draw(v.S));
  v.feed(SOL(10, {stage: 3, cam: {w: 80, h: 50, D: 1}}), T + 900_000);         // the next sol line: everything known again
  v.feed(CTICK(0, {s: 10, cam: CAM(80, 50)}), T + 900_600);
  assert.strictEqual(v.S.cam.w * v.S.cam.h, 4000);
  assert.doesNotThrow(() => draw(v.S));
  const u = visitor();                                                          // bad base64 or an empty image: refused, no exception
  u.hello({}, [SOL()], T);
  assert.doesNotThrow(() => u.feed(TICK(0, {cam: '%%%'}), T + 1));
  assert.strictEqual(u.S.cam, null);
  assert.strictEqual(u.S.t, 0);
});

test('M3 a tick of another sol without its sol line: the sol number follows the tick, the old image is never drawn under it', () => {
  const v = visitor();
  v.hello({tick_age_s: 0.5, cam_age_s: 5.3}, [SOL(8), POSES(1200, 8), CTICK(1192, {s: 8}), TICK(1199, {s: 8}),
    {e: 'phase', ph: 'idle', next: SRV}], T);
  assert.strictEqual(v.S.sol, 8);
  assert.strictEqual(v.S.camT, 1192);
  v.feed({e: 'restart'}, T + 60_000);
  v.feed(TICK(19, {s: 9}), T + 70_000);                                         // resumed sol 9: no sol line was written
  assert.strictEqual(v.S.sol, 9);
  assert.strictEqual(v.S.cam, null);                                            // the image of sol 8 is gone
  assert.strictEqual(v.S.now, null);                                            // sol 8's start time is not sol 9's
  assert.strictEqual(v.S.w, null);
  assert.strictEqual(v.S.sunTimes, null);
  assert.strictEqual(v.S.camDims.w, 8);                                         // the camera size stays the last known one
  const b = draw(v.S);
  assert.ok(hasText(b, 8 + Math.floor((320 - Con.textWidth('NO IMAGE YET')) / 2), 24 + 100 + 9, 'NO IMAGE YET', Con.MARK));
  assert.strictEqual(v.age(T + 70_500), 1);
  v.feed(CTICK(24, {s: 9}), T + 73_000);                                        // same size: taken, with sol 9's number
  assert.strictEqual(v.S.camT, 24);
  assert.strictEqual(v.S.cam.data.length, 48);
  assert.doesNotThrow(() => draw(v.S));
});

test('M1 a cut of the visitor\'s link mid-episode, reconnected 5 s later: CONNECTING, never ENGINE SILENT, one change each way', () => {
  const v = visitor(), seen = [];
  v.hello({tick_age_s: 0.1, cam_age_s: 0.1}, [SOL(), POSES(101), CTICK(96), TICK(100)], T);
  let i = 101;
  const tCut = T + 10_000, tBack = tCut + 5_300;
  for (let t = T; t <= T + 30_000; t += 250) {
    if (t < tCut || t >= tBack + 300) while (T + 600 * (i - 100) <= t) { v.feed(i % 8 === 0 ? CTICK(i) : TICK(i), T + 600 * (i - 100)); i++; }
    if (t === tCut) v.link.onLost();                                            // app.js es.onerror
    if (t === tBack) { v.link.onOk(); }                                         // es.onopen of the new connection
    if (t === tBack + 250) {                                                    // its hello and snapshot
      const last = i - 1, lastCam = last - (last % 8);
      v.hello({tick_age_s: 0.2, cam_age_s: (t - (T + 600 * (lastCam - 100))) / 1000}, [SOL(), POSES(i), CTICK(lastCam), TICK(last)], t);
      while (T + 600 * (i - 100) <= t) i++;                                     // missed during the cut
    }
    const lab = v.label(t);
    assert.notStrictEqual(lab, 'ENGINE SILENT', `ENGINE SILENT at +${t - tCut} ms after the cut`);
    if (!seen.length || seen[seen.length - 1] !== lab) seen.push(lab);
  }
  assert.deepStrictEqual(seen, ['LIVE', 'CONNECTING', 'LIVE']);
  const o = Live.makeLink();                                                    // OFFLINE / SERVER BUSY are not hidden by a cut
  o.onNetworkError(); o.onNetworkError(); o.onNetworkError(); o.onLost();
  assert.strictEqual(o.state, 'OFFLINE');
  o.onHttp(503); o.onLost();
  assert.strictEqual(o.state, 'SERVER BUSY');
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'pages', 'live', 'app.js'), 'utf8');
  assert.ok(/es\.onerror = function \(\) \{ es\.close\(\); es = null; clearTimeout\(openTimer\); link\.onLost\(\); banner\(\); probe\(\); \};/.test(src));
});

test('M5 fresh restart then a fresh status `episode` before any fresh tick: RESUMING (FR REPRISE), panel RESUMING, not WAITING', () => {
  const v = visitor();
  v.hello({tick_age_s: 0.1, cam_age_s: 0.1}, [SOL(), POSES(601), CTICK(600)], T);
  const tr = T + 20_000;
  v.feed({e: 'restart'}, tr);
  v.feed({e: 'status', phase: 'idle', h: 'ok'}, tr + 5);
  assert.strictEqual(v.label(tr + 10), 'LIVE');                                 // status idle: not yet
  v.feed({e: 'phase', ph: 'idle', next: '2026-11-13T09:45:00Z'}, tr + 6);
  const wait = draw(v.S);
  assert.ok(hasText(wait, 160, 6, 'END OF SOL | WAITING', Con.hud(10)));
  v.feed({e: 'status', phase: 'episode', h: 'ok'}, tr + 60_000);
  assert.strictEqual(v.label(tr + 60_100), 'RESUMING');
  assert.strictEqual(Live.extraLabel('RESUMING', 'fr'), 'REPRISE');
  assert.strictEqual(Live.extraLabel('RESUMING', 'en'), 'RESUMING');
  assert.strictEqual(Live.resumeText(v.S, 'fr'), 'Le moteur a redémarré : il recalcule le sol en cours avant de reprendre la diffusion.');
  assert.strictEqual(Live.resumeText(v.S, 'en'), 'The engine restarted: it is recomputing the current sol before broadcasting again.');
  const b = draw(v.S);
  assert.ok(hasText(b, 160, 6, 'RESUMING', Con.hud(10)) && hasText(b, 340, 28, 'BRAIN | RESUMING', Con.hud(10)));
  assert.ok(!hasText(b, 160, 6, 'END OF SOL | WAITING', Con.hud(10)));
  assert.strictEqual(v.label(tr + 60_000 + 119_000), 'RESUMING');               // still bound by the 120 s rule
  assert.strictEqual(v.label(tr + 60_000 + 121_000), 'ENGINE SILENT');
  v.feed({e: 'ff', s: 9, from: 601, to: 700, why: 'restart'}, tr + 90_000);
  v.feed(TICK(701), tr + 90_000);                                               // the first fresh tick ends it
  assert.strictEqual(v.label(tr + 90_100), 'LIVE');
  assert.strictEqual(Live.resumeText(v.S, 'en'), null);
  v.feed(TICK(702), tr + 90_600);
  v.feed({e: 'status', phase: 'episode'}, tr + 90_700);                         // a status in a normal episode: not a resume
  assert.strictEqual(v.label(tr + 90_800), 'LIVE');
  // a visitor who did not see the restart (connected during the catch-up) gets no RESUMING: restart is never replayed
  const w = visitor();
  w.hello({engine_silent_s: 30, tick_age_s: 40, cam_age_s: 40, phase_age_s: 30}, [SOL(), POSES(601), CTICK(600),
    {e: 'phase', ph: 'idle', next: '2026-11-13T09:45:00Z'}], tr + 30_000);
  w.feed({e: 'status', phase: 'episode'}, tr + 60_000);
  assert.strictEqual(w.label(tr + 60_100), 'LIVE');
  // a reconnection (new hello) forgets a restart seen before the cut; a fresh phase line ends RESUMING; hold wins
  const x = visitor();
  x.hello({tick_age_s: 0.1}, [SOL(), POSES(601), TICK(600)], T);
  x.feed({e: 'restart'}, tr); x.feed({e: 'status', phase: 'episode'}, tr + 60_000);
  assert.strictEqual(x.label(tr + 60_001), 'RESUMING');
  x.feed({e: 'phase', ph: 'learn'}, tr + 61_000);
  assert.strictEqual(x.label(tr + 61_001), 'LEARNING');
  x.feed({e: 'restart'}, tr + 70_000); x.feed({e: 'status', phase: 'episode'}, tr + 71_000);
  x.hello({tick_age_s: 50}, [], tr + 72_000);
  x.feed({e: 'status', phase: 'episode'}, tr + 73_000);
  assert.notStrictEqual(x.label(tr + 73_001), 'RESUMING');
  x.feed({e: 'restart'}, tr + 80_000); x.feed({e: 'status', phase: 'episode'}, tr + 81_000);
  x.feed({e: 'phase', ph: 'hold', why: 'check'}, tr + 82_000);
  assert.strictEqual(x.label(tr + 82_001), 'ENGINE HOLD');
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'pages', 'live', 'app.js'), 'utf8');
  assert.ok(src.includes("(st === 'RESUMING' ? Live.resumeText(S, lang) : null)"));
});

test('data age = max(age of the last tick, age of the drawn image), never under either; no image: the tick\'s', () => {
  const v = visitor();
  v.hello({tick_age_s: 0.3, cam_age_s: 4.5}, [SOL(), POSES(8), CTICK(0), TICK(7)], T);
  assert.strictEqual(v.age(T), 5);                                              // ceil(4.5) > ceil(0.3)
  v.feed(TICK(8, {cam: CAM(8, 6)}), T + 100);
  assert.strictEqual(v.age(T + 100), 0);
  v.feed(TICK(9), T + 700);
  assert.strictEqual(v.age(T + 1700), 2);                                       // the image (T+100) is older than the tick (T+700)
  const w = visitor();
  w.hello({tick_age_s: 7.0, cam_age_s: 7.0}, [SOL(), POSES(8), CTICK(0)], T);
  assert.strictEqual(w.age(T), 7);
});
