import { expect, test } from '@playwright/test';

// The browser-test container does not receive the setup code, so these cover the locked
// state and refusals. A successful unlock is covered against the real store by the
// backend live-stack test.

test('integration settings start locked and refuse a wrong code', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  const lock = page.getByRole('region', { name: 'Integrations lock' });
  await expect(lock.getByRole('status')).toHaveText('Locked.', { timeout: 20000 });

  const unlock = lock.getByRole('button', { name: 'Unlock' });
  await expect(unlock).toBeDisabled();
  const code = lock.getByLabel('Setup code');
  await expect(code).toHaveAttribute('type', 'password');
  await code.focus();
  await page.keyboard.type('not-the-setup-code');
  await expect(unlock).toBeEnabled();
  await page.keyboard.press('Enter'); // keyboard only: no pointer needed to submit

  await expect(lock.getByRole('alert')).toHaveText('That code was not accepted.', {
    timeout: 10000,
  });
  await expect(lock.getByRole('status')).toHaveText('Locked.');
  await expect(code).toHaveValue('');
});

test('sync settings cannot be changed or run without a session', async ({ page }) => {
  await page.goto('/');
  const change = await page.request.put('/api/correspondence', { data: { enabled: 'invalid' } });
  expect(change.status()).toBe(401);
  expect(await change.json()).toEqual({ detail: 'A local session is required.' });
  expect((await page.request.post('/api/correspondence/sync')).status()).toBe(401);
  expect((await page.request.get('/api/correspondence')).status()).toBe(200);
});
