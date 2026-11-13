import { useEffect, useState } from 'react';
import { safeHref } from './safe';
import { Plus, Search, Mail, Phone, ExternalLink, UserX } from 'lucide-react';
import {
  type Contact,
  type Communication,
  type StartStage,
  readContacts,
  createContact,
  updateContact,
  readCommunications,
  readReviewQueue,
  createCommunication,
  createApplicationFromMail,
  updateCommunication,
} from './contacts-api';
import { type Pursuit, closedStages, readWorkspace } from './career-api';
import { ClassifierBadge, MessageBody, ReplyComposer, groupThreads } from './MessageCard';
import StageSuggestions from './StageSuggestions';

const RELATIONSHIPS = [
  'unknown',
  'recruiter',
  'hiring_manager',
  'referral',
  'colleague',
  'mentor',
  'friend',
  'other',
];
const CHANNELS = ['email', 'linkedin', 'phone', 'in_person', 'other'];
const pursuitLabel = (p: Pursuit) => `${p.job.company} — ${p.job.title}`;

const START_STAGES: { value: StartStage; label: string }[] = [
  { value: 'review', label: 'Lead to review' },
  { value: 'preparing', label: 'Preparing to apply' },
  { value: 'applied', label: 'Already applied' },
  { value: 'interview', label: 'Interviewing' },
];

/**
 * Start an application from a queued message. Open for a detected confirmation,
 * behind a button for anything else, such as a recruiter's first message.
 */
function ApplicationPrompt({
  item,
  busy,
  onCreate,
}: {
  item: Communication;
  busy: boolean;
  onCreate: (company: string, title: string, stage: StartStage) => void;
}) {
  const confirmation = item.detection?.kind === 'application_confirmation';
  // Recruiters often put the client in brackets: "Sam [Acme] - Resume".
  const bracketed = /\[([^\]]{2,60})\]/.exec(item.subject)?.[1] ?? '';
  const [open, setOpen] = useState(confirmation);
  const [company, setCompany] = useState(item.detection?.company ?? bracketed);
  const [title, setTitle] = useState(item.detection?.title ?? '');
  const [stage, setStage] = useState<StartStage>(confirmation ? 'applied' : 'preparing');
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 rounded-md border border-emerald-300 px-3 py-1 text-xs font-medium text-emerald-800 hover:bg-emerald-50"
      >
        New application from this message…
      </button>
    );
  }
  return (
    <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50/60 p-2">
      <p className="text-xs text-emerald-900">
        {confirmation
          ? `This looks like an application confirmation${item.detection?.evidence ? ` (“${item.detection.evidence}”)` : ''}. Check the employer and role, then record it.`
          : 'Start tracking the role this message is about. The sender is added as a contact and the whole thread is linked.'}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          aria-label={`Employer for ${item.subject || '(no subject)'}`}
          placeholder="Employer"
          maxLength={200}
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          className="w-44 rounded-md border border-slate-300 px-2 py-1 text-xs"
        />
        <input
          aria-label={`Role for ${item.subject || '(no subject)'}`}
          placeholder="Role"
          maxLength={300}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="min-w-56 flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs"
        />
        <select
          aria-label={`Starting stage for ${item.subject || '(no subject)'}`}
          value={stage}
          onChange={(e) => setStage(e.target.value as StartStage)}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs"
        >
          {START_STAGES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={busy || !company.trim() || !title.trim()}
          onClick={() => onCreate(company.trim(), title.trim(), stage)}
          className="rounded-md bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-800 disabled:opacity-50"
        >
          Create application
        </button>
      </div>
    </div>
  );
}

function PursuitSelect({
  label,
  value,
  pursuits,
  suggestedId,
  onChange,
}: {
  label: string;
  value: string;
  pursuits: Pursuit[];
  suggestedId: string | null;
  onChange: (id: string) => void;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="max-w-xs rounded-md border border-slate-300 px-2 py-1 text-xs"
    >
      <option value="">No pursuit</option>
      {pursuits.map((p) => (
        <option key={p.id} value={p.id}>
          {pursuitLabel(p)}
          {p.id === suggestedId ? ' (suggested)' : ''}
        </option>
      ))}
    </select>
  );
}

