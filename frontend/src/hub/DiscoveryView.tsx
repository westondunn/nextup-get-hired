import { useEffect, useRef, useState } from 'react';
import { safeHref } from './safe';
import { request } from '../jobs-api';

type Board = { provider: 'greenhouse' | 'lever' | 'ashby'; board: string; company: string };
type Responsibility = 'auto' | 'management' | 'individual' | 'any';
type CatalogBoard = Board & { careers_url?: string; sector?: string };

const lines = (text: string) =>
  text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
const aliasText = (aliases: Record<string, string>) =>
  Object.entries(aliases)
    .map(([short, full]) => `${short} = ${full}`)
    .join('\n');
// A line without "=" is sent with an empty expansion so that the server rejects it visibly.
const parseAliases = (text: string) =>
  Object.fromEntries(
    lines(text).map((line) => {
      const [short, ...rest] = line.split('=');
      return [short.trim(), rest.join('=').trim()];
    }),
  );
interface Discovery {
  enabled: boolean;
  interval_hours: number;
  min_score: number;
  match_preferences: {
    locations: string[];
    include_unspecified_location: boolean;
    leadership: 'auto' | 'strict' | 'any';
    needs_sponsorship: boolean;
    has_clearance: boolean;
    responsibility: Responsibility;
    title_aliases: Record<string, string>;
    other_specialties: string[];
  };
  boards: Board[];
  catalog: CatalogBoard[];
  max_boards: number;
  live_enabled: boolean;
  profile_ready: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  states: (Board & {
    run: {
      id: string;
      status: string;
      received: number;
      stored: number;
      invalid: number;
      error: string | null;
      automatic: boolean;
      completed_at: string | null;
    } | null;
  })[];
}
const key = (b: Board) => `${b.provider}:${b.board.toLowerCase()}`;

