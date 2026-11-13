'use strict';
// Page v2 (live-rc14): the REAL app.js in the VM (app_vm.js), driven like a visitor: enlarge / close a panel, keys, history, deep links,
// language switch without reload, tabs, waiting card before the first sol, EF-87 (DESIGN.md §4, §6, §12 T13-T17). Test streams only.
const test = require('node:test');
const assert = require('node:assert');
const {Con, fs, path, PAGE} = require('./helpers.js');
const {makePage, ageSeconds} = require('./app_vm.js');
const {tx, findText} = require('./page_helpers.js');

const T = 5_000_000;
const SRV = '2026-11-13T10:00:00Z';
const CAM = (w, h, v) => Buffer.alloc(w * h, v === undefined ? 3 : v).toString('base64');
const TICK = (t, extra) => Object.assign({e: 'tick', s: 9, t, hr: 8.5, m: 'DRIVE', p: [10, 20, 1, 0], tg: null, b: 0.5, v: 0.1, pi: 0, ro: 0,
  sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0], dr: 0, nd: 0}, extra || {});
const CTICK = (t, extra) => TICK(t, Object.assign({cam: CAM(8, 6, t % 24), z: new Array(40).fill(0)}, extra || {}));
const SOL = (s, extra) => Object.assign({e: 'sol', s: s === undefined ? 9 : s, stage: 3, stage_name: 'ENERGY', now: SRV, cam: {w: 8, h: 6, D: 1},
  tick_ms: 600, slot0: Date.parse('2026-11-13T09:45:00Z'), sun: {lever: 6, coucher: 18}, season_sols: 150}, extra || {});
const POSES = (n) => ({e: 'poses', s: 9, t: Array.from({length: n}, (_, i) => i), p: []});
const HELLO = (snap, h) => Object.assign({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: snap.length, tick_age_s: 0.1,
  cam_age_s: 0.1, phase_age_s: null}, h || {});

async function live(o, snap) {
  const p = await makePage(Object.assign({t0: T, keepBuffer: true}, o));
  p.open();
  const s = snap || [SOL(), POSES(101), CTICK(96), TICK(100)];
  p.send(HELLO(s));
  s.forEach((ev) => p.send(ev));
  p.advance(T + 1000);
  return p;
}
function feed(p, from, to, t0) { for (let i = from; i <= to; i++) p.send(i % 8 === 0 ? CTICK(i) : TICK(i), t0 + 600 * (i - from)); }

test('T13 enlarge: click -> one history entry #en/live/cam, the picture BEFORE showModal, live copies, Esc -> back -> closed, focus returned', async () => {
  const p = await live({lang: 'en'});
  const n0 = p.history.entries.length;
  p.click('hit-cam');
  p.advance(T + 1100);
  assert.strictEqual(p.location.hash, '#en/live/cam');
  assert.strictEqual(p.history.entries.length, n0 + 1);
  assert.deepStrictEqual(p.history.state, {ov: true});
  assert.strictEqual(p.el('ov').open, true);
  const open = p.dialogLog.find((d) => d.op === 'open'), firstOv = p.puts.find((x) => x.id === 'ov-c');
  assert.ok(firstOv && firstOv.n < open.n, 'the enlarged picture must be painted before the dialog opens');
  assert.deepStrictEqual(firstOv.args, [-7, -23, 7, 23, 322, 202]);         // the CAM-1 rectangle of the same rendering
  assert.strictEqual(p.el('ov-c').width, 322); assert.strictEqual(p.el('ov-c').height, 202);
  assert.strictEqual(p.el('ov-title').textContent, tx('en', 'n.panel.cam'));
  assert.ok(/^SOL 9 · 08:30 · .* · data age: \d+ s$/.test(p.el('ov-status').textContent) || p.el('ov-status').textContent === '', p.el('ov-status').textContent);
  // live: every draw copies the panel again (same rhythm as the console, <= 2 per second)
  const before = p.puts.filter((x) => x.id === 'ov-c').length;
  feed(p, 101, 120, T + 1200);
  p.advance(T + 1200 + 600 * 20);
  const ovPuts = p.puts.filter((x) => x.id === 'ov-c'), opened = open.t;
  assert.ok(ovPuts.length - before >= 10, `${ovPuts.length - before} copies`);
  // one copy per draw of the console (the limiter: <= 2 a second), none of its own
  const drawTimes = p.draws.filter((d) => d.t > opened).map((d) => d.t);
  assert.deepStrictEqual(ovPuts.filter((x) => x.t > opened).map((x) => x.t), drawTimes);
  for (let i = 1; i < drawTimes.length; i++) assert.ok(drawTimes[i] - drawTimes[i - 1] >= 500, 'more than 2 draws a second');
  assert.ok(/^SOL 9 · 08:30 · /.test(p.el('ov-status').textContent), p.el('ov-status').textContent);
  // Esc (the dialog's cancel event): history.back(), then the popstate closes it
  const ev = p.el('ov').dispatch('cancel');
  assert.ok(ev.defaultPrevented);
  p.advance(p.t + 400);
  assert.strictEqual(p.el('ov').open, false);
  assert.strictEqual(p.location.hash, '#en/live');
  assert.strictEqual(p.focused, 'hit-cam');
  assert.deepStrictEqual(p.errors, []);
});

