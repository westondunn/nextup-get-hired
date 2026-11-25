import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { GoogleConnectionCard } from './GoogleConnectionCard';
import { type GoogleConnection, resultMessages } from './google-api';

const CLIENT_ID = '123456789012-synthetic0client.apps.googleusercontent.com';
const SECRET = 'SYNTHETIC-client-secret-for-tests-only';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

const connection = (changes: Partial<GoogleConnection> = {}): GoogleConnection => ({
  available: true,
  unavailable_reason: null,
  client_configured: false,
  client_id: null,
  state: 'not_configured',
  enabled_capabilities: ['gmail', 'calendar'],
  granted_capabilities: [],
  account_address: null,
  credential_source:
    changes.state && ['connected', 'needs_reauthorization', 'unreadable'].includes(changes.state)
      ? 'stored'
      : 'none',
  sync: {
    gmail: {
      active: false,
      last_attempt_at: null,
      last_success_at: null,
      last_status: 'not_run',
      freshness: 'inactive',
    },
    calendar: {
      active: false,
      last_attempt_at: null,
      last_success_at: null,
      last_status: 'not_run',
      freshness: 'inactive',
    },
  },
  ...changes,
});
const withClient = (changes: Partial<GoogleConnection> = {}) =>
  connection({ client_configured: true, client_id: CLIENT_ID, state: 'not_connected', ...changes });

function stubFetch(...responses: Response[]) {
  const fetch = vi.fn();
  for (const response of responses) fetch.mockResolvedValueOnce(response);
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

let submit: ReturnType<typeof vi.fn>;
beforeEach(() => {
  // jsdom does not navigate; record that the browser was asked to post the form.
  submit = vi.fn();
  HTMLFormElement.prototype.submit = submit as unknown as () => void;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const card = () => screen.getByRole('region', { name: 'Google connection' });
const text = () => card().textContent ?? '';
const clientId = () => screen.getByLabelText('Client ID') as HTMLInputElement;
const clientSecret = () => screen.getByLabelText('Client secret') as HTMLInputElement;
const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement;
const box = (name: string) => screen.getByRole('checkbox', { name }) as HTMLInputElement;

it('asks for nothing and reads nothing while integrations are locked', () => {
  const fetch = stubFetch();
  render(<GoogleConnectionCard sessionActive={false} />);
  expect(text()).toContain('Locked. Unlock integrations above');
  expect(fetch).not.toHaveBeenCalled();
  expect(card().querySelector('form')).toBeNull();
});

it.each([
  ['fixture_mode', 'uses bundled sample data only'],
  ['switched_off', 'switched off in this installation'],
  ['no_key', 'No encryption key is configured'],
] as const)('says why no account can be connected: %s', async (reason, sentence) => {
  stubFetch(json(connection({ available: false, unavailable_reason: reason })));
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain(sentence));
  expect(card().querySelector('form')).toBeNull();
});

it('offers the client form first, and no way to connect before a client is saved', async () => {
  const fetch = stubFetch(json(connection()));
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('No Google client is saved.'));
  expect(fetch.mock.calls[0][0]).toBe('/api/google/connection');
  expect(clientSecret().type).toBe('password');
  expect(clientSecret().getAttribute('autocomplete')).toBe('off');
  expect(button('Save client').disabled).toBe(true);
  fireEvent.change(clientId(), { target: { value: CLIENT_ID } });
  expect(button('Save client').disabled).toBe(true); // both values are needed
  expect(screen.queryByRole('button', { name: 'Connect Google account' })).toBeNull();
  expect(card().querySelectorAll('form').length).toBe(1);
});

it('saves the client once, forgets the secret and never shows it', async () => {
  const fetch = stubFetch(json(connection()), json(withClient()));
  const { container } = render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('No Google client is saved.'));
  fireEvent.change(clientId(), { target: { value: `  ${CLIENT_ID} ` } });
  fireEvent.change(clientSecret(), { target: { value: SECRET } });
  fireEvent.submit(clientSecret().closest('form')!);

  await waitFor(() => expect(text()).toContain('The Google client is saved.'));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][0]).toBe('/api/google/client');
  expect(fetch.mock.calls[1][1].method).toBe('PUT');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    client_id: CLIENT_ID,
    client_secret: SECRET,
  });
  expect(clientSecret().value).toBe('');
  expect(clientId().value).toBe('');
  expect(text()).toContain(`Saved client: ${CLIENT_ID}`);
  expect(container.innerHTML).not.toContain(SECRET);
  expect(button('Connect Google account')).toBeTruthy();
});

