'use strict';
// live-rc16: the visitor's local time next to every UTC time of the DOM (S3), and « Alive for 3 h 12 min · 13 sols » (S5).
// Zones are passed explicitly (or through TZ in a child process): the result never depends on the machine running the tests.
const test = require('node:test');
const assert = require('node:assert');
const {execFileSync} = require('node:child_process');
const {Live, fs, path, PAGE} = require('./helpers.js');
const {makePage} = require('./app_vm.js');
const {I18N, tx} = require('./page_helpers.js');
const Lay = require(path.join(PAGE, 'layout.js'));

const CSS = fs.readFileSync(path.join(PAGE, 'live.css'), 'utf8');
const BUILD = path.join(__dirname, '..', '..', 'tools', 'live', 'build_page.py');
const T = 5_000_000;
const SRV = '2026-11-13T15:30:00Z';
const BIRTH = '2026-11-13T12:11:21Z';
const O = (lang) => ({t: Object.fromEntries(Object.entries(I18N).map(([k, v]) => [k, v[lang]]))});
const ms = (iso) => Date.parse(iso);

test('S3 formatting: FR and EN, several zones, one clock when the zone is UTC', () => {
  const m = ms('2026-11-13T14:45:00Z');
  assert.strictEqual(Live.timeBoth(m, false, O('en'), 'UTC'), '14:45 UTC');
  assert.strictEqual(Live.timeBoth(m, false, O('en'), 'Europe/Paris'), '14:45 UTC · 15:45 your time');
  assert.strictEqual(Live.timeBoth(m, false, O('fr'), 'Europe/Paris'), '14:45 UTC · 15:45 chez vous');
  assert.strictEqual(Live.timeBoth(m, true, O('fr'), 'America/New_York'), '14:45:00 UTC · 09:45:00 chez vous');
  assert.strictEqual(Live.timeBoth(m, false, O('en'), 'Asia/Kolkata'), '14:45 UTC · 20:15 your time');
  assert.strictEqual(Live.timeBoth(ms('2026-11-13T23:50:00Z'), false, O('en'), 'Europe/Paris'), '23:50 UTC · 00:50 your time');   // 24 h clock, never « 24:50 »
  assert.strictEqual(Live.timeBoth(NaN, false, O('en'), 'UTC'), '');
  assert.strictEqual(Live.timeBoth(Date.parse('nope'), true, O('en')), '');
});

test('S3 daylight saving: Europe/Paris is +1 h in winter and +2 h in summer; the change day follows the zone', () => {
  const en = O('en');
  assert.strictEqual(Live.timeBoth(ms('2026-01-15T12:00:00Z'), false, en, 'Europe/Paris'), '12:00 UTC · 13:00 your time');
  assert.strictEqual(Live.timeBoth(ms('2026-07-15T12:00:00Z'), false, en, 'Europe/Paris'), '12:00 UTC · 14:00 your time');
  // 2026-03-29 01:00 UTC: Paris goes from +1 to +2 (02:00 -> 03:00 local)
  assert.strictEqual(Live.timeBoth(ms('2026-03-29T00:59:00Z'), false, en, 'Europe/Paris'), '00:59 UTC · 01:59 your time');
  assert.strictEqual(Live.timeBoth(ms('2026-03-29T01:00:00Z'), false, en, 'Europe/Paris'), '01:00 UTC · 03:00 your time');
  // London in winter has the UTC clock: shown once; in summer not
  assert.strictEqual(Live.timeBoth(ms('2026-01-15T12:00:00Z'), false, en, 'Europe/London'), '12:00 UTC');
  assert.strictEqual(Live.timeBoth(ms('2026-07-15T12:00:00Z'), false, en, 'Europe/London'), '12:00 UTC · 13:00 your time');
});

