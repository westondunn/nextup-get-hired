import { afterEach, expect, it, vi } from 'vitest';
import { ApiError } from '../jobs-api';
import {
  type GoogleConnection,
  GoogleActionError,
  readConnection,
  saveClient,
  testConnection,
  disconnectConnection,
  googleResultOf,
  resultMessages,
  takeGoogleResult,
} from './google-api';

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

const gmailSync = {
  active: true,
  last_attempt_at: '2026-06-20T09:00:00.123456+00:00',
  last_status: 'temporarily_unavailable',
  last_success_at: '2026-06-18T09:00:00Z',
  freshness: 'stale',
} as const;
const report: GoogleConnection = {
  available: true,
  unavailable_reason: null,
  client_configured: true,
  client_id: 'synthetic-test.apps.googleusercontent.com',
  state: 'connected',
  enabled_capabilities: ['gmail', 'calendar'],
  granted_capabilities: ['gmail'],
  account_address: 'synthetic@example.test',
  credential_source: 'stored',
  sync: {
    gmail: gmailSync,
    calendar: {
      active: false,
      last_attempt_at: null,
      last_status: 'not_run',
      last_success_at: null,
      freshness: 'inactive',
    },
  },
};
const emptyReport: GoogleConnection = {
  ...report,
  client_configured: false,
  client_id: null,
  state: 'not_configured',
  granted_capabilities: [],
  account_address: null,
  credential_source: 'none',
  sync: { gmail: report.sync.calendar, calendar: report.sync.calendar },
};
const privateDetail = 'SYNTHETIC_RAW_PROVIDER_DETAIL';
function respond(body: unknown, status = 200) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

it('reads the common status and exposes only its documented fields', async () => {
  const fetch = respond({
    ...report,
    refresh_token: privateDetail,
    sync: {
      drive: privateDetail,
      gmail: { ...gmailSync, provider_details: privateDetail },
      calendar: report.sync.calendar,
    },
  });
  expect(await readConnection()).toEqual(report);
  expect(fetch.mock.calls[0][0]).toBe('/api/google/connection');
});

it('submits the setup secret only in the same-origin PUT body and returns the updated report', async () => {
  const fetch = respond({ ...report, client_secret: privateDetail });
  expect(await saveClient(report.client_id!, privateDetail)).toEqual(report);
  expect(fetch).toHaveBeenCalledWith(
    '/api/google/client',
    expect.objectContaining({
      method: 'PUT',
      mode: 'same-origin',
      redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: report.client_id, client_secret: privateDetail }),
    }),
  );
});

it.each([
  'ok',
  'disabled',
  'not_granted',
  'needs_reauthorization',
  'wrong_scope',
  'admin_restricted',
  'temporarily_unavailable',
  'provider_rejected',
])('reads the fixed probe outcome %s without using it as sync evidence', async (gmail) => {
  const capabilities = { gmail, calendar: 'not_granted' };
  const fetch = respond({
    result: 'complete',
    capabilities: { ...capabilities, extra: privateDetail },
    connection: report,
    message: privateDetail,
  });
  expect(await testConnection()).toEqual({ result: 'complete', capabilities, connection: report });
  expect(fetch.mock.calls[0][0]).toBe('/api/google/connection/test');
  expect(fetch.mock.calls[0][1].method).toBe('POST');
  expect(fetch.mock.calls[0][1].body).toBeUndefined();
});

it.each([
  ['disconnected', 'confirmed'],
  ['disconnected', 'not_applicable'],
  ['disconnected', 'unconfirmed'],
  ['already_disconnected', 'not_applicable'],
])('reads local result %s and provider revocation %s separately', async (result, revocation) => {
  const fetch = respond({ result, revocation, connection: emptyReport, warning: privateDetail });
  const response = await disconnectConnection();
  expect(response).toMatchObject({ result, revocation, connection: emptyReport });
  expect(response.warning).toBe(
    revocation === 'unconfirmed'
      ? 'Removal at Google could not be confirmed. You can check or remove access under third-party access in your Google Account. Removing a shared grant can affect other credentials.'
      : undefined,
  );
  expect(fetch.mock.calls[0][0]).toBe('/api/google/connection');
  expect(fetch.mock.calls[0][1].method).toBe('DELETE');
  expect(fetch.mock.calls[0][1].body).toBeUndefined();
});

it.each([
  ['fixture_mode', 409],
  ['switched_off', 409],
  ['no_key', 409],
  ['not_connected', 409],
  ['configured_externally', 409],
  ['unreadable', 409],
  ['needs_reauthorization', 409],
  ['busy', 409],
  ['no_enabled_grant', 409],
  ['connection_error', 503],
] as const)(
  'keeps the fixed refusal code %s and drops arbitrary server text',
  async (code, status) => {
    respond({ detail: { code, message: privateDetail } }, status);
    const error = await testConnection().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(GoogleActionError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code, status });
    expect(String(error)).not.toContain(privateDetail);
  },
);

it.each([
  readConnection,
  () => saveClient('client', privateDetail),
  testConnection,
  disconnectConnection,
])(
  'recognizes an expired local session on every route regardless of response body',
  async (action) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(privateDetail, { status: 401 })));
    await expect(action()).rejects.toMatchObject({
      code: 'session_expired',
      status: 401,
      message: expect.stringContaining('Unlock it again'),
    });
  },
);

