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
