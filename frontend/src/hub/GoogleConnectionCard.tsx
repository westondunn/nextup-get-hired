import { type FormEvent, useEffect, useId, useRef, useState } from 'react';
import { ApiError } from '../jobs-api';
import {
  CALLBACK_PATH,
  CONNECT_ACTION,
  type Capability,
  capabilityLabels,
  type GoogleConnection,
  type GoogleResult,
  readConnection,
  resultMessages,
  saveClient,
} from './google-api';
import { readSession } from './session-api';

const unavailable: Record<NonNullable<GoogleConnection['unavailable_reason']>, string> = {
  fixture_mode:
    'Google connections are not available: this installation uses bundled sample data only.',
  switched_off:
    "Gmail and Calendar sync are switched off in this installation's configuration, so no " +
    'Google account can be connected.',
  no_key: 'No encryption key is configured, so a Google connection cannot be stored.',
};

const names = (capabilities: Capability[]) =>
  capabilities.map((capability) => capabilityLabels[capability]).join(' and ');

function stateText(connection: GoogleConnection): string {
  switch (connection.state) {
    case 'not_configured':
      return 'No Google client is saved.';
    case 'not_connected':
      return 'A Google client is saved. No account is connected.';
    case 'connected':
      return connection.account_address
        ? `Connected as ${connection.account_address}.`
        : 'Connected.';
    case 'needs_reauthorization':
      return 'The connection has to be authorized again. Connect the account again.';
    case 'unreadable':
      return (
        'The stored connection cannot be read with the current encryption key. Save the ' +
        'client again, then connect the account again.'
      );
  }
}

function failure(error: unknown, fallback: string): string {
  // The API's refusals are fixed sentences that never repeat what was submitted.
  if (error instanceof ApiError && [409, 422, 503].includes(error.status)) return error.message;
  if (error instanceof ApiError && error.status === 401) {
    return 'The integrations lock has closed. Unlock it again above.';
  }
  return fallback;
}

/**
 * Saves the user's own Google OAuth client and starts the consent flow.
 * The client secret lives only in the input while it is typed and is cleared on every submit.
 */
