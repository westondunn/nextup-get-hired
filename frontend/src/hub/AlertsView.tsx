import { useEffect, useState } from 'react';
import { request, type Job } from '../jobs-api';
import { trackJobChecked, announce } from './career-api';
import { JobDetailModal } from './JobBoardView';

interface InboxAlert {
  id: string;
  search_name: string;
  job: Job;
  created_at: string;
  read_at: string | null;
}
interface InboxPage {
  items: InboxAlert[];
  total: number;
  unread: number;
}

export default function AlertsView() {
  const [page, setPage] = useState<InboxPage | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await request<InboxPage>(
          `alerts?unread_only=${unreadOnly}&offset=${offset}&limit=10`,
        );
        if (active) {
          if (offset > 0 && offset >= result.total) {
            setOffset(Math.max(0, Math.floor((result.total - 1) / 10) * 10));
            return;
          }
          setPage(result);
          setError('');
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Inbox unavailable.');
      } finally {
        if (active) {
          setLoading(false);
          timer = setTimeout(poll, 5000);
        }
      }
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [unreadOnly, offset, refresh]);

  async function markRead(id: string) {
    setBusy(id);
    try {
      await request<InboxAlert>(`alerts/${id}/read`, { method: 'PUT' });
      setRefresh((v) => v + 1);
    } catch (err) {
      console.error('Action failed:', err);
      /* silent */
    } finally {
      setBusy(null);
    }
  }

  async function handleTrack(job: Job) {
    try {
      if (await trackJobChecked(job.source, job.external_id)) announce();
    } catch (err) {
      console.error('Action failed:', err);
      /* silent */
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Alert Inbox</h2>
          <p className="mt-1 text-sm text-slate-500">
            Local job match notifications from your saved searches.
            {page ? ` ${page.unread} unread.` : ''}
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => {
              setUnreadOnly(e.target.checked);
              setOffset(0);
              setLoading(true);
            }}
            className="accent-slate-900"
          />
          Unread only
        </label>
      </div>

      {error && <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {loading ? (
        <p className="mt-6 text-sm text-slate-500">Loading…</p>
      ) : !error && page?.items.length === 0 ? (
        <p className="mt-6 text-sm text-slate-500">
          No {unreadOnly ? 'unread ' : ''}alerts yet. Enable alerts on a saved search to start
          receiving matches.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {page?.items.map((alert) => (
            <li
              key={alert.id}
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-slate-900">{alert.job.title}</h3>
                  <p className="text-sm text-slate-500">
                    {alert.job.company} · {alert.job.location}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${alert.read_at ? 'bg-slate-100 text-slate-600' : 'bg-red-100 text-red-700'}`}
                >
                  {alert.read_at ? 'Read' : 'New'}
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-600">
                {alert.search_name} · Score {alert.job.score}/100 ·{' '}
                {new Date(alert.created_at).toLocaleString()}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedJob(alert.job)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  View details
                </button>
                {!alert.read_at && (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void markRead(alert.id)}
                    className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    Mark read
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void handleTrack(alert.job)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Track job
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!loading && !error && page && page.total > 10 && (
        <nav className="mt-4 flex items-center gap-4">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => {
              setOffset((v) => Math.max(0, v - 10));
              setLoading(true);
            }}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-sm text-slate-600">
            {offset + 1}–{Math.min(offset + 10, page.total)} of {page.total}
          </span>
          <button
            type="button"
            disabled={offset + 10 >= page.total}
            onClick={() => {
              setOffset((v) => v + 10);
              setLoading(true);
            }}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Next
          </button>
        </nav>
      )}

      {selectedJob && (
        <JobDetailModal job={selectedJob} snapshot onClose={() => setSelectedJob(null)} />
      )}
    </div>
  );
}