test('T13 keys and buttons: → / ← change panel without a new history entry; close by the button; deep link closed by replaceState', async () => {
  const p = await live({lang: 'fr'});
  p.click('hit-brain'); p.advance(p.t + 100);
  assert.strictEqual(p.location.hash, '#fr/live/brain');
  const n = p.history.entries.length;
  p.key('ov', 'ArrowRight'); p.advance(p.t + 400);
  assert.strictEqual(p.location.hash, '#fr/live/map');
  p.click('ov-next'); p.advance(p.t + 400);
  assert.strictEqual(p.location.hash, '#fr/live/tel');
  p.key('ov', 'ArrowLeft'); p.advance(p.t + 400);
  assert.strictEqual(p.location.hash, '#fr/live/map');
  assert.strictEqual(p.history.entries.length, n);
  assert.strictEqual(p.el('ov-title').textContent, 'Carte locale');
  assert.strictEqual(p.el('ov-help').attrs.href, '#fr/about/console');
  p.click('ov-close'); p.advance(p.t + 400);
  assert.strictEqual(p.el('ov').open, false);
  assert.strictEqual(p.location.hash, '#fr/live');
  // deep link: opened once the console can be drawn; closing replaces the anchor (no entry to go back to)
  const q = await makePage({t0: T, lang: 'en', hash: '#en/live/brain', keepBuffer: true});
  assert.strictEqual(q.el('ov').open, false);                                      // nothing drawn yet: not opened on an empty frame
  q.open(); const s = [SOL(), POSES(101), CTICK(96), TICK(100)]; q.send(HELLO(s)); s.forEach((e) => q.send(e)); q.advance(T + 1000);
  assert.strictEqual(q.el('ov').open, true);
  assert.strictEqual(q.history.entries.length, 1);
  q.el('ov').dispatch('cancel'); q.advance(q.t + 400);
  assert.strictEqual(q.el('ov').open, false);
  assert.strictEqual(q.location.hash, '#en/live');
  assert.strictEqual(q.history.entries.length, 1);
  assert.deepStrictEqual([...p.errors, ...q.errors], []);
});

test('T13 before a console is drawn only CAM-1 can be enlarged; without <dialog> nothing opens and nothing breaks', async () => {
  const p = await makePage({t0: T, lang: 'en', keepBuffer: true});
  p.open(); p.send(HELLO([], {engine_silent_s: 1})); p.advance(T + 1000);
  assert.strictEqual(p.el('hit-brain').attrs['aria-disabled'], 'true');
  assert.strictEqual(p.el('hit-cam').attrs['aria-disabled'], undefined);
  p.click('hit-brain'); p.advance(p.t + 400);
  assert.strictEqual(p.el('ov').open, false);
  p.click('hit-cam'); p.advance(p.t + 400);
  assert.strictEqual(p.el('ov').open, true);
  const q = await live({lang: 'en', noDialog: true});
  q.click('hit-cam'); q.advance(q.t + 400);
  assert.strictEqual(q.el('ov').open, false);
  assert.ok(q.html.classList.contains('nodialog'));
  assert.deepStrictEqual([...p.errors, ...q.errors], []);
});

test('language switch: no reload, no new history entry, texts, attributes, title and canvas in the other language at once', async () => {
  const p = await live({lang: 'en'});
  const n = p.history.entries.length, nStreams = p.streams.length, d0 = p.draws.length;
  p.click('langlink'); p.advance(p.t + 10);
  assert.strictEqual(p.html.lang, 'fr');
  assert.strictEqual(p.location.hash, '#fr/live');
  assert.strictEqual(p.history.entries.length, n);
  assert.strictEqual(p.streams.length, nStreams, 'a new stream was opened (reload)');
  assert.strictEqual(p.el('state').textContent, 'EN DIRECT');
  assert.ok(p.el('line').textContent.startsWith('SOL 9 · 08:30 · '), p.el('line').textContent);
  assert.ok(ageSeconds(p.el('age').textContent), p.el('age').textContent);
  assert.ok(p.el('age').textContent.startsWith('âge de la donnée : '), p.el('age').textContent);
  assert.strictEqual(p.document.title, 'Sol-0 en direct : un rover simulé qui apprend seul');      // SEO lot A (secpage): d.title
  assert.strictEqual(p.el('c').attrs['aria-label'], tx('fr', 'd.canvas'));
  assert.strictEqual(p.el('hit-cam').attrs['aria-label'], 'Agrandir : Caméra CAM-1');
  assert.strictEqual(p.el('langlink').attrs.href, '#en/live');
  p.advance(p.t + 600);
  assert.ok(p.draws.length > d0 && p.lastDraw.lang === 'fr');
  assert.ok(findText(p.buffer, 'TÉLÉMÉTRIE', Con.hud(10), [136, 232, 384, 352]), 'the canvas is not French');
  assert.ok(!p.errors.includes('location.reload called'));
  assert.deepStrictEqual(p.errors, []);
});

