import { type FormEvent, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ApiError } from '../jobs-api';
import {
  CALLBACK_PATH,
  CONNECT_ACTION,
  type Capability,
  capabilityLabels,
  type GoogleConnection,
  type GoogleResult,
  type GoogleTestResult,
  GoogleActionError,
  disconnectConnection,
  testConnection,
  readConnection,
  resultMessages,
  saveClient,
} from './google-api';
import { GoogleSyncStatus, GoogleTestResults } from './GoogleSyncStatus';
import { safeHref } from './safe';
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
      return 'A Google client is saved. Connect an account to use that client.';
    case 'connected':
      return connection.account_address
        ? `Connected as ${connection.account_address}.`
        : 'Connected.';
    case 'needs_reauthorization':
      return 'The connection has to be authorized again. Connect the account again.';
    case 'unreadable':
      return 'The stored connection cannot be read with the current encryption key. Restore the original key or remove the saved connection and set it up again.';
  }
}

type CardProps = {
  sessionActive: boolean;
  result?: GoogleResult | null;
  syncRevision?: number;
  onSessionExpired?: () => void;
  onConnectionChanged?: (kind: 'save' | 'test' | 'disconnect') => void;
};

const lockMessage = 'The integrations lock has closed. Unlock it again above.';
const actionButton =
  'rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 disabled:opacity-50';

export function GoogleConnectionCard({ sessionActive, result = null, ...props }: CardProps) {
  const titleId = useId();
  const title = useRef<HTMLHeadingElement>(null);
  const outcome = useRef<HTMLParagraphElement>(null);
  const [dismissedResult, setDismissedResult] = useState<GoogleResult | null>(null);
  const showResult = result && result !== dismissedResult;
  useEffect(() => {
    if (showResult) outcome.current?.focus();
  }, [showResult, result]);
  return (
    <section
      aria-labelledby={titleId}
      className="mb-3 min-w-0 rounded-lg border border-slate-200 p-4"
    >
      <h3 ref={title} tabIndex={-1} id={titleId} className="text-sm font-semibold text-slate-900">
        Google connection
      </h3>
      <p className="text-xs text-slate-600">
        Gmail and Calendar use read-only access through your own Google Cloud OAuth client.
      </p>
      {showResult && (
        <p ref={outcome} tabIndex={-1} role="status" className="mt-2 text-sm">
          {resultMessages[result]}
        </p>
      )}
      {sessionActive ? (
        <UnlockedConnection
          {...props}
          dismissOutcome={() => setDismissedResult(result)}
          focusTitle={() => title.current?.focus()}
        />
      ) : (
        <p className="mt-2 text-sm">
          Locked. Unlock integrations above to see or change the Google connection.
        </p>
      )}
    </section>
  );
}

