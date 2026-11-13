'use strict';
// Security batch 1, page side (consigne 50, out/security/SECURITE-SITE.md): SEC-04 display, SEC-14, SEC-15, SEC-17, SEC-29, SEC-30,
// and lot A of out/seo/SEO-PLAN.md (head, robots, sitemap, icons, noscript, no-JS view). Test streams and fake data only.
const test = require('node:test');
const assert = require('node:assert');
const {execFileSync} = require('node:child_process');
const os = require('node:os');
const {Live, fs, path, PAGE, ROOT} = require('./helpers.js');
const {makePage, CONFIG} = require('./app_vm.js');
const {I18N, tx} = require('./page_helpers.js');

const BUILD = path.join(ROOT, 'tools', 'live', 'build_page.py');
const ICONS = path.join(ROOT, 'tools', 'live', 'make_icons.py');
const T = 5_000_000;
const SRV = '2026-11-13T10:00:00Z';
const STATE_SRC = 'https://raw.githubusercontent.com/MalikChopa/MalikChopa/state/';
const TICK = (t, extra) => Object.assign({e: 'tick', s: 9, t, hr: 8.5, m: 'DRIVE', p: [10, 20, 1, 0], tg: null, b: 0.5, v: 0.1, pi: 0, ro: 0,
  sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0], dr: 0, nd: 0}, extra || {});
const SOL = () => ({e: 'sol', s: 9, stage: 3, stage_name: 'ENERGY', now: SRV, cam: {w: 8, h: 6, D: 1}, tick_ms: 600,
  slot0: Date.parse('2026-11-13T09:45:00Z'), sun: {lever: 6, coucher: 18}, season_sols: 150});
const HELLO = (n) => ({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: n, tick_age_s: 0.1, cam_age_s: 0.1, phase_age_s: null});

function tmpdir(tag) { return fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'secpage-' + tag + '-')); }
function py(args, env) {
  try { return {ok: true, out: execFileSync('python3', args, {env: Object.assign({PATH: process.env.PATH, HOME: env || tmpdir('home')}), stdio: 'pipe'}).toString()}; }
  catch (e) { return {ok: false, err: String(e.stderr), code: e.status}; }
}
let BUILT = null;
function built() {           // the page as the consigne builds it (site derived from the stream: https://sol0.fr)
  if (BUILT) return BUILT;
  const out = path.join(tmpdir('build'), 'page');
  const r = py([BUILD, '--repo', 'MalikChopa/MalikChopa', '--stream', 'https://live.sol0.fr', '--birth-utc', '2026-11-13T12:11:21Z', '--out', out]);
  assert.ok(r.ok, r.err);
  BUILT = {dir: out, res: JSON.parse(r.out), html: fs.readFileSync(path.join(out, 'index.html'), 'utf8')};
  return BUILT;
}
const metaContent = (html, attr, name) => { const m = new RegExp('<meta ' + attr + '="' + name.replace(/[:.]/g, '\\$&') + '"[^>]*? content="([^"]*)"').exec(html); return m ? m[1] : null; };
const unesc = (s) => s.replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// ---------------- SEC-14 ----------------
test('SEC-14 hostile stream lines: every case under 50 ms per frame, the page draws the next normal lines (child process, 60 s cap)', () => {
  const out = execFileSync('node', [path.join(__dirname, 'hostile_bench.js')], {timeout: 60_000, env: {PATH: process.env.PATH, HOME: tmpdir('home')}}).toString();
  const r = JSON.parse(out);
  assert.ok(r.cases.length >= 23, 'cases: ' + r.cases.length);
  for (const c of r.cases) {
    assert.ok(c.ms < 50, `${c.name}: ${c.ms} ms`);
    if (c.drawsAfter !== null) assert.ok(c.drawsAfter >= 1, `${c.name}: no draw after the hostile line`);
  }
});

