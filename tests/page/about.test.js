'use strict';
// Page v2 (live-rc14): the « How it works » tab (content of the EXPLAIN role, out/page-v2/explain, adapted in pages/live/about):
// every picture is labelled (schéma / illustration / test image, never presented as Sol-0's life), CSP-safe markup, same structure
// in both languages, labels of the page states equal to i18n.json (DESIGN.md §10, §12 T20).
const test = require('node:test');
const assert = require('node:assert');
const {fs, path, PAGE} = require('./helpers.js');
const {I18N} = require('./page_helpers.js');

const FR = fs.readFileSync(path.join(PAGE, 'about', 'fr.html'), 'utf8'), EN = fs.readFileSync(path.join(PAGE, 'about', 'en.html'), 'utf8');
const TAGS = {fr: ['schéma', 'illustration', "image d'essai, pas Sol-0"], en: ['diagram', 'illustration', 'test image, not Sol-0']};

test('T20 every image is in a <figure> with a labelled caption; every SVG has a <title> and a visible « schéma » / « diagram »', () => {
  for (const [lang, f] of [['fr', FR], ['en', EN]]) {
    const figs = [...f.matchAll(/<figure[^>]*>([\s\S]*?)<\/figure>/g)].map((m) => m[1]);
    const imgs = f.match(/<img\b/g) || [], svgs = f.match(/<svg\b/g) || [];
    assert.ok(imgs.length >= 1 && imgs.length <= 6, `${lang}: ${imgs.length} images`);
    let inFig = 0;
    for (const g of figs) {
      const cap = /<figcaption>([\s\S]*?)<\/figcaption>/.exec(g);
      assert.ok(cap, `${lang}: a figure without caption`);
      const tag = /<span class="x-tag">([^<]*)<\/span>/.exec(cap[1]);
      assert.ok(tag && TAGS[lang].includes(tag[1]), `${lang}: caption label ${tag && tag[1]}`);
      if (/<img\b/.test(g)) { inFig++; assert.notStrictEqual(tag[1], TAGS[lang][0], 'an image labelled as a diagram'); }
      if (/<svg\b/.test(g)) {
        assert.strictEqual(tag[1], TAGS[lang][0]);
        assert.ok(/<svg[^>]*role="img"[^>]*>\s*<title id="[^"]+">[^<]+<\/title>/.test(g), `${lang}: svg without title`);
        assert.ok(new RegExp('>' + (lang === 'fr' ? 'SCHÉMA' : 'DIAGRAM') + '<').test(g), `${lang}: svg without its visible label`);
      }
    }
    assert.strictEqual(inFig, imgs.length, `${lang}: an image outside a figure`);
    for (const m of f.matchAll(/<img\b[^>]*>/g)) {
      assert.ok(/\ssrc="about\/img\/[a-z0-9-]+\.png"/.test(m[0]) && /\salt="[^"]{10,}"/.test(m[0]) && /loading="lazy"/.test(m[0]) && /\swidth="\d+"/.test(m[0]) && /\sheight="\d+"/.test(m[0]), m[0]);
      const file = path.join(PAGE, /src="([^"]+)"/.exec(m[0])[1]);
      assert.ok(fs.statSync(file).size <= 300 * 1024, file);
    }
    assert.ok(svgs.length >= 1);
    assert.ok(!/<script|<style|\sstyle=|\son[a-z]+=|javascript:|<iframe/i.test(f), `${lang}: forbidden markup`);
  }
  // same sections, same figures, in both languages
  assert.deepStrictEqual([...FR.matchAll(/data-sec="([a-z]+)"/g)].map((m) => m[1]), [...EN.matchAll(/data-sec="([a-z]+)"/g)].map((m) => m[1]));
  assert.strictEqual((FR.match(/<figure/g) || []).length, (EN.match(/<figure/g) || []).length);
});

test('the explainer quotes the badge words of i18n.json; it gives the birth time and no seed-like number', () => {
  for (const [lang, f] of [['fr', FR], ['en', EN]]) {
    for (const m of f.matchAll(/<span class="x-lbl">([^<]+)<\/span>/g)) {
      assert.ok(Object.keys(I18N).some((k) => k.startsWith('d.state.') && I18N[k][lang] === m[1]), `${lang}: « ${m[1]} » is not a badge of the page`);
    }
    assert.ok(/12:11:21/.test(f), `${lang}: birth time`);
    assert.ok(!/\b\d{12,}\b/.test(f.replace(/<!--[\s\S]*?-->/g, '')), `${lang}: a long number (a seed?) in the text`);
  }
  // ids unique across the two fragments (both are in the same document)
  const ids = [...(FR + EN).matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
  assert.strictEqual(new Set(ids).size, ids.length);
});