it.each([
  [422, 'The client ID must be the full value ending in .apps.googleusercontent.com.'],
  [
    409,
    'A Google account is connected with the current client. Disconnect it before saving a different client ID.',
  ],
  [503, 'No encryption key is configured, so a Google client cannot be stored.'],
])('shows the fixed refusal of a save and forgets the secret: %i', async (status, detail) => {
  stubFetch(json(connection()), json({ detail }, status));
  const { container } = render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('No Google client is saved.'));
  fireEvent.change(clientId(), { target: { value: 'not-a-client-id' } });
  fireEvent.change(clientSecret(), { target: { value: SECRET } });
  fireEvent.submit(clientSecret().closest('form')!);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe(detail));
  expect(clientSecret().value).toBe('');
  expect(clientId().value).toBe('not-a-client-id'); // kept, so it can be corrected
  expect(container.innerHTML).not.toContain(SECRET);
});

it('tells the user to unlock again when the session has ended', async () => {
  stubFetch(json(connection()), json({ detail: 'A local session is required.' }, 401));
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('No Google client is saved.'));
  fireEvent.change(clientId(), { target: { value: CLIENT_ID } });
  fireEvent.change(clientSecret(), { target: { value: SECRET } });
  fireEvent.submit(clientSecret().closest('form')!);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Unlock it again'));
});

it('builds a form that the browser posts to the start route', async () => {
  stubFetch(json(withClient({ enabled_capabilities: ['calendar'] })));
  render(<GoogleConnectionCard sessionActive />);
  const connect = await screen.findByRole('button', { name: 'Connect Google account' });
  const form = connect.closest('form')!;
  expect(form.getAttribute('method')).toBe('post');
  expect(form.getAttribute('action')).toBe('/api/google/connect');
  // Only what the installation allows is offered, and it is a real form field.
  expect(screen.queryByRole('checkbox', { name: 'Gmail (read-only)' })).toBeNull();
  const calendar = box('Calendar (read-only)');
  expect([calendar.name, calendar.value, calendar.checked]).toEqual([
    'capability',
    'calendar',
    true,
  ]);
  // The exact address to register for the client, for the way this page was opened.
  expect(text()).toContain(`${window.location.origin}/api/google/callback`);
  fireEvent.click(calendar);
  expect((connect as HTMLButtonElement).disabled).toBe(true); // nothing to ask for
});

it('checks the lock and the connection, then lets the browser post the form', async () => {
  const fetch = stubFetch(
    json(withClient()),
    json({ configured: true, active: true }),
    json(withClient()),
  );
  render(<GoogleConnectionCard sessionActive />);
  const connect = await screen.findByRole('button', { name: 'Connect Google account' });
  fireEvent.click(box('Calendar (read-only)')); // ask for Gmail only
  fireEvent.submit(connect.closest('form')!);
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(fetch.mock.calls.slice(1).map((call) => call[0])).toEqual([
    '/api/session',
    '/api/google/connection',
  ]);
  const posted = [...new FormData(connect.closest('form')!).entries()];
  expect(posted).toEqual([['capability', 'gmail']]);
  expect(screen.queryByRole('alert')).toBeNull();
});

it.each([
  [
    'the lock has closed',
    json({ configured: true, active: false }),
    json(withClient()), // would be accepted; it must not be asked for
    'The integrations lock has closed.',
  ],
  [
    'connections became unavailable',
    json({ configured: true, active: true }),
    json(withClient({ available: false, unavailable_reason: 'switched_off' })),
    'cannot be started right now',
  ],
  [
    'a capability was switched off',
    json({ configured: true, active: true }),
    json(withClient({ enabled_capabilities: ['calendar'] })),
    'cannot be started right now',
  ],
  [
    'the session is refused',
    json({ configured: true, active: true }),
    json({ detail: 'A local session is required.' }, 401),
    'The integrations lock has closed.',
  ],
])('does not leave the page when %s', async (_case, session, after, message) => {
  const fetch = stubFetch(json(withClient()), session, after);
  render(<GoogleConnectionCard sessionActive />);
  const connect = await screen.findByRole('button', { name: 'Connect Google account' });
  fireEvent.submit(connect.closest('form')!);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain(message));
  expect(submit).not.toHaveBeenCalled();
  expect(fetch.mock.calls.length).toBe(_case === 'the lock has closed' ? 2 : 3);
});

