'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs'), path = require('path');
const {Con, Live, events, PAGE, ROOT} = require('./helpers.js');

function fakeClock() {
  const c = {t: 0, timers: []};
  c.now = () => c.t;
  c.setTimer = (f, ms) => { const h = {f, at: c.t + ms, live: true}; c.timers.push(h); return h; };
  c.advance = (to) => {   // run due timers in order up to `to`
    for (;;) {
      const due = c.timers.filter((h) => h.live && h.at <= to).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      due.live = false; c.t = due.at; due.f();
    }
    c.t = to;
  };
  return c;
}

test('nominal stream of 60 s (a tick every 600 ms): draws = ticks +- 1', () => {
  const c = fakeClock(); let draws = 0;
  const L = Live.makeLimiter({now: c.now, setTimer: c.setTimer, draw: () => { draws++; }});
  let ticks = 0;
  for (let t = 0; t < 60000; t += 600) { c.advance(t); ticks++; L.request(); }
  c.advance(61000);
  assert.ok(Math.abs(draws - ticks) <= 1, `draws ${draws} ticks ${ticks}`);
});

test('100 events in 1 s: at most 2 draws, then the latest state is drawn', () => {
  const c = fakeClock(); const drawn = []; let cur = 0;
  const L = Live.makeLimiter({now: c.now, setTimer: c.setTimer, draw: () => { drawn.push([c.t, cur]); }});
  for (let i = 0; i < 100; i++) { c.advance(i * 10); cur = i; L.request(); }
  c.advance(999);
  assert.ok(drawn.length <= 2, JSON.stringify(drawn));
  c.advance(5000);
  const gaps = drawn.slice(1).map((d, i) => d[0] - drawn[i][0]);
  assert.ok(gaps.every((g) => g >= 500), 'two draws closer than 500 ms: ' + gaps);
  assert.strictEqual(drawn[drawn.length - 1][1], 99, 'the last state must be the one drawn');
});

test('a burst of 1000 events over 10 s never exceeds 2 draws in any 1 s window', () => {
  const c = fakeClock(); const at = [];
  const L = Live.makeLimiter({now: c.now, setTimer: c.setTimer, draw: () => at.push(c.t)});
  for (let i = 0; i < 1000; i++) { c.advance(i * 10); L.request(); }
  c.advance(12000);
  for (let i = 0; i + 2 < at.length; i++) assert.ok(at[i + 2] - at[i] >= 1000 - 0, `3 draws within ${at[i + 2] - at[i]} ms`);
});

test('OFFLINE only after 3 consecutive network failures; success resets; 503/429 give SERVER BUSY, never OFFLINE', () => {
  const L = Live.makeLink();
  assert.strictEqual(L.state, 'CONNECTING');
  L.onNetworkError(); L.onNetworkError();
  assert.notStrictEqual(L.state, 'OFFLINE');
  L.onHttp(200);
  L.onNetworkError(); L.onNetworkError();
  assert.notStrictEqual(L.state, 'OFFLINE', 'a success must reset the count');
  L.onNetworkError();
  assert.strictEqual(L.state, 'OFFLINE');
  const B = Live.makeLink();
  for (let i = 0; i < 10; i++) { B.onHttp(i % 2 ? 503 : 429); assert.strictEqual(B.state, 'SERVER BUSY'); }
  assert.strictEqual(B.failures, 0);
  B.onNetworkError(); B.onNetworkError();
  assert.notStrictEqual(B.state, 'OFFLINE');
});

test('states follow the stream: LIVE on ticks, LEARNING during the learning phases, ENGINE SILENT after 5 s without tick', () => {
  const S = Live.newView(), L = Live.makeLink(), ev = events(2);
  for (const e of ev.slice(0, 5)) { Live.applyEvent(S, e, 1000); L.onEvent(S, e); }
  assert.strictEqual(L.state, 'LIVE');
  assert.strictEqual(Live.label(L, S, 2000), 'LIVE');
  assert.strictEqual(Live.label(L, S, 7000), 'ENGINE SILENT');
  const ph = {e: 'phase', ph: 'learn', utc: '2026-11-11T07:30:00Z', next: '2026-11-11T07:45:00Z'};
  Live.applyEvent(S, ph, 8000); L.onEvent(S, ph);
  assert.strictEqual(L.state, 'LEARNING');
  const ph2 = {e: 'phase', ph: 'idle', next: '2026-11-11T07:45:00Z'};
  Live.applyEvent(S, ph2, 9000); L.onEvent(S, ph2);
  assert.strictEqual(L.state, 'LIVE');
});