export default function DiscoveryView({ onViewJobs }: { onViewJobs: () => void }) {
  const initialized = useRef(false);
  const [state, setState] = useState<Discovery | null>(null);
  const [selected, setSelected] = useState<Board[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [interval, setInterval] = useState(24);
  const [minimum, setMinimum] = useState(20);
  const [locations, setLocations] = useState('');
  const [includeUnspecified, setIncludeUnspecified] = useState(false);
  const [leadership, setLeadership] = useState<'auto' | 'strict' | 'any'>('auto');
  const [needsSponsorship, setNeedsSponsorship] = useState(false);
  const [hasClearance, setHasClearance] = useState(false);
  const [responsibility, setResponsibility] = useState<Responsibility>('auto');
  const [aliases, setAliases] = useState('');
  const [specialties, setSpecialties] = useState('');
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [provider, setProvider] = useState<Board['provider']>('greenhouse');
  const [board, setBoard] = useState('');
  const [company, setCompany] = useState('');
  const [sourceSearch, setSourceSearch] = useState('');

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await request<Discovery>('discovery');
        if (active) {
          setState(next);
          if (!initialized.current) {
            initialized.current = true;
            if (next.enabled && next.profile_ready) onViewJobs();
          }
          if (!dirty) {
            setSelected(next.boards);
            setEnabled(next.enabled);
            setInterval(next.interval_hours);
            setMinimum(next.min_score);
            setLocations(next.match_preferences.locations.join('\n'));
            setIncludeUnspecified(next.match_preferences.include_unspecified_location);
            setLeadership(next.match_preferences.leadership);
            setNeedsSponsorship(next.match_preferences.needs_sponsorship);
            setHasClearance(next.match_preferences.has_clearance);
            setResponsibility(next.match_preferences.responsibility);
            setAliases(aliasText(next.match_preferences.title_aliases));
            setSpecialties(next.match_preferences.other_specialties.join('\n'));
          }
        }
      } catch (err) {
        console.error('Action failed:', err);
        if (active) setError('Discovery unavailable.');
      } finally {
        if (active) timer = setTimeout(poll, 10000);
      }
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [dirty]);

  async function save() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const next = await request<Discovery>('discovery', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled,
          interval_hours: interval,
          min_score: minimum,
          boards: selected.map(({ provider, board, company }) => ({ provider, board, company })),
          match_preferences: {
            locations: locations
              .split('\n')
              .map((i) => i.trim())
              .filter(Boolean),
            include_unspecified_location: includeUnspecified,
            leadership,
            needs_sponsorship: needsSponsorship,
            has_clearance: hasClearance,
            responsibility,
            title_aliases: parseAliases(aliases),
            other_specialties: lines(specialties),
          },
        }),
      });
      setState(next);
      setLocations(next.match_preferences.locations.join('\n'));
      setIncludeUnspecified(next.match_preferences.include_unspecified_location);
      setLeadership(next.match_preferences.leadership);
      setNeedsSponsorship(next.match_preferences.needs_sponsorship);
      setHasClearance(next.match_preferences.has_clearance);
      setResponsibility(next.match_preferences.responsibility);
      setAliases(aliasText(next.match_preferences.title_aliases));
      setSpecialties(next.match_preferences.other_specialties.join('\n'));
      setDirty(false);
      setMessage(
        enabled
          ? 'Saved. Automatic discovery will run when due.'
          : 'Saved. Automatic discovery paused.',
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await request<{ runs: { status: string }[] }>('discovery/run', {
        method: 'POST',
      });
      setMessage(`${result.runs.length} employer requests queued.`);
      onViewJobs();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not start.');
    } finally {
      setBusy(false);
    }
  }

  const available: CatalogBoard[] = [
    ...(state?.catalog ?? []),
    ...selected.filter((b) => !state?.catalog.some((s) => key(b) === key(s))),
  ];
  const visible = available.filter((item) =>
    `${item.company} ${item.provider} ${item.board} ${item.sector ?? ''}`
      .toLowerCase()
      .includes(sourceSearch.trim().toLowerCase()),
  );

  return (
    <div>
      <h2 className="text-xl font-bold text-slate-900">Job Discovery</h2>
      <p className="mt-1 text-sm text-slate-500">
        Automatically fetch and score jobs from employer boards. Your profile stays local.
      </p>

      {!state && <p className="mt-4 text-sm text-slate-500">Loading…</p>}
      {error && <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {state && (
        <>
          {!state.profile_ready && (
            <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
              Save your profile (skills, target roles, location) before discovery can run.
            </div>
          )}

          <fieldset disabled={busy} className="mt-6 space-y-6">
            {/* Employer sources */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700">
                Employer sources ({selected.length}/{state.max_boards})
              </h3>
              <input
                type="search"
                aria-label="Search employers"
                value={sourceSearch}
                placeholder="Search employers…"
                onChange={(e) => setSourceSearch(e.target.value)}
                className="mt-2 block w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {visible.map((item) => (
                  <label
                    key={key(item)}
                    className="flex items-start gap-2 rounded-lg border border-slate-200 p-3 text-sm hover:bg-slate-50"
                  >
                    <input
                      type="checkbox"
                      checked={selected.some((x) => key(x) === key(item))}
                      disabled={
                        selected.length >= state.max_boards &&
                        !selected.some((x) => key(x) === key(item))
                      }
                      onChange={(e) => {
                        setDirty(true);
                        setSelected((old) =>
                          e.target.checked
                            ? [...old, item]
                            : old.filter((x) => key(x) !== key(item)),
                        );
                      }}
                      className="mt-0.5 accent-slate-900"
                    />
                    <div>
                      <p className="font-medium text-slate-900">
                        {item.company} <span className="text-slate-500">({item.provider})</span>
                      </p>
                      {item.sector && <p className="text-xs text-slate-500">{item.sector}</p>}
                      {item.careers_url && (
                        <a
                          href={safeHref(item.careers_url)}
                          aria-label={`${item.company} public careers board`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-slate-500 underline"
                        >
                          Public board
                        </a>
                      )}
                    </div>
                  </label>
                ))}
              </div>
              {!visible.length && <p className="mt-2 text-sm text-slate-500">No matches.</p>}
            </div>

            {/* Add custom board */}
            <details>
              <summary className="cursor-pointer text-sm font-medium text-slate-700">
                Add another employer board
              </summary>
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4">
                <label className="block text-xs">
                  <span className="font-medium text-slate-600">Provider</span>
                  <select
                    value={provider}
                    onChange={(e) => setProvider(e.target.value as Board['provider'])}
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="greenhouse">Greenhouse</option>
                    <option value="lever">Lever</option>
                    <option value="ashby">Ashby</option>
                  </select>
                </label>
                <label className="block text-xs">
                  <span className="font-medium text-slate-600">Board token</span>
                  <input
                    value={board}
                    onChange={(e) => setBoard(e.target.value)}
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </label>
                <label className="block text-xs">
                  <span className="font-medium text-slate-600">Company name</span>
                  <input
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </label>
                <div className="flex items-end">
                  <button
                    type="button"
                    disabled={
                      !/^[A-Za-z0-9_-]{1,100}$/.test(board) ||
                      !company.trim() ||
                      selected.length >= state.max_boards ||
                      selected.some(
                        (x) =>
                          x.provider === provider && x.board.toLowerCase() === board.toLowerCase(),
                      )
                    }
                    onClick={() => {
                      setSelected((old) => [...old, { provider, board, company: company.trim() }]);
                      setBoard('');
                      setCompany('');
                      setDirty(true);
                    }}
                    className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    Add
                  </button>
                </div>
              </div>
            </details>

            {/* Options */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => {
                    setEnabled(e.target.checked);
                    setDirty(true);
                  }}
                  className="accent-slate-900"
                />
                Refresh automatically
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Interval (hours)</span>
                <input
                  type="number"
                  min={6}
                  max={168}
                  value={interval}
                  onChange={(e) => {
                    setInterval(Number(e.target.value));
                    setDirty(true);
                  }}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Min match score</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={minimum}
                  onChange={(e) => {
                    setMinimum(Number(e.target.value));
                    setDirty(true);
                  }}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
            </div>

            {/* Match relevance */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700">Match relevance</h3>
              <label className="mt-2 block text-xs">
                <span className="font-medium text-slate-600">Location phrases (one per line)</span>
                <textarea
                  rows={4}
                  value={locations}
                  onChange={(e) => {
                    setLocations(e.target.value);
                    setDirty(true);
                  }}
                  placeholder={'Remote\nExample City'}
                  className="mt-1 block w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="mt-2 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={includeUnspecified}
                  onChange={(e) => {
                    setIncludeUnspecified(e.target.checked);
                    setDirty(true);
                  }}
                  className="accent-slate-900"
                />
                Include unspecified/worldwide locations
              </label>
              <label className="mt-2 block text-xs">
                <span className="font-medium text-slate-600">Leadership matching</span>
                <select
                  value={leadership}
                  onChange={(e) => {
                    setLeadership(e.target.value as typeof leadership);
                    setDirty(true);
                  }}
                  className="mt-1 block w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="auto">Follow target roles</option>
                  <option value="strict">Require leadership titles</option>
                  <option value="any">Allow IC roles too</option>
                </select>
              </label>
              <label className="mt-2 block text-xs">
                <span className="font-medium text-slate-600">
                  Title abbreviations (one per line, short = full)
                </span>
                <textarea
                  rows={2}
                  value={aliases}
                  onChange={(e) => {
                    setAliases(e.target.value);
                    setDirty(true);
                  }}
                  placeholder={'pm = product management'}
                  className="mt-1 block w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="mt-2 block text-xs">
                <span className="font-medium text-slate-600">
                  Other specialties to leave out (one per line)
                </span>
                <textarea
                  rows={2}
                  value={specialties}
                  onChange={(e) => {
                    setSpecialties(e.target.value);
                    setDirty(true);
                  }}
                  placeholder={'product marketing'}
                  className="mt-1 block w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="mt-2 block text-xs">
                <span className="font-medium text-slate-600">Responsibility level to score</span>
                <select
                  value={responsibility}
                  onChange={(e) => {
                    setResponsibility(e.target.value as Responsibility);
                    setDirty(true);
                  }}
                  className="mt-1 block w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="auto">Follow target roles</option>
                  <option value="management">People management</option>
                  <option value="individual">Individual contributor</option>
                  <option value="any">Either</option>
                </select>
              </label>
              <label className="mt-2 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={needsSponsorship}
                  onChange={(e) => {
                    setNeedsSponsorship(e.target.checked);
                    setDirty(true);
                  }}
                  className="accent-slate-900"
                />
                I need visa sponsorship
              </label>
              <label className="mt-2 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={hasClearance}
                  onChange={(e) => {
                    setHasClearance(e.target.checked);
                    setDirty(true);
                  }}
                  className="accent-slate-900"
                />
                I hold an active security clearance
              </label>
              <p className="mt-1 text-[11px] text-slate-500">
                Scoring quotes sponsorship, clearance, citizenship and people-management statements
                from listings and compares them with these answers. It never infers your status.
              </p>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void save()}
                disabled={
                  busy ||
                  selected.length > state.max_boards ||
                  (enabled && (!state.profile_ready || !state.live_enabled || !selected.length))
                }
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                Save settings
              </button>
              <button
                type="button"
                onClick={() => void run()}
                disabled={
                  busy ||
                  dirty ||
                  !state.profile_ready ||
                  !state.live_enabled ||
                  !state.boards.length
                }
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Find jobs now
              </button>
              <button
                type="button"
                onClick={onViewJobs}
                disabled={!state.profile_ready}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                View discovered jobs
              </button>
            </div>

            <p className="text-xs text-slate-500">
              {state.enabled
                ? `Auto-refresh on. Next: ${state.next_run_at ? new Date(state.next_run_at).toLocaleString() : 'pending'}.`
                : 'Auto-refresh paused.'}
            </p>

            {/* Fetch states */}
            {state.states.length > 0 && (
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-semibold text-slate-700">Fetch status</h3>
                <ul className="mt-2 space-y-2 text-sm">
                  {state.states.map((item) => (
                    <li key={key(item)} className="flex items-center justify-between">
                      <span className="font-medium text-slate-900">
                        {item.company} <span className="text-slate-500">({item.provider})</span>
                      </span>
                      {item.run ? (
                        <span
                          className={`text-xs ${item.run.error ? 'text-red-600' : 'text-slate-600'}`}
                        >
                          {item.run.status} · {item.run.stored} saved
                          {item.run.error && ` · ${item.run.error}`}
                          {item.run.completed_at &&
                            ` · ${new Date(item.run.completed_at).toLocaleString()}`}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-500">Not fetched</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </fieldset>

          {message && <p className="mt-4 text-sm text-emerald-600">{message}</p>}
        </>
      )}
    </div>
  );
}