test('SEC-14 live.js keeps the previous value when a line carries a malformed pose, sun, target, mode, phase, module or stage name', () => {
  const S = Live.newView();
  Live.applyEvent(S, SOL(), 0);
  Live.applyEvent(S, TICK(1, {sd: [0.5, 0.6, -0.8]}), 0);
  const pose = S.pose, sun = S.sunVec;
  for (const p of [[1, 2, 'x', 0], [1, 2, 1e8, 0], [1, 2, NaN, 0], [1, 2, 1], 'abc', null, [1, 'y', 0, 1], [1, 2, 0, -1.01]]) {
    Live.applyEvent(S, TICK(2, {p}), 0);
    assert.strictEqual(S.pose, pose, JSON.stringify(p));
  }
  for (const sd of [[1, 'x', 0], [1, 1e8, 0], [2, 0, 0], [0.5, 0.6], 'x']) {
    Live.applyEvent(S, TICK(3, {sd}), 0);
    assert.strictEqual(S.sunVec, sun, JSON.stringify(sd));
  }
  Live.applyEvent(S, TICK(4, {m: 'X'.repeat(65)})); assert.strictEqual(S.mode, 'DRIVE');
  Live.applyEvent(S, TICK(5, {m: {toString: 1}})); assert.strictEqual(S.mode, 'DRIVE');
  Live.applyEvent(S, TICK(6, {tg: ['x', 1]})); assert.strictEqual(S.target, null);
  // legitimate values pass, including the engine's rounding just above 1 (dmath.rot renormalises)
  Live.applyEvent(S, TICK(7, {p: [3.5, -2.25, 1 + 1e-12, -1e-9], sd: [0, -1, 1e-7], tg: [4, 5], m: 'SEEK_SUN'}), 0);
  assert.deepStrictEqual([S.pose, S.sunVec, S.target, S.mode], [[3.5, -2.25, 1 + 1e-12, -1e-9], [0, -1, 1e-7], [4, 5], 'SEEK_SUN']);
  Live.applyEvent(S, {e: 'phase', ph: 'P'.repeat(65)}, 0); assert.strictEqual(S.phase, 'episode');
  Live.applyEvent(S, {e: 'phase', ph: 'learn'}, 0); assert.strictEqual(S.phase, 'learn');
  Live.applyEvent(S, {e: 'learn', mod: {toString: 1}, gen: 1, of: 2}, 0); assert.strictEqual(S.learn, null);
  Live.applyEvent(S, {e: 'learn', mod: 'm4', gen: 1, of: 2, best: 0.5, mean: 0.1}, 0); assert.strictEqual(S.learn.mod, 'm4');
  const S2 = Live.newView();
  Live.applyEvent(S2, Object.assign(SOL(), {stage_name: {toString: 1}}), 0); assert.strictEqual(S2.stageName, '');
  Live.applyEvent(S2, Object.assign(SOL(), {stage_name: 'N'.repeat(65)}), 0); assert.strictEqual(S2.stageName, '');
  // a flood of spectrum points in one line: at most 64 kept per line
  Live.applyEvent(S2, Object.assign(SOL(), {scan0: {n: 0, explained: 0, xy: [], labels: []}}), 0);
  Live.applyEvent(S2, TICK(1, {spc: {v: new Array(16).fill(0), pts: Array.from({length: 5000}, (_, k) => [k, 0, 0, 1])}}), 0);
  assert.strictEqual(S2.scan.pts.length, 64);
});

// ---------------- SEC-04 ----------------
test('SEC-04 link: streams_full or 503/429 = SERVER BUSY (hard); 3 stream failures then a 2xx or a 5xx = SERVER BUSY (soft); a hello resets', () => {
  const L = Live.makeLink();
  L.onHttp(200, true); assert.deepStrictEqual([L.state, L.busy, L.hard], ['SERVER BUSY', true, true]);
  L.onHttp(200, false); assert.deepStrictEqual([L.state, L.busy], ['CONNECTING', false]);
  L.onHttp(502); assert.deepStrictEqual([L.state, L.busy], ['CONNECTING', false]);
  L.onStreamError(); L.onStreamError(); L.onHttp(502); assert.strictEqual(L.busy, false, 'two failures are not enough');
  L.onStreamError(); L.onHttp(502); assert.deepStrictEqual([L.state, L.busy, L.hard], ['SERVER BUSY', true, false]);
  L.onHttp(200); assert.deepStrictEqual([L.state, L.busy, L.hard], ['SERVER BUSY', true, false]);
  L.onOk(); L.onHello(); assert.deepStrictEqual([L.state, L.busy, L.streamFails], ['LIVE', false, 0]);
  L.onHttp(200); assert.strictEqual(L.busy, false);
  L.onStreamError(); L.onStreamError(); L.onStreamError(); L.onHttp(404); assert.strictEqual(L.busy, false, 'a 4xx says nothing about load');
});

