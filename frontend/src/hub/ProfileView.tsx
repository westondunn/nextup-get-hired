import { type ChangeEvent, type FormEvent, useEffect, useState } from 'react';
import {
  exampleProfile,
  parseProfile,
  type ProfileData,
  readProfile,
  saveProfile,
} from '../profile-api';

export default function ProfileView() {
  const [skills, setSkills] = useState('');
  const [titles, setTitles] = useState('');
  const [location, setLocation] = useState('');
  const [preferences, setPreferences] = useState<ProfileData['work_preferences']>([]);
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loadAttempt, setLoadAttempt] = useState(0);

  function populate(profile: ProfileData) {
    setSkills(profile.skills.join('\n'));
    setTitles(profile.target_titles.join('\n'));
    setLocation(profile.location);
    setPreferences(profile.work_preferences);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void readProfile()
      .then((profile) => {
        if (!active) return;
        if (profile) populate(profile);
        setReady(true);
        setNotice(
          profile ? 'Saved profile loaded.' : 'Start with your details or load the example.',
        );
      })
      .catch((cause) => {
        if (active)
          setError(cause instanceof Error ? cause.message : 'Profile could not be loaded.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loadAttempt]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError('');
    setNotice('');
    try {
      const profile = parseProfile({
        skills: skills.split('\n').filter((v) => v.trim()),
        target_titles: titles.split('\n').filter((v) => v.trim()),
        location,
        work_preferences: preferences,
      });
      setSaving(true);
      populate(await saveProfile(profile));
      setNotice('Profile saved.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError('');
    setNotice('');
    try {
      if (file.size > 32768) throw new Error('File too large (max 32 KB).');
      const profile = parseProfile(JSON.parse(await file.text()));
      populate(profile);
      setNotice('JSON loaded. Save to keep changes.');
    } catch (cause) {
      setError(
        cause instanceof SyntaxError
          ? 'Not valid JSON.'
          : cause instanceof Error
            ? cause.message
            : 'Could not read file.',
      );
    }
  }

  return (
    <div>
      <h2 className="text-xl font-bold text-slate-900">Search Profile</h2>
      <p className="mt-1 text-sm text-slate-500">
        Define your skills, target roles, and preferences. This profile stays on your device and
        powers job scoring.
      </p>

      {loading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}
      {error && <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {!ready && !loading && (
        <button
          type="button"
          onClick={() => setLoadAttempt((v) => v + 1)}
          className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          Retry
        </button>
      )}

      <form
        onSubmit={(e) => void submit(e)}
        onChange={() => {
          setNotice('Unsaved changes.');
          setError('');
        }}
        className="mt-6"
      >
        <fieldset disabled={!ready || loading || saving} className="space-y-5">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">
                Skills <span className="font-normal text-slate-500">· one per line, up to 50</span>
              </span>
              <textarea
                value={skills}
                onChange={(e) => setSkills(e.target.value)}
                rows={5}
                required
                placeholder={'Project planning\nBudgeting\nStakeholder communication'}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">
                Target titles{' '}
                <span className="font-normal text-slate-500">· one per line, up to 20</span>
              </span>
              <textarea
                value={titles}
                onChange={(e) => setTitles(e.target.value)}
                rows={5}
                required
                placeholder={'Operations Manager\nProgram Coordinator'}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>

          <label className="block text-sm">
            <span className="font-medium text-slate-700">Preferred location</span>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              maxLength={160}
              required
              placeholder="City or region"
              className="mt-1 block w-full max-w-md rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>

          <fieldset>
            <legend className="text-sm font-medium text-slate-700">Work preferences</legend>
            <div className="mt-2 flex flex-wrap gap-4">
              {(['remote', 'hybrid', 'onsite'] as const).map((value) => (
                <label key={value} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={preferences.includes(value)}
                    onChange={(e) =>
                      setPreferences((c) =>
                        e.target.checked ? [...c, value] : c.filter((i) => i !== value),
                      )
                    }
                    className="accent-slate-900"
                  />
                  {value === 'onsite' ? 'On-site' : value[0].toUpperCase() + value.slice(1)}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save profile'}
            </button>
            <button
              type="button"
              onClick={() => {
                populate(exampleProfile);
                setError('');
                setNotice('Example loaded. Save to keep it.');
              }}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Use example
            </button>
            <label className="cursor-pointer rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Import JSON
              <input
                type="file"
                accept=".json,application/json"
                onChange={(e) => void importFile(e)}
                className="hidden"
              />
            </label>
          </div>
        </fieldset>
      </form>
      {notice && <p className="mt-4 text-sm text-emerald-600">{notice}</p>}
    </div>
  );
}
