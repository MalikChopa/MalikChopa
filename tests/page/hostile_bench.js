'use strict';
// SEC-14 bench (not a *.test.js file): the REAL page (app_vm.js: app.js, live.js, console.js) receives a real stage-5 test sol, then
// malformed stream lines (FRONT-02 and more), each followed by a normal tick. For each line: the wall time of its reception plus one
// draw period (one draw + the text lines), and whether the page draws again after it. Test streams only (tests/page/fixtures).
// Run by tests/page/secpage.test.js in a child process with a time limit (an endless loop cannot stop the runner).
//   node tests/page/hostile_bench.js [case ...]   ->  {"cases": [{"name", "ms", "drawsAfter", "errors"}], "maxMs"}
const {makePage} = require('./app_vm.js');
const {events} = require('./helpers.js');

const LONG = 'A'.repeat(70 * 1024);                      // a line stays under the server's 80 KB cap (streamlog.MAX_LINE)
const CASES = {
  p_nan: (t) => ({p: [t.p[0], t.p[1], 'x', 0]}),
  p_big: (t) => ({p: [t.p[0], t.p[1], 1e8, 0]}),
  p_huge_pos: (t) => ({p: [1e300, -1e300, t.p[2], t.p[3]]}),
  sd_str: () => ({sd: [1, 'x', 0]}),
  sd_big: () => ({sd: [1, 1e8, 0]}),
  tg_bad: () => ({tg: ['x', 1e308]}),
  m_obj: () => ({m: {toString: 1}}),
  m_long: () => ({m: LONG}),
  arrays_bad: () => ({x: 'not an array', hd: null, y: {}, u: 'x', xi: [1e308, 'y'], m1: [[1], 'z'], z: LONG}),
  spc_flood: (t, i) => ({spc: {v: new Array(16).fill(0.5), cat: 2, conf: 0.5, pts: Array.from({length: 6000}, (_, k) => [i * 6000 + k, k, -k, k % 16])}}),
  cam_bad: () => ({cam: LONG}),
  lm_bad: () => ({lm: {x0: 1e300, y0: 'x', d: 'AAAA'}}),
  sol_obj_name: null,          // a sol line (see below)
  sol_scan_flood: null,
  phase_long: null,
  learn_bad: null,
  sol_end_long: null
};

function lineFor(name, base, i) {
  if (name === 'sol_obj_name') return [{e: 'sol', s: base.s, stage: 5, stage_name: {toString: 1}, now: '2026-11-13T10:00:00Z', cam: {w: 32, h: 20, D: 1}, tick_ms: 600}];
  if (name === 'sol_scan_flood') {
    const n = 4000;
    return [{e: 'sol', s: base.s, stage: 5, stage_name: LONG, now: '2026-11-13T10:00:00Z', cam: {w: 32, h: 20, D: 1}, tick_ms: 600,
             scan0: {n, explained: 0.5, xy: Array.from({length: n}, (_, k) => [k, -k]), labels: Array.from({length: n}, (_, k) => k % 16), names: {2: LONG}}}];
  }
  if (name === 'phase_long') return [{e: 'phase', ph: LONG}, {e: 'phase', ph: 'learn'}, {e: 'learn', mod: LONG, gen: {toString: 1}, of: 1, best: 1e308, mean: 'x', val: {k: LONG}}];
  if (name === 'learn_bad') return [{e: 'phase', ph: 'learn'}, {e: 'learn', mod: 'm4', gen: {toString: 1}, of: LONG, best: 1, mean: 1, val: {r2: LONG}}];
  if (name === 'sol_end_long') return [{e: 'phase', ph: 'idle', next: LONG}, {e: 'sol_end', stage: LONG, progress: {text: LONG, fraction: 'x'}, distance_m: LONG, targets: LONG, attempts: {toString: 1}}];
  return [Object.assign({}, base, {t: base.t + 1}, CASES[name](base, i))];
}

// the drawing alone (console.js line() and text() bounds), without live.js's checks: a state set directly, one page render
const DIRECT = {
  draw_pose_nan: (S) => { S.pose = [S.pose[0], S.pose[1], NaN, 0]; },
  draw_pose_str: (S) => { S.pose = [S.pose[0], S.pose[1], 'x', 0]; },
  draw_pose_frac: (S) => { S.pose = [S.pose[0], S.pose[1], 0.5, 0.25]; S.trail = []; },
  draw_sun_str: (S) => { S.sun = [1, 'x', 0]; S.mode = 'DRIVE'; },
  draw_sun_big: (S) => { S.sun = [1, 1e8, 0]; S.mode = 'DRIVE'; },
  draw_text_long: (S) => { S.stageName = LONG; S.mode = LONG; }
};
function direct(name) {
  const {Live} = require('./helpers.js');
  const {fixtureState, aug, opts} = require('./page_helpers.js');
  const S = aug(fixtureState(5, 'day'));
  DIRECT[name](S);
  const buf = new Uint8Array(640 * 360), h0 = process.hrtime.bigint();
  let err = 0;
  try { Live.renderLive(buf, S, null, opts('en')); } catch (e) { err = 1; }
  return {name, ms: Math.round(Number(process.hrtime.bigint() - h0) / 1e4) / 100, drawsAfter: null, errors: err};
}

async function run(names) {
  const ev = events(5), sol = ev[0], ticks = ev.filter((e) => e.e === 'tick');
  const out = [];
  let i = 0;
  for (const name of names) {
    if (DIRECT[name]) { out.push(direct(name)); continue; }
    const t0 = 5_000_000;
    const p = await makePage({t0, keepDraws: true});
    p.open();
    const snap = [sol, ticks[0]];
    p.send({e: 'hello', proto: 2, server_utc: '2026-11-13T10:00:00Z', engine_silent_s: 0, snap_n: snap.length, tick_age_s: 0.1, cam_age_s: 0.1, phase_age_s: null});
    snap.forEach((e) => p.send(e));
    let t = t0 + 1000;
    for (let k = 1; k < 8; k++) { p.send(ticks[k], t); t += 600; }
    p.advance(t); t += 600;
    const base = ticks[8];
    const lines = lineFor(name, base, i++);
    const h0 = process.hrtime.bigint();
    lines.forEach((l) => p.send(l, t));
    p.advance(t + 600);
    const ms = Number(process.hrtime.bigint() - h0) / 1e6;
    t += 1200;
    const d0 = p.draws.length;
    // the page goes on: a new sol line and two normal ticks are drawn
    p.send(sol, t); p.send(ticks[9], t + 600); p.send(ticks[10], t + 1200); p.advance(t + 2400);
    out.push({name, ms: Math.round(ms * 100) / 100, drawsAfter: p.draws.length - d0, errors: p.errors.length});
  }
  return {cases: out, maxMs: Math.max(...out.map((c) => c.ms))};
}

if (require.main === module) {
  const names = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(CASES).concat(Object.keys(DIRECT));
  run(names).then((r) => { process.stdout.write(JSON.stringify(r) + '\n'); }, (e) => { process.stderr.write(String(e && e.stack || e) + '\n'); process.exit(2); });
}
module.exports = {run, CASES, DIRECT};
