import { expect, test } from '@playwright/test';

test('career workspace persists a synthetic application and recorded contact without sending', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Applications', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Applications' })).toBeVisible({ timeout: 10000 });
  if (process.env.NEXTUP_CI_REQUIRE_PROFILE !== '1') return;
  const seed = await page.request.post('/api/job-references', {
    data: {
      title: 'Synthetic Career QA Director',
      company: 'Synthetic Career Company',
      location: 'US Remote',
      description: 'Python test automation synthetic listing.',
      url: 'https://example.invalid/career-workflow',
    },
  });
  expect(seed.status()).toBe(201);
  const reference = await seed.json();
  const tracked = await page.request.post('/api/career/pursuits', {
    data: reference,
  });
  expect(tracked.status()).toBe(200);
  const pursuit = await tracked.json();

  // Verify career workspace has the pursuit
  const workspace = await (await page.request.get('/api/career')).json();
  const found = workspace.items.find((p: { id: string }) => p.id === pursuit.id);
  expect(found).toBeTruthy();
  expect(found.stage).toBe('review');

  // Record a contact via API
  const contact = await page.request.post(`/api/career/pursuits/${pursuit.id}/contact`, {
    data: { version: found.version, note: 'Synthetic browser contact' },
  });
  expect(contact.status()).toBe(200);

  await page.screenshot({
    path: 'test-results/career-workspace.png',
    fullPage: true,
  });
});
