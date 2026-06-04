#!/usr/bin/env node
/**
 * Build the Chrome extension, injecting environment variables.
 *
 *   FLOWBOARD_APP_ORIGIN=https://app.example.com node build.js
 *
 * Outputs to extension/dist/ — load that folder in chrome://extensions.
 * Default origin: http://localhost:8101
 */
const fs   = require('fs');
const path = require('path');

const APP_ORIGIN = (process.env.FLOWBOARD_APP_ORIGIN || 'http://localhost:8101').replace(/\/$/, '');

console.log(`[build] APP_ORIGIN = ${APP_ORIGIN}`);

const SRC  = __dirname;
const DIST = path.join(SRC, 'dist');

fs.mkdirSync(DIST, { recursive: true });

// Files that need __APP_ORIGIN__ replaced
const TEMPLATE_FILES = ['background.js', 'manifest.json'];

// Files copied verbatim
const STATIC_FILES = ['content.js', 'injected.js', 'popup.html', 'popup.js', 'rules.json'];

for (const f of TEMPLATE_FILES) {
  const src = path.join(SRC, f);
  if (!fs.existsSync(src)) { console.warn(`[build] missing ${f}, skipping`); continue; }
  const out = fs.readFileSync(src, 'utf8').replaceAll('__APP_ORIGIN__', APP_ORIGIN);
  fs.writeFileSync(path.join(DIST, f), out);
  console.log(`[build] wrote ${f}`);
}

for (const f of STATIC_FILES) {
  const src = path.join(SRC, f);
  if (!fs.existsSync(src)) { console.warn(`[build] missing ${f}, skipping`); continue; }
  fs.copyFileSync(src, path.join(DIST, f));
  console.log(`[build] copied ${f}`);
}

console.log(`[build] done → ${DIST}`);