test('S3 the machine zone (TZ in a child process): UTC shows once, Asia/Kolkata +05:30 shows both', () => {
  const code = `const L=require(${JSON.stringify(path.join(PAGE, 'live.js'))});console.log(L.timeBoth(Date.parse('2026-11-13T14:45:00Z'),false,{t:{'d.t.utc':'{u} UTC','d.t.both':'{u} UTC / {l}'}}))`;
  const run = (tz) => execFileSync(process.execPath, ['-e', code], {env: {PATH: process.env.PATH, TZ: tz, HOME: process.env.TMPDIR || '/nonexistent'}}).toString().trim();
  assert.strictEqual(run('UTC'), '14:45 UTC');
  assert.strictEqual(run('Asia/Kolkata'), '14:45 UTC / 20:15');
  assert.strictEqual(run('America/New_York'), '14:45 UTC / 09:45');
});

test('S5 durations and text: hours, days, minutes; sols from the stream; FR and EN; singular', () => {
  const en = O('en'), fr = O('fr'), b = ms(BIRTH);
  assert.strictEqual(Live.aliveText(b, b + (3 * 3600 + 12 * 60 + 5) * 1000, 13, 'en', en), 'Alive for 3 h 12 min · 13 sols');
  assert.strictEqual(Live.aliveText(b, b + (3 * 3600 + 12 * 60 + 5) * 1000, 13, 'fr', fr), 'En vie depuis 3 h 12 min · 13 sols');
  assert.strictEqual(Live.aliveText(b, b + (2 * 86400 + 3 * 3600 + 59 * 60) * 1000, 190, 'fr', fr), 'En vie depuis 2 j 3 h · 190 sols');
  assert.strictEqual(Live.aliveText(b, b + (2 * 86400 + 3 * 3600) * 1000, 190, 'en', en), 'Alive for 2 d 3 h · 190 sols');
  assert.strictEqual(Live.aliveText(b, b + 42 * 60 * 1000, 1, 'en', en), 'Alive for 42 min · 1 sol');
  assert.strictEqual(Live.aliveText(b, b + 42 * 60 * 1000, 0, 'fr', fr), 'En vie depuis 42 min · 0 sol');
  assert.strictEqual(Live.aliveText(b, b + 42 * 60 * 1000, 0, 'en', en), 'Alive for 42 min · 0 sols');
  assert.strictEqual(Live.aliveText(b, b + 5000, 7, 'en', en), 'Alive for 0 min · 7 sols');
  // no sol from the stream: no number, never computed from the clock
  assert.strictEqual(Live.aliveText(b, b + 3600e3, null, 'en', en), 'Alive for 1 h 0 min');
  assert.strictEqual(Live.aliveText(b, b + 3600e3, undefined, 'fr', fr), 'En vie depuis 1 h 0 min');
  // no birth, or a birth in the future: nothing
  assert.strictEqual(Live.aliveText(null, b, 3, 'en', en), '');
  assert.strictEqual(Live.aliveText(b, b - 1, 3, 'en', en), '');
  assert.strictEqual(Live.birthMs('2026-11-13T12:11:21Z'), b);
  for (const bad of [undefined, null, '', 'yesterday', '2026-11-13 12:11:21', '2026-11-13T12:11:21+01:00', '2026-13-45T99:00:00Z', 12]) assert.strictEqual(Live.birthMs(bad), null, String(bad));
});

const SOL = (s) => ({e: 'sol', s, stage: 3, stage_name: 'ENERGY', now: SRV, cam: {w: 8, h: 6, D: 1}, tick_ms: 600, slot0: ms('2026-11-13T15:15:00Z'),
  sun: {lever: 6, coucher: 18}, season_sols: 150});
const POSES = (n, s) => ({e: 'poses', s, t: Array.from({length: n}, (_, i) => i), p: []});
const TICK = (t, s) => ({e: 'tick', s, t, hr: 8.5, m: 'DRIVE', p: [10, 20, 1, 0], tg: null, b: 0.5, v: 0.1, pi: 0, ro: 0, sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0],
  x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0], dr: 0, nd: 0});
