import { useEffect, useState } from 'react';
import { parseDelimited } from './csv';
import { safeHref } from './safe';
import {
  type FetchRun,
  type Job,
  type JobFilters,
  type JobPage,
  type JobView,
  type SourceStatus,
  emptyJobFilters,
  readJobs,
  readLatestFetch,
  readSourceStatus,
  sourceLabels,
  startJobFetch,
  saveJobReference,
  importCsvJobs,
} from '../jobs-api';
import { trackJobChecked, announce } from './career-api';
import OpenApplicationBadge from './OpenApplicationBadge';
import SavedSearchesBar from './SavedSearchesBar';
import { RatingButtons, RatingsPanel } from './JobRatings';

const HIDE_OPEN_KEY = 'nextup.jobBoard.hideOpenCompanies';

function FilterPanel({
  value,
  scoringAvailable,
  onApply,
}: {
  value: JobFilters;
  scoringAvailable: boolean;
  onApply: (f: JobFilters) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  return (
    <details className="mt-4 rounded-xl border border-slate-200 bg-white p-4" open>
      <summary className="cursor-pointer text-sm font-semibold text-slate-700">
        Filter &amp; sort
      </summary>
      <form
        className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          onApply({ ...draft });
        }}
      >
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Keywords</span>
          <input
            maxLength={160}
            value={draft.q}
            placeholder="All words must appear"
            onChange={(e) => setDraft({ ...draft, q: e.target.value })}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Company</span>
          <input
            maxLength={160}
            value={draft.company}
            onChange={(e) => setDraft({ ...draft, company: e.target.value })}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Location</span>
          <input
            maxLength={160}
            value={draft.location}
            onChange={(e) => setDraft({ ...draft, location: e.target.value })}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Exclude</span>
          <input
            maxLength={200}
            value={draft.exclude}
            placeholder="intern, internship"
            onChange={(e) => setDraft({ ...draft, exclude: e.target.value })}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Work mode</span>
          <select
            value={draft.work_mode}
            onChange={(e) =>
              setDraft({ ...draft, work_mode: e.target.value as JobFilters['work_mode'] })
            }
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="any">Any</option>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">On-site</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Max age</span>
          <select
            value={draft.max_age_days}
            onChange={(e) => setDraft({ ...draft, max_age_days: e.target.value })}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Any</option>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </select>
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Min score</span>
          <input
            type="number"
            min={0}
            max={100}
            disabled={!scoringAvailable}
            value={draft.min_score}
            placeholder="None"
            onChange={(e) => setDraft({ ...draft, min_score: e.target.value })}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Sort</span>
          <select
            value={draft.sort}
            onChange={(e) => setDraft({ ...draft, sort: e.target.value as JobFilters['sort'] })}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="newest">Newest</option>
            <option value="score" disabled={!scoringAvailable}>
              Highest score
            </option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={draft.discovery_only}
            disabled={!scoringAvailable}
            onChange={(e) => setDraft({ ...draft, discovery_only: e.target.checked })}
            className="accent-slate-900"
          />
          Discovery matches only
        </label>
        <div className="flex items-end gap-2">
          <button
            type="submit"
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            Apply
          </button>
          <button
            type="button"
            onClick={() => {
              const c = emptyJobFilters();
              setDraft(c);
              onApply(c);
            }}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Clear
          </button>
        </div>
      </form>
    </details>
  );
}

function AddJobModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [company, setCompany] = useState('');
  const [location, setLocation] = useState('');
  const [description, setDescription] = useState('');
  const [alsoTrack, setAlsoTrack] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const result = await saveJobReference({
        title: title.trim(),
        company: company.trim(),
        location: location.trim(),
        description: description.trim(),
        url: url.trim(),
      });
      if (alsoTrack && (await trackJobChecked(result.source, result.external_id))) {
        announce();
      }
      onAdded();
      onClose();
    } catch (err) {
      console.error('Action failed:', err);
      setError(err instanceof Error ? err.message : 'Could not save job.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-900">Add Job Manually</h2>
        <p className="mt-1 text-sm text-slate-500">
          Paste a job from any source — LinkedIn, company site, referral, etc.
        </p>
        <form onSubmit={(e) => void submit(e)} className="mt-4 space-y-3">
          <label className="block text-sm">
            <span className="font-medium text-slate-700">URL</span>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              placeholder="https://..."
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Title</span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                placeholder="Software Engineer"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Company</span>
              <input
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                required
                placeholder="Acme Corp"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Location</span>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              required
              placeholder="Remote / San Francisco, CA"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Paste the job description (optional)"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={alsoTrack}
              onChange={(e) => setAlsoTrack(e.target.checked)}
              className="accent-slate-900"
            />
            Add to my pipeline immediately
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Add Job'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function TrackButton({ job }: { job: Job }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  async function handle() {
    setBusy(true);
    try {
      const r = await trackJobChecked(job.source, job.external_id);
      if (r === null) {
        setMsg('Not tracked');
        return;
      }
      setMsg(r.created ? 'Added to pipeline' : 'Already tracked');
      announce();
    } catch (e) {
      console.error('Action failed:', e);
      setMsg(e instanceof Error ? e.message : 'Error');
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => void handle()}
        className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
      >
        {busy ? 'Saving…' : 'Track'}
      </button>
      {msg && <span className="text-xs text-slate-500">{msg}</span>}
    </span>
  );
}

