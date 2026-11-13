'use strict';
// live-rc15: the fixes of out/page-v2/VERIF-rc14.md (I1, I2, I3, and the cheap M1, M2, M4, M5), on the REAL page code (layout.js,
// live.js, console.js, and app.js in the VM of app_vm.js). No browser: CSS is checked as text, and the heights the page measures in a
// browser are modelled from live.css (the model is checked against the stylesheet). Test streams and test states only.
const test = require('node:test');
const assert = require('node:assert');
const {Con, Live, fs, path, PAGE} = require('./helpers.js');
const {makePage} = require('./app_vm.js');
const {tx, opts, states, findText, I18N, TEST_NOW} = require('./page_helpers.js');
const Lay = require(path.join(PAGE, 'layout.js'));

const CSS = fs.readFileSync(path.join(PAGE, 'live.css'), 'utf8');
const HTML = fs.readFileSync(path.join(PAGE, 'index.html'), 'utf8');
const T = 5_000_000;
const SRV = '2026-11-13T10:00:00Z';
const CAM = (w, h, v) => Buffer.alloc(w * h, v === undefined ? 3 : v).toString('base64');
const TICK = (t, extra) => Object.assign({e: 'tick', s: 9, t, hr: 8.5, m: 'DRIVE', p: [10, 20, 1, 0], tg: null, b: 0.5, v: 0.1, pi: 0, ro: 0,
  sl: 0, so: 0, fl: 0, u: [0, 0], xi: [0, 0], x: new Array(24).fill(0), hd: new Array(16).fill(0), y: [0, 0], dr: 0, nd: 0}, extra || {});
const CTICK = (t, extra) => TICK(t, Object.assign({cam: CAM(8, 6, t % 24), z: new Array(40).fill(0)}, extra || {}));
const SOL = (s, extra) => Object.assign({e: 'sol', s: s === undefined ? 9 : s, stage: 3, stage_name: 'ENERGY', now: SRV, cam: {w: 8, h: 6, D: 1},
  tick_ms: 600, slot0: Date.parse('2026-11-13T09:45:00Z'), sun: {lever: 6, coucher: 18}, season_sols: 150}, extra || {});
const POSES = (n, s) => ({e: 'poses', s: s === undefined ? 9 : s, t: Array.from({length: n}, (_, i) => i), p: []});
const HELLO = (snap, h) => Object.assign({e: 'hello', proto: 2, server_utc: SRV, engine_silent_s: 0, snap_n: snap.length, tick_age_s: 0.1,
  cam_age_s: 0.1, phase_age_s: null}, h || {});
const iso = (ms) => new Date(ms).toISOString().replace('.000', '');

// one CSS rule's declarations, by its exact selector (the whole selector, at the start of a line)
function rule(sel) {
  const i = ('\n' + CSS).indexOf('\n' + sel + ' {');
  assert.ok(i >= 0, `no rule « ${sel} »`);
  return CSS.slice(i + sel.length + 2, CSS.indexOf('}', i)).trim();
}
function px(decls, prop) { const m = new RegExp(`(?:^|;)\\s*${prop}: (\\d+)px`).exec(decls); return m ? +m[1] : null; }

// What a browser measures for #stage, modelled from live.css (checked by the test « CSS heights » below): #top 44 px (compact 32),
// #bar 32 px (compact 26) on one line in console mode, #bar2 never shown in console mode, else one row of about 20 px when it has a
// text, #silentmsg about 22 px when shown, the view's top padding 0 in console mode (else 4). The stage is as wide as the window minus
// 2 x 8 px. « Details » closed: 28 px.
function measure(p, vw) {
  const st = p.el('stage');
  st.clientWidth = vw - 16;
  st.getBoundingClientRect = () => {
    const compact = p.html.classList.contains('compact'), consoleMode = p.html.dataset.mode === 'console';
    const bar2 = !consoleMode && (p.el('stagebar').textContent || p.el('next').textContent) ? 20 : 0;
    return {top: (compact ? 32 : 44) + (compact ? 26 : 32) + bar2 + (p.el('silentmsg').hidden ? 0 : 22) + (consoleMode ? 0 : 4)};
  };
  p.el('details').offsetHeight = 28;
}
function consoleSize(p) { return [p.el('console').style.width, p.el('console').style.height].join(' x '); }
function want(vw, vh, dpr) { const c = Lay.plan(vw, vh, dpr).console; return `${c.cssW}px x ${c.cssH}px`; }