async function livePage(o) {
  const p = await makePage(Object.assign({t0: T}, o || {}));
  p.open();
  const s = [SOL(), TICK(100)];
  p.send(HELLO(s.length)); s.forEach((e) => p.send(e));
  p.advance(T + 1000);
  return p;
}
const nowFetches = (p, from) => p.fetches.filter((f) => f.url === CONFIG.stream + '/now.json' && f.t >= from).map((f) => f.t);

test('SEC-04 page: /now.json streams_full -> SERVER BUSY, the busy note, /now.json every 9 s and no stream until the places free up', async () => {
  for (const lang of ['en', 'fr']) {
    const p = await livePage({lang});
    p.nowBody = {streams_full: true};
    const n0 = p.streams.length, t0 = p.t;
    p.error(t0 + 100);
    p.advance(t0 + 30_000);
    assert.strictEqual(p.el('state').textContent, tx(lang, 'd.state.busy'));
    assert.strictEqual(p.el('silentmsg').textContent, tx(lang, 'd.busy.note'));
    assert.strictEqual(p.streams.length, n0, 'a stream was opened while the server says the streams are full');
    const f = nowFetches(p, t0);
    assert.ok(f.length >= 3, f.join());
    for (let i = 1; i < f.length; i++) assert.strictEqual(f[i] - f[i - 1], 9000);
    p.nowBody = {streams_full: false};
    p.advance(p.t + 9000 + 5000 + 10);
    assert.strictEqual(p.streams.length, n0 + 1, 'no reconnection once the places are free');
    p.open(); p.send(HELLO(0)); p.advance(p.t + 1000);
    assert.notStrictEqual(p.el('state').textContent, tx(lang, 'd.state.busy'));
    assert.deepStrictEqual(p.errors, []);
  }
});

test('SEC-04 page: repeated 502 (or a refused stream while /now.json answers 200) -> SERVER BUSY after 3 failures, then one try every 9 s', async () => {
  for (const status of [502, 200]) {
    const p = await livePage({lang: 'en'});
    p.nowStatus = status;
    const t0 = p.t, opened = [];
    let n = p.streams.length;
    p.error(t0 + 100);
    for (let t = t0 + 100; t <= t0 + 60_000; t += 100) {
      p.advance(t);
      if (p.streams.length > n) { n = p.streams.length; opened.push(p.t); p.error(p.t + 50); }     // every new stream is refused
    }
    assert.strictEqual(p.el('state').textContent, tx('en', 'd.state.busy'), String(status));
    assert.ok(opened.length >= 4, opened.join());
    assert.strictEqual(opened[0] - t0, 5100, 'first retries keep the 5 s cadence');
    for (let i = 2; i < opened.length; i++) assert.ok(opened[i] - opened[i - 1] >= 9000, `${status}: retry after ${opened[i] - opened[i - 1]} ms`);
    // the stream works again: a hello ends the busy state and resets the count
    p.nowStatus = 200;
    p.advance(p.t + 9100);
    p.open(); p.send(HELLO(0)); p.advance(p.t + 1000);
    assert.strictEqual(p.link.streamFails, 0);
    assert.notStrictEqual(p.el('state').textContent, tx('en', 'd.state.busy'));
    assert.deepStrictEqual(p.errors, []);
  }
});

// ---------------- SEC-15 ----------------
async function offlinePage(o, set) {
  const p = await livePage(o);
  if (set) set(p);
  p.nowStatus = 'network';
  p.error(p.t + 100);
  const t0 = p.t;
  for (let t = t0; t <= t0 + 120_000 && !p.html.classList.contains('offline'); t += 1000) p.advance(t);
  assert.ok(p.html.classList.contains('offline'));
  return p;
}
const GIF_URL = CONFIG.stateRaw + '/console.gif';

