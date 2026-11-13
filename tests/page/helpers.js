'use strict';
const fs = require('fs'), path = require('path'), zlib = require('zlib');
const ROOT = path.resolve(__dirname, '..', '..');
const PAGE = path.join(ROOT, 'pages', 'live');
const FIX = path.join(__dirname, 'fixtures');
const assets = JSON.parse(fs.readFileSync(path.join(PAGE, 'assets.json'), 'utf8'));
const Con = require(path.join(PAGE, 'console.js')).init(assets);
const Live = require(path.join(PAGE, 'live.js'));
Live.setConsole(Con);
function events(stage) {
  const txt = zlib.gunzipSync(fs.readFileSync(path.join(FIX, (typeof stage === 'number' ? `stage${stage}` : stage) + '.ndjson.gz'))).toString('utf8');
  return txt.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}
function refs(stage) { return JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(FIX, (typeof stage === 'number' ? `stage${stage}` : stage) + '.ref.json.gz'))).toString('utf8')); }
module.exports = {ROOT, PAGE, FIX, assets, Con, Live, events, refs, zlib, fs, path};
