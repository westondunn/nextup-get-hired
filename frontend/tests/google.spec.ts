import { expect, type Page, test } from '@playwright/test';
import type { CorrespondenceSettings } from '../src/hub/correspondence-api';
import type { GoogleConnection } from '../src/hub/google-api';

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

  const testGrant = await page.request.post('/api/google/connection/test');
  expect([testGrant.status(), await testGrant.json()]).toEqual([401, required]);
  const disconnect = await page.request.delete('/api/google/connection');
  expect([disconnect.status(), await disconnect.json()]).toEqual([401, required]);

  // The callback needs no session. On sample data it refuses before reading anything.
  const callback = await page.request.get('/api/google/callback?state=synthetic&code=synthetic', {
    maxRedirects: 0,
  });
  expect(callback.status()).toBe(409);
  expect(callback.headers()['referrer-policy']).toBe('no-referrer');
});

const inactiveSync: GoogleConnection['sync']['gmail'] = {
  active: false,
  last_attempt_at: null,
  last_status: 'not_run',
  last_success_at: null,
  freshness: 'inactive',
};
const noConnection: GoogleConnection = {
  available: true,
  unavailable_reason: null,
  client_configured: false,
  client_id: null,
  state: 'not_configured',
  enabled_capabilities: ['gmail', 'calendar'],
  granted_capabilities: [],
  account_address: null,
  credential_source: 'none',
  sync: { gmail: inactiveSync, calendar: inactiveSync },
};
const storedConnection: GoogleConnection = {
  ...noConnection,
  client_configured: true,
  client_id: 'synthetic.apps.googleusercontent.com',
  state: 'connected',
  granted_capabilities: ['gmail'],
  account_address: 'synthetic@example.invalid',
  credential_source: 'stored',
  sync: {
    gmail: {
      active: true,
      last_attempt_at: '2026-11-20T12:10:00Z',
      last_status: 'temporarily_unavailable',
      last_success_at: '2026-11-20T12:00:00Z',
      freshness: 'stale',
    },
    calendar: inactiveSync,
  },
};

async function mockGoogle(page: Page, baseURL: string | undefined) {
  const origin = new URL(baseURL ?? 'http://127.0.0.1:15173').origin;
  const fixture = {
    active: false,
    connection: storedConnection,
    readFailed: false,
    expireOnTest: false,
    waitForTest: Promise.resolve(),
    consentBody: null as string | null,
    syncReads: 0,
    calls: [] as string[],
    external: [] as string[],
  };
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.origin !== origin) {
      fixture.external.push(url.origin);
      return route.abort();
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();

    const action = `${method} ${url.pathname}`;
    if (url.pathname.startsWith('/api/google/')) fixture.calls.push(action);
    switch (action) {
      case 'GET /api/session':
        return route.fulfill({ json: { configured: true, active: fixture.active } });
      case 'POST /api/session':
        expect(route.request().postDataJSON()).toEqual({ code: 'synthetic-setup-code' });
        fixture.active = true;
        return route.fulfill({ status: 204 });
      case 'GET /api/google/connection':
        return fixture.readFailed
          ? route.fulfill({ status: 503, json: { detail: 'Synthetic status unavailable.' } })
          : route.fulfill({ json: fixture.connection });
      case 'POST /api/google/connection/test':
        await fixture.waitForTest;
        if (fixture.expireOnTest) {
          fixture.active = false;
          return route.fulfill({
            status: 401,
            json: { detail: 'A local session is required.' },
          });
        }
        return route.fulfill({
          json: {
            result: 'complete',
            capabilities: { gmail: 'ok', calendar: 'not_granted' },
            connection: fixture.connection,
          },
        });
      case 'POST /api/google/connect':
        fixture.consentBody = route.request().postData();
        return route.fulfill({ status: 303, headers: { Location: '/?google=declined' } });
      case 'DELETE /api/google/connection':
        fixture.connection = noConnection;
        return route.fulfill({
          json: {
            result: 'disconnected',
            revocation: 'unconfirmed',
            warning:
              'Removal at Google could not be confirmed. You can check or remove access under ' +
              'third-party access in your Google Account. Removing a shared grant can affect other credentials.',
            connection: fixture.connection,
          },
        });
      case 'GET /api/correspondence': {
        fixture.syncReads += 1;
        const { granted_capabilities: granted, sync } = fixture.connection;
        const settings: CorrespondenceSettings = {
          enabled: sync.gmail.active,
          calendar_enabled: sync.calendar.active,
          credentials_present: granted.includes('gmail'),
          calendar_credentials_present: granted.includes('calendar'),
          live_enabled: true,
          calendar_live_enabled: true,
          interval_seconds: 300,
          calendar_interval_seconds: 300,
          query: 'label:synthetic',
          max_messages_per_run: 25,
          calendar_lookahead_days: 14,
          auto_create_applications: false,
          last_run_at: null,
          last_status: 'not_run',
          last_error: '',
          last_imported: 0,
          cursor_epoch: null,
          calendar_last_run_at: null,
          calendar_last_status: 'not_run',
          calendar_last_error: '',
          calendar_last_imported: 0,
          review_count: 0,
        };
        return route.fulfill({ json: settings });
      }
      case 'GET /api/today':
        return route.fulfill({ json: { campaign: null } });
      default:
        // Other Settings panels are outside this scenario. Nothing falls through to an API.
        return route.fulfill({ status: 404, json: { detail: 'Not used by this browser test.' } });
    }
  });
  return fixture;
}

