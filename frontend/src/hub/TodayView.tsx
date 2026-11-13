import { useEffect, useState } from 'react';
import { AlertTriangle, Calendar, CheckCircle, Clock, Target, Users } from 'lucide-react';
import { type TodayData, type CampaignTask, readToday, updateTask } from './campaign-api';
import MessageCard from './MessageCard';

const CATEGORY_COLORS: Record<string, string> = {
  administration: 'bg-slate-100 text-slate-700',
  pipeline: 'bg-blue-100 text-blue-700',
  planning: 'bg-purple-100 text-purple-700',
  networking: 'bg-indigo-100 text-indigo-700',
  resume: 'bg-amber-100 text-amber-700',
  profile: 'bg-teal-100 text-teal-700',
  sourcing: 'bg-cyan-100 text-cyan-700',
  applications: 'bg-emerald-100 text-emerald-700',
  content: 'bg-pink-100 text-pink-700',
  interview: 'bg-orange-100 text-orange-700',
  follow_up: 'bg-red-100 text-red-700',
  review: 'bg-yellow-100 text-yellow-700',
  evidence: 'bg-lime-100 text-lime-700',
  other: 'bg-slate-100 text-slate-600',
};

function TaskCard({
  task,
  onStatusChange,
  onUpdate,
  showReason,
}: {
  task: CampaignTask;
  onStatusChange: (id: string, status: string) => void;
  onUpdate: (id: string, data: Record<string, unknown>) => void;
  showReason?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [notes, setNotes] = useState(task.notes);
  const [status, setStatus] = useState(task.status);
  const [dueDate, setDueDate] = useState(task.due_date ?? '');
  const today = new Date().toLocaleDateString('sv-SE');
  const isDueToday = task.due_date === today;
  const isOverdue =
    task.due_date != null &&
    task.due_date < today &&
    task.status !== 'completed' &&
    task.status !== 'canceled';
  return (
    <div
      className={`rounded-xl border shadow-sm ${isDueToday ? 'border-amber-300 bg-amber-50/30' : isOverdue ? 'border-red-300 bg-red-50/30' : 'border-slate-200 bg-white'}`}
    >
      <div className="flex items-start gap-3 p-4">
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            const next = task.status === 'planned' ? 'in_progress' : 'completed';
            onStatusChange(task.id, next);
            setBusy(false);
          }}
          className="mt-0.5 shrink-0"
          title={task.status === 'in_progress' ? 'Mark complete' : 'Start'}
        >
          <CheckCircle
            className={`h-5 w-5 ${task.status === 'in_progress' ? 'text-emerald-500' : task.status === 'completed' ? 'text-emerald-400' : 'text-slate-300 hover:text-slate-500'}`}
          />
        </button>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="min-w-0 flex-1 text-left"
        >
          <p className="text-sm font-medium text-slate-900">{task.title}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${CATEGORY_COLORS[task.category] ?? CATEGORY_COLORS.other}`}
            >
              {task.category}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-semibold ${task.priority === 'P0' ? 'bg-red-100 text-red-700' : task.priority === 'P1' ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-600'}`}
            >
              {task.priority}
            </span>
            {task.estimated_minutes && (
              <span className="flex items-center gap-1 text-xs text-slate-500">
                <Clock className="h-3 w-3" /> {task.estimated_minutes}m
              </span>
            )}
            {task.due_date && (
              <span
                className={`text-xs ${isOverdue ? 'font-semibold text-red-600' : isDueToday ? 'font-semibold text-amber-600' : 'text-slate-500'}`}
              >
                {isOverdue ? 'OVERDUE ' : isDueToday ? 'DUE TODAY · ' : ''}
                {task.due_date}
              </span>
            )}
          </div>
          {showReason && task.priority_reason && (
            <p className="mt-1 text-xs text-slate-500">{task.priority_reason}</p>
          )}
          {!expanded && task.completion_criteria && (
            <p className="mt-1 text-xs text-slate-400">{task.completion_criteria.slice(0, 120)}…</p>
          )}
          {!expanded && task.communication && (
            <p className="mt-1 text-xs text-blue-700">
              Message from {task.communication.sender || 'an unknown sender'}. Open to read it in
              full.
            </p>
          )}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 px-4 pb-4 pt-3">
          {task.communication && (
            <div className="mb-3">
              <MessageCard
                message={task.communication}
                heading="Message to answer"
                reply={{
                  taskId: task.id,
                  sentLabel: 'Log as sent and complete task',
                  onDone: (status) => {
                    if (status === 'sent') onStatusChange(task.id, 'completed');
                  },
                }}
              />
            </div>
          )}
          {task.completion_criteria && (
            <div className="mb-3">
              <p className="text-xs font-medium text-slate-600">Completion criteria</p>
              <p className="mt-1 text-sm text-slate-700">{task.completion_criteria}</p>
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Status</span>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="planned">Planned</option>
                <option value="in_progress">In Progress</option>
                <option value="waiting">Waiting</option>
                <option value="blocked">Blocked</option>
                <option value="completed">Completed</option>
                <option value="canceled">Canceled</option>
              </select>
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Due date</span>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              {dueDate && dueDate !== task.due_date && (
                <p className="mt-1 text-[10px] text-amber-600">
                  Changed from {task.due_date ?? 'unset'}
                </p>
              )}
            </label>
          </div>
          <label className="mt-3 block text-xs">
            <span className="font-medium text-slate-600">Notes</span>
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Progress, decisions, links…"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          {task.depends_on.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">Depends on: {task.depends_on.join(', ')}</p>
          )}
          {task.suggested_after.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              Suggested after: {task.suggested_after.join(', ')}
            </p>
          )}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                onUpdate(task.id, { status, notes, due_date: dueDate || null });
                setBusy(false);
              }}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function TodayView({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState('');

  async function load() {
    try {
      setData(await readToday());
      setError('');
    } catch (err) {
      console.error('Action failed:', err);
      setError('Today view unavailable.');
    }
  }

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 30000);
    return () => clearInterval(timer);
  }, []);

  async function handleStatusChange(taskId: string, status: string) {
    if (!data?.campaign) return;
    try {
      await updateTask(data.campaign.id, taskId, { status });
      await load();
    } catch (err) {
      console.error('Action failed:', err);
      /* silent */
    }
  }

  async function handleUpdate(taskId: string, updates: Record<string, unknown>) {
    if (!data?.campaign) return;
    try {
      await updateTask(data.campaign.id, taskId, updates);
      await load();
    } catch (err) {
      console.error('Action failed:', err);
      /* silent */
    }
  }

  if (!data) return <p className="text-sm text-slate-500">{error || 'Loading…'}</p>;
  if (!data.campaign)
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
        <Target className="mx-auto h-8 w-8 text-slate-400" />
        <p className="mt-3 text-sm font-medium text-slate-700">No active campaign</p>
        <p className="mt-1 text-xs text-slate-500">
          Import your seed data or create a campaign from the Search Plan page.
        </p>
        <button
          type="button"
          onClick={() => onNavigate('plan')}
          className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          Go to Search Plan
        </button>
      </div>
    );

  const {
    campaign,
    priority_actions,
    overdue_tasks,
    today_tasks,
    upcoming_tasks,
    interviews,
    follow_ups,
    capacity,
    commitments,
  } = data;
  const capacityPercent = capacity
    ? Math.round((capacity.used_minutes / capacity.total_minutes) * 100)
    : 0;

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {/* Campaign banner */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl bg-slate-900 p-5 text-white">
        <div>
          <p className="text-xs font-medium text-slate-400">{campaign.title}</p>
          <p className="text-lg font-bold">
            Day {campaign.day_number + 1} · {campaign.days_remaining} days left
          </p>
        </div>
        {capacity && (
          <div className="w-48">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Capacity</span>
              <span>
                {capacity.used_minutes}m / {capacity.total_minutes}m
              </span>
            </div>
            <div className="mt-1 h-2 rounded-full bg-slate-700">
              <div
                className="h-2 rounded-full bg-emerald-500 transition-all"
                style={{ width: `${Math.min(capacityPercent, 100)}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Top 3 Priority Actions */}
      {priority_actions.length > 0 && (
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-slate-900">
            <Target className="h-5 w-5 text-red-500" /> Priority Actions
          </h2>
          <div className="space-y-3">
            {priority_actions.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                onStatusChange={handleStatusChange}
                onUpdate={handleUpdate}
                showReason
              />
            ))}
          </div>
        </div>
      )}

      {/* Overdue */}
      {overdue_tasks.length > 0 && (
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-red-700">
            <AlertTriangle className="h-5 w-5" /> Overdue ({overdue_tasks.length})
          </h2>
          <div className="space-y-2">
            {overdue_tasks.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                onStatusChange={handleStatusChange}
                onUpdate={handleUpdate}
              />
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Today's Tasks */}
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-slate-900">
            <Calendar className="h-5 w-5 text-blue-500" /> Today ({today_tasks.length})
          </h2>
          {today_tasks.length ? (
            <div className="space-y-2">
              {today_tasks.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
                  onStatusChange={handleStatusChange}
                  onUpdate={handleUpdate}
                />
              ))}
            </div>
          ) : (
            <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No tasks due today.</p>
          )}
        </div>

        {/* Upcoming */}
        <div>
          <h2 className="mb-3 text-base font-semibold text-slate-900">Upcoming (3 days)</h2>
          {upcoming_tasks.length ? (
            <div className="space-y-2">
              {upcoming_tasks.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
                  onStatusChange={handleStatusChange}
                  onUpdate={handleUpdate}
                />
              ))}
            </div>
          ) : (
            <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No upcoming tasks.</p>
          )}
        </div>
      </div>

      {/* Interviews & Commitments */}
      {(interviews.length > 0 || commitments.length > 0) && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {interviews.length > 0 && (
            <div>
              <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-slate-900">
                <Users className="h-5 w-5 text-orange-500" /> Interviews
              </h2>
              <div className="space-y-2">
                {interviews.map((i) => (
                  <div key={i.id} className="rounded-lg border border-slate-200 bg-white p-3">
                    <p className="text-sm font-medium text-slate-900">{i.title}</p>
                    <p className="text-xs text-slate-500">
                      {i.company} {i.next_action_on ? `· ${i.next_action_on}` : ''}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {follow_ups.length > 0 && (
            <div>
              <h2 className="mb-3 text-base font-semibold text-slate-900">Follow-ups Due</h2>
              <div className="space-y-2">
                {follow_ups.map((f) => (
                  <div key={f.id} className="rounded-lg border border-slate-200 bg-white p-3">
                    <p className="text-sm font-medium text-slate-900">{f.title}</p>
                    <p className="text-xs text-slate-500">
                      {f.company} · {f.stage} · due {f.next_action_on}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
