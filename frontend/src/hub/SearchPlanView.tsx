import { useEffect, useState } from 'react';
import { localDate } from './safe';
import { Plus, Upload, CheckCircle, Clock, CalendarDays, List } from 'lucide-react';
import {
  type Campaign,
  type CampaignTask,
  type SeedPreview,
  type SeedResult,
  readCampaigns,
  updateCampaign,
  readTasks,
  createTask,
  updateTask,
  previewSeed,
  applySeed,
} from './campaign-api';
import MessageCard from './MessageCard';

const CATEGORIES = [
  'administration',
  'pipeline',
  'planning',
  'networking',
  'resume',
  'profile',
  'sourcing',
  'applications',
  'content',
  'interview',
  'follow_up',
  'review',
  'evidence',
  'other',
];
const STATUSES = ['planned', 'in_progress', 'waiting', 'blocked', 'completed', 'canceled'];
const PRIORITIES = ['P0', 'P1', 'P2', 'P3'];

const STATUS_COLORS: Record<string, string> = {
  planned: 'bg-slate-100 text-slate-700',
  in_progress: 'bg-blue-100 text-blue-700',
  waiting: 'bg-amber-100 text-amber-700',
  blocked: 'bg-red-100 text-red-700',
  completed: 'bg-emerald-100 text-emerald-700',
  canceled: 'bg-slate-200 text-slate-500',
};

function CapacityEditor({ campaign, onSaved }: { campaign: Campaign; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(campaign.daily_capacity_minutes));
  const [busy, setBusy] = useState(false);

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
      >
        <Clock className="h-4 w-4" />
        {campaign.daily_capacity_minutes}m/day
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5">
      <Clock className="h-4 w-4 text-blue-600" />
      <input
        type="number"
        min={30}
        max={720}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="w-16 rounded border border-blue-300 px-2 py-1 text-sm"
        autoFocus
      />
      <span className="text-xs text-blue-600">min/day</span>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await updateCampaign(campaign.id, { daily_capacity_minutes: Number(value) });
            onSaved();
            setEditing(false);
          } catch (err) {
            console.error('Action failed:', err);
          }
          setBusy(false);
        }}
        className="rounded bg-blue-700 px-2 py-1 text-[10px] font-medium text-white hover:bg-blue-800 disabled:opacity-50"
      >
        Save
      </button>
      <button
        type="button"
        onClick={() => {
          setEditing(false);
          setValue(String(campaign.daily_capacity_minutes));
        }}
        className="text-[10px] text-blue-600 hover:text-blue-800"
      >
        Cancel
      </button>
    </span>
  );
}

