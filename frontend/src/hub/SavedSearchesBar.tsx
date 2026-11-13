import { useEffect, useState } from 'react';
import {
  checkAlerts,
  configureAlerts,
  deleteSavedSearch,
  readSavedSearch,
  readSavedSearches,
  saveSearch,
  type SavedSearch,
  type SearchView,
} from '../saved-search-api';

function AlertConfig({ search }: { search: SavedSearch }) {
  const [enabled, setEnabled] = useState(search.alerts_enabled ?? false);
  const [minimum, setMinimum] = useState(String(search.alert_min_score ?? 70));
  const [saved, setSaved] = useState(search);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    setEnabled(search.alerts_enabled ?? false);
    setMinimum(String(search.alert_min_score ?? 70));
    setSaved(search);
  }, [search]);

  useEffect(() => {
    let active = true;
    let first = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const row = await readSavedSearch(search.id);
        if (active) {
          setSaved(row);
          if (row.alert_check_status !== 'queued')
            setNotice((v) => (v === 'Check queued.' ? '' : v));
          if (first) {
            setEnabled(row.alerts_enabled ?? false);
            setMinimum(String(row.alert_min_score ?? 70));
            first = false;
          }
        }
      } catch (err) {
        console.error('Action failed:', err);
        /* silent */
      } finally {
        if (active) {
          setReading(false);
          timer = setTimeout(poll, 5000);
        }
      }
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [search.id, refresh]);

  async function act(check: boolean) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const row = check
        ? await checkAlerts(search.id)
        : await configureAlerts(search.id, enabled, Number(minimum));
      setSaved(row);
      setNotice(
        check ? 'Check queued.' : row.alerts_enabled ? 'Alerts enabled.' : 'Alerts disabled.',
      );
      setRefresh((v) => v + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  const status =
    {
      disabled: 'Off',
      pending: 'Pending',
      queued: 'Queued',
      ok: 'OK',
      profile_required: 'Profile required',
      publish_failed: 'Retry pending',
    }[saved.alert_check_status ?? 'disabled'] ?? 'Unknown';

  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3">
      <h4 className="text-xs font-semibold text-slate-600">Alerts for this search</h4>
      <form
        className="mt-2 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void act(false);
        }}
      >
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            disabled={busy || reading}
            className="accent-slate-900"
          />
          Enable
        </label>
        <label className="block text-xs">
          <span className="text-slate-600">Min score</span>
          <input
            type="number"
            min={0}
            max={100}
            required
            value={minimum}
            onChange={(e) => setMinimum(e.target.value)}
            disabled={busy || reading}
            className="ml-2 w-16 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={busy || reading}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          Save
        </button>
        <button
          type="button"
          disabled={busy || !saved.alerts_enabled || saved.alert_check_status === 'queued'}
          onClick={() => void act(true)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Check now
        </button>
      </form>
      <p className="mt-2 text-xs text-slate-500">
        Status: {status}
        {saved.alert_checked_at && ` · Last ${new Date(saved.alert_checked_at).toLocaleString()}`}
      </p>
      {notice && <p className="mt-1 text-xs text-emerald-600">{notice}</p>}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

export default function SavedSearchesBar({
  current,
  onLoad,
}: {
  current: SearchView;
  onLoad: (search: SavedSearch) => void;
}) {
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setBusy(true);
    readSavedSearches()
      .then((rows) => {
        if (active) {
          setSearches(rows);
          setError('');
        }
      })
      .catch(() => {
        if (active) setError('Could not load saved searches.');
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [retry]);

  async function save(replace: boolean) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const row = await saveSearch(name.trim(), current, replace ? selected : undefined);
      setSearches((rows) =>
        [...rows.filter((i) => i.id !== row.id), row].sort((a, b) => a.name.localeCompare(b.name)),
      );
      setSelected(row.id);
      setName(row.name);
      setNotice(`Saved "${row.name}".`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await deleteSavedSearch(selected);
      setSearches((rows) => rows.filter((r) => r.id !== selected));
      setSelected('');
      setName('');
      setNotice('Deleted.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  const chosen = searches.find((r) => r.id === selected);

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-700">Saved Searches</h3>
      <div className="mt-2 flex flex-wrap items-end gap-3">
        <label className="block text-xs">
          <span className="text-slate-600">Search</span>
          <select
            value={selected}
            disabled={busy}
            onChange={(e) => {
              setSelected(e.target.value);
              setName(searches.find((r) => r.id === e.target.value)?.name ?? '');
              setNotice('');
            }}
            className="mt-1 block w-48 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Choose…</option>
            {searches.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={busy || !chosen}
          onClick={() => {
            if (chosen) {
              onLoad(chosen);
              setNotice(`Loaded "${chosen.name}".`);
            }
          }}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          Load
        </button>
        <label className="block text-xs">
          <span className="text-slate-600">Name</span>
          <input
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name this view"
            className="mt-1 block w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <button
          type="button"
          disabled={busy || !name.trim()}
          onClick={() => void save(false)}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          Save new
        </button>
        <button
          type="button"
          disabled={busy || !chosen || !name.trim()}
          onClick={() => void save(true)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Update
        </button>
        <button
          type="button"
          disabled={busy || !chosen}
          onClick={() => void remove()}
          className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
        >
          Delete
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Apply filters before saving. Deleting removes alert inbox entries too.
      </p>
      {chosen && <AlertConfig key={chosen.id} search={chosen} />}
      {notice && <p className="mt-2 text-xs text-emerald-600">{notice}</p>}
      {error && (
        <div className="mt-2">
          <p className="text-xs text-red-600">{error}</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => setRetry((v) => v + 1)}
            className="mt-1 text-xs text-slate-600 underline"
          >
            Retry
          </button>
        </div>
      )}
    </div>
  );
}
