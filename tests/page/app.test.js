'use strict';
// The REAL app.js (DOM glue) driven like a browser would (tests/page/app_vm.js: fake DOM, clock, timers, fetch, EventSource).
// RC12-verif (live-rc12 audit, brief 45 role FIX4):
//   I1  a `status` must redraw the canvas: RESUMING on the image, not only in the banner;
//   I2  between a `sol` line and its first tick, the canvas and the text lines must not stay on the previous sol (image, age, line).
const test = require('node:test');
const assert = require('node:assert');
const {Con, assets} = require('./helpers.js');
const {makePage, ageSeconds} = require('./app_vm.js');

const T = 5_000_000;
const SRV = '2026-11-13T10:00:00Z';
const CAM = (w, h, v) => Buffer.alloc(w * h, v === undefined ? 3 : v).toString('base64');
const TICK = (t, extra) => Object.assign({e: 'tick', s: 9, t, hr: 8.5, m: 'DRIVE', p: [10, 20, 1, 0], tg: null, b: 0.5, v: 0.1, pi: 0, ro: 0,
  sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0], dr: 0, nd: 0}, extra || {});
const CTICK = (t, extra) => TICK(t, Object.assign({cam: CAM(8, 6, t % 24), z: new Array(40).fill(0)}, extra || {}));
const SOL = (s, extra) => Object.assign({e: 'sol', s: s === undefined ? 9 : s, stage: 0, stage_name: 'WAKE', now: SRV, cam: {w: 8, h: 6, D: 1},
  tick_ms: 600, slot0: 0, sun: {lever: 6, coucher: 18}, season_sols: 150}, extra || {});
const POSES = (n, s) => ({e: 'poses', s: s === undefined ? 9 : s, t: Array.from({length: n}, (_, i) => i), p: []});
const HELLO = (snap, h) => Object.assign({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: snap.length, tick_age_s: null,
  cam_age_s: null, phase_age_s: null}, h || {});

function hasText(buf, x, y, s, color) {
  const c = new Uint8Array(640 * 360);
  Con.text(c, x, y, s, color, 1);
  let set = 0, same = 0;
  for (let i = 0; i < c.length; i++) if (c[i]) { set++; if (buf[i] === c[i]) same++; }
  return set > 0 && same === set;
}
const NO_IMG = [8 + Math.floor((320 - Con.textWidth('NO IMAGE YET')) / 2), 24 + 100 + 9, 'NO IMAGE YET', Con.MARK];
async function connected(lang, snap, h, t) {
  const p = await makePage({t0: t || T, lang, keepBuffer: true});
  p.open();
  p.send(HELLO(snap, h));
  snap.forEach((ev) => p.send(ev));
  return p;
}

test('app.js I1: a fresh status `episode` after a fresh restart redraws the canvas: RESUMING on the image (EN and FR banners)', async () => {
  for (const lang of ['en', 'fr']) {
    const p = await connected(lang, [SOL(), POSES(601), CTICK(600)], {tick_age_s: 0.1, cam_age_s: 0.1});
    p.advance(T + 1000);
    assert.deepStrictEqual(p.errors, []);
    assert.strictEqual(p.lastDraw.camT, 600);
    const tr = T + 20_000;
    p.send({e: 'restart', code_version: 'x'}, tr);
    p.send({e: 'status', phase: 'idle', h: 'ok', utc: SRV}, tr + 5);
    p.send({e: 'phase', ph: 'idle', next: '2026-11-13T09:45:00Z', utc: SRV}, tr + 6);
    p.advance(tr + 1000);
    assert.ok(hasText(p.buffer, 160, 6, 'END OF SOL | WAITING', Con.hud(10)));
    const ts = tr + 60_000;
    p.send({e: 'status', phase: 'episode', h: 'ok', utc: SRV}, ts);             // the only line of the catch-up (one a minute)
    p.advance(ts + 500);
    assert.ok(p.lastDraw.t >= ts && p.lastDraw.t <= ts + 500, `last draw at +${p.lastDraw.t - ts} ms`);
    assert.strictEqual(p.lastDraw.title, 'RESUMING');
    assert.ok(hasText(p.buffer, 160, 6, 'RESUMING', Con.hud(10)) && hasText(p.buffer, 340, 28, 'BRAIN | RESUMING', Con.hud(10)));
    assert.ok(!hasText(p.buffer, 160, 6, 'END OF SOL | WAITING', Con.hud(10)));
    assert.ok(hasText(p.buffer, 12, 213, 'LAST FRAME T600', Con.MARK));
    assert.strictEqual(p.el('state').dataset.state, 'RESUMING');
    assert.strictEqual(p.el('state').textContent, lang === 'fr' ? 'REPRISE' : 'RESUMING');
    assert.strictEqual(p.el('silentmsg').hidden, false);
    assert.strictEqual(p.el('silentmsg').textContent, lang === 'fr'
      ? 'Le moteur a redémarré : il recalcule le sol en cours avant de reprendre la diffusion.'
      : 'The engine restarted: it is recomputing the current sol before broadcasting again.');
    for (let t = ts + 500; t <= ts + 30_000; t += 250) {                        // the whole catch-up: image and banner agree
      p.advance(t);
      assert.strictEqual(p.lastDraw.title, 'RESUMING');
      assert.strictEqual(p.el('state').dataset.state, 'RESUMING');
    }
    p.send({e: 'ff', s: 9, from: 601, to: 700, why: 'restart'}, ts + 30_000);
    p.send(TICK(701), ts + 30_000);                                             // the first fresh tick ends it, on the image too
    p.advance(ts + 30_500);
    assert.strictEqual(p.lastDraw.title, null);
    assert.ok(!hasText(p.buffer, 160, 6, 'RESUMING', Con.hud(10)));
    p.advance(ts + 31_100);
    assert.strictEqual(p.el('state').dataset.state, 'LIVE');
    assert.deepStrictEqual(p.errors, []);
  }
});

