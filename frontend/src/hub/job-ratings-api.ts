import { request } from '../jobs-api';

export type JobRatingValue = -1 | 0 | 1;

export interface JobRating {
  job_key: string;
  source: string;
  external_id: string;
  title: string;
  company: string;
  rating: -1 | 1;
  updated_at: string;
}

/** Rate one job: 1 = more like this, -1 = less like this, 0 = clear. */
export const rateJob = (source: string, externalId: string, rating: JobRatingValue) =>
  request<{ job_key: string; rating: JobRatingValue }>('job-ratings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, external_id: externalId, rating }),
  });
export const readJobRatings = () => request<JobRating[]>('job-ratings');
export const clearJobRating = (jobKey: string) =>
  request<void>(`job-ratings/${encodeURIComponent(jobKey)}`, { method: 'DELETE' });
