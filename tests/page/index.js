'use strict';
// Entry point so that `node --test tests/page/` (a directory argument) runs the whole suite on every Node version.
require('./render.test.js');
require('./logic.test.js');
require('./absent.test.js');
require('./labels.test.js');
require('./silent.test.js');
require('./exact.test.js');
require('./image.test.js');
require('./app.test.js');
// page v2 (live-rc14)
require('./i18n.test.js');
require('./v2render.test.js');
require('./layout.test.js');
require('./ui.test.js');
require('./about.test.js');
// VERIF-rc14 fixes (live-rc15)
require('./verif14.test.js');
// live-rc16: local time and « alive for »
require('./local.test.js');
// security batch 1 + SEO lot A (consigne 50, secpage)
require('./secpage.test.js');
// the intro cinematic on the first visit (consigne 52, intro)
require('./intro.test.js');