function UnlockedConnection({
  onSessionExpired,
  onConnectionChanged,
  syncRevision = 0,
  focusTitle,
  dismissOutcome,
}: Omit<CardProps, 'sessionActive' | 'result'> & {
  focusTitle: () => void;
  dismissOutcome: () => void;
}) {
  const [connection, setConnection] = useState<GoogleConnection | null>(null);
  const [clientId, setClientId] = useState('');
  const secretInput = useRef<HTMLInputElement>(null);
  const [hasSecret, setHasSecret] = useState(false);
  const [selected, setSelected] = useState<Capability[]>([]);
  const [busy, setBusy] = useState<'save' | 'consent' | 'test' | 'disconnect' | null>(null);
  const [reading, setReading] = useState(true);
  const [expired, setExpired] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [warning, setWarning] = useState('');
  const [probes, setProbes] = useState<GoogleTestResult['capabilities'] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [reload, setReload] = useState(0);
  const sequence = useRef(0);
  const actionPending = useRef(false);
  const readPending = useRef(false);
  const readingStatus = useRef(true);
  const lastReport = useRef<GoogleConnection | null>(null);
  const callbacks = useRef({ onSessionExpired, onConnectionChanged });
  const cancel = useRef<HTMLButtonElement>(null);
  const disconnectButton = useRef<HTMLButtonElement>(null);
  const connectForm = useRef<HTMLFormElement>(null);
  const clientIdInput = useId();
  const clientSecretInput = useId();
  const addressId = useId();
  const confirmId = useId();
  const testDescriptionId = useId();

  useLayoutEffect(() => {
    callbacks.current = { onSessionExpired, onConnectionChanged };
  }, [onSessionExpired, onConnectionChanged]);
  useLayoutEffect(
    () => () => {
      ++sequence.current;
    },
    [],
  );
  useLayoutEffect(() => {
    if (confirming) cancel.current?.focus();
  }, [confirming]);

  function accept(next: GoogleConnection) {
    const previous = lastReport.current;
    lastReport.current = next;
    if (
      !next.available ||
      next.client_id !== previous?.client_id ||
      next.account_address !== previous?.account_address
    ) {
      forgetSecret();
    }
    setConnection(next);
    setSelected((choices) =>
      previous
        ? choices.filter((c) => next.enabled_capabilities.includes(c))
        : next.enabled_capabilities,
    );
  }

  function forgetSecret() {
    if (secretInput.current) secretInput.current.value = '';
    setHasSecret(false);
  }

  function clearReport() {
    lastReport.current = null;
    setConnection(null);
    setSelected([]);
    forgetSecret();
    setClientId('');
    setProbes(null);
    setConfirming(false);
  }

  function expire() {
    ++sequence.current;
    clearReport();
    setWarning('');
    setNotice('');
    setExpired(true);
    setError(lockMessage);
    callbacks.current.onSessionExpired?.();
  }

  function reportError(e: unknown, fallback: string) {
    if (e instanceof ApiError && e.status === 401) expire();
    else
      setError(
        e instanceof GoogleActionError && e.code !== 'request_failed' ? e.message : fallback,
      );
  }

  useEffect(() => {
    if (expired) return;
    if (actionPending.current) {
      readPending.current = true;
      return;
    }
    const id = ++sequence.current;
    readingStatus.current = true;
    setReading(true);
    setError('');
    readConnection()
      .then((next) => {
        if (id !== sequence.current) return;
        const previous = lastReport.current;
        accept(next);
        // Keep a completed test visible when just the sync timestamps change.
        if (
          !previous ||
          previous.account_address !== next.account_address ||
          previous.client_id !== next.client_id ||
          previous.credential_source !== next.credential_source ||
          previous.state !== next.state ||
          previous.available !== next.available ||
          String(previous.enabled_capabilities) !== String(next.enabled_capabilities) ||
          String(previous.granted_capabilities) !== String(next.granted_capabilities)
        ) {
          setProbes(null);
          if (cancel.current) {
            setConfirming(false);
            setNotice(
              'The Google connection changed. Review its current status before disconnecting.',
            );
            focusTitle();
          } else if (previous) {
            setNotice('');
          }
        }
      })
      .catch((e: unknown) => {
        if (id !== sequence.current) return;
        if (cancel.current) focusTitle();
        clearReport();
        reportError(e, 'The Google connection could not be read.');
      })
      .finally(() => {
        if (id === sequence.current) {
          readingStatus.current = false;
          setReading(false);
        }
      });
  }, [syncRevision, reload, expired]);

  function begin(operation: NonNullable<typeof busy>) {
    if (actionPending.current || readingStatus.current || expired) return;
    actionPending.current = true;
    dismissOutcome();
    const id = ++sequence.current;
    setReading(false);
    setBusy(operation);
    setError('');
    setNotice('');
    setProbes(null);
    return id;
  }

  function finish(id: number) {
    if (id !== sequence.current) return;
    actionPending.current = false;
    setBusy(null);
    if (readPending.current) {
      readPending.current = false;
      setReload((value) => value + 1);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const secret = secretInput.current?.value;
    if (!clientId.trim() || !secret || confirming || !connection?.available) return;
    const id = begin('save');
    if (!id) return;
    forgetSecret();
    try {
      const next = await saveClient(clientId.trim(), secret);
      if (id !== sequence.current) return;
      accept(next);
      setClientId('');
      setNotice('The Google client is saved.');
      callbacks.current.onConnectionChanged?.('save');
    } catch (e) {
      if (id === sequence.current)
        reportError(e, 'The Google client could not be saved. Refresh status and try again.');
    } finally {
      finish(id);
    }
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    if (!canConnect || !selected.length || confirming) return;
    const id = begin('consent');
    if (!id) return;
    try {
      const session = await readSession();
      if (id !== sequence.current) return;
      if (!session.active) {
        expire();
        return;
      }
      const next = await readConnection();
      if (id !== sequence.current) return;
      accept(next);
      if (
        !next.available ||
        !next.client_configured ||
        next.state === 'unreadable' ||
        next.client_id !== connection?.client_id ||
        next.account_address !== connection?.account_address ||
        next.credential_source !== connection?.credential_source ||
        !selected.every((name) => next.enabled_capabilities.includes(name))
      ) {
        setError('The connection cannot be started right now. Check the status above.');
        return;
      }
      connectForm.current?.submit();
    } catch (e) {
      if (id === sequence.current)
        reportError(e, 'The connection could not be started. Refresh status and try again.');
    } finally {
      finish(id);
    }
  }

  async function testGrant() {
    if (!canTest || confirming) return;
    const id = begin('test');
    if (!id) return;
    try {
      const response = await testConnection();
      if (id !== sequence.current) return;
      accept(response.connection);
      setProbes(response.capabilities);
      setNotice('Connection test completed.');
      callbacks.current.onConnectionChanged?.('test');
    } catch (e) {
      if (id === sequence.current)
        reportError(e, 'The connection test could not be completed. Refresh status and try again.');
    } finally {
      finish(id);
    }
  }

  function cancelDisconnect() {
    if (actionPending.current) return;
    setConfirming(false);
    disconnectButton.current?.focus();
  }

  async function disconnect() {
    if (!confirming || !connection?.client_configured) return;
    const id = begin('disconnect');
    if (!id) return;
    try {
      const response = await disconnectConnection();
      if (id !== sequence.current) return;
      accept(response.connection);
      setClientId('');
      forgetSecret();
      setConfirming(false);
      setWarning(response.warning ?? '');
      setNotice(
        response.result === 'already_disconnected'
          ? 'The saved Google connection was already removed.'
          : 'The saved Google connection was removed locally and both syncs are paused.' +
              (response.revocation === 'confirmed' ? ' Google confirmed removal of access.' : ''),
      );
      focusTitle();
      callbacks.current.onConnectionChanged?.('disconnect');
    } catch (e) {
      if (id !== sequence.current) return;
      setConfirming(false);
      if (e instanceof GoogleActionError && e.status === 409) {
        reportError(e, 'Disconnect was refused. Refresh status before trying again.');
        focusTitle();
      } else if (e instanceof ApiError && e.status === 401) {
        expire();
      } else {
        clearReport();
        setError(
          'The disconnect result is unknown. Refresh status to check which credentials are still saved before trying again.',
        );
        focusTitle();
        callbacks.current.onConnectionChanged?.('disconnect');
      }
    } finally {
      finish(id);
    }
  }

  function toggle(capability: Capability) {
    if (actionPending.current || confirming) return;
    setSelected((current) =>
      current.includes(capability)
        ? current.filter((name) => name !== capability)
        : [...current, capability],
    );
  }

  const enabled = connection?.enabled_capabilities ?? [];
  const granted = connection?.granted_capabilities ?? [];
  const notGranted = enabled.filter((name) => !granted.includes(name));
  const hasGrant = connection?.credential_source === 'stored';
  const canConnect =
    !!connection?.available && connection.client_configured && connection.state !== 'unreadable';
  const canTest =
    connection?.available &&
    hasGrant &&
    connection.state === 'connected' &&
    enabled.some((name) => granted.includes(name));

  const clientForm = connection?.available && (
    <form onSubmit={save} className="mt-3 flex flex-wrap items-end gap-2">
      <p className="w-full text-xs text-slate-600">
        {connection.client_id ? (
          <>
            Saved client: <code className="break-all">{connection.client_id}</code>. Enter both
            values to update the saved client.
          </>
        ) : (
          'Enter the client ID and client secret of your OAuth client (type "Web application").'
        )}
      </p>
      <div className="min-w-0 max-w-full">
        <label htmlFor={clientIdInput} className="block text-xs font-medium text-slate-600">
          Client ID
        </label>
        <input
          id={clientIdInput}
          type="text"
          autoComplete="off"
          spellCheck={false}
          disabled={!!busy || reading || confirming}
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          className="mt-1 w-full max-w-72 rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <div className="min-w-0 max-w-full">
        <label htmlFor={clientSecretInput} className="block text-xs font-medium text-slate-600">
          Client secret
        </label>
        <input
          id={clientSecretInput}
          type="password"
          autoComplete="off"
          spellCheck={false}
          disabled={!!busy || reading || confirming}
          ref={secretInput}
          onChange={(e) => setHasSecret(Boolean(e.currentTarget.value))}
          className="mt-1 w-full max-w-64 rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <button
        type="submit"
        disabled={!!busy || reading || confirming || !clientId.trim() || !hasSecret}
        className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
      >
        Save client
      </button>
      <p className="w-full text-[11px] text-slate-500">
        The secret is stored encrypted and is never shown again.
      </p>
    </form>
  );

  if (expired)
    return (
      <p role="alert" className="mt-2 text-sm">
        {lockMessage}
      </p>
    );
  return (
    <>
      <p aria-live="polite" className="mt-2 break-words text-sm font-medium text-slate-700">
        {connection
          ? stateText(connection)
          : reading
            ? 'Reading the connection…'
            : 'Connection status unknown.'}
      </p>
      {connection?.unavailable_reason && (
        <p className="mt-1 text-sm">{unavailable[connection.unavailable_reason]}</p>
      )}
      {connection?.credential_source === 'configured' && (
        <p className="mt-1 text-sm">
          Google credentials are managed in the installation configuration. Change them there. Sync
          history for that mailbox cannot be verified.
        </p>
      )}
      {connection && hasGrant && (
        <ul className="mt-1 text-sm text-slate-700">
          <li>Google granted: {granted.length ? names(granted) : 'nothing NextUp uses'}.</li>
          {notGranted.length > 0 && (
            <li>
              Not granted: {names(notGranted)}.{canConnect && ' Reauthorize to request access.'}
            </li>
          )}
        </ul>
      )}
      <button
        type="button"
        disabled={!!busy || reading || confirming}
        onClick={() => setReload((v) => v + 1)}
        className={actionButton}
      >
        Refresh status
      </button>
      {connection && <GoogleSyncStatus connection={connection} />}
      {connection && (canTest || connection.client_configured) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {canTest && (
            <p id={testDescriptionId} className="w-full text-xs text-slate-600">
              Test contacts Google to check the enabled access you granted. It imports nothing.
            </p>
          )}
          {canTest && (
            <button
              aria-describedby={testDescriptionId}
              type="button"
              className={actionButton}
              disabled={!!busy || reading || confirming}
              onClick={() => void testGrant()}
            >
              Test connection
            </button>
          )}
          {connection.client_configured && (
            <button
              type="button"
              ref={disconnectButton}
              aria-expanded={confirming}
              aria-disabled={!!busy || reading}
              className={actionButton}
              disabled={!!busy}
              onClick={() => {
                if (readingStatus.current || actionPending.current) return;
                dismissOutcome();
                setConfirming(true);
              }}
            >
              Disconnect Google connection
            </button>
          )}
        </div>
      )}
      <p role="status" aria-atomic="true" className="mt-2 text-sm font-medium text-slate-800">
        {reading && connection
          ? 'Refreshing local status…'
          : busy === 'test'
            ? 'Testing read-only access…'
            : busy === 'disconnect'
              ? 'Disconnecting…'
              : notice}
      </p>
      {probes && <GoogleTestResults results={probes} />}
      {warning && (
        <div role="alert" className="mt-2 text-sm text-amber-900">
          {warning}{' '}
          <a className="underline" href={safeHref('https://myaccount.google.com/connections')}>
            Manage third-party access in your Google Account
          </a>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      )}
      {confirming && (
        <fieldset
          className="mt-2 min-w-0 rounded border border-amber-300 p-3"
          aria-describedby={confirmId}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              cancelDisconnect();
            }
          }}
        >
          <legend className="font-semibold">Disconnect Google connection?</legend>
          <p id={confirmId} className="mb-2 text-sm">
            {hasGrant
              ? 'Remove the saved OAuth client and grant from NextUp.'
              : 'Remove the saved OAuth client from NextUp.'}{' '}
            Both Gmail and Calendar sync will pause. Your imported records and edits are kept.
            {hasGrant &&
              connection?.available &&
              connection.state !== 'unreadable' &&
              ' NextUp will try to revoke the grant at Google when safe.'}
            {hasGrant &&
              (!connection?.available || connection.state === 'unreadable') &&
              ' Check third-party access in your Google Account to confirm removal at Google.'}
            {connection?.credential_source === 'configured' &&
              ' The credentials in your installation configuration remain.'}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              ref={cancel}
              type="button"
              disabled={!!busy}
              className={actionButton}
              onClick={cancelDisconnect}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!!busy}
              className={actionButton}
              aria-disabled={!!busy || reading}
              onClick={() => void disconnect()}
            >
              Confirm disconnect
            </button>
          </div>
        </fieldset>
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
            {hasGrant
              ? 'Reauthorize through Google’s consent screen using the access selected below. Registered redirect URI:'
              : "Before connecting, add this address to the client's authorized redirect URIs:"}{' '}
            <code className="break-all">{window.location.origin + CALLBACK_PATH}</code>
          </p>
          <fieldset className="mt-2 min-w-0">
            <legend className="text-xs font-medium text-slate-600">Access to ask Google for</legend>
            {enabled.map((capability) => (
              <label key={capability} className="mr-4 mt-1 inline-flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  name="capability"
                  value={capability}
                  disabled={(!!busy && busy !== 'consent') || confirming}
                  checked={selected.includes(capability)}
                  onChange={() => toggle(capability)}
                />
                {capabilityLabels[capability]} (read-only)
              </label>
            ))}
          </fieldset>
          <button
            type="submit"
            disabled={!!busy || reading || confirming || selected.length === 0}
            aria-describedby={addressId}
            className="mt-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {hasGrant ? 'Reauthorize Google account' : 'Connect Google account'}
          </button>
          <p className="mt-1 text-[11px] text-slate-500">
            You will leave this page for Google's consent screen and be sent back here.
          </p>
        </form>
      )}

      {clientForm &&
        (hasGrant && connection?.state !== 'unreadable' ? (
          <details
            className="mt-3"
            onToggle={(e) => {
              if (!e.currentTarget.open) forgetSecret();
            }}
          >
            <summary className="cursor-pointer text-sm font-medium">
              Edit saved OAuth client
            </summary>
            {clientForm}
          </details>
        ) : (
          clientForm
        ))}
    </>
  );
}