test('VERIF-rc14 I1: in console mode the badge and the data age never shrink; « no image yet » apart, it gives way first', async () => {
  // the stylesheet: one line; #state and #age `flex: none`; #noimg and #stagebar shrink first, the sol line next, the next sol last
  assert.strictEqual(rule('html[data-mode="console"] #bar'), 'flex-wrap: nowrap; overflow: hidden;');
  assert.ok(/flex: 0 100 auto;/.test(rule('html[data-mode="console"] #bar > span')));
  assert.strictEqual(rule('html[data-mode="console"] #bar > #state, html[data-mode="console"] #bar > #age'), 'flex: none;');
  assert.strictEqual(rule('html[data-mode="console"] #bar > #noimg, html[data-mode="console"] #bar > #stagebar'), 'flex-shrink: 1000;');
  assert.strictEqual(rule('html[data-mode="console"] #bar > #next'), 'flex-shrink: 1;');
  assert.ok(HTML.includes('<span id="line"></span><span id="age"></span><span id="noimg"></span></div>'));
  // the page: #age holds the age alone (FR and EN), #noimg the rest
  for (const lang of ['en', 'fr']) {
    const p = await makePage({t0: T, lang, keepBuffer: true});
    p.open();
    const s = [SOL(), POSES(101), TICK(100)];                        // no image yet in this sol
    p.send(HELLO(s)); s.forEach((e) => p.send(e)); p.advance(T + 2000);
    assert.ok(new RegExp('^' + tx(lang, 'd.age', {t: '\\d+ s'}) + '$').test(p.el('age').textContent), p.el('age').textContent);
    assert.strictEqual(p.el('noimg').textContent, '· ' + tx(lang, 'd.noimage'));
    p.send(CTICK(101), T + 2100); p.advance(T + 3500);
    assert.strictEqual(p.el('noimg').textContent, '');
    assert.deepStrictEqual(p.errors, []);
  }
  // width model (ESTIMATE, no browser: monospace advance 0.6 em, as in VERIF-rc14): the widest badge of the language and the longest
  // age (« 59 min 59 s ») fit in every console-mode window from 568 px wide, so the age always keeps its number
  const ages = ['59 min 59 s', '23 h 59 min'];
  for (const lang of ['en', 'fr']) {
    const badge = Math.max(...Object.keys(I18N).filter((k) => k.startsWith('d.state.')).map((k) => I18N[k][lang].length));
    const age = Math.max(...ages.map((a) => tx(lang, 'd.age', {t: a}).length));
    for (const [vw, vh] of [[568, 320], [640, 300], [667, 375], [844, 390], [1024, 698], [1440, 789], [2560, 1440]]) {
      const compact = Lay.isCompact(Lay.chooseMode(vw, vh), vh), font = compact ? 13 : 14, gap = compact ? 10 : 14;
      const need = (badge * 0.6 * font + 2 * 8 + 2) + gap + age * 0.6 * font + 2 * 8;
      assert.ok(need <= vw, `${lang} ${vw}x${vh}: badge + age need ${need.toFixed(0)} px`);
    }
  }
});