function JobDetailModal({
  job,
  onClose,
  snapshot = false,
  onRated,
}: {
  job: Job;
  onClose: () => void;
  snapshot?: boolean;
  onRated?: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-slate-900">{job.title}</h2>
            <p className="text-sm text-slate-500">
              {job.company} · {job.location}
            </p>
            <OpenApplicationBadge job={job} />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Close
          </button>
        </div>
        <p className="mt-2 text-sm text-slate-600">
          {sourceLabels[job.source]} ·{' '}
          {job.date_kind === 'observed'
            ? 'Observed'
            : job.date_kind === 'updated'
              ? 'Updated'
              : 'Posted'}{' '}
          {new Date(job.posted_at).toLocaleDateString()}
          {job.expired ? ' · Expired' : ''}
        </p>
        <p className="mt-1 text-sm font-semibold text-emerald-600">
          {job.score != null ? `Match: ${job.score}/100` : 'Unscored'}
        </p>
        {job.score_breakdown && (
          <div className="mt-4 rounded-lg bg-slate-50 p-4">
            <h3 className="text-sm font-semibold text-slate-700">Score evidence</h3>
            {job.score_breakdown.components.map((c) => (
              <div key={c.key} className="mt-2">
                <p className="text-sm font-medium text-slate-800">
                  {c.label}: {c.points}/{c.maximum}
                </p>
                <p className="text-xs text-slate-600">{c.evidence.join(' ')}</p>
              </div>
            ))}
          </div>
        )}
        <div className="mt-4">
          <h3 className="text-sm font-semibold text-slate-700">Description</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">
            {job.description || 'No description.'}
          </p>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {(job.origins ?? [job])
            .filter((o) => /^https?:\/\//i.test(o.url))
            .map((o) => (
              <a
                key={`${o.source}:${o.external_id}`}
                href={safeHref(o.url)}
                target="_blank"
                rel="noreferrer"
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                View on {sourceLabels[o.source]} ↗
              </a>
            ))}
          <TrackButton job={job} />
          {onRated && <RatingButtons job={job} onRated={onRated} />}
        </div>
        <p className="mt-4 text-xs text-slate-500">
          {snapshot ? 'Snapshot from when this alert was created.' : 'Details from stored record.'}
        </p>
      </div>
    </div>
  );
}

export { JobDetailModal };

export default function JobBoardView() {
  const [source, setSource] = useState<JobView>('all');
  const [includeExpired, setIncludeExpired] = useState(false);
  const [filters, setFilters] = useState(emptyJobFilters);
  const [page, setPage] = useState<JobPage>({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [run, setRun] = useState<FetchRun | null>(null);
  const [config, setConfig] = useState<SourceStatus | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [showAddJob, setShowAddJob] = useState(false);
  const [showPassed, setShowPassed] = useState(false);
  // Remembered per browser; the API decides live, so closing an application
  // brings that employer's jobs back without touching this switch.
  const [hideOpen, setHideOpen] = useState(() => {
    try {
      return window.localStorage.getItem(HIDE_OPEN_KEY) === 'true';
    } catch {
      return false;
    }
  });
  const [ratingsVersion, setRatingsVersion] = useState(0);
  const combined = source === 'all';
  // A rating rescores every similar job, so reload the page and the tuning panel.
  const afterRating = () => {
    setRatingsVersion((v) => v + 1);
    setRefresh((v) => v + 1);
  };

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [nextConfig, nextPage, nextRun] = await Promise.all([
          readSourceStatus(source === 'greenhouse' ? 'greenhouse' : 'adzuna'),
          readJobs(source, offset, includeExpired, filters, !showPassed, hideOpen),
          combined ? Promise.resolve(null) : readLatestFetch(source),
        ]);
        if (active) {
          setConfig(nextConfig);
          setPage(nextPage);
          setRun(nextRun);
          setError('');
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : 'Job data unavailable.');
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
  }, [source, offset, refresh, includeExpired, filters, showPassed, hideOpen]);

  function chooseSource(next: JobView) {
    setSource(next);
    setRefresh((v) => v + 1);
    setOffset(0);
    setPage({ items: [], total: 0 });
    setRun(null);
    setConfig(null);
    setError('');
    setLoading(true);
    setActionError('');
  }

  async function fetchJobs() {
    if (combined) return;
    setSubmitting(true);
    setActionError('');
    try {
      setRun(await startJobFetch(source));
      setOffset(0);
      setRefresh((v) => v + 1);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : 'Fetch failed.');
    } finally {
      setSubmitting(false);
    }
  }

  const pending =
    run?.status === 'queued' ||
    run?.status === 'running' ||
    (run?.status === 'publish_failed' && Boolean(run.recovery_deadline));
  const summary = page.summary;

  return (
    <div>
      <h2 className="text-xl font-bold text-slate-900">Job Board</h2>
      <div className="flex items-center justify-between">
        <p className="mt-1 text-sm text-slate-500">
          Browse, search, and filter job listings from multiple sources.
        </p>
        <div className="flex gap-2">
          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <span>Import CSV</span>
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (!file) return;
                try {
                  const text = await file.text();
                  const lines = parseDelimited(text);
                  if (lines.length < 2) {
                    setActionError('CSV must have a header row and at least one data row.');
                    return;
                  }
                  const headers = lines[0].map((h) => h.trim().toLowerCase().replace(/\s+/g, '_'));
                  const rows = lines.slice(1).map((vals) => {
                    const obj: Record<string, string> = {};
                    headers.forEach((h, i) => {
                      obj[h] = vals[i]?.trim() ?? '';
                    });
                    return obj;
                  });
                  const result = await importCsvJobs(rows);
                  setRefresh((v) => v + 1);
                  setActionError('');
                  alert(
                    `Imported ${result.imported} jobs, ${result.skipped} skipped.${result.errors.length ? '\n' + result.errors.join('\n') : ''}`,
                  );
                } catch (err) {
                  console.error('CSV import failed:', err);
                  setActionError(err instanceof Error ? err.message : 'CSV import failed.');
                }
              }}
            />
          </label>
          <button
            type="button"
            onClick={() => setShowAddJob(true)}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            + Add Job
          </button>
        </div>
      </div>

      {/* Summary stats */}
      {summary && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            [
              ['Matching', summary.results],
              ['Sources', summary.source_records],
              ['Score 70+', summary.high_score_results ?? '—'],
              ['Avg score', summary.average_score ?? '—'],
            ] as const
          ).map(([label, val]) => (
            <div key={label} className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-medium text-slate-500">{label}</p>
              <p className="text-2xl font-bold text-slate-900">{val}</p>
            </div>
          ))}
        </div>
      )}

      {/* Source controls */}
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Source</span>
          <select
            value={source}
            onChange={(e) => chooseSource(e.target.value as JobView)}
            disabled={submitting}
            className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="all">Discovered &amp; saved</option>
            <option value="adzuna">Adzuna</option>
            <option value="greenhouse">Greenhouse</option>
          </select>
        </label>
        {!combined && (
          <button
            type="button"
            onClick={() => void fetchJobs()}
            disabled={loading || submitting || pending || !!error || !config?.ready}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {submitting ? 'Submitting…' : pending ? 'Fetching…' : `Fetch ${source}`}
          </button>
        )}
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={includeExpired}
            onChange={(e) => {
              setIncludeExpired(e.target.checked);
              setOffset(0);
              setLoading(true);
            }}
            className="accent-slate-900"
          />
          Show expired
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={showPassed}
            onChange={(e) => {
              setShowPassed(e.target.checked);
              setOffset(0);
              setLoading(true);
            }}
            className="accent-slate-900"
          />
          Show jobs you passed on
        </label>
        <label
          className="flex items-center gap-2 text-xs"
          title="Jobs at these employers return as soon as the application there is closed"
        >
          <input
            type="checkbox"
            checked={hideOpen}
            onChange={(e) => {
              const next = e.target.checked;
              setHideOpen(next);
              try {
                window.localStorage.setItem(HIDE_OPEN_KEY, String(next));
              } catch {
                // Private mode or blocked storage: the switch still works for this visit.
              }
              setOffset(0);
              setLoading(true);
            }}
            className="accent-slate-900"
          />
          Hide employers with an open application
        </label>
      </div>

      <RatingsPanel version={ratingsVersion} onChanged={afterRating} />

      {/* Status */}
      <SavedSearchesBar
        current={{ source, include_expired: includeExpired, filters }}
        onLoad={(saved) => {
          chooseSource(saved.source);
          setIncludeExpired(saved.include_expired);
          setFilters({ ...saved.filters });
        }}
      />

      {run && (
        <p
          className={`mt-3 text-sm ${run.status === 'failed' || run.status === 'publish_failed' ? 'text-red-600' : 'text-slate-600'}`}
        >
          {run.status === 'succeeded'
            ? `Saved ${run.stored_count} listings (${run.skipped_count} skipped).`
            : run.status === 'queued'
              ? 'Queued — waiting for worker.'
              : run.status === 'running'
                ? 'Fetching…'
                : (run.error_message ?? 'Fetch incomplete.')}
        </p>
      )}

      <FilterPanel
        value={filters}
        scoringAvailable={page.scoring_available === true}
        onApply={(f) => {
          setFilters(f);
          setOffset(0);
          setLoading(true);
        }}
      />

      {error && <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {actionError && (
        <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{actionError}</div>
      )}

      {/* Job list */}
      {loading ? (
        <p className="mt-6 text-sm text-slate-500">Loading…</p>
      ) : page.items.length === 0 ? (
        <p className="mt-6 text-sm text-slate-500">No jobs match current filters.</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {page.items.map((job) => (
            <li
              key={`${job.source}:${job.external_id}`}
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-slate-900">{job.title}</h3>
                  <p className="text-sm text-slate-500">
                    {job.company} · {job.location}
                  </p>
                  <OpenApplicationBadge job={job} />
                </div>
                <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                  {(job.origins ?? [job])
                    .map((o) => sourceLabels[o.source])
                    .filter((v, i, a) => a.indexOf(v) === i)
                    .join(' · ')}
                </span>
              </div>
              <p className="mt-1 text-sm font-medium text-emerald-600">
                {job.score != null ? `Match: ${job.score}/100` : 'Unscored'}
              </p>
              <p className="mt-2 text-sm text-slate-600">
                {job.description.length > 200
                  ? `${job.description.slice(0, 200)}…`
                  : job.description}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => setSelectedJob(job)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  View details
                </button>
                <TrackButton job={job} />
                <RatingButtons job={job} onRated={afterRating} />
                <span className="text-xs text-slate-500">
                  {job.date_kind === 'observed'
                    ? 'Observed'
                    : job.date_kind === 'updated'
                      ? 'Updated'
                      : 'Posted'}{' '}
                  {new Date(job.posted_at).toLocaleDateString()}
                  {job.expired ? ' · Expired' : ''}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Pagination */}
      {page.total > 10 && (
        <nav className="mt-4 flex items-center gap-4" aria-label="Job pages">
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
        <JobDetailModal
          job={selectedJob}
          onClose={() => setSelectedJob(null)}
          onRated={afterRating}
        />
      )}
      {showAddJob && (
        <AddJobModal
          onClose={() => setShowAddJob(false)}
          onAdded={() => setRefresh((v) => v + 1)}
        />
      )}
    </div>
  );
}