test('tabs: How it works without redrawing the hidden console, back to Live with a draw at once; deep link to a section', async () => {
  const p = await live({lang: 'fr'});
  p.navigate('#fr/about'); p.advance(p.t + 400);
  assert.strictEqual(p.html.dataset.tab, 'about');
  assert.strictEqual(p.el('tab-about').attrs['aria-current'], 'page');
  assert.strictEqual(p.document.title, 'Comment ça marche · Sol-0');
  const d0 = p.draws.length;
  feed(p, 101, 110, p.t + 100); p.advance(p.t + 7000);
  assert.strictEqual(p.draws.length, d0, 'the hidden console was drawn');
  assert.ok(p.el('line').textContent.startsWith('SOL 9 · '), 'the status bar stops');   // the bar keeps living on the explainer tab
  p.navigate('#fr/live/cam'); p.advance(p.t + 600);
  assert.strictEqual(p.html.dataset.tab, 'live');
  assert.ok(p.draws.length > d0, 'no draw on the way back');
  assert.strictEqual(p.el('ov').open, true);
  p.navigate('#fr/about/brain'); p.advance(p.t + 600);
  assert.strictEqual(p.el('ov').open, false);
  assert.strictEqual(p.focused, 'fr-brain');
  p.back(); p.advance(p.t + 600);                                                  // back: the enlarged panel again (wanted)
  assert.strictEqual(p.el('ov').open, true);
  assert.deepStrictEqual(p.errors, []);
});

test('T14 EF-87: 20 clicks in 1 s (language, panel) apply at most 3 switches a second; <= 2 draws a second over 60 s with a panel open', async () => {
  const p = await live({lang: 'en'});
  const langs = [];
  p.html.lang = p.html.lang;                                                       // watch html.lang
  let last = p.html.lang;
  const t0 = p.t + 1000;
  for (let i = 0; i < 20; i++) {
    p.advance(t0 + 50 * i); p.click('langlink');
    if (p.html.lang !== last) { langs.push(p.t); last = p.html.lang; }
  }
  for (let t = t0 + 1000; t <= t0 + 3000; t += 50) { p.advance(t); if (p.html.lang !== last) { langs.push(p.t); last = p.html.lang; } }
  assert.ok(langs.filter((t) => t < t0 + 1000).length <= 3, JSON.stringify(langs.map((t) => t - t0)));
  for (let i = 1; i < langs.length; i++) assert.ok(langs[i] - langs[i - 1] >= 350);
  const q = await live({lang: 'en'});
  const opens = [];
  for (let i = 0; i < 20; i++) { q.advance(q.t + 50); q.click(i % 2 ? 'ov-close' : 'hit-cam'); }
  q.advance(q.t + 2000);
  q.dialogLog.forEach((d) => opens.push(d.t));
  for (let i = 1; i < opens.length; i++) assert.ok(opens[i] - opens[i - 1] >= 350, JSON.stringify(q.dialogLog));
  const r = await live({lang: 'en'});
  r.click('hit-cam'); r.advance(r.t + 100);
  const start = r.t, n0 = r.draws.length;
  feed(r, 101, 200, start);
  r.advance(start + 60_000);
  const ds = r.draws.slice(n0);
  for (let i = 1; i < ds.length; i++) assert.ok(ds[i].t - ds[i - 1].t >= 500);
  assert.ok(ds.length <= 121 && ds.length >= 50, `${ds.length} draws`);
  const css = fs.readFileSync(path.join(PAGE, 'live.css'), 'utf8');
  assert.ok(!/@keyframes/.test(css) && !/scroll-behavior\s*:\s*smooth/.test(css));
  for (const m of css.matchAll(/\b(transition|animation)\s*:\s*([^;}]+)/g)) assert.strictEqual(m[2].trim(), 'none', m[0]);
  assert.ok(/#ov::backdrop \{ background: rgba\(18, 12, 10, 0\.92\); \}/.test(css));
  assert.deepStrictEqual([...p.errors, ...q.errors, ...r.errors], []);
});

