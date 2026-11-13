import { useEffect, useState } from 'react';
import {
  Send,
  CalendarClock,
  Mail,
  Eye,
  CheckSquare,
  RefreshCw,
  Building2,
  ArrowRight,
} from 'lucide-react';
import type { ComponentType } from 'react';
import { request, readJobs, type Job } from '../jobs-api';
import {
  type Workspace,
  type Pursuit,
  type Stage,
  type WeeklySummary,
  closedStages,
  readWorkspace,
  readWeeklySummary,
  buildPlan,
  advanceStage,
  recordContact,
  announce,
} from './career-api';

interface InboxPage {
  items: {
    id: string;
    search_name: string;
    job: Job;
    created_at: string;
    read_at: string | null;
  }[];
  total: number;
  unread: number;
}

type IconComponent = ComponentType<{ className?: string }>;

function Card({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {children}
    </div>
  );
}

function StatCard({
  title,
  value,
  sub,
  icon: Icon,
  badge,
  badgeClass,
}: {
  title: string;
  value: number | string;
  sub: string | null;
  icon: IconComponent;
  badge: string;
  badgeClass: string;
}) {
  return (
    <Card className="relative p-5">
      <span
        className={`absolute right-4 top-4 rounded-full px-2 py-0.5 text-xs font-semibold ${badgeClass}`}
      >
        {badge}
      </span>
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">
        <Icon className="h-5 w-5 text-slate-700" />
      </div>
      <p className="mt-4 text-sm font-medium text-slate-500">{title}</p>
      <p className="mt-1 text-3xl font-bold tracking-tight text-slate-900">{value}</p>
      <p className="mt-1 h-5 text-sm text-slate-500">{sub}</p>
    </Card>
  );
}

const KANBAN_COLUMNS: { title: string; dot: string; stages: Stage[] }[] = [
  { title: 'Preparing', dot: 'bg-slate-400', stages: ['review', 'preparing'] },
  { title: 'Applied', dot: 'bg-blue-400', stages: ['applied'] },
  { title: 'Interviewing', dot: 'bg-orange-400', stages: ['interview'] },
  { title: 'Offers', dot: 'bg-emerald-500', stages: ['offer'] },
];