async function openGoogleSettings(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: 'Today' })).toBeVisible();
  const openNavigation = page.getByRole('button', { name: 'Open navigation' });
  if (await openNavigation.isVisible()) await openNavigation.press('Enter');
  await page.getByRole('button', { name: 'Settings', exact: true }).press('Enter');
  const lock = page.getByRole('region', { name: 'Integrations lock' });
  const card = page.getByRole('region', { name: 'Google connection' });
  return { lock, card };
}

test('@google-mock partial grant, stale sync and keyboard disconnect confirmation', async ({
  page,
  baseURL,
}) => {
  const fixture = await mockGoogle(page, baseURL);
  const { lock, card } = await openGoogleSettings(page);
  await expect(card).toContainText('Locked. Unlock integrations above');
  expect(fixture.calls).toEqual([]);
  await lock.getByLabel('Setup code').fill('synthetic-setup-code');
  await lock.getByLabel('Setup code').press('Enter');
  await expect(card).toContainText('synthetic@example.invalid');
  await expect(card).toContainText(/not granted.*calendar|calendar.*not granted/i);
  await expect(card).toContainText(/stale/i);
  const gmailSync = page.getByRole('checkbox', { name: 'Enable Gmail sync' });
  const calendarSync = page.getByRole('checkbox', { name: 'Enable Calendar sync' });
  await expect(gmailSync).toBeChecked();
  await expect(calendarSync).not.toBeChecked();

  const testConnection = card.getByRole('button', { name: /test connection/i });
  await testConnection.press('Enter');
  const testResults = card.getByRole('region', { name: 'Connection test results' });
  await expect(testResults).toContainText('Gmail');
  await expect(testResults).toContainText('Calendar');
  expect(fixture.calls).toContain('POST /api/google/connection/test');

  const disconnect = card.getByRole('button', {
    name: 'Disconnect Google connection',
    exact: true,
  });
  await disconnect.press('Enter');
  const confirmation = card.getByRole('group', { name: 'Disconnect Google connection?' });
  const cancel = confirmation.getByRole('button', { name: 'Cancel' });
  await expect(cancel).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(confirmation).not.toBeVisible();
  await expect(disconnect).toBeFocused();
  expect(fixture.calls).not.toContain('DELETE /api/google/connection');

  await page.keyboard.press('Enter');
  await expect(cancel).toBeFocused();
  await page.keyboard.press('Tab');
  const confirm = confirmation.getByRole('button', { name: 'Confirm disconnect' });
  await expect(confirm).toBeFocused();
  const earlierSyncReads = fixture.syncReads;
  await page.keyboard.press('Enter');
  await expect(confirmation).not.toBeVisible();
  await expect(card).toContainText('Removal at Google could not be confirmed.');
  await expect(card.getByRole('heading', { name: 'Google connection' })).toBeFocused();
  await expect(card.getByRole('link', { name: /manage third-party access/i })).toBeVisible();
  await expect(card).not.toContainText('synthetic@example.invalid');
  await expect(gmailSync).not.toBeChecked();
  await expect(calendarSync).not.toBeChecked();
  expect(fixture.syncReads).toBeGreaterThan(earlierSyncReads);
  expect(fixture.calls.filter((method) => method.startsWith('DELETE'))).toHaveLength(1);
  expect(fixture.external).toEqual([]);
});

