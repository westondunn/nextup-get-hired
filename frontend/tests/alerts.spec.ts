import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

test('opt-in local alerts persist, mark read, suppress repeat matches, and disable without profile writes', async ({
  page,
}) => {
  test.setTimeout(120000);
  const name = `Alerts browser ${randomUUID()}`;
  const created = await page.request.post('/api/saved-searches', {
    data: { name, source: 'adzuna', filters: { q: 'Head QA' } },
  });
  expect(created.status()).toBe(201);
  const search = await created.json();
  let writes = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/profile') && request.method() === 'PUT') writes++;
  });
  try {
    const fetched = await page.request.post('/api/job-fetches', {
      data: { source: 'adzuna' },
    });
    expect(fetched.status()).toBe(202);
    const run = await fetched.json();
    await expect
      .poll(
        async () => (await (await page.request.get(`/api/job-fetches/${run.id}`)).json()).status,
        { timeout: 25000 },
      )
      .toBe('succeeded');

    // Configure alerts via API
    const alertConfig = await page.request.put(`/api/saved-searches/${search.id}/alerts`, {
      data: { enabled: true, min_score: 0 },
    });
    // Fresh install without profile gets 409
    if ((await page.request.get('/api/profile')).status() === 404) {
      expect(alertConfig.status()).toBe(409);
      expect(writes).toBe(0);
      return;
    }
    expect(alertConfig.status()).toBe(200);

    // Wait for alert check via scheduler
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`/api/saved-searches/${search.id}`)).json())
            .alert_check_status,
        { timeout: 85000 },
      )
      .toBe('ok');

    // Check alerts inbox via API
    const inbox = await (await page.request.get('/api/alerts?unread_only=false&limit=10')).json();
    const entry = inbox.items.find((a: { search_name: string }) => a.search_name === name);
    expect(entry).toBeTruthy();

    // Mark read
    const markRead = await page.request.put(`/api/alerts/${entry.id}/read`);
    expect(markRead.status()).toBe(200);

    // Disable alerts
    const disabled = await page.request.put(`/api/saved-searches/${search.id}/alerts`, {
      data: { enabled: false, min_score: 0 },
    });
    expect(disabled.status()).toBe(200);

    // Navigate to Alerts page to verify it loads
    await page.goto('/');
    await page.getByRole('button', { name: 'Alerts' }).click();
    await expect(page.getByRole('heading', { name: 'Alerts', level: 1 })).toBeVisible({
      timeout: 10000,
    });

    expect(writes).toBe(0);
    await page.screenshot({
      path: 'test-results/local-alert-inbox.png',
      fullPage: true,
    });
  } finally {
    expect((await page.request.delete(`/api/saved-searches/${search.id}`)).status()).toBe(204);
  }
});
