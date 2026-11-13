import { useEffect, useState } from 'react';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import type { Job } from '../jobs-api';
import {
  type JobRating,
  type JobRatingValue,
  clearJobRating,
  rateJob,
  readJobRatings,
} from './job-ratings-api';

/**
 * "More like this" / "Less like this" on one job. Clicking the active choice clears it.
 * Ratings move similar jobs by up to 15 points on the board, at the next discovery
 * ingest, and in the daily plan.
 */
export function RatingButtons({ job, onRated }: { job: Job; onRated: () => void }) {
  const [rating, setRating] = useState<number>(job.rating ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setRating(job.rating ?? 0), [job.rating]);

  async function choose(value: 1 | -1) {
    const next: JobRatingValue = rating === value ? 0 : value;
    setBusy(true);
    setError('');
    try {
      await rateJob(job.source, job.external_id, next);
      setRating(next);
      onRated();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rating not saved.');
    } finally {
      setBusy(false);
    }
  }

  const style = (active: boolean, tone: string) =>
    `inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium disabled:opacity-50 ${
      active ? tone : 'border-slate-300 text-slate-700 hover:bg-slate-50'
    }`;
  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        type="button"
        aria-pressed={rating === 1}
        disabled={busy}
        onClick={() => void choose(1)}
        title="Rank similar jobs higher, now and at the next discovery run"
        className={style(rating === 1, 'border-emerald-600 bg-emerald-50 text-emerald-800')}
      >
        <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />
        More like this
      </button>
      <button
        type="button"
        aria-pressed={rating === -1}
        disabled={busy}
        onClick={() => void choose(-1)}
        title="Rank similar jobs lower, hide this one, and never plan it"
        className={style(rating === -1, 'border-rose-600 bg-rose-50 text-rose-800')}
      >
        <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" />
        Less like this
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </span>
  );
}

/** Every rating that is tuning the scores, with a way to take each one back. */
export function RatingsPanel({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [ratings, setRatings] = useState<JobRating[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    readJobRatings()
      .then((rows) => active && setRatings(rows))
      .catch(() => active && setError('Ratings unavailable.'));
    return () => {
      active = false;
    };
  }, [version]);

  async function clear(row: JobRating) {
    setBusy(true);
    setError('');
    try {
      await clearJobRating(row.job_key);
      setRatings((rows) => rows.filter((r) => r.job_key !== row.job_key));
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not clear the rating.');
    } finally {
      setBusy(false);
    }
  }

  if (ratings.length === 0 && !error) return null;
  const liked = ratings.filter((r) => r.rating === 1).length;
  return (
    <details className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
      <summary className="cursor-pointer text-sm font-medium text-slate-800">
        Tuning from your ratings: {liked} more like this, {ratings.length - liked} less like this
      </summary>
      <p className="mt-2 text-xs text-slate-500">
        Jobs with similar titles (and the same employer) gain or lose up to 15 points. That reorders
        this board, decides which discovered jobs clear your minimum score at the next run, and
        steers the daily plan. Jobs you passed on are hidden and never planned.
      </p>
      <ul className="mt-2 space-y-1">
        {ratings.map((row) => (
          <li key={row.job_key} className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">
              <span
                className={`mr-2 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${row.rating === 1 ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'}`}
              >
                {row.rating === 1 ? 'More' : 'Less'}
              </span>
              {row.title} · {row.company}
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => void clear(row)}
              aria-label={`Clear rating for ${row.title} at ${row.company}`}
              className="shrink-0 rounded-md border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              Clear
            </button>
          </li>
        ))}
      </ul>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </details>
  );
}