export default function SearchPlanView() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [activeCampaign, setActiveCampaign] = useState<Campaign | null>(null);
  const [tasks, setTasks] = useState<CampaignTask[]>([]);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterPriority, setFilterPriority] = useState('');
  const [selectedWeek, setSelectedWeek] = useState(0);
  const [viewMode, setViewMode] = useState<'week' | 'calendar'>('week');
  const [showAddForm, setShowAddForm] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newCategory, setNewCategory] = useState('other');
  const [newPriority, setNewPriority] = useState('P1');
  const [newDue, setNewDue] = useState('');
  const [newMinutes, setNewMinutes] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  // Seed import
  const [seedPreview, setSeedPreview] = useState<SeedPreview | null>(null);
  const [seedResult, setSeedResult] = useState<SeedResult | null>(null);
  const [seedData, setSeedData] = useState<unknown>(null);

  async function load() {
    try {
      const camps = await readCampaigns();
      setCampaigns(camps);
      const active = camps.find((c) => c.is_active) ?? camps[0] ?? null;
      setActiveCampaign(active);
      if (active) {
        const params: Record<string, string> = {};
        if (filterStatus) params.status = filterStatus;
        if (filterCategory) params.category = filterCategory;
        if (filterPriority) params.priority = filterPriority;
        setTasks(await readTasks(active.id, Object.keys(params).length ? params : undefined));
      }
      setError('');
    } catch (err) {
      console.error('Action failed:', err);
      setError('Could not load campaign data.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [filterStatus, filterCategory, filterPriority]);

  async function handleAddTask() {
    if (!activeCampaign || !newTitle.trim()) return;
    setBusy(true);
    try {
      await createTask(activeCampaign.id, {
        title: newTitle.trim(),
        category: newCategory,
        priority: newPriority,
        due_date: newDue || null,
        estimated_minutes: newMinutes ? Number(newMinutes) : null,
      });
      setNewTitle('');
      setNewDue('');
      setNewMinutes('');
      setShowAddForm(false);
      await load();
      setMessage('Task created.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleStatusChange(taskId: string, status: string) {
    if (!activeCampaign) return;
    try {
      await updateTask(activeCampaign.id, taskId, { status });
      await load();
    } catch (err) {
      console.error('Action failed:', err);
    }
  }

  async function handleSeedFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      setSeedData(data);
      setSeedPreview(await previewSeed(data));
      setSeedResult(null);
    } catch (err) {
      console.error('Action failed:', err);
      setError(err instanceof Error ? err.message : 'Invalid JSON.');
    }
  }

  async function handleApplySeed() {
    if (!seedData) return;
    setBusy(true);
    try {
      const result = await applySeed(seedData);
      setSeedResult(result);
      setSeedPreview(null);
      setSeedData(null);
      await load();
      setMessage(
        `Imported: ${result.tasks_created} new, ${result.tasks_updated} updated, ${result.tasks_skipped} skipped.`,
      );
    } catch (err) {
      console.error('Action failed:', err);
      setError(err instanceof Error ? err.message : 'Import failed.');
    } finally {
      setBusy(false);
    }
  }

  // Group tasks by week
  const weekGroups: { weekStart: string; weekEnd: string; tasks: CampaignTask[] }[] = [];
  if (activeCampaign) {
    const start = new Date(activeCampaign.start_date + 'T00:00:00');
    const end = new Date(activeCampaign.end_date + 'T00:00:00');
    let current = new Date(start);
    while (current <= end) {
      const weekEnd = new Date(current);
      weekEnd.setDate(weekEnd.getDate() + 6);
      const ws = localDate(current);
      const we = localDate(weekEnd > end ? end : weekEnd);
      const weekTasks = tasks.filter((t) => t.due_date && t.due_date >= ws && t.due_date <= we);
      weekGroups.push({ weekStart: ws, weekEnd: we, tasks: weekTasks });
      current.setDate(current.getDate() + 7);
    }
  }
  const noDateTasks = tasks.filter((t) => !t.due_date);
  const currentWeek = weekGroups[selectedWeek];

  // Group week tasks by day
  const dayGroups: { date: string; dayName: string; tasks: CampaignTask[] }[] = [];
  if (currentWeek) {
    const ws = new Date(currentWeek.weekStart + 'T00:00:00');
    const we = new Date(currentWeek.weekEnd + 'T00:00:00');
    let d = new Date(ws);
    while (d <= we) {
      const ds = localDate(d);
      const dayTasks = currentWeek.tasks.filter((t) => t.due_date === ds);
      const dayName = d.toLocaleDateString(undefined, {
        weekday: 'long',
        month: 'short',
        day: 'numeric',
      });
      if (dayTasks.length > 0) dayGroups.push({ date: ds, dayName, tasks: dayTasks });
      d.setDate(d.getDate() + 1);
    }
  }

  return (
    <div>
      {error && <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && (
        <div className="mb-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{message}</div>
      )}

      {/* Toolbar */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
          <Upload className="h-4 w-4" /> Import Seed JSON
          <input
            type="file"
            accept=".json"
            onChange={(e) => void handleSeedFile(e)}
            className="hidden"
          />
        </label>
        {showAddForm ? null : (
          <button
            type="button"
            onClick={() => setShowAddForm(true)}
            className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            <Plus className="h-4 w-4" /> Add Task
          </button>
        )}
        {activeCampaign && <CapacityEditor campaign={activeCampaign} onSaved={() => void load()} />}
      </div>

      {/* Seed preview */}
      {seedPreview && (
        <div className="mb-6 rounded-xl border border-blue-200 bg-blue-50 p-5">
          <h3 className="text-sm font-semibold text-blue-800">Seed Import Preview</h3>
          <div className="mt-2 text-sm text-blue-700">
            <p>
              Campaign: {seedPreview.campaign.key} ({seedPreview.campaign.action})
            </p>
            <p>
              Tasks: {seedPreview.tasks.new} new, {seedPreview.tasks.updated} to update,{' '}
              {seedPreview.tasks.skipped} skipped
            </p>
            <p>Evidence: {seedPreview.evidence.count} items</p>
            <p>Content: {seedPreview.content.count} items</p>
            {seedPreview.contacts && <p>Contacts: {seedPreview.contacts.count} entries</p>}
          </div>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleApplySeed()}
              className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
            >
              {busy ? 'Importing…' : 'Apply Import'}
            </button>
            <button
              type="button"
              onClick={() => {
                setSeedPreview(null);
                setSeedData(null);
              }}
              className="rounded-lg border border-blue-300 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Add task form */}
      {showAddForm && (
        <div className="mb-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-slate-900">New Task</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block text-xs sm:col-span-3">
              <span className="font-medium text-slate-600">Title</span>
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Category</span>
              <select
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Priority</span>
              <select
                value={newPriority}
                onChange={(e) => setNewPriority(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Due date</span>
              <input
                type="date"
                value={newDue}
                onChange={(e) => setNewDue(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Estimated minutes</span>
              <input
                type="number"
                min="1"
                max="480"
                value={newMinutes}
                onChange={(e) => setNewMinutes(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              disabled={busy || !newTitle.trim()}
              onClick={() => void handleAddTask()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Create
            </button>
            <button
              type="button"
              onClick={() => setShowAddForm(false)}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {loading && <p className="text-sm text-slate-500">Loading…</p>}

      {!loading && !activeCampaign && (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
          <p className="text-sm text-slate-500">
            No campaign yet. Import a seed JSON to get started.
          </p>
        </div>
      )}

      {activeCampaign && (
        <>
          {/* View mode tabs */}
          <div className="mb-4 flex items-center gap-2">
            {(
              [
                ['week', List, 'Tasks'],
                ['calendar', CalendarDays, 'Calendar'],
              ] as const
            ).map(([mode, Icon, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium ${viewMode === mode ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
              >
                <Icon className="h-4 w-4" /> {label}
              </button>
            ))}
          </div>

          {/* Workload Projection */}
          {(viewMode === 'week' || viewMode === 'calendar') && (
            <WorkloadProjection tasks={tasks} campaign={activeCampaign} />
          )}

          {/* Calendar View */}
          {viewMode === 'calendar' && (
            <CalendarView
              tasks={tasks}
              campaign={activeCampaign}
              onStatusChange={handleStatusChange}
              onReload={() => void load()}
            />
          )}

          {/* Task List View */}
          {viewMode === 'week' && (
            <>
              {/* Filters */}
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <select
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">All statuses</option>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <select
                  value={filterCategory}
                  onChange={(e) => setFilterCategory(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">All categories</option>
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <select
                  value={filterPriority}
                  onChange={(e) => setFilterPriority(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">All priorities</option>
                  {PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-slate-500">{tasks.length} tasks</span>
              </div>

              {/* Week tabs */}
              <div className="mb-4 flex flex-wrap gap-2">
                {weekGroups.map((w, i) => (
                  <button
                    key={w.weekStart}
                    type="button"
                    onClick={() => setSelectedWeek(i)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium ${selectedWeek === i ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
                  >
                    Week {i + 1} ({w.tasks.length})
                  </button>
                ))}
              </div>

              {/* Day groups */}
              {dayGroups.map(({ date, dayName, tasks: dayTasks }) => (
                <div key={date} className="mb-6">
                  <h3 className="mb-2 text-sm font-semibold text-slate-700">{dayName}</h3>
                  <div className="space-y-2">
                    {dayTasks.map((t) => (
                      <SearchPlanTaskCard
                        key={t.id}
                        task={t}
                        campaignId={activeCampaign.id}
                        onReload={() => void load()}
                      />
                    ))}
                  </div>
                </div>
              ))}
              {currentWeek && !dayGroups.length && (
                <p className="text-sm text-slate-500">
                  No tasks scheduled for this week
                  {filterStatus || filterCategory || filterPriority ? ' with current filters' : ''}.
                </p>
              )}

              {/* No-date tasks */}
              {noDateTasks.length > 0 && (
                <div className="mt-6">
                  <h3 className="mb-2 text-sm font-semibold text-slate-700">
                    Unscheduled ({noDateTasks.length})
                  </h3>
                  <div className="space-y-2">
                    {noDateTasks.slice(0, 10).map((t) => (
                      <SearchPlanTaskCard
                        key={t.id}
                        task={t}
                        campaignId={activeCampaign.id}
                        onReload={() => void load()}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

/* ---------- Search Plan Task Card ---------- */

function SearchPlanTaskCard({
  task,
  campaignId,
  onReload,
}: {
  task: CampaignTask;
  campaignId: string;
  onReload: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState(task.status);
  const [dueDate, setDueDate] = useState(task.due_date ?? '');
  const [notes, setNotes] = useState(task.notes);
  const [priority, setPriority] = useState(task.priority);
  const [busy, setBusy] = useState(false);
  const today = new Date().toLocaleDateString('sv-SE');
  const isDueToday = task.due_date === today;
  const isOd = overdue(task);

  async function save() {
    setBusy(true);
    try {
      await updateTask(campaignId, task.id, { status, notes, priority, due_date: dueDate || null });
      onReload();
    } catch (err) {
      console.error('Action failed:', err);
    }
    setBusy(false);
  }

  async function quickStatus(next: string) {
    setBusy(true);
    try {
      await updateTask(campaignId, task.id, { status: next });
      onReload();
    } catch (err) {
      console.error('Action failed:', err);
    }
    setBusy(false);
  }

  return (
    <div
      className={`rounded-xl border shadow-sm ${isDueToday ? 'border-amber-300 bg-amber-50/30' : isOd ? 'border-red-300 bg-red-50/30' : task.status === 'completed' ? 'border-emerald-200 bg-emerald-50/30' : 'border-slate-200 bg-white'}`}
    >
      <div className="flex items-start gap-3 p-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            const next =
              task.status === 'planned'
                ? 'in_progress'
                : task.status === 'in_progress'
                  ? 'completed'
                  : task.status;
            void quickStatus(next);
          }}
          className="mt-0.5 shrink-0"
        >
          <CheckCircle
            className={`h-5 w-5 ${task.status === 'completed' ? 'text-emerald-500' : task.status === 'in_progress' ? 'text-blue-500' : 'text-slate-300 hover:text-slate-500'}`}
          />
        </button>
        <div className="min-w-0 flex-1">
          <p
            className={`text-sm font-medium ${task.status === 'completed' ? 'text-slate-400 line-through' : 'text-slate-900'}`}
          >
            {task.title}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[task.status] ?? ''}`}
            >
              {task.status}
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
            {isDueToday && (
              <span className="rounded bg-amber-200 px-1.5 py-0.5 text-[10px] font-bold text-amber-800">
                DUE TODAY
              </span>
            )}
            {isOd && (
              <span className="rounded bg-red-200 px-1.5 py-0.5 text-[10px] font-bold text-red-800">
                OVERDUE
              </span>
            )}
          </div>
          {!expanded && task.completion_criteria && (
            <p className="mt-1 text-xs text-slate-400">
              {task.completion_criteria.slice(0, 120)}
              {task.completion_criteria.length > 120 ? '…' : ''}
            </p>
          )}
          {!expanded && task.communication && (
            <p className="mt-1 text-xs text-blue-700">
              Message from {task.communication.sender || 'an unknown sender'}. Edit to read it in
              full.
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!expanded && task.status !== 'completed' && task.status !== 'canceled' && (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void quickStatus(task.status === 'planned' ? 'in_progress' : 'completed')
              }
              className="rounded-md bg-slate-900 px-2.5 py-1 text-[10px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {task.status === 'planned'
                ? 'Start'
                : task.status === 'in_progress'
                  ? 'Complete'
                  : 'Update'}
            </button>
          )}
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="rounded-md border border-slate-300 px-2.5 py-1 text-[10px] font-medium text-slate-700 hover:bg-slate-50"
          >
            {expanded ? 'Close' : 'Edit'}
          </button>
        </div>
      </div>
      {expanded && (
        <div className="border-t border-slate-100 px-3 pb-3 pt-2">
          {task.communication && (
            <div className="mb-3">
              <MessageCard
                message={task.communication}
                heading="Message to answer"
                reply={{
                  taskId: task.id,
                  sentLabel: 'Log as sent and complete task',
                  onDone: (status) => {
                    if (status === 'sent') void quickStatus('completed');
                  },
                }}
              />
            </div>
          )}
          {task.completion_criteria && (
            <div className="mb-3">
              <p className="text-xs font-medium text-slate-600">What to do</p>
              <p className="mt-1 text-sm text-slate-700">{task.completion_criteria}</p>
            </div>
          )}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Status</span>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Due date</span>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Priority</span>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
              >
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="mt-2 block text-xs">
            <span className="font-medium text-slate-600">Notes</span>
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Progress, decisions, links…"
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
          {task.depends_on.length > 0 && (
            <p className="mt-1 text-[10px] text-slate-500">
              Depends on: {task.depends_on.join(', ')}
            </p>
          )}
          {task.suggested_after.length > 0 && (
            <p className="mt-0.5 text-[10px] text-slate-500">
              Suggested after: {task.suggested_after.join(', ')}
            </p>
          )}
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void save()}
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

/* ---------- Workload Projection ---------- */

function WorkloadProjection({ tasks, campaign }: { tasks: CampaignTask[]; campaign: Campaign }) {
  const today = new Date().toLocaleDateString('sv-SE');
  const capacity = campaign.daily_capacity_minutes;

  // Build daily totals for the next 21 days
  const days: {
    date: string;
    label: string;
    minutes: number;
    count: number;
    isWeekend: boolean;
    isToday: boolean;
    overCapacity: boolean;
  }[] = [];
  const start = new Date(today + 'T00:00:00');
  for (let i = 0; i < 21; i++) {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    const ds = localDate(d);
    const dow = d.getDay();
    const isWeekend = dow === 0 || dow === 6;
    const dayTasks = tasks.filter(
      (t) => t.due_date === ds && t.status !== 'completed' && t.status !== 'canceled',
    );
    const minutes = dayTasks.reduce((sum, t) => sum + (t.estimated_minutes || 0), 0);
    days.push({
      date: ds,
      label: d.toLocaleDateString(undefined, {
        weekday: 'short',
        month: 'numeric',
        day: 'numeric',
      }),
      minutes,
      count: dayTasks.length,
      isWeekend,
      isToday: ds === today,
      overCapacity: minutes > capacity,
    });
  }

  const maxMinutes = Math.max(capacity, ...days.map((d) => d.minutes));

  // Summary
  const totalPlanned = tasks
    .filter((t) => t.status !== 'completed' && t.status !== 'canceled')
    .reduce((s, t) => s + (t.estimated_minutes || 0), 0);
  const totalTasks = tasks.filter(
    (t) => t.status !== 'completed' && t.status !== 'canceled',
  ).length;
  const overloadedDays = days.filter((d) => d.overCapacity && !d.isWeekend).length;

  return (
    <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">Workload Projection (next 3 weeks)</h3>
        <div className="flex gap-4 text-xs text-slate-500">
          <span>
            {totalTasks} tasks · {Math.round(totalPlanned / 60)}h total
          </span>
          <span>{capacity}m/day capacity</span>
          {overloadedDays > 0 && (
            <span className="font-semibold text-red-600">{overloadedDays} overloaded days</span>
          )}
        </div>
      </div>
      <div className="mt-3 flex items-end gap-px" style={{ height: '5rem' }}>
        {days.map((d) => {
          const heightPct = maxMinutes > 0 ? (d.minutes / maxMinutes) * 100 : 0;
          const capacityPct = maxMinutes > 0 ? (capacity / maxMinutes) * 100 : 100;
          return (
            <div key={d.date} className="group relative flex-1" style={{ height: '100%' }}>
              {/* Capacity line */}
              <div
                className="absolute left-0 right-0 border-t border-dashed border-slate-300"
                style={{ bottom: `${capacityPct}%` }}
              />
              {/* Bar */}
              <div
                className={`absolute bottom-0 left-0 right-0 rounded-t-sm transition-all ${
                  d.isWeekend
                    ? 'bg-slate-200'
                    : d.overCapacity
                      ? 'bg-red-400'
                      : d.isToday
                        ? 'bg-blue-500'
                        : d.minutes > 0
                          ? 'bg-emerald-400'
                          : 'bg-slate-100'
                }`}
                style={{ height: `${Math.max(heightPct, d.minutes > 0 ? 3 : 0)}%` }}
              />
              {/* Tooltip */}
              <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 rounded bg-slate-800 px-2 py-1 text-[10px] text-white whitespace-nowrap group-hover:block">
                {d.label}: {d.count} tasks, {d.minutes}m{d.overCapacity && ' ⚠ over capacity'}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex gap-px text-[8px] text-slate-400">
        {days.map((d, i) => (
          <div
            key={d.date}
            className={`flex-1 text-center ${d.isToday ? 'font-bold text-blue-600' : ''}`}
          >
            {i % 3 === 0 ? d.label.split(',')[0] : ''}
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-3 text-[10px] text-slate-500">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-emerald-400" /> Within capacity
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-red-400" /> Over capacity
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-blue-500" /> Today
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-slate-200" /> Weekend
        </span>
        <span className="flex items-center gap-1 border-t border-dashed border-slate-400 px-1">
          {capacity}m cap
        </span>
      </div>
    </div>
  );
}

/* ---------- Calendar View ---------- */

const PRIORITY_DOT: Record<string, string> = {
  P0: 'bg-red-500',
  P1: 'bg-orange-400',
  P2: 'bg-blue-400',
  P3: 'bg-slate-300',
};

function CalendarView({
  tasks,
  campaign,
  onStatusChange,
  onReload,
}: {
  tasks: CampaignTask[];
  campaign: Campaign;
  onStatusChange: (id: string, status: string) => void;
  onReload: () => void;
}) {
  const [monthOffset, setMonthOffset] = useState(0);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const baseDate = new Date(campaign.start_date + 'T00:00:00');
  const viewDate = new Date(baseDate);
  viewDate.setMonth(viewDate.getMonth() + monthOffset);
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const monthName = viewDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

  // Build calendar grid
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  // Index tasks by date
  const tasksByDate: Record<string, CampaignTask[]> = {};
  for (const t of tasks) {
    if (t.due_date) {
      tasksByDate[t.due_date] = tasksByDate[t.due_date] || [];
      tasksByDate[t.due_date].push(t);
    }
  }

  const today = new Date().toLocaleDateString('sv-SE');

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setMonthOffset((m) => m - 1)}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          ← Prev
        </button>
        <h3 className="text-base font-semibold text-slate-900">{monthName}</h3>
        <button
          type="button"
          onClick={() => setMonthOffset((m) => m + 1)}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Next →
        </button>
      </div>
      <div className="grid grid-cols-7 gap-px rounded-xl border border-slate-200 bg-slate-200 overflow-hidden">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
          <div
            key={d}
            className="bg-slate-100 px-2 py-1.5 text-center text-xs font-semibold text-slate-500"
          >
            {d}
          </div>
        ))}
        {cells.map((day, i) => {
          if (day === null) return <div key={`empty-${i}`} className="min-h-[5rem] bg-slate-50" />;
          const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          const dayTasks = tasksByDate[dateStr] || [];
          const isToday = dateStr === today;
          const isWeekend = new Date(year, month, day).getDay() % 6 === 0;
          return (
            <button
              key={day}
              type="button"
              onClick={() => setSelectedDate(selectedDate === dateStr ? null : dateStr)}
              className={`min-h-[5rem] p-1.5 text-left ${selectedDate === dateStr ? 'ring-2 ring-blue-500' : ''} ${isToday ? 'bg-blue-50' : isWeekend ? 'bg-slate-50' : 'bg-white'}`}
            >
              <p className={`text-xs font-medium ${isToday ? 'text-blue-700' : 'text-slate-500'}`}>
                {day}
              </p>
              <div className="mt-1 space-y-0.5">
                {dayTasks.slice(0, 4).map((t) => (
                  <div
                    key={t.id}
                    className={`flex items-center gap-1 rounded px-1 py-0.5 text-[10px] leading-tight ${t.status === 'completed' ? 'text-slate-400 line-through' : 'text-slate-800'}`}
                  >
                    <span
                      className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${PRIORITY_DOT[t.priority] ?? 'bg-slate-300'}`}
                    />
                    <span className="truncate">
                      {t.title.length > 30 ? t.title.slice(0, 30) + '…' : t.title}
                    </span>
                  </div>
                ))}
                {dayTasks.length > 4 && (
                  <p className="text-[9px] text-slate-400">+{dayTasks.length - 4} more</p>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Selected day detail */}
      {selectedDate && (tasksByDate[selectedDate] || []).length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">
            {new Date(selectedDate + 'T00:00:00').toLocaleDateString(undefined, {
              weekday: 'long',
              month: 'long',
              day: 'numeric',
            })}
          </h3>
          <div className="space-y-2">
            {(tasksByDate[selectedDate] || []).map((t) => (
              <SearchPlanTaskCard
                key={t.id}
                task={t}
                campaignId={campaign.id}
                onReload={onReload}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function overdue(t: CampaignTask): boolean {
  if (!t.due_date || t.status === 'completed' || t.status === 'canceled') return false;
  return t.due_date < new Date().toLocaleDateString('sv-SE');
}