export function GoogleConnectionCard({
  sessionActive,
  result = null,
}: {
  sessionActive: boolean;
  result?: GoogleResult | null;
}) {
  const [connection, setConnection] = useState<GoogleConnection | null>(null);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [selected, setSelected] = useState<Capability[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const card = useRef<HTMLElement>(null);
  const connectForm = useRef<HTMLFormElement>(null);
  const titleId = useId();
  const clientIdInput = useId();
  const clientSecretInput = useId();
  const addressId = useId();

  useEffect(() => {
    if (!sessionActive) {
      setConnection(null);
      return;
    }
    let current = true;
    setError('');
    readConnection()
      .then((next) => {
        if (!current) return;
        setConnection(next);
        setSelected(next.enabled_capabilities);
      })
      .catch((e) => {
        if (current) setError(failure(e, 'The Google connection could not be read.'));
      });
    return () => {
      current = false;
    };
  }, [sessionActive]);

  // Arriving back from Google: bring the outcome into view.
  useEffect(() => {
    if (result) card.current?.scrollIntoView?.({ block: 'center' });
  }, [result]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!clientId || !clientSecret || busy) return;
    const secret = clientSecret;
    setClientSecret('');
    setBusy(true);
    setError('');
    setSaved('');
    try {
      const next = await saveClient(clientId.trim(), secret);
      setConnection(next);
      setClientId('');
      setSaved('The Google client is saved.');
    } catch (e) {
      setError(failure(e, 'The Google client could not be saved.'));
    } finally {
      setBusy(false);
    }
  }

  // The form is posted by the browser itself, so a refusal would replace this page with
  // the API's answer. Check first that the request will be accepted.
  async function connect(event: FormEvent) {
    event.preventDefault();
    if (busy || selected.length === 0) return;
    setBusy(true);
    setError('');
    setSaved('');
    try {
      const session = await readSession();
      if (!session.active) {
        setError('The integrations lock has closed. Unlock it again above.');
        return;
      }
      const next = await readConnection();
      setConnection(next);
      const allowed = selected.every((name) => next.enabled_capabilities.includes(name));
      if (!next.available || !next.client_configured || next.state === 'unreadable' || !allowed) {
        setSelected(next.enabled_capabilities);
        setError('The connection cannot be started right now. Check the status above.');
        return;
      }
      connectForm.current?.submit();
    } catch (e) {
      setError(failure(e, 'The connection could not be started.'));
    } finally {
      setBusy(false);
    }
  }

  function toggle(capability: Capability) {
    setSelected((current) =>
      current.includes(capability)
        ? current.filter((name) => name !== capability)
        : [...current, capability],
    );
  }

  const enabled = connection?.enabled_capabilities ?? [];
  const granted = connection?.granted_capabilities ?? [];
  const notGranted = enabled.filter((name) => !granted.includes(name));
  const hasGrant = connection?.state === 'connected';
  const canConnect =
    !!connection?.available && connection.client_configured && connection.state !== 'unreadable';
  const status = !sessionActive
    ? 'Locked. Unlock integrations above to see or change the Google connection.'
    : !connection
      ? error
        ? 'Connection status unknown.'
        : 'Reading the connection…'
      : !connection.available && connection.unavailable_reason
        ? unavailable[connection.unavailable_reason]
        : stateText(connection);

  return (
    <section
      ref={card}
      aria-labelledby={titleId}
      className={`mb-3 rounded-lg border p-4 ${hasGrant ? 'border-emerald-200 bg-emerald-50/30' : 'border-slate-200'}`}
    >
      <h3 id={titleId} className="text-sm font-semibold text-slate-900">
        Google connection
      </h3>
      <p className="text-xs text-slate-500">
        Read-only access to Gmail and Google Calendar through an OAuth client that you create in
        your own Google Cloud project. Connecting an account is not a sign-in to NextUp.
      </p>
      {result && (
        <p
          aria-live="polite"
          aria-atomic="true"
          className={`mt-2 text-xs font-medium ${result.startsWith('connected') ? 'text-emerald-700' : 'text-amber-700'}`}
        >
          {resultMessages[result]}
        </p>
      )}
      <p aria-live="polite" aria-atomic="true" className="mt-2 text-xs font-medium text-slate-700">
        {status}
      </p>

      {connection && hasGrant && (
        <ul className="mt-1 text-xs text-slate-600">
          <li>Google granted: {granted.length ? names(granted) : 'nothing NextUp uses'}.</li>
          {notGranted.length > 0 && (
            <li>Not granted: {names(notGranted)}. Connect again to add it.</li>
          )}
        </ul>
      )}

      {connection?.available && (
        <form onSubmit={save} className="mt-3 flex flex-wrap items-end gap-2">
          <p className="w-full text-xs text-slate-600">
            {connection.client_id ? (
              <>
                Saved client: <code className="break-all">{connection.client_id}</code>. Enter both
                values again to replace it.
              </>
            ) : (
              'Enter the client ID and client secret of your OAuth client (type "Web application").'
            )}
          </p>
          <div>
            <label htmlFor={clientIdInput} className="block text-xs font-medium text-slate-600">
              Client ID
            </label>
            <input
              id={clientIdInput}
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className="mt-1 w-72 max-w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor={clientSecretInput} className="block text-xs font-medium text-slate-600">
              Client secret
            </label>
            <input
              id={clientSecretInput}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              className="mt-1 w-64 max-w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={busy || !clientId || !clientSecret}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Save client
          </button>
          <p className="w-full text-[11px] text-slate-500">
            The secret is stored encrypted and is never shown again.
          </p>
        </form>
      )}

      {connection && canConnect && (
        <form
          ref={connectForm}
          method="post"
          action={CONNECT_ACTION}
          onSubmit={connect}
          className="mt-4 border-t border-slate-200 pt-3"
        >
          <p id={addressId} className="text-xs text-slate-600">
            Before connecting, add this address to the client's authorized redirect URIs:{' '}
            <code className="break-all">{window.location.origin + CALLBACK_PATH}</code>
          </p>
          <fieldset className="mt-2">
            <legend className="text-xs font-medium text-slate-600">Access to ask Google for</legend>
            {enabled.map((capability) => (
              <label key={capability} className="mr-4 mt-1 inline-flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  name="capability"
                  value={capability}
                  checked={selected.includes(capability)}
                  onChange={() => toggle(capability)}
                />
                {capabilityLabels[capability]} (read-only)
              </label>
            ))}
          </fieldset>
          <button
            type="submit"
            disabled={busy || selected.length === 0}
            aria-describedby={addressId}
            className="mt-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {hasGrant || connection.state === 'needs_reauthorization'
              ? 'Connect again'
              : 'Connect Google account'}
          </button>
          <p className="mt-1 text-[11px] text-slate-500">
            You will leave this page for Google's consent screen and be sent back here.
          </p>
        </form>
      )}

      {saved && (
        <p aria-live="polite" className="mt-2 text-xs text-emerald-700">
          {saved}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </p>
      )}
    </section>
  );
}