it('allows the fixed client setup refusal needed to correct the input', async () => {
  const detail = 'The client ID must be the full value ending in .apps.googleusercontent.com.';
  respond({ detail }, 422);
  await expect(saveClient('client', privateDetail)).rejects.toMatchObject({
    code: 'setup_refused',
    status: 422,
    message: detail,
  });
});

it.each([
  [503, { code: 'busy', message: privateDetail }],
  [409, { code: privateDetail, message: privateDetail }],
  [409, { code: 'constructor', message: privateDetail }],
  [422, privateDetail],
] as const)(
  'drops unrecognized refusals even when human-readable detail is present',
  async (status, detail) => {
    respond({ detail }, status);
    await expect(saveClient('client', privateDetail)).rejects.toMatchObject({
      code: 'request_failed',
      status,
      message: expect.not.stringContaining(privateDetail),
    });
  },
);

it.each([
  { state: privateDetail },
  { available: false },
  { client_configured: false },
  { sync: { ...report.sync, gmail: { ...gmailSync, freshness: 'inactive' } } },
  { available: 1 },
  { client_configured: null },
  { granted_capabilities: ['gmail', 'gmail'] },
  { enabled_capabilities: ['gmail', privateDetail] },
  { unavailable_reason: privateDetail },
  { credential_source: privateDetail },
  { client_id: privateDetail },
  { account_address: privateDetail },
  { sync: { gmail: gmailSync } },
  { sync: { ...report.sync, gmail: { ...gmailSync, freshness: privateDetail } } },
  { sync: { ...report.sync, calendar: { ...gmailSync, last_status: privateDetail } } },
  { sync: { ...report.sync, calendar: { ...gmailSync, last_success_at: privateDetail } } },
  { sync: { ...report.sync, calendar: { ...gmailSync, last_attempt_at: '2026-99-99T00:00:00Z' } } },
])('rejects an ill-formed report with a fixed safe message', async (overrides) => {
  respond({ ...report, ...overrides });
  await expect(readConnection()).rejects.toMatchObject({
    code: 'invalid_response',
    message: expect.not.stringContaining(privateDetail),
  });
});

it.each([
  [
    testConnection,
    {
      result: 'complete',
      capabilities: { gmail: 'ok', calendar: privateDetail },
      connection: report,
    },
  ],
  [testConnection, { result: 'complete', capabilities: { gmail: 'ok' }, connection: report }],
  [
    testConnection,
    { result: 'complete', capabilities: { gmail: 'ok', calendar: 'ok' }, connection: {} },
  ],
  [
    testConnection,
    { result: privateDetail, capabilities: { gmail: 'ok', calendar: 'ok' }, connection: report },
  ],
  [
    disconnectConnection,
    { result: 'disconnected', revocation: privateDetail, connection: emptyReport },
  ],
  [
    disconnectConnection,
    { result: 'already_disconnected', revocation: 'confirmed', connection: emptyReport },
  ],
  [disconnectConnection, { result: 'disconnected', revocation: 'confirmed' }],
] as const)('rejects an incomplete or unrecognized action response', async (action, body) => {
  respond(body);
  await expect(action()).rejects.toMatchObject({
    code: 'invalid_response',
    message: expect.not.stringContaining(privateDetail),
  });
});

it('reports non-JSON success bodies and network failures without quoting them', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(privateDetail))
    .mockRejectedValueOnce(new Error(privateDetail));
  vi.stubGlobal('fetch', fetch);
  await expect(readConnection()).rejects.toMatchObject({
    code: 'invalid_response',
    message: expect.not.stringContaining(privateDetail),
  });
  await expect(disconnectConnection()).rejects.toMatchObject({
    code: 'request_failed',
    message: expect.not.stringContaining(privateDetail),
  });
});

it('reads only the fixed result words', () => {
  for (const word of Object.keys(resultMessages)) {
    expect(googleResultOf(`?google=${word}`)).toBe(word);
  }
  expect(Object.keys(resultMessages).sort()).toEqual([
    'connected',
    'connected_earlier_not_revoked',
    'declined',
    'failed',
    'not_granted',
  ]);
});

it.each([
  '',
  '?google=',
  '?google=CONNECTED',
  '?google=connected%20',
  '?google=constructor',
  '?google=toString',
  '?google=__proto__',
  '?google=%3Cscript%3E',
  '?other=connected',
])('ignores anything else: %s', (search) => {
  expect(googleResultOf(search)).toBeNull();
});

it('takes the word out of the address bar and keeps the rest of the address', () => {
  window.history.replaceState(null, '', '/?google=declined&keep=1#part');
  expect(takeGoogleResult()).toBe('declined');
  expect(window.location.pathname + window.location.search + window.location.hash).toBe(
    '/?keep=1#part',
  );
  expect(takeGoogleResult()).toBeNull(); // read once
});

it('removes an unknown word as well, and reports nothing', () => {
  window.history.replaceState(null, '', '/?google=something-else');
  expect(takeGoogleResult()).toBeNull();
  expect(window.location.search).toBe('');
});

it('leaves an address without the parameter untouched', () => {
  window.history.replaceState(null, '', '/?keep=1');
  expect(takeGoogleResult()).toBeNull();
  expect(window.location.search).toBe('?keep=1');
});