it('shows the account, what Google granted and what it did not', async () => {
  stubFetch(
    json(
      withClient({
        state: 'connected',
        granted_capabilities: ['calendar'],
        account_address: 'person@example.test',
      }),
    ),
  );
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('Connected as person@example.test.'));
  expect(text()).toContain('Google granted: Calendar.');
  expect(text()).toContain('Not granted: Gmail. Reauthorize to request access.');
  expect(button('Reauthorize Google account')).toBeTruthy();
});

it('does not mention what was not granted when everything allowed was', async () => {
  stubFetch(
    json(
      withClient({
        state: 'connected',
        enabled_capabilities: ['gmail'],
        granted_capabilities: ['gmail', 'calendar'],
        account_address: 'person@example.test',
      }),
    ),
  );
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('Google granted: Gmail and Calendar.'));
  expect(text()).not.toContain('Not granted');
});

it('offers to connect again when the connection needs reauthorization', async () => {
  stubFetch(json(withClient({ state: 'needs_reauthorization' })));
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('has to be authorized again'));
  expect(button('Reauthorize Google account')).toBeTruthy();
});

it('asks for the client again when the stored connection cannot be read', async () => {
  stubFetch(json(withClient({ state: 'unreadable' })));
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() => expect(text()).toContain('cannot be read with the current encryption key'));
  expect(button('Save client')).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Connect/ })).toBeNull();
});

it.each(Object.entries(resultMessages))(
  'shows the fixed sentence for the outcome %s',
  async (word, sentence) => {
    stubFetch(json(withClient()));
    render(<GoogleConnectionCard sessionActive result={word as keyof typeof resultMessages} />);
    await waitFor(() => expect(text()).toContain(sentence));
  },
);

it('shows the outcome even while integrations are locked', () => {
  stubFetch();
  render(<GoogleConnectionCard sessionActive={false} result="declined" />);
  expect(text()).toContain(resultMessages.declined);
  expect(text()).toContain('Locked.');
});

it('reports a connection that could not be read', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('network'));
  vi.stubGlobal('fetch', fetch);
  render(<GoogleConnectionCard sessionActive />);
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toBe('The Google connection could not be read.'),
  );
  expect(text()).toContain('Connection status unknown.');
});

const managed = (changes: Partial<GoogleConnection> = {}) =>
  withClient({
    state: 'connected',
    credential_source: 'stored',
    account_address: 'person@example.test',
    granted_capabilities: ['gmail'],
    ...changes,
  });
const googleSettings = (name: string) => screen.getByRole('region', { name });
const disconnectName = 'Disconnect Google connection';
const confirmName = 'Confirm disconnect';