test('VERIF-rc14 I2: the CSS heights are the layout constants; console mode has one status row; compact: « Details » not subtracted', () => {
  assert.strictEqual(px(rule('#top'), 'min-height'), Lay.CHROME.header);
  assert.strictEqual(px(rule('#bar'), 'min-height'), Lay.CHROME.bar);
  assert.strictEqual(px(rule('html.compact #top'), 'min-height'), Lay.CHROME.compact);
  assert.strictEqual(px(rule('html.compact #bar'), 'min-height'), Lay.CHROME.compactBar);
  assert.strictEqual(px(rule('html.compact #view-live'), 'padding-bottom'), Lay.CHROME.compactBottom);
  assert.strictEqual(rule('html[data-mode="console"] #view-live'), 'padding-top: 0;');
  assert.strictEqual(rule('html[data-mode="console"] #bar2'), 'display: none;');
  assert.ok(/html\.compact #bar\.waitnext > #line, html\.compact #bar\.waitnext > #noimg \{ display: none; \}/.test(CSS));
  // the measured path (app.js) and the computed one (tests, fallback) are the same function: equal for the CSS heights
  for (const [vw, vh] of [[568, 320], [667, 375], [1024, 768], [1440, 789], [2560, 1440]]) {
    const compact = Lay.isCompact('console', vh), top = compact ? 32 + 26 : 44 + 32;
    assert.deepStrictEqual(Lay.stageBox(vh, compact, vw - 16, top, 28), Lay.consoleBox(vw, vh), `${vw}x${vh}`);
    // compact: an open « Details » (300 px) does not shrink the console; otherwise its height counts, at most 40 px
    assert.deepStrictEqual(Lay.stageBox(vh, compact, vw - 16, top, 300).h, compact ? Lay.consoleBox(vw, vh).h : vh - top - 40 - 16);
  }
  // larger than rc14's measured phone landscape (VERIF-rc14: about 388x218, 320x180 while waiting, at 568x320)
  assert.ok(Lay.plan(568, 320, 2).console.cssW >= 458 && Lay.plan(667, 375, 2).console.cssW >= 555);
});

test('VERIF-rc14 I2: phone in landscape, measured path of app.js: the console keeps its size from a sol to the end-of-sol wait', async () => {
  for (const [vw, vh, dpr] of [[568, 320, 2], [667, 375, 2], [1440, 789, 2]]) {
    for (const lang of ['fr', 'en']) {
      const p = await makePage({t0: T, lang, keepBuffer: true, vw, vh, dpr});
      measure(p, vw);
      p.resize(vw, vh, dpr); p.advance(T + 10);
      p.open();
      const s = [SOL(), POSES(101), CTICK(96), TICK(100)];
      p.send(HELLO(s)); s.forEach((e) => p.send(e)); p.advance(T + 1000);
      p.resize(vw, vh, dpr); p.advance(T + 1100);                       // the bar has its texts: lay out again (ResizeObserver in a browser)
      const tag = `${vw}x${vh} ${lang}`, size = consoleSize(p);
      assert.strictEqual(p.html.dataset.mode, 'console', tag);
      assert.strictEqual(p.html.classList.contains('compact'), vh < 500, tag);
      assert.strictEqual(size, want(vw, vh, dpr), tag);
      assert.strictEqual(p.el('next').parentNode, p.el('bar'), `${tag}: the next sol is not in the status row`);
      assert.strictEqual(p.el('stagebar').parentNode, p.el('bar'), tag);
      // end of sol: learning, then the wait with the countdown in #next (in #bar); the console does not move
      p.send({e: 'phase', ph: 'learn'}, T + 2000);
      p.send({e: 'sol_end', s: 9, stage: 3}, T + 2500);
      p.send({e: 'phase', ph: 'idle', next: iso(Date.parse(SRV) + 120_000)}, T + 3000);
      for (let t = T + 3000; t <= T + 8000; t += 500) {
        p.advance(t); p.resize(vw, vh, dpr);
        assert.strictEqual(consoleSize(p), size, `${tag}: the console moved at +${t - T} ms`);
      }
      p.advance(T + 8500);
      assert.ok(p.el('next').textContent.length > 0, tag);
      assert.ok(p.el('bar').classList.contains('waitnext'), tag);
      // the next sol: the countdown goes, the size stays
      const s2 = [SOL(10), POSES(1, 10), CTICK(0, {s: 10})];
      s2.forEach((e, i) => p.send(e, T + 9000 + i));
      p.advance(T + 10_500); p.resize(vw, vh, dpr); p.advance(T + 10_600);
      assert.strictEqual(p.el('next').textContent, '', tag);
      assert.ok(!p.el('bar').classList.contains('waitnext'), tag);
      assert.strictEqual(consoleSize(p), size, tag);
      // portrait: the stage and the next sol go back to the second row (not sticky); landscape again: back in the status row
      p.resize(vh, vw, dpr); p.advance(p.t + 600); p.advance(p.t + 10);
      assert.strictEqual(p.html.dataset.mode, 'panels', tag);
      assert.strictEqual(p.el('next').parentNode, p.el('bar2'), tag);
      assert.strictEqual(p.el('stagebar').parentNode, p.el('bar2'), tag);
      p.resize(vw, vh, dpr); p.advance(p.t + 600); p.advance(p.t + 10);
      assert.strictEqual(p.el('next').parentNode, p.el('bar'), tag);
      assert.strictEqual(consoleSize(p), size, tag);
      assert.deepStrictEqual(p.errors, []);
    }
  }
});

test('VERIF-rc14 I3: « SOL d/n » of Details is the sol number in year 1 (counted from 0 like the sols); year 2 starts at SOL 0', () => {
  const S = Live.newView();
  const at = (sol) => { Live.applyEvent(S, {e: 'sol', s: sol, stage: 0, stage_name: 'AWAKENING', now: SRV, tick_ms: 600, cam: {w: 8, h: 6, D: 1},
    season_sols: 150, sun: {lever: 6, coucher: 18}}, 0); return S; };
  for (let sol = 0; sol < 600; sol += 13) {
    const m = /^YEAR 1 · SOL (\d+)\/600 · /.exec(Live.seasonLine(at(sol), opts('en')));
    assert.ok(m && +m[1] === sol, `sol ${sol}: ${Live.seasonLine(S, opts('en'))}`);
  }
  assert.strictEqual(Live.seasonLine(at(0), opts('en')), 'YEAR 1 · SOL 0/600 · DAYLIGHT 12.0 h');
  assert.strictEqual(Live.seasonLine(at(208), opts('fr')), 'ANNÉE 1 · SOL 208/600 · DURÉE DU JOUR 12,0 h');
  assert.strictEqual(Live.seasonLine(at(599), opts('en')), 'YEAR 1 · SOL 599/600 · DAYLIGHT 12.0 h');
  assert.strictEqual(Live.seasonLine(at(600), opts('en')), 'YEAR 2 · SOL 0/600 · DAYLIGHT 12.0 h');
  assert.strictEqual(Live.seasonLine(at(608), opts('fr')), 'ANNÉE 2 · SOL 8/600 · DURÉE DU JOUR 12,0 h');
  // the help text says how it is counted, in both languages
  assert.ok(/from 0 like the sols/.test(I18N['d.seasonhelp'].en) && /à partir de 0 comme les sols/.test(I18N['d.seasonhelp'].fr));
});

test('VERIF-rc14 M1: the dark outline of « SUN / SOLEIL » stays inside the CAM-1 frame (row 224 intact), FR and EN', () => {
  const ST = states();
  let n = 0;
  for (const [name, S] of Object.entries(ST)) {
    if (!(S.stage >= 3 && S.sun && S.sun[0] > 0 && S.mode !== 'SLEEP' && S.cam)) continue;
    for (const lang of ['en', 'fr']) {
      const b = new Uint8Array(640 * 360);
      Live.renderLive(b, S, null, opts(lang));
      const frame = b[224 * 640 + 200];
      for (let x = 7; x <= 328; x++) assert.strictEqual(b[224 * 640 + x], frame, `${name} ${lang}: frame row 224 erased at x ${x}`);
      const sun = tx(lang, 'c.cam.sun');
      if (findText(b, sun, Con.MARK, [8, 200, 80, 224])) n++;
    }
  }
  assert.ok(n >= 8, `${n} renders with the SUN label`);
});

test('VERIF-rc14 M2: a close by the browser right after opening never reopens the panel (EF-87)', async () => {
  for (const lang of ['en', 'fr']) {
    const p = await makePage({t0: T, lang, keepBuffer: true});
    p.open();
    const s = [SOL(), POSES(101), CTICK(96), TICK(100)];
    p.send(HELLO(s)); s.forEach((e) => p.send(e)); p.advance(T + 1000);
    // ticks every 100 ms, the limiter draws at most every 500 ms; the click comes 200 ms after a draw, so a draw falls inside the 350 ms
    // guard that delays the route change of the close (asserted below; measured: 100 ms after the opening, out/page-v2/fix15/probe_m2.js)
    let tk = 101;
    const feedTo = (t) => { for (; T + 1000 + 100 * (tk - 100) <= t; tk++) p.send(tk % 8 === 0 ? CTICK(tk) : TICK(tk), T + 1000 + 100 * (tk - 100)); p.advance(t); };
    feedTo(T + 3000);
    const last = p.draws[p.draws.length - 1].t;
    feedTo(last + 200);
    p.click('hit-cam'); feedTo(p.t + 10);
    assert.strictEqual(p.el('ov').open, true);
    const opened = p.dialogLog[0].t;
    p.el('ov').open = false; p.el('ov').dispatch('close');                  // the browser closed it (no cancel event: Chrome's 2nd Esc)
    feedTo(opened + 4000);
    assert.ok(p.draws.some((d) => d.t > opened && d.t < opened + 350), 'no draw inside the guard: the case is not exercised');
    assert.deepStrictEqual(p.dialogLog.map((d) => d.op), ['open'], JSON.stringify(p.dialogLog.map((d) => [d.op, d.t - opened])));
    assert.strictEqual(p.el('ov').open, false);
    assert.strictEqual(p.location.hash, `#${lang}/live`);
    // and the visitor can open it again
    p.click('hit-cam'); feedTo(p.t + 400);
    assert.strictEqual(p.el('ov').open, true);
    assert.deepStrictEqual(p.errors, []);
  }
});

test('VERIF-rc14 M4: the waiting card draws the next sol only while it is ahead; redrawn once it passes, without a state change', async () => {
  for (const lang of ['en', 'fr']) {
    const p = await makePage({t0: T, lang, keepBuffer: true});
    p.open(); p.send(HELLO([], {engine_silent_s: 0}));
    const next = Date.parse(SRV) + 30_000;
    p.send({e: 'phase', ph: 'idle', next: iso(next)}, T + 10);
    p.advance(T + 600);
    const nxt = tx(lang, 'c.wait.next', {hh: '10', mm: '00', ss: '30'});
    assert.ok(findText(p.buffer, nxt, Con.MARK, [8, 24, 328, 224]), nxt);
    for (let t = T + 5000; t <= T + 45_000; t += 5000) p.send({e: 'status', phase: 'idle', h: 'ok'}, t);    // the engine is alive
    p.advance(T + 45_000);
    assert.strictEqual(p.el('state').dataset.state, 'LIVE');
    assert.ok(!findText(p.buffer, nxt, Con.MARK, [8, 24, 328, 224]), 'a past time is still drawn');
    assert.ok(findText(p.buffer, tx(lang, 'c.wait.idle'), Con.MARK, [8, 24, 328, 224]));
    assert.strictEqual(p.el('next').textContent, '');
    const w = p.waits.filter((x) => x.t > T + 600);
    assert.ok(w.length === 1 && w[0].t >= T + 30_000 && w[0].t <= T + 32_000, JSON.stringify(w.map((x) => x.t - T)));
    assert.deepStrictEqual(p.errors, []);
  }
  // the renderer alone: the page's clock decides (o.now), before and after the time
  const S = Live.newView();
  Live.applyEvent(S, {e: 'phase', ph: 'idle', next: '2026-11-13T12:15:00Z'}, 0);
  const b = new Uint8Array(640 * 360), nxt = tx('fr', 'c.wait.next', {hh: '12', mm: '15', ss: '00'});
  Live.renderWaiting(b, S, opts('fr', {now: TEST_NOW}));
  assert.ok(findText(b, nxt, Con.MARK, [8, 24, 328, 224]));
  Live.renderWaiting(b, S, opts('fr', {now: Date.parse('2026-11-13T12:15:01Z')}));
  assert.ok(!findText(b, nxt, Con.MARK, [8, 24, 328, 224]));
});

test('VERIF-rc14 M5: a stacked panel wider than the screen starts at the left edge (`safe center`), never cut on the left', () => {
  const r = rule('#panels');
  assert.ok(/align-items: center; align-items: safe center;/.test(r), r);     // the plain value first: kept where `safe` is unknown
  assert.ok(/align-items: center; align-items: safe center;/.test(rule('.group.split')));
});
