'use strict';
// Bench helper (not a *.test.js): runs the REAL page (pages/live/app.js with live.js and console.js, in a node `vm` context, see
// app_vm.js) for each visitor, feeds it the events the visitor RECEIVED from the real web.py at their receive times, runs the page's
// own timers (draw limiter, text lines every second, reconnection) and reports what the page shows at each probe time.
// Used by tests/live/test_state_bench.py.  (live-rc12 used a copy of the app.js glue here; RC12-verif I1 showed the copy hid a bug.)
// Usage: node bench_visits.js <in.json> <out.json>
//   in  = {visitors: [{id, lang, events: [[recv_ms, event], ...], probes: [ms, ...]}]}   (page clock = bench clock, ms)
//         two pseudo-events model a cut of the visitor's own link (brief 45): {e: '__cut'} = es.onerror of the page's stream (app.js
//         closes it, probes /now.json and opens a new stream 5 s later), {e: '__open'} = es.onopen of that new stream; the new
//         hello and snapshot follow as real events.
//   out = {visitors: [{id, errors: [...], probes: [[...FIELDS], ...]}]}
//         logic fields (from the page's own state objects S and link): label, age (Live.dataAgeS), hasTick, tickS, tickT (last tick
//         event received), phase, nextLeft, holdSinceMs, sol, holdEn, silentEn, camT, hasImage, resumeEn, imgS, imgT (last tick event
//         with `cam`: the bench's own record of which tick produced the image, independent of the page);
//         DOM and canvas fields (what app.js really wrote and drew): domState (#state data-state), domStateText, domAge (#age in
//         seconds), domAgeRes (1, or 60 when the text shows hours), domAgeAt (page time of the last #age write), ageKey (view key
//         when #age was written), lineSol (sol number at the start of #line), keyNow (view key of S now), keyAt (when it last
//         changed), canSince (since when the page may show something), drawKey, drawAt, drawTitle (the last canvas draw),
//         stateAt (page time of the last banner write) and stateWant (the page state Live.label at that write).
//         view key = [sol, image tick or null, bare view, pause title] (app_vm.js viewKey).
const {fs} = require('./helpers.js');
const {makePage, ageSeconds} = require('./app_vm.js');
const RENDER_EVERY = 1;           // the real renderLive runs on every draw of app.js
const FIELDS = ['t', 'label', 'age', 'hasTick', 'tickS', 'tickT', 'phase', 'nextLeft', 'holdSinceMs', 'sol', 'holdEn', 'silentEn', 'camT',
                'hasImage', 'resumeEn', 'imgS', 'imgT', 'domState', 'domStateText', 'domAge', 'domAgeRes', 'domAgeAt', 'ageKey', 'lineSol',
                'keyNow', 'keyAt', 'canSince', 'drawKey', 'drawAt', 'drawTitle', 'stateAt', 'stateWant'];

async function visit(v) {
  const evs = v.events, probes = v.probes;
  const t0 = evs.length ? evs[0][0] : (probes.length ? probes[0] : 0);
  const page = await makePage({t0, lang: v.lang === 'fr' ? 'fr' : 'en', renderEvery: RENDER_EVERY, keepDraws: false, shared: true});
  const Live = page.Live;
  let tickS = null, tickT = null, imgS = null, imgT = null, ageKey = null, keyNow = null, keyAt = t0, canSince = null;
  let stateWant = null;
  page.el('age').onWrite = () => { ageKey = page.viewKey(); };
  page.el('state').onWrite = () => { stateWant = page.link && page.S ? Live.label(page.link, page.S, page.t) : null; };
  page.open();
  function after(t) {                                     // the view key only changes with a line (S changes only in applyEvent)
    const k = page.viewKey();
    if (k !== keyNow) { keyNow = k; keyAt = t; }
    const c = Live.canDraw(page.S);
    if (!c) canSince = null; else if (canSince === null) canSince = t;
  }
  function onEvent(ev, t) {
    if (ev.e === '__cut') { page.error(t); after(t); return; }
    if (ev.e === '__open') {
      page.advance(t);
      if (!page.es || page.es.closed) page.errors.push('the bench reconnected before app.js opened a new stream');
      page.open();
      return;
    }
    page.send(ev, t);
    if (ev.e === 'tick') { tickS = typeof ev.s === 'number' ? ev.s : null; tickT = ev.t; if (ev.cam !== undefined) { imgS = tickS; imgT = ev.t; } }
    if (ev.e === 'sol') { imgS = null; imgT = null; }
    after(t);
  }
  const res = [];
  let i = 0;
  for (const p of probes) {
    while (i < evs.length && evs[i][0] <= p) { onEvent(evs[i][1], evs[i][0]); i++; }
    page.advance(p);
    const S = page.S, link = page.link, d = page.lastDraw, st = page.el('state'), a = ageSeconds(page.el('age').textContent);
    const m = /^SOL (\S+) /.exec(page.el('line').textContent);
    res.push([p, Live.label(link, S, p), Live.dataAgeS(S, p), S.hasTick, tickS, tickT, S.phase, Live.nextLeftS(S, p),
              S.phaseSinceMs, S.sol, Live.holdText(S, p, 'en'), Live.silentText(S, p, 'en'), S.cam ? S.camT : null, !!S.cam,
              Live.resumeText(S, 'en'), imgS, imgT, st.dataset.state === undefined ? null : st.dataset.state, st.textContent,
              a ? a.s : null, a ? a.res : null, page.el('age').writtenAt, ageKey, m ? m[1] : null, keyNow, keyAt, canSince,
              d ? d.key : null, d ? d.t : null, d ? d.title : null, st.writtenAt, stateWant]);
  }
  while (i < evs.length) { onEvent(evs[i][1], evs[i][0]); i++; }
  return {id: v.id, errors: page.errors, probes: res};
}

(async () => {
  const inp = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const out = {fields: FIELDS, visitors: []};
  for (const v of inp.visitors) out.visitors.push(await visit(v));
  fs.writeFileSync(process.argv[3], JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
