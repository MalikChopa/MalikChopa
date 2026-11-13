'use strict';
// The intro cinematic on the first visit (consignes 51 and 52, out/cinematique/web/README.md): the REAL route.js, app.js and intro.js
// in the VM (app_vm.js, `intro: true`), driven like a visitor; the page as build_page.py writes it. Test streams and fake storage only.
const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const {fs, path, PAGE, ROOT} = require('./helpers.js');
const {makePage, makeStorage} = require('./app_vm.js');
const {I18N} = require('./page_helpers.js');
const Intro = require(path.join(PAGE, 'intro.js'));
const Route = require(path.join(PAGE, 'route.js'));

const T = 5_000_000;
const SRV = '2026-11-13T10:00:00Z';
const KEY = 'sol0.intro.seen';
const CAM = (w, h, v) => Buffer.alloc(w * h, v === undefined ? 3 : v).toString('base64');
const TICK = (t, extra) => Object.assign({e: 'tick', s: 9, t, hr: 8.5, m: 'DRIVE', p: [10, 20, 1, 0], tg: null, b: 0.5, v: 0.1, pi: 0, ro: 0,
  sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0], dr: 0, nd: 0}, extra || {});
const CTICK = (t) => TICK(t, {cam: CAM(8, 6, t % 24), z: new Array(40).fill(0)});
const SOL = () => ({e: 'sol', s: 9, stage: 3, stage_name: 'ENERGY', now: SRV, cam: {w: 8, h: 6, D: 1}, tick_ms: 600,
  slot0: Date.parse('2026-11-13T09:45:00Z'), sun: {lever: 6, coucher: 18}, season_sols: 150});
const HELLO = (n) => ({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: n, tick_age_s: 0.1, cam_age_s: 0.1, phase_age_s: null});
// what RENDER delivered (out/cinematique/web/README.md, consigne 52): the file whose EF-87 was measured on its decoded frames
const MP4_SHA = '372da3352db04413c3de83890b9c5dd666ea6f39b3eed7fd8067200f8db6944d';
const POSTER_SHA = '7ed75f159a3bd026955ab2ad5b247ca15f7c627d5a6b81bff1479342a46b2b40';

const page = (o) => makePage(Object.assign({t0: T, lang: 'en', intro: true}, o || {}));
const plays = (p) => p.videoLog.filter((x) => x.op === 'play');
const vsrc = (p) => p.el('intro-v').getAttribute('src');
function feed(p, from, n, t0) { for (let i = 0; i < n; i++) p.send(i % 4 === 0 ? CTICK(from + i) : TICK(from + i), t0 + 600 * i); }
function startStream(p) { p.open(); p.send(HELLO(2)); p.send(SOL()); p.send(CTICK(100)); }
// EF-87 as the project counts it (src/rover/render/photosens.py): at most 3 switches in any window (t - 1000, t]
function worstPerSecond(times) { let w = 0; times.forEach((ti) => { w = Math.max(w, times.filter((x) => ti - 1000 < x && x <= ti).length); }); return w; }
function tmpdir(tag) { return fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'intro-' + tag + '-')); }
function build(src, out) {
  try {
    return {ok: true, out: execFileSync('python3', [path.join(ROOT, 'tools', 'live', 'build_page.py'), '--repo', 'MalikChopa/MalikChopa',
      '--stream', 'https://live.sol0.fr', '--birth-utc', '2026-11-13T12:11:21Z', '--out', out].concat(src ? ['--src', src] : []),
    {env: {PATH: process.env.PATH, HOME: tmpdir('home')}, stdio: 'pipe'}).toString()};
  } catch (e) { return {ok: false, err: String(e.stderr)}; }
}
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

