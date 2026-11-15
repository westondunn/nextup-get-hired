import { expect, test } from '@playwright/test';

// The browser-test container does not receive the setup code, and the stack runs on
// bundled sample data, where every Google connection route refuses. These cover the
// locked card, the outcome shown when Google sends the browser back, and the refusals.
// The flow itself is covered with mocked Google calls by the backend suites.

test('the Google connection card is locked and reads nothing without a session', async ({
  page,
}) => {
  const calls: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/google')) calls.push(path);
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  const lock = page.getByRole('region', { name: 'Integrations lock' });
  await expect(lock.locator('[aria-live="polite"]')).toHaveText('Locked.', { timeout: 20000 });

  const card = page.getByRole('region', { name: 'Google connection' });
  await expect(card).toContainText('Locked. Unlock integrations above');
  await expect(card.locator('form')).toHaveCount(0);
  await expect(card.getByRole('button')).toHaveCount(0);
  expect(calls).toEqual([]);
});

test('arriving back from Google opens Settings, shows the outcome and clears the address', async ({
  page,
}) => {
  await page.goto('/?google=declined');
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible({
    timeout: 20000,
  });
  const card = page.getByRole('region', { name: 'Google connection' });
  await expect(card).toContainText('Access was declined at Google. Nothing was changed.');
  expect(new URL(page.url()).search).toBe('');
});

test('a result word that is not one of the fixed ones is ignored and never shown', async ({
  page,
}) => {
  await page.goto('/?google=synthetic-unknown-word');
  await expect(page.getByRole('heading', { level: 1, name: 'Today' })).toBeVisible({
    timeout: 20000,
  });
  expect(new URL(page.url()).search).toBe('');
  await expect(page.locator('body')).not.toContainText('synthetic-unknown-word');
});

test('the Google connection routes refuse without a session', async ({ page }) => {
  await page.goto('/');
  const required = { detail: 'A local session is required.' };
  const report = await page.request.get('/api/google/connection');
  expect([report.status(), await report.json()]).toEqual([401, required]);
  const save = await page.request.put('/api/google/client', {
    data: { client_id: 'synthetic', client_secret: 'synthetic' },
  });
  expect([save.status(), await save.json()]).toEqual([401, required]);
  const start = await page.request.post('/api/google/connect', {
    form: { capability: 'gmail' },
    maxRedirects: 0,
  });
  expect([start.status(), await start.json()]).toEqual([401, required]);

  // The callback needs no session. On sample data it refuses before reading anything.
  const callback = await page.request.get('/api/google/callback?state=synthetic&code=synthetic', {
    maxRedirects: 0,
  });
  expect(callback.status()).toBe(409);
  expect(callback.headers()['referrer-policy']).toBe('no-referrer');
});