const HELLO = (snap) => ({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: snap.length, tick_age_s: 0.1, cam_age_s: 0.1, phase_age_s: null});
async function livePage(o, sol) {
  const p = await makePage(Object.assign({t0: T}, o));
  p.open();
  const s = [SOL(sol), POSES(101, sol), TICK(100, sol)];
  p.send(HELLO(s)); s.forEach((e) => p.send(e)); p.advance(T + 2000);
  return p;
}

test('S5 the page: the line comes from config.json birth_utc and the stream sol, ticks once a second; absent birth: no line', async () => {
  for (const lang of ['en', 'fr']) {
    const p = await livePage({lang, config: {birth_utc: BIRTH}}, 13);
    assert.strictEqual(p.el('alive').textContent, lang === 'fr' ? 'En vie depuis 3 h 18 min · 13 sols' : 'Alive for 3 h 18 min · 13 sols', 'server clock 15:30:00 (+2 s of the page)');
    p.advance(T + 2000 + 60_000);
    assert.ok(/3 h 19 min/.test(p.el('alive').textContent), p.el('alive').textContent);
    // a new sol line: the number follows the stream
    p.send(SOL(14), p.t + 10); p.send(POSES(1, 14), p.t + 11); p.send(TICK(0, 14), p.t + 12); p.advance(p.t + 2000);
    assert.ok(/ 14 sols?$/.test(p.el('alive').textContent), p.el('alive').textContent);
    assert.deepStrictEqual(p.errors, []);
    const q = await livePage({lang}, 13);
    assert.strictEqual(q.el('alive').textContent, '', 'no --birth-utc: the line is not shown');
    const r = await livePage({lang, config: {birth_utc: 'garbage'}}, 13);
    assert.strictEqual(r.el('alive').textContent, '');
  }
});

test('S3 the page: the next sol shows UTC and the visitor\'s time; the offline note too; canvas texts untouched', async () => {
  const p = await livePage({lang: 'en', config: {birth_utc: BIRTH}}, 13);
  p.send({e: 'phase', ph: 'idle', next: '2026-11-13T15:45:00Z'}, p.t + 10); p.advance(p.t + 2000);
  assert.ok(/^NEXT SOL 15:45:00 UTC(?: · \d\d:\d\d:\d\d your time)? \(\d+:\d\d\)$/.test(p.el('next').textContent), p.el('next').textContent);
  const src = fs.readFileSync(path.join(PAGE, 'console.js'), 'utf8') + fs.readFileSync(path.join(PAGE, 'live.js'), 'utf8');
  assert.ok(!/timeBoth/.test(fs.readFileSync(path.join(PAGE, 'console.js'), 'utf8')) && /getUTCHours\(\)\), mm: pad2/.test(src), 'the canvas keeps its UTC');
  assert.strictEqual(I18N['c.hdr.right'].en, 'SOL START {hh}:{mm} UTC');
  assert.strictEqual(I18N['c.wait.next'].en, 'NEXT SOL {hh}:{mm}:{ss} UTC');
});

test('i18n completeness: every new text has FR + EN with the same placeholders', () => {
  const ids = Object.keys(I18N).filter((k) => k.startsWith('d.t.') || k.startsWith('d.alive'));
  assert.ok(ids.length === 9, ids.join(','));
  for (const id of ids.concat(['d.next', 'd.off.note'])) {
    assert.ok(I18N[id].en && I18N[id].fr, id);
    const ph = (s) => (s.match(/\{[a-z]+\}/g) || []).sort().join();
    assert.strictEqual(ph(I18N[id].en), ph(I18N[id].fr), id);
  }
  assert.ok(/chez vous/.test(tx('fr', 'd.t.both', {u: 'a', l: 'b'})) && /your time/.test(tx('en', 'd.t.both', {u: 'a', l: 'b'})));
});

