import { afterEach, expect, it, vi } from 'vitest';
import { emptyJobFilters } from './jobs-api';
import { deleteSavedSearch, readSavedSearches, saveSearch } from './saved-search-api';

afterEach(() => vi.unstubAllGlobals());

it('round-trips numeric filters and nulls between form values and the API', async () => {
  const body = {
    name: 'QA',
    source: 'adzuna',
    include_expired: true,
    filters: { ...emptyJobFilters(), min_score: 0, max_age_days: null },
  };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...body, id: '123' }), { status: 201 }))
    .mockResolvedValueOnce(new Response(JSON.stringify([{ ...body, id: '123' }])));
  vi.stubGlobal('fetch', fetch);
  const saved = await saveSearch('QA', {
    source: 'adzuna',
    include_expired: true,
    filters: { ...emptyJobFilters(), min_score: '0' },
  });
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(body);
  expect(saved.filters.min_score).toBe('0');
  expect(saved.filters.max_age_days).toBe('');
  expect(await readSavedSearches()).toEqual([saved]);
});

it('accepts an empty successful delete response and exposes conflict errors', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'Name already exists' }), { status: 409 }),
      ),
  );
  await expect(deleteSavedSearch('123')).resolves.toBeUndefined();
  await expect(
    saveSearch('QA', { source: 'adzuna', include_expired: false, filters: emptyJobFilters() }),
  ).rejects.toThrow('Name already exists');
});
