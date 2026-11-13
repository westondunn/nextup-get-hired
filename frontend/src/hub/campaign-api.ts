import { request } from '../jobs-api';

export interface Campaign {
  id: string;
  campaign_key: string;
  title: string;
  start_date: string;
  end_date: string;
  timezone: string;
  daily_capacity_minutes: number;
  preferences: Record<string, unknown>;
  is_active: boolean;
  task_counts: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface CampaignTask {
  id: string;
  campaign_id: string;
  seed_key: string | null;
  title: string;
  category: string;
  status: string;
  priority: string;
  due_date: string | null;
  estimated_minutes: number | null;
  depends_on: string[];
  suggested_after: string[];
  completion_criteria: string;
  notes: string;
  pursuit_id: string | null;
  communication_id?: string | null;
  /** The imported message a follow-up task answers, in full. */
  communication?: TaskMessage | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  priority_reason?: string;
}

export interface TaskMessage {
  id: string;
  source: string;
  channel: string;
  direction: string;
  sender: string | null;
  subject: string;
  body: string;
  received_at: string | null;
  contact_id: string | null;
  pursuit_id: string | null;
}

export interface TodayData {
  campaign: {
    id: string;
    title: string;
    day_number: number;
    days_remaining: number;
    daily_capacity_minutes: number;
    timezone: string;
  } | null;
  priority_actions: CampaignTask[];
  overdue_tasks: CampaignTask[];
  today_tasks: CampaignTask[];
  upcoming_tasks: CampaignTask[];
  interviews: {
    id: string;
    title: string;
    company: string;
    next_action_on: string | null;
    score: number | null;
  }[];
  follow_ups: {
    id: string;
    title: string;
    company: string;
    stage: string;
    next_action_on: string | null;
  }[];
  capacity: { used_minutes: number; remaining_minutes: number; total_minutes: number } | null;
  commitments: {
    id: string;
    title: string;
    company: string;
    stage: string;
    next_action_on: string | null;
  }[];
}

export interface SeedPreview {
  campaign: { key: string; exists: boolean; action: string };
  tasks: { new: number; updated: number; skipped: number; details: Record<string, unknown[]> };
  evidence: { count: number; note: string };
  content: { count: number; note: string };
  leads: { count: number };
  contacts?: { count: number };
}

export interface SeedResult {
  campaign_id: string;
  campaign_key: string;
  tasks_created: number;
  tasks_updated: number;
  tasks_skipped: number;
}

const json = (method: string, value: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

export const readCampaigns = () => request<Campaign[]>('campaigns');
export const createCampaign = (data: Record<string, unknown>) =>
  request<Campaign>('campaigns', json('POST', data));
export const readCampaign = (id: string) => request<Campaign>(`campaigns/${id}`);
export const updateCampaign = (id: string, data: Record<string, unknown>) =>
  request<Campaign>(`campaigns/${id}`, json('PUT', data));

export const readTasks = (campaignId: string, params?: Record<string, string>) => {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  return request<CampaignTask[]>(`campaigns/${campaignId}/tasks${query}`);
};
export const createTask = (campaignId: string, data: Record<string, unknown>) =>
  request<CampaignTask>(`campaigns/${campaignId}/tasks`, json('POST', data));
export const updateTask = (campaignId: string, taskId: string, data: Record<string, unknown>) =>
  request<CampaignTask>(`campaigns/${campaignId}/tasks/${taskId}`, json('PUT', data));
export const bulkTaskStatus = (campaignId: string, taskIds: string[], status: string) =>
  request<{ updated: number }>(
    `campaigns/${campaignId}/tasks/bulk-status`,
    json('POST', { task_ids: taskIds, status }),
  );

export const readToday = () => request<TodayData>('today');

export const previewSeed = (data: unknown) =>
  request<SeedPreview>('seed/preview', json('POST', data));
export const applySeed = (data: unknown) => request<SeedResult>('seed/apply', json('POST', data));
