'use strict';
// Exact comparison of the page's palette-index buffers with render.console.render_frame (design 9.6), real recorded sols.
const test = require('node:test');
const assert = require('node:assert');
const {Con, Live, events, refs, zlib} = require('./helpers.js');

const MAP = [7, 231, 129, 353];            // map rectangle (x0, y0, x1, y1), masked when the frame has no `lm`
for (const stage of [0, 1, 2, 3, 4, 5, 'fake5']) {
  // 'fake5' = FICTITIOUS stage-5 trace with a SCAN cloud (no real sol has analysed a sample yet): code equality only.
  test(`${stage === 'fake5' ? 'fictitious stage 5 with SCAN cloud' : 'stage ' + stage}: page buffers equal the Python reference (nodes, CAM-1, map, telemetry, ARM/SCAN)`, () => {
    const ev = events(stage), R = refs(stage), S = Live.newView(), buf = new Uint8Array(640 * 360);
    const byIdx = new Map(R.refs.map((r) => [r.i, r]));
    let compared = 0, fullCompared = 0, bad = [];
    ev.forEach((e, k) => {
      Live.applyEvent(S, e, 1000 * k);
      if (e.e !== 'tick') return;
      const r = byIdx.get(k - 1);
      if (!r) return;
      Con.renderConsole(buf, S, {scanlines: true, connections: false});
      const want = zlib.inflateSync(Buffer.from(r.buf, 'base64'));
      assert.strictEqual(want.length, 640 * 360);
      let diff = 0, first = null;
      for (let y = 0; y < 360; y++) for (let x = 0; x < 640; x++) {
        if (!r.full && x >= MAP[0] && x < MAP[2] && y >= MAP[1] && y < MAP[3]) continue;
        if (buf[y * 640 + x] !== want[y * 640 + x]) { diff++; if (!first) first = [x, y, buf[y * 640 + x], want[y * 640 + x]]; }
      }
      compared++; if (r.full) fullCompared++;
      if (diff) bad.push(`tick ${e.t}: ${diff} px differ, first (x,y,got,want) ${JSON.stringify(first)}`);
    });
    assert.ok(compared >= 20, `only ${compared} frames compared`);
    assert.ok(fullCompared >= 10, `only ${fullCompared} frames with the full map compared`);
    assert.deepStrictEqual(bad, [], bad.slice(0, 5).join('\n'));
  });
}

test('connections drawn by the page stay inside the brain panel and change pixels only there', () => {
  const ev = events(3), S = Live.newView(), a = new Uint8Array(640 * 360), b = new Uint8Array(640 * 360);
  let n = 0;
  for (const e of ev) {
    Live.applyEvent(S, e, 0);
    if (e.e !== 'tick' || e.t !== 400) continue;
    Con.renderConsole(a, S, {connections: false}); Con.renderConsole(b, S, {connections: true});
    for (let y = 0; y < 360; y++) for (let x = 0; x < 640; x++) if (a[y * 640 + x] !== b[y * 640 + x]) {
      n++; assert.ok(x >= 336 && x < 632 && y >= 24 && y < 224, `pixel outside the brain panel ${x},${y}`);
    }
  }
  assert.ok(n > 50, 'no connection drawn');
});
