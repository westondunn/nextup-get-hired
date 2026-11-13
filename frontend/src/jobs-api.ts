export type JobSource = 'adzuna' | 'greenhouse' | 'lever' | 'ashby' | 'reference';
export type JobView = JobSource | 'all';
export const sourceLabels: Record<JobSource, string> = {
  adzuna: 'Adzuna',
  greenhouse: 'Greenhouse',
  lever: 'Lever',
  ashby: 'Ashby',
  reference: 'Saved link',
};
export interface JobOrigin {
  source: JobSource;
  external_id: string;
  url: string;
  fetched_at: string;
  expired: boolean;
  score?: number | null;
}
export interface ScoreExplanation {
  total: number;
  version: string;
  as_of: string;
  components: { key: string; label: string; points: number; maximum: number; evidence: string[] }[];
}
export interface JobFilters {
  q: string;
  company: string;
  location: string;
  exclude: string;
  work_mode: 'any' | 'remote' | 'hybrid' | 'onsite' | 'unknown';
  min_score: string;
  max_age_days: string;
  sort: 'newest' | 'score';
  discovery_only: boolean;
}
export const emptyJobFilters = (): JobFilters => ({
  q: '',
  company: '',
  location: '',
  exclude: '',
  work_mode: 'any',
  min_score: '',
  max_age_days: '',
  sort: 'newest',
  discovery_only: false,
});
export interface Job {
  source: JobSource;
  external_id: string;
  title: string;
  company: string;
  location: string;
  description: string;
  url: string;
  posted_at: string;
  fetched_at: string;
  date_kind?: 'posted' | 'updated' | 'observed';
  expired?: boolean;
  origins?: JobOrigin[];
  score?: number | null;
  score_breakdown?: ScoreExplanation | null;
  work_modes?: string[];
  /** 1 = more like this, -1 = less like this, null = not rated. */
  rating?: number | null;
  /** Open (not closed) applications at this employer; same_job marks this posting. */
  open_applications?: OpenApplication[];
}
export interface OpenApplication {
  pursuit_id: string;
  title: string;
  company: string;
  stage: string;
  same_job: boolean;
}
export interface JobPage {
  items: Job[];
  total: number;
  raw_total?: number;
  retention_days?: number;
  scoring_available?: boolean;
  scoring_version?: string;
  summary?: {
    results: number;
    source_records: number;
    high_score_results: number | null;
    average_score: number | null;
    expired_results: number;
    source_counts: Partial<Record<JobSource, number>>;
  };
}
export interface FetchRun {
  id: string;
  source: JobSource;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'publish_failed';
  recovery_deadline?: string | null;
  delivery_attempts?: number;
  query: Record<string, string>;
  stored_count: number;
  received_count: number;
  skipped_count: number;
  error_message: string | null;
}
export interface SourceStatus {
  ready: boolean;
  message: string;
  query: Record<string, string> | null;
}

/** An API failure; `conflict` names a recoverable 409, such as "same_company". */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly conflict = '',
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/${path}`, { ...options, signal: AbortSignal.timeout(15000) });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      typeof body?.detail === 'string'
        ? body.detail
        : 'Job data could not be read. Try again when the API is available.',
      response.status,
      response.headers.get('X-Nextup-Conflict') ?? '',
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const readSourceStatus = (source: 'adzuna' | 'greenhouse' = 'adzuna') =>
  request<SourceStatus>(`job-source?source=${source}`);
export const readJobs = (
  source: JobView,
  offset: number,
  includeExpired = false,
  filters = emptyJobFilters(),
  hidePassed = false,
  hideOpenCompanies = false,
) => {
  const query = new URLSearchParams({
    source,
    limit: '10',
    offset: String(offset),
    include_expired: String(includeExpired),
  });
  if (hidePassed) query.set('hide_passed', 'true');
  if (hideOpenCompanies) query.set('hide_open_companies', 'true');
  for (const [key, value] of Object.entries(filters))
    if (value !== '') query.set(key, String(value));
  return request<JobPage>(`jobs?${query}`);
};
export const readLatestFetch = (source: JobSource) =>
  request<FetchRun | null>(`job-fetches/latest?source=${source}`);
export const startJobFetch = (source: JobSource) =>
  request<FetchRun>('job-fetches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source }),
  });
export const importCsvJobs = (rows: Record<string, string>[]) =>
  request<{ imported: number; skipped: number; errors: string[]; total_rows: number }>(
    'job-imports/csv',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows }),
    },
  );

export const saveJobReference = (data: {
  title: string;
  company: string;
  location: string;
  description: string;
  url: string;
}) =>
  request<{ source: 'reference'; external_id: string }>('job-references', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
