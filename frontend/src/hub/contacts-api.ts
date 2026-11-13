import { request } from '../jobs-api';

export interface Contact {
  id: string;
  name: string;
  company: string | null;
  title: string | null;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  relationship: string;
  notes: string;
  do_not_contact: boolean;
  introduced_by: string | null;
  last_contacted_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Local classification of an imported message; `applied` records what it created. */
export interface MailDetection {
  kind: 'application_confirmation' | 'auto_reply' | 'rejection' | 'interview_invitation' | 'none';
  confidence?: 'high' | 'medium';
  company?: string;
  title?: string;
  requisition?: string;
  evidence?: string;
  undone?: boolean;
  applied?: {
    pursuit_id: string;
    created_pursuit: boolean;
    previous_stage?: string;
    created_contact?: boolean;
    stage?: string;
    at: string;
  };
  stage_decision?: { decision: 'applied' | 'ignored'; stage: string; at: string };
  /** An external classifier's verdict, merged in by the sync as a hint. */
  classifier?: ClassifierHint;
}

export type ClassifierClassification =
  'new_application' | 'opportunity' | 'existing_company' | 'not_relevant';

export interface ClassifierHint {
  classification: ClassifierClassification;
  companies: string[];
  company_id: string | null;
  company_name: string | null;
  confidence: number | null;
  model: string | null;
  prompt_version: string | null;
  classified_at: string | null;
  /** False when Nextup's own detection says otherwise; null when Nextup has no opinion. */
  agrees: boolean | null;
}

/** A rejection or interview message that proposes a stage for one application. */
export interface StageSuggestion {
  stage: 'rejected' | 'interview';
  pursuit_id: string;
  current_stage: string;
  company: string;
  title: string;
  evidence: string;
  communication: Communication;
}
export type StartStage = 'review' | 'preparing' | 'applied' | 'interview';

export interface Communication {
  id: string;
  contact_id: string | null;
  pursuit_id: string | null;
  campaign_task_id: string | null;
  channel: string;
  direction: string;
  subject: string;
  body: string;
  status: string;
  sent_at: string | null;
  received_at: string | null;
  notes: string;
  source: string;
  source_id: string | null;
  thread_id: string | null;
  sender: string | null;
  suggested_pursuit_id: string | null;
  detection?: MailDetection | null;
  /** Current name of the company the classifier matched, if any. */
  classifier_company?: string | null;
  suggested_company?: string | null;
  pursuit_company?: string | null;
  created_at: string;
  updated_at: string;
}

const json = (method: string, value: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

export const readContacts = (q?: string) =>
  request<Contact[]>(`contacts${q ? `?q=${encodeURIComponent(q)}` : ''}`);
export const createContact = (data: Record<string, unknown>) =>
  request<Contact>('contacts', json('POST', data));
export const updateContact = (id: string, data: Record<string, unknown>) =>
  request<Contact>(`contacts/${id}`, json('PUT', data));
export const deleteContact = (id: string) => request<void>(`contacts/${id}`, { method: 'DELETE' });

const PAGE_SIZE = 200;
const MAX_PAGES = 25;
/** Every matching communication, newest first; the API pages them 200 at a time. */
export const readCommunications = async (params?: Record<string, string>) => {
  const rows: Communication[] = [];
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const qs = new URLSearchParams({
      ...params,
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    });
    const batch = await request<Communication[]>(`communications?${qs.toString()}`);
    rows.push(...batch);
    if (batch.length < PAGE_SIZE) break;
  }
  return rows;
};
export const readReviewQueue = () => readCommunications({ unlinked: 'true' });
export const createCommunication = (data: Record<string, unknown>) =>
  request<Communication>('communications', json('POST', data));
export interface ApplicationFromMail {
  pursuit_id: string;
  created: boolean;
  stage: string;
  company: string;
  title: string;
  contact_id: string | null;
}
/** Create (or advance to applied) the application an imported confirmation refers to. */
export const createApplicationFromMail = (
  id: string,
  data: { company?: string; title?: string; stage?: StartStage },
) => request<ApplicationFromMail>(`communications/${id}/application`, json('POST', data));
/** Reverse what a confirmation email recorded; the message returns to the review queue. */
export const undoApplicationFromMail = (id: string) =>
  request<void>(`communications/${id}/application`, { method: 'DELETE' });
export const readStageSuggestions = () => request<StageSuggestion[]>('stage-suggestions');
/** Confirm (move the stage and link the message) or ignore one suggestion. */
export const decideStageSuggestion = (id: string, decision: 'apply' | 'ignore') =>
  request<{ decision: string; current_stage: string }>(
    `communications/${id}/stage-suggestion`,
    json('POST', { decision }),
  );
export const updateCommunication = (id: string, data: Record<string, unknown>) =>
  request<Communication>(`communications/${id}`, json('PUT', data));
