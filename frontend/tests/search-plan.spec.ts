import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

// A synthetic campaign far in the future: it is always the first one the view selects
// (campaigns are listed newest start date first), and its calendar month never changes.
const START = '2099-01-05'; // a Monday
const END = '2099-02-01';

test('search plan lists, filters and creates tasks and shows the calendar', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Search Plan', exact: true }).first().click();
  await expect(page.getByRole('heading', { level: 1, name: 'Search Plan' })).toBeVisible({
    timeout: 10000,
  });
  if (process.env.NEXTUP_CI_REQUIRE_PROFILE !== '1') return;

  const run = randomUUID().slice(0, 8);
  const created = await page.request.post('/api/campaigns', {
    data: {
      campaign_key: `e2e-plan-${run}`,
      title: `Synthetic plan ${run}`,
      start_date: START,
      end_date: END,
    },
  });
  expect(created.status()).toBe(201);
  const campaign = await created.json();
  expect(campaign.timezone).toBe('UTC');
  const seeded = `Synthetic seeded task ${run}`;
  const first = await page.request.post(`/api/campaigns/${campaign.id}/tasks`, {
    data: { title: seeded, category: 'planning', due_date: '2099-01-06', estimated_minutes: 30 },
  });
  expect(first.status()).toBe(201);

  // Loading: leave the page and come back so the view reads the new campaign.
  await page.getByRole('button', { name: 'Today', exact: true }).first().click();
  await page.getByRole('button', { name: 'Search Plan', exact: true }).first().click();
  await expect(page.getByText(seeded)).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('button', { name: 'Week 1 (1)' })).toBeVisible();
  await expect(page.getByText('Workload Projection (next 3 weeks)')).toBeVisible();

  // The removed section must not come back.
  await expect(page.getByRole('button', { name: /benefit/i })).toHaveCount(0);
  await expect(page.getByText(/benefits summary/i)).toHaveCount(0);

  // Filtering.
  const status = page.locator('select').filter({ hasText: 'All statuses' });
  await status.selectOption('completed');
  await expect(
    page.getByText('No tasks scheduled for this week with current filters.'),
  ).toBeVisible();
  await expect(page.getByText(seeded)).toHaveCount(0);
  await status.selectOption('');
  await expect(page.getByText(seeded)).toBeVisible();

  // Creating a task through the form.
  const added = `Synthetic added task ${run}`;
  await page.getByRole('button', { name: 'Add Task' }).click();
  await page.getByLabel('Title').fill(added);
  await page.getByLabel('Due date').fill('2099-01-07');
  await page.getByLabel('Estimated minutes').fill('45');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByText('Task created.')).toBeVisible();
  await expect(page.getByText(added)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Week 1 (2)' })).toBeVisible();
  const stored = await (await page.request.get(`/api/campaigns/${campaign.id}/tasks`)).json();
  expect(stored.map((t: { title: string }) => t.title).sort()).toEqual([added, seeded].sort());

  // Calendar.
  await page.getByRole('button', { name: 'Calendar', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'January 2099' })).toBeVisible();
  await expect(page.getByText(seeded.slice(0, 30))).toBeVisible();
  await page.getByRole('button', { name: 'Next →' }).click();
  await expect(page.getByRole('heading', { name: 'February 2099' })).toBeVisible();
});
