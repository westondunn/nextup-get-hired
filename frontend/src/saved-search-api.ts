import { request, type JobFilters, type JobView } from './jobs-api';

export interface SearchView {
  source: JobView;
  include_expired: boolean;
  filters: JobFilters;
}
interface StoredSearch extends Omit<SearchView, 'filters'> {
  id: string;
  name: string;
  alerts_enabled?: boolean;
  alert_min_score?: number;
  alert_check_status?: string;
  alert_checked_at?: string | null;
  filters: Omit<JobFilters, 'min_score' | 'max_age_days'> & {
    min_score: number | null;
    max_age_days: number | null;
  };
}
export interface SavedSearch extends SearchView {
  id: string;
  name: string;
  alerts_enabled?: boolean;
  alert_min_score?: number;
  alert_check_status?: string;
  alert_checked_at?: string | null;
}

function fromStored(row: StoredSearch): SavedSearch {
  return {
    ...row,
    filters: {
      ...row.filters,
      discovery_only: row.filters.discovery_only ?? false,
      min_score: row.filters.min_score == null ? '' : String(row.filters.min_score),
      max_age_days: row.filters.max_age_days == null ? '' : String(row.filters.max_age_days),
    },
  };
}
export async function readSavedSearches() {
  return (await request<StoredSearch[]>('saved-searches')).map(fromStored);
}
export async function readSavedSearch(id: string) {
  return fromStored(await request<StoredSearch>(`saved-searches/${id}`));
}
export async function configureAlerts(id: string, enabled: boolean, minScore: number) {
  return fromStored(
    await request<StoredSearch>(`saved-searches/${id}/alerts`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, min_score: minScore }),
    }),
  );
}
export async function checkAlerts(id: string) {
  return fromStored(
    await request<StoredSearch>(`saved-searches/${id}/alerts/check`, { method: 'POST' }),
  );
}
export async function saveSearch(name: string, view: SearchView, id?: string) {
  const body = {
    name,
    ...view,
    filters: {
      ...view.filters,
      min_score: view.filters.min_score === '' ? null : Number(view.filters.min_score),
      max_age_days: view.filters.max_age_days === '' ? null : Number(view.filters.max_age_days),
    },
  };
  return fromStored(
    await request<StoredSearch>(`saved-searches${id ? `/${id}` : ''}`, {
      method: id ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}
export const deleteSavedSearch = (id: string) =>
  request<void>(`saved-searches/${id}`, { method: 'DELETE' });
