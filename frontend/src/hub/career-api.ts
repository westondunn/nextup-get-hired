import { ApiError, request, type Job } from '../jobs-api';

export type Stage =
  | 'review'
  | 'preparing'
  | 'applied'
  | 'interview'
  | 'offer'
  | 'accepted'
  | 'rejected'
  | 'withdrawn'
  | 'dismissed';

export const stages: Stage[] = [
  'review',
  'preparing',
  'applied',
  'interview',
  'offer',
  'accepted',
  'rejected',
  'withdrawn',
  'dismissed',
];

export const closedStages = new Set<Stage>(['accepted', 'rejected', 'withdrawn', 'dismissed']);

export interface Preferences {
  automatic: boolean;
  daily_limit: number;
  follow_up_days: number;
  timezone: string;
  minimum_annual_usd: number | null;
  minimum_hourly_usd: number | null;
  start_by: string;
  open_to_contract: boolean;
  open_to_individual_contributor: boolean;
  verified_achievements: string;
  application_template: string;
  outreach_template: string;
}

export interface Pursuit {
  id: string;
  job: Job;
  stage: Stage;
  notes: string;
  application_draft: string;
  outreach_draft: string;
  next_action_on: string | null;
  created_by: string;
  version: number;
  applied_at: string | null;
  updated_at: string;
  due: boolean;
  next_action: string;
  follow_up_draft: string;
  checks: string[];
  priority_score?: number;
  priority_reason?: string;
  prep_data?: Record<string, string>;
  offer_data?: Record<string, string>;
  resume_version_id: string | null;
  resume_label?: string | null;
}

export interface Analytics {
  total: number;
  applied: number;
  interviewing: number;
  offers: number;
  apply_rate: number;
  interview_rate: number;
  offer_rate: number;
  transitions: Record<string, number>;
  stale_items: {
    id: string;
    title: string;
    company: string;
    stage: string;
    updated_at: string | null;
  }[];
}

export interface Workspace {
  preferences: Preferences;
  today: string;
  items: Pursuit[];
  total: number;
  plan: Pursuit[];
  counts: Record<Stage, number>;
  ready: boolean;
  automation: { status: string; checked_at: string | null; worker: string | null };
  delivery: string;
  analytics?: Analytics;
}

export interface Attachment {
  kind: string;
  label: string;
  content: string;
  url: string;
}

export interface PursuitEvent {
  id: string;
  message: string;
  event_date: string | null;
  actor: string;
  source: string;
  evidence: string;
  attachments?: Attachment[];
  created_at: string;
}

export interface TimelineInput {
  message: string;
  event_date: string;
  actor?: string;
  source?: string;
  evidence?: string;
  attachments?: { kind: string; label: string; content: string; url: string }[];
}

const json = (method: string, value: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

export const readWorkspace = () => request<Workspace>('career');

export const savePreferences = (prefs: Preferences) =>
  request<Workspace>('career/preferences', json('PUT', prefs));

export const buildPlan = () =>
  request<{ added: number; status: string }>('career/plan', { method: 'POST' });

export const trackJob = (source: string, externalId: string, allowSameCompany = false) =>
  request<{ id: string; created: boolean }>(
    'career/pursuits',
    json('POST', {
      source,
      external_id: externalId,
      ...(allowSameCompany ? { allow_same_company: true } : {}),
    }),
  );

/**
 * Track a job, asking first when the employer already has an open application.
 * Returns null when the user decides not to track a second job there.
 */
export async function trackJobChecked(source: string, externalId: string) {
  try {
    return await trackJob(source, externalId);
  } catch (e) {
    if (!(e instanceof ApiError) || e.conflict !== 'same_company') throw e;
    if (!window.confirm(e.message)) return null;
    return trackJob(source, externalId, true);
  }
}

export const updatePursuit = (
  id: string,
  data: {
    version: number;
    stage: Stage;
    notes: string;
    application_draft: string;
    outreach_draft: string;
    next_action_on: string | null;
    prep_data?: Record<string, string>;
    offer_data?: Record<string, string>;
    resume_version_id?: string | null;
  },
) => request<Pursuit>(`career/pursuits/${id}`, json('PUT', data));

export const recordContact = (id: string, version: number, note: string) =>
  request<Pursuit>(`career/pursuits/${id}/contact`, json('POST', { version, note }));

export const readEvents = (id: string) => request<PursuitEvent[]>(`career/pursuits/${id}/events`);

export const readTimeline = (id: string) =>
  request<PursuitEvent[]>(`career/pursuits/${id}/timeline`);

export const addTimelineEvent = (id: string, data: TimelineInput) =>
  request<PursuitEvent>(`career/pursuits/${id}/timeline`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

export const updateTimelineEvent = (
  pursuitId: string,
  eventId: string,
  data: Record<string, unknown>,
) =>
  request<PursuitEvent>(`career/pursuits/${pursuitId}/timeline/${eventId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

export const deleteTimelineEvent = (pursuitId: string, eventId: string) =>
  request<void>(`career/pursuits/${pursuitId}/timeline/${eventId}`, { method: 'DELETE' });

export const announce = () => window.dispatchEvent(new Event('nextup:pursuits'));

export interface WeeklyPeriod {
  added: number;
  applied: number;
  interviews: number;
  offers: number;
  contacts: number;
  total_events: number;
}
export interface WeeklySummary {
  this_week: WeeklyPeriod;
  last_week: WeeklyPeriod;
}
export const readWeeklySummary = () => request<WeeklySummary>('career/weekly-summary');

const NEXT_STAGE: Partial<Record<Stage, Stage>> = {
  review: 'preparing',
  preparing: 'applied',
  applied: 'interview',
  interview: 'offer',
};

export async function advanceStage(item: Pursuit): Promise<Pursuit> {
  const next = NEXT_STAGE[item.stage];
  if (!next) throw new Error(`Cannot advance from ${item.stage}`);
  return updatePursuit(item.id, {
    version: item.version,
    stage: next,
    notes: item.notes,
    application_draft: item.application_draft,
    outreach_draft: item.outreach_draft,
    next_action_on: next === 'applied' ? null : item.next_action_on,
  });
}

export const bulkUpdateStage = (items: Pursuit[], stage: Stage) =>
  request<{ succeeded: number; skipped: number }>(
    'career/pursuits/bulk',
    json('POST', {
      items: items.map((i) => ({ id: i.id, version: i.version })),
      stage,
    }),
  );
