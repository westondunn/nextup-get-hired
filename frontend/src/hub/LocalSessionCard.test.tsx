import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { LocalSessionCard } from './LocalSessionCard';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CODE = 'synthetic-setup-code-for-tests-only';
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

function stubFetch(...responses: Array<Response | Error>) {
  const fetch = vi.fn();
  for (const response of responses) {
    if (response instanceof Error) fetch.mockRejectedValueOnce(response);
    else fetch.mockResolvedValueOnce(response);
  }
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

const status = () =>
  screen
    .getByRole('region', { name: 'Integrations lock' })
    .querySelector('[aria-live="polite"][aria-atomic="true"]')?.textContent;
const input = () => screen.getByLabelText('Setup code') as HTMLInputElement;

it('is a named region that reports a locked state and asks for the code', async () => {
  stubFetch(json({ configured: true, active: false }));
  render(<LocalSessionCard />);
  expect(screen.getByRole('region', { name: 'Integrations lock' })).toBeTruthy();
  await waitFor(() => expect(status()).toBe('Locked.'));
  expect(input().type).toBe('password');
  expect(input().getAttribute('autocomplete')).toBe('off');
  expect(input().getAttribute('aria-describedby')).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Unlock' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole('button', { name: 'Lock' })).toBeNull();
});

it('unlocks by submitting the form, sends the code once and forgets it', async () => {
  const fetch = stubFetch(
    json({ configured: true, active: false }),
    new Response(null, { status: 204 }),
  );
  const onChange = vi.fn();
  const { container } = render(<LocalSessionCard onChange={onChange} />);
  await waitFor(() => expect(status()).toBe('Locked.'));
  fireEvent.change(input(), { target: { value: CODE } });
  expect((screen.getByRole('button', { name: 'Unlock' }) as HTMLButtonElement).disabled).toBe(
    false,
  );
  fireEvent.submit(input().closest('form')!); // what pressing Enter in the field does

  await waitFor(() => expect(status()).toBe('Unlocked in this browser.'));
  expect(fetch.mock.calls[1][0]).toBe('/api/session');
  expect(fetch.mock.calls[1][1].method).toBe('POST');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ code: CODE });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(onChange.mock.calls).toEqual([[false], [true]]);
  expect(screen.queryByLabelText('Setup code')).toBeNull();
  expect(container.innerHTML).not.toContain(CODE);
  expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
  expect(screen.getByRole('button', { name: 'Lock' })).toBeTruthy();
});

it('announces a refused code, clears the field and stays locked', async () => {
  stubFetch(json({ configured: true, active: false }), json({ detail: 'Session refused.' }, 401));
  const { container } = render(<LocalSessionCard />);
  await waitFor(() => expect(status()).toBe('Locked.'));
  fireEvent.change(input(), { target: { value: CODE } });
  fireEvent.click(screen.getByRole('button', { name: 'Unlock' }));

  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toBe('That code was not accepted.'),
  );
  expect(status()).toBe('Locked.');
  expect(input().value).toBe('');
  expect(container.innerHTML).not.toContain(CODE);
});

it('locks again and reports it', async () => {
  const fetch = stubFetch(
    json({ configured: true, active: true }),
    new Response(null, { status: 204 }),
  );
  const onChange = vi.fn();
  render(<LocalSessionCard onChange={onChange} />);
  await waitFor(() => expect(status()).toBe('Unlocked in this browser.'));
  expect(screen.queryByLabelText('Setup code')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Lock' }));

  await waitFor(() => expect(status()).toBe('Locked.'));
  expect(fetch.mock.calls[1][0]).toBe('/api/session');
  expect(fetch.mock.calls[1][1].method).toBe('DELETE');
  expect(onChange.mock.calls).toEqual([[true], [false]]);
  expect(screen.getByLabelText('Setup code')).toBeTruthy();
});

it('explains when no setup code is configured and offers no field', async () => {
  stubFetch(json({ configured: false, active: false }));
  render(<LocalSessionCard />);
  await waitFor(() =>
    expect(status()).toBe('Locked. No setup code is configured for this installation.'),
  );
  expect(screen.queryByLabelText('Setup code')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Unlock' })).toBeNull();
});

it('shows the server message when sessions are unavailable', async () => {
  stubFetch(
    json({ configured: true, active: false }),
    json({ detail: 'Session store unavailable.' }, 503),
  );
  render(<LocalSessionCard />);
  await waitFor(() => expect(status()).toBe('Locked.'));
  fireEvent.change(input(), { target: { value: CODE } });
  fireEvent.click(screen.getByRole('button', { name: 'Unlock' }));
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toBe('Session store unavailable.'),
  );
});

it('reports an unreadable status without offering actions that would fail', async () => {
  stubFetch(new Error('network down'));
  render(<LocalSessionCard />);
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toBe('The lock status could not be read.'),
  );
  expect(status()).toBe('Lock status unknown.');
  expect(screen.queryByLabelText('Setup code')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
});
