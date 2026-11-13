import { useEffect, useState } from 'react';
import { Plus, Shield, FileText, Printer, Paperclip } from 'lucide-react';
import {
  type Evidence,
  type ResumeVersion,
  readEvidence,
  createEvidence,
  updateEvidence,
  readResumes,
  createResume,
  updateResume,
  uploadResumeFile,
  deleteResumeFile,
  resumeFileUrl,
} from './evidence-api';
import { composeWithEvidence, renderResumeHtml } from './resume-print';

const formatSize = (bytes: number) =>
  bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.ceil(bytes / 1000)} KB`;

/** The wording that may appear on a resume, in order of how carefully it was vetted. */
const bulletFor = (ev: Evidence) =>
  (ev.permitted_wording || ev.personal_contribution || ev.detail || ev.topic).trim();

function printResume(title: string, text: string): boolean {
  const popup = window.open('', '_blank');
  if (!popup) return false;
  popup.document.write(renderResumeHtml(title, text));
  popup.document.close();
  popup.focus();
  window.setTimeout(() => popup.print(), 250);
  return true;
}

const STATUS_BADGE: Record<string, string> = {
  confirmed: 'bg-emerald-100 text-emerald-700',
  needs_user_confirmation: 'bg-amber-100 text-amber-700',
  rejected: 'bg-red-100 text-red-700',
};

export default function EvidenceView() {
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [resumes, setResumes] = useState<ResumeVersion[]>([]);
  const [filterStatus, setFilterStatus] = useState('');
  const [editing, setEditing] = useState<Evidence | null>(null);
  const [editingResume, setEditingResume] = useState<ResumeVersion | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [showAddResume, setShowAddResume] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  // Add evidence form
  const [newTopic, setNewTopic] = useState('');
  const [newDetail, setNewDetail] = useState('');
  const [newSource, setNewSource] = useState('');
  const [newScope, setNewScope] = useState('');
  const [newDates, setNewDates] = useState('');
  const [newContribution, setNewContribution] = useState('');

  // Add resume form
  const [newVariant, setNewVariant] = useState('');
  const [newContent, setNewContent] = useState('');

  // Compose a tailored variant from an existing version plus confirmed evidence
  const [composeBase, setComposeBase] = useState<ResumeVersion | null>(null);
  const [composeName, setComposeName] = useState('');
  const [composeText, setComposeText] = useState('');
  const [composeEvidence, setComposeEvidence] = useState<Evidence[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  async function load() {
    try {
      const [ev, res] = await Promise.all([readEvidence(filterStatus || undefined), readResumes()]);
      setEvidence(ev);
      setResumes(res);
      setError('');
    } catch {
      setError('Could not load data.');
    }
  }

  useEffect(() => {
    void load();
  }, [filterStatus]);

  async function handleAddEvidence() {
    setBusy(true);
    try {
      await createEvidence({
        topic: newTopic.trim(),
        detail: newDetail,
        source: newSource || null,
        scope: newScope || null,
        dates: newDates || null,
        personal_contribution: newContribution,
      });
      setNewTopic('');
      setNewDetail('');
      setNewSource('');
      setNewScope('');
      setNewDates('');
      setNewContribution('');
      setShowAdd(false);
      await load();
      setMessage('Evidence added.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateEvidence(id: string, data: Record<string, unknown>) {
    setBusy(true);
    try {
      await updateEvidence(id, data);
      setEditing(null);
      await load();
      setMessage('Updated.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleUpload(resume: ResumeVersion, file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      await uploadResumeFile(resume.id, file);
      await load();
      setMessage(`Stored ${file.name} with ${resume.variant_name} v${resume.version_number}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleRemoveFile(resume: ResumeVersion) {
    setBusy(true);
    try {
      await deleteResumeFile(resume.id);
      await load();
      setMessage('File removed; the version and its text are kept.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  async function openComposer(base: ResumeVersion) {
    setComposeBase(base);
    setComposeName(base.variant_name);
    setComposeText(base.content);
    setPicked(new Set());
    try {
      setComposeEvidence(await readEvidence('confirmed'));
    } catch {
      setComposeEvidence([]);
    }
  }

  function insertPicked() {
    const bullets = composeEvidence.filter((ev) => picked.has(ev.id)).map(bulletFor);
    setComposeText(composeWithEvidence(composeText, bullets));
    setPicked(new Set());
  }

  async function saveComposed() {
    if (!composeBase) return;
    setBusy(true);
    try {
      const created = await createResume({
        variant_name: composeName.trim(),
        content: composeText,
        notes: `Composed from ${composeBase.variant_name} v${composeBase.version_number}`,
      });
      setComposeBase(null);
      await load();
      setMessage(
        `Saved ${created.variant_name} v${created.version_number}. Print it, then upload the PDF you send.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  function handlePrint(title: string, text: string) {
    if (!printResume(title, text)) setError('Allow pop-ups for this site to print a resume.');
  }

  async function handleAddResume() {
    setBusy(true);
    try {
      await createResume({ variant_name: newVariant.trim(), content: newContent });
      setNewVariant('');
      setNewContent('');
      setShowAddResume(false);
      await load();
      setMessage('Resume created.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      {error && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && (
        <div className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{message}</div>
      )}

      {/* Evidence Bank */}
      <div>
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900">
            <Shield className="h-5 w-5 text-emerald-600" /> Career Evidence
          </h2>
          <div className="flex gap-3">
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">All statuses</option>
              <option value="needs_user_confirmation">Needs confirmation</option>
              <option value="confirmed">Confirmed</option>
              <option value="rejected">Rejected</option>
            </select>
            <button
              type="button"
              onClick={() => setShowAdd(true)}
              className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
            >
              <Plus className="h-4 w-4" /> Add Evidence
            </button>
          </div>
        </div>

        {showAdd && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block text-xs sm:col-span-2">
                <span className="font-medium text-slate-600">Topic</span>
                <input
                  value={newTopic}
                  onChange={(e) => setNewTopic(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Source</span>
                <input
                  value={newSource}
                  onChange={(e) => setNewSource(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Scope</span>
                <input
                  value={newScope}
                  onChange={(e) => setNewScope(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs">
                <span className="font-medium text-slate-600">Dates</span>
                <input
                  value={newDates}
                  onChange={(e) => setNewDates(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs sm:col-span-2">
                <span className="font-medium text-slate-600">Personal contribution</span>
                <textarea
                  rows={3}
                  value={newContribution}
                  onChange={(e) => setNewContribution(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-xs sm:col-span-2">
                <span className="font-medium text-slate-600">Detail</span>
                <textarea
                  rows={3}
                  value={newDetail}
                  onChange={(e) => setNewDetail(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
            </div>
            <div className="mt-3 flex gap-3">
              <button
                type="button"
                disabled={busy || !newTopic.trim()}
                onClick={() => void handleAddEvidence()}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                Create
              </button>
              <button
                type="button"
                onClick={() => setShowAdd(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="mt-4 space-y-3">
          {evidence.map((ev) => (
            <div key={ev.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-slate-900">{ev.topic}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[ev.verification_status] ?? 'bg-slate-100 text-slate-600'}`}
                    >
                      {ev.verification_status.replace(/_/g, ' ')}
                    </span>
                    {ev.scope && <span className="text-xs text-slate-500">{ev.scope}</span>}
                    {ev.dates && <span className="text-xs text-slate-500">{ev.dates}</span>}
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  {ev.verification_status !== 'confirmed' && (
                    <button
                      type="button"
                      onClick={() =>
                        void handleUpdateEvidence(ev.id, { verification_status: 'confirmed' })
                      }
                      className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
                    >
                      Confirm
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setEditing(editing?.id === ev.id ? null : ev)}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    {editing?.id === ev.id ? 'Close' : 'Edit'}
                  </button>
                </div>
              </div>
              {ev.instruction && <p className="mt-2 text-xs text-amber-700">{ev.instruction}</p>}
              {ev.detail && <p className="mt-2 text-sm text-slate-600">{ev.detail}</p>}
              {ev.personal_contribution && (
                <p className="mt-1 text-xs text-slate-500">
                  Contribution: {ev.personal_contribution.slice(0, 200)}
                </p>
              )}
              {ev.permitted_wording && (
                <p className="mt-1 text-xs text-emerald-700">
                  Approved wording: {ev.permitted_wording.slice(0, 200)}
                </p>
              )}

              {editing?.id === ev.id && (
                <EvidenceEditor
                  evidence={ev}
                  onSave={(data) => void handleUpdateEvidence(ev.id, data)}
                  busy={busy}
                />
              )}
            </div>
          ))}
          {!evidence.length && <p className="text-sm text-slate-500">No evidence records yet.</p>}
        </div>
      </div>

      {/* Resume Versions */}
      <div>
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900">
            <FileText className="h-5 w-5 text-blue-600" /> Resume Variants
          </h2>
          <button
            type="button"
            onClick={() => setShowAddResume(true)}
            className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            <Plus className="h-4 w-4" /> New Variant
          </button>
        </div>

        {showAddResume && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <label className="block text-xs">
              <span className="font-medium text-slate-600">Variant name</span>
              <input
                value={newVariant}
                onChange={(e) => setNewVariant(e.target.value)}
                placeholder="e.g. Management roles"
                className="mt-1 block w-full max-w-sm rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="mt-3 block text-xs">
              <span className="font-medium text-slate-600">Content</span>
              <textarea
                rows={8}
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
              />
            </label>
            <div className="mt-3 flex gap-3">
              <button
                type="button"
                disabled={busy || !newVariant.trim()}
                onClick={() => void handleAddResume()}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                Create
              </button>
              <button
                type="button"
                onClick={() => setShowAddResume(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {composeBase && (
          <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50/40 p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-900">
              Compose from {composeBase.variant_name} v{composeBase.version_number}
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Tick confirmed evidence to add it as bullets, edit the text, save it as a new version,
              then print it to PDF and upload the file you actually send.
            </p>
            <label className="mt-3 block text-xs">
              <span className="font-medium text-slate-600">Variant name</span>
              <input
                value={composeName}
                onChange={(e) => setComposeName(e.target.value)}
                className="mt-1 block w-full max-w-sm rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className="lg:col-span-1">
                <p className="text-xs font-medium text-slate-600">Confirmed evidence</p>
                <div className="mt-1 max-h-72 space-y-1 overflow-y-auto rounded-lg border border-slate-200 bg-white p-2">
                  {composeEvidence.map((ev) => (
                    <label key={ev.id} className="flex items-start gap-2 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        checked={picked.has(ev.id)}
                        onChange={(e) => {
                          const next = new Set(picked);
                          if (e.target.checked) next.add(ev.id);
                          else next.delete(ev.id);
                          setPicked(next);
                        }}
                        className="mt-0.5"
                      />
                      <span>
                        <span className="font-medium">{ev.topic}</span>
                        <span className="block text-slate-500">{bulletFor(ev).slice(0, 140)}</span>
                      </span>
                    </label>
                  ))}
                  {!composeEvidence.length && (
                    <p className="text-xs text-slate-500">No confirmed evidence yet.</p>
                  )}
                </div>
                <button
                  type="button"
                  disabled={!picked.size}
                  onClick={insertPicked}
                  className="mt-2 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Insert {picked.size || ''} selected
                </button>
              </div>
              <label className="block text-xs lg:col-span-2">
                <span className="font-medium text-slate-600">
                  Resume text (# headings, - bullets)
                </span>
                <textarea
                  rows={16}
                  value={composeText}
                  onChange={(e) => setComposeText(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                />
              </label>
            </div>
            <div className="mt-3 flex flex-wrap gap-3">
              <button
                type="button"
                disabled={busy || !composeName.trim()}
                onClick={() => void saveComposed()}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                Save as new version
              </button>
              <button
                type="button"
                onClick={() => handlePrint(composeName || composeBase.variant_name, composeText)}
                className="flex items-center gap-2 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                <Printer className="h-4 w-4" /> Print / Save as PDF
              </button>
              <button
                type="button"
                onClick={() => setComposeBase(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="mt-4 space-y-3">
          {resumes.map((r) => (
            <div key={r.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-900">{r.variant_name}</p>
                  <p className="text-xs text-slate-500">
                    v{r.version_number} · {r.is_active ? 'Active' : 'Archived'} ·{' '}
                    {new Date(r.updated_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void openComposer(r)}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Compose variant
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePrint(r.variant_name, r.content)}
                    className="flex items-center gap-1 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Printer className="h-3.5 w-3.5" /> Print
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingResume(editingResume?.id === r.id ? null : r)}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    {editingResume?.id === r.id ? 'Close' : 'Edit'}
                  </button>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-600">
                <Paperclip className="h-3.5 w-3.5 text-slate-400" />
                {r.file ? (
                  <>
                    <a
                      href={resumeFileUrl(r.id)}
                      download={r.file.name}
                      className="font-medium text-blue-700 hover:underline"
                    >
                      {r.file.name}
                    </a>
                    <span className="text-slate-400">
                      {formatSize(r.file.size)} · uploaded{' '}
                      {new Date(r.file.uploaded_at).toLocaleDateString()}
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleRemoveFile(r)}
                      className="text-slate-500 hover:text-red-600 disabled:opacity-50"
                    >
                      Remove file
                    </button>
                  </>
                ) : (
                  <span className="text-slate-400">No file stored for this version</span>
                )}
                <label className="cursor-pointer rounded-md border border-slate-300 px-2 py-1 font-medium text-slate-700 hover:bg-slate-50">
                  {r.file ? 'Replace file' : 'Upload PDF or DOCX'}
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    className="sr-only"
                    disabled={busy}
                    onChange={(e) => {
                      void handleUpload(r, e.target.files?.[0]);
                      e.target.value = '';
                    }}
                  />
                </label>
              </div>
              {editingResume?.id === r.id && (
                <div className="mt-3">
                  <textarea
                    rows={10}
                    defaultValue={r.content}
                    id={`resume-${r.id}`}
                    className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                  />
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        const el = document.getElementById(`resume-${r.id}`) as HTMLTextAreaElement;
                        try {
                          await updateResume(r.id, { content: el.value });
                          await load();
                          setMessage('Saved.');
                          setEditingResume(null);
                        } catch {
                          setError('Failed.');
                        }
                        setBusy(false);
                      }}
                      className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                    >
                      Save
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
          {!resumes.length && <p className="text-sm text-slate-500">No resume variants yet.</p>}
        </div>
      </div>
    </div>
  );
}

function EvidenceEditor({
  evidence,
  onSave,
  busy,
}: {
  evidence: Evidence;
  onSave: (data: Record<string, unknown>) => void;
  busy: boolean;
}) {
  const [detail, setDetail] = useState(evidence.detail);
  const [contribution, setContribution] = useState(evidence.personal_contribution);
  const [wording, setWording] = useState(evidence.permitted_wording);
  const [source, setSource] = useState(evidence.source ?? '');
  const [scope, setScope] = useState(evidence.scope ?? '');
  const [dates, setDates] = useState(evidence.dates ?? '');

  return (
    <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Source</span>
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Scope</span>
          <input
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium text-slate-600">Dates</span>
          <input
            value={dates}
            onChange={(e) => setDates(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </label>
      </div>
      <label className="block text-xs">
        <span className="font-medium text-slate-600">Detail</span>
        <textarea
          rows={3}
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      </label>
      <label className="block text-xs">
        <span className="font-medium text-slate-600">Personal contribution</span>
        <textarea
          rows={2}
          value={contribution}
          onChange={(e) => setContribution(e.target.value)}
          className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      </label>
      <label className="block text-xs">
        <span className="font-medium text-slate-600">Permitted public wording</span>
        <textarea
          rows={2}
          value={wording}
          onChange={(e) => setWording(e.target.value)}
          className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      </label>
      <button
        type="button"
        disabled={busy}
        onClick={() =>
          onSave({
            detail,
            personal_contribution: contribution,
            permitted_wording: wording,
            source: source || null,
            scope: scope || null,
            dates: dates || null,
          })
        }
        className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
      >
        Save Changes
      </button>
    </div>
  );
}
