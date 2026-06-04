/**
 * Quick diagnostic: navigate to app after login and dump the DOM structure
 * to understand what selectors actually work.
 */
import { chromium } from 'playwright';

const API_URL = 'http://localhost:8101';

async function main() {
  // Create a fresh account for this diagnostic
  const email = `diag-${Date.now()}@gmail.com`;
  const password = 'TestPass1234!';

  console.log('Creating account via API...');
  const reg = await fetch(`${API_URL}/api/account/register`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
  console.log('Register:', reg.status, await reg.text());

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  // Navigate and log all responses
  page.on('response', r => {
    if (r.url().includes('/api/account/')) console.log(`  API: ${r.status()} ${r.url()}`);
  });
  page.on('console', m => {
    if (m.type() === 'error') console.log('  CONSOLE ERR:', m.text());
  });

  // Go directly to /app/
  await page.goto('http://localhost:3000/app/', { waitUntil: 'load', timeout: 15000 });
  await page.waitForTimeout(1000);

  // Fill and submit login form
  const h1 = await page.locator('h1').first().textContent().catch(() => 'none');
  console.log('h1 before login:', h1);

  if (h1.includes('Welcome')) {
    await page.locator('input[type="email"]').fill(email);
    await page.locator('input[placeholder="Password"]').fill(password);
    await page.locator('button[type="submit"]').click();
    console.log('Login form submitted, waiting 8s...');
    await page.waitForTimeout(8000);
  }

  // Dump DOM structure
  const url = page.url();
  const h1After = await page.locator('h1').first().textContent().catch(() => 'none');
  console.log('\nURL after wait:', url);
  console.log('h1 after:', h1After);

  // Get all top-level class names
  const classes = await page.evaluate(() => {
    const els = document.querySelectorAll('body > *, body > * > *');
    return Array.from(els).slice(0, 20).map(el => ({
      tag: el.tagName,
      cls: el.className,
      id: el.id,
      text: el.textContent?.slice(0, 50).trim()
    }));
  });
  console.log('\nTop DOM elements:');
  classes.forEach(el => console.log(`  <${el.tag} class="${el.cls}" id="${el.id}"> "${el.text}"`));

  // Try specific selectors
  for (const sel of ['.app', '.canvas-wrap', '[class*="app"]', '[class*="App"]', '[class*="canvas"]', '[class*="sidebar"]', '[class*="project"]']) {
    const count = await page.locator(sel).count();
    if (count > 0) {
      const txt = await page.locator(sel).first().textContent().catch(() => '');
      console.log(`  FOUND "${sel}" (${count}): "${txt.slice(0, 60)}"`);
    }
  }

  await page.screenshot({ path: 'd:\\Workspace\\AI\\d12\\flowboard\\e2e-screenshots\\diag-after-login.png', fullPage: true });
  await browser.close();
}

main().catch(e => { console.error(e); process.exit(1); });
