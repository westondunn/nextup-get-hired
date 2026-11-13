import { useEffect, useState } from 'react';
import { safeHref } from './safe';
import {
  type Workspace,
  type Pursuit,
  type Preferences,
  type Stage,
  type PursuitEvent,
  stages,
  closedStages,
  readWorkspace,
  savePreferences,
  buildPlan,
  updatePursuit,
  advanceStage,
  bulkUpdateStage,
  recordContact,
  readTimeline,
  addTimelineEvent,
  updateTimelineEvent,
  deleteTimelineEvent,
  announce,
} from './career-api';
import { type ResumeVersion, readResumes } from './evidence-api';
import StageSuggestions from './StageSuggestions';
import { type Communication, readCommunications, undoApplicationFromMail } from './contacts-api';
import { ThreadCard, groupThreads } from './MessageCard';

/* ---------- Structured Data Panels ---------- */

const PREP_SECTIONS = [
  {
    key: 'company_research',
    label: 'Company Research',
    placeholder: 'What does the company do? Recent news, funding, culture…',
  },
  {
    key: 'talking_points',
    label: 'Talking Points',
    placeholder: 'Key achievements and experiences to highlight…',
  },
  {
    key: 'star_examples',
    label: 'STAR Examples',
    placeholder: 'Situation, Task, Action, Result for behavioral questions…',
  },
  {
    key: 'questions_to_ask',
    label: 'Questions to Ask',
    placeholder: 'Questions about the role, team, growth…',
  },
  {
    key: 'logistics',
    label: 'Logistics',
    placeholder: 'Date, time, format (video/phone/onsite), interviewer name…',
  },
] as const;

const OFFER_FIELDS = [
  { key: 'base_salary', label: 'Base Salary', placeholder: 'e.g. annual base' },
  { key: 'equity', label: 'Equity / RSUs', placeholder: 'e.g. equity grant and vesting' },
  { key: 'signing_bonus', label: 'Signing Bonus', placeholder: 'e.g. one-time amount' },
  { key: 'benefits', label: 'Benefits Summary', placeholder: 'e.g. health, retirement, other' },
  { key: 'pto', label: 'PTO', placeholder: 'Unlimited / 20 days' },
  { key: 'start_date', label: 'Start Date', placeholder: 'YYYY-MM-DD' },
  { key: 'deadline', label: 'Decision Deadline', placeholder: 'YYYY-MM-DD' },
] as const;

