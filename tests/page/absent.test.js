'use strict';
const test = require('node:test');
const assert = require('node:assert');
const {Con, Live} = require('./helpers.js');

test('fix refuses non-numbers', () => {
  assert.strictEqual(Con.fix(null, 2), '--');
  assert.strictEqual(Con.fix(undefined, 2, true), '--');
  assert.strictEqual(Con.fix(NaN, 2), '--');
  assert.strictEqual(Con.fix(0, 2), '0.00');
});
test('valText: absent ARI prints --, real zeros stay', () => {
  const t = Live.valText('m5', {val: {ari: null, k: 1}});
  assert.ok(t.includes('ARI --') && !t.includes('0.00'), t);
  assert.strictEqual(Live.valText('m5', {val: {ari: 0, k: 0}}), 'K 0 | ARI 0.00');
  assert.ok(Live.valText('m1', {val: {r2: null}}).includes('R2 --'));
  assert.ok(Live.valText('m2', {val: {}}).includes('EXPLAINED --'));
  assert.ok(Live.valText('m5', {val: {ari: 0.5, k: null}}).startsWith('K --'));
});
test('SCAN line without scan0 prints no invented K 0 / AX 0%', () => {
  const t = Con.scanLine({scan: null});
  assert.ok(!/K 0|AX 0%/.test(t), t);
  assert.strictEqual(t, 'K -- N -- AX --');
  assert.strictEqual(Con.scanLine({scan: {k: null, ax: null, pts: []}}), 'K -- N 0 AX --');
  assert.strictEqual(Con.scanLine({scan: {k: 0, ax: 0, pts: []}}), 'K 0 N 0 AX 0%');
});
