import { ApiError } from '../jobs-api';

// Every API call requires the local session. Only these fields from the local report
// are used by Settings. Provider messages and credentials have no display surface.
const capabilities = ['gmail', 'calendar'] as const;
export type Capability = (typeof capabilities)[number];
export const capabilityLabels: Record<Capability, string> = {
  gmail: 'Gmail',
  calendar: 'Calendar',
};

const attemptStatuses = [
  'not_run',
  'ok',
  'disabled',
  'not_configured',
  'needs_reauthorization',
  'wrong_scope',
  'admin_restricted',
  'temporarily_unavailable',
  'unreadable',
  'connection_error',
  'provider_rejected',
] as const;
export type GoogleAttemptStatus = (typeof attemptStatuses)[number];

export interface GoogleSyncStatus {
  active: boolean;
  last_attempt_at: string | null;
  last_status: GoogleAttemptStatus;
  last_success_at: string | null;
  freshness: 'inactive' | 'unknown' | 'current' | 'stale';
}

export interface GoogleConnection {
  available: boolean;
  unavailable_reason: 'fixture_mode' | 'switched_off' | 'no_key' | null;
  client_configured: boolean;
  client_id: string | null;
  state: 'not_configured' | 'not_connected' | 'connected' | 'needs_reauthorization' | 'unreadable';
  enabled_capabilities: Capability[];
  granted_capabilities: Capability[];
  account_address: string | null;
  credential_source: 'none' | 'stored' | 'configured';
  sync: Record<Capability, GoogleSyncStatus>;
}

const probeResults = [
  'ok',
  'disabled',
  'not_granted',
  'wrong_scope',
  'needs_reauthorization',
  'admin_restricted',
  'temporarily_unavailable',
  'provider_rejected',
] as const;
export type GoogleProbeResult = (typeof probeResults)[number];
export interface GoogleTestResult {
  result: 'complete';
  capabilities: Record<Capability, GoogleProbeResult>;
  connection: GoogleConnection;
}

export interface GoogleDisconnectResult {
  result: 'disconnected' | 'already_disconnected';
  revocation: 'confirmed' | 'unconfirmed' | 'not_applicable';
  connection: GoogleConnection;
  warning?: string;
}

const refusalMessages = {
  fixture_mode: 'Google connection tests are unavailable in sample data mode.',
  switched_off: 'Google connections are switched off in this installation.',
  no_key: 'The key for the saved Google connection is unavailable.',
  not_connected: 'No saved Google grant is connected.',
  configured_externally: 'Google credentials are managed in the installation configuration.',
  unreadable: 'The saved Google connection cannot be read with this key.',
  needs_reauthorization: 'The Google connection has to be authorized again in Settings.',
  busy: 'Another Google connection action is in progress. Try again.',
  no_enabled_grant: 'No enabled Google capability is included in the saved grant.',
  connection_error: 'The local Google connection could not be read or updated.',
} as const;

// Client setup still uses fixed string refusals. Accept only its known status/message pairs.
const setupRefusals: Record<number, readonly string[]> = {
  409: [
    'Google connections are not available in fixture data mode.',
    "Gmail and Calendar sync are switched off in this installation's configuration, so no Google client can be saved.",
    'A Google account is connected with the current client. Disconnect it before saving a different client ID.',
  ],
  422: [
    'Invalid Google client request.',
    'The client ID must be the full value ending in .apps.googleusercontent.com.',
    'The client secret is empty, too long, or contains a space.',
  ],
  503: ['No encryption key is configured, so a Google client cannot be stored.'],
};
const removalWarning =
  'Removal at Google could not be confirmed. You can check or remove access under ' +
  'third-party access in your Google Account. Removing a shared grant can affect other credentials.';
const requestFailure =
  'The Google connection request could not be completed. Check the connection status and try again.';

type ErrorCode =
  | keyof typeof refusalMessages
  | 'setup_refused'
  | 'session_expired'
  | 'invalid_response'
  | 'request_failed';
export class GoogleActionError extends ApiError {
  constructor(
    readonly code: ErrorCode,
    status: number,
    message: string,
  ) {
    super(message, status);
  }
}

function invalid(): never {
  throw new GoogleActionError(
    'invalid_response',
    200,
    'The Google connection response could not be read. Check the connection status and try again.',
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown) {
  return isRecord(value) ? value : invalid();
}

function word<const T extends string>(value: unknown, allowed: readonly T[]): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : invalid();
}

function flag(value: unknown) {
  return typeof value === 'boolean' ? value : invalid();
}

function nullableText(value: unknown, pattern: RegExp) {
  if (value === null) return null;
  return typeof value === 'string' && pattern.test(value) ? value : invalid();
}

function timestamp(value: unknown) {
  const date = nullableText(
    value,
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/,
  );
  return date === null || Number.isFinite(Date.parse(date)) ? date : invalid();
}

function capabilityList(value: unknown) {
  if (!Array.isArray(value) || value.length > capabilities.length) return invalid();
  const list = value.map((name) => word(name, capabilities));
  return new Set(list).size === list.length ? list : invalid();
}

function perCapability<T>(value: unknown, parse: (entry: unknown) => T): Record<Capability, T> {
  const entries = record(value);
  return { gmail: parse(entries.gmail), calendar: parse(entries.calendar) };
}