function InterviewPrepPanel({
  data,
  onChange,
}: {
  data: Record<string, string>;
  onChange: (d: Record<string, string>) => void;
}) {
  return (
    <div className="mb-4 rounded-lg border-2 border-blue-200 bg-blue-50 p-4">
      <h4 className="text-sm font-semibold text-blue-800">Interview Prep</h4>
      <p className="mt-1 text-xs text-blue-600">
        Prepare three specific examples. Confirm the interview time and format.
      </p>
      <div className="mt-3 space-y-3">
        {PREP_SECTIONS.map(({ key, label, placeholder }) => (
          <label key={key} className="block text-sm">
            <span className="font-medium text-blue-700">{label}</span>
            <textarea
              rows={3}
              value={data[key] ?? ''}
              onChange={(e) => onChange({ ...data, [key]: e.target.value })}
              placeholder={placeholder}
              className="mt-1 block w-full rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function OfferDetailsPanel({
  data,
  onChange,
}: {
  data: Record<string, string>;
  onChange: (d: Record<string, string>) => void;
}) {
  return (
    <div className="mb-4 rounded-lg border-2 border-amber-200 bg-amber-50 p-4">
      <h4 className="text-sm font-semibold text-amber-800">Offer Details</h4>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {OFFER_FIELDS.map(({ key, label, placeholder }) => (
          <label key={key} className="block text-sm">
            <span className="font-medium text-amber-700">{label}</span>
            <input
              value={data[key] ?? ''}
              onChange={(e) => onChange({ ...data, [key]: e.target.value })}
              placeholder={placeholder}
              className="mt-1 block w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function TimelineEventRow({
  ev,
  pursuitId,
  onReload,
}: {
  ev: PursuitEvent;
  pursuitId: string;
  onReload: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState(ev.message);
  const [evDate, setEvDate] = useState(ev.event_date ?? '');
  const [actor, setActor] = useState(ev.actor);
  const [source, setSource] = useState(ev.source);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await updateTimelineEvent(pursuitId, ev.id, {
        message: msg,
        event_date: evDate || null,
        actor,
        source,
      });
      setEditing(false);
      await onReload();
    } catch (err) {
      console.error('Action failed:', err);
    }
    setBusy(false);
  }

  async function remove() {
    if (!confirm('Delete this event?')) return;
    setBusy(true);
    try {
      await deleteTimelineEvent(pursuitId, ev.id);
      await onReload();
    } catch (err) {
      console.error('Action failed:', err);
    }
    setBusy(false);
  }

  if (editing) {
    return (
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-2.5">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <input
            value={evDate}
            onChange={(e) => setEvDate(e.target.value)}
            type="date"
            className="rounded border border-slate-300 px-2 py-1 text-xs"
          />
          <input
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            placeholder="Who"
            className="rounded border border-slate-300 px-2 py-1 text-xs"
          />
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="Source"
            className="rounded border border-slate-300 px-2 py-1 text-xs"
          />
          <input
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
            placeholder="What happened"
            className="rounded border border-slate-300 px-2 py-1 text-xs sm:col-span-2"
          />
        </div>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void save()}
            className="rounded bg-slate-900 px-2 py-1 text-[10px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="rounded border border-slate-300 px-2 py-1 text-[10px] font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void remove()}
            className="rounded border border-red-200 px-2 py-1 text-[10px] font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex gap-3 rounded-lg border border-slate-100 bg-white p-2.5">
      <div className="shrink-0 text-right" style={{ minWidth: '5rem' }}>
        <p className="text-xs font-medium text-slate-700">
          {ev.event_date || new Date(ev.created_at).toLocaleDateString()}
        </p>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-slate-900">{ev.message}</p>
        {(ev.actor || ev.source) && (
          <p className="mt-0.5 text-[10px] text-slate-500">
            {[ev.actor, ev.source].filter(Boolean).join(' · ')}
          </p>
        )}
        {ev.evidence && <p className="mt-0.5 text-[10px] text-slate-400">{ev.evidence}</p>}
        {ev.attachments && ev.attachments.length > 0 && (
          <div className="mt-1">
            {ev.attachments.map((att, i) => (
              <details key={i} className="mt-1 rounded border border-slate-100 bg-slate-50 p-1.5">
                <summary className="cursor-pointer text-[10px] font-medium text-slate-600">
                  {att.label || att.kind} {att.content ? `(${att.content.length} chars)` : ''}
                </summary>
                {att.content && (
                  <p className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap text-[10px] text-slate-600">
                    {att.content}
                  </p>
                )}
                {att.url && (
                  <a
                    href={safeHref(att.url)}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 text-[10px] text-blue-600 underline"
                  >
                    {att.url}
                  </a>
                )}
              </details>
            ))}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="shrink-0 self-start rounded px-1.5 py-0.5 text-[10px] text-slate-400 opacity-0 transition-opacity hover:bg-slate-100 hover:text-slate-600 group-hover:opacity-100"
      >
        Edit
      </button>
    </div>
  );
}

function PursuitEditor({ item, refresh }: { item: Pursuit; refresh: () => Promise<void> }) {
  const [stage, setStage] = useState(item.stage);
  const [notes, setNotes] = useState(item.notes);
  const [application, setApplication] = useState(item.application_draft);
  const [outreach, setOutreach] = useState(item.outreach_draft);
  const [due, setDue] = useState(item.next_action_on ?? '');
  const [prepData, setPrepData] = useState<Record<string, string>>(item.prep_data ?? {});
  const [offerData, setOfferData] = useState<Record<string, string>>(item.offer_data ?? {});
  const [resumeId, setResumeId] = useState(item.resume_version_id ?? '');
  const [resumes, setResumes] = useState<ResumeVersion[]>([]);
  const [mail, setMail] = useState<Communication[]>([]);
  const [contact, setContact] = useState('');
  const [events, setEvents] = useState<PursuitEvent[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const [showAddEvent, setShowAddEvent] = useState(false);
  const [evMsg, setEvMsg] = useState('');
  const [evDate, setEvDate] = useState('');
  const [evActor, setEvActor] = useState('');
  const [evSource, setEvSource] = useState('');
  const [evAttachContent, setEvAttachContent] = useState('');
  const [evAttachLabel, setEvAttachLabel] = useState('');

  async function loadTimeline() {
    try {
      setEvents(await readTimeline(item.id));
    } catch (err) {
      console.error('Action failed:', err);
      setError('Timeline unavailable.');
    }
  }

  async function loadMail() {
    try {
      setMail(await readCommunications({ pursuit_id: item.id }));
    } catch (err) {
      console.error('Action failed:', err);
    }
  }

  // The confirmation email that created this application or moved it to applied.
  const detectedFrom = mail.find(
    (m) => m.detection?.applied?.created_pursuit || m.detection?.applied?.previous_stage,
  );

  async function undoDetected() {
    if (!detectedFrom?.detection?.applied) return;
    const created = detectedFrom.detection.applied.created_pursuit;
    if (
      !window.confirm(
        created
          ? 'Remove this application? It was created from a confirmation email; the message goes back to the review queue on Contacts.'
          : `Move this application back to ${detectedFrom.detection.applied.previous_stage}? The confirmation email goes back to the review queue on Contacts.`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await undoApplicationFromMail(detectedFrom.id);
      announce();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not undo.');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    readTimeline(item.id)
      .then((result) => active && setEvents(result))
      .catch(() => active && setError('Timeline unavailable.'));
    readCommunications({ pursuit_id: item.id })
      .then((rows) => active && setMail(rows))
      .catch((err) => console.error('Action failed:', err));
    return () => {
      active = false;
    };
  }, [item.id, item.version]);

  useEffect(() => {
    let active = true;
    readResumes()
      .then((rows) => active && setResumes(rows))
      .catch((err) => console.error('Action failed:', err));
    return () => {
      active = false;
    };
  }, []);

  async function save() {
    setBusy(true);
    setError('');
    try {
      await updatePursuit(item.id, {
        version: item.version,
        stage,
        notes,
        application_draft: application,
        outreach_draft: outreach,
        next_action_on: due || null,
        prep_data: prepData,
        offer_data: offerData,
        resume_version_id: resumeId || null,
      });
      await refresh();
      setMessage('Saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  }

  async function handleContact() {
    setBusy(true);
    setError('');
    try {
      await recordContact(item.id, item.version, contact.trim());
      await refresh();
      setContact('');
      setMessage('Contact recorded.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not record contact.');
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setMessage('Copied to clipboard.');
    } catch (err) {
      console.error('Action failed:', err);
      setError('Clipboard unavailable.');
    }
  }

  const dirty =
    stage !== item.stage ||
    notes !== item.notes ||
    application !== item.application_draft ||
    outreach !== item.outreach_draft ||
    due !== (item.next_action_on ?? '') ||
    resumeId !== (item.resume_version_id ?? '') ||
    JSON.stringify(prepData) !== JSON.stringify(item.prep_data ?? {}) ||
    JSON.stringify(offerData) !== JSON.stringify(item.offer_data ?? {});

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">{item.job.title}</h3>
          <p className="text-sm text-slate-500">
            {item.job.company} · {item.job.location}
          </p>
          {item.job.score != null && (
            <p className="mt-1 text-sm text-emerald-600">Match score: {item.job.score}/100</p>
          )}
          {(item.created_by === 'email' || detectedFrom) && (
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800">
                {item.created_by === 'email' ? 'Created from email' : 'Marked applied from email'}
              </span>
              {detectedFrom && (
                <>
                  <span>
                    {detectedFrom.subject || '(no subject)'} ·{' '}
                    {new Date(
                      detectedFrom.received_at || detectedFrom.created_at,
                    ).toLocaleDateString()}
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void undoDetected()}
                    className="rounded-md border border-slate-300 px-2 py-0.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    Undo
                  </button>
                </>
              )}
            </p>
          )}
        </div>
        {/^https?:\/\//i.test(item.job.url) && (
          <a
            href={safeHref(item.job.url)}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Open listing ↗
          </a>
        )}
      </div>

      {/* Quick Apply Panel */}
      {(item.stage === 'review' || item.stage === 'preparing') && (
        <div className="mb-4 rounded-lg border-2 border-emerald-200 bg-emerald-50 p-4">
          <h4 className="text-sm font-semibold text-emerald-800">Quick Apply</h4>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <p className="text-xs font-medium text-emerald-700">Application Draft</p>
              <p className="mt-1 max-h-24 overflow-y-auto text-xs text-slate-700 whitespace-pre-wrap">
                {application.slice(0, 300)}
                {application.length > 300 ? '…' : ''}
              </p>
              <button
                type="button"
                onClick={() => void copy(application)}
                className="mt-2 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
              >
                Copy Application
              </button>
            </div>
            <div>
              <p className="text-xs font-medium text-emerald-700">Outreach Draft</p>
              <p className="mt-1 max-h-24 overflow-y-auto text-xs text-slate-700 whitespace-pre-wrap">
                {outreach.slice(0, 300)}
                {outreach.length > 300 ? '…' : ''}
              </p>
              <button
                type="button"
                onClick={() => void copy(outreach)}
                className="mt-2 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
              >
                Copy Outreach
              </button>
            </div>
          </div>
          {/* Quality check */}
          {(() => {
            const placeholders = (application + ' ' + outreach).match(/\[[^\]]+\]/g);
            if (placeholders && placeholders.length > 0) {
              return (
                <div className="mt-2 rounded-md bg-amber-100 p-2 text-xs text-amber-800">
                  Draft has {placeholders.length} placeholder{placeholders.length > 1 ? 's' : ''}:{' '}
                  {placeholders.slice(0, 3).join(', ')}
                  {placeholders.length > 3 ? '…' : ''}. Edit before applying.
                </div>
              );
            }
            return null;
          })()}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {/^https?:\/\//i.test(item.job.url) && (
              <a
                href={safeHref(item.job.url)}
                target="_blank"
                rel="noreferrer"
                className="rounded-md border border-emerald-300 px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100"
              >
                Open Listing ↗
              </a>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError('');
                try {
                  await advanceStage({ ...item, stage: 'preparing' });
                  await refresh();
                  setMessage('Marked as applied.');
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Failed.');
                } finally {
                  setBusy(false);
                }
              }}
              className="rounded-md bg-slate-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              I Applied →
            </button>
          </div>
        </div>
      )}

      {/* Interview Prep Panel */}
      {item.stage === 'interview' && <InterviewPrepPanel data={prepData} onChange={setPrepData} />}

      {/* Offer Details Panel */}
      {item.stage === 'offer' && <OfferDetailsPanel data={offerData} onChange={setOfferData} />}

      {item.checks.length > 0 && (
        <ul className="mb-4 list-inside list-disc text-sm text-slate-600">
          {item.checks.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}

      <fieldset disabled={busy} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Stage</span>
            <select
              value={stage}
              onChange={(e) => {
                const v = e.target.value as Stage;
                setStage(v);
                if (v === 'applied' && item.stage !== 'applied') setDue('');
              }}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              {stages.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-medium text-slate-700">Next action date</span>
            <input
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="font-medium text-slate-700">Resume submitted</span>
            <select
              value={resumeId}
              onChange={(e) => setResumeId(e.target.value)}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Not recorded</option>
              {resumes
                .filter((r) => r.is_active || r.id === item.resume_version_id)
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.variant_name} v{r.version_number}
                    {r.file ? ` · ${r.file.name}` : ' · no file'}
                  </option>
                ))}
            </select>
            <span className="mt-1 block text-xs text-slate-500">
              Which variant went to this employer. Upload files on the Evidence page.
            </span>
          </label>
        </div>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Notes</span>
          <textarea
            rows={3}
            maxLength={12000}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-slate-700">
            Application &amp; outreach drafts
          </summary>
          <div className="mt-3 space-y-3">
            <label className="block text-sm">
              <span className="text-slate-600">Application draft</span>
              <textarea
                rows={6}
                maxLength={16000}
                value={application}
                onChange={(e) => setApplication(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <button
              type="button"
              onClick={() => void copy(application)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              Copy application draft
            </button>
            <label className="block text-sm">
              <span className="text-slate-600">Outreach draft</span>
              <textarea
                rows={4}
                maxLength={16000}
                value={outreach}
                onChange={(e) => setOutreach(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <button
              type="button"
              onClick={() => void copy(outreach)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              Copy outreach draft
            </button>
            {item.applied_at && (
              <>
                <label className="block text-sm">
                  <span className="text-slate-600">Follow-up draft</span>
                  <textarea
                    rows={4}
                    readOnly
                    value={item.follow_up_draft}
                    className="mt-1 block w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void copy(item.follow_up_draft)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Copy follow-up draft
                </button>
              </>
            )}
          </div>
        </details>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void save()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Save progress
          </button>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Reload saved
          </button>
        </div>

        {!closedStages.has(item.stage) && (
          <details>
            <summary className="cursor-pointer text-sm font-medium text-slate-700">
              Record a message you sent
            </summary>
            <div className="mt-3 flex gap-3">
              <input
                maxLength={400}
                placeholder="Who you contacted and what you sent"
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                type="button"
                disabled={!contact.trim() || dirty}
                onClick={() => void handleContact()}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                Record
              </button>
            </div>
            {dirty && <p className="mt-1 text-xs text-slate-500">Save edits first.</p>}
          </details>
        )}
      </fieldset>

      {message && <p className="mt-3 text-sm text-emerald-600">{message}</p>}
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      {mail.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-700">Correspondence ({mail.length})</h4>
          <p className="mt-0.5 text-xs text-slate-500">
            Messages and events linked to this application, shown in full and grouped by thread.
            Draft a reply here, send it from your mail client, then log it as sent.
          </p>
          <div className="mt-2 space-y-2">
            {groupThreads(mail).map((thread) => (
              <ThreadCard
                key={thread[0].id}
                messages={thread}
                reply={{
                  onDone: () => {
                    void loadMail();
                    void loadTimeline();
                    setMessage('Reply recorded.');
                  },
                }}
              />
            ))}
          </div>
        </div>
      )}

      {/* Timeline */}
      <div className="mt-4">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold text-slate-700">Timeline ({events.length})</h4>
          <button
            type="button"
            onClick={() => setShowAddEvent(!showAddEvent)}
            className="text-xs font-medium text-slate-500 hover:text-slate-700"
          >
            {showAddEvent ? 'Cancel' : '+ Add Event'}
          </button>
        </div>

        {showAddEvent && (
          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-xs text-slate-500">Record a past event with its actual date.</p>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <input
                value={evDate}
                onChange={(e) => setEvDate(e.target.value)}
                type="date"
                placeholder="When"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                value={evActor}
                onChange={(e) => setEvActor(e.target.value)}
                placeholder="Who (e.g., recruiter name)"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                value={evSource}
                onChange={(e) => setEvSource(e.target.value)}
                placeholder="Source (e.g., email, call, meeting)"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                value={evMsg}
                onChange={(e) => setEvMsg(e.target.value)}
                placeholder="What happened"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm sm:col-span-2"
              />
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-xs font-medium text-slate-500">
                Attach transcript or note
              </summary>
              <div className="mt-2 space-y-2">
                <input
                  value={evAttachLabel}
                  onChange={(e) => setEvAttachLabel(e.target.value)}
                  placeholder="Label (e.g., Interview transcript, Meeting notes)"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <textarea
                  value={evAttachContent}
                  onChange={(e) => setEvAttachContent(e.target.value)}
                  rows={4}
                  placeholder="Paste transcript, summary, or notes…"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
            </details>
            <button
              type="button"
              disabled={busy || !evMsg.trim() || !evDate}
              onClick={async () => {
                setBusy(true);
                const attachments = evAttachContent.trim()
                  ? [
                      {
                        kind: 'transcript',
                        label: evAttachLabel || 'Attachment',
                        content: evAttachContent,
                        url: '',
                      },
                    ]
                  : [];
                try {
                  await addTimelineEvent(item.id, {
                    message: evMsg.trim(),
                    event_date: evDate,
                    actor: evActor,
                    source: evSource,
                    attachments,
                  });
                  setEvMsg('');
                  setEvDate('');
                  setEvActor('');
                  setEvSource('');
                  setEvAttachContent('');
                  setEvAttachLabel('');
                  setShowAddEvent(false);
                  await loadTimeline();
                  setMessage('Event added.');
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Failed.');
                }
                setBusy(false);
              }}
              className="mt-2 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Add to Timeline
            </button>
          </div>
        )}

        {events.length > 0 && (
          <div className="mt-3 space-y-2">
            {events.map((ev) => (
              <TimelineEventRow key={ev.id} ev={ev} pursuitId={item.id} onReload={loadTimeline} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ApplicationsView() {
  const [data, setData] = useState<Workspace | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [selected, setSelected] = useState('');
  const [editing, setEditing] = useState<Pursuit | null>(null);
  const [filter, setFilter] = useState('active');
  const [sortBy, setSortBy] = useState<'default' | 'score' | 'due' | 'updated'>('default');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [batchMode, setBatchMode] = useState(false);
  const [batchIndex, setBatchIndex] = useState(0);
  const [showCompare, setShowCompare] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  async function refresh(resetEditor = false) {
    const next = await readWorkspace();
    setData(next);
    setPrefs((c) => c ?? next.preferences);
    if (resetEditor) {
      setEditing((c) => next.items.find((r) => r.id === c?.id) ?? null);
      setMessage('Loaded from saved records.');
    }
    setError('');
  }

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const next = await readWorkspace();
        if (active) {
          setData(next);
          setPrefs((c) => c ?? next.preferences);
          setError('');
        }
      } catch (err) {
        console.error('Action failed:', err);
        if (active) setError('Pipeline unavailable. Check the API.');
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 30000);
    const changed = () => void poll();
    window.addEventListener('nextup:pursuits', changed);
    return () => {
      active = false;
      clearInterval(timer);
      window.removeEventListener('nextup:pursuits', changed);
    };
  }, []);

  async function handleSavePrefs() {
    if (!prefs) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const next = await savePreferences(prefs);
      setData(next);
      setPrefs(next.preferences);
      setMessage('Goals saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  }

  async function handleBuild() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await buildPlan();
      await refresh();
      announce();
      setMessage(
        result.status === 'not_configured'
          ? 'Save goals first.'
          : result.status === 'profile_required'
            ? 'Save your profile and discovery settings first.'
            : `${result.added} new opportunities added.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not build plan.');
    } finally {
      setBusy(false);
    }
  }

  function choose(item: Pursuit) {
    setSelected(item.id);
    setEditing(item);
  }

  const q = searchQuery.toLowerCase().trim();
  const filtered =
    data?.items.filter(
      (row) =>
        (filter === 'all' ||
          (filter === 'active' ? !closedStages.has(row.stage) : row.stage === filter)) &&
        (!q || `${row.job.title} ${row.job.company} ${row.job.location}`.toLowerCase().includes(q)),
    ) ?? [];
  const visible = [...filtered].sort((a, b) => {
    if (sortBy === 'score') return (b.job.score ?? 0) - (a.job.score ?? 0);
    if (sortBy === 'due') return (a.next_action_on ?? 'z').localeCompare(b.next_action_on ?? 'z');
    if (sortBy === 'updated') return b.updated_at.localeCompare(a.updated_at);
    return 0;
  });

  function exportCsv() {
    if (!data) return;
    const header = [
      'Title',
      'Company',
      'Location',
      'Stage',
      'Score',
      'Next Action',
      'Applied At',
      'Updated At',
      'URL',
    ];
    const rows = data.items.map((r) => [
      r.job.title,
      r.job.company,
      r.job.location,
      r.stage,
      String(r.job.score ?? ''),
      r.next_action_on ?? '',
      r.applied_at ?? '',
      r.updated_at,
      r.job.url,
    ]);
    const escape = (v: string) => `"${v.replace(/"/g, '""')}"`;
    const csv = [header, ...rows].map((r) => r.map(escape).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pipeline-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-slate-900">Application Pipeline</h2>
        {data && (
          <button
            type="button"
            onClick={exportCsv}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Export CSV
          </button>
        )}
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Track opportunities from discovery to offer. Prepare applications and record your progress.
      </p>

      <StageSuggestions
        onChanged={() => {
          announce();
          void refresh(true);
        }}
      />

      {error && <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {!data && !error && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {data && prefs && (
        <>
          {/* Metrics bar */}
          <div className="mt-6 flex flex-wrap gap-6">
            {(
              [
                ['Preparing', data.counts.review + data.counts.preparing],
                ['Applied', data.counts.applied],
                ['Interviewing', data.counts.interview],
                ['Offers', data.counts.offer],
              ] as const
            ).map(([label, count]) => (
              <div key={label} className="text-center">
                <p className="text-2xl font-bold text-slate-900">{count}</p>
                <p className="text-xs text-slate-500">{label}</p>
              </div>
            ))}
          </div>

          {/* Daily plan */}
          {data.plan.length > 0 && (
            <div className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
              <h3 className="text-sm font-semibold text-emerald-800">Due today</h3>
              <ul className="mt-2 space-y-2">
                {data.plan.map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      onClick={() => choose(row)}
                      className="w-full rounded-lg bg-white p-3 text-left shadow-sm hover:bg-emerald-50"
                    >
                      <p className="text-sm font-medium text-slate-900">
                        {row.job.company}: {row.job.title}
                      </p>
                      <p className="text-xs text-slate-500">
                        {row.next_action} · Due {row.next_action_on}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setChecked(new Set());
              }}
              placeholder="Search title, company, location…"
              className="w-48 rounded-lg border border-slate-300 px-3 py-2 text-sm placeholder:text-slate-400"
            />
            <button
              type="button"
              disabled={busy || !data.ready}
              onClick={() => void handleBuild()}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? 'Working…' : "Build today's plan"}
            </button>
            <select
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setChecked(new Set());
              }}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="active">Active</option>
              <option value="all">All stages</option>
              {stages.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="default">Default order</option>
              <option value="score">Highest score</option>
              <option value="due">Due date</option>
              <option value="updated">Recently updated</option>
            </select>
            <button
              type="button"
              onClick={() => {
                setBatchMode(!batchMode);
                setBatchIndex(0);
              }}
              className={`rounded-lg px-4 py-2 text-sm font-medium ${batchMode ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'border border-slate-300 text-slate-700 hover:bg-slate-50'}`}
            >
              {batchMode ? 'Exit Batch Mode' : 'Batch Apply'}
            </button>
          </div>

          {/* Bulk action bar */}
          {checked.size > 0 && (
            <div className="mt-3 flex items-center gap-3 rounded-lg bg-slate-100 p-3">
              <span className="text-sm font-medium text-slate-700">{checked.size} selected</span>
              <button
                type="button"
                disabled={bulkBusy}
                onClick={async () => {
                  setBulkBusy(true);
                  const items = visible.filter((r) => checked.has(r.id));
                  const result = await bulkUpdateStage(items, 'dismissed');
                  setChecked(new Set());
                  await refresh();
                  setMessage(
                    `Dismissed ${result.succeeded}${result.skipped ? `, ${result.skipped} skipped` : ''}.`,
                  );
                  announce();
                  setBulkBusy(false);
                }}
                className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {bulkBusy ? 'Working…' : 'Dismiss Selected'}
              </button>
              <button
                type="button"
                disabled={bulkBusy}
                onClick={async () => {
                  setBulkBusy(true);
                  const items = visible.filter((r) => checked.has(r.id));
                  let succeeded = 0;
                  let failed = 0;
                  for (const item of items) {
                    try {
                      await advanceStage(item);
                      succeeded++;
                    } catch {
                      failed++;
                    }
                  }
                  setChecked(new Set());
                  await refresh();
                  setMessage(`Advanced ${succeeded}${failed ? `, ${failed} failed` : ''}.`);
                  announce();
                  setBulkBusy(false);
                }}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {bulkBusy ? 'Working…' : 'Advance Selected'}
              </button>
              {checked.size >= 2 && checked.size <= 5 && (
                <button
                  type="button"
                  onClick={() => setShowCompare(true)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Compare {checked.size}
                </button>
              )}
              <button
                type="button"
                onClick={() => setChecked(new Set())}
                className="text-xs text-slate-500 hover:text-slate-700"
              >
                Clear
              </button>
            </div>
          )}

          {/* Batch Apply Mode */}
          {batchMode ? (
            (() => {
              const preparing = visible.filter(
                (r) => r.stage === 'review' || r.stage === 'preparing',
              );
              const current = preparing[batchIndex];
              if (!preparing.length)
                return (
                  <p className="mt-4 text-sm text-slate-500">
                    No review/preparing items to batch process.
                  </p>
                );
              if (!current) {
                setBatchIndex(0);
                return null;
              }
              return (
                <div className="mt-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-700">
                      {batchIndex + 1} of {preparing.length}
                    </span>
                    <div className="h-2 flex-1 mx-4 rounded-full bg-slate-200">
                      <div
                        className="h-2 rounded-full bg-emerald-500 transition-all"
                        style={{ width: `${((batchIndex + 1) / preparing.length) * 100}%` }}
                      />
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                    <h3 className="text-lg font-semibold text-slate-900">{current.job.title}</h3>
                    <p className="text-sm text-slate-500">
                      {current.job.company} · {current.job.location}
                    </p>
                    {current.job.score != null && (
                      <p className="mt-1 text-sm text-emerald-600">
                        Match: {current.job.score}/100
                      </p>
                    )}
                    <p className="mt-3 max-h-32 overflow-y-auto text-sm text-slate-600 whitespace-pre-wrap">
                      {current.job.description?.slice(0, 500)}
                      {(current.job.description?.length ?? 0) > 500 ? '…' : ''}
                    </p>
                    {current.application_draft && (
                      <div className="mt-4 rounded-lg bg-slate-50 p-3">
                        <p className="text-xs font-medium text-slate-600">Application Draft</p>
                        <p className="mt-1 max-h-24 overflow-y-auto text-xs text-slate-700 whitespace-pre-wrap">
                          {current.application_draft.slice(0, 400)}
                        </p>
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(current.application_draft);
                            } catch (err) {
                              console.error('Action failed:', err);
                            }
                          }}
                          className="mt-2 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
                        >
                          Copy Draft
                        </button>
                      </div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-3">
                      {/^https?:\/\//i.test(current.job.url) && (
                        <a
                          href={safeHref(current.job.url)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                        >
                          Open Listing ↗
                        </a>
                      )}
                      <button
                        type="button"
                        disabled={busy}
                        onClick={async () => {
                          setBusy(true);
                          try {
                            await advanceStage({ ...current, stage: 'preparing' });
                            announce();
                            await refresh();
                            setBatchIndex((i) => Math.min(i, preparing.length - 2));
                          } catch (err) {
                            console.error('Action failed:', err);
                          }
                          setBusy(false);
                        }}
                        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                      >
                        I Applied →
                      </button>
                      <button
                        type="button"
                        onClick={() => setBatchIndex((i) => Math.min(i + 1, preparing.length - 1))}
                        className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        Skip
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={async () => {
                          setBusy(true);
                          try {
                            await updatePursuit(current.id, {
                              version: current.version,
                              stage: 'dismissed',
                              notes: current.notes,
                              application_draft: current.application_draft,
                              outreach_draft: current.outreach_draft,
                              next_action_on: current.next_action_on,
                            });
                            announce();
                            await refresh();
                            setBatchIndex((i) => Math.min(i, preparing.length - 2));
                          } catch (err) {
                            console.error('Action failed:', err);
                          }
                          setBusy(false);
                        }}
                        className="rounded-md border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                </div>
              );
            })()
          ) : (
            <>
              {/* Pipeline list */}
              <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {visible.map((row) => (
                  <div
                    key={row.id}
                    className={`flex items-start gap-2 rounded-xl border p-4 transition-colors ${
                      selected === row.id
                        ? 'border-slate-900 bg-slate-50'
                        : 'border-slate-200 bg-white hover:border-slate-300'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked.has(row.id)}
                      onChange={(e) => {
                        const next = new Set(checked);
                        if (e.target.checked) next.add(row.id);
                        else next.delete(row.id);
                        setChecked(next);
                      }}
                      className="mt-1 shrink-0 accent-slate-900"
                      onClick={(e) => e.stopPropagation()}
                    />
                    <button
                      type="button"
                      onClick={() => choose(row)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <p className="text-sm font-semibold text-slate-900">{row.job.title}</p>
                      <p className="text-xs text-slate-500">{row.job.company}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                          {row.stage}
                        </span>
                        {row.job.score != null && (
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${row.job.score >= 70 ? 'bg-emerald-100 text-emerald-700' : row.job.score >= 40 ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-600'}`}
                          >
                            {row.job.score}
                          </span>
                        )}
                        {row.next_action_on && (
                          <span className="text-xs text-slate-500">Next {row.next_action_on}</span>
                        )}
                      </div>
                    </button>
                  </div>
                ))}
              </div>
              {!visible.length && (
                <p className="mt-4 text-sm text-slate-500">No tracked jobs in this view.</p>
              )}
              {data.total > data.items.length && (
                <p className="mt-2 text-xs text-slate-500">
                  Showing {data.items.length} of {data.total} tracked jobs.
                </p>
              )}

              {/* Pursuit editor */}
              {editing && (
                <PursuitEditor
                  key={`${editing.id}:${editing.version}`}
                  item={editing}
                  refresh={() => refresh(true)}
                />
              )}
            </>
          )}

          {/* Preferences */}
          <details className="mt-8">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700">
              Income goals &amp; planning settings
            </summary>
            <div className="mt-4 space-y-4 rounded-xl border border-slate-200 bg-white p-5">
              <fieldset disabled={busy} className="space-y-4">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={prefs.automatic}
                    onChange={(e) => setPrefs({ ...prefs, automatic: e.target.checked })}
                    className="accent-slate-900"
                  />
                  Automatically prepare daily shortlist
                </label>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <label className="block text-sm">
                    <span className="font-medium text-slate-700">Daily target</span>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={prefs.daily_limit}
                      onChange={(e) => setPrefs({ ...prefs, daily_limit: Number(e.target.value) })}
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="font-medium text-slate-700">Follow-up days</span>
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={prefs.follow_up_days}
                      onChange={(e) =>
                        setPrefs({ ...prefs, follow_up_days: Number(e.target.value) })
                      }
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="font-medium text-slate-700">Timezone</span>
                    <input
                      value={prefs.timezone}
                      onChange={(e) => setPrefs({ ...prefs, timezone: e.target.value })}
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    />
                  </label>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <label className="block text-sm">
                    <span className="font-medium text-slate-700">Min annual pay (USD)</span>
                    <input
                      type="number"
                      min={1}
                      value={prefs.minimum_annual_usd ?? ''}
                      onChange={(e) =>
                        setPrefs({
                          ...prefs,
                          minimum_annual_usd: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="font-medium text-slate-700">Min hourly pay (USD)</span>
                    <input
                      type="number"
                      min={1}
                      value={prefs.minimum_hourly_usd ?? ''}
                      onChange={(e) =>
                        setPrefs({
                          ...prefs,
                          minimum_hourly_usd: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="font-medium text-slate-700">Start by</span>
                    <input
                      type="date"
                      value={prefs.start_by}
                      onChange={(e) => setPrefs({ ...prefs, start_by: e.target.value })}
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    />
                  </label>
                </div>
                <div className="flex flex-wrap gap-4 text-sm">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={prefs.open_to_contract}
                      onChange={(e) => setPrefs({ ...prefs, open_to_contract: e.target.checked })}
                      className="accent-slate-900"
                    />
                    Open to contract
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={prefs.open_to_individual_contributor}
                      onChange={(e) =>
                        setPrefs({ ...prefs, open_to_individual_contributor: e.target.checked })
                      }
                      className="accent-slate-900"
                    />
                    Open to IC roles
                  </label>
                </div>
                <label className="block text-sm">
                  <span className="font-medium text-slate-700">Verified achievements</span>
                  <textarea
                    rows={4}
                    maxLength={8000}
                    value={prefs.verified_achievements}
                    placeholder="Specific results you can substantiate."
                    onChange={(e) => setPrefs({ ...prefs, verified_achievements: e.target.value })}
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </label>
                <details className="mt-4">
                  <summary className="cursor-pointer text-sm font-medium text-slate-700">
                    Custom draft templates
                  </summary>
                  <p className="mt-2 text-xs text-slate-500">
                    Use placeholders: {'{company}'}, {'{title}'}, {'{location}'}, {'{skills}'},{' '}
                    {'{achievements}'}. Leave blank for defaults.
                  </p>
                  <label className="mt-3 block text-sm">
                    <span className="text-slate-600">Application template</span>
                    <textarea
                      rows={5}
                      maxLength={4000}
                      value={prefs.application_template}
                      placeholder={
                        'Hello {company} hiring team,\n\nI am interested in the {title} role.\n{skills}\n\n{achievements}\n\n[Your name]'
                      }
                      onChange={(e) => setPrefs({ ...prefs, application_template: e.target.value })}
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    />
                  </label>
                  <label className="mt-3 block text-sm">
                    <span className="text-slate-600">Outreach template</span>
                    <textarea
                      rows={4}
                      maxLength={4000}
                      value={prefs.outreach_template}
                      placeholder={
                        'Hello [contact name],\n\nI am exploring the {title} opportunity at {company}.\n{skills}\n\n[Your name]'
                      }
                      onChange={(e) => setPrefs({ ...prefs, outreach_template: e.target.value })}
                      className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    />
                  </label>
                </details>
                <button
                  type="button"
                  onClick={() => void handleSavePrefs()}
                  className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  Save goals
                </button>
              </fieldset>
            </div>
          </details>
        </>
      )}
      {message && <p className="mt-3 text-sm text-emerald-600">{message}</p>}

      {/* Comparison Modal */}
      {showCompare &&
        data &&
        (() => {
          const items = data.items.filter((r) => checked.has(r.id));
          if (items.length < 2) {
            setShowCompare(false);
            return null;
          }
          return (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
              onClick={() => setShowCompare(false)}
            >
              <div
                className="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-2xl bg-white p-6 shadow-xl"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold text-slate-900">Compare {items.length} Jobs</h2>
                  <button
                    type="button"
                    onClick={() => setShowCompare(false)}
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Close
                  </button>
                </div>
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
                        <th className="pb-2 pr-4 w-28">Attribute</th>
                        {items.map((i) => (
                          <th key={i.id} className="pb-2 pr-4">
                            {i.job.company}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="text-slate-700">
                      {(
                        [
                          ['Title', (i: Pursuit) => i.job.title],
                          ['Location', (i: Pursuit) => i.job.location],
                          ['Stage', (i: Pursuit) => i.stage],
                          [
                            'Match Score',
                            (i: Pursuit) => (i.job.score != null ? `${i.job.score}/100` : '—'),
                          ],
                          ['Next Action', (i: Pursuit) => i.next_action_on ?? 'None'],
                          [
                            'Applied',
                            (i: Pursuit) =>
                              i.applied_at ? new Date(i.applied_at).toLocaleDateString() : '—',
                          ],
                          [
                            'Work Modes',
                            (i: Pursuit) => (i.job.work_modes ?? []).join(', ') || '—',
                          ],
                        ] as [string, (i: Pursuit) => string][]
                      ).map(([label, fn]) => (
                        <tr key={label} className="border-b border-slate-100">
                          <td className="py-2 pr-4 text-xs font-medium text-slate-500">{label}</td>
                          {items.map((i) => (
                            <td key={i.id} className="py-2 pr-4">
                              {fn(i)}
                            </td>
                          ))}
                        </tr>
                      ))}
                      <tr className="border-b border-slate-100">
                        <td className="py-2 pr-4 text-xs font-medium text-slate-500">
                          Description
                        </td>
                        {items.map((i) => (
                          <td key={i.id} className="py-2 pr-4">
                            <p className="max-h-24 overflow-y-auto text-xs whitespace-pre-wrap">
                              {i.job.description?.slice(0, 300) ?? '—'}
                            </p>
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="py-2 pr-4 text-xs font-medium text-slate-500">Listing</td>
                        {items.map((i) => (
                          <td key={i.id} className="py-2 pr-4">
                            {/^https?:\/\//i.test(i.job.url) ? (
                              <a
                                href={safeHref(i.job.url)}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs text-slate-600 underline"
                              >
                                Open ↗
                              </a>
                            ) : (
                              '—'
                            )}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          );
        })()}
    </div>
  );
}
