import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Job } from '../jobs-api';
import { RatingButtons, RatingsPanel } from './JobRatings';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const job = {
  source: 'greenhouse',
  external_id: 'g-1',
  title: 'Director of Quality Engineering',
  company: 'Acme',
  rating: null,
} as unknown as Job;

it('rates a job, toggles the choice off again, and reports each change', async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}')));
  vi.stubGlobal('fetch', fetch);
  const onRated = vi.fn();
  render(<RatingButtons job={job} onRated={onRated} />);

  const more = screen.getByRole('button', { name: 'More like this' });
  fireEvent.click(more);
  await waitFor(() => expect(more.getAttribute('aria-pressed')).toBe('true'));
  expect(fetch.mock.calls[0][0]).toBe('/api/job-ratings');
  expect(fetch.mock.calls[0][1].method).toBe('PUT');
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
    source: 'greenhouse',
    external_id: 'g-1',
    rating: 1,
  });

  fireEvent.click(more);
  await waitFor(() => expect(more.getAttribute('aria-pressed')).toBe('false'));
  expect(JSON.parse(fetch.mock.calls[1][1].body).rating).toBe(0);

  fireEvent.click(screen.getByRole('button', { name: 'Less like this' }));
  await waitFor(() => expect(JSON.parse(fetch.mock.calls[2][1].body).rating).toBe(-1));
  expect(onRated).toHaveBeenCalledTimes(3);
});

it('lists the ratings that tune scores and clears one', async () => {
  const rows = [
    { job_key: 'k1', title: 'Director QE', company: 'Acme', rating: 1 },
    { job_key: 'k/2', title: 'Payroll Manager', company: 'Initech', rating: -1 },
  ];
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(rows)))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal('fetch', fetch);
  const onChanged = vi.fn();
  render(<RatingsPanel version={0} onChanged={onChanged} />);

  expect(
    await screen.findByText('Tuning from your ratings: 1 more like this, 1 less like this'),
  ).toBeTruthy();
  fireEvent.click(
    screen.getByRole('button', { name: 'Clear rating for Payroll Manager at Initech' }),
  );
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(fetch.mock.calls[1][0]).toBe('/api/job-ratings/k%2F2');
  expect(fetch.mock.calls[1][1].method).toBe('DELETE');
  expect(screen.queryByText(/Payroll Manager/)).toBeNull();
});

it('stays out of the way until something is rated', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('[]'));
  vi.stubGlobal('fetch', fetch);
  const { container } = render(<RatingsPanel version={0} onChanged={() => undefined} />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(container.innerHTML).toBe('');
});
