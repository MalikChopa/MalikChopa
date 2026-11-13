'use strict';
// Runs the REAL page (pages/live/route.js, console.js, live.js, layout.js and app.js, unchanged) in a node `vm` context, without a
// browser (RC12-verif I1: the page tests must go through app.js). Fakes: DOM elements (text, attributes, classList, style, listeners,
// focus, canvas contexts that record putImageData, the <dialog>, the parents of the status-bar spans), window (size, devicePixelRatio, listeners, matchMedia,
// requestAnimationFrame), history and location.hash, clock and timers (Date.now, setTimeout, setInterval), fetch and EventSource.
// Used by tests/page/*.test.js and tests/page/bench_visits.js (not a *.test.js file).
//
//   const page = await makePage({t0, lang: 'en' | 'fr', hash, vw, vh, dpr, keepBuffer: true});
//   page.click(id), page.key(id, key), page.navigate(hash), page.back(), page.resize(vw, vh, dpr)   (user actions, page v2)
//   page.puts (every putImageData: {t, id, args}), page.waits (waiting-card draws), page.history (entries, idx), page.html
//   page.open();                       // es.onopen of the current stream
//   page.send(ev, t);                  // one SSE event received at page time t (ms): the real listeners of app.js run
//   page.error(t);                     // es.onerror (the visitor's own link broke)
//   page.advance(t);                   // runs the page's timers due up to t (draw limiter, text lines every second, reconnection)
//   page.S, page.link                  // the page's own state objects (captured when app.js creates them)
//   page.el(id).textContent            // the DOM as app.js wrote it; page.el(id).writtenAt = page time of the last write
//   page.draws, page.lastDraw          // every canvas draw (app.js draw -> renderLive): {t, key, title, sol, camT, bare}
//   page.buffer                        // palette indexes of the last draw (keepBuffer), to look for drawn texts
//   page.errors                        // exceptions in the page (also those app.js swallows), timers included
// Intro cinematic (consigne 52): `intro: true` also runs pages/live/intro.js right after app.js, as index.html does; fakes: the
// <dialog id="intro"> (page.introLog), the <video id="intro-v"> (page.videoLog; `autoplay`: 'ok' | 'refuse' | 'pending', mutable as
// page.autoplay; `canPlay: false`), localStorage (`storage`: an object from makeStorage(), 'throw' = the getter throws, 'broken' =
// its methods throw; absent = no localStorage at all), navigator.connection.saveData (`saveData: true`), `introNoDialog: true`,
// `failFiles: true` (assets.json cannot be read: app.js shows its error and opens no stream).
// The intro elements start `hidden` as written in index.html. page.ops orders every stream opening and video call.
const vm = require('vm'), fs = require('fs'), path = require('path');
const {PAGE, assets} = require('./helpers.js');

const FILES = ['console.js', 'live.js', 'app.js', 'route.js', 'layout.js', 'intro.js'];
const SCRIPTS = FILES.map((f) => new vm.Script(fs.readFileSync(path.join(PAGE, f), 'utf8'), {filename: f}));
const I18N = JSON.parse(fs.readFileSync(path.join(PAGE, 'i18n.json'), 'utf8'));
// the intro elements written `hidden` in index.html (the header button, « Play the intro », « Sound off »)
const INTRO_HIDDEN = new Set([...fs.readFileSync(path.join(PAGE, 'index.html'), 'utf8').matchAll(/<[^>]*\bid="(intro[a-z-]*)"[^>]*>/g)]
  .filter((m) => /\shidden[\s>]/.test(m[0])).map((m) => m[1]));