test('app.js I1: RESUMING with no phase line since the restart is still drawn on the image (pause view over the last tick)', async () => {
  const p = await connected('en', [SOL(), POSES(601), CTICK(600)], {tick_age_s: 0.1, cam_age_s: 0.1});
  p.advance(T + 1000);
  p.send({e: 'restart'}, T + 20_000);
  p.send({e: 'status', phase: 'episode'}, T + 20_100);
  p.advance(T + 20_600);
  assert.strictEqual(p.S.phase, null);
  assert.ok(hasText(p.buffer, 160, 6, 'RESUMING', Con.hud(10)) && hasText(p.buffer, 340, 28, 'BRAIN | RESUMING', Con.hud(10)));
  assert.deepStrictEqual(p.errors, []);
});

test('app.js I2: a late sol start (sol line, then `ff` computed without broadcast): bare view and live text at once, never sol 8', async () => {
  for (const lang of ['en', 'fr']) {
    const snap = [SOL(8), POSES(1200, 8), CTICK(1192, {s: 8}), TICK(1199, {s: 8}), {e: 'phase', ph: 'learn'}, {e: 'sol_end', s: 8, stage: 0},
      {e: 'phase', ph: 'idle', next: '2026-11-13T10:15:00Z'}];
    const p = await connected(lang, snap, {engine_silent_s: 30, tick_age_s: 400, cam_age_s: 404, phase_age_s: 30});
    p.advance(T + 1000);
    assert.ok(hasText(p.buffer, 12, 213, 'LAST FRAME T1192', Con.MARK));
    assert.ok(hasText(p.buffer, 160, 6, 'END OF SOL | WAITING', Con.hud(10)));
    p.send({e: 'status', phase: 'idle', h: 'ok'}, T + 30_000);
    const ts = T + 31_000;                                                      // the sol line of sol 9, 250 s late
    p.send(SOL(9), ts);
    p.send({e: 'ff', s: 9, from: 0, to: 427, why: 'late'}, ts);                 // written at the first broadcast tick, here early
    p.advance(ts + 500);
    assert.strictEqual(p.lastDraw.sol, 9);
    assert.strictEqual(p.lastDraw.camT, null);
    assert.strictEqual(p.lastDraw.bare, true);
    assert.ok(hasText(p.buffer, 160, 6, 'SOL 0009', Con.hud(10)));
    assert.ok(hasText(p.buffer, ...NO_IMG));
    assert.ok(!hasText(p.buffer, 12, 213, 'LAST FRAME T1192', Con.MARK), 'the image of sol 8 is still drawn under sol 9');
    assert.ok(!hasText(p.buffer, 160, 6, 'END OF SOL | WAITING', Con.hud(10)));
    const tpl = assets.i18n[lang].line, noimg = lang === 'fr' ? "pas encore d'image" : 'no image yet';
    const want = tpl.replace('{s}', 9).replace('{hh}', '--').replace('{mm}', '--').replace('{mode}', '--').replace('{b}', '--').replace('{v}', '--');
    for (let t = ts + 1000; t <= ts + 25_000; t += 250) {                       // the whole window: nothing frozen
      p.advance(t);
      assert.strictEqual(p.el('line').textContent, want);
      assert.ok(p.el('age').writtenAt >= t - 1000, `age text written ${t - p.el('age').writtenAt} ms ago`);
      const a = ageSeconds(p.el('age').textContent);
      assert.ok(a && a.s >= Math.floor((t - ts) / 1000) && a.s <= Math.ceil((t - ts) / 1000) + 1, `${p.el('age').textContent} at +${t - ts}`);
      assert.ok(p.el('age').textContent.endsWith(' · ' + noimg), p.el('age').textContent);
      assert.strictEqual(p.el('state').dataset.state, 'LIVE');
    }
    assert.ok(!/null|undefined|NaN/.test(p.el('line').textContent + p.el('age').textContent + p.el('season').textContent));
    p.send(TICK(428), ts + 25_700);                                             // the first broadcast tick (no image: 428 % 8 = 4)
    p.advance(ts + 26_200);
    assert.strictEqual(p.lastDraw.bare, false);
    assert.ok(hasText(p.buffer, ...NO_IMG));
    for (let t = 429; t <= 432; t++) p.send(t === 432 ? CTICK(432) : TICK(t), ts + 25_700 + 600 * (t - 428));
    p.advance(ts + 25_700 + 600 * 4 + 500);
    assert.strictEqual(p.lastDraw.camT, 432);
    p.advance(ts + 25_700 + 600 * 4 + 1500);
    assert.ok(/^SOL 9 · 08:30 · DRIVE · /.test(p.el('line').textContent), p.el('line').textContent);
    assert.ok(!p.el('age').textContent.includes(noimg));
    assert.deepStrictEqual(p.errors, []);
  }
});