test('@google-mock unavailable status offers a safe retry and switched-off has no actions', async ({
  page,
  baseURL,
}) => {
  const fixture = await mockGoogle(page, baseURL);
  fixture.active = true;
  fixture.readFailed = true;
  const { card } = await openGoogleSettings(page);
  await expect(card).toContainText(/connection status unknown|could not be read/i);
  await expect(card.getByRole('button', { name: /test|reauthorize|disconnect/i })).toHaveCount(0);
  fixture.readFailed = false;
  fixture.connection = {
    ...noConnection,
    available: false,
    unavailable_reason: 'switched_off',
    enabled_capabilities: [],
  };
  const priorReads = fixture.calls.length;
  await card.getByRole('button', { name: 'Refresh status' }).press('Enter');
  await expect(card).toContainText(/switched off/i);
  await expect(card.getByRole('button', { name: /test|reauthorize|disconnect/i })).toHaveCount(0);
  expect(fixture.calls.length).toBeGreaterThan(priorReads);
  expect(fixture.calls.every((call) => call === 'GET /api/google/connection')).toBe(true);
  expect(fixture.external).toEqual([]);
});

test('@google-mock a pending probe preserves edits to the Gmail sync query', async ({
  page,
  baseURL,
}) => {
  const fixture = await mockGoogle(page, baseURL);
  fixture.active = true;
  let finishProbe!: () => void;
  fixture.waitForTest = new Promise<void>((resolve) => {
    finishProbe = resolve;
  });
  const { card } = await openGoogleSettings(page);
  const earlierReads = fixture.syncReads;
  await card.getByRole('button', { name: 'Test connection' }).click();
  const query = page.getByRole('textbox', { name: 'Gmail search query' });
  await query.fill('label:my-unsaved-filter');
  const updatedSettings = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/correspondence' &&
      response.request().method() === 'GET',
  );
  finishProbe();
  await updatedSettings;
  await expect(card.getByRole('region', { name: 'Connection test results' })).toBeVisible();
  expect(fixture.syncReads).toBeGreaterThan(earlierReads);
  await expect(query).toBeFocused();
  await expect(query).toHaveValue('label:my-unsaved-filter');
  expect(fixture.external).toEqual([]);
});

test('@google-mock an expired session during Test hides stored status and usable actions', async ({
  page,
  baseURL,
}) => {
  const fixture = await mockGoogle(page, baseURL);
  fixture.active = true;
  fixture.expireOnTest = true;
  const { lock, card } = await openGoogleSettings(page);
  await card.getByRole('button', { name: /test connection/i }).press('Enter');
  await expect(card).toContainText(/lock.*closed|unlock integrations/i);
  await expect(lock.getByLabel('Setup code')).toBeVisible();
  await expect(lock.getByLabel('Setup code')).toBeFocused();
  await expect(lock.getByRole('button', { name: 'Unlock', exact: true })).toBeDisabled();
  await expect(page.getByRole('checkbox', { name: 'Enable Gmail sync' })).toBeDisabled();
  await expect(card).not.toContainText('synthetic@example.invalid');
  await expect(card.getByRole('button', { name: /test connection|disconnect/i })).toHaveCount(0);
  expect(fixture.calls).toContain('POST /api/google/connection/test');
  expect(fixture.external).toEqual([]);
});

test('@google-mock connected card and confirmation reflow at 320 CSS pixels', async ({
  page,
  baseURL,
}) => {
  await page.setViewportSize({ width: 320, height: 840 });
  const fixture = await mockGoogle(page, baseURL);
  fixture.active = true;
  const { card } = await openGoogleSettings(page);
  await expect(card).toContainText('synthetic@example.invalid');
  const disconnect = card.getByRole('button', {
    name: 'Disconnect Google connection',
    exact: true,
  });
  await disconnect.press('Enter');
  const confirmation = card.getByRole('group', { name: 'Disconnect Google connection?' });
  await expect(confirmation).toBeVisible();
  for (const region of [card, confirmation]) {
    const horizontalOverflow = await region.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    );
    expect(horizontalOverflow).toBe(false);
  }
  await expect(confirmation.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(disconnect).toBeFocused();
  expect(fixture.calls).not.toContain('DELETE /api/google/connection');
  expect(fixture.external).toEqual([]);
});

test('@google-mock reauthorization uses the existing browser form and reports a declined flow', async ({
  page,
  baseURL,
}) => {
  const fixture = await mockGoogle(page, baseURL);
  fixture.active = true;
  fixture.connection = { ...storedConnection, state: 'needs_reauthorization' };
  const { card } = await openGoogleSettings(page);
  await expect(card).toContainText(/authori[sz]ed again|reauthorization/i);
  await card.getByRole('button', { name: 'Reauthorize Google account' }).press('Enter');
  await expect(card).toContainText('Access was declined at Google. Nothing was changed.');
  expect(new URL(page.url()).search).toBe('');
  expect(fixture.calls.filter((call) => call === 'POST /api/google/connect')).toHaveLength(1);
  expect(new URLSearchParams(fixture.consentBody ?? '').getAll('capability')).toContain('gmail');
  expect(fixture.calls).not.toContain('DELETE /api/google/connection');
  expect(fixture.external).toEqual([]);
});