test('decide() and isDeepLink(): first visit only on the live view, never under reduced motion or Save-Data; #intro always opens', () => {
  const base = {supported: true, deep: false, seen: false, reduced: false, saveData: false, tab: 'live', sub: null};
  const d = (x) => Intro.decide(Object.assign({}, base, x));
  assert.strictEqual(d({}), 'play');
  assert.strictEqual(d({seen: true}), 'none');
  assert.strictEqual(d({reduced: true}), 'none');
  assert.strictEqual(d({saveData: true}), 'none');
  assert.strictEqual(d({tab: 'about'}), 'none');
  assert.strictEqual(d({sub: 'cam'}), 'none');
  assert.strictEqual(d({deep: true, seen: true}), 'play');
  assert.strictEqual(d({deep: true, reduced: true}), 'open');
  assert.strictEqual(d({supported: false}), 'none');
  assert.strictEqual(d({supported: false, deep: true}), 'none');
  for (const h of ['#intro', 'intro', '#INTRO', '#fr/intro', '#en/intro']) assert.ok(Intro.isDeepLink(h), h);
  // « intro » is also a section of « How it works » (#en/about/intro): never the cinematic
  for (const h of ['', '#', '#en/about/intro', '#fr/live/intro', '#intro/x', '#de/intro', '#en/live', null, undefined]) assert.ok(!Intro.isDeepLink(h), String(h));
  assert.strictEqual(Route.parse('#en/about/intro').sub, 'intro');
  assert.strictEqual(Intro.SRC, 'media/intro.mp4');
  assert.strictEqual(Intro.POSTER, 'media/intro-poster.png');
});

test('first visit: the intro opens at once over the live, muted; the video is requested after the stream; flag at « playing »; closes at the end, never loops', async () => {
  for (const lang of ['en', 'fr']) {
    const st = makeStorage();
    const p = await page({lang, storage: st});
    const v = p.el('intro-v');
    assert.strictEqual(p.el('intro').open, true);
    assert.deepStrictEqual(p.introLog.map((x) => [x.t, x.op]), [[T, 'open']]);
    assert.strictEqual(v.getAttribute('poster'), 'media/intro-poster.png');
    assert.strictEqual(p.focused, 'intro-skip', 'focus on « Skip » at the opening');
    assert.strictEqual(p.el('intro-label').hidden, false, 'ILLUSTRATION label visible during the playback');
    assert.strictEqual(p.el('introbtn').hidden, false, 'header button « Watch the intro »');
    const pl = plays(p);
    assert.strictEqual(pl.length, 1);
    assert.deepStrictEqual([pl[0].src, pl[0].muted, pl[0].t], ['media/intro.mp4', true, T]);
    assert.ok(p.es.n < pl[0].n, 'the stream is opened before the video is requested');
    assert.strictEqual(p.html.lang, lang);
    p.advance(T + 10);                                         // « playing »
    assert.deepStrictEqual(st.data, {[KEY]: '1'});
    startStream(p);
    feed(p, 101, 10, T + 100);
    assert.strictEqual(p.el('intro').open, true);
    v.paused = true; p.video('ended');
    p.advance(p.t + 400);
    assert.strictEqual(p.el('intro').open, false);
    assert.strictEqual(vsrc(p), null, 'the source is removed (download stopped)');
    assert.ok(p.videoLog.some((x) => x.op === 'load' && x.src === null));
    assert.strictEqual(p.focused, 'introbtn', 'focus back to « Watch the intro »');
    p.advance(p.t + 600_000);
    assert.strictEqual(plays(p).length, 1, 'never loops');
    assert.strictEqual(p.introLog.length, 2);
    assert.deepStrictEqual(p.errors, []);
  }
});

