'use strict';
// End-to-end: decode a stream file written by the REAL producer (rover.live) with the page's own code (applyEvent + renderConsole).
// Usage: node e2e_stream.js <stream.ndjson>  ->  prints a JSON report; exit 1 on any inconsistency.
const {Live, Con, fs} = require('./helpers.js');
const lines = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
const S = Live.newView(); const rep = {events: lines.length, ticks: 0, camTicks: 0, lm: 0, snt: 0, sd: 0, sol: 0, arm: 0, smp: 0, spc: 0, locked: 0, drawn: 0, errors: []};
let lastTick = null, lastSd = null, lmSeen = false, solEv = null;
const img = new Uint8Array(640 * 360);
lines.forEach((ev, i) => {
  try { Live.applyEvent(S, ev, i); } catch (e) { rep.errors.push('apply ' + ev.e + ': ' + e.message); return; }
  if (ev.e === 'sol') { rep.sol++; solEv = ev; }
  if (ev.e !== 'tick') return;
  rep.ticks++; lastTick = ev;
  if (ev.smp) rep.smp++;
  if (ev.spc) rep.spc++;
  if ((ev.fl & 16) !== 0) rep.locked++;
  if (ev.cam !== undefined) {
    rep.camTicks++;
    if (ev.sd) { rep.sd++; lastSd = ev.sd; }
    if (ev.snt) { rep.snt++; if (ev.snt.length !== ev.sn.length) rep.errors.push('snt/sn length at t' + ev.t); }
    if (ev.lm) { rep.lm++; lmSeen = true; }
    if (ev.arm) { rep.arm++; if (!S.armPatch || S.armPatch.length !== 256) rep.errors.push('arm patch at t' + ev.t); }
    if (rep.camTicks % 20 === 1) { try { Live.renderLive(img, S, null); rep.drawn++; } catch (e) { rep.errors.push('render t' + ev.t + ': ' + e.message); } }
  }
});
if (rep.smp) check0(S.sample && Array.isArray(S.sample.f) && S.sample.f.length === 5, 'sample not decoded');
if (rep.spc) check0(S.spectrum === null || S.spectrum.length === 16 || S.spectrum.length > 0, 'spectrum shape');
function check0(c, m) { if (!c) rep.errors.push(m); }
function check(c, m) { if (!c) rep.errors.push(m); }
check(rep.sol === 1 && rep.ticks > 0, 'no sol / ticks');
check(S.w && S.w.length > 0 && Array.from(S.w).every(Number.isFinite), 'weights missing or not finite (sol.w.m0)');
check(JSON.stringify(S.pose) === JSON.stringify(lastTick.p), 'pose is not the last tick pose');
check(S.battery === lastTick.b && S.u === lastTick.u && S.hd === lastTick.hd, 'telemetry/brain not copied from the last tick');
check(lastSd === null || JSON.stringify(S.sun) === JSON.stringify(lastSd), 'sun vector is not the last sd');
check(S.map.size > 0, 'map empty although cells were seen');
check(rep.lm > 0 && rep.snt > 0, 'no lm / snt received');
for (const v of S.map.values()) { if (!(v >= 1 && v <= 254)) { rep.errors.push('map value out of range ' + v); break; } }
check(S.locked === ((lastTick.fl & 16) !== 0), 'locked flag');
check(S.camDims && S.camDims.w === solEv.cam.w && S.cam && S.cam.data.length === S.cam.w * S.cam.h, 'camera image size');
rep.mapCells = S.map.size; rep.weights = S.w ? S.w.length : 0;
console.log(JSON.stringify(rep));
process.exit(rep.errors.length ? 1 : 0);
