'use strict';
// Page v2 (live-rc14): every text of the page in FR and EN (DESIGN.md §7, §12 T7, T8, T10, T11). The table is pages/live/i18n.json
// (words from out/page-v2/I18N.md); the English of every canvas text is the literal drawn by the code (rc13 text), so the English
// page draws what the Python renderer draws.
const test = require('node:test');
const assert = require('node:assert');
const {Con, Live, assets, fs, path, PAGE} = require('./helpers.js');
const {I18N} = require('./page_helpers.js');

const SRC = Object.fromEntries(['console.js', 'live.js', 'app.js', 'index.html'].map((f) => [f, fs.readFileSync(path.join(PAGE, f), 'utf8')]));
// ids written in the code: T(o, 'id', ...), tr(o, 'id', ...), tt('id' ...), {{t:id}} {{a:id}} {{tb:id}}
function literalIds() {
  const ids = new Set();
  for (const f of ['console.js', 'live.js', 'app.js']) {
    for (const m of SRC[f].matchAll(/\b(?:T|tr)\((?:\w+|domO\(\w+, \w+\)), '([a-z0-9._-]+)'/g)) ids.add(m[1]);
    for (const m of SRC[f].matchAll(/\btt\('([a-z0-9._-]+)'/g)) ids.add(m[1]);
  }
  for (const m of SRC['app.js'].matchAll(/'([cdn]\.[a-z0-9._-]+)'/g)) if (I18N[m[1]]) ids.add(m[1]);     // tt(cond ? 'a' : 'b'), TB[lang]['id']
  // the « See it live → » link is written into the explainer fragments (pages/live/about) with the table's words
  for (const l of ['fr', 'en']) if (fs.readFileSync(path.join(PAGE, 'about', l + '.html'), 'utf8').includes('>' + I18N['n.seelive'][l] + '</a>')) ids.add('n.seelive');
  for (const m of SRC['index.html'].matchAll(/\{\{(?:t|a|tb):([a-z0-9._-]+)\}\}/g)) ids.add(m[1]);
  for (const id of [...ids]) if (id.endsWith('.')) ids.delete(id);      // a family prefix ('c.mode.' + key): see FAMILIES
  return ids;
}
// families built from a key at run time, with every key the code can use
const FAMILIES = {
  'c.mode.': Object.keys(assets.mode_labels), 'c.stage.': ['0', '1', '2', '3', '4', '5'], 'c.pause.ph.': Object.keys(Live.PH_EN),
  'c.pause.mod.': Object.keys(Live.MOD_NAMES), 'c.wait.': Object.keys(Live.WAIT_EN), 'd.state.': Object.values(Live.STATE_KEY),
  'n.panel.': ['cam', 'brain', 'map', 'tel', 'inst'], 'c.arm.ch.': ['hrd', 'r', 'g', 'b', 'grn']};

test('T7 every text id used by the page exists in i18n.json with a non-empty FR and EN; no dead entry', () => {
  const used = literalIds();
  for (const [pre, keys] of Object.entries(FAMILIES)) keys.forEach((k) => used.add(pre + k));
  ['d.state.offline'].forEach((k) => used.add(k));                 // the badge of the offline state (stateKey('OFFLINE'))
  for (const id of used) {
    assert.ok(I18N[id], `id ${id} used by the page is missing from i18n.json`);
    assert.ok(I18N[id].en && I18N[id].fr, `id ${id}: empty text`);
  }
  // dead entries: none, except the rc13 drawing kept for the parity path (no page options) and the waiting card of a family
  const dead = Object.keys(I18N).filter((id) => !used.has(id));
  assert.deepStrictEqual(dead, [], 'entries of i18n.json used nowhere: ' + dead.join(', '));
  assert.ok(used.size >= 150, `only ${used.size} ids`);
});

test('T8 the English of each canvas text is the literal drawn by the code (and the code\'s key maps agree with the table)', () => {
  let n = 0;
  for (const f of ['console.js', 'live.js']) {
    for (const m of SRC[f].matchAll(/\b(?:T|tr)\(o, '([a-z0-9._-]+)', '((?:[^'\\]|\\.)*)'/g)) {
      n++;
      assert.strictEqual(I18N[m[1]].en, m[2].replace(/\\'/g, "'"), `${f}: ${m[1]}`);
    }
    for (const m of SRC[f].matchAll(/\b(?:T|tr)\(o, '([a-z0-9._-]+)', "([^"]*)"/g)) { n++; assert.strictEqual(I18N[m[1]].en, m[2], `${f}: ${m[1]}`); }
  }
  assert.ok(n >= 90, `only ${n} literals checked`);
  for (const [k, v] of Object.entries(assets.mode_labels)) assert.strictEqual(I18N['c.mode.' + k].en, v, k);
  for (const [k, v] of Object.entries(Live.WAIT_EN)) assert.strictEqual(I18N['c.wait.' + k].en, v, k);
  for (const [k, v] of Object.entries(Live.MOD_NAMES)) assert.strictEqual(I18N['c.pause.mod.' + k].en, v, k);
  for (const [k, v] of Object.entries(Live.PH_EN)) assert.strictEqual(I18N['c.pause.ph.' + k].en, v, k);
  for (const [k, v] of Object.entries(Live.DOM_FR)) assert.strictEqual(I18N[k].fr, v, k);
  // the canvas state words are the badge's words (D17: the canvas says what the badge says)
  for (const k of ['connecting', 'learning', 'replay', 'silent', 'hold', 'busy', 'resuming', 'offline']) {
    assert.strictEqual(I18N['c.wait.' + k].en, I18N['d.state.' + k].en, k); assert.strictEqual(I18N['c.wait.' + k].fr, I18N['d.state.' + k].fr, k);
  }
  // stage names: the engine's names (src/rover/live/runner.py STAGE_NAMES) are the English of c.stage.n
  const runner = fs.readFileSync(path.join(PAGE, '..', '..', 'src', 'rover', 'live', 'runner.py'), 'utf8');
  const names = JSON.parse('[' + /STAGE_NAMES = \(([^)]*)\)/.exec(runner)[1] + ']');
  names.forEach((nm, i) => assert.strictEqual(I18N['c.stage.' + i].en, nm));
});

test('T10 glyphs: every character of the FR canvas texts is in the font (ASCII 32-126) or in the page\'s accent table', () => {
  const ok = (ch) => (ch.charCodeAt(0) >= 32 && ch.charCodeAt(0) <= 126) || Con.ACCENTS[ch] !== undefined;
  const seen = new Set();
  for (const [id, e] of Object.entries(I18N)) {
    if (!id.startsWith('c.')) continue;
    for (const ch of e.fr + e.en) { assert.ok(ok(ch), `${id}: ${JSON.stringify(ch)} has no glyph`); if (ch.charCodeAt(0) > 126) seen.add(ch); }
  }
  assert.deepStrictEqual([...seen].sort(), ['À', 'È', 'É', 'Ê', 'Û']);     // I18N.md §2: what the FR canvas needs
  // the 95 exported glyphs are untouched: accents are a separate table, base glyph + mark
  assert.strictEqual(assets.font.table.length, 95);
  for (const [ch, [base]] of Object.entries(Con.ACCENTS)) assert.ok(/[A-Z]/.test(base), ch);
  // strict mode: an unknown character is an error (production draws '?')
  Con.setStrict(true);
  try { assert.throws(() => Con.text(new Uint8Array(640 * 360), 0, 10, 'Œ', 1, 1)); assert.doesNotThrow(() => Con.text(new Uint8Array(640 * 360), 0, 10, 'ÉÈÊÀÛ', 1, 1)); }
  finally { Con.setStrict(false); }
});

// the longest value each {field} can take (cells); the stage, mode and phase names: the longest of the language
function longest(lang, pre) { return Object.entries(I18N).filter(([k]) => k.startsWith(pre)).map(([, v]) => v[lang]).sort((a, b) => b.length - a.length)[0]; }
function fill(id, lang) {
  const big = {n: '9999', s: '5', p: '100', b: '100', hh: '23', mm: '59', ss: '59', w: '160', h: '100', g: '+0.00', v: '+0.00', c: '0.99', a: '100%',
               u0: '+0.00', u1: '+0.00', k: '15', m: '6', d: '99999', name: longest(lang, 'c.stage.'), mode: longest(lang, 'c.mode.'), ph: longest(lang, 'c.pause.ph.')};
  if (id === 'c.scan.cat') big.name = '';                         // the category name is data of the engine (its own length)
  if (id === 'c.scan.peak') big.k = '15';
  if (id === 'c.scan.line') { big.k = '15'; big.n = '512'; big.a = '100%'; }
  if (id === 'c.arm.gain') big.n = lang === 'fr' ? 'NOUVEAU' : 'NOVEL';
  if (id === 'c.pause.gen') { big.g = '12'; big.n = '12'; }
  if (id === 'c.pause.battery') big.n = '99';
  if (id === 'c.arm.drills') { big.n = '6'; big.m = '6'; }
  if (id === 'c.pause.lastframe') big.n = '1199';
  if (id === 'c.tel.atstage' || id === 'c.tel.fromstage') big.n = '3';
  return Live.tr({t: {[id]: I18N[id][lang]}}, id, I18N[id].en, big);
}
test('T11 widths: every canvas text, EN and FR, filled with its longest values, fits its budget (cells of 6 px)', () => {
  const over = [];
  for (const [id, e] of Object.entries(I18N)) {
    if (!id.startsWith('c.') || e.b === null) continue;
    for (const lang of ['en', 'fr']) { const s = fill(id, lang); if (s.length > e.b) over.push(`${id} ${lang} ${JSON.stringify(s)} ${s.length} > ${e.b}`); }
  }
  assert.deepStrictEqual(over, []);
});