export default function DashboardView({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [alerts, setAlerts] = useState<InboxPage | null>(null);
  const [topJobs, setTopJobs] = useState<Job[]>([]);
  const [weekly, setWeekly] = useState<WeeklySummary | null>(null);
  const [activity, setActivity] = useState<
    { id: string; message: string; created_at: string; job_title: string; job_company: string }[]
  >([]);
  const [error, setError] = useState('');
  const [buildBusy, setBuildBusy] = useState(false);
  const [buildMsg, setBuildMsg] = useState('');
  const [advanceBusy, setAdvanceBusy] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [ws, inbox, jobs, wk, act] = await Promise.all([
          readWorkspace(),
          request<InboxPage>('alerts?unread_only=true&offset=0&limit=5'),
          readJobs('all', 0, false, {
            q: '',
            company: '',
            location: '',
            exclude: '',
            work_mode: 'any',
            min_score: '50',
            max_age_days: '',
            sort: 'score',
            discovery_only: false,
          }),
          readWeeklySummary(),
          request<typeof activity>('career/activity'),
        ]);
        if (active) {
          setWorkspace(ws);
          setAlerts(inbox);
          setTopJobs(jobs.items.slice(0, 3));
          setWeekly(wk);
          setActivity(act);
          setError('');
        }
      } catch (err) {
        console.error('Action failed:', err);
        if (active) setError('Dashboard data unavailable. Check the local API.');
      }
      if (active) timer = setTimeout(poll, 15000);
    }
    void poll();
    const changed = () => void readWorkspace().then((ws) => active && setWorkspace(ws));
    window.addEventListener('nextup:pursuits', changed);
    return () => {
      active = false;
      clearTimeout(timer);
      window.removeEventListener('nextup:pursuits', changed);
    };
  }, []);

  async function handleBuild() {
    setBuildBusy(true);
    setBuildMsg('');
    try {
      const result = await buildPlan();
      announce();
      setBuildMsg(
        result.status === 'not_configured'
          ? 'Save your goals first.'
          : result.status === 'profile_required'
            ? 'Save your profile and discovery settings first.'
            : `${result.added} new opportunities added.`,
      );
    } catch (e) {
      console.error('Action failed:', e);
      setBuildMsg(e instanceof Error ? e.message : 'Could not build plan.');
    } finally {
      setBuildBusy(false);
    }
  }

  async function handleAdvance(item: Pursuit) {
    setAdvanceBusy(item.id);
    try {
      await advanceStage(item);
      announce();
      const ws = await readWorkspace();
      setWorkspace(ws);
    } catch (err) {
      console.error('Action failed:', err);
      /* silent — workspace will refresh on poll */
    } finally {
      setAdvanceBusy(null);
    }
  }

  const ADVANCE_LABELS: Partial<Record<Stage, string>> = {
    review: 'Start Preparing',
    preparing: 'Mark Applied',
    applied: 'Mark Interviewing',
    interview: 'Mark Offer',
  };

  const totalApplied = workspace
    ? workspace.counts.applied +
      workspace.counts.interview +
      workspace.counts.offer +
      workspace.counts.accepted
    : 0;
  const interviewing = workspace?.counts.interview ?? 0;
  const unread = alerts?.unread ?? 0;
  const preparing = workspace ? workspace.counts.review + workspace.counts.preparing : 0;

  const stats = [
    {
      title: 'Total Applied',
      value: totalApplied,
      sub: workspace ? `${preparing} preparing` : null,
      icon: Send as IconComponent,
      badge: String(totalApplied),
      badgeClass: 'bg-orange-100 text-orange-700',
    },
    {
      title: 'Interviewing',
      value: interviewing,
      sub: workspace?.plan.find((p) => p.stage === 'interview') ? 'action due today' : null,
      icon: CalendarClock as IconComponent,
      badge: String(interviewing),
      badgeClass: 'bg-orange-100 text-orange-700',
    },
    {
      title: 'Unread Alerts',
      value: unread,
      sub: null,
      icon: Mail as IconComponent,
      badge: String(unread),
      badgeClass: unread > 0 ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-600',
    },
    {
      title: 'Offers',
      value: workspace?.counts.offer ?? 0,
      sub: workspace?.counts.accepted ? `${workspace.counts.accepted} accepted` : null,
      icon: Eye as IconComponent,
      badge: String(workspace?.counts.offer ?? 0),
      badgeClass: 'bg-emerald-100 text-emerald-700',
    },
  ];

  return (
    <>
      {error && <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {/* Stats */}
      <section className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((s) => (
          <StatCard key={s.title} {...s} />
        ))}
      </section>

      {/* Daily plan */}
      {workspace && workspace.plan.length > 0 && (
        <Card className="mt-6 p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900">Today&apos;s Plan</h2>
            <span className="text-xs text-slate-500">
              {workspace.today} · {workspace.preferences.timezone}
            </span>
          </div>
          <ul className="space-y-2">
            {[...workspace.plan]
              .sort((a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0))
              .map((item) => (
                <li key={item.id} className="flex items-center gap-3 rounded-lg bg-slate-50 p-3">
                  <CheckSquare className="h-4 w-4 shrink-0 text-slate-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-900">
                      {item.job.title} at {item.job.company}
                    </p>
                    <p className="text-xs text-slate-500">
                      {item.next_action} · Due {item.next_action_on}
                      {item.job.score != null && ` · Score ${item.job.score}`}
                      {item.priority_reason && ` · ${item.priority_reason}`}
                    </p>
                  </div>
                  {ADVANCE_LABELS[item.stage] && (
                    <button
                      type="button"
                      disabled={advanceBusy === item.id}
                      onClick={() => void handleAdvance(item)}
                      className="shrink-0 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                    >
                      {advanceBusy === item.id ? '…' : ADVANCE_LABELS[item.stage]}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onNavigate('applications')}
                    className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                  >
                    <ArrowRight className="h-4 w-4" />
                  </button>
                </li>
              ))}
          </ul>
        </Card>
      )}

      {/* Build plan button */}
      {workspace && !workspace.plan.length && (
        <Card className="mt-6 p-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Today&apos;s Plan</h2>
              <p className="mt-1 text-sm text-slate-500">
                No actions due today. Build a plan from discovered jobs.
              </p>
            </div>
            <button
              type="button"
              disabled={buildBusy || !workspace.ready}
              onClick={() => void handleBuild()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {buildBusy ? 'Building…' : 'Build plan'}
            </button>
          </div>
          {buildMsg && <p className="mt-2 text-sm text-slate-600">{buildMsg}</p>}
        </Card>
      )}

      {/* Offer Comparison */}
      {workspace &&
        (() => {
          const offers = workspace.items.filter((p) => p.stage === 'offer');
          if (offers.length < 1) return null;
          return (
            <Card className="mt-6 p-5">
              <h2 className="mb-3 text-base font-semibold text-slate-900">
                {offers.length === 1 ? 'Active Offer' : `Compare ${offers.length} Offers`}
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                      <th className="pb-2 pr-4">Company</th>
                      <th className="pb-2 pr-4">Role</th>
                      <th className="pb-2 pr-4">Base Salary</th>
                      <th className="pb-2 pr-4">Equity</th>
                      <th className="pb-2 pr-4">Bonus</th>
                      <th className="pb-2 pr-4">Deadline</th>
                      <th className="pb-2">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {offers.map((o) => {
                      const d = o.offer_data ?? {};
                      return (
                        <tr key={o.id} className="border-b border-slate-100">
                          <td className="py-2 pr-4 font-medium text-slate-900">{o.job.company}</td>
                          <td className="py-2 pr-4 text-slate-700">{o.job.title}</td>
                          <td className="py-2 pr-4 text-slate-700">{d.base_salary || '—'}</td>
                          <td className="py-2 pr-4 text-slate-700">{d.equity || '—'}</td>
                          <td className="py-2 pr-4 text-slate-700">{d.signing_bonus || '—'}</td>
                          <td className="py-2 pr-4 text-slate-700">{d.deadline || '—'}</td>
                          <td className="py-2 text-emerald-600 font-semibold">
                            {o.job.score ?? '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <button
                type="button"
                onClick={() => onNavigate('applications')}
                className="mt-3 text-xs font-medium text-slate-500 hover:text-slate-700"
              >
                Open in pipeline →
              </button>
            </Card>
          );
        })()}

      {/* Follow-up Reminders */}
      {workspace &&
        (() => {
          const followUps = workspace.plan.filter((p) => p.stage === 'applied' && p.due);
          if (!followUps.length) return null;
          return (
            <Card className="mt-6 p-5">
              <h2 className="mb-3 text-base font-semibold text-slate-900">Follow-ups Due</h2>
              <ul className="space-y-3">
                {followUps.map((item) => (
                  <li key={item.id} className="rounded-lg border border-slate-200 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-900">
                          {item.job.title} at {item.job.company}
                        </p>
                        <p className="text-xs text-slate-500">
                          Applied{' '}
                          {item.applied_at
                            ? new Date(item.applied_at).toLocaleDateString()
                            : 'recently'}{' '}
                          · Follow up due {item.next_action_on}
                        </p>
                      </div>
                    </div>
                    {item.follow_up_draft && (
                      <p className="mt-2 max-h-16 overflow-y-auto rounded bg-slate-50 p-2 text-xs text-slate-600 whitespace-pre-wrap">
                        {item.follow_up_draft.slice(0, 200)}
                        {item.follow_up_draft.length > 200 ? '…' : ''}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item.follow_up_draft && (
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(item.follow_up_draft);
                            } catch (err) {
                              console.error('Action failed:', err);
                            }
                          }}
                          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                        >
                          Copy Follow-up
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await recordContact(item.id, item.version, 'Sent follow-up message');
                            announce();
                            const ws = await readWorkspace();
                            setWorkspace(ws);
                          } catch (err) {
                            console.error('Action failed:', err);
                          }
                        }}
                        className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      >
                        I Followed Up
                      </button>
                      <button
                        type="button"
                        onClick={() => onNavigate('applications')}
                        className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      >
                        Open Details
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          );
        })()}

      {/* Main 3-column area */}
      <section className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-4">
        {/* Kanban */}
        <div className="xl:col-span-2">
          <Card className="flex flex-col p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-slate-900">Application Pipeline</h2>
              <button
                type="button"
                onClick={() => onNavigate('applications')}
                className="text-xs font-medium text-slate-500 hover:text-slate-700"
              >
                View all →
              </button>
            </div>
            <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-4">
              {KANBAN_COLUMNS.map((col) => {
                const cards =
                  workspace?.items.filter(
                    (p) => col.stages.includes(p.stage) && !closedStages.has(p.stage),
                  ) ?? [];
                return (
                  <div key={col.title} className="flex flex-col rounded-lg bg-slate-50 p-2.5">
                    <div className="mb-2.5 flex items-center gap-2 px-1">
                      <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                      <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                        {col.title}
                      </span>
                      <span className="ml-auto text-xs text-slate-400">{cards.length}</span>
                    </div>
                    <div className="space-y-2.5">
                      {cards.slice(0, 4).map((p) => (
                        <div
                          key={p.id}
                          className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
                        >
                          <p className="text-sm font-semibold leading-snug text-slate-900">
                            {p.job.title}
                          </p>
                          <p className="text-sm text-slate-500">at {p.job.company}</p>
                          {p.stage === 'offer' && (
                            <span className="mt-2 inline-flex items-center rounded-full bg-emerald-500 px-2.5 py-1 text-xs font-semibold text-white">
                              Offer Received
                            </span>
                          )}
                          <div className="mt-3 flex items-center justify-between">
                            <span className="text-xs text-slate-500">
                              {p.next_action_on ? `Due ${p.next_action_on}` : p.stage}
                            </span>
                            <div className="flex items-center gap-1 text-slate-400">
                              <button
                                type="button"
                                aria-label="Open in pipeline"
                                onClick={() => onNavigate('applications')}
                                className="rounded p-1 hover:bg-slate-100 hover:text-slate-600"
                              >
                                <RefreshCw className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                      {cards.length > 4 && (
                        <p className="px-1 text-xs text-slate-400">+{cards.length - 4} more</p>
                      )}
                      {cards.length === 0 && (
                        <p className="px-1 py-2 text-xs text-slate-400">None yet</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>

        {/* Progress + Funnel + Stale */}
        <div className="xl:col-span-1">
          <div className="flex flex-col gap-6">
            {/* Funnel Analytics */}
            {workspace?.analytics && workspace.analytics.total > 0 && (
              <Card className="p-5">
                <h2 className="mb-3 text-base font-semibold text-slate-900">Funnel</h2>
                <div className="space-y-2">
                  {(
                    [
                      ['Tracked', workspace.analytics.total, 100, 'bg-slate-400'],
                      [
                        'Applied',
                        workspace.analytics.applied,
                        workspace.analytics.apply_rate,
                        'bg-blue-500',
                      ],
                      [
                        'Interviewing',
                        workspace.analytics.interviewing,
                        workspace.analytics.interview_rate,
                        'bg-orange-500',
                      ],
                      [
                        'Offers',
                        workspace.analytics.offers,
                        workspace.analytics.offer_rate,
                        'bg-emerald-500',
                      ],
                    ] as const
                  ).map(([label, count, rate, color]) => (
                    <div key={label}>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-600">{label}</span>
                        <span className="font-semibold text-slate-900">
                          {count} {rate < 100 ? `(${rate}%)` : ''}
                        </span>
                      </div>
                      <div className="mt-1 h-2 rounded-full bg-slate-100">
                        <div
                          className={`h-2 rounded-full ${color} transition-all`}
                          style={{ width: `${Math.max(rate, 2)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {/* Stale Items */}
            {workspace?.analytics && workspace.analytics.stale_items.length > 0 && (
              <Card className="p-5">
                <h2 className="mb-3 text-base font-semibold text-slate-900">Needs Attention</h2>
                <p className="text-xs text-slate-500">No activity for 7+ days</p>
                <ul className="mt-2 space-y-2">
                  {workspace.analytics.stale_items.slice(0, 5).map((item) => (
                    <li
                      key={item.id}
                      className="flex items-center justify-between rounded-lg bg-amber-50 p-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-slate-900">{item.title}</p>
                        <p className="text-xs text-slate-500">
                          {item.company} · {item.stage}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => onNavigate('applications')}
                        className="shrink-0 text-xs text-slate-500 hover:text-slate-700"
                      >
                        Open →
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            <Card className="p-5">
              <h2 className="mb-3 text-base font-semibold text-slate-900">Search Progress</h2>
              {workspace ? (
                <div className="space-y-3">
                  {(
                    [
                      ['Preparing', workspace.counts.review + workspace.counts.preparing],
                      ['Applied', workspace.counts.applied],
                      ['Interviewing', workspace.counts.interview],
                      ['Offers', workspace.counts.offer],
                      [
                        'Closed',
                        workspace.counts.accepted +
                          workspace.counts.rejected +
                          workspace.counts.withdrawn +
                          workspace.counts.dismissed,
                      ],
                    ] as const
                  ).map(([label, count]) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-sm text-slate-600">{label}</span>
                      <span className="text-sm font-semibold text-slate-900">{count}</span>
                    </div>
                  ))}
                  <div className="border-t border-slate-100 pt-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-slate-700">Total tracked</span>
                      <span className="text-sm font-bold text-slate-900">{workspace.total}</span>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-slate-500">Loading…</p>
              )}
            </Card>
            <Card className="p-5">
              <h2 className="mb-3 text-base font-semibold text-slate-900">Automation</h2>
              {workspace ? (
                <>
                  <p className="text-sm text-slate-600">
                    {workspace.preferences.automatic
                      ? 'Automatic planning is on'
                      : 'Automatic planning is paused'}
                  </p>
                  {workspace.automation.checked_at && (
                    <p className="mt-1 text-xs text-slate-500">
                      Last checked {new Date(workspace.automation.checked_at).toLocaleString()}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => onNavigate('applications')}
                    className="mt-4 w-full rounded-lg border border-slate-300 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Manage Pipeline
                  </button>
                </>
              ) : (
                <p className="text-sm text-slate-500">Loading…</p>
              )}
            </Card>

            {/* Weekly Summary */}
            {weekly && (
              <Card className="p-5">
                <h2 className="mb-3 text-base font-semibold text-slate-900">This Week</h2>
                <div className="space-y-2">
                  {(
                    [
                      ['Added to review', weekly.this_week.added, weekly.last_week.added],
                      ['Applied', weekly.this_week.applied, weekly.last_week.applied],
                      ['Interviews', weekly.this_week.interviews, weekly.last_week.interviews],
                      ['Offers', weekly.this_week.offers, weekly.last_week.offers],
                      ['Follow-ups sent', weekly.this_week.contacts, weekly.last_week.contacts],
                    ] as const
                  ).map(([label, current, previous]) => {
                    const diff = current - previous;
                    return (
                      <div key={label} className="flex items-center justify-between">
                        <span className="text-xs text-slate-600">{label}</span>
                        <span className="flex items-center gap-1.5">
                          <span className="text-sm font-semibold text-slate-900">{current}</span>
                          {diff !== 0 && (
                            <span
                              className={`text-xs font-medium ${diff > 0 ? 'text-emerald-600' : 'text-red-500'}`}
                            >
                              {diff > 0 ? '+' : ''}
                              {diff}
                            </span>
                          )}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-2 text-xs text-slate-500">vs previous 7 days</p>
              </Card>
            )}
          </div>
        </div>

        {/* Insights */}
        <div className="xl:col-span-1">
          <Card className="p-5">
            <h2 className="text-base font-semibold text-slate-900">Insights &amp; Actions</h2>

            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Recent Alerts
            </h3>
            {alerts && alerts.items.length > 0 ? (
              <ul className="mt-2 divide-y divide-slate-100">
                {alerts.items.slice(0, 3).map((a) => (
                  <li key={a.id}>
                    <button
                      type="button"
                      onClick={() => onNavigate('messages')}
                      className="-mx-2 flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left hover:bg-slate-50"
                    >
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700">
                        {a.job.score ?? '?'}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-slate-900">{a.job.title}</p>
                        <p className="truncate text-xs text-slate-500">
                          {a.job.company} · {a.search_name}
                        </p>
                      </div>
                      {!a.read_at && (
                        <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-xs font-semibold text-white">
                          new
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-slate-500">
                {alerts ? 'No unread alerts.' : 'Loading…'}
              </p>
            )}
            {unread > 3 && (
              <button
                type="button"
                onClick={() => onNavigate('messages')}
                className="mt-2 text-xs font-medium text-slate-500 hover:text-slate-700"
              >
                View all {unread} alerts →
              </button>
            )}

            <div className="my-4 border-t border-slate-100" />

            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Top Matches
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">Highest scored discovered jobs</p>
            {topJobs.length > 0 ? (
              <div className="mt-3 space-y-3">
                {topJobs.map((job) => (
                  <div
                    key={`${job.source}:${job.external_id}`}
                    className="rounded-lg border border-slate-200 p-3"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-900">
                        <Building2 className="h-4 w-4 text-white" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-900">{job.title}</p>
                        <p className="text-xs text-slate-500">{job.company}</p>
                      </div>
                    </div>
                    {job.score != null && (
                      <p className="mt-2 text-sm font-semibold text-emerald-600">
                        Match {job.score}%
                      </p>
                    )}
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => onNavigate('jobs')}
                        className="flex-1 rounded-md border border-slate-300 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        View
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-500">
                No scored jobs yet. Set up your profile and discovery.
              </p>
            )}
          </Card>

          {/* Activity Feed */}
          {activity.length > 0 && (
            <Card className="mt-6 p-5">
              <h2 className="mb-3 text-base font-semibold text-slate-900">Recent Activity</h2>
              <ul className="space-y-2">
                {activity.slice(0, 10).map((ev) => (
                  <li key={ev.id} className="flex gap-3 text-xs">
                    <span className="shrink-0 text-slate-400">
                      {new Date(ev.created_at).toLocaleDateString(undefined, {
                        month: 'short',
                        day: 'numeric',
                      })}
                    </span>
                    <div className="min-w-0">
                      <p className="text-slate-700">{ev.message}</p>
                      {ev.job_title && (
                        <p className="truncate text-slate-500">
                          {ev.job_title} · {ev.job_company}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </section>
    </>
  );
}