// FORMAT test only: no real `learn` flux exists yet (L0a/L0c not built); these events are written by hand and are never displayed.
test('learning pause and waiting view (format test with hand-written events)', () => {
  const S = Live.newView(), buf = new Uint8Array(640 * 360), ev = events(3);
  for (const e of ev.slice(0, 40)) Live.applyEvent(S, e, 0);
  const t = S.t;
  [{e: 'phase', ph: 'learn', utc: 'x', next: '2026-11-11T07:45:00Z'},
   {e: 'learn', mod: 'm3', gen: 1, of: 12, best: 1.5, mean: 0.5, val: null},
   {e: 'learn', mod: 'm3', gen: 2, of: 12, best: 2.5, mean: 0.9, val: null},
   {e: 'learn', mod: 'battery', gen: 17, of: 20, best: null, mean: null, val: {successes: 17}},
   {e: 'phase', ph: 'render'}, {e: 'phase', ph: 'save'}].forEach((e) => Live.applyEvent(S, e, 0));
  assert.strictEqual(S.learn.mod, 'battery');
  assert.strictEqual(Live.valText('battery', S.learnVals.battery), 'TEST COURSES 17 PASSED');
  Live.renderLive(buf, S, null);
  const a = Buffer.from(buf);
  Live.applyEvent(S, {e: 'phase', ph: 'idle', next: '2026-11-11T07:45:00Z'}, 0);
  Live.applyEvent(S, {e: 'sol_end', attempts: 1, stage: 3, progress: {fraction: 0.4, text: '40%', blocking: null}, distance_m: 120, targets: 3}, 0);
  Live.renderLive(buf, S, null);
  assert.notDeepStrictEqual(a, Buffer.from(buf));
  assert.strictEqual(S.t, t);                      // the last tick is kept (LAST FRAME T<t>)
});

test('no animation or interpolation: the view model only changes by events', () => {
  const S = Live.newView(); const before = JSON.stringify(S.pose);
  Live.renderLive(new Uint8Array(640 * 360), Object.assign(S, {cam: {w: 8, h: 6, data: new Uint8Array(48)}, stageName: 'X', now: '2026-01-01T00:00:00Z'}), null);
  assert.strictEqual(JSON.stringify(S.pose), before);
});

test('Python-compatible number formatting (half-even ties, signs)', () => {
  assert.strictEqual(Con.fix(0.125, 2), '0.12'); assert.strictEqual(Con.fix(0.375, 2), '0.38');
  assert.strictEqual(Con.fix(-0.001, 2, true), '-0.00'); assert.strictEqual(Con.fix(0.5, 2, true), '+0.50');
  assert.strictEqual(Con.fix(2.675, 2), '2.67'); assert.strictEqual(Con.fix(12.3456, 1), '12.3');
});

test('page weight (page v2 budgets, DESIGN.md §9.4), no third-party script, no URL outside the configuration, no cookie/storage', () => {
  // live-rc13: one 200 KB cap for the whole folder; page v2: JS + CSS <= 150 KB, JSON <= 40 KB, HTML sources (index.html + the two
  // explainer fragments) <= 250 KB; the explainer images are checked by tools/live/build_page.py (tests/live/test_assets.py)
  const sizes = {code: 0, json: 0, html: 0};
  const files = [];
  // media/: the intro cinematic (binary MP4 and PNG, own budget checked by build_page.py, tests/page/intro.test.js)
  (function walk(d) { for (const f of fs.readdirSync(d)) { const p = path.join(d, f); if (fs.statSync(p).isDirectory()) { if (f !== 'img' && f !== 'media') walk(p); } else files.push(p); } })(PAGE);
  for (const p of files) {
    if (p.endsWith('.md')) continue;                 // about/SOURCES.md: notes for the maintainers, never copied into the page
    const txt = fs.readFileSync(p, 'utf8'), f = path.relative(PAGE, p);
    sizes[p.endsWith('.html') ? 'html' : (p.endsWith('.json') ? 'json' : 'code')] += Buffer.byteLength(txt);
    assert.ok(!/https?:\/\//i.test(txt.replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/, '')), `URL in ${f}`);
    // consigne 52: one exception, the intro's « seen » flag (intro.js, key sol0.intro.seen, read and written in try/catch)
    const t2 = f === 'intro.js' ? txt.replace(/root\.localStorage\.(getItem|setItem)\(KEY/g, '') : txt;
    assert.ok(!/document\.cookie|localStorage|sessionStorage|XMLHttpRequest|\beval\(|new Function/.test(t2), `forbidden API in ${f}`);
    assert.ok(!/<script[^>]+src="(https?:)?\/\//i.test(txt), `third-party script in ${f}`);
  }
  assert.ok(sizes.code <= 150 * 1024 && sizes.json <= 40 * 1024 && sizes.html <= 250 * 1024, JSON.stringify(sizes));
});

test('REPLAY banner when the sol event says replay; season line computed from the sol event', () => {
  const S = Live.newView(); const L = Live.makeLink();
  L.onOk();
  Live.applyEvent(S, {e: 'sol', s: 412, stage: 0, stage_name: 'x', now: '2026-01-01T00:00:00Z', tick_ms: 600, cam: {w: 8, h: 3, D: 24}, w: '', replay: true, season_sols: 150, sun: {lever: 7.2, coucher: 16.8}}, 0);
  L.state = 'LIVE';
  assert.strictEqual(Live.label(L, S, 0), 'REPLAY');
  assert.strictEqual(Live.seasonText(S, 'YEAR {y} · DAY {d}/{n} · DAYLIGHT {h} h'), 'YEAR 1 · DAY 413/600 · DAYLIGHT 9.6 h');
  Live.applyEvent(S, {e: 'sol', s: 1300, stage: 0, stage_name: 'x', now: '2026-01-01T00:00:00Z', tick_ms: 600, cam: {w: 8, h: 3, D: 24}, w: '', season_sols: 150}, 0);
  assert.strictEqual(Live.label(L, S, 0), 'LIVE');
  assert.strictEqual(Live.seasonText(S, 't'), null);
});
