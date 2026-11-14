import { type FormEvent, useEffect, useId, useState } from 'react';
import { ApiError } from '../jobs-api';
import { endSession, readSession, type SessionState, startSession } from './session-api';

function failure(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'That code was not accepted.';
    if (error.status === 503) return error.message;
  }
  return fallback;
}

/**
 * Lets the user unlock integration settings by entering the installation's setup code once.
 * The code lives only in the input while it is being typed and is cleared on every submit.
 */
export function LocalSessionCard({ onChange }: { onChange?: (active: boolean) => void }) {
  const [state, setState] = useState<SessionState | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const titleId = useId();
  const inputId = useId();
  const helpId = useId();

  function apply(next: SessionState) {
    setState(next);
    onChange?.(next.active);
  }

  useEffect(() => {
    let current = true;
    readSession()
      .then((next) => {
        if (current) apply(next);
      })
      .catch(() => {
        if (current) setError('The lock status could not be read.');
      });
    return () => {
      current = false;
    };
    // Runs once on mount; `apply` only forwards the result to the caller.
  }, []);

  async function unlock(event: FormEvent) {
    event.preventDefault();
    if (!code || busy) return;
    const submitted = code;
    setCode('');
    setBusy(true);
    setError('');
    try {
      await startSession(submitted);
      apply({ configured: true, active: true });
    } catch (e) {
      setError(failure(e, 'Integration settings could not be unlocked.'));
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    setBusy(true);
    setError('');
    try {
      await endSession();
      apply({ configured: true, active: false });
    } catch (e) {
      setError(failure(e, 'Integration settings could not be locked.'));
    } finally {
      setBusy(false);
    }
  }

  const status = !state
    ? error
      ? 'Lock status unknown.'
      : 'Checking the lock…'
    : !state.configured
      ? 'Locked. No setup code is configured for this installation.'
      : state.active
        ? 'Unlocked in this browser.'
        : 'Locked.';

  return (
    <section
      aria-labelledby={titleId}
      className={`mb-3 rounded-lg border p-4 ${state?.active ? 'border-emerald-200 bg-emerald-50/30' : 'border-slate-200'}`}
    >
      <h3 id={titleId} className="text-sm font-semibold text-slate-900">
        Integrations lock
      </h3>
      <p className="text-xs text-slate-500">
        Changing or running mail and calendar sync needs this installation's setup code, entered
        once in this browser.
      </p>
      <p role="status" className="mt-2 text-xs font-medium text-slate-700">
        {status}
      </p>

      {state?.configured && !state.active && (
        <form onSubmit={unlock} className="mt-3 flex flex-wrap items-end gap-2">
          <div>
            <label htmlFor={inputId} className="block text-xs font-medium text-slate-600">
              Setup code
            </label>
            <input
              id={inputId}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              aria-describedby={helpId}
              className="mt-1 w-64 max-w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={busy || !code}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Unlock
          </button>
          <p id={helpId} className="w-full text-[11px] text-slate-500">
            The code is the contents of the <code>setup_code</code> file in this installation's
            secrets folder.
          </p>
        </form>
      )}

      {state && !state.configured && (
        <p className="mt-2 text-[11px] text-slate-500">
          Start NextUp again with its launcher to generate one.
        </p>
      )}

      {state?.active && (
        <button
          type="button"
          onClick={() => void lock()}
          disabled={busy}
          className="mt-3 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Lock
        </button>
      )}

      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </p>
      )}
    </section>
  );
}