test('SEC-15 offline: a STILL of the published GIF (first frame on a canvas); the animation only after a click, through the EF-87 guard', async () => {
  const p = await offlinePage({lang: 'fr'});
  assert.strictEqual(p.el('offimg').src, '', 'the animated GIF must never load by itself');
  assert.strictEqual(p.el('offimg').hidden, true);
  assert.strictEqual(p.bitmaps.length, 1);
  assert.strictEqual(p.stills.length, 1); assert.strictEqual(p.stills[0].id, 'offc');
  assert.strictEqual(p.el('offc').hidden, false);
  assert.strictEqual(p.el('offplay').hidden, false);
  assert.strictEqual(p.el('offplay').textContent, tx('fr', 'n.offplay'));
  assert.strictEqual(p.el('offc').attrs['aria-label'], tx('fr', 'd.offstill'));
  assert.ok(p.bitmaps[0].closed, 'the bitmap is released');
  p.advance(p.t + 1000);
  p.click('offplay'); p.advance(p.t + 10);
  assert.strictEqual(p.el('offimg').src, GIF_URL);
  assert.deepStrictEqual([p.el('offimg').hidden, p.el('offc').hidden], [false, true]);
  assert.strictEqual(p.el('offplay').textContent, tx('fr', 'n.offstop'));
  p.click('offplay'); p.advance(p.t + 10);
  assert.strictEqual(p.el('offimg').src, GIF_URL, 'a second click within 350 ms is applied later (EF-87)');
  p.advance(p.t + 400);
  assert.strictEqual(p.el('offimg').src, '');
  assert.deepStrictEqual([p.el('offimg').hidden, p.el('offc').hidden], [true, false]);
  // the stream comes back: nothing of the offline view stays
  p.click('offplay'); p.advance(p.t + 400);
  p.open(); p.send(HELLO(2)); [SOL(), TICK(400)].forEach((e) => p.send(e)); p.advance(p.t + 1500);
  assert.deepStrictEqual([p.el('off').hidden, p.el('offimg').src, p.el('offimg').hidden, p.el('offplay').hidden], [true, '', true, true]);
  assert.deepStrictEqual(p.errors, []);
});

test('SEC-15 offline: not a GIF, or over 2 MB -> no still and no play button; status.json values checked (sol, ISO UTC time, size)', async () => {
  const html = Uint8Array.from(Buffer.from('<html><script>alert(1)</script>'));
  const big = new Uint8Array(2 * 1024 * 1024 + 1); big.set([0x47, 0x49, 0x46, 0x38, 0x39, 0x61]);
  for (const bytes of [html, big]) {
    const p = await offlinePage({lang: 'en'}, (q) => { q.gifBytes = bytes; });
    assert.deepStrictEqual([p.bitmaps.length, p.stills.length, p.el('offplay').hidden, p.el('offimg').src], [0, 0, true, '']);
  }
  const none = tx('en', 'd.t.none');
  const cases = [
    ['{"run":{"sol":41},"det":{"last_success_utc":"2026-11-13T18:00:05Z"}}', 41, true],
    ['{"run":{"sol":"<b>41</b>"},"det":{"last_success_utc":"javascript:alert(1)"}}', '?', false],
    ['{"run":{"sol":-1},"det":{"sol":7,"last_success_utc":"2026-13-99"}}', '?', false],
    ['{"det":{"sol":1.5}}', '?', false],
    ['[1,2,3]', '?', false],
    ['not json', '?', false],
    ['{"run":{"sol":3},"pad":"' + 'x'.repeat(70000) + '"}', '?', false]];
  for (const [body, n, timed] of cases) {
    const p = await offlinePage({lang: 'en'}, (q) => { q.statusBody = body; });
    const note = p.el('offnote').textContent;
    assert.ok(note.includes('Last published sol: ' + n + ','), note);
    assert.strictEqual(note.includes(none), !timed, note);
    assert.ok(!/alert|<b>/.test(note), note);
  }
});

