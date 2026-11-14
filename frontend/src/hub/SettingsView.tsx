import { useEffect, useState } from 'react';
import { type Diagnostic, type Health, readDiagnostic, readHealth, startDiagnostic } from '../api';
import { cleanupHistory, previewHistory, type HistoryPreview } from '../retention-api';
import {
  type ProfileData,
  readProfile,
  saveProfile,
  parseProfile,
  exampleProfile,
} from '../profile-api';
import { ApiError, request } from '../jobs-api';
import { type Campaign, readCampaigns, updateCampaign } from './campaign-api';
import {
  type CorrespondenceSettings,
  readCorrespondence,
  runCorrespondenceSync,
  saveCorrespondence,
} from './correspondence-api';
import { LocalSessionCard } from './LocalSessionCard';

const SERVICE_LABELS: Record<string, string> = {
  api: 'API',
  database: 'PostgreSQL',
  broker: 'Redis broker',
  worker: 'Celery worker',
};

// Sync settings are behind the local session; say where to unlock them.
function syncFailure(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 401) {
    return 'Integration settings are locked. Unlock them above with the setup code, then try again.';
  }
  return error instanceof Error ? error.message : fallback;
}

/* ---------- Main Settings View ---------- */
export default function SettingsView() {
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
  // Profile
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [skills, setSkills] = useState('');
  const [titles, setTitles] = useState('');
  const [location, setLocation] = useState('');
  const [workPrefs, setWorkPrefs] = useState<ProfileData['work_preferences']>([]);
  const [profileNotice, setProfileNotice] = useState('');
  const [profileError, setProfileError] = useState('');
  const [profileBusy, setProfileBusy] = useState(false);
  // Campaign
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [capacity, setCapacity] = useState('240');
  const [timezone, setTimezone] = useState('UTC');
  const [campBusy, setCampBusy] = useState(false);
  const [campMsg, setCampMsg] = useState('');
  // Gmail correspondence sync (backend-backed, read-only)
  const [mail, setMail] = useState<CorrespondenceSettings | null>(null);
  const [mailQuery, setMailQuery] = useState('label:job-search');
  const [mailBatch, setMailBatch] = useState(25);
  const [calLookahead, setCalLookahead] = useState(14);
  const [mailBusy, setMailBusy] = useState(false);
  const [mailMsg, setMailMsg] = useState('');
  const [mailError, setMailError] = useState('');
  // Discovery
  const [discovery, setDiscovery] = useState<{
    enabled: boolean;
    interval_hours: number;
    min_score: number;
    boards: unknown[];
    max_boards: number;
  } | null>(null);
  const [discEnabled, setDiscEnabled] = useState(false);
  const [discInterval, setDiscInterval] = useState(24);
  const [discMinScore, setDiscMinScore] = useState(20);
  const [discBusy, setDiscBusy] = useState(false);
  const [discMsg, setDiscMsg] = useState('');

  // General
  const [message, setMessage] = useState('');

  useEffect(() => {
    // Health polling
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const h = await readHealth();
        if (active) {
          setHealth(h);
          setHealthError('');
        }
      } catch (err) {
        console.error('Action failed:', err);
        if (active) {
          setHealth(null);
          setHealthError('API unreachable.');
        }
      }
      if (active) timer = setTimeout(poll, 10000);
    }
    void poll();
    readCorrespondence()
      .then((m) => {
        if (!active) return;
        setMail(m);
        setMailQuery(m.query);
        setMailBatch(m.max_messages_per_run);
        setCalLookahead(m.calendar_lookahead_days);
      })
      .catch(() => {
        if (active) setMailError('Gmail sync status unavailable.');
      });
    // Load profile
    readProfile()
      .then((p) => {
        if (p && active) {
          setProfile(p);
          setSkills(p.skills.join('\n'));
          setTitles(p.target_titles.join('\n'));
          setLocation(p.location);
          setWorkPrefs(p.work_preferences);
        }
      })
      .catch(() => {});
    // Load campaign
    readCampaigns()
      .then((camps) => {
        const c = camps.find((x) => x.is_active) ?? camps[0];
        if (c && active) {
          setCampaign(c);
          setCapacity(String(c.daily_capacity_minutes));
          setTimezone(c.timezone);
        }
      })
      .catch(() => {});
    // Load discovery
    request<typeof discovery>('discovery')
      .then((d) => {
        if (d && active) {
          setDiscovery(d);
          setDiscEnabled(d.enabled);
          setDiscInterval(d.interval_hours);
          setDiscMinScore(d.min_score);
        }
      })
      .catch(() => {});
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
    async function poll() {
      try {
        const next = await readDiagnostic(run!.id);
        if (active) {
          setRun(next);
          setDiagError('');
        }
        if (!['queued', 'publish_failed'].includes(next.status)) return;
      } catch (err) {
        console.error('Action failed:', err);
        if (active) setDiagError('Waiting…');
      }
      if (active) timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [run?.id, run?.status]);

  async function saveMail(changes: {
    enabled?: boolean;
    calendar_enabled?: boolean;
    auto_create_applications?: boolean;
  }) {
    const autoCreate = changes.auto_create_applications ?? mail?.auto_create_applications ?? false;
    const enabled = changes.enabled ?? mail?.enabled ?? false;
    const calendarEnabled = changes.calendar_enabled ?? mail?.calendar_enabled ?? false;
    const query = mailQuery.trim() || 'label:job-search';
    const batch = Math.min(200, Math.max(1, Math.round(mailBatch) || 25));
    const lookahead = Math.min(60, Math.max(1, Math.round(calLookahead) || 14));
    if (
      mail &&
      enabled === mail.enabled &&
      calendarEnabled === mail.calendar_enabled &&
      autoCreate === mail.auto_create_applications &&
      query === mail.query &&
      batch === mail.max_messages_per_run &&
      lookahead === mail.calendar_lookahead_days
    ) {
      return;
    }
    setMailBusy(true);
    setMailError('');
    try {
      const next = await saveCorrespondence({
        enabled,
        query,
        max_messages_per_run: batch,
        calendar_enabled: calendarEnabled,
        calendar_lookahead_days: lookahead,
        auto_create_applications: autoCreate,
      });
      setMail(next);
      setMailQuery(next.query);
      setMailBatch(next.max_messages_per_run);
      setCalLookahead(next.calendar_lookahead_days);
      setMailMsg(
        `Gmail sync ${next.enabled ? 'on' : 'off'}; Calendar sync ${next.calendar_enabled ? 'on' : 'off'}; applications from confirmation emails ${next.auto_create_applications ? 'on' : 'off'}. Mail and calendar access stay read only.`,
      );
    } catch (e) {
      setMailError(syncFailure(e, 'Could not save sync settings.'));
    } finally {
      setMailBusy(false);
    }
  }

  async function syncMailNow() {
    setMailBusy(true);
    setMailError('');
    try {
      await runCorrespondenceSync();
      setMailMsg('Sync queued. Results appear here and in Contacts within a minute.');
      setTimeout(() => {
        readCorrespondence()
          .then(setMail)
          .catch(() => undefined);
      }, 5000);
    } catch (e) {
      setMailError(syncFailure(e, 'Sync could not be queued.'));
    } finally {
      setMailBusy(false);
    }
  }

  const displayedRun = run ?? health?.latest_diagnostic;

  return (
    <div className="space-y-8">
      {/* ===== Campaign Settings ===== */}
      <Section title="Campaign">
        {campaign ? (
          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Daily capacity (minutes)</span>
                <input
                  type="number"
                  min={30}
                  max={720}
                  value={capacity}
                  onChange={(e) => setCapacity(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Timezone</span>
                <input
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <div className="flex items-end">
                <button
                  type="button"
                  disabled={campBusy}
                  onClick={async () => {
                    setCampBusy(true);
                    setCampMsg('');
                    try {
                      await updateCampaign(campaign.id, {
                        daily_capacity_minutes: Number(capacity),
                        timezone,
                      });
                      setCampMsg('Saved.');
                    } catch (err) {
                      console.error('Action failed:', err);
                      setCampMsg('Failed.');
                    }
                    setCampBusy(false);
                  }}
                  className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  Save
                </button>
              </div>
            </div>
            <p className="text-xs text-slate-500">
              {campaign.title} · {campaign.start_date} to {campaign.end_date}
            </p>
            {campMsg && <p className="text-xs text-emerald-600">{campMsg}</p>}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No active campaign.</p>
        )}
      </Section>

      {/* ===== Search Profile ===== */}
      <Section title="Search Profile">
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setProfileError('');
            setProfileNotice('');
            setProfileBusy(true);
            try {
              const p = parseProfile({
                skills: skills.split('\n').filter((v) => v.trim()),
                target_titles: titles.split('\n').filter((v) => v.trim()),
                location,
                work_preferences: workPrefs,
              });
              const saved = await saveProfile(p);
              setProfile(saved);
              setSkills(saved.skills.join('\n'));
              setTitles(saved.target_titles.join('\n'));
              setLocation(saved.location);
              setWorkPrefs(saved.work_preferences);
              setProfileNotice('Profile saved.');
            } catch (err) {
              console.error('Action failed:', err);
              setProfileError(err instanceof Error ? err.message : 'Failed.');
            }
            setProfileBusy(false);
          }}
          className="space-y-3"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Skills (one per line)</span>
              <textarea
                rows={4}
                value={skills}
                onChange={(e) => setSkills(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Target titles (one per line)</span>
              <textarea
                rows={4}
                value={titles}
                onChange={(e) => setTitles(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <label className="block text-xs">
            <span className="font-medium text-slate-600">Location</span>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="mt-1 block w-full max-w-sm rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <fieldset>
            <legend className="text-xs font-medium text-slate-600">Work preferences</legend>
            <div className="mt-1 flex gap-4">
              {(['remote', 'hybrid', 'onsite'] as const).map((v) => (
                <label key={v} className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={workPrefs.includes(v)}
                    onChange={(e) =>
                      setWorkPrefs((c) => (e.target.checked ? [...c, v] : c.filter((i) => i !== v)))
                    }
                    className="accent-slate-900"
                  />
                  {v === 'onsite' ? 'On-site' : v[0].toUpperCase() + v.slice(1)}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={profileBusy}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Save Profile
            </button>
            <button
              type="button"
              onClick={() => {
                setSkills(exampleProfile.skills.join('\n'));
                setTitles(exampleProfile.target_titles.join('\n'));
                setLocation(exampleProfile.location);
                setWorkPrefs(exampleProfile.work_preferences);
              }}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Load Example
            </button>
          </div>
          {profileNotice && <p className="text-xs text-emerald-600">{profileNotice}</p>}
          {profileError && <p className="text-xs text-red-600">{profileError}</p>}
        </form>
      </Section>

      {/* ===== Discovery ===== */}
      <Section title="Job Discovery">
        {discovery ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={discEnabled}
                  onChange={(e) => setDiscEnabled(e.target.checked)}
                  className="accent-slate-900"
                />
                Auto-refresh enabled
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Interval (hours)</span>
                <input
                  type="number"
                  min={6}
                  max={168}
                  value={discInterval}
                  onChange={(e) => setDiscInterval(Number(e.target.value))}
                  className="ml-2 w-16 rounded border border-slate-300 px-2 py-1 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Min score</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={discMinScore}
                  onChange={(e) => setDiscMinScore(Number(e.target.value))}
                  className="ml-2 w-16 rounded border border-slate-300 px-2 py-1 text-sm"
                />
              </label>
            </div>
            <p className="text-xs text-slate-500">
              {discovery.boards.length} employer boards configured (max {discovery.max_boards}).
              Manage boards on the Discovery page.
            </p>
            <button
              type="button"
              disabled={discBusy}
              onClick={async () => {
                setDiscBusy(true);
                setDiscMsg('');
                try {
                  await request('discovery', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      enabled: discEnabled,
                      interval_hours: discInterval,
                      min_score: discMinScore,
                      boards: discovery.boards,
                    }),
                  });
                  setDiscMsg('Saved.');
                } catch (err) {
                  console.error('Action failed:', err);
                  setDiscMsg('Failed.');
                }
                setDiscBusy(false);
              }}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Save Discovery Settings
            </button>
            {discMsg && <p className="text-xs text-emerald-600">{discMsg}</p>}
          </div>
        ) : (
          <p className="text-sm text-slate-500">Loading discovery settings…</p>
        )}
      </Section>

      {/* ===== Integrations ===== */}
      <Section title="Integrations">
        <p className="mb-3 text-xs text-slate-500">Connect external services.</p>

        <LocalSessionCard />

        {/* Google Calendar (read-only sync, backend-backed) */}
        <IntegrationCard
          name="Google Calendar (read-only sync)"
          description="Log upcoming events for review. Nothing is created, edited, or accepted."
          enabled={mail?.calendar_enabled ?? false}
          onToggle={(v) => void saveMail({ calendar_enabled: v })}
        >
          <label className="block text-xs sm:w-48">
            <span className="font-medium text-slate-600">Look ahead (days)</span>
            <input
              type="number"
              min={1}
              max={60}
              value={calLookahead}
              onChange={(e) => setCalLookahead(Number(e.target.value))}
              onBlur={() => void saveMail({})}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          {mail && (
            <p className="mt-2 text-xs text-slate-500">
              Last run:{' '}
              {mail.calendar_last_run_at
                ? new Date(mail.calendar_last_run_at).toLocaleString()
                : 'never'}
              {' · '}status {mail.calendar_last_status} · imported {mail.calendar_last_imported}
            </p>
          )}
          {mail?.calendar_last_error && (
            <p className="mt-1 text-xs text-red-600">{mail.calendar_last_error}</p>
          )}
        </IntegrationCard>
        {mail && !(mail.calendar_live_enabled && mail.credentials_present) && (
          <p className="-mt-2 mb-3 text-[11px] text-amber-700">
            Calendar sync is switched off in this release and cannot be enabled from here yet.
          </p>
        )}

        {/* Gmail (read-only sync, backend-backed) */}
        <IntegrationCard
          name="Gmail (read-only sync)"
          description="Import matching mail as inbound communications. Nothing is ever sent or labeled."
          enabled={mail?.enabled ?? false}
          onToggle={(v) => void saveMail({ enabled: v })}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block text-xs sm:col-span-2">
              <span className="font-medium text-slate-600">Gmail search query</span>
              <input
                value={mailQuery}
                onChange={(e) => setMailQuery(e.target.value)}
                onBlur={() => void saveMail({})}
                placeholder="label:job-search"
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
              />
            </label>
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Messages per run</span>
              <input
                type="number"
                min={1}
                max={200}
                value={mailBatch}
                onChange={(e) => setMailBatch(Number(e.target.value))}
                onBlur={() => void saveMail({})}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <label className="mt-3 flex items-start gap-2 text-xs">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={mail?.auto_create_applications ?? false}
              disabled={mailBusy || !mail}
              onChange={(e) => void saveMail({ auto_create_applications: e.target.checked })}
            />
            <span>
              <span className="font-medium text-slate-700">
                Create applications from confirmation emails
              </span>
              <span className="mt-0.5 block text-slate-500">
                When a message such as “Thank you for applying to …” names the employer and the
                role, Nextup records the application as applied (or moves a matching one from review
                or preparing), adds the sender as a contact, links the message, and schedules the
                status check. Less certain matches wait in Contacts for your confirmation, and every
                automatic record can be undone from the application.
              </span>
            </span>
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={mailBusy}
              onClick={() => void syncMailNow()}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Sync now
            </button>
            {mail && (
              <span className="text-xs text-slate-500">
                Last run: {mail.last_run_at ? new Date(mail.last_run_at).toLocaleString() : 'never'}
                {' · '}status {mail.last_status} · imported {mail.last_imported} ·{' '}
                {mail.review_count} awaiting review
              </span>
            )}
          </div>
          {mail?.last_error && <p className="mt-1 text-xs text-red-600">{mail.last_error}</p>}
        </IntegrationCard>
        {mail && !(mail.live_enabled && mail.credentials_present) && (
          <p className="-mt-2 mb-3 text-[11px] text-amber-700">
            Gmail sync is switched off in this release and cannot be enabled from here yet. Only
            read-only scopes are ever requested.
          </p>
        )}
        {mailMsg && <p className="-mt-2 mb-3 text-xs text-emerald-700">{mailMsg}</p>}
        {mailError && <p className="-mt-2 mb-3 text-xs text-red-600">{mailError}</p>}

        {/* CSV Import */}
        <IntegrationCard
          name="CSV Job Import"
          description="Import jobs from a CSV file (LinkedIn export, job board export, etc.)"
          enabled={true}
          onToggle={() => {}}
        >
          <p className="text-xs text-slate-500">
            Use the Job Board "Add Job" button for individual entries, or set up an automation to
            batch-import from CSV to the{' '}
            <code className="text-[10px]">POST /api/job-references</code> endpoint.
          </p>
          <p className="mt-1 text-[10px] text-slate-400">
            Fields: title, company, location, description, url
          </p>
        </IntegrationCard>
      </Section>

      {/* ===== System Health ===== */}
      <Section title="System Health">
        {healthError && <p className="mb-3 text-sm text-red-600">{healthError}</p>}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(SERVICE_LABELS).map(([key, label]) => {
            const status = health?.checks[key as keyof Health['checks']];
            return (
              <div key={key} className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-sm font-medium text-slate-700">{label}</p>
                <p
                  className={`mt-1 flex items-center gap-2 text-sm font-semibold ${status === 'up' ? 'text-emerald-600' : status === 'down' ? 'text-red-600' : 'text-slate-500'}`}
                >
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${status === 'up' ? 'bg-emerald-500' : status === 'down' ? 'bg-red-500' : 'bg-slate-400'}`}
                  />
                  {status === 'up' ? 'Responding' : status === 'down' ? 'Unavailable' : 'Unknown'}
                </p>
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Scheduler: {health?.scheduler ?? 'unknown'} · Interval:{' '}
          {health?.diagnostic_interval_seconds ?? '?'}s
          {health && ` · Last ${new Date(health.checked_at).toLocaleTimeString()}`}
        </p>
      </Section>

      {/* ===== Diagnostics ===== */}
      <Section title="Diagnostics">
        <button
          type="button"
          onClick={async () => {
            setDiagBusy(true);
            setDiagError('');
            try {
              setRun(await startDiagnostic());
            } catch (err) {
              console.error('Action failed:', err);
              setDiagError(err instanceof Error ? err.message : 'Failed.');
            }
            setDiagBusy(false);
          }}
          disabled={diagBusy || run?.status === 'queued'}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {diagBusy ? 'Submitting…' : run?.status === 'queued' ? 'Waiting…' : 'Run Diagnostic'}
        </button>
        {diagError && <p className="mt-2 text-sm text-red-600">{diagError}</p>}
        {displayedRun && (
          <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm">
            <p className="font-medium text-slate-900">
              {displayedRun.status === 'succeeded'
                ? 'Passed'
                : displayedRun.status === 'queued'
                  ? 'Queued'
                  : (displayedRun.error_message ?? 'Failed')}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {displayedRun.worker ?? 'Pending'} ·{' '}
              {displayedRun.completed_at
                ? new Date(displayedRun.completed_at).toLocaleString()
                : 'Pending'}
            </p>
          </div>
        )}
      </Section>

      {/* ===== Task History ===== */}
      <Section title="Task History Cleanup">
        <button
          type="button"
          disabled={histBusy}
          onClick={async () => {
            setHistBusy(true);
            setPreview(null);
            setHistError('');
            setHistMsg('');
            try {
              setPreview(await previewHistory());
            } catch (err) {
              console.error('Action failed:', err);
              setHistError(err instanceof Error ? err.message : 'Failed.');
            }
            setHistBusy(false);
          }}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {histBusy ? 'Loading…' : 'Preview Cleanup'}
        </button>
        {histError && <p className="mt-2 text-sm text-red-600">{histError}</p>}
        {histMsg && (
          <p role="status" className="mt-2 text-sm text-emerald-600">
            {histMsg}
          </p>
        )}
        {preview && (
          <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm">
            <p>
              Diagnostics: {preview.groups.diagnostics.selected}/
              {preview.groups.diagnostics.eligible} · Fetches: {preview.groups.fetches.selected}/
              {preview.groups.fetches.eligible}
            </p>
            {preview.enabled &&
              preview.groups.diagnostics.selected + preview.groups.fetches.selected > 0 && (
                <div className="mt-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      onChange={(e) => setConfirmed(e.target.checked)}
                      className="accent-slate-900"
                    />
                    I understand this permanently deletes the previewed history
                  </label>
                  <button
                    type="button"
                    disabled={!confirmed || histBusy}
                    onClick={async () => {
                      setHistBusy(true);
                      try {
                        const r = await cleanupHistory(preview.token);
                        const { diagnostics, fetches } = r.groups;
                        setHistMsg(
                          `Deleted ${diagnostics.deleted} diagnostics and ${fetches.deleted} fetch records.` +
                            ` Skipped ${diagnostics.skipped + fetches.skipped}.`,
                        );
                        setConfirmed(false);
                        setPreview(null);
                      } catch (err) {
                        console.error('Action failed:', err);
                        setHistError('Failed.');
                      }
                      setHistBusy(false);
                    }}
                    className="mt-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                  >
                    Delete previewed history
                  </button>
                </div>
              )}
          </div>
        )}
      </Section>

      {message && <p className="text-sm text-emerald-600">{message}</p>}
    </div>
  );
}

/* ---------- Helpers ---------- */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="mb-4 text-base font-semibold text-slate-900">{title}</h2>
      {children}
    </div>
  );
}

function IntegrationCard({
  name,
  description,
  enabled,
  onToggle,
  children,
}: {
  name: string;
  description: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`mb-3 rounded-lg border p-4 ${enabled ? 'border-emerald-200 bg-emerald-50/30' : 'border-slate-200'}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-900">{name}</p>
          <p className="text-xs text-slate-500">{description}</p>
        </div>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onToggle(e.target.checked)}
            className="accent-emerald-600"
          />
          {enabled ? 'Enabled' : 'Disabled'}
        </label>
      </div>
      {enabled && <div className="mt-3">{children}</div>}
    </div>
  );
}
