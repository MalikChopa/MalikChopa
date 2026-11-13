'use strict';
// Exact labels (brief 42): every label must say what its value is.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs'), path = require('path');
const {Con, Live} = require('./helpers.js');

test('battery line: the success count only, never paired with the number of generations', () => {
  const t = Live.valText('battery', {val: {successes: 20}, gen: 1, of: 1});
  assert.strictEqual(t, 'TEST COURSES 20 PASSED');
  assert.ok(!/\//.test(t));
  assert.strictEqual(Live.valText('battery', {val: {}, gen: 1, of: 1}), 'TEST COURSES -- PASSED');
  assert.strictEqual(Live.valText('battery', {gen: 1, of: 1}), 'TEST COURSES -- PASSED');
});

test('sol_end progress: the producer sends an object {fraction, text, blocking}, shown as its text', () => {
  assert.strictEqual(Live.progressText({fraction: 0.4, text: '40% of X', blocking: null}), '40% of X');
  assert.strictEqual(Live.progressText({fraction: 0.4}), '40%');
  assert.strictEqual(Live.progressText({}), null);
  assert.strictEqual(Live.progressText(0.4), null);
  assert.strictEqual(Live.progressText(undefined), null);
});

function sample() {
  const S = Live.newView();
  // hasTick: an image only ever comes with a tick (applyTick); without a tick the page draws the bare view (live-rc13, RC12-verif I2)
  Object.assign(S, {cam: {w: 8, h: 6, data: new Uint8Array(48)}, camDims: {w: 8, h: 6}, stageName: 'X', sol: 3, now: '2026-01-01T07:45:00Z', hasTick: true});
  return S;
}

test('header: the live page says SOL START (S.now is the start of the sol); the parity renderer keeps LAST CONTACT', () => {
  const S = sample(), a = new Uint8Array(640 * 360), b = new Uint8Array(640 * 360), c = new Uint8Array(640 * 360);
  Live.renderLive(a, S, null);
  Con.renderConsole(b, S, {scanlines: true, contactLabel: 'SOL START'});
  Con.renderConsole(c, S, {scanlines: true});
  assert.deepStrictEqual(Buffer.from(a), Buffer.from(b));
  assert.notDeepStrictEqual(Buffer.from(a), Buffer.from(c));
});

test('sol_end rows: no [OBJECT OBJECT], renamed rows', () => {
  const S = sample(), a = new Uint8Array(640 * 360), b = new Uint8Array(640 * 360);
  Live.applyEvent(S, {e: 'phase', ph: 'idle'}, 0);
  Live.applyEvent(S, {e: 'sol_end', stage: 2, progress: {fraction: 0.4, text: 'AB', blocking: null}, attempts: 0, battery_successes: 20}, 0);
  Live.renderLive(a, S, null);
  Live.applyEvent(S, {e: 'sol_end', stage: 2, progress: {fraction: 0.4, text: 'CD', blocking: null}, attempts: 0, battery_successes: 20}, 0);
  Live.renderLive(b, S, null);
  assert.notDeepStrictEqual(Buffer.from(a), Buffer.from(b));   // the progress text is drawn
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'pages', 'live', 'live.js'), 'utf8');
  assert.ok(src.includes("'COURSES PASSED'") && src.includes("'RETRIES'") && !src.includes("'BATTERY TESTS'") && !src.includes("'ATTEMPTS'"));
});

test('offline note does not claim "offline since" the last publication time', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'pages', 'live', 'app.js'), 'utf8');
  assert.ok(!/offline_note/.test(src) && /Last published sol/.test(src) && /Dernier sol publi/.test(src));
});
