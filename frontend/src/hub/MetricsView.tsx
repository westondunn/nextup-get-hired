import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { request } from '../jobs-api';

interface WeeklyCohort {
  label: string;
  start: string;
  end: string;
  applications_submitted: number;
  reached_screen: number;
  screen_rate: number | null;
  outreach_threads: number;
  reply_events: number;
  reply_rate: number | null;
}

interface FunnelCounts {
  applied: number;
  replied: number;
  interviewed: number;
  offers: number;
  accepted: number;
}

interface Funnel {
  overall: FunnelCounts & { tracked: number };
  conversion: Record<string, number | null>;
  median_days: Record<string, number | null>;
  cohorts: (FunnelCounts & { label: string; start: string; end: string })[];
  notes: Record<string, unknown>;
}

const FUNNEL_STEPS: { key: keyof FunnelCounts; label: string }[] = [
  { key: 'applied', label: 'Applied' },
  { key: 'replied', label: 'Replied' },
  { key: 'interviewed', label: 'Interviewed' },
  { key: 'offers', label: 'Offers' },
  { key: 'accepted', label: 'Accepted' },
];
const CONVERSIONS: { key: string; label: string }[] = [
  { key: 'applied_to_replied', label: 'Applied → replied' },
  { key: 'replied_to_interviewed', label: 'Replied → interviewed' },
  { key: 'interviewed_to_offers', label: 'Interviewed → offers' },
  { key: 'applied_to_offers', label: 'Applied → offers' },
];
const DURATIONS: { key: string; label: string }[] = [
  { key: 'applied_to_reply', label: 'Applied to first reply' },
  { key: 'applied_to_interview', label: 'Applied to interview' },
  { key: 'interview_to_offer', label: 'Interview to offer' },
];

interface Metrics {
  weekly_cohorts: WeeklyCohort[];
  funnel: Funnel;
  median_stage_age_days: Record<string, number>;
  source_performance: Record<
    string,
    { tracked: number; applied: number; interviewing: number; offers: number }
  >;
  tasks: { completed: number; total: number };
  notes: Record<string, unknown>;
}

