import { expect, test } from '@playwright/test';

test('task-history preview is read-only; isolated CI confirms and verifies synthetic cleanup', async ({
  page,
}) => {
  let cleanupRequests = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/task-history/cleanup')) cleanupRequests++;
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 10000 });
  const responsePromise = page.waitForResponse('**/api/task-history/preview');
  await page.getByRole('button', { name: 'Preview cleanup' }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const preview = await response.json();
  await expect(page.getByText(/Diagnostics:/)).toBeVisible();
  expect(cleanupRequests).toBe(0);
  // Normal development tests always stop at the read-only preview, even if enabled.
  if (process.env.NEXTUP_CI_RETENTION !== '1') return;
  expect(preview.enabled).toBe(true);
  expect(preview.groups.diagnostics.items.map((item: { id: string }) => item.id)).toEqual([
    'dddddddd-0000-4000-8000-000000000001',
  ]);
  expect(preview.groups.fetches.items.map((item: { id: string }) => item.id)).toEqual([
    'ffffffff-0000-4000-8000-000000000001',
  ]);
  const profile = await (await page.request.get('/api/profile')).json();
  const jobs = await (
    await page.request.get('/api/jobs?source=adzuna&include_expired=true')
  ).json();
  const button = page.getByRole('button', { name: 'Delete previewed history' });
  await expect(button).toBeDisabled();
  await page.screenshot({ path: 'test-results/task-history-preview.png' });
  await page.getByRole('checkbox', { name: /deletes the previewed history/ }).check();
  const cleaned = page.waitForResponse('**/api/task-history/cleanup');
  await button.click();
  expect((await cleaned).status()).toBe(200);
  await expect(page.getByRole('status')).toContainText(
    'Deleted 1 diagnostics and 1 fetch records. Skipped 0',
  );
  expect(cleanupRequests).toBe(1);
  expect(
    (await page.request.get('/api/diagnostics/dddddddd-0000-4000-8000-000000000001')).status(),
  ).toBe(404);
  expect(
    (await page.request.get('/api/job-fetches/ffffffff-0000-4000-8000-000000000001')).status(),
  ).toBe(404);
  expect(
    (await page.request.get('/api/diagnostics/dddddddd-0000-4000-8000-000000000002')).status(),
  ).toBe(200);
  expect(
    (await page.request.get('/api/job-fetches/ffffffff-0000-4000-8000-000000000002')).status(),
  ).toBe(200);
  expect(await (await page.request.get('/api/profile')).json()).toEqual(profile);
  expect(
    await (await page.request.get('/api/jobs?source=adzuna&include_expired=true')).json(),
  ).toEqual(jobs);
  await page.screenshot({ path: 'test-results/task-history.png' });
});