test('T15 / T16 no reload anywhere; the ids the bench reads are kept; #line starts with SOL; #age parsed in FR and EN', async () => {
  const src = fs.readFileSync(path.join(PAGE, 'app.js'), 'utf8');
  assert.ok(!/location\.reload|location\.href\s*=|location\.assign|location\.replace/.test(src));
  const html = fs.readFileSync(path.join(PAGE, 'index.html'), 'utf8');
  for (const id of ['state', 'line', 'age', 'next', 'season', 'silentmsg', 'summary', 'c', 'off', 'offimg', 'offnote', 'legend', 'langlink']) assert.ok(html.includes(`id="${id}"`), id);
  assert.ok(!/\sstyle=|<style|\son[a-z]+=/i.test(html));
  for (const lang of ['en', 'fr']) {
    const p = await live({lang});
    p.advance(p.t + 2000);
    assert.ok(/^SOL 9 /.test(p.el('line').textContent));
    const a = ageSeconds(p.el('age').textContent);
    assert.ok(a && a.s >= 0, p.el('age').textContent);
    assert.ok(p.el('stagebar').textContent === (lang === 'fr' ? 'STADE 3 · ÉNERGIE' : 'STAGE 3 · ENERGY'), p.el('stagebar').textContent);
    // VERIF-rc14 I3 (live-rc15): sol 9 of year 1 is « SOL 9/600 », the number of the bar (was 10/600)
    assert.ok(p.el('season').textContent === (lang === 'fr' ? 'ANNÉE 1 · SOL 9/600 · DURÉE DU JOUR 12,0 h' : 'YEAR 1 · SOL 9/600 · DAYLIGHT 12.0 h'), p.el('season').textContent);
    assert.deepStrictEqual(p.errors, []);
  }
});

test('T17 before the very first sol: the waiting card says when the next sol starts; #next counts down every second; no draw of any sol', async () => {
  for (const lang of ['en', 'fr']) {
    const p = await makePage({t0: T, lang, keepBuffer: true});
    p.open(); p.send(HELLO([], {engine_silent_s: 2}));
    const next = new Date(Date.parse(SRV) + 240_000).toISOString().replace('.000', '');
    p.send({e: 'phase', ph: 'idle', next}, T + 10);
    p.advance(T + 600);
    assert.strictEqual(p.draws.length, 0);
    const w = p.waits[p.waits.length - 1];
    assert.ok(w && w.key === 'idle', JSON.stringify(p.waits));
    assert.ok(findText(p.buffer, tx(lang, 'c.wait.next', {hh: '10', mm: '04', ss: '00'}), Con.MARK, [8, 24, 328, 224]));
    const seen = [];
    for (let t = T + 1000; t <= T + 10_000; t += 1000) { p.advance(t); seen.push(p.el('next').textContent); }
    // live-rc16: « 10:04:00 UTC » then the visitor's time (or nothing more in a UTC zone), whatever the zone of the machine running the test
    assert.ok(seen.every((s) => new RegExp('^' + (lang === 'fr' ? 'SOL SUIVANT' : 'NEXT SOL') + ' 10:04:00 UTC(?: · \\d\\d:\\d\\d:\\d\\d (?:chez vous|your time))? \\(').test(s)), JSON.stringify(seen));
    assert.strictEqual(new Set(seen).size, seen.length, 'the countdown is frozen');
    const nWaits = p.waits.length;
    p.advance(T + 20_000);
    assert.strictEqual(p.waits.length, nWaits, 'the waiting card is redrawn although nothing changed');
    assert.strictEqual(p.el('line').textContent, '');
    assert.deepStrictEqual(p.errors, []);
  }
});

test('M13 offline: the published GIF without the live lines; the live lines come back with the stream', async () => {
  const p = await live({lang: 'fr'});
  p.nowStatus = 'network';
  p.error(p.t + 100);                                   // the probe fails, then the new streams never open: OFFLINE after 3 failures
  const t0 = p.t;
  for (let t = t0; t <= t0 + 120_000 && !p.html.classList.contains('offline'); t += 1000) p.advance(t);
  assert.strictEqual(p.el('off').hidden, false);
  assert.ok(p.html.classList.contains('offline'));
  assert.strictEqual(p.el('line').hidden, true); assert.strictEqual(p.el('age').hidden, true);
  assert.ok(/^Serveur hors ligne\. Dernier sol publié : /.test(p.el('offnote').textContent), p.el('offnote').textContent);
  assert.strictEqual(p.el('state').textContent, 'HORS LIGNE');
  const s = [SOL(), POSES(301), CTICK(296), TICK(300)];                             // the stream is back
  p.open(); p.send(HELLO(s)); s.forEach((e) => p.send(e)); p.advance(p.t + 1500);
  assert.strictEqual(p.el('off').hidden, true); assert.strictEqual(p.el('line').hidden, false);
  assert.ok(!p.html.classList.contains('offline'));
  assert.deepStrictEqual(p.errors, []);
});
