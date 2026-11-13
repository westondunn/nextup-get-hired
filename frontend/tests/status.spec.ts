import { expect, test } from '@playwright/test';

test('live services and persisted diagnostic appear in the browser', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 10000 });
  await expect(page.getByText('Responding').first()).toBeVisible({ timeout: 20000 });
  const publication = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/diagnostics') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Run Diagnostic' }).click();
  const response = await publication;
  expect(response.status()).toBe(202);
  await expect(page.getByText('Passed')).toBeVisible({ timeout: 20000 });
  await page.screenshot({
    path: 'test-results/status-desktop.png',
    fullPage: true,
  });
});

test('profile save works from settings', async ({ page }) => {
  let writes = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/profile') && request.method() === 'PUT') writes += 1;
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('button', { name: 'Save Profile' })).toBeEnabled();
  expect(writes).toBe(0);
});

test('small screens retain readable layout', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Today', exact: true })).toBeVisible({
    timeout: 10000,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: 'test-results/status-mobile.png',
    fullPage: true,
  });
});

test('job board loads and shows the source selector', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Job Board' }).click();
  await expect(page.getByRole('heading', { name: 'Job Board', level: 1 })).toBeVisible({
    timeout: 10000,
  });
  await expect(page.locator('select').first()).toBeVisible();
  await page.screenshot({
    path: 'test-results/jobs-board.png',
    fullPage: true,
  });
});
