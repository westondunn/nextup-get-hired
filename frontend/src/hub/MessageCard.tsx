import { useState } from 'react';
import { createCommunication, type MailDetection } from './contacts-api';

/** An imported Gmail message or Calendar event, as the API returns it. */
export interface ImportedMessage {
  id?: string;
  source: string;
  channel: string;
  direction: string;
  sender: string | null;
  subject: string;
  body: string;
  received_at: string | null;
  sent_at?: string | null;
  created_at?: string;
  contact_id?: string | null;
  pursuit_id?: string | null;
  thread_id?: string | null;
  detection?: MailDetection | null;
  classifier_company?: string | null;
}

const CLASSIFIER_LABELS: Record<string, string> = {
  new_application: 'Application',
  opportunity: 'Opportunity',
  existing_company: 'Existing company',
  not_relevant: 'Not relevant',
};
const KIND_LABELS: Record<string, string> = {
  application_confirmation: 'an application confirmation',
  rejection: 'a rejection',
  interview_invitation: 'an interview invitation',
};

/** The external classifier's verdict and matched company, flagged when Nextup disagrees. */
export function ClassifierBadge({ message }: { message: ImportedMessage }) {
  const hint = message.detection?.classifier;
  if (!hint) return null;
  const company = message.classifier_company ?? hint.company_name;
  const confidence = hint.confidence != null ? ` (${Math.round(hint.confidence * 100)}%)` : '';
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span
        className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-800"
        title={`Classified externally${hint.model ? ` with ${hint.model}` : ''}${confidence}${hint.companies.length ? `; companies: ${hint.companies.join(', ')}` : ''}`}
      >
        Classifier: {CLASSIFIER_LABELS[hint.classification] ?? hint.classification}
        {company ? ` · ${company}` : ''}
      </span>
      {hint.agrees === false && (
        <span
          className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-900"
          title={`Nextup read this as ${KIND_LABELS[message.detection?.kind ?? ''] ?? message.detection?.kind}; the classifier said ${CLASSIFIER_LABELS[hint.classification] ?? hint.classification}. Nextup's reading is used.`}
        >
          Classifier disagrees
        </span>
      )}
    </span>
  );
}

const TALL = 24 * 16; // px; a message taller than this scrolls until expanded

export function sourceLabel(source: string): string {
  return source === 'calendar' ? 'calendar' : source === 'gmail' ? 'email' : source;
}

export function messageTime(m: ImportedMessage): number {
  const stamp = m.received_at ?? m.sent_at ?? m.created_at;
  return stamp ? new Date(stamp).getTime() : 0;
}

/**
 * Group messages that share a Gmail thread. Threads are ordered newest-activity first;
 * inside a thread the messages run oldest to newest so the exchange reads in order.
 * A message without a thread is a thread of one.
 */
export function groupThreads<T extends ImportedMessage>(rows: T[]): T[][] {
  const byThread = new Map<string, T[]>();
  for (const row of rows) {
    const key = row.thread_id ? `t:${row.thread_id}` : `m:${row.id ?? Math.random()}`;
    const bucket = byThread.get(key);
    if (bucket) bucket.push(row);
    else byThread.set(key, [row]);
  }
  const threads = [...byThread.values()];
  for (const thread of threads) thread.sort((a, b) => messageTime(a) - messageTime(b));
  threads.sort((a, b) => messageTime(b[b.length - 1]) - messageTime(a[a.length - 1]));
  return threads;
}

export function replySubject(subject: string): string {
  return /^re:/i.test(subject.trim()) ? subject.trim() : `Re: ${subject}`.trim();
}

/**
 * The whole message text, never a preview: imported mail and events are acted on from
 * here, so nothing is cut. Very long messages scroll inside the card until expanded.
 */
export function MessageBody({ body, className = '' }: { body: string; className?: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!body) return null;
  const long = body.length > 1500;
  return (
    <div className={className}>
      <pre
        className="mt-1 whitespace-pre-wrap break-words rounded-md border border-slate-100 bg-slate-50/60 p-2 font-sans text-xs text-slate-700"
        style={!expanded && long ? { maxHeight: TALL, overflowY: 'auto' } : undefined}
      >
        {body}
      </pre>
      {long && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-[11px] font-medium text-slate-500 hover:text-slate-800"
        >
          {expanded ? 'Collapse message' : 'Show without scrolling'}
        </button>
      )}
    </div>
  );
}

export interface ReplyOptions {
  /** The follow-up task this reply answers; recorded on the logged communication. */
  taskId?: string | null;
  /** Label for the button that records the reply as sent. */
  sentLabel?: string;
  /** Called after a communication was recorded, with its status. */
  onDone: (status: 'draft' | 'sent') => void;
}

