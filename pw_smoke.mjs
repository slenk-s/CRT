const { chromium } = await import('file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto('http://localhost:5173/admin/users', { waitUntil: 'networkidle' });
console.log('url', page.url());
console.log('title', await page.title());
console.log('body', (await page.locator('body').innerText()).slice(0, 200));
await browser.close();