export default function MetricsView() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    request<Metrics>('career/metrics')
      .then((m) => active && setMetrics(m))
      .catch(() => active && setError('Metrics unavailable.'));
    return () => {
      active = false;
    };
  }, []);

  function handleExport() {
    window.open('/api/career/export', '_blank');
  }

  if (error) return <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>;
  if (!metrics) return <p className="text-sm text-slate-500">Loading metrics…</p>;

  return (
    <div className="space-y-8">
      {/* Export button */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleExport}
          className="flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <Download className="h-4 w-4" /> Export Activity CSV
        </button>
      </div>

      {/* Weekly cohorts */}
      <div>
        <h2 className="mb-3 text-lg font-bold text-slate-900">Weekly Cohorts</h2>
        <p className="mb-3 text-xs text-slate-500">
          Rates use same-cohort denominators. Recent and small cohorts may be inconclusive. Unknown
          values shown as "—".
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                <th className="pb-2 pr-4">Week</th>
                <th className="pb-2 pr-4">Applied</th>
                <th className="pb-2 pr-4">Screens</th>
                <th className="pb-2 pr-4">Screen %</th>
                <th className="pb-2 pr-4">Outreach</th>
                <th className="pb-2 pr-4">Replies</th>
                <th className="pb-2">Reply %</th>
              </tr>
            </thead>
            <tbody>
              {metrics.weekly_cohorts.map((w) => (
                <tr key={w.start} className="border-b border-slate-100">
                  <td className="py-2 pr-4 font-medium text-slate-900">{w.label}</td>
                  <td className="py-2 pr-4 text-slate-700">{w.applications_submitted}</td>
                  <td className="py-2 pr-4 text-slate-700">{w.reached_screen}</td>
                  <td className="py-2 pr-4 text-slate-700">
                    {w.screen_rate != null ? `${w.screen_rate}%` : '—'}
                  </td>
                  <td className="py-2 pr-4 text-slate-700">{w.outreach_threads}</td>
                  <td className="py-2 pr-4 text-slate-700">{w.reply_events}</td>
                  <td className="py-2 text-slate-700">
                    {w.reply_rate != null ? `${w.reply_rate}%` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Funnel */}
      <div>
        <h2 className="mb-3 text-lg font-bold text-slate-900">Funnel</h2>
        <p className="mb-3 text-xs text-slate-500">
          Applications to replies to interviews to offers, from recorded stages, timeline events and
          linked inbound mail. Unknown values shown as "—", never as zero.
        </p>
        <div className="space-y-2">
          {FUNNEL_STEPS.map((step) => {
            const value = metrics.funnel.overall[step.key];
            const base = metrics.funnel.overall.applied;
            return (
              <div key={step.key} className="flex items-center gap-3 text-sm">
                <span className="w-24 shrink-0 text-xs font-medium text-slate-500">
                  {step.label}
                </span>
                <div className="h-4 flex-1 rounded bg-slate-100">
                  <div
                    className="h-4 rounded bg-blue-500"
                    style={{ width: `${base ? (value / base) * 100 : 0}%` }}
                  />
                </div>
                <span className="w-8 text-right font-semibold text-slate-900">{value}</span>
              </div>
            );
          })}
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {CONVERSIONS.map((c) => (
            <div key={c.key} className="rounded-xl border border-slate-200 bg-white p-3">
              <p className="text-xs font-medium text-slate-500">{c.label}</p>
              <p className="text-xl font-bold text-slate-900">
                {metrics.funnel.conversion[c.key] != null
                  ? `${metrics.funnel.conversion[c.key]}%`
                  : '—'}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {DURATIONS.map((d) => (
            <div key={d.key} className="rounded-xl border border-slate-200 bg-white p-3">
              <p className="text-xs font-medium text-slate-500">{d.label} (median)</p>
              <p className="text-xl font-bold text-slate-900">
                {metrics.funnel.median_days[d.key] != null
                  ? `${metrics.funnel.median_days[d.key]}d`
                  : '—'}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                <th className="pb-2 pr-4">Applied in</th>
                {FUNNEL_STEPS.map((step) => (
                  <th key={step.key} className="pb-2 pr-4">
                    {step.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metrics.funnel.cohorts.map((c) => (
                <tr key={c.start} className="border-b border-slate-100">
                  <td className="py-2 pr-4 font-medium text-slate-900">{c.label}</td>
                  {FUNNEL_STEPS.map((step) => (
                    <td key={step.key} className="py-2 pr-4 text-slate-700">
                      {c[step.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Stage age */}
      <div>
        <h2 className="mb-3 text-lg font-bold text-slate-900">Stage Duration</h2>
        <p className="mb-3 text-xs text-slate-500">
          Median days in current stage for active items.
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(metrics.median_stage_age_days).map(([stage, days]) => (
            <div key={stage} className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-medium text-slate-500">{stage}</p>
              <p className={`text-2xl font-bold ${days > 7 ? 'text-amber-600' : 'text-slate-900'}`}>
                {days}d
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Source performance */}
      {Object.keys(metrics.source_performance).length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-bold text-slate-900">Source Performance</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                  <th className="pb-2 pr-4">Source</th>
                  <th className="pb-2 pr-4">Tracked</th>
                  <th className="pb-2 pr-4">Applied</th>
                  <th className="pb-2 pr-4">Interviewing</th>
                  <th className="pb-2">Offers</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(metrics.source_performance).map(([source, counts]) => (
                  <tr key={source} className="border-b border-slate-100">
                    <td className="py-2 pr-4 font-medium text-slate-900">{source}</td>
                    <td className="py-2 pr-4 text-slate-700">{counts.tracked}</td>
                    <td className="py-2 pr-4 text-slate-700">{counts.applied}</td>
                    <td className="py-2 pr-4 text-slate-700">{counts.interviewing}</td>
                    <td className="py-2 text-slate-700">{counts.offers}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Task progress */}
      <div>
        <h2 className="mb-3 text-lg font-bold text-slate-900">Campaign Tasks</h2>
        <div className="flex items-center gap-4">
          <div className="h-3 flex-1 rounded-full bg-slate-200">
            <div
              className="h-3 rounded-full bg-emerald-500 transition-all"
              style={{
                width: `${metrics.tasks.total ? (metrics.tasks.completed / metrics.tasks.total) * 100 : 0}%`,
              }}
            />
          </div>
          <span className="text-sm font-semibold text-slate-700">
            {metrics.tasks.completed} / {metrics.tasks.total}
          </span>
        </div>
      </div>

      {/* Weekly review prompt */}
      <div className="rounded-xl border border-blue-200 bg-blue-50 p-5">
        <h3 className="text-sm font-semibold text-blue-800">Weekly Review Guidance</h3>
        <div className="mt-2 text-sm text-blue-700">
          {(() => {
            const latest = metrics.weekly_cohorts[metrics.weekly_cohorts.length - 1];
            if (!latest) return <p>No data yet for review.</p>;
            if (latest.applications_submitted >= 10 && latest.reached_screen === 0) {
              return (
                <p>
                  10+ applications with no screens. Consider a positioning review — are target
                  titles, resume emphasis, and application quality aligned with what these employers
                  are looking for?
                </p>
              );
            }
            if (
              latest.reached_screen > 0 &&
              latest.reached_screen >= latest.applications_submitted * 0.3
            ) {
              return (
                <p>
                  Good screen rate. Focus on interview preparation and advancing active processes.
                </p>
              );
            }
            if (latest.applications_submitted < 5) {
              return (
                <p>
                  Low application volume this week. Check if sourcing, role criteria, or capacity
                  need adjustment.
                </p>
              );
            }
            return (
              <p>
                Pipeline is building. Continue current approach and review again next week with more
                data.
              </p>
            );
          })()}
        </div>
      </div>
    </div>
  );
}
