import { expect, test } from '@playwright/test';

test('discovery displays readiness and only saves paused synthetic settings in CI', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Discovery' }).click();
  await expect(page.getByRole('heading', { name: 'Discovery', exact: true })).toBeVisible({
    timeout: 10000,
  });
  await expect(page.getByRole('button', { name: 'Save settings' })).toBeVisible();
  if (process.env.NEXTUP_CI_REQUIRE_PROFILE !== '1') return;
  await expect(page.getByRole('button', { name: 'Find jobs now' })).toBeDisabled();
  await page.getByLabel('Affirm (greenhouse)').check();
  await page.getByLabel('Search employers').fill('gitlab');
  await expect(page.getByLabel('Affirm (greenhouse)')).toHaveCount(0);
  await page.getByLabel('GitLab (greenhouse)').check();
  await expect(page.getByRole('link', { name: 'GitLab public careers board' })).toHaveAttribute(
    'href',
    'https://job-boards.greenhouse.io/gitlab',
  );
  await page.getByLabel('Search employers').fill('healthcare');
  await page.getByLabel('Included Health (lever)').check();
  await expect(page.getByLabel('GitLab (greenhouse)')).toHaveCount(0);
  await page.getByLabel('Location phrases (one per line)').fill('US\nSynthetic City');
  await page.getByLabel('Leadership matching').selectOption('strict');
  const saved = page.waitForResponse(
    (r) => r.url().endsWith('/api/discovery') && r.request().method() === 'PUT',
  );
  await page.getByRole('button', { name: 'Save settings' }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByText('Saved. Automatic discovery paused.')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Discovery' }).click();
  await expect(page.getByRole('heading', { name: 'Discovery', exact: true })).toBeVisible({
    timeout: 10000,
  });
  await expect(page.getByLabel('Affirm (greenhouse)')).toBeChecked();
  await expect(page.getByLabel('GitLab (greenhouse)')).toBeChecked();
  await expect(page.getByLabel('Included Health (lever)')).toBeChecked();
  await expect(page.getByText('Employer sources (3/40)')).toBeVisible();
  await expect(page.getByLabel('Location phrases (one per line)')).toHaveValue(
    'US\nSynthetic City',
  );
  await expect(page.getByLabel('Leadership matching')).toHaveValue('strict');
  await expect(page.getByRole('button', { name: 'Find jobs now' })).toBeDisabled();
  await page.screenshot({ path: 'test-results/discovery.png' });
  // Return only CI's synthetic configuration to empty/paused for the following tests.
  expect(
    (
      await page.request.put('/api/discovery', {
        data: { enabled: false, boards: [], match_preferences: {} },
      })
    ).status(),
  ).toBe(200);
});