test('SEC-15 offline: a config whose state address is not the GitHub state branch is never fetched nor shown', async () => {
  const p = await offlinePage({lang: 'en', config: {stateRaw: 'https://evil.example/x/y/state'}});
  assert.deepStrictEqual(p.fetches.filter((f) => /evil/.test(f.url)), []);
  assert.deepStrictEqual([p.bitmaps.length, p.el('offimg').src, p.el('offplay').hidden], [0, '', true]);
  assert.ok(/^Server offline\. Last published sol: \?,/.test(p.el('offnote').textContent), p.el('offnote').textContent);
  // app.js reads nothing else from the network than the stream origin, its own folder and the state branch
  const src = fs.readFileSync(path.join(PAGE, 'app.js'), 'utf8');
  const targets = [...src.matchAll(/fetch\(([^,)]+)/g)].map((m) => m[1].trim()).sort();
  assert.deepStrictEqual(targets, ["'assets.json'", "'config.json'", "'i18n.json'", "cfg.stream + '/now.json'", 'url', 'url']);
  assert.ok(!/offimg'\)\.src = cfg|\.src = cfg\.stateRaw/.test(src));
});

// ---------------- SEC-29 / SEC-15 CSP ----------------
test('SEC-29 CSP of the built page: no data:, GitHub limited to the state branch of --repo (second policy), both before any script', () => {
  const {html} = built();
  const metas = [...html.matchAll(/<meta http-equiv="Content-Security-Policy" content="([^"]*)">/g)].map((m) => m[1]);
  assert.strictEqual(metas.length, 2);
  assert.ok(!/data:/.test(metas.join(' ')));
  // consigne 52: media-src 'self' (the intro cinematic, media/intro.mp4), nothing more
  assert.strictEqual(metas[0], "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' https://raw.githubusercontent.com; media-src 'self'; " +
    "connect-src 'self' https://live.sol0.fr https://raw.githubusercontent.com; base-uri 'none'; form-action 'none'");
  assert.strictEqual(metas[1], `img-src 'self' ${STATE_SRC}; connect-src 'self' https://live.sol0.fr ${STATE_SRC}`);
  const lastMeta = html.lastIndexOf('http-equiv="Content-Security-Policy"');
  assert.ok(lastMeta < html.indexOf('<script') && lastMeta < html.indexOf('<link'));
  const cfg = JSON.parse(fs.readFileSync(path.join(built().dir, 'config.json'), 'utf8'));
  assert.strictEqual(cfg.stateRaw + '/', STATE_SRC, 'what app.js reads is inside the CSP source');
});

// ---------------- SEC-30 ----------------
test('SEC-30 explainer fragments: allow-list of tags, attributes and values; the real fragments pass', () => {
  const dir = tmpdir('frag');
  const cases = {
    meta: '<meta http-equiv="refresh" content="0;url=//evil.example">', base: '<base href="/">', iframe: '<iframe></iframe>',
    object: '<object data="x"></object>', embed: '<embed src="about/img/a.png">', form: '<form action="#x"></form>', link: '<link rel="x" href="#a">',
    a_proto: '<a href="//evil.example/">x</a>', a_https: '<a href="https://evil.example/">x</a>', a_data: '<a href="data:text/html,x">x</a>',
    a_entity: '<a href="jav&#97;script:alert(1)">x</a>', img_ext: '<img src="//evil.example/x.png" alt="">',
    img_up: '<img src="about/img/../../config.json" alt="">', svg_url: '<svg viewBox="0 0 1 1"><rect fill="url(https://evil.example/#a)"/></svg>',
    svg_xlink: '<svg><a xlink:href="#x">y</a></svg>', doctype: '<!DOCTYPE html><p>x</p>', srcdoc: '<p srcdoc="x">y</p>', cdata: '<svg><![CDATA[x]]></svg>',
    // VERIF-P I1 (out/seclot1/VERIF-P.md): html.parser and a browser disagreeing on where a tag starts or ends
    comment_diff: `<p title="<!--">a</p><p title='-->"><meta http-equiv=refresh content=0;url=//evil.example/>'>b</p>`,
    unclosed_tail: '<p>x</p>\n<meta http-equiv="refresh" content="0;url=//evil.example/"', unclosed_quote: '<p>x</p>\n<p title="x',
    svg_title: '<svg><title><meta http-equiv="refresh" content="0;url=//evil.example/"></title></svg>',
    css_escape: '<svg viewBox="0 0 1 1"><rect fill="\\75 rl(//evil.example/x.png)"/></svg>',
    css_escape_entity: '<svg viewBox="0 0 1 1"><rect fill="&#92;75 rl(#a)"/></svg>', raw_lt: '<p>1 < 2</p>', bogus_end: '</ x><p>y</p>',
    unclosed_title: '<svg><title>x', unclosed_div: '<div><p>x</p>', div_selfclose: '<div/><p>x</p>', mismatched: '<p><em>x</p></em>',
    slash_onclick: '<p/onclick=alert(1)>x</p>', unquoted_href: '<a href=//evil.example/>x</a>', http_equiv: '<p title="http-equiv">x</p>'};
  const ok = {anchor: '<p><a href="#fr/about/brain">x</a></p>', marker: '<svg viewBox="0 0 2 2"><path d="M0 0" marker-end="url(#ar)"/></svg>',
              img: '<figure><img src="about/img/map-sol86.png" alt="x" width="2" height="2" loading="lazy" decoding="async"></figure>',
              repo: '<p><a href="{{REPO_URL}}">repo</a></p>', lt_entity: '<p>1 &lt; 2 &amp; 3<br>4</p>',
              svg_title_ok: '<svg viewBox="0 0 2 2"><title id="t">A &lt;b&gt;</title><desc id="d">x</desc></svg>',
              comment: '<!-- a note: <meta> is refused --><p>x</p>'};
  const drv = path.join(dir, 'drv.py');
  fs.writeFileSync(drv, [
    'import json, sys', 'from pathlib import Path', 'sys.path.insert(0, sys.argv[1])', 'import build_page',
    'cases = json.loads(Path(sys.argv[2]).read_text()); src = Path(sys.argv[3]); res = {}; srv = {}',
    'for k, frag in cases.items():',
    '    (src / "about").mkdir(parents=True, exist_ok=True); (src / "about" / "fr.html").write_text(frag, encoding="utf-8")',
    '    try:', '        srv[k] = build_page._fragment(src, "fr", "https://github.com/o/r"); res[k] = "ok"',
    '    except SystemExit as e:', '        res[k] = "refused: " + str(e)',
    'print(json.dumps({"res": res, "srv": srv}))'].join('\n'));
  fs.writeFileSync(path.join(dir, 'cases.json'), JSON.stringify(Object.assign({}, cases, ok)));
  const r = py(['-I', drv, path.dirname(BUILD), path.join(dir, 'cases.json'), path.join(dir, 'src')]);
  assert.ok(r.ok, r.err);
  const {res, srv} = JSON.parse(r.out);
  for (const k of Object.keys(cases)) assert.ok(res[k].startsWith('refused'), `${k}: ${res[k]}`);
  for (const k of Object.keys(ok)) assert.strictEqual(res[k], 'ok', k);
  assert.strictEqual(srv.comment, '<p>x</p>', 'the allow-list ran on the served text: comments removed first');
  assert.strictEqual(srv.repo, '<p><a href="https://github.com/o/r">repo</a></p>');
  assert.ok(built().html.includes('data-explain="fr"') && built().html.includes('data-explain="en"'));
});

// ---------------- SEC-17 ----------------
test('SEC-17 404.html: console style, FR + EN, links back to the live and to How it works, no script, copied as it is', () => {
  const src = fs.readFileSync(path.join(PAGE, '404.html'), 'utf8');
  assert.ok(!/<script|\son[a-z]+\s*=|\sstyle\s*=|<style|https?:\/\/|\{\{/i.test(src));
  assert.ok(/<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'">/.test(src));
  assert.ok(src.includes('<link rel="stylesheet" href="/live.css">') && src.includes('<section lang="fr">') && src.includes('<section lang="en">'));
  for (const h of ['/#fr/live', '/#en/live', '/#fr/about', '/#en/about', '/']) assert.ok(src.includes(`href="${h}"`), h);
  assert.ok(src.includes('Retour au direct') && src.includes('Back to the live view') && src.includes('Comment ça marche') && src.includes('How it works'));
  assert.deepStrictEqual(src.replace(/<[^>]*>/g, ' ').replace(/sol-0/gi, '').match(/\d+/g), ['404'], 'no number but the error code (no invented data)');
  const css = fs.readFileSync(path.join(PAGE, 'live.css'), 'utf8');
  for (const c of ['nf-box', 'nf-head', 'nf-badge', 'nf-links', 'nf-main', 'nf-home']) assert.ok(css.includes('.' + c), c);
  assert.strictEqual(fs.readFileSync(path.join(built().dir, '404.html'), 'utf8'), src);
});

// ---------------- SEO lot A ----------------
test('SEO: head of the built page (canonical, description, Open Graph, X card, JSON-LD, icons) for https://sol0.fr; no hreflang yet', () => {
  const {html, dir, res} = built();
  assert.strictEqual(res.site, 'https://sol0.fr');
  const title = /<title>([^<]*)<\/title>/.exec(html)[1];
  assert.strictEqual(unesc(title), I18N['d.title'].en);
  assert.strictEqual(unesc(metaContent(html, 'name', 'description')), I18N['d.desc'].en);
  assert.ok(html.includes('<link rel="canonical" href="https://sol0.fr/">'));
  assert.ok(!/hreflang="(?:fr|en|x-default)"/.test(html.slice(0, html.indexOf('</head>'))), 'lot A: one URL, no hreflang');
  assert.strictEqual(metaContent(html, 'property', 'og:url'), 'https://sol0.fr/');
  assert.strictEqual(unesc(metaContent(html, 'property', 'og:title')), I18N['d.title'].en);
  assert.strictEqual(unesc(metaContent(html, 'property', 'og:description')), I18N['d.desc'].en);
  const img = metaContent(html, 'property', 'og:image');
  assert.strictEqual(img, 'https://sol0.fr/about/img/bande-annonce-image180.png');
  const png = fs.readFileSync(path.join(dir, 'about', 'img', 'bande-annonce-image180.png'));
  assert.deepStrictEqual([metaContent(html, 'property', 'og:image:width'), metaContent(html, 'property', 'og:image:height')],
    [String(png.readUInt32BE(16)), String(png.readUInt32BE(20))]);
  assert.ok(/illustration/i.test(metaContent(html, 'property', 'og:image:alt')) && /ILLUSTRATION/.test(metaContent(html, 'property', 'og:image:alt')));
  assert.strictEqual(metaContent(html, 'name', 'twitter:card'), 'summary_large_image');
  const ld = JSON.parse(/<script type="application\/ld\+json">([^<]*)<\/script>/.exec(html)[1]);
  assert.deepStrictEqual(ld, {'@context': 'https://schema.org', '@type': 'WebSite', name: 'Sol-0', alternateName: ['SOL-0', 'Sol-0 live'], url: 'https://sol0.fr/', inLanguage: ['en', 'fr']});
  for (const h of ['favicon.ico', 'icons/icon-192.png', 'icons/apple-touch-icon.png']) {
    assert.ok(html.includes(`href="${h}"`), h); assert.ok(fs.existsSync(path.join(dir, h)), h);
  }
  assert.strictEqual(fs.readFileSync(path.join(dir, 'robots.txt'), 'utf8'), 'User-agent: *\nAllow: /\n\nSitemap: https://sol0.fr/sitemap.xml\n');
  assert.strictEqual(fs.readFileSync(path.join(dir, 'sitemap.xml'), 'utf8'),
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n<url><loc>https://sol0.fr/</loc></url>\n</urlset>\n');
});

test('SEO: --site none, an explicit site, a stream that is not live.* and a bad site', () => {
  const run = (stream, extra) => { const out = path.join(tmpdir('site'), 'p'); return Object.assign(py([BUILD, '--repo', 'o/r', '--stream', stream, '--out', out].concat(extra || [])), {dir: out}); };
  const a = run('https://live.example.org', ['--site', 'none']);
  assert.ok(a.ok, a.err);
  const ha = fs.readFileSync(path.join(a.dir, 'index.html'), 'utf8');
  assert.ok(!/canonical|og:|ld\+json|twitter:/.test(ha) && !fs.existsSync(path.join(a.dir, 'sitemap.xml')));
  assert.strictEqual(fs.readFileSync(path.join(a.dir, 'robots.txt'), 'utf8'), 'User-agent: *\nAllow: /\n');
  const b = run('https://live.example.org', ['--site', 'https://www.example.net']);
  assert.ok(b.ok, b.err);
  assert.ok(fs.readFileSync(path.join(b.dir, 'index.html'), 'utf8').includes('<link rel="canonical" href="https://www.example.net/">'));
  const c = run('https://stream.example.org');
  assert.ok(c.ok && JSON.parse(c.out).site === null, c.err);
  assert.ok(!/canonical/.test(fs.readFileSync(path.join(c.dir, 'index.html'), 'utf8')));
  const d = run('https://live.example.org');
  assert.strictEqual(JSON.parse(d.out).site, 'https://example.org');
  for (const bad of ['http://example.org', 'https://example.org/path', 'example.org', 'https://x y']) {
    const e = run('https://live.example.org', ['--site', bad]);
    assert.ok(!e.ok && /--site/.test(e.err), bad);
  }
});

test('SEO: title and description follow the page language; noscript lead FR + EN with the repository link; no snippet from the status bars', async () => {
  for (const lang of ['en', 'fr']) {
    const p = await livePage({lang});
    assert.strictEqual(p.document.title, I18N['d.title'][lang]);
    assert.strictEqual(p.el('mdesc').attrs.content, I18N['d.desc'][lang]);
    p.navigate('#' + lang + '/about'); p.advance(p.t + 400);
    assert.strictEqual(p.document.title, tx(lang, 'n.tab.about') + ' · Sol-0');
    assert.deepStrictEqual(p.errors, []);
  }
  const {html} = built();
  const ns = /<noscript>([\s\S]*?)<\/noscript>/.exec(html)[1];
  for (const l of ['fr', 'en']) assert.ok(ns.includes(`<p lang="${l}">${I18N['n.noscript.lead'][l]}</p>`), l);
  assert.ok(ns.includes('<a href="https://github.com/MalikChopa/MalikChopa">GitHub · MalikChopa/MalikChopa</a>'));
  for (const id of ['bar', 'bar2', 'silentmsg', 'stateann']) assert.ok(new RegExp(`id="${id}"[^>]*data-nosnippet`).test(html), id);
});

test('SEO: without JavaScript the explainer is shown in both languages and the empty console is not; with it, nothing changes', async () => {
  const css = fs.readFileSync(path.join(PAGE, 'live.css'), 'utf8');
  assert.ok(css.includes('html.js[lang="fr"] .l-en, html.js[lang="en"] .l-fr { display: none; }'));
  assert.ok(css.includes('html.js[data-tab="about"] #view-live, html.js[data-tab="live"] #view-about { display: none; }'));
  assert.ok(!/(^|\n)html\[lang=|(^|\n)html\[data-tab=/.test(css), 'a language or tab rule without .js would hide text from a no-JS reader');
  for (const id of ['#stage', '#bar', '#bar2', '#tabs', '.tools', '#details', '#skip']) assert.ok(css.includes('html:not(.js) ' + id), id);
  const p = await livePage({lang: 'fr'});
  assert.ok(p.html.classList.contains('js'), 'route.js marks the page as scripted before the first paint');
  const route = fs.readFileSync(path.join(PAGE, 'route.js'), 'utf8');
  assert.ok(route.indexOf("classList.add('js')") < route.indexOf('html.lang = r.lang'));
});

test('icons: make_icons.py --check (pixels of the committed files), ICO sizes 16/32/48, PNG 192 and 180, copied by the build', () => {
  const r = py(['-I', ICONS, '--check']);
  assert.ok(r.ok, r.err);
  const ico = fs.readFileSync(path.join(PAGE, 'favicon.ico'));
  assert.deepStrictEqual([ico.readUInt16LE(0), ico.readUInt16LE(2), ico.readUInt16LE(4)], [0, 1, 3]);
  assert.deepStrictEqual([0, 1, 2].map((k) => ico[6 + 16 * k]), [16, 32, 48]);
  for (const [f, n] of [['icons/icon-192.png', 192], ['icons/apple-touch-icon.png', 180]]) {
    const b = fs.readFileSync(path.join(PAGE, f));
    assert.deepStrictEqual([b.readUInt32BE(16), b.readUInt32BE(20)], [n, n], f);
    assert.ok(b.equals(fs.readFileSync(path.join(built().dir, f))), f);
  }
  assert.ok(ico.equals(fs.readFileSync(path.join(built().dir, 'favicon.ico'))));
});
