import { useEffect, useState } from 'react';
import { localDate, safeHref } from './safe';
import {
  Plus,
  ArrowRight,
  PenLine,
  LayoutGrid,
  CalendarDays,
  CheckCircle2,
  Clock,
  AlertCircle,
  Circle,
} from 'lucide-react';
import {
  type ContentItem,
  readContent,
  createContent,
  updateContent,
  advanceContent,
} from './content-api';

const STATES = ['idea', 'outline', 'draft', 'approved', 'scheduled', 'published'] as const;
const STATE_COLORS: Record<string, string> = {
  idea: 'bg-slate-100 text-slate-600 border-slate-200',
  outline: 'bg-purple-50 text-purple-700 border-purple-200',
  draft: 'bg-blue-50 text-blue-700 border-blue-200',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  scheduled: 'bg-amber-50 text-amber-700 border-amber-200',
  published: 'bg-green-50 text-green-700 border-green-200',
};
const KIND_BADGE: Record<string, string> = {
  linkedin_post: 'bg-blue-100 text-blue-700',
  article: 'bg-purple-100 text-purple-700',
  comment: 'bg-slate-100 text-slate-700',
  other: 'bg-slate-100 text-slate-600',
};
const TASK_STATUS_ICON: Record<string, { icon: typeof CheckCircle2; color: string }> = {
  completed: { icon: CheckCircle2, color: 'text-emerald-500' },
  in_progress: { icon: Clock, color: 'text-blue-500' },
  blocked: { icon: AlertCircle, color: 'text-red-500' },
  waiting: { icon: Clock, color: 'text-amber-500' },
  planned: { icon: Circle, color: 'text-slate-400' },
  canceled: { icon: Circle, color: 'text-slate-300' },
};

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', weekday: 'short' });
}

function getWeekLabel(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00');
  const monday = new Date(d);
  monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const fmt = (dt: Date) => dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `Week of ${fmt(monday)} – ${fmt(sunday)}`;
}

function getWeekKey(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00');
  const monday = new Date(d);
  monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return localDate(monday);
}

