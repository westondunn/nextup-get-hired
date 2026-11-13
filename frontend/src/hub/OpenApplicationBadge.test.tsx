import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Job, OpenApplication } from '../jobs-api';
import { ApiError } from '../jobs-api';
import { trackJobChecked } from './career-api';
import OpenApplicationBadge from './OpenApplicationBadge';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const open = (title: string, stage: string, same_job = false): OpenApplication => ({
  pursuit_id: title,
  title,
  company: 'Acme',
  stage,
  same_job,
});
const job = (open_applications: OpenApplication[]) => ({ open_applications }) as unknown as Job;

it('labels the job you track and warns about other open applications there', () => {
  render(
    <OpenApplicationBadge
      job={job([
        open('Director QE', 'interview', true),
        open('Head of QA', 'review'),
        open('SDET', 'applied'),
      ])}
    />,
  );
  expect(screen.getByText('In your applications · Interview')).toBeTruthy();
  expect(
    screen.getByText(/Open application at Acme: Head of QA · Review \(\+1 more\)/),
  ).toBeTruthy();
});

it('renders nothing for employers without an open application', () => {
  const { container } = render(<OpenApplicationBadge job={job([])} />);
  expect(container.innerHTML).toBe('');
});

const conflict = () =>
  new Response(JSON.stringify({ detail: 'You already have an open application at Acme.' }), {
    status: 409,
    headers: { 'X-Nextup-Conflict': 'same_company' },
  });

it('asks before tracking a second job at the same employer', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(conflict())
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'p2', created: true })));
  vi.stubGlobal('fetch', fetch);
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  expect(await trackJobChecked('reference', 'r2')).toEqual({ id: 'p2', created: true });
  expect(confirm).toHaveBeenCalledWith('You already have an open application at Acme.');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    source: 'reference',
    external_id: 'r2',
    allow_same_company: true,
  });
});

it('tracks nothing when the user declines, and passes other errors through', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(conflict()));
  vi.spyOn(window, 'confirm').mockReturnValue(false);
  expect(await trackJobChecked('reference', 'r2')).toBeNull();
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(new Response('{"detail":"Saved job not found"}', { status: 404 })),
  );
  await expect(trackJobChecked('reference', 'missing')).rejects.toBeInstanceOf(ApiError);
});