const REL_BADGE: Record<string, string> = {
  recruiter: 'bg-blue-100 text-blue-700',
  hiring_manager: 'bg-purple-100 text-purple-700',
  referral: 'bg-emerald-100 text-emerald-700',
  colleague: 'bg-amber-100 text-amber-700',
  mentor: 'bg-indigo-100 text-indigo-700',
  friend: 'bg-pink-100 text-pink-700',
};

export default function ContactsView() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [comms, setComms] = useState<Communication[]>([]);
  const [queue, setQueue] = useState<Communication[]>([]);
  // Filters over the external classifier's hint; '' means any, 'disagrees' means Nextup disagrees.
  const [hintClass, setHintClass] = useState('');
  const [hintCompany, setHintCompany] = useState('');
  const [pursuits, setPursuits] = useState<Pursuit[]>([]);
  // Pursuit chosen per imported message; defaults to the sync's suggestion.
  const [pick, setPick] = useState<Record<string, string>>({});
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [openThreads, setOpenThreads] = useState<Set<string>>(new Set());
  const [searchQ, setSearchQ] = useState('');
  const [selected, setSelected] = useState<Contact | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [showAddComm, setShowAddComm] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  // Add contact
  const [cName, setCName] = useState('');
  const [cCompany, setCCompany] = useState('');
  const [cTitle, setCTitle] = useState('');
  const [cEmail, setCEmail] = useState('');
  const [cRelation, setCRelation] = useState('unknown');
  const [cNotes, setCNotes] = useState('');
  const [cIntro, setCIntro] = useState('');

  // Add comm
  const [mChannel, setMChannel] = useState('email');
  const [mDirection, setMDirection] = useState('outbound');
  const [mSubject, setMSubject] = useState('');
  const [mBody, setMBody] = useState('');
  const [mStatus, setMStatus] = useState('draft');

  async function load() {
    try {
      setContacts(await readContacts(searchQ || undefined));
      setError('');
    } catch {
      setError('Could not load contacts.');
    }
    try {
      setQueue(await readReviewQueue());
    } catch (err) {
      console.error('Action failed:', err);
    }
    try {
      setPursuits((await readWorkspace()).items);
    } catch (err) {
      console.error('Action failed:', err);
    }
  }

  const openPursuits = pursuits
    .filter((p) => !closedStages.has(p.stage))
    .sort((a, b) => pursuitLabel(a).localeCompare(pursuitLabel(b)));
  const chosenPursuit = (m: Communication) => {
    const chosen = pick[m.id] ?? m.suggested_pursuit_id ?? '';
    return openPursuits.some((p) => p.id === chosen) ? chosen : '';
  };

  async function linkQueued(
    item: Communication,
    changes: Record<string, unknown>,
    done = 'Imported message linked.',
  ) {
    setBusy(true);
    try {
      await updateCommunication(item.id, changes);
      await load();
      if (selected) await loadComms(selected.id);
      setMessage(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function createFromMail(
    item: Communication,
    company: string,
    title: string,
    stage: StartStage,
  ) {
    setBusy(true);
    try {
      const made = await createApplicationFromMail(item.id, { company, title, stage });
      await load();
      if (selected) await loadComms(selected.id);
      setMessage(
        made.created
          ? `Application created at ${made.stage}: ${made.title} at ${made.company}.`
          : `Linked to your ${made.company} application (${made.stage}).`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the application.');
    } finally {
      setBusy(false);
    }
  }

  async function loadComms(contactId: string) {
    try {
      setComms(await readCommunications({ contact_id: contactId }));
    } catch (err) {
      console.error('Action failed:', err);
    }
  }

  useEffect(() => {
    void load();
  }, [searchQ]);
  useEffect(() => {
    if (selected) void loadComms(selected.id);
  }, [selected?.id]);

  async function handleAdd() {
    setBusy(true);
    try {
      const c = await createContact({
        name: cName.trim(),
        company: cCompany || null,
        title: cTitle || null,
        email: cEmail || null,
        relationship: cRelation,
        notes: cNotes,
        introduced_by: cIntro || null,
      });
      setCName('');
      setCCompany('');
      setCTitle('');
      setCEmail('');
      setCRelation('unknown');
      setCNotes('');
      setCIntro('');
      setShowAdd(false);
      await load();
      setSelected(c);
      setMessage('Contact added.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleAddComm() {
    if (!selected) return;
    setBusy(true);
    try {
      await createCommunication({
        contact_id: selected.id,
        channel: mChannel,
        direction: mDirection,
        subject: mSubject,
        body: mBody,
        status: mStatus,
      });
      setMSubject('');
      setMBody('');
      setMStatus('draft');
      setShowAddComm(false);
      await loadComms(selected.id);
      await load();
      setMessage('Communication logged.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function markSent(commId: string) {
    setBusy(true);
    try {
      await updateCommunication(commId, { status: 'sent' });
      if (selected) await loadComms(selected.id);
      await load();
    } catch (err) {
      console.error('Action failed:', err);
    } finally {
      setBusy(false);
    }
  }

  const hintOf = (m: Communication) => m.detection?.classifier;
  const matchesHint = (m: Communication) =>
    (!hintClass ||
      (hintClass === 'disagrees'
        ? hintOf(m)?.agrees === false
        : hintClass === 'none'
          ? !hintOf(m)
          : hintOf(m)?.classification === hintClass)) &&
    (!hintCompany || hintOf(m)?.company_id === hintCompany);
  const shownQueue = queue.filter(matchesHint);
  const shownComms = comms.filter((m) => !hintClass || matchesHint(m));
  const hintCompanies = Array.from(
    new Map(
      [...queue, ...comms]
        .filter((m) => hintOf(m)?.company_id)
        .map((m) => [
          hintOf(m)!.company_id as string,
          m.classifier_company ?? hintOf(m)!.company_name ?? 'Unknown company',
        ]),
    ),
  ).sort((a, b) => a[1].localeCompare(b[1]));
  const anyHints = [...queue, ...comms].some((m) => hintOf(m));
  const hintFilters = anyHints && (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
      <label className="flex items-center gap-1">
        <span className="font-medium text-slate-600">Classifier verdict</span>
        <select
          value={hintClass}
          onChange={(e) => setHintClass(e.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1"
        >
          <option value="">Any</option>
          <option value="new_application">Application</option>
          <option value="opportunity">Opportunity</option>
          <option value="existing_company">Existing company</option>
          <option value="not_relevant">Not relevant</option>
          <option value="disagrees">Classifier disagrees with Nextup</option>
          <option value="none">Not classified</option>
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="font-medium text-slate-600">Classifier company</span>
        <select
          value={hintCompany}
          onChange={(e) => setHintCompany(e.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1"
        >
          <option value="">Any</option>
          {hintCompanies.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );

  return (
    <div className="space-y-6">
      <StageSuggestions onChanged={() => void load()} />
      {queue.length > 0 && (
        <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4">
          <h3 className="text-sm font-semibold text-slate-900">
            Imported mail awaiting review (
            {shownQueue.length === queue.length
              ? queue.length
              : `${shownQueue.length} of ${queue.length}`}
            )
          </h3>
          {hintFilters}
          <p className="mt-1 text-xs text-slate-500">
            Synced read-only from Gmail and Google Calendar. Link each item to a pursuit, to the
            selected contact, or to both at once, or dismiss what should not be tracked. Application
            confirmations can be recorded as applications here; they are only recorded automatically
            when that is turned on in Settings.
          </p>
          <div className="mt-3 space-y-2">
            {shownQueue.map((m) => (
              <div key={m.id} className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-slate-600">
                    <span className="mr-2 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                      {m.source === 'calendar' ? 'calendar' : 'email'}
                    </span>
                    {m.sender || 'Unknown sender'} <ClassifierBadge message={m} />
                  </span>
                  <span className="text-xs text-slate-400">
                    {new Date(m.received_at || m.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-sm font-medium text-slate-900">
                  {m.subject || '(no subject)'}
                </p>
                <MessageBody body={m.body} />
                {m.direction === 'inbound' && m.source === 'gmail' && (
                  <ApplicationPrompt
                    item={m}
                    busy={busy}
                    onCreate={(company, title, stage) =>
                      void createFromMail(m, company, title, stage)
                    }
                  />
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <PursuitSelect
                    label={`Pursuit for ${m.subject || '(no subject)'}`}
                    value={chosenPursuit(m)}
                    pursuits={openPursuits}
                    suggestedId={m.suggested_pursuit_id}
                    onChange={(id) => setPick((prev) => ({ ...prev, [m.id]: id }))}
                  />
                  <button
                    type="button"
                    disabled={busy || !chosenPursuit(m)}
                    onClick={() => void linkQueued(m, { pursuit_id: chosenPursuit(m) })}
                    className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    Link to pursuit
                  </button>
                  <button
                    type="button"
                    disabled={busy || !selected}
                    title={selected ? undefined : 'Select a contact first'}
                    onClick={() => selected && void linkQueued(m, { contact_id: selected.id })}
                    className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    Link to {selected ? selected.name : 'selected contact'}
                  </button>
                  <button
                    type="button"
                    disabled={busy || !selected || !chosenPursuit(m)}
                    title={
                      selected ? undefined : 'Select a contact and choose a pursuit to link both'
                    }
                    onClick={() =>
                      selected &&
                      void linkQueued(m, { contact_id: selected.id, pursuit_id: chosenPursuit(m) })
                    }
                    className="rounded-md border border-slate-900 px-3 py-1 text-xs font-medium text-slate-900 hover:bg-slate-100 disabled:opacity-50"
                  >
                    Link to both
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    title="Hide this import; it stays stored so a re-scan cannot bring it back"
                    onClick={() =>
                      void linkQueued(m, { status: 'dismissed' }, 'Imported message dismissed.')
                    }
                    className="ml-auto rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50 disabled:opacity-50"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Contact list */}
        <div className="lg:col-span-1">
          {error && (
            <div className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
          )}
          {message && (
            <div className="mb-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">
              {message}
            </div>
          )}

          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                placeholder="Search contacts…"
                className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm"
              />
            </div>
            <button
              type="button"
              onClick={() => setShowAdd(true)}
              className="rounded-lg bg-slate-900 p-2 text-white hover:bg-slate-800"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>

          {showAdd && (
            <div className="mt-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="space-y-2">
                <input
                  value={cName}
                  onChange={(e) => setCName(e.target.value)}
                  placeholder="Name *"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <input
                  value={cCompany}
                  onChange={(e) => setCCompany(e.target.value)}
                  placeholder="Company"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <input
                  value={cTitle}
                  onChange={(e) => setCTitle(e.target.value)}
                  placeholder="Title / Role"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <input
                  value={cEmail}
                  onChange={(e) => setCEmail(e.target.value)}
                  placeholder="Email"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <select
                  value={cRelation}
                  onChange={(e) => setCRelation(e.target.value)}
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  {RELATIONSHIPS.map((r) => (
                    <option key={r} value={r}>
                      {r.replace('_', ' ')}
                    </option>
                  ))}
                </select>
                <input
                  value={cIntro}
                  onChange={(e) => setCIntro(e.target.value)}
                  placeholder="Introduced by"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <textarea
                  value={cNotes}
                  onChange={(e) => setCNotes(e.target.value)}
                  rows={2}
                  placeholder="Notes"
                  className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  disabled={busy || !cName.trim()}
                  onClick={() => void handleAdd()}
                  className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  Add
                </button>
                <button
                  type="button"
                  onClick={() => setShowAdd(false)}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div className="mt-3 space-y-2">
            {contacts.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setSelected(c);
                  setShowAddComm(false);
                }}
                className={`w-full rounded-xl border p-3 text-left transition-colors ${selected?.id === c.id ? 'border-slate-900 bg-slate-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-slate-900">{c.name}</p>
                  {c.do_not_contact && <UserX className="h-4 w-4 text-red-500" />}
                </div>
                <p className="text-xs text-slate-500">
                  {[c.title, c.company].filter(Boolean).join(' · ') || 'No details'}
                </p>
                <div className="mt-1 flex gap-1">
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${REL_BADGE[c.relationship] ?? 'bg-slate-100 text-slate-600'}`}
                  >
                    {c.relationship.replace('_', ' ')}
                  </span>
                  {c.last_contacted_at && (
                    <span className="text-[10px] text-slate-400">
                      Last {new Date(c.last_contacted_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </button>
            ))}
            {!contacts.length && (
              <p className="py-4 text-center text-sm text-slate-500">No contacts yet.</p>
            )}
          </div>
        </div>

        {/* Contact detail + communications */}
        <div className="lg:col-span-2">
          {selected ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-bold text-slate-900">{selected.name}</h2>
                    <p className="text-sm text-slate-500">
                      {[selected.title, selected.company].filter(Boolean).join(' at ')}
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${REL_BADGE[selected.relationship] ?? 'bg-slate-100 text-slate-600'}`}
                  >
                    {selected.relationship.replace('_', ' ')}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
                  {selected.email && (
                    <span className="flex items-center gap-1">
                      <Mail className="h-3 w-3" /> {selected.email}
                    </span>
                  )}
                  {selected.phone && (
                    <span className="flex items-center gap-1">
                      <Phone className="h-3 w-3" /> {selected.phone}
                    </span>
                  )}
                  {selected.linkedin_url && (
                    <a
                      href={safeHref(selected.linkedin_url)}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 text-blue-600"
                    >
                      <ExternalLink className="h-3 w-3" /> LinkedIn
                    </a>
                  )}
                </div>
                {selected.introduced_by && (
                  <p className="mt-2 text-xs text-slate-500">
                    Introduced by: {selected.introduced_by}
                  </p>
                )}
                {selected.notes && <p className="mt-2 text-sm text-slate-600">{selected.notes}</p>}
                {selected.do_not_contact && (
                  <p className="mt-2 text-xs font-semibold text-red-600">Do not contact</p>
                )}
              </div>

              {/* Communications */}
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900">Communications</h3>
                <button
                  type="button"
                  onClick={() => setShowAddComm(true)}
                  className="flex items-center gap-1 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                >
                  <Plus className="h-3 w-3" /> Log Message
                </button>
              </div>

              {showAddComm && (
                <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <select
                      value={mChannel}
                      onChange={(e) => setMChannel(e.target.value)}
                      className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    >
                      {CHANNELS.map((c) => (
                        <option key={c} value={c}>
                          {c.replace('_', ' ')}
                        </option>
                      ))}
                    </select>
                    <select
                      value={mDirection}
                      onChange={(e) => setMDirection(e.target.value)}
                      className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    >
                      <option value="outbound">Outbound</option>
                      <option value="inbound">Inbound</option>
                      <option value="note">Private Note</option>
                    </select>
                    <select
                      value={mStatus}
                      onChange={(e) => setMStatus(e.target.value)}
                      className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    >
                      <option value="draft">Draft</option>
                      <option value="copied">Copied</option>
                      <option value="sent">Sent</option>
                      <option value="received">Received</option>
                      <option value="private_note">Private Note</option>
                    </select>
                  </div>
                  <input
                    value={mSubject}
                    onChange={(e) => setMSubject(e.target.value)}
                    placeholder="Subject"
                    className="mt-3 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                  <textarea
                    value={mBody}
                    onChange={(e) => setMBody(e.target.value)}
                    rows={4}
                    placeholder="Message body"
                    className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleAddComm()}
                      className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                    >
                      Log
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowAddComm(false)}
                      className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <div className="space-y-2">
                {groupThreads(shownComms).map((thread) => {
                  const key = thread[0].thread_id ?? thread[0].id;
                  const collapsed = thread.length > 1 && !openThreads.has(key);
                  const shown = collapsed ? thread.slice(-1) : thread;
                  const rows = shown.map((m) => (
                    <div key={m.id} className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span
                            className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${m.direction === 'inbound' ? 'bg-blue-100 text-blue-700' : m.direction === 'note' ? 'bg-slate-100 text-slate-600' : 'bg-emerald-100 text-emerald-700'}`}
                          >
                            {m.direction}
                          </span>
                          <span className="text-xs text-slate-500">{m.channel}</span>
                          <span
                            className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${m.status === 'sent' ? 'bg-emerald-100 text-emerald-700' : m.status === 'draft' ? 'bg-amber-100 text-amber-700' : m.status === 'received' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600'}`}
                          >
                            {m.status}
                          </span>
                        </div>
                        <span className="text-xs text-slate-400">
                          {new Date(m.created_at).toLocaleDateString()}
                        </span>
                      </div>
                      {m.subject && (
                        <p className="mt-1 text-sm font-medium text-slate-900">{m.subject}</p>
                      )}
                      <MessageBody body={m.body} />
                      {m.source !== 'manual' &&
                        (m.pursuit_id ? (
                          <p className="mt-1 text-[11px] text-slate-500">
                            Linked to {m.pursuit_company || 'a pursuit'}
                          </p>
                        ) : (
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <PursuitSelect
                              label={`Pursuit for ${m.subject || '(no subject)'}`}
                              value={chosenPursuit(m)}
                              pursuits={openPursuits}
                              suggestedId={m.suggested_pursuit_id}
                              onChange={(id) => setPick((prev) => ({ ...prev, [m.id]: id }))}
                            />
                            <button
                              type="button"
                              disabled={busy || !chosenPursuit(m)}
                              onClick={() => void linkQueued(m, { pursuit_id: chosenPursuit(m) })}
                              className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                            >
                              Link to pursuit
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                void linkQueued(
                                  m,
                                  { status: 'dismissed' },
                                  'Imported message dismissed.',
                                )
                              }
                              className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50 disabled:opacity-50"
                            >
                              Dismiss
                            </button>
                          </div>
                        ))}
                      {m.direction === 'inbound' && replyTo !== m.id && (
                        <button
                          type="button"
                          onClick={() => setReplyTo(m.id)}
                          className="mt-2 rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800"
                        >
                          Draft reply
                        </button>
                      )}
                      {replyTo === m.id && (
                        <ReplyComposer
                          message={m}
                          reply={{
                            onDone: () => {
                              setReplyTo(null);
                              if (selected) void loadComms(selected.id);
                              void load();
                              setMessage('Reply recorded.');
                            },
                          }}
                          onCancel={() => setReplyTo(null)}
                        />
                      )}
                      {m.status === 'draft' && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void markSent(m.id)}
                          className="mt-2 rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          Mark Sent
                        </button>
                      )}
                    </div>
                  ));
                  if (thread.length === 1) return rows;
                  return (
                    <div
                      key={key}
                      className="space-y-2 rounded-lg border border-blue-100 bg-blue-50/30 p-2"
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setOpenThreads((prev) => {
                            const next = new Set(prev);
                            if (next.has(key)) next.delete(key);
                            else next.add(key);
                            return next;
                          })
                        }
                        className="text-[11px] font-medium text-blue-700 hover:text-blue-900"
                      >
                        {collapsed
                          ? `Show ${thread.length - 1} earlier ${thread.length === 2 ? 'message' : 'messages'} in this thread`
                          : 'Hide earlier messages in this thread'}
                      </button>
                      {rows}
                    </div>
                  );
                })}
                {!comms.length && (
                  <p className="text-sm text-slate-500">No communications logged yet.</p>
                )}
              </div>
            </div>
          ) : (
            <div className="flex h-64 items-center justify-center rounded-xl border border-slate-200 bg-white">
              <p className="text-sm text-slate-500">
                Select a contact to see details and communications.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