test('app.js: a visitor arriving during the snapshot never sees the bare view flash; a snapshot with a sol line only shows it', async () => {
  const p = await connected('en', [SOL(), POSES(101), CTICK(96), TICK(100)], {tick_age_s: 0.2, cam_age_s: 2.6});
  p.advance(T + 2000);
  assert.ok(p.draws.length >= 1 && p.draws.every((d) => !d.bare && d.camT === 96), JSON.stringify(p.draws));
  const q = await connected('en', [SOL()], {engine_silent_s: 1});              // ff in progress: the sol is known, no tick yet
  assert.strictEqual(q.lastDraw && q.lastDraw.bare, true);
  q.advance(T + 1000);
  assert.ok(hasText(q.buffer, 160, 6, 'SOL 0009', Con.hud(10)) && hasText(q.buffer, ...NO_IMG));
  assert.ok(q.el('line').textContent.startsWith('SOL 9 · --:--'), q.el('line').textContent);
  const r = await connected('en', [], {engine_silent_s: 1});                    // nothing known: nothing drawn, no text line
  r.advance(T + 3000);
  assert.strictEqual(r.draws.length, 0);
  assert.strictEqual(r.el('line').textContent, '');
  assert.deepStrictEqual([...p.errors, ...q.errors, ...r.errors], []);
});

test('app.js: the normal sol rollover shows the bare view at most one draw period (500 ms), at most 2 draws a second (EF-87)', async () => {
  const p = await connected('en', [SOL(8), POSES(1200, 8), CTICK(1192, {s: 8}), TICK(1199, {s: 8}), {e: 'phase', ph: 'idle', next: SRV}],
    {tick_age_s: 100, cam_age_s: 104, phase_age_s: 20});
  p.advance(T + 10_000);
  const ts = T + 10_000, n0 = p.draws.length;
  p.send(SOL(9), ts);
  p.send(CTICK(0), ts + 50);                                                    // tick 0 right after the sol line
  for (let k = 1; k <= 5; k++) p.send(TICK(k), ts + 50 + 600 * k);
  p.advance(ts + 4000);
  const ds = p.draws.slice(n0);
  const bare = ds.filter((d) => d.bare);
  assert.ok(bare.length <= 1, JSON.stringify(ds));
  const firstFull = ds.find((d) => !d.bare);
  assert.ok(firstFull && firstFull.t - ts <= 550 && firstFull.camT === 0, JSON.stringify(ds));
  for (let i = 1; i < ds.length; i++) assert.ok(ds[i].t - ds[i - 1].t >= 500, JSON.stringify(ds));      // the limiter: 2 draws a second at most
  assert.deepStrictEqual(p.errors, []);
});

test('app.js: a cut of the visitor\'s link: CONNECTING at once, reconnection by app.js itself, never ENGINE SILENT', async () => {
  const p = await connected('fr', [SOL(), POSES(101), CTICK(96), TICK(100)], {tick_age_s: 0.1, cam_age_s: 2.5});
  let i = 101;
  const tCut = T + 10_000;
  for (let t = T; t < tCut; t += 600) { p.send(i % 8 === 0 ? CTICK(i) : TICK(i), t); i++; }
  p.error(tCut);
  assert.strictEqual(p.el('state').dataset.state, 'CONNECTING');
  assert.strictEqual(p.el('state').textContent, 'CONNEXION');
  const before = p.streams.length;
  for (let t = tCut; t <= tCut + 30_000; t += 250) {
    p.advance(t);
    assert.notStrictEqual(p.el('state').dataset.state, 'ENGINE SILENT', `+${t - tCut} ms`);
    if (p.streams.length > before && !p.reopened) {                              // app.js opened a new stream (5 s after the probe)
      p.reopened = t;
      p.open();
      const last = i + 8, cam = last - (last % 8);
      const snap = [SOL(), POSES(last + 1), CTICK(cam), TICK(last)];
      p.send(HELLO(snap, {tick_age_s: 0.2, cam_age_s: 0.2 + 0.6 * (last - cam)}));
      snap.forEach((ev) => p.send(ev));
      i = last + 1;
    } else if (p.reopened) { p.send(i % 8 === 0 ? CTICK(i) : TICK(i)); i++; }
  }
  assert.ok(p.reopened && p.reopened - tCut >= 5000 && p.reopened - tCut <= 5250, String(p.reopened - tCut));
  assert.strictEqual(p.el('state').dataset.state, 'LIVE');
  assert.deepStrictEqual(p.errors, []);
});
