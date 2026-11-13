import { request } from '../jobs-api';

export interface LinkedTask {
  id: string;
  title?: string;
  status?: string;
  due_date?: string | null;
}

export interface ContentItem {
  id: string;
  seed_key: string | null;
  kind: string;
  state: string;
  topic: string;
  title: string | null;
  body: string;
  outline: string[] | null;
  campaign_task_id: string | null;
  published_at: string | null;
  public_url: string | null;
  notes: string;
  target_date: string | null;
  series: string | null;
  linked_task: LinkedTask | null;
  created_at: string;
  updated_at: string;
}

const json = (method: string, value: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

export const readContent = (kind?: string, state?: string, series?: string) => {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);
  if (state) params.set('state', state);
  if (series) params.set('series', series);
  const qs = params.toString();
  return request<ContentItem[]>(`content${qs ? `?${qs}` : ''}`);
};
export const createContent = (data: Record<string, unknown>) =>
  request<ContentItem>('content', json('POST', data));
export const updateContent = (id: string, data: Record<string, unknown>) =>
  request<ContentItem>(`content/${id}`, json('PUT', data));
export const deleteContent = (id: string) => request<void>(`content/${id}`, { method: 'DELETE' });
export const advanceContent = (id: string) =>
  request<ContentItem>(`content/${id}/advance`, { method: 'POST' });