test('second visit: nothing opens, nothing is loaded; « Watch the intro » plays it (muted), Skip gives the focus back', async () => {
  const st = makeStorage({[KEY]: '1'});
  const p = await page({storage: st});
  startStream(p); p.advance(T + 1000);
  assert.strictEqual(p.el('intro').open, false);
  assert.deepStrictEqual(p.introLog, []);
  assert.strictEqual(plays(p).length, 0);
  assert.strictEqual(vsrc(p), null);
  assert.strictEqual(p.el('intro-v').getAttribute('poster'), null, 'not even the poster is requested');
  assert.strictEqual(p.el('introbtn').hidden, false);
  p.click('introbtn');
  assert.strictEqual(p.el('intro').open, true);
  assert.deepStrictEqual(plays(p).map((x) => [x.src, x.muted]), [['media/intro.mp4', true]]);
  assert.strictEqual(p.focused, 'intro-skip');
  p.advance(p.t + 500);
  p.click('intro-skip');
  p.advance(p.t + 400);
  assert.strictEqual(p.el('intro').open, false);
  assert.strictEqual(p.el('intro-v').paused, true);
  assert.strictEqual(vsrc(p), null);
  assert.strictEqual(p.focused, 'introbtn');
  p.click('introbtn'); p.advance(p.t + 400);                  // again: from the start (a fresh source)
  assert.strictEqual(plays(p).length, 2);
  assert.strictEqual(plays(p)[1].src, 'media/intro.mp4');
  assert.deepStrictEqual(p.errors, []);
});

test('no storage (absent, getter throws, methods throw): shown once per page load at most, never again in that load, no error', async () => {
  for (const storage of [undefined, 'throw', 'broken']) {
    for (let load = 0; load < 2; load++) {                    // every load of the page: at most once
      const p = await page({storage});
      assert.strictEqual(p.el('intro').open, true, String(storage));
      p.advance(T + 10);                                       // « playing »: the flag cannot be written, silently
      p.click('intro-skip'); p.advance(T + 400);
      assert.strictEqual(p.el('intro').open, false);
      startStream(p); feed(p, 101, 20, T + 1000);
      p.advance(T + 600_000);
      assert.strictEqual(p.introLog.filter((x) => x.op === 'open').length, 1, String(storage));
      assert.strictEqual(plays(p).length, 1);
      assert.deepStrictEqual(p.errors, [], String(storage));
    }
  }
});

test('prefers-reduced-motion: no autoplay, the button only (a click plays it); #intro opens on the poster and waits for « Play the intro »', async () => {
  const st = makeStorage();
  const p = await page({storage: st, reducedMotion: true});
  p.advance(T + 1000);
  assert.strictEqual(p.el('intro').open, false);
  assert.strictEqual(plays(p).length, 0);
  assert.deepStrictEqual(st.data, {});
  assert.strictEqual(p.el('introbtn').hidden, false);
  p.click('introbtn');
  assert.strictEqual(p.el('intro').open, true);
  assert.strictEqual(plays(p).length, 1, 'a click is an explicit choice');
  const q = await page({storage: makeStorage(), reducedMotion: true, hash: '#intro'});
  assert.strictEqual(q.el('intro').open, true);
  q.advance(T + 5000);
  assert.strictEqual(plays(q).length, 0, 'no autoplay under reduced motion, even from a link');
  assert.strictEqual(q.el('intro-play').hidden, false);
  assert.strictEqual(q.focused, 'intro-play');
  q.click('intro-play');
  assert.strictEqual(plays(q).length, 1);
  assert.strictEqual(q.el('intro-play').hidden, true);
  assert.deepStrictEqual([...p.errors, ...q.errors], []);
});

test('Save-Data: no autoplay at the first visit (2.8 MB), the button and #intro still work', async () => {
  const p = await page({storage: makeStorage(), saveData: true});
  p.advance(T + 1000);
  assert.strictEqual(p.el('intro').open, false);
  assert.strictEqual(plays(p).length, 0);
  p.click('introbtn');
  assert.strictEqual(plays(p).length, 1);
  const q = await page({storage: makeStorage(), saveData: true, hash: '#intro'});
  assert.strictEqual(q.el('intro').open, true);
  assert.strictEqual(plays(q).length, 1);
});

