import { request } from '../jobs-api';

// The stored Google connection (docs/decisions/0003-google-connection.md). Every route
// here needs the local session. No credential is ever returned by the API; the client
// secret is only ever sent, once, when the user saves it.

export type Capability = 'gmail' | 'calendar';
export const capabilityLabels: Record<Capability, string> = {
  gmail: 'Gmail',
  calendar: 'Calendar',
};

export interface GoogleConnection {
  available: boolean;
  unavailable_reason: 'fixture_mode' | 'switched_off' | 'no_key' | null;
  client_configured: boolean;
  client_id: string | null;
  state: 'not_configured' | 'not_connected' | 'connected' | 'needs_reauthorization' | 'unreadable';
  enabled_capabilities: Capability[];
  granted_capabilities: Capability[];
  account_address: string | null;
}

export const readConnection = () => request<GoogleConnection>('google/connection');
export const saveClient = (clientId: string, clientSecret: string) =>
  request<GoogleConnection>('google/client', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  });

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
