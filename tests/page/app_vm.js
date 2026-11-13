'use strict';
// Runs the REAL page (pages/live/console.js, live.js and app.js, unchanged) in a node `vm` context, without a browser (RC12-verif I1:
// the page tests must go through app.js). Fakes: DOM elements, clock and timers (Date.now, setTimeout, setInterval), fetch and
// EventSource. Used by tests/page/app.test.js and tests/page/bench_visits.js (not a *.test.js file).
//
//   const page = await makePage({t0, lang: 'en' | 'fr', keepBuffer: true});
//   page.open();                       // es.onopen of the current stream
//   page.send(ev, t);                  // one SSE event received at page time t (ms): the real listeners of app.js run
//   page.error(t);                     // es.onerror (the visitor's own link broke)
//   page.advance(t);                   // runs the page's timers due up to t (draw limiter, text lines every second, reconnection)
//   page.S, page.link                  // the page's own state objects (captured when app.js creates them)
//   page.el(id).textContent            // the DOM as app.js wrote it; page.el(id).writtenAt = page time of the last write
//   page.draws, page.lastDraw          // every canvas draw (app.js draw -> renderLive): {t, key, title, sol, camT, bare}
//   page.buffer                        // palette indexes of the last draw (keepBuffer), to look for drawn texts
//   page.errors                        // exceptions in the page (also those app.js swallows), timers included
const vm = require('vm'), fs = require('fs'), path = require('path');
const {PAGE, assets} = require('./helpers.js');

const SCRIPTS = ['console.js', 'live.js', 'app.js'].map((f) => new vm.Script(fs.readFileSync(path.join(PAGE, f), 'utf8'), {filename: f}));
const CONFIG = {stream: 'https://stream.test', stateRaw: 'https://state.test'};

// `shared: true` (bench, for time): console.js and live.js run once in a context shared by every page (measured on node 24: page
// start 0.3 ms instead of 2.1 ms, draw 1.04 ms instead of 1.2 ms). Equivalent for the page: their only module state is set at
// start-up with the same values for every page (console.js init(assets), live.js setConsole); app.js stays one per page.
// A context whose global is an ordinary object when Node allows it (vm.constants.DONT_CONTEXTIFY, Node >= 22.8): a contextified
// global answers every global lookup (Math, Uint8Array...) through an interceptor, ten times slower in the drawing loops.
function newContext(props) {
  let g;
  if (vm.constants && vm.constants.DONT_CONTEXTIFY !== undefined) { g = vm.createContext(vm.constants.DONT_CONTEXTIFY); Object.assign(g, props); }
  else { g = Object.assign({}, props); vm.createContext(g); }
  g.self = g;
  return g;
}
let SHARED = null;
function shared() {
  if (SHARED) return SHARED;
  const c = newContext({atob, console: {log() {}, error() {}, warn() {}}});
  SCRIPTS[0].runInContext(c);
  SCRIPTS[1].runInContext(c);
  c.Sol0Console.init(assets);
  const Con = Object.assign({}, c.Sol0Console);
  Con.init = function () { return Con; };            // already initialised with the same assets.json
  SHARED = {Live: c.Sol0Live, Con, Uint8Array: vm.runInContext('Uint8Array', c)};
  return SHARED;
}

// A thenable that runs its callbacks at once: app.js chains fetch().then().catch() and the fake network answers synchronously.
function settled(ok, val) {
  const p = {
    then(f, r) {
      const h = ok ? f : r;
      if (typeof h !== 'function') return p;
      try { const v = h(val); return (v && typeof v.then === 'function') ? v : settled(true, v); } catch (e) { return settled(false, e); }
    },
    catch(r) { return p.then(undefined, r); }
  };
  return p;
}

// The state the canvas shows (same function at draw time and at probe time): sol number, image tick, bare view, pause title.
function viewKey(Live, S) {
  if (!Live.canDraw(S)) return null;
  return JSON.stringify([typeof S.sol === 'number' ? S.sol : null, S.cam ? S.camT : null, !S.hasTick || !S.camDims, Live.pauseTitle(S)]);
}