function TaskStatusBadge({ status }: { status: string }) {
  const info = TASK_STATUS_ICON[status] ?? TASK_STATUS_ICON.planned;
  const Icon = info.icon;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[10px] ${info.color}`}
      title={`Task: ${status}`}
    >
      <Icon className="h-3 w-3" />
      <span className="hidden sm:inline">{status.replace('_', ' ')}</span>
    </span>
  );
}

function ContentCard({
  item,
  busy,
  onAdvance,
  onEdit,
  compact,
}: {
  item: ContentItem;
  busy: boolean;
  onAdvance: (id: string) => void;
  onEdit: (item: ContentItem) => void;
  compact?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border border-white/50 bg-white shadow-sm ${compact ? 'p-2' : 'p-3'}`}
    >
      <p className="text-xs font-medium text-slate-900">{item.topic}</p>
      {item.title && <p className="mt-0.5 text-xs text-slate-600">{item.title}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1">
        <span
          className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${KIND_BADGE[item.kind] ?? ''}`}
        >
          {item.kind.replace('_', ' ')}
        </span>
        {!compact && item.target_date && (
          <span className="rounded-full bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
            {formatDate(item.target_date)}
          </span>
        )}
        {item.series && (
          <span className="rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-600">
            {item.series}
          </span>
        )}
        {item.linked_task?.status && <TaskStatusBadge status={item.linked_task.status} />}
        {item.public_url && (
          <a
            href={safeHref(item.public_url)}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-blue-600 underline"
          >
            Live
          </a>
        )}
      </div>
      <div className="mt-2 flex gap-1">
        {item.state !== 'published' && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onAdvance(item.id)}
            className="rounded px-1.5 py-0.5 text-[10px] font-medium text-slate-600 hover:bg-slate-100"
            title="Advance"
          >
            <ArrowRight className="h-3 w-3" />
          </button>
        )}
        <button
          type="button"
          onClick={() => onEdit(item)}
          className="rounded px-1.5 py-0.5 text-[10px] font-medium text-slate-600 hover:bg-slate-100"
          title="Edit"
        >
          <PenLine className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

export default function ContentView() {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [filterKind, setFilterKind] = useState('');
  const [filterSeries, setFilterSeries] = useState('');
  const [viewMode, setViewMode] = useState<'kanban' | 'timeline'>('kanban');
  const [editing, setEditing] = useState<ContentItem | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  // Add form
  const [newTopic, setNewTopic] = useState('');
  const [newKind, setNewKind] = useState('linkedin_post');
  const [newBody, setNewBody] = useState('');
  const [newTargetDate, setNewTargetDate] = useState('');
  const [newSeries, setNewSeries] = useState('');

  const seriesOptions = [...new Set(items.map((i) => i.series).filter(Boolean))] as string[];

  async function load() {
    try {
      setItems(await readContent(filterKind || undefined, undefined, filterSeries || undefined));
      setError('');
    } catch {
      setError('Could not load content.');
    }
  }

  useEffect(() => {
    void load();
  }, [filterKind, filterSeries]);

  async function handleAdd() {
    setBusy(true);
    try {
      await createContent({
        topic: newTopic.trim(),
        kind: newKind,
        body: newBody,
        target_date: newTargetDate || null,
        series: newSeries || null,
      });
      setNewTopic('');
      setNewBody('');
      setNewTargetDate('');
      setNewSeries('');
      setShowAdd(false);
      await load();
      setMessage('Content created.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleAdvance(id: string) {
    setBusy(true);
    try {
      await advanceContent(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleSave(id: string, data: Record<string, unknown>) {
    setBusy(true);
    try {
      await updateContent(id, data);
      setEditing(null);
      await load();
      setMessage('Saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  // Group by state for kanban
  const grouped = STATES.map((state) => ({
    state,
    items: items.filter((i) => i.state === state),
  }));

  // Group by week for timeline
  const scheduled = items
    .filter((i) => i.target_date)
    .sort((a, b) => a.target_date!.localeCompare(b.target_date!));
  const unscheduled = items.filter((i) => !i.target_date);
  const weekGroups: { key: string; label: string; items: ContentItem[] }[] = [];
  for (const item of scheduled) {
    const key = getWeekKey(item.target_date!);
    const existing = weekGroups.find((g) => g.key === key);
    if (existing) {
      existing.items.push(item);
    } else {
      weekGroups.push({ key, label: getWeekLabel(item.target_date!), items: [item] });
    }
  }

  return (
    <div>
      {error && <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && (
        <div className="mb-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{message}</div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        {/* View toggle */}
        <div className="flex rounded-lg border border-slate-300 p-0.5">
          <button
            type="button"
            onClick={() => setViewMode('kanban')}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === 'kanban'
                ? 'bg-slate-900 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <LayoutGrid className="h-3.5 w-3.5" /> Board
          </button>
          <button
            type="button"
            onClick={() => setViewMode('timeline')}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              viewMode === 'timeline'
                ? 'bg-slate-900 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <CalendarDays className="h-3.5 w-3.5" /> Timeline
          </button>
        </div>

        <select
          value={filterKind}
          onChange={(e) => setFilterKind(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">All types</option>
          <option value="linkedin_post">LinkedIn Posts</option>
          <option value="article">Articles</option>
          <option value="comment">Comments</option>
        </select>

        {seriesOptions.length > 0 && (
          <select
            value={filterSeries}
            onChange={(e) => setFilterSeries(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">All series</option>
            {seriesOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}

        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          <Plus className="h-4 w-4" /> Add Content
        </button>
      </div>

      {showAdd && (
        <div className="mb-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs sm:col-span-2">
              <span className="font-medium text-slate-600">Topic</span>
              <input
                value={newTopic}
                onChange={(e) => setNewTopic(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Type</span>
              <select
                value={newKind}
                onChange={(e) => setNewKind(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="linkedin_post">LinkedIn Post</option>
                <option value="article">Article</option>
                <option value="comment">Comment</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Target Date</span>
              <input
                type="date"
                value={newTargetDate}
                onChange={(e) => setNewTargetDate(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Series</span>
              <input
                value={newSeries}
                onChange={(e) => setNewSeries(e.target.value)}
                placeholder="e.g. weekly-notes"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs sm:col-span-2">
              <span className="font-medium text-slate-600">Body / Draft</span>
              <textarea
                rows={4}
                value={newBody}
                onChange={(e) => setNewBody(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              disabled={busy || !newTopic.trim()}
              onClick={() => void handleAdd()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Create
            </button>
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Kanban board */}
      {viewMode === 'kanban' && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
          {grouped.map(({ state, items: stateItems }) => (
            <div
              key={state}
              className={`rounded-xl border p-3 ${STATE_COLORS[state] ?? 'bg-slate-50 border-slate-200'}`}
            >
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide">
                {state} ({stateItems.length})
              </h3>
              <div className="space-y-2">
                {stateItems.map((item) => (
                  <ContentCard
                    key={item.id}
                    item={item}
                    busy={busy}
                    onAdvance={handleAdvance}
                    onEdit={(i) => setEditing(editing?.id === i.id ? null : i)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Timeline view */}
      {viewMode === 'timeline' && (
        <div className="space-y-6">
          {weekGroups.map((group) => (
            <div key={group.key}>
              <h3 className="mb-3 text-sm font-semibold text-slate-700">{group.label}</h3>
              <div className="space-y-2">
                {group.items.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm"
                  >
                    {/* Date column */}
                    <div className="w-24 shrink-0 text-right">
                      <p className="text-xs font-semibold text-slate-900">
                        {formatDate(item.target_date!)}
                      </p>
                    </div>

                    {/* Content */}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-900">
                        {item.title || item.topic}
                      </p>
                      {item.title && item.topic !== item.title && (
                        <p className="mt-0.5 text-xs text-slate-500">{item.topic}</p>
                      )}
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${KIND_BADGE[item.kind] ?? ''}`}
                        >
                          {item.kind.replace('_', ' ')}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATE_COLORS[item.state] ?? ''}`}
                        >
                          {item.state}
                        </span>
                        {item.linked_task?.status && (
                          <TaskStatusBadge status={item.linked_task.status} />
                        )}
                        {item.public_url && (
                          <a
                            href={safeHref(item.public_url)}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[10px] text-blue-600 underline"
                          >
                            Live
                          </a>
                        )}
                      </div>
                      {item.notes && (
                        <p className="mt-1.5 text-xs text-slate-500 line-clamp-2">{item.notes}</p>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 gap-1">
                      {item.state !== 'published' && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleAdvance(item.id)}
                          className="rounded p-1.5 text-slate-500 hover:bg-slate-100"
                          title="Advance"
                        >
                          <ArrowRight className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setEditing(editing?.id === item.id ? null : item)}
                        className="rounded p-1.5 text-slate-500 hover:bg-slate-100"
                        title="Edit"
                      >
                        <PenLine className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {unscheduled.length > 0 && (
            <div>
              <h3 className="mb-3 text-sm font-semibold text-slate-400">Unscheduled</h3>
              <div className="space-y-2">
                {unscheduled.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-start gap-3 rounded-xl border border-dashed border-slate-200 bg-white p-3"
                  >
                    <div className="w-24 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-900">
                        {item.title || item.topic}
                      </p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${KIND_BADGE[item.kind] ?? ''}`}
                        >
                          {item.kind.replace('_', ' ')}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATE_COLORS[item.state] ?? ''}`}
                        >
                          {item.state}
                        </span>
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      {item.state !== 'published' && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleAdvance(item.id)}
                          className="rounded p-1.5 text-slate-500 hover:bg-slate-100"
                          title="Advance"
                        >
                          <ArrowRight className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setEditing(editing?.id === item.id ? null : item)}
                        className="rounded p-1.5 text-slate-500 hover:bg-slate-100"
                        title="Edit"
                      >
                        <PenLine className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {scheduled.length === 0 && unscheduled.length === 0 && (
            <p className="py-12 text-center text-sm text-slate-400">
              No content yet. Add some to get started.
            </p>
          )}
        </div>
      )}

      {/* Editor */}
      {editing && (
        <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">Edit: {editing.topic}</h3>
          <div className="mt-3 space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block text-xs sm:col-span-2">
                <span className="font-medium text-slate-600">Topic</span>
                <input
                  defaultValue={editing.topic}
                  id="edit-topic"
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Target Date</span>
                <input
                  type="date"
                  defaultValue={editing.target_date ?? ''}
                  id="edit-target-date"
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Series</span>
                <input
                  defaultValue={editing.series ?? ''}
                  id="edit-series"
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
            </div>

            {editing.linked_task?.title && (
              <div className="rounded-lg bg-slate-50 px-3 py-2">
                <p className="text-xs font-medium text-slate-600">Linked Task</p>
                <p className="mt-0.5 text-xs text-slate-700">
                  {editing.linked_task.title}
                  {editing.linked_task.status && (
                    <span className="ml-2">
                      <TaskStatusBadge status={editing.linked_task.status} />
                    </span>
                  )}
                </p>
              </div>
            )}

            {editing.outline && editing.outline.length > 0 && (
              <div>
                <p className="text-xs font-medium text-slate-600">Outline</p>
                <ol className="mt-1 list-inside list-decimal text-xs text-slate-600">
                  {editing.outline.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ol>
              </div>
            )}
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Body</span>
              <textarea
                rows={8}
                defaultValue={editing.body}
                id="edit-body"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            {editing.state === 'published' && (
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Public URL</span>
                <input
                  defaultValue={editing.public_url ?? ''}
                  id="edit-url"
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
            )}
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Notes</span>
              <textarea
                rows={2}
                defaultValue={editing.notes}
                id="edit-notes"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const topic = (document.getElementById('edit-topic') as HTMLInputElement).value;
                  const body = (document.getElementById('edit-body') as HTMLTextAreaElement).value;
                  const notes = (document.getElementById('edit-notes') as HTMLTextAreaElement)
                    .value;
                  const url = (document.getElementById('edit-url') as HTMLInputElement | null)
                    ?.value;
                  const targetDate = (
                    document.getElementById('edit-target-date') as HTMLInputElement
                  ).value;
                  const series = (document.getElementById('edit-series') as HTMLInputElement).value;
                  void handleSave(editing.id, {
                    topic,
                    body,
                    notes,
                    target_date: targetDate || null,
                    series: series || null,
                    ...(url !== undefined ? { public_url: url || null } : {}),
                  });
                }}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