function syncStatus(value: unknown): GoogleSyncStatus {
  const data = record(value);
  const active = flag(data.active);
  const freshness = word(data.freshness, ['inactive', 'unknown', 'current', 'stale']);
  if (active === (freshness === 'inactive')) return invalid();
  return {
    active,
    last_attempt_at: timestamp(data.last_attempt_at),
    last_status: word(data.last_status, attemptStatuses),
    last_success_at: timestamp(data.last_success_at),
    freshness,
  };
}

function connectionReport(value: unknown): GoogleConnection {
  const data = record(value);
  const available = flag(data.available);
  const reason =
    data.unavailable_reason === null
      ? null
      : word(data.unavailable_reason, ['fixture_mode', 'switched_off', 'no_key']);
  const clientConfigured = flag(data.client_configured);
  const clientId = nullableText(
    data.client_id,
    /^[0-9a-zA-Z][0-9a-zA-Z._-]{0,180}\.apps\.googleusercontent\.com$/,
  );
  if (available !== (reason === null) || clientConfigured !== (clientId !== null)) return invalid();
  return {
    available,
    unavailable_reason: reason,
    client_configured: clientConfigured,
    client_id: clientId,
    state: word(data.state, [
      'not_configured',
      'not_connected',
      'connected',
      'needs_reauthorization',
      'unreadable',
    ]),
    enabled_capabilities: capabilityList(data.enabled_capabilities),
    granted_capabilities: capabilityList(data.granted_capabilities),
    account_address: nullableText(
      data.account_address,
      /^[^\s@\x00-\x1f\x7f]{1,64}@[^\s@\x00-\x1f\x7f]{1,255}$/u,
    ),
    credential_source: word(data.credential_source, ['none', 'stored', 'configured']),
    sync: perCapability(data.sync, syncStatus),
  };
}

function refusal(status: number, body: unknown, setup: boolean) {
  const detail = isRecord(body) ? body.detail : null;
  if (
    isRecord(detail) &&
    typeof detail.code === 'string' &&
    Object.hasOwn(refusalMessages, detail.code)
  ) {
    const code = detail.code as keyof typeof refusalMessages;
    if (status === (code === 'connection_error' ? 503 : 409))
      return new GoogleActionError(code, status, refusalMessages[code]);
  }
  if (setup && typeof detail === 'string' && setupRefusals[status]?.includes(detail))
    return new GoogleActionError('setup_refused', status, detail);
  return new GoogleActionError('request_failed', status, requestFailure);
}

async function googleRequest(path: string, options?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/google/${path}`, {
      ...options,
      mode: 'same-origin',
      redirect: 'error',
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new GoogleActionError('request_failed', 0, requestFailure);
  }
  if (response.status === 401) {
    throw new GoogleActionError(
      'session_expired',
      401,
      'The integrations lock has closed. Unlock it again above.',
    );
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw refusal(response.status, body, path === 'client');
  return body;
}

export const readConnection = async () => connectionReport(await googleRequest('connection'));
export const saveClient = async (clientId: string, clientSecret: string) =>
  connectionReport(
    await googleRequest('client', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
    }),
  );

export async function testConnection(): Promise<GoogleTestResult> {
  const body = record(await googleRequest('connection/test', { method: 'POST' }));
  return {
    result: word(body.result, ['complete']),
    capabilities: perCapability(body.capabilities, (value) => word(value, probeResults)),
    connection: connectionReport(body.connection),
  };
}

export async function disconnectConnection(): Promise<GoogleDisconnectResult> {
  const body = record(await googleRequest('connection', { method: 'DELETE' }));
  const result = word(body.result, ['disconnected', 'already_disconnected']);
  const revocation = word(body.revocation, ['confirmed', 'unconfirmed', 'not_applicable']);
  if (result === 'already_disconnected' && revocation !== 'not_applicable') return invalid();
  return {
    result,
    revocation,
    connection: connectionReport(body.connection),
    ...(revocation === 'unconfirmed' && { warning: removalWarning }),
  };
}

// The consent flow is started by a form posted to this address, not by a fetch: the API
// answers with a redirect to Google, which the browser has to follow as a navigation.
export const CONNECT_ACTION = '/api/google/connect';
export const CALLBACK_PATH = '/api/google/callback';

// When the flow ends, the API sends the browser to `/?google=<word>` with one of these
// words. Anything else in that parameter is ignored and never shown.
export const resultMessages = {
  connected: 'The Google account is connected.',
  connected_earlier_not_revoked:
    'The Google account is connected. Access for the account connected before could not be ' +
    'revoked. You can remove it in that Google Account, under third-party access.',
  declined: 'Access was declined at Google. Nothing was changed.',
  not_granted:
    'Google did not grant any of the access that was asked for. Nothing was stored. Connect ' +
    'again and leave the access you want ticked.',
  failed: 'The connection could not be completed. Nothing was stored. Try again.',
} as const;
export type GoogleResult = keyof typeof resultMessages;

export function googleResultOf(search: string): GoogleResult | null {
  const word = new URLSearchParams(search).get('google');
  return word !== null && Object.hasOwn(resultMessages, word) ? (word as GoogleResult) : null;
}

/** Read the result word from the address bar and remove the parameter from it. */
export function takeGoogleResult(): GoogleResult | null {
  const parameters = new URLSearchParams(window.location.search);
  if (!parameters.has('google')) return null;
  const result = googleResultOf(window.location.search);
  parameters.delete('google');
  const rest = parameters.toString();
  window.history.replaceState(
    window.history.state,
    '',
    window.location.pathname + (rest ? `?${rest}` : '') + window.location.hash,
  );
  return result;
}