it.each(['fixture_mode', 'switched_off', 'no_key'] as const)(
  'still permits removing local credentials while %s prevents provider actions',
  async (reason) => {
    stubFetch(json(managed({ available: false, unavailable_reason: reason })));
    render(<GoogleConnectionCard sessionActive />);
    await screen.findByRole('button', { name: disconnectName });
    expect(screen.queryByRole('button', { name: 'Reauthorize Google account' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Test connection' })).toBeNull();
    fireEvent.click(button(disconnectName));
    expect(
      screen.getByRole('group', { name: 'Disconnect Google connection?' }).textContent,
    ).toContain('confirm removal at Google');
  },
);

it('distinguishes external-only credentials from a saved client without a grant', async () => {
  const fallback = connection({ credential_source: 'configured' });
  const fetch = stubFetch(json(fallback), json(withClient({ credential_source: 'configured' })));
  render(<GoogleConnectionCard sessionActive />);
  await screen.findByText(/managed in the installation configuration/);
  expect(screen.queryByRole('button', { name: disconnectName })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Test connection' })).toBeNull();
  fireEvent.click(button('Refresh status'));
  fireEvent.click(await screen.findByRole('button', { name: disconnectName }));
  expect(
    screen.getByRole('group', { name: 'Disconnect Google connection?' }).textContent,
  ).toContain('credentials in your installation configuration remain');
  expect(screen.queryByRole('button', { name: 'Test connection' })).toBeNull();
  expect(fetch.mock.calls.map((c) => c[0])).toEqual([
    '/api/google/connection',
    '/api/google/connection',
  ]);
});

it.each([
  ['stale', 'Stale'],
  ['current', 'Current'],
  ['unknown', 'Unknown'],
  ['inactive', 'Inactive'],
] as const)(
  'reports %s sync freshness alongside its last attempt and success',
  async (freshness, label) => {
    const hasHistory = ['stale', 'current'].includes(freshness);
    const stamp = '2026-11-24T12:00:00Z';
    const report = managed();
    report.sync.gmail = {
      active: freshness !== 'inactive',
      freshness,
      last_status: 'temporarily_unavailable',
      last_attempt_at: stamp,
      last_success_at: hasHistory ? stamp : null,
    };
    stubFetch(json(report));
    render(<GoogleConnectionCard sessionActive />);
    const area = await screen.findByRole('region', { name: 'Gmail sync' });
    expect(area.textContent).toContain('Freshness: ' + label);
    expect(area.textContent).toContain('Try again later');
    expect(area.querySelectorAll('time')).toHaveLength(hasHistory ? 2 : 1);
    expect(!hasHistory && area.textContent?.includes('No verified success')).toBe(!hasHistory);
    expect(googleSettings('Calendar sync').textContent).toContain('Sync off');
  },
);

it.each([
  ['ok', 'Read-only access verified'],
  ['not_granted', 'Not granted'],
  ['wrong_scope', 'grant read-only access'],
  ['needs_reauthorization', 'Reauthorize the Google account'],
  ['admin_restricted', 'administrator'],
  ['temporarily_unavailable', 'Try again later'],
  ['provider_rejected', 'Google refused'],
  ['disabled', 'Disabled in this installation'],
] as const)('shows the fixed per-capability test outcome %s', async (code, message) => {
  const stored = managed();
  const changed = vi.fn();
  const fetch = stubFetch(
    json(stored),
    json({
      result: 'complete',
      capabilities: { gmail: code, calendar: 'not_granted' },
      connection: stored,
    }),
  );
  render(<GoogleConnectionCard sessionActive onConnectionChanged={changed} />);
  const test = await screen.findByRole('button', { name: 'Test connection' });
  expect(test.getAttribute('aria-describedby')).toBeTruthy();
  fireEvent.click(test);
  const results = await screen.findByRole('region', { name: 'Connection test results' });
  expect(within(results).getByText(new RegExp('^Gmail: .*' + message))).toBeTruthy();
  expect(within(results).getByText(/^Calendar: Not granted/)).toBeTruthy();
  expect(googleSettings('Gmail sync').textContent).toContain('No verified success');
  expect(fetch.mock.calls[1][0]).toBe('/api/google/connection/test');
  expect(changed.mock.calls).toEqual([['test']]);
});

it('announces busy test refusal and permits retry without displaying the server message', async () => {
  const stored = managed();
  stubFetch(
    json(stored),
    json({ detail: { code: 'busy', message: SECRET } }, 409),
    json({
      result: 'complete',
      capabilities: { gmail: 'ok', calendar: 'not_granted' },
      connection: stored,
    }),
  );
  render(<GoogleConnectionCard sessionActive />);
  fireEvent.click(await screen.findByRole('button', { name: 'Test connection' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Try again');
  expect(text()).not.toContain(SECRET);
  fireEvent.click(button('Test connection'));
  expect(await screen.findByRole('region', { name: 'Connection test results' })).toBeTruthy();
});

it('places focus on the callback outcome, Cancel on confirmation, and restores the trigger on Escape', async () => {
  const fetch = stubFetch(json(managed()));
  render(<GoogleConnectionCard sessionActive result="connected" />);
  expect(document.activeElement?.textContent).toBe(resultMessages.connected);
  const trigger = await screen.findByRole('button', { name: disconnectName });
  fireEvent.click(trigger);
  expect(document.activeElement).toBe(button('Cancel'));
  expect(screen.queryByText(resultMessages.connected)).toBeNull();
  fireEvent.keyDown(button('Cancel'), { key: 'Escape' });
  expect(document.activeElement).toBe(trigger);
  expect(screen.queryByRole('group', { name: 'Disconnect Google connection?' })).toBeNull();
  fireEvent.click(trigger);
  fireEvent.click(button('Cancel'));
  expect(document.activeElement).toBe(trigger);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each([
  ['disconnected', 'confirmed', 'Google confirmed removal of access.'],
  ['disconnected', 'unconfirmed', 'Removal at Google could not be confirmed.'],
  ['disconnected', 'not_applicable', 'removed locally'],
  ['already_disconnected', 'not_applicable', 'already removed'],
] as const)(
  'handles the disconnect result %s / %s without promising wider revocation',
  async (result, revocation, sentence) => {
    const changed = vi.fn();
    const fetch = stubFetch(
      json(managed()),
      json({ result, revocation, warning: SECRET, connection: connection() }),
    );
    render(<GoogleConnectionCard sessionActive onConnectionChanged={changed} />);
    fireEvent.click(await screen.findByRole('button', { name: disconnectName }));
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(button(confirmName));
    await waitFor(() => expect(text()).toContain(sentence));
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Google connection' }));
    expect(screen.queryByRole('button', { name: disconnectName })).toBeNull();
    expect(text()).not.toContain('person@example.test');
    expect(text()).not.toContain(SECRET);
    const removal = screen.queryByRole('link', { name: /Manage third-party access/ });
    expect(removal?.getAttribute('href') ?? null).toBe(
      revocation === 'unconfirmed' ? 'https://myaccount.google.com/connections' : null,
    );
    expect(fetch.mock.calls[1][1].method).toBe('DELETE');
    expect(changed.mock.calls).toEqual([['disconnect']]);
  },
);

it('recovers from an ambiguous disconnect with a local status read before retry', async () => {
  const changed = vi.fn();
  const fetch = stubFetch(json(managed()), json({ detail: SECRET }, 503), json(connection()));
  render(<GoogleConnectionCard sessionActive onConnectionChanged={changed} />);
  fireEvent.click(await screen.findByRole('button', { name: disconnectName }));
  fireEvent.click(button(confirmName));
  expect((await screen.findByRole('alert')).textContent).toContain('disconnect result is unknown');
  expect(text()).not.toContain(SECRET);
  expect(screen.queryByRole('button', { name: disconnectName })).toBeNull();
  expect(changed.mock.calls).toEqual([['disconnect']]);
  fireEvent.click(button('Refresh status'));
  await screen.findByText('No Google client is saved.');
  expect(fetch.mock.calls.map((c) => c[1].method ?? 'GET')).toEqual(['GET', 'DELETE', 'GET']);
});

function pendingResponse() {
  let give!: (result: Response) => void;
  const promise = new Promise<Response>((resolve) => {
    give = resolve;
  });
  return { promise, give };
}

it('forgets secret input when locked, and ignores a Test response from the previous session', async () => {
  const old = pendingResponse();
  const changed = vi.fn();
  const fetch = stubFetch(json(managed()));
  fetch.mockReturnValueOnce(old.promise).mockResolvedValueOnce(json(connection()));
  const view = render(<GoogleConnectionCard sessionActive onConnectionChanged={changed} />);
  const test = await screen.findByRole('button', { name: 'Test connection' });
  fireEvent.click(screen.getByText('Edit saved OAuth client'));
  fireEvent.change(clientSecret(), { target: { value: SECRET } });
  expect(card().innerHTML).not.toContain(SECRET);
  fireEvent.click(test);
  view.rerender(<GoogleConnectionCard sessionActive={false} onConnectionChanged={changed} />);
  expect(text()).not.toContain('person@example.test');
  view.rerender(<GoogleConnectionCard sessionActive onConnectionChanged={changed} />);
  await screen.findByText('No Google client is saved.');
  await act(async () =>
    old.give(
      json({
        result: 'complete',
        capabilities: { gmail: 'ok', calendar: 'ok' },
        connection: managed(),
      }),
    ),
  );
  expect(screen.queryByRole('region', { name: 'Connection test results' })).toBeNull();
  expect(text()).not.toContain('person@example.test');
  expect(clientSecret().value).toBe('');
  expect(changed).not.toHaveBeenCalled();
});

it('rechecks changed sync settings after a Test without losing its results', async () => {
  const probe = pendingResponse();
  const first = managed();
  const newer = managed();
  newer.sync.gmail = { ...newer.sync.gmail, active: true, freshness: 'unknown' };
  const fetch = stubFetch(json(first));
  fetch.mockReturnValueOnce(probe.promise).mockResolvedValueOnce(json(newer));
  const view = render(<GoogleConnectionCard sessionActive syncRevision={1} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Test connection' }));
  view.rerender(<GoogleConnectionCard sessionActive syncRevision={2} />);
  expect(fetch).toHaveBeenCalledTimes(2);
  await act(async () =>
    probe.give(
      json({
        result: 'complete',
        capabilities: { gmail: 'ok', calendar: 'not_granted' },
        connection: first,
      }),
    ),
  );
  await waitFor(() => expect(googleSettings('Gmail sync').textContent).toContain('Sync on'));
  expect(googleSettings('Connection test results').textContent).toContain(
    'Read-only access verified',
  );
});

it.each([false, true])(
  'holds confirmation through a local read and cancels if its target changed: %s',
  async (changed) => {
    const read = pendingResponse();
    const stored = managed();
    const fetch = stubFetch(json(stored));
    fetch.mockReturnValueOnce(read.promise);
    const view = render(<GoogleConnectionCard sessionActive syncRevision={1} />);
    fireEvent.click(await screen.findByRole('button', { name: disconnectName }));
    const cancel = button('Cancel');
    view.rerender(<GoogleConnectionCard sessionActive syncRevision={2} />);
    expect(document.activeElement).toBe(cancel);
    expect(button(confirmName).getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(button(confirmName));
    expect(fetch.mock.calls.map((c) => c[1].method ?? 'GET')).toEqual(['GET', 'GET']);
    await act(async () =>
      read.give(json(changed ? managed({ account_address: 'other@example.test' }) : stored)),
    );
    if (changed) {
      expect(screen.queryByRole('button', { name: confirmName })).toBeNull();
      expect(text()).toContain('Review its current status');
      expect(document.activeElement).toBe(
        screen.getByRole('heading', { name: 'Google connection' }),
      );
    } else {
      expect(document.activeElement).toBe(cancel);
      expect(button(confirmName).getAttribute('aria-disabled')).toBe('false');
    }
  },
);

it('does not start a lifecycle action against a report being refreshed', async () => {
  const read = pendingResponse();
  const fetch = stubFetch(json(managed()));
  fetch.mockReturnValueOnce(read.promise);
  render(<GoogleConnectionCard sessionActive />);
  await screen.findByRole('button', { name: 'Test connection' });
  fireEvent.click(button('Refresh status'));
  expect(button('Test connection').disabled).toBe(true);
  expect(button('Reauthorize Google account').disabled).toBe(true);
  fireEvent.click(button(disconnectName));
  expect(screen.queryByRole('button', { name: confirmName })).toBeNull();
  await act(async () => read.give(json(connection())));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(text()).toContain('No Google client is saved.');
});

it.each(['test', 'consent', 'disconnect'] as const)(
  'locks immediately on session loss during %s',
  async (kind) => {
    const expired = vi.fn();
    const fetch = stubFetch(
      json(managed()),
      kind === 'consent' ? json({ active: false, configured: true }) : json({}, 401),
    );
    render(<GoogleConnectionCard sessionActive onSessionExpired={expired} />);
    if (kind === 'test')
      fireEvent.click(await screen.findByRole('button', { name: 'Test connection' }));
    if (kind === 'consent')
      fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize Google account' }));
    if (kind === 'disconnect') {
      fireEvent.click(await screen.findByRole('button', { name: disconnectName }));
      fireEvent.click(button(confirmName));
    }
    await waitFor(() => expect(expired).toHaveBeenCalledOnce());
    expect(screen.getByRole('alert').textContent).toContain('lock has closed');
    expect(text()).not.toContain('person@example.test');
    expect(card().querySelector('form,button,a')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(2);
  },
);