async function makePage(o) {
  o = o || {};
  const page = {t: o.t0 || 0, errors: [], draws: [], lastDraw: null, buffer: null, streams: [], es: null, nowStatus: 200, S: null,
                link: null, Live: null};
  const timers = [];
  let seq = 0;
  const els = {};
  function el(id) {
    if (!els[id]) {
      let text = '';
      const e = {id, hidden: false, dataset: {}, href: '', src: '', attrs: {}, writtenAt: null, writes: 0,
                 setAttribute(k, v) { e.attrs[k] = String(v); }, addEventListener() {},
                 get textContent() { return text; },
                 set textContent(v) { text = String(v); e.writtenAt = page.t; e.writes++; if (e.onWrite) e.onWrite(text); }};
      if (id === 'c') {
        e.getContext = () => ({
          createImageData: (w, h) => ({width: w, height: h, data: new Uint8ClampedArray(w * h * 4)}),
          putImageData: () => {}
        });
      }
      els[id] = e;
    }
    return els[id];
  }
  page.el = el;
  function addTimer(fn, ms, every) {
    const id = ++seq;
    timers.push({id, at: page.t + Math.max(0, ms || 0), fn, every: every ? Math.max(1, ms) : 0});
    return id;
  }
  function clearTimer(id) { const i = timers.findIndex((x) => x.id === id); if (i >= 0) timers.splice(i, 1); }
  function fetchFake(url) {
    if (url === 'assets.json') return settled(true, {status: 200, json: () => assets});
    if (url === 'config.json') return settled(true, {status: 200, json: () => CONFIG});
    if (url === CONFIG.stream + '/now.json') {
      if (page.nowStatus === 'network') return settled(false, new Error('network'));
      return settled(true, {status: page.nowStatus, json: () => ({})});
    }
    if (url === CONFIG.stateRaw + '/status.json') return settled(true, {status: 200, json: () => ({})});
    return settled(false, new Error('unknown url ' + url));
  }
  class EventSourceFake {
    constructor(url) { this.url = url; this.listeners = {}; this.closed = false; this.onopen = null; this.onerror = null; page.streams.push(this); page.es = this; }
    addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); }
    close() { this.closed = true; }
  }
  const ctx = newContext({
    location: {hash: o.lang === 'fr' ? '#fr' : '#en', reload() {}},
    navigator: {language: o.lang === 'fr' ? 'fr-FR' : 'en-US'},
    document: {getElementById: el, documentElement: {lang: ''}, title: ''},
    fetch: fetchFake, EventSource: EventSourceFake, AbortController, atob,
    setTimeout: (f, ms) => addTimer(f, ms, false), clearTimeout: clearTimer,
    setInterval: (f, ms) => addTimer(f, ms, true), clearInterval: clearTimer,
    console: {log() {}, error() {}, warn() {}},
    __now: () => page.t
  });
  vm.runInContext('Date.now = function () { return __now(); };', ctx);
  if (o.shared) {                                   // app.js's canvas buffer: same realm as the drawing code (measured faster)
    const sh = shared();
    ctx.Sol0Console = sh.Con; ctx.Sol0Live = Object.assign({}, sh.Live); ctx.Uint8Array = sh.Uint8Array;
  }
  else { SCRIPTS[0].runInContext(ctx); SCRIPTS[1].runInContext(ctx); }
  const Live = ctx.Sol0Live;
  page.Live = Live;
  // capture the page's own state objects, and record every exception of the page (app.js swallows those of a line)
  const real = Object.assign({}, Live);
  Object.keys(real).forEach((k) => {
    if (typeof real[k] !== 'function') return;
    Live[k] = function () {
      try { return real[k].apply(this, arguments); } catch (e) { page.errors.push(k + ': ' + e.message); throw e; }
    };
  });
  Live.newView = function () { const S = real.newView(); if (!page.S) page.S = S; return S; };
  Live.makeLink = function () { const L = real.makeLink(); if (!page.link) page.link = L; return L; };
  // `renderEvery` n > 1 (bench, for time): the real renderLive runs on one draw in n; the key of every draw is recorded
  const every = o.renderEvery || 1;
  page.drawCount = 0;
  Live.renderLive = function (buf, S, link) {
    const d = {t: page.t, key: viewKey(real, S), title: real.pauseTitle(S), sol: S.sol, camT: S.cam ? S.camT : null, bare: !S.hasTick || !S.camDims};
    page.lastDraw = d;
    if (o.keepDraws !== false) page.draws.push(d);
    if (page.drawCount++ % every === 0) {
      try { real.renderLive(buf, S, link); } catch (e) { page.errors.push('renderLive: ' + e.message); throw e; }
      if (o.keepBuffer) page.buffer = Uint8Array.from(buf);
    }
    return buf;
  };
  page.viewKey = () => viewKey(real, page.S);
  SCRIPTS[2].runInContext(ctx);
  await new Promise((r) => setImmediate(r));          // Promise.all(assets, config) -> init -> connect()
  if (!page.es) throw new Error('app.js did not open the stream: ' + el('state').textContent);

  page.advance = (t) => {
    for (;;) {
      let next = null;
      for (const x of timers) if (x.at <= t && (next === null || x.at < next.at || (x.at === next.at && x.id < next.id))) next = x;
      if (next === null) break;
      page.t = Math.max(page.t, next.at);
      if (next.every) next.at += next.every; else clearTimer(next.id);
      try { next.fn(); } catch (e) { page.errors.push('timer: ' + e.message); }
    }
    page.t = Math.max(page.t, t);
  };
  page.open = (t) => { if (t !== undefined) page.advance(t); if (page.es && page.es.onopen) page.es.onopen(); };
  page.error = (t) => { if (t !== undefined) page.advance(t); if (page.es && page.es.onerror) page.es.onerror(); };
  page.sendRaw = (name, data, t) => {
    if (t !== undefined) page.advance(t);
    const es = page.es;
    if (!es || es.closed) { page.errors.push('event on a closed stream: ' + name); return; }
    (es.listeners[name] || []).forEach((f) => f({data}));
  };
  page.send = (ev, t) => page.sendRaw(ev.e, JSON.stringify(ev), t);
  return page;
}

// What a probe of a test or of the bench reads in the DOM: the banner state, its text, the age line in seconds (parsed), the line.
function ageSeconds(txt) {
  const m = /:\s*(?:(\d+) h (\d+) min|(\d+) min (\d+) s|(\d+) s)/.exec(txt || '');
  if (!m) return null;
  if (m[1] !== undefined) return {s: 3600 * +m[1] + 60 * +m[2], res: 60};
  if (m[3] !== undefined) return {s: 60 * +m[3] + +m[4], res: 1};
  return {s: +m[5], res: 1};
}

module.exports = {makePage, viewKey, ageSeconds, CONFIG};
