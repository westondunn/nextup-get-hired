import { useEffect, useState } from 'react';
import { type StageSuggestion, decideStageSuggestion, readStageSuggestions } from './contacts-api';
import { MessageBody } from './MessageCard';

/** Why a message suggests a stage, in the user's terms. */
export function suggestionSummary(s: StageSuggestion): string {
  return s.stage === 'rejected'
    ? `This reads like a rejection for ${s.title} at ${s.company}.`
    : `This reads like an interview for ${s.title} at ${s.company}.`;
}

/**
 * Imported mail and calendar events that point to a rejection or an interview.
 * Nothing changes until the user confirms; ignoring keeps the application as it is.
 */
export default function StageSuggestions({ onChanged }: { onChanged?: () => void }) {
  const [items, setItems] = useState<StageSuggestion[]>([]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  async function load() {
    try {
      setItems(await readStageSuggestions());
    } catch {
      // The pipeline works without suggestions; stay quiet when they cannot be read.
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function decide(s: StageSuggestion, decision: 'apply' | 'ignore') {
    setBusy(true);
    setError('');
    try {
      await decideStageSuggestion(s.communication.id, decision);
      setNote(
        decision === 'apply'
          ? `${s.company} — ${s.title} moved to ${s.stage}.` +
              (s.stage === 'interview' ? ' A preparation task was added to your plan.' : '')
          : `Left ${s.company} — ${s.title} at ${s.current_stage}.`,
      );
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not record that.');
    } finally {
      setBusy(false);
    }
  }

  if (items.length === 0 && !note && !error) return null;
  return (
    <section
      aria-label="Suggested stage changes"
      className="mt-4 rounded-xl border border-amber-200 bg-amber-50/50 p-4"
    >
      {items.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-slate-900">
            Suggested from your mail ({items.length})
          </h3>
          <p className="mt-1 text-xs text-slate-600">
            Read the message, then confirm the change or ignore it. Nothing moves on its own.
          </p>
        </>
      )}
      <div className="mt-2 space-y-2">
        {items.map((s) => {
          const m = s.communication;
          const shown = open.has(m.id);
          return (
            <div key={m.id} className="rounded-lg border border-slate-200 bg-white p-3">
              <p className="text-sm font-medium text-slate-900">{suggestionSummary(s)}</p>
              <p className="mt-0.5 text-xs text-slate-600">
                {m.source === 'calendar' ? 'Calendar event' : 'Email'} from{' '}
                {m.sender || 'unknown sender'} ·{' '}
                {new Date(m.received_at || m.created_at).toLocaleString()} ·{' '}
                {m.subject || '(no subject)'}
                {s.evidence ? ` · matched “${s.evidence}”` : ''}
              </p>
              {shown && <MessageBody body={m.body} />}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void decide(s, 'apply')}
                  className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  Move from {s.current_stage} to {s.stage}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void decide(s, 'ignore')}
                  className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Ignore
                </button>
                <button
                  type="button"
                  aria-expanded={shown}
                  onClick={() =>
                    setOpen((prev) => {
                      const next = new Set(prev);
                      if (next.has(m.id)) next.delete(m.id);
                      else next.add(m.id);
                      return next;
                    })
                  }
                  className="rounded-md px-2 py-1 text-xs font-medium text-blue-700 hover:underline"
                >
                  {shown ? 'Hide message' : 'Read message'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {note && <p className="mt-2 text-xs text-emerald-700">{note}</p>}
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </section>
  );
}