test('Skip: the button, Esc and a click outside the film close it and remember it; a click on the film or its label does not', async () => {
  const closers = {
    skip: (p) => p.click('intro-skip'),
    esc: (p) => { const e = p.el('intro').dispatch('cancel'); assert.strictEqual(e.defaultPrevented, true, 'Esc goes through the guard'); },
    backdrop: (p) => p.click('intro'),                                         // a click on ::backdrop targets the dialog
    box: (p) => p.el('intro').dispatch('click', {target: p.el('intro-box')})  // the empty area around the film
  };
  for (const [name, fn] of Object.entries(closers)) {
    const st = makeStorage();
    const p = await page({storage: st, autoplay: 'pending'});                 // never « playing »: only the close writes the flag
    p.advance(T + 500);
    for (const id of ['intro-v', 'intro-label', 'intro-title']) p.el('intro').dispatch('click', {target: p.el(id)});
    p.advance(T + 1000);
    assert.strictEqual(p.el('intro').open, true, name + ': a click on the film keeps it');
    assert.deepStrictEqual(st.data, {}, name);
    fn(p);
    p.advance(T + 1500);
    assert.strictEqual(p.el('intro').open, false, name);
    assert.deepStrictEqual(st.data, {[KEY]: '1'}, name);
    assert.ok(p.videoLog.some((x) => x.op === 'pause'), name);
    assert.strictEqual(vsrc(p), null, name);
    assert.strictEqual(p.focused, 'introbtn', name);
    assert.deepStrictEqual(p.errors, [], name);
  }
  // closed by the browser itself (a second Esc): the page follows, the flag is written, nothing is left playing
  const st = makeStorage();
  const p = await page({storage: st, autoplay: 'pending'});
  p.advance(T + 100);
  p.el('intro').open = false; p.el('intro').dispatch('close');
  assert.strictEqual(vsrc(p), null);
  assert.deepStrictEqual(st.data, {[KEY]: '1'});
  p.click('introbtn'); p.advance(T + 300);
  assert.strictEqual(p.el('intro').open, false, 'the browser\'s close counts as a switch for the EF-87 guard');
  p.advance(T + 450);
  assert.strictEqual(p.el('intro').open, true, 'it can be watched again');
  assert.strictEqual(p.introLog[p.introLog.length - 1].t, T + 450);
});

test('sound: muted at the start; « Sound on » / « Sound off »; a later « Watch the intro » keeps the choice of the session', async () => {
  const p = await page({storage: makeStorage()});
  const v = p.el('intro-v');
  assert.strictEqual(v.muted, true);
  assert.deepStrictEqual([p.el('intro-snd-on').hidden, p.el('intro-snd-off').hidden], [false, true]);
  p.click('intro-snd');
  assert.strictEqual(v.muted, false);
  assert.deepStrictEqual([p.el('intro-snd-on').hidden, p.el('intro-snd-off').hidden], [true, false]);
  p.click('intro-snd');
  assert.strictEqual(v.muted, true);
  p.click('intro-snd');
  p.advance(T + 400); p.click('intro-skip'); p.advance(T + 800);
  p.click('introbtn'); p.advance(T + 1200);
  assert.deepStrictEqual(plays(p).map((x) => x.muted), [true, false], 'muted at the first play, sound after the visitor chose it');
  // the sound never starts by itself: every play of a page that was never clicked is muted
  const q = await page({storage: makeStorage(), hash: '#intro'});
  assert.ok(plays(q).every((x) => x.muted));
  assert.deepStrictEqual([...p.errors, ...q.errors], []);
});

test('deep link: #intro and #fr/intro open it even after a visit; #en/about/intro and a panel link do not; a link followed on the page opens it again', async () => {
  const seen = () => makeStorage({[KEY]: '1'});
  const a = await page({storage: seen(), hash: '#intro'});
  assert.strictEqual(a.el('intro').open, true);
  assert.strictEqual(plays(a).length, 1);
  assert.strictEqual(a.location.hash, '#en/live', 'app.js writes the canonical anchor');
  const b = await page({storage: seen(), hash: '#fr/intro', lang: 'en'});
  assert.strictEqual(b.el('intro').open, true);
  assert.strictEqual(b.html.lang, 'fr');
  const c = await page({storage: makeStorage(), hash: '#en/about/intro'});
  assert.strictEqual(c.el('intro').open, false, 'a first visit on « How it works » is left alone');
  const d = await page({storage: makeStorage(), hash: '#en/live/cam'});
  assert.strictEqual(d.el('intro').open, false, 'a first visit on an enlarged panel is left alone');
  const e = await page({storage: seen()});
  startStream(e); e.advance(T + 1000);
  e.navigate('#intro'); e.advance(e.t + 400);
  assert.strictEqual(e.el('intro').open, true);
  assert.strictEqual(e.location.hash, '#en/live', 'the anchor gives way at once');
  e.click('intro-skip'); e.advance(e.t + 400);
  e.navigate('#intro'); e.advance(e.t + 400);
  assert.strictEqual(e.el('intro').open, true, 'following the link again opens it again');
  assert.strictEqual(plays(e).length, 2);
  assert.deepStrictEqual([...a.errors, ...b.errors, ...c.errors, ...d.errors, ...e.errors], []);
});