// layout budget (rc15 rules): the data age never truncated, the alive line the first to give way, no console move
function rule(sel) { const i = ('\n' + CSS).indexOf('\n' + sel + ' {'); assert.ok(i >= 0, sel); return CSS.slice(i + sel.length + 2, CSS.indexOf('}', i)).trim(); }
test('layout: #alive shrinks before everything; #age and #state never shrink; panels mode wraps (nothing truncated)', () => {
  assert.strictEqual(rule('html[data-mode="console"] #bar > #state, html[data-mode="console"] #bar > #age'), 'flex: none;');
  assert.strictEqual(rule('html[data-mode="console"] #bar > #alive'), 'flex-shrink: 2000;');
  assert.ok(/flex-shrink: 1000;/.test(rule('html[data-mode="console"] #bar > #noimg, html[data-mode="console"] #bar > #stagebar')));
  assert.ok(/flex-wrap: wrap;/.test(rule('#bar, #bar2')) && !/nowrap/.test(rule('#bar, #bar2')));
});

test('layout at 320/375/568/768/1024/1440: console size and the age text do not change with the alive line', async () => {
  const sizes = [[320, 568, 2], [375, 667, 2], [568, 320, 2], [768, 954, 2], [1024, 768, 1], [1440, 789, 2]];
  for (const lang of ['en', 'fr']) {
    for (const [vw, vh, dpr] of sizes) {
      const run = async (cfg) => {
        const p = await makePage({t0: T, lang, vw, vh, dpr, config: cfg});
        const st = p.el('stage'); st.clientWidth = vw - 16;
        st.getBoundingClientRect = () => ({top: p.html.classList.contains('compact') ? 58 : 76});
        p.el('details').offsetHeight = 28;
        p.resize(vw, vh, dpr); p.advance(T + 10); p.open();
        const s = [SOL(13), POSES(101, 13), TICK(100, 13)];
        p.send(HELLO(s)); s.forEach((e) => p.send(e)); p.advance(T + 1000); p.resize(vw, vh, dpr); p.advance(T + 1100);
        for (let t = T + 2000; t <= T + 125_000; t += 1000) p.advance(t);
        assert.deepStrictEqual(p.errors, []);
        return p;
      };
      const a = await run({birth_utc: BIRTH}), b = await run({}), tag = `${lang} ${vw}x${vh}`;
      assert.strictEqual([a.el('console').style.width, a.el('console').style.height].join(), [b.el('console').style.width, b.el('console').style.height].join(), tag);
      assert.strictEqual(a.el('age').textContent.replace(/\d+/g, 'N'), b.el('age').textContent.replace(/\d+/g, 'N'), tag);
      assert.ok(/\d/.test(a.el('age').textContent) && a.el('alive').textContent.length > 0, tag);
      assert.strictEqual(a.el('alive').parentNode, a.el(Lay.chooseMode(vw, vh) === 'console' ? 'bar' : 'bar2'), tag);
    }
  }
});

test('build_page.py: --birth-utc is validated and written into config.json; absent -> no key; never guessed', () => {
  const tmp = fs.mkdtempSync(path.join(process.env.TMPDIR || require('os').tmpdir(), 'rc16-'));
  const run = (args) => { try { return {ok: true, out: execFileSync('python3', [BUILD, '--repo', 'o/r', '--stream', 'https://live.example.org', ...args], {env: {PATH: process.env.PATH, HOME: tmp}, stdio: 'pipe'}).toString()}; } catch (e) { return {ok: false, err: String(e.stderr)}; } };
  const out1 = path.join(tmp, 'a'), out2 = path.join(tmp, 'b');
  assert.ok(run(['--out', out1, '--birth-utc', BIRTH]).ok);
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(out1, 'config.json'), 'utf8')).birth_utc, BIRTH);
  assert.ok(run(['--out', out2]).ok);
  assert.ok(!('birth_utc' in JSON.parse(fs.readFileSync(path.join(out2, 'config.json'), 'utf8'))));
  for (const bad of ['2026-11-13', '2026-11-13T12:11:21', '2026-02-30T12:00:00Z', 'now', '2026-11-13T12:11:21+00:00']) {
    const r = run(['--out', path.join(tmp, 'c'), '--birth-utc', bad]);
    assert.ok(!r.ok && /birth-utc/.test(r.err), bad);
  }
  fs.rmSync(tmp, {recursive: true, force: true});
});
