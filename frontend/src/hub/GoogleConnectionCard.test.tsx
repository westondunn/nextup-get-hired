import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  [409, 'A Google account is connected with the current client.'],
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
  expect(text()).toContain('Not granted: Gmail. Connect again to add it.');
  expect(button('Connect again')).toBeTruthy();
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
  expect(button('Connect again')).toBeTruthy();
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