function makeStorage(init) {
  const data = Object.assign({}, init || {}), log = [];
  return {data, log, getItem(k) { log.push(['get', k]); return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
          setItem(k, v) { log.push(['set', k, String(v)]); data[k] = String(v); }};
}
// secpage: stateRaw has the shape build_page.py writes (app.js reads only https://raw.githubusercontent.com/<owner>/<repo>/state)
const CONFIG = {stream: 'https://stream.test', stateRaw: 'https://raw.githubusercontent.com/o/r/state'};
// the smallest well-formed GIF header (a still is drawn from the published console.gif through createImageBitmap, faked below)
const GIF = Uint8Array.from([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 1, 0, 1, 0, 0, 0, 0, 0x3b]);

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
                introLog: [], videoLog: [], autoplay: o.autoplay || 'ok', pendingPlays: [],
                link: null, Live: null, puts: [], waits: [], dialogLog: [], ops: 0,
                // secpage: the body of /now.json (streams_full), of status.json, the bytes of console.gif, every fetch and every still drawn
                nowBody: {}, statusBody: '{}', gifBytes: GIF, gifStatus: 200, fetches: [], bitmaps: [], stills: []};
  const timers = [];
  let seq = 0;
  const els = {};
  function listeners(obj) {
    obj._l = {};
    obj.addEventListener = (n, f) => { (obj._l[n] = obj._l[n] || []).push(f); };
    obj.removeEventListener = (n, f) => { obj._l[n] = (obj._l[n] || []).filter((g) => g !== f); };
    obj.dispatch = (n, ev) => { const e = Object.assign({type: n, target: obj, defaultPrevented: false, preventDefault() { e.defaultPrevented = true; }}, ev || {});
      (obj._l[n] || []).slice().forEach((f) => { try { f.call(obj, e); } catch (x) { page.errors.push('listener ' + n + ': ' + x.message); } }); return e; };
    return obj;
  }
  function classList() {
    const set = new Set();
    return {add(c) { set.add(c); }, remove(c) { set.delete(c); }, contains(c) { return set.has(c); }, toggle(c, on) { if (on === undefined ? !set.has(c) : on) set.add(c); else set.delete(c); },
            toString() { return [...set].join(' '); }};
  }
  const docEl = listeners({lang: '', dataset: {}, classList: classList(), requestFullscreen: null});
  // the parents of index.html that app.js may change (VERIF-rc14 I2: the stage and the next sol move between #bar and #bar2)
  const PARENT = {state: 'bar', line: 'bar', age: 'bar', noimg: 'bar', stagebar: 'bar2', next: 'bar2'};
  function el(id) {
    if (!els[id]) {
      let text = '';
      const e = listeners({id, hidden: INTRO_HIDDEN.has(id), dataset: {}, href: '', src: '', attrs: {}, writtenAt: null, writes: 0, style: {}, classList: classList(),
                 width: 0, height: 0, clientWidth: 0, parentNode: null, children: [],
                 appendChild(c) { if (c.parentNode) c.parentNode.children = c.parentNode.children.filter((x) => x !== c); c.parentNode = e; e.children.push(c); return c; },
                 setAttribute(k, v) { e.attrs[k] = String(v); if (k === 'src') e.src = String(v); }, getAttribute(k) { return k in e.attrs ? e.attrs[k] : null; },
                 removeAttribute(k) { delete e.attrs[k]; if (k === 'src') e.src = ''; }, focus() { page.focused = id; docFake.activeElement = e; },
                 get textContent() { return text; },
                 set textContent(v) { text = String(v); e.writtenAt = page.t; e.writes++; if (e.onWrite) e.onWrite(text); }});
      e.getContext = () => ({
        createImageData: (w, h) => ({width: w, height: h, data: new Uint8ClampedArray(w * h * 4)}),
        putImageData: (...args) => { page.puts.push({t: page.t, n: ++page.ops, id, args: args.slice(1)}); },
        drawImage: (bm, x, y) => { page.stills.push({t: page.t, id, bm, x, y}); }
      });
      if (id === 'ov') {
        e.open = false;
        e.showModal = () => { if (e.open) throw new Error('showModal on an open dialog'); e.open = true; page.dialogLog.push({t: page.t, n: ++page.ops, op: 'open'}); };
        e.close = () => { if (!e.open) return; e.open = false; page.dialogLog.push({t: page.t, n: ++page.ops, op: 'close'}); addTimer(() => e.dispatch('close'), 0, false); };
        if (o.noDialog) { delete e.showModal; }
      }
      if (id === 'intro') {
        e.open = false;
        e.showModal = () => { if (e.open) throw new Error('showModal on an open intro'); e.open = true; page.introLog.push({t: page.t, n: ++page.ops, op: 'open'}); };
        e.close = () => { if (!e.open) return; e.open = false; page.introLog.push({t: page.t, n: ++page.ops, op: 'close'}); addTimer(() => e.dispatch('close'), 0, false); };
        if (o.introNoDialog) delete e.showModal;
      }
      if (id === 'intro-v') {         // the <video>: muted attribute in index.html, preload none, no src until intro.js sets it
        Object.assign(e, {muted: true, paused: true,
          canPlayType: (t) => { page.videoLog.push({t: page.t, n: ++page.ops, op: 'canPlayType', type: t}); return o.canPlay === false ? '' : 'probably'; },
          play: () => {
            page.videoLog.push({t: page.t, n: ++page.ops, op: 'play', src: e.getAttribute('src'), muted: e.muted});
            if (page.autoplay === 'pending') { const q = {then(f, r) { page.pendingPlays.push({f, r}); return q; }}; return q; }   // settled later by the test
            if (page.autoplay === 'refuse') return settled(false, new Error('NotAllowedError'));
            e.paused = false; addTimer(() => { if (!e.paused) e.dispatch('playing'); }, 0, false);
            return settled(true, undefined);
          },
          pause: () => { e.paused = true; page.videoLog.push({t: page.t, n: ++page.ops, op: 'pause'}); },
          load: () => { e.paused = true; page.videoLog.push({t: page.t, n: ++page.ops, op: 'load', src: e.getAttribute('src')}); }});
      }
      els[id] = e;
      if (PARENT[id]) el(PARENT[id]).appendChild(e);
    }
    return els[id];
  }
  page.el = el;
  page.html = docEl;
  function addTimer(fn, ms, every) {
    const id = ++seq;
    timers.push({id, at: page.t + Math.max(0, ms || 0), fn, every: every ? Math.max(1, ms) : 0});
    return id;
  }
  function clearTimer(id) { const i = timers.findIndex((x) => x.id === id); if (i >= 0) timers.splice(i, 1); }
  function fetchFake(url) {
    page.fetches.push({t: page.t, url});
    if (url === 'assets.json') return o.failFiles ? settled(false, new Error('network')) : settled(true, {status: 200, json: () => assets});
    if (url === 'config.json') return settled(true, {status: 200, json: () => Object.assign({}, CONFIG, o.config || {})});
    if (url === 'i18n.json') return settled(true, {status: 200, json: () => I18N});
    if (url === CONFIG.stream + '/now.json') {
      if (page.nowStatus === 'network') return settled(false, new Error('network'));
      const body = page.nowBody;
      return settled(true, {status: page.nowStatus, ok: page.nowStatus >= 200 && page.nowStatus < 300, json: () => body,
                            text: () => settled(true, typeof body === 'string' ? body : JSON.stringify(body))});
    }
    if (url === CONFIG.stateRaw + '/status.json') {
      const body = page.statusBody;
      return settled(true, {status: 200, ok: true, json: () => JSON.parse(body), text: () => settled(true, body)});
    }
    if (url === CONFIG.stateRaw + '/console.gif') {
      const b = page.gifBytes, st = page.gifStatus;
      return settled(true, {status: st, ok: st >= 200 && st < 300, arrayBuffer: () => settled(true, b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength))});
    }
    return settled(false, new Error('unknown url ' + url));
  }
  class EventSourceFake {
    constructor(url) { this.url = url; this.listeners = {}; this.closed = false; this.onopen = null; this.onerror = null; this.t = page.t; this.n = ++page.ops; page.streams.push(this); page.es = this; }
    addEventListener(n, f) { (this.listeners[n] = this.listeners[n] || []).push(f); }
    close() { this.closed = true; }
  }
  const loc = {hash: o.hash !== undefined ? o.hash : (o.lang === 'fr' ? '#fr' : '#en'), reload() { page.errors.push('location.reload called'); }};
  const docFake = listeners({getElementById: el, documentElement: docEl, title: '', hidden: false, activeElement: null, fullscreenEnabled: false});
  const win = listeners({});
  const hist = {entries: [{state: null, hash: loc.hash}], idx: 0,
    get state() { return hist.entries[hist.idx].state; },
    pushState(st, _t, h) { hist.entries.splice(hist.idx + 1); hist.entries.push({state: st === null || st === undefined ? null : JSON.parse(JSON.stringify(st)), hash: h}); hist.idx++; loc.hash = h; },
    replaceState(st, _t, h) { hist.entries[hist.idx] = {state: st === null || st === undefined ? null : JSON.parse(JSON.stringify(st)), hash: h}; loc.hash = h; },
    back() {
      if (hist.idx === 0) return;
      hist.idx--; loc.hash = hist.entries[hist.idx].hash;
      addTimer(() => { win.dispatch('popstate', {state: hist.state}); win.dispatch('hashchange'); }, 0, false);
    }};
  page.history = hist; page.location = loc; page.win = win; page.document = docFake;
  const ctx = newContext({
    location: loc, history: hist,
    navigator: Object.assign({language: o.lang === 'fr' ? 'fr-FR' : 'en-US'}, o.saveData ? {connection: {saveData: true}} : {}),
    document: docFake,
    innerWidth: o.vw || 1280, innerHeight: o.vh || 800, devicePixelRatio: o.dpr || 1, scrollY: 0, scrollTo() {},
    addEventListener: win.addEventListener, removeEventListener: win.removeEventListener,
    matchMedia: (q) => ({matches: !!(o.reducedMotion && /reduce/.test(q)), media: q}),
    requestAnimationFrame: (f) => addTimer(f, 0, false),
    fetch: fetchFake, EventSource: EventSourceFake, AbortController, atob,
    Blob: class { constructor(parts, opt) { this.parts = parts; this.type = opt && opt.type; } },
    createImageBitmap: (blob) => { const bm = {width: o.bitmapW || 640, height: o.bitmapH || 360, blob, closed: false, close() { this.closed = true; }};
                                   page.bitmaps.push(bm); return settled(true, bm); },
    setTimeout: (f, ms) => addTimer(f, ms, false), clearTimeout: clearTimer,
    setInterval: (f, ms) => addTimer(f, ms, true), clearInterval: clearTimer,
    console: {log() {}, error() {}, warn() {}},
    __now: () => page.t
  });
  page.ctx = ctx;
  if (o.storage === 'throw') Object.defineProperty(ctx, 'localStorage', {get() { throw new Error('SecurityError: storage disabled'); }, configurable: true});
  else if (o.storage === 'broken') ctx.localStorage = {getItem() { throw new Error('QuotaExceededError'); }, setItem() { throw new Error('QuotaExceededError'); }};
  else if (o.storage) ctx.localStorage = o.storage;
  vm.runInContext('Date.now = function () { return __now(); };', ctx);
  SCRIPTS[3].runInContext(ctx);                     // route.js (in <head>): lang, tab and mode on <html>
  if (o.shared) {                                   // app.js's canvas buffer: same realm as the drawing code (measured faster)
    const sh = shared();
    ctx.Sol0Console = sh.Con; ctx.Sol0Live = Object.assign({}, sh.Live); ctx.Uint8Array = sh.Uint8Array;
  }
  else { SCRIPTS[0].runInContext(ctx); SCRIPTS[1].runInContext(ctx); }
  SCRIPTS[4].runInContext(ctx);                     // layout.js
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
  Live.renderLive = function (buf, S, link, ro) {
    const d = {t: page.t, key: viewKey(real, S), title: real.pauseTitle(S), sol: S.sol, camT: S.cam ? S.camT : null, bare: !S.hasTick || !S.camDims,
               lang: ro && ro.lang, label: ro && ro.label};
    page.lastDraw = d;
    if (o.keepDraws !== false) page.draws.push(d);
    if (page.drawCount++ % every === 0) {
      if (o.boxes && ro) ro.boxes = (page.boxes = []);
      try { real.renderLive(buf, S, link, ro); } catch (e) { page.errors.push('renderLive: ' + e.message); throw e; }
      if (o.keepBuffer) page.buffer = Uint8Array.from(buf);
    }
    return buf;
  };
  Live.renderWaiting = function (buf, S, ro) {
    page.waits.push({t: page.t, key: real.waitKey(S, ro && ro.label), lang: ro && ro.lang, next: S.nextUtc});
    try { real.renderWaiting(buf, S, ro); } catch (e) { page.errors.push('renderWaiting: ' + e.message); throw e; }
    if (o.keepBuffer) page.buffer = Uint8Array.from(buf);
    return buf;
  };
  page.viewKey = () => viewKey(real, page.S);
  SCRIPTS[2].runInContext(ctx);
  if (o.intro) SCRIPTS[5].runInContext(ctx);        // intro.js, the next <script> of index.html (before app.js's files arrive)
  page.video = (name) => el('intro-v').dispatch(name);
  await new Promise((r) => setImmediate(r));          // Promise.all(assets, config) -> init -> connect()
  if (!page.es && !o.failFiles) throw new Error('app.js did not open the stream: ' + el('state').textContent);

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
  // user actions (page v2)
  page.click = (id, ev) => el(id).dispatch('click', ev);
  page.key = (id, key) => el(id).dispatch('keydown', {key});
  page.navigate = (hash) => {          // a click on a link <a href="#..."> (new history entry, then hashchange)
    hist.entries.splice(hist.idx + 1); hist.entries.push({state: null, hash}); hist.idx++; loc.hash = hash;
    addTimer(() => win.dispatch('hashchange'), 0, false);
  };
  page.back = () => hist.back();
  page.resize = (vw, vh, dpr) => { ctx.innerWidth = vw; ctx.innerHeight = vh; if (dpr) ctx.devicePixelRatio = dpr; win.dispatch('resize'); };
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

module.exports = {makePage, viewKey, ageSeconds, CONFIG, makeStorage, INTRO_HIDDEN};