/**
 * Draft and record a reply to an imported message. Nothing is sent from here: you send
 * it from your own mail client, then log it as sent, which clears the missed-reply rule.
 */
export function ReplyComposer({
  message,
  reply,
  onCancel,
}: {
  message: ImportedMessage;
  reply: ReplyOptions;
  onCancel: () => void;
}) {
  const [subject, setSubject] = useState(replySubject(message.subject));
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  async function record(status: 'draft' | 'sent') {
    setBusy(true);
    setError('');
    try {
      await createCommunication({
        contact_id: message.contact_id ?? null,
        pursuit_id: message.pursuit_id ?? null,
        campaign_task_id: reply.taskId ?? null,
        channel: 'email',
        direction: 'outbound',
        subject,
        body,
        status,
        thread_id: message.thread_id ?? null,
      });
      reply.onDone(status);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not record the reply.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50/40 p-3">
      <p className="text-xs font-medium text-slate-700">
        Reply to {message.sender || 'the sender'}
      </p>
      <p className="mt-0.5 text-[11px] text-slate-500">
        Nextup never sends mail. Write the reply here, copy it into your mail client, send it
        yourself, then log it as sent.
      </p>
      <input
        aria-label="Reply subject"
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        maxLength={500}
        className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
      />
      <textarea
        aria-label="Reply body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        maxLength={20000}
        placeholder="Your reply…"
        className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || !body.trim()}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(`${subject}\n\n${body}`);
              setCopied(true);
            } catch (err) {
              console.error('Action failed:', err);
            }
          }}
          className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-white disabled:opacity-50"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button
          type="button"
          disabled={busy || !body.trim()}
          onClick={() => void record('draft')}
          className="rounded-md border border-slate-900 px-3 py-1 text-xs font-medium text-slate-900 hover:bg-white disabled:opacity-50"
        >
          Save draft
        </button>
        <button
          type="button"
          disabled={busy || !body.trim()}
          onClick={() => void record('sent')}
          className="rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {reply.sentLabel ?? 'Log as sent'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-800"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Sender, time, subject, and the full body of an imported message. */
export default function MessageCard({
  message,
  heading,
  reply,
}: {
  message: ImportedMessage;
  heading?: string;
  reply?: ReplyOptions;
}) {
  const [replying, setReplying] = useState(false);
  const when = message.received_at ? new Date(message.received_at).toLocaleString() : '';
  const outbound = message.direction === 'outbound';
  return (
    <div
      className={`rounded-lg border p-3 ${outbound ? 'border-emerald-100 bg-emerald-50/30' : 'border-blue-100 bg-white'}`}
    >
      {heading && <p className="text-xs font-medium text-slate-600">{heading}</p>}
      <div className="mt-0.5 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-slate-600">
          <span className="mr-2 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
            {outbound ? 'you' : sourceLabel(message.source)}
          </span>
          {outbound
            ? `Your reply${message.sent_at ? '' : ' (not sent yet)'}`
            : message.sender || 'Unknown sender'}{' '}
          <ClassifierBadge message={message} />
        </span>
        {when && <span className="text-xs text-slate-400">{when}</span>}
      </div>
      <p className="mt-1 text-sm font-medium text-slate-900">{message.subject || '(no subject)'}</p>
      <MessageBody body={message.body} />
      {reply && message.id && message.direction === 'inbound' && !replying && (
        <button
          type="button"
          onClick={() => setReplying(true)}
          className="mt-2 rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800"
        >
          Draft reply
        </button>
      )}
      {reply && replying && (
        <ReplyComposer
          message={message}
          reply={{
            ...reply,
            onDone: (status) => {
              setReplying(false);
              reply.onDone(status);
            },
          }}
          onCancel={() => setReplying(false)}
        />
      )}
    </div>
  );
}

/** One Gmail thread: the latest message open, earlier ones behind a toggle. */
export function ThreadCard({
  messages,
  reply,
}: {
  messages: ImportedMessage[];
  reply?: ReplyOptions;
}) {
  const [open, setOpen] = useState(false);
  if (messages.length === 1) return <MessageCard message={messages[0]} reply={reply} />;
  const shown = open ? messages : messages.slice(-1);
  return (
    <div className="space-y-2 rounded-lg border border-blue-100 bg-blue-50/30 p-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] font-medium text-blue-700 hover:text-blue-900"
      >
        {open
          ? 'Hide earlier messages in this thread'
          : `Show ${messages.length - 1} earlier ${messages.length === 2 ? 'message' : 'messages'} in this thread`}
      </button>
      {shown.map((m) => (
        <MessageCard key={m.id} message={m} reply={reply} />
      ))}
    </div>
  );
}