test('the stream is never delayed: same opening time and same draws as a page without the intro, the console keeps drawing underneath', async () => {
  const runs = {};
  for (const intro of [false, true]) {
    const p = await makePage({t0: T, lang: 'en', intro, storage: makeStorage()});
    const esAt = p.es.t;
    startStream(p);
    feed(p, 101, 40, T + 200);
    p.advance(T + 30_000);
    runs[intro] = {p, esAt, url: p.es.url, draws: p.draws.map((d) => d.t), puts: p.puts.filter((x) => x.id === 'c').length};
  }
  assert.strictEqual(runs.true.esAt, runs.false.esAt);
  assert.strictEqual(runs.true.url, runs.false.url);
  assert.deepStrictEqual(runs.true.draws, runs.false.draws, 'the same draws at the same times');
  assert.ok(runs.true.draws.length >= 20 && runs.true.puts === runs.false.puts);
  const p = runs.true.p;
  assert.ok(p.introLog[0].t === T && p.draws.filter((d) => d.t > T && d.t < T + 30_000).length >= 20, 'drawn while the intro is open');
  assert.strictEqual(p.el('intro').open, true);
  assert.ok(p.streams.length === 1 && !p.es.closed);
  // app.js: the stream first, then the signal to the intro; intro.js never touches the network but its own video
  const app = fs.readFileSync(path.join(PAGE, 'app.js'), 'utf8'), src = fs.readFileSync(path.join(PAGE, 'intro.js'), 'utf8');
  assert.ok(app.indexOf('connect();\n    // the stream is requested first') > 0 && app.indexOf('Sol0Intro.streamStarted()') > app.indexOf('connect();\n    // the stream'));
  assert.ok(!/fetch\(|EventSource|XMLHttpRequest|Sol0Live|\bawait\b/.test(src));
  assert.deepStrictEqual(p.errors, []);
});

test('the page cannot read its files: the intro still starts its video, at most WAIT_STREAM_MS later, and nothing throws', async () => {
  const p = await page({storage: makeStorage(), failFiles: true});
  assert.strictEqual(p.el('intro').open, true);
  assert.strictEqual(plays(p).length, 0);
  p.advance(T + Intro.WAIT_STREAM_MS - 1);
  assert.strictEqual(plays(p).length, 0);
  p.advance(T + Intro.WAIT_STREAM_MS);
  assert.strictEqual(plays(p).length, 1);
  assert.deepStrictEqual(p.errors, []);
});

test('autoplay refused: the poster and « Play the intro » (focused), no retry loop; the click plays it', async () => {
  const st = makeStorage();
  const p = await page({storage: st, autoplay: 'refuse'});
  assert.strictEqual(plays(p).length, 1);
  assert.strictEqual(p.el('intro-play').hidden, false);
  assert.strictEqual(p.focused, 'intro-play');
  p.advance(T + 600_000);
  assert.strictEqual(plays(p).length, 1, 'no retry');
  assert.strictEqual(p.el('intro').open, true);
  assert.deepStrictEqual(st.data, {});
  p.autoplay = 'ok';
  p.click('intro-play');
  assert.strictEqual(plays(p).length, 2);
  assert.strictEqual(p.el('intro-play').hidden, true);
  p.advance(p.t + 10);
  assert.deepStrictEqual(st.data, {[KEY]: '1'});
  // a refusal that arrives after the intro was closed and opened again never shows the old button
  const q = await page({storage: makeStorage({[KEY]: '1'}), autoplay: 'pending'});
  q.click('introbtn'); q.advance(T + 400); q.click('intro-skip'); q.advance(T + 800); q.click('introbtn'); q.advance(T + 1200);
  assert.strictEqual(q.el('intro').open, true);
  assert.strictEqual(q.pendingPlays.length, 2);
  q.pendingPlays[0].r(new Error('AbortError'));               // the first play, aborted by the close
  assert.strictEqual(q.el('intro-play').hidden, true);
  q.pendingPlays[1].r(new Error('NotAllowedError'));          // the current one
  assert.strictEqual(q.el('intro-play').hidden, false);
  assert.deepStrictEqual([...p.errors, ...q.errors], []);
});

test('a video error closes it without remembering it (next load tries again); no error escapes', async () => {
  const st = makeStorage();
  const p = await page({storage: st, autoplay: 'pending'});
  p.advance(T + 500);
  p.video('error');
  p.advance(T + 1000);
  assert.strictEqual(p.el('intro').open, false);
  assert.deepStrictEqual(st.data, {});
  p.video('error');                                           // after the close (source removed): ignored
  assert.deepStrictEqual(p.errors, []);
});

test('EF-87: open / close at most one switch per 350 ms (<= 3 in any second), also mixed with the enlarged panel (one guard for the page)', async () => {
  const p = await page({storage: makeStorage({[KEY]: '1'})});
  startStream(p); p.advance(T + 1000);
  const t0 = p.t;
  for (let i = 0; i < 20; i++) { p.advance(t0 + 50 * i); p.click(i % 2 ? 'intro-skip' : 'introbtn'); }
  p.advance(t0 + 3000);
  const ts = p.introLog.map((x) => x.t);
  assert.ok(ts.length >= 2, JSON.stringify(p.introLog));
  for (let i = 1; i < ts.length; i++) assert.ok(ts[i] - ts[i - 1] >= 350, JSON.stringify(ts.map((t) => t - t0)));
  assert.ok(worstPerSecond(ts) <= 3);
  // intro and enlarged panel together: a close of the intro then a click on a panel, repeated
  const q = await page({storage: makeStorage({[KEY]: '1'})});
  startStream(q); feed(q, 101, 8, T + 100); q.advance(T + 6000);
  const s0 = q.t;
  for (let i = 0; i < 12; i++) {
    q.advance(s0 + 100 * i);
    q.click(['introbtn', 'intro-skip', 'hit-cam', 'ov-close'][i % 4]);
  }
  q.advance(s0 + 5000);
  const all = [...q.introLog, ...q.dialogLog].map((x) => x.t).sort((a, b) => a - b);
  assert.ok(q.introLog.length >= 1 && q.dialogLog.length >= 1, JSON.stringify({i: q.introLog, d: q.dialogLog}));
  for (let i = 1; i < all.length; i++) assert.ok(all[i] - all[i - 1] >= 350, JSON.stringify(all.map((t) => t - s0)));
  assert.ok(worstPerSecond(all) <= 3);
  // no fade, no flash: the backdrop is the page's own dark colour; the film sits on black; no transition or animation
  const css = fs.readFileSync(path.join(PAGE, 'live.css'), 'utf8');
  assert.ok(css.includes('#intro::backdrop { background: rgba(18, 12, 10, 0.96); }'));
  const block = css.slice(css.indexOf('/* the intro cinematic'), css.indexOf("/* « How it works » tab")).replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(block.length > 200 && !/transition|animation|#fff|:\s*white|opacity/i.test(block));
  assert.deepStrictEqual([...p.errors, ...q.errors], []);
});

test('a panel deep link waits under the intro and opens at the next draw after it (never two dialogs at once)', async () => {
  // brain: enlargeable only once a console is drawn (CAM-1 opens at once on the waiting card, before anyone can click)
  const p = await page({storage: makeStorage({[KEY]: '1'}), hash: '#en/live/brain'});
  assert.strictEqual(p.el('ov').open, false);
  p.click('introbtn');
  assert.strictEqual(p.el('intro').open, true);
  startStream(p); feed(p, 101, 6, T + 100); p.advance(T + 4000);
  assert.strictEqual(p.el('ov').open, false, 'the panel waits');
  p.click('intro-skip'); p.advance(p.t + 400);
  assert.strictEqual(p.el('intro').open, false);
  feed(p, 107, 3, p.t + 100); p.advance(p.t + 2500);
  assert.strictEqual(p.el('ov').open, true, 'then it opens');
  assert.ok(p.introLog[p.introLog.length - 1].t <= p.dialogLog[0].t);
  assert.deepStrictEqual(p.errors, []);
});

test('no <dialog> or no H.264: no intro, no button, and the live page runs as before', async () => {
  for (const o of [{canPlay: false}, {introNoDialog: true}]) {
    const p = await page(Object.assign({storage: makeStorage(), hash: '#intro'}, o));
    startStream(p); p.advance(T + 2000);
    assert.strictEqual(p.el('intro').open, false);
    assert.strictEqual(p.el('introbtn').hidden, true);
    assert.strictEqual(plays(p).length, 0);
    assert.ok(p.draws.length >= 1);
    assert.strictEqual(p.ctx.Sol0Intro.isOpen(), false);
    assert.deepStrictEqual(p.errors, []);
  }
});

test('markup: a labelled modal dialog, the ILLUSTRATION label, real buttons in both languages, a video without autoplay / loop / controls', () => {
  const html = fs.readFileSync(path.join(PAGE, 'index.html'), 'utf8');
  assert.ok(html.includes('<dialog id="intro" aria-labelledby="intro-title" aria-describedby="intro-label">'));
  assert.ok(html.includes('<h2 id="intro-title" class="sr">{{t:n.intro.title}}</h2>'));
  assert.ok(html.includes('<p id="intro-label">{{t:n.intro.label}}</p>'));
  const video = /<video [^>]*>/.exec(html)[0];
  assert.strictEqual(video, '<video id="intro-v" width="640" height="360" muted playsinline preload="none" aria-labelledby="intro-title">');
  assert.ok(!/autoplay|loop|controls|src=/.test(video));
  for (const id of ['introbtn', 'intro-play', 'intro-snd', 'intro-skip']) assert.ok(new RegExp(`<button id="${id}" type="button"`).test(html), id);
  assert.ok(/<span class="tools"><button id="introbtn" type="button" hidden>/.test(html), 'the button is in the header, hidden until intro.js runs');
  assert.ok(html.indexOf('<script src="app.js"></script>\n<script src="intro.js"></script>') > 0, 'intro.js after app.js');
  assert.strictEqual(I18N['n.intro.label'].en, 'ILLUSTRATION: a drawn trailer, not footage from the simulation.');
  assert.strictEqual(I18N['n.intro.label'].fr, 'ILLUSTRATION : bande-annonce dessinée, pas une image de la simulation.');
  const words = {'n.intro.watch': ['Revoir la cinématique', 'Watch the intro'], 'n.intro.soundon': ['Activer le son', 'Sound on'],
    'n.intro.soundoff': ['Couper le son', 'Sound off'], 'n.intro.skip': ['Passer', 'Skip'], 'n.intro.play': ['Lancer la cinématique', 'Play the intro']};
  for (const [id, [fr, en]] of Object.entries(words)) assert.deepStrictEqual([I18N[id].fr, I18N[id].en], [fr, en], id);
  // no spoiler: the intro texts say nothing of stages, skills or results
  for (const id of Object.keys(I18N).filter((k) => k.startsWith('n.intro.'))) assert.ok(!/stage|stade|learn|appren|drill|forage|scan/i.test(I18N[id].en + I18N[id].fr), id);
});

test('build: media/ copied byte for byte (the measured files), CSP media-src \'self\' only, texts FR + EN; bad media refused', () => {
  const src = fs.readFileSync(path.join(PAGE, 'media', 'intro.mp4')), poster = fs.readFileSync(path.join(PAGE, 'media', 'intro-poster.png'));
  assert.strictEqual(sha(src), MP4_SHA);
  assert.strictEqual(sha(poster), POSTER_SHA);
  assert.ok(src.length <= 3 * 1024 * 1024 && poster.length <= 150 * 1024);
  const out = path.join(tmpdir('build'), 'page');
  const r = build(null, out);
  assert.ok(r.ok, r.err);
  const res = JSON.parse(r.out);
  assert.ok(res.files.includes('media/intro.mp4') && res.files.includes('media/intro-poster.png') && res.files.includes('intro.js'));
  assert.strictEqual(res.sizes.media, src.length + poster.length);
  assert.ok(res.sizes.code <= 150 * 1024, 'JS + CSS ' + res.sizes.code);
  assert.strictEqual(sha(fs.readFileSync(path.join(out, 'media', 'intro.mp4'))), MP4_SHA);
  assert.strictEqual(sha(fs.readFileSync(path.join(out, 'media', 'intro-poster.png'))), POSTER_SHA);
  const html = fs.readFileSync(path.join(out, 'index.html'), 'utf8');
  const metas = [...html.matchAll(/<meta http-equiv="Content-Security-Policy" content="([^"]*)">/g)].map((m) => m[1]);
  assert.strictEqual((metas.join(' ').match(/media-src/g) || []).length, 1);
  assert.ok(metas[0].includes("; media-src 'self'; ") && !/media-src[^;]*(https?:|\*|data:|blob:)/.test(metas[0]));
  for (const id of ['n.intro.watch', 'n.intro.skip', 'n.intro.soundon', 'n.intro.label']) {
    assert.ok(html.includes(`<span class="l-fr" lang="fr">${I18N[id].fr}</span><span class="l-en" lang="en">${I18N[id].en}</span>`), id);
  }
  // refusals: moov after mdat (no faststart), an MP4 over 4 MB, a PNG that is not one, a media file named by the page but missing
  const box = (t, body) => { const b = Buffer.alloc(8 + body.length); b.writeUInt32BE(8 + body.length, 0); b.write(t, 4, 'latin1'); body.copy(b, 8); return b; };
  const cases = {
    late_moov: (d) => fs.writeFileSync(path.join(d, 'media', 'intro.mp4'), Buffer.concat([box('ftyp', Buffer.alloc(8)), box('mdat', Buffer.alloc(64)), box('moov', Buffer.alloc(16))])),
    no_ftyp: (d) => fs.writeFileSync(path.join(d, 'media', 'intro.mp4'), Buffer.concat([box('moov', Buffer.alloc(16)), box('mdat', Buffer.alloc(64))])),
    cut_box: (d) => fs.writeFileSync(path.join(d, 'media', 'intro.mp4'), Buffer.concat([box('ftyp', Buffer.alloc(8)), box('moov', Buffer.alloc(16)), box('mdat', Buffer.alloc(64)).subarray(0, 40)])),
    too_big: (d) => fs.writeFileSync(path.join(d, 'media', 'intro.mp4'), Buffer.concat([box('ftyp', Buffer.alloc(8)), box('moov', Buffer.alloc(16)), box('mdat', Buffer.alloc(4 * 1024 * 1024))])),
    not_png: (d) => fs.writeFileSync(path.join(d, 'media', 'intro-poster.png'), Buffer.from('GIF89a')),
    missing: (d) => fs.unlinkSync(path.join(d, 'media', 'intro-poster.png'))};
  for (const [name, spoil] of Object.entries(cases)) {
    const d = path.join(tmpdir('bad'), 'live');
    fs.cpSync(PAGE, d, {recursive: true});
    spoil(d);
    const b = build(d, path.join(tmpdir('bout'), 'p'));
    assert.ok(!b.ok && /media\//.test(b.err), name + ': ' + (b.err || b.out));
  }
  // the copy of the real files with a 64-bit mdat size passes (the box parser follows the largesize)
  assert.strictEqual(src.readUInt32BE(28 + src.readUInt32BE(28)), 1, 'intro.mp4 mdat uses a 64-bit size');
});
