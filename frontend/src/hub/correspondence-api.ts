import { request } from '../jobs-api';

export interface CorrespondenceSettings {
  enabled: boolean;
  query: string;
  max_messages_per_run: number;
  live_enabled: boolean;
  credentials_present: boolean;
  interval_seconds: number;
  last_run_at: string | null;
  last_status: string;
  last_error: string;
  last_imported: number;
  cursor_epoch: number | null;
  calendar_enabled: boolean;
  calendar_lookahead_days: number;
  auto_create_applications: boolean;
  calendar_live_enabled: boolean;
  calendar_interval_seconds: number;
  calendar_last_run_at: string | null;
  calendar_last_status: string;
  calendar_last_error: string;
  calendar_last_imported: number;
  review_count: number;
}

export interface CorrespondenceInput {
  enabled: boolean;
  query: string;
  max_messages_per_run: number;
  calendar_enabled: boolean;
  calendar_lookahead_days: number;
  auto_create_applications: boolean;
}

const json = (method: string, value: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

export const readCorrespondence = () => request<CorrespondenceSettings>('correspondence');
export const saveCorrespondence = (data: CorrespondenceInput) =>
  request<CorrespondenceSettings>('correspondence', json('PUT', data));
export const runCorrespondenceSync = () =>
  request<{ queued: boolean; tasks: string[] }>('correspondence/sync', { method: 'POST' });
