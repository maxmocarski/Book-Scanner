// Use tests/ui/mock_server.py, never your real library: this creates test accounts/trades.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');

const base = process.argv[2] || 'http://127.0.0.1:8765';
const out = process.env.BOOKBRIDGE_UI_SCREENSHOTS || '/tmp/bookbridge-ui-check';

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.BOOKBRIDGE_CHROMIUM || undefined,
    args: ['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
  });
  
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, permissions: ['camera'] });
  const page = await context.newPage();
  const errors = [];
  
  page.on('pageerror', err => errors.push(err.message));
  await fs.mkdir(out, { recursive: true });
  
  const stamp = String(Date.now());
  const name = 'reader_' + stamp;
  const friendName = 'friend_' + stamp;
  const password = 'test-only-passphrase';

  async function req(path, token, body, method) {
    const response = await fetch(base + path, {
      method: method || (body ? 'POST' : 'GET'),
      headers: {
        ...(token ? { Authorization: 'Bearer ' + token } : {}),
        ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {})
      },
      body: body ? (body instanceof FormData ? body : JSON.stringify(body)) : undefined
    });
    const result = response.status === 204 ? null : await response.json();
    assert(response.ok, JSON.stringify({ path, status: response.status, result }));
    return result;
  }

  const visible = async selector => {
    await page.locator(selector).waitFor({ state: 'visible', timeout: 15000 });
  };
  
  const text = async (selector, value) => {
    await page.waitForFunction(([selector, value]) => document.querySelector(selector)?.textContent.includes(value), [selector, value], { timeout: 15000 });
  };

  await page.goto(base);
  await visible('#auth');
  await page.screenshot({ path: out + '/01-sign-in.png', fullPage: true });
  
  await page.locator('#auth-toggle').click();
  await page.locator('#auth-name').fill(name);
  await page.locator('#auth-password').fill(password);
  await page.locator('#auth-submit').click();
  
  await visible('#workspace');
  await text('#username', name);

  const ownToken = await page.evaluate(() => sessionStorage.getItem('bookbridge-token'));

  await page.locator('#camera-open').click();
  await visible('#camera-controls');
  await page.locator('#shutter').click();
  await page.waitForFunction(() => document.querySelectorAll('.photo-choice img').length === 1);
  await page.getByRole('button', { name: 'Remove front photo', exact: true }).click();
  await page.locator('#camera-close').click();

  const png = await page.evaluate(() => {
    const c = document.createElement('canvas');
    c.width = 420;
    c.height = 620;
    const x = c.getContext('2d');
    x.fillStyle = '#233b32';
    x.fillRect(0, 0, 420, 620);
    x.strokeStyle = '#c8b878';
    x.lineWidth = 3;
    x.strokeRect(24, 24, 372, 572);
    x.fillStyle = '#e8d6ad';
    x.textAlign = 'center';
    x.font = '22px Georgia';
    x.fillText('F. SCOTT FITZGERALD', 210, 105);
    x.font = '44px Georgia';
    x.fillText('THE GREAT', 210, 210);
    x.fillText('GATSBY', 210, 265);
    x.font = '100px Georgia';
    x.fillText('✦', 210, 440);
    return c.toDataURL('image/png').split(',')[1];
  });

  for (const [i, view] of ['front', 'spine', 'back'].entries()) {
    await page.getByRole('button', { name: 'Select ' + view + ' photo', exact: true }).click();
    await page.locator('#upload-photo').click();
    await page.locator('#photo-input').setInputFiles({ name: view + '.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') });
    await page.waitForFunction(n => document.querySelectorAll('.photo-choice img').length === n, i + 1);
  }

  await page.screenshot({ path: out + '/02-scanner.png', fullPage: true });
  
  await page.locator('#scan-mode').selectOption('lookup');
  await page.locator('#queue-book').click();
  await text('#scan-feedback', 'Book queued');
  
  await page.locator('[data-tab=queue]').click();
  await page.getByRole('button', { name: 'Review', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  await visible('#review-dialog');

  assert.equal(await page.locator('#review-book-title').inputValue(), 'The Great Gatsby');
  assert.equal(await page.locator('#review-author').inputValue(), 'F. Scott Fitzgerald');
  assert.equal(await page.locator('#review-isbn').inputValue(), '9780743273565');
  assert.equal(await page.locator('#review-photos figure').count(), 3);
  
  await text('#review-notes', 'Text corrections');
  await page.locator('#review-available').check();
  await page.screenshot({ path: out + '/03-review.png', fullPage: true });
  
  await page.getByRole('button', { name: 'Save to my library', exact: true }).click();
  await page.locator('#review-dialog').waitFor({ state: 'hidden' });

  await page.locator('[data-tab=library]').click();
  await visible('.book-card');
  await text('#book-grid', 'The Great Gatsby');
  await page.waitForFunction(() => document.querySelector('.book-card img')?.src.startsWith('blob:'));
  await page.screenshot({ path: out + '/04-library.png', fullPage: true });

  await page.getByRole('button', { name: 'The Great Gatsby by F. Scott Fitzgerald', exact: true }).click();
  await page.locator('#book
