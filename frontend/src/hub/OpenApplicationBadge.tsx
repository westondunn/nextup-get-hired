import type { Job } from '../jobs-api';

const stageLabel = (stage: string) => stage.charAt(0).toUpperCase() + stage.slice(1);

/**
 * Marks a job whose employer already has an open (not closed) application:
 * "In your applications" when it is this job, otherwise a warning naming the other one.
 */
export default function OpenApplicationBadge({ job }: { job: Job }) {
  const open = job.open_applications ?? [];
  if (open.length === 0) return null;
  const mine = open.find((a) => a.same_job);
  const others = open.filter((a) => !a.same_job);
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5">
      {mine && (
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
          In your applications · {stageLabel(mine.stage)}
        </span>
      )}
      {others.length > 0 && (
        <span
          className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900"
          title={others.map((a) => `${a.title} (${a.stage})`).join('\n')}
        >
          Open application at {others[0].company}: {others[0].title} · {stageLabel(others[0].stage)}
          {others.length > 1 ? ` (+${others.length - 1} more)` : ''}
        </span>
      )}
    </span>
  );
}
