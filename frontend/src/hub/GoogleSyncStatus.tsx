import {
  capabilityLabels,
  type Capability,
  type GoogleAttemptStatus,
  type GoogleConnection,
  type GoogleProbeResult,
} from './google-api';

const capabilities: Capability[] = ['gmail', 'calendar'];

const attemptText: Record<GoogleAttemptStatus, string> = {
  not_run: 'No recorded attempt',
  ok: 'OK',
  disabled: 'Disabled',
  not_configured: 'Configure the connection',
  needs_reauthorization: 'Reauthorize the Google account',
  wrong_scope: 'Reauthorize and grant read-only access',
  admin_restricted: 'Ask your Google administrator about access',
  temporarily_unavailable: 'Temporarily unavailable. Try again later',
  unreadable: 'Check the installation encryption key',
  connection_error: 'Check the local connection settings',
  provider_rejected: 'Google refused the request. Check the grant',
};

const probeText: Record<GoogleProbeResult, string> = {
  ok: 'Read-only access verified',
  disabled: 'Disabled in this installation',
  not_granted: 'Not granted. Reauthorize to request access',
  wrong_scope: attemptText.wrong_scope,
  needs_reauthorization: attemptText.needs_reauthorization,
  admin_restricted: attemptText.admin_restricted,
  temporarily_unavailable: attemptText.temporarily_unavailable,
  provider_rejected: attemptText.provider_rejected,
};

const freshnessText = {
  inactive: 'Inactive',
  unknown: 'Unknown',
  current: 'Current',
  stale: 'Stale',
};

function time(value: string) {
  return <time dateTime={value}>{new Date(value).toLocaleString()}</time>;
}

export function GoogleSyncStatus({ connection }: { connection: GoogleConnection }) {
  return (
    <div className="my-3 grid gap-2 sm:grid-cols-2">
      {capabilities.map((name) => {
        const sync = connection.sync[name];
        const title = capabilityLabels[name] + ' sync';
        return (
          <section
            key={name}
            aria-label={title}
            className="min-w-0 rounded border border-slate-200 p-2 text-xs text-slate-700"
          >
            <h4 className="font-semibold">{title}</h4>
            <p>
              {connection.enabled_capabilities.includes(name)
                ? 'Enabled in this installation'
                : 'Disabled in this installation'}{' '}
              · Sync {sync.active ? 'on' : 'off'}
            </p>
            <p>Freshness: {freshnessText[sync.freshness]}</p>
            <p>
              Last successful sync:{' '}
              {sync.last_success_at ? time(sync.last_success_at) : 'No verified success'}
            </p>
            <p>
              Last attempt: {attemptText[sync.last_status]}
              {sync.last_attempt_at && <> · {time(sync.last_attempt_at)}</>}
            </p>
          </section>
        );
      })}
    </div>
  );
}

export function GoogleTestResults({ results }: { results: Record<Capability, GoogleProbeResult> }) {
  return (
    <section aria-label="Connection test results" className="mt-2 text-sm text-slate-700">
      <h4 className="font-semibold">Connection test results</h4>
      <ul>
        {capabilities.map((name) => (
          <li key={name}>
            {capabilityLabels[name]}: {probeText[results[name]]}
          </li>
        ))}
      </ul>
      <p className="text-xs">
        Testing reads account access. Sync history changes when a sync runs.
      </p>
    </section>
  );
}
