import { useEffect, useState } from 'react';
import { type Diagnostic, type Health, readDiagnostic, readHealth, startDiagnostic } from '../api';
import { cleanupHistory, previewHistory, type HistoryPreview } from '../retention-api';

const SERVICE_LABELS: Record<string, string> = {
  api: 'API',
  database: 'PostgreSQL',
  broker: 'Redis broker',
  worker: 'Celery worker',
};

function statusColor(status?: string) {
  if (status === 'up') return 'text-emerald-600';
  if (status === 'down') return 'text-red-600';
  return 'text-slate-500';
}

function statusLabel(status?: string) {
  if (status === 'up') return 'Responding';
  if (status === 'down') return 'Unavailable';
  return 'Unknown';
}

export default function SystemView() {
  // Health
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState('');

  // Diagnostics
  const [run, setRun] = useState<Diagnostic | null>(null);
  const [diagBusy, setDiagBusy] = useState(false);
  const [diagError, setDiagError] = useState('');

  // Task history
  const [preview, setPreview] = useState<HistoryPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [histBusy, setHistBusy] = useState(false);
  const [histError, setHistError] = useState('');
  const [histMsg, setHistMsg] = useState('');

  // Health polling
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await readHealth();
        if (active) {
          setHealth(next);
          setHealthError('');
        }
      } catch (err) {
        console.error('Action failed:', err);
        if (active) {
          setHealth(null);
          setHealthError('API unreachable.');
        }
      }
      if (active) timer = setTimeout(poll, 5000);
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);

  // Diagnostic polling
  useEffect(() => {
    if (!run || !['queued', 'publish_failed'].includes(run.status)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const id = run.id;
    async function poll() {
      try {
        const next = await readDiagnostic(id);
        if (active) {
          setRun(next);
          setDiagError('');
        }
        if (!['queued', 'publish_failed'].includes(next.status)) return;
      } catch (err) {
        console.error('Action failed:', err);
        if (active) setDiagError('Waiting for result…');
      }
      if (active) timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [run?.id, run?.status]);

  async function diagnose() {
    setDiagBusy(true);
    setDiagError('');
    try {
      setRun(await startDiagnostic());
    } catch (cause) {
      setDiagError(cause instanceof Error ? cause.message : 'Failed.');
    } finally {
      setDiagBusy(false);
    }
  }

  async function loadPreview() {
    setHistBusy(true);
    setPreview(null);
    setConfirmed(false);
    setHistError('');
    setHistMsg('');
    try {
      setPreview(await previewHistory());
    } catch (cause) {
      setHistError(cause instanceof Error ? cause.message : 'Preview unavailable.');
    } finally {
      setHistBusy(false);
    }
  }

  async function clean() {
    if (!preview?.enabled || !confirmed || histBusy) return;
    setHistBusy(true);
    setHistError('');
    try {
      const { groups } = await cleanupHistory(preview.token);
      setHistMsg(
        `Deleted ${groups.diagnostics.deleted} diagnostics and ${groups.fetches.deleted} fetches. Skipped ${groups.diagnostics.skipped + groups.fetches.skipped}.`,
      );
    } catch (cause) {
      setHistError(cause instanceof Error ? cause.message : 'Cleanup failed.');
    } finally {
      setPreview(null);
      setConfirmed(false);
      setHistBusy(false);
    }
  }

  const displayedRun = run ?? health?.latest_diagnostic;

  return (
    <div className="space-y-8">
      {/* Service status */}
      <div>
        <h2 className="text-xl font-bold text-slate-900">System Status</h2>
        <p className="mt-1 text-sm text-slate-500">
          {healthError
            ? 'Connection unavailable'
            : health?.status === 'ok'
              ? 'All services responding'
              : health
                ? 'Attention needed'
                : 'Checking…'}
        </p>
        {healthError && (
          <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{healthError}</div>
        )}
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(SERVICE_LABELS).map(([key, label]) => {
            const status = health?.checks[key as keyof Health['checks']];
            return (
              <div key={key} className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-sm font-medium text-slate-700">{label}</p>
                <p
                  className={`mt-1 flex items-center gap-2 text-sm font-semibold ${statusColor(status)}`}
                >
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${status === 'up' ? 'bg-emerald-500' : status === 'down' ? 'bg-red-500' : 'bg-slate-400'}`}
                  />
                  {statusLabel(status)}
                </p>
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Updates every 5 seconds
          {health && ` · Last ${new Date(health.checked_at).toLocaleTimeString()}`}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Scheduler: <strong>{health?.scheduler ?? 'unknown'}</strong>
          {health ? `. Check interval: ${health.diagnostic_interval_seconds}s.` : ''}
        </p>
      </div>

      {/* Diagnostics */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="text-base font-semibold text-slate-900">End-to-End Diagnostic</h3>
        <p className="mt-1 text-sm text-slate-500">API → Redis → Celery worker → PostgreSQL</p>
        <button
          type="button"
          onClick={() => void diagnose()}
          disabled={diagBusy || run?.status === 'queued' || run?.status === 'publish_failed'}
          className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {diagBusy
            ? 'Submitting…'
            : run?.status === 'queued' || run?.status === 'publish_failed'
              ? 'Waiting for worker…'
              : 'Run diagnostic'}
        </button>
        {diagError && <p className="mt-2 text-sm text-red-600">{diagError}</p>}
        {displayedRun && (
          <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm">
            <p className="font-medium text-slate-900">
              {displayedRun.status === 'succeeded'
                ? 'Result saved to PostgreSQL'
                : displayedRun.status === 'queued'
                  ? 'Queued — awaiting worker'
                  : displayedRun.status === 'publish_failed'
                    ? 'Delivery unconfirmed — retry pending'
                    : (displayedRun.error_message ?? 'Diagnostic failed.')}
            </p>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-slate-500">Task ID</dt>
              <dd className="font-mono text-xs text-slate-700">{displayedRun.id}</dd>
              <dt className="text-slate-500">Worker</dt>
              <dd className="text-slate-700">{displayedRun.worker ?? 'Pending'}</dd>
              <dt className="text-slate-500">Source</dt>
              <dd className="text-slate-700">{displayedRun.source}</dd>
              <dt className="text-slate-500">Completed</dt>
              <dd className="text-slate-700">
                {displayedRun.completed_at
                  ? new Date(displayedRun.completed_at).toLocaleString()
                  : 'Pending'}
              </dd>
            </dl>
          </div>
        )}
      </div>

      {/* Task history */}
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="text-base font-semibold text-slate-900">Task History</h3>
        <p className="mt-1 text-sm text-slate-500">
          Preview and clean up old completed diagnostics and fetch records. Active work is
          preserved.
        </p>
        <button
          type="button"
          disabled={histBusy}
          onClick={() => void loadPreview()}
          className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {histBusy ? 'Please wait…' : 'Preview cleanup'}
        </button>
        {histError && <p className="mt-2 text-sm text-red-600">{histError}</p>}
        {histMsg && <p className="mt-2 text-sm text-emerald-600">{histMsg}</p>}
        {preview && (
          <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm">
            <p className="text-slate-700">
              Completed before {new Date(preview.cutoff).toLocaleString()} ({preview.retention_days}{' '}
              days). Up to {preview.batch_size} per type.
            </p>
            <ul className="mt-2 space-y-1 text-slate-600">
              <li>
                Diagnostics: {preview.groups.diagnostics.selected} of{' '}
                {preview.groups.diagnostics.eligible} eligible
              </li>
              <li>
                Fetches: {preview.groups.fetches.selected} of {preview.groups.fetches.eligible}{' '}
                eligible
              </li>
            </ul>
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">
                Review records
              </summary>
              {(['diagnostics', 'fetches'] as const).map((kind) => (
                <ul key={kind} className="mt-2 space-y-1 text-xs text-slate-600">
                  {preview.groups[kind].items.map((item) => (
                    <li key={item.id}>
                      {item.source} · {item.status} · {new Date(item.completed_at).toLocaleString()}{' '}
                      · <code className="text-slate-500">{item.id}</code>
                    </li>
                  ))}
                </ul>
              ))}
            </details>
            <p className="mt-2 text-xs text-slate-500">
              Expires {new Date(preview.expires_at).toLocaleTimeString()}.
            </p>
            {!preview.enabled ? (
              <p className="mt-2 text-sm text-amber-700">
                Cleanup is switched off in this installation's configuration.
              </p>
            ) : preview.groups.diagnostics.selected + preview.groups.fetches.selected > 0 ? (
              <div className="mt-3">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    disabled={histBusy}
                    onChange={(e) => setConfirmed(e.target.checked)}
                    className="accent-slate-900"
                  />
                  Delete the previewed history
                </label>
                <button
                  type="button"
                  disabled={!confirmed || histBusy}
                  onClick={() => void clean()}
                  className="mt-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            ) : (
              <p className="mt-2 text-sm text-slate-600">No eligible history.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
