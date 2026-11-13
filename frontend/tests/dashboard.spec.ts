import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

test('saved searches CRUD works via API and Job Board loads', async ({ page }) => {
  const name = `Dashboard browser ${randomUUID()}`;
  let savedId: string | undefined;
  // Refresh via API
  const publication = await page.request.post('/api/job-fetches', {
    data: { source: 'adzuna' },
  });
  // An earlier test may have fetched within the rate-limit window.
  expect([202, 429]).toContain(publication.status());
  if (publication.status() === 202) {
    const run = await publication.json();
    await expect
      .poll(
        async () => (await (await page.request.get(`/api/job-fetches/${run.id}`)).json()).status,
        { timeout: 25000 },
      )
      .toBe('succeeded');
  }

  let unrelatedWrites = 0;
  page.on('request', (request) => {
    if (
      (request.url().endsWith('/api/profile') && request.method() === 'PUT') ||
      (request.url().endsWith('/api/job-fetches') && request.method() === 'POST')
    )
      unrelatedWrites++;
  });

  try {
    // Create saved search via API
    const created = await page.request.post('/api/saved-searches', {
      data: {
        name,
        source: 'adzuna',
        include_expired: true,
        filters: { q: 'Head QA' },
      },
    });
    expect(created.status()).toBe(201);
    savedId = (await created.json()).id;

    // Load and verify via API
    const loaded = await (await page.request.get(`/api/saved-searches/${savedId}`)).json();
    expect(loaded.name).toBe(name);

    // Update via API
    const updated = await page.request.put(`/api/saved-searches/${savedId}`, {
      data: {
        name: `${name} updated`,
        source: 'adzuna',
        include_expired: true,
        filters: { q: 'Head QA' },
      },
    });
    expect(updated.status()).toBe(200);

    // Navigate to Job Board and verify it loads
    await page.goto('/');
    await page.getByRole('button', { name: 'Job Board' }).click();
    await expect(page.getByRole('heading', { name: 'Job Board', level: 1 })).toBeVisible({
      timeout: 10000,
    });

    // Delete via API
    const deletion = await page.request.delete(`/api/saved-searches/${savedId}`);
    expect(deletion.status()).toBe(204);
    savedId = undefined;

    expect(unrelatedWrites).toBe(0);
    await page.screenshot({
      path: 'test-results/dashboard-saved-search.png',
      fullPage: true,
    });
  } finally {
    if (savedId) {
      const cleanup = await page.request.delete(`/api/saved-searches/${savedId}`);
      expect([204, 404]).toContain(cleanup.status());
    }
  }
});
