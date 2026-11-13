import { afterEach, expect, it, vi } from 'vitest';
import {
  readCorrespondence,
  runCorrespondenceSync,
  saveCorrespondence,
} from './correspondence-api';

afterEach(() => vi.unstubAllGlobals());

it('reads settings, saves them with a PUT body, and queues a manual sync', async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}')));
  vi.stubGlobal('fetch', fetch);
  await readCorrespondence();
  expect(fetch.mock.calls[0][0]).toBe('/api/correspondence');
  expect(fetch.mock.calls[0][1].method).toBeUndefined();
  const input = {
    enabled: false,
    query: 'label:job-search',
    max_messages_per_run: 25,
    calendar_enabled: false,
    calendar_lookahead_days: 14,
    auto_create_applications: false,
  };
  await saveCorrespondence(input);
  expect(fetch.mock.calls[1][1].method).toBe('PUT');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual(input);
  await runCorrespondenceSync();
  expect(fetch.mock.calls[2][0]).toBe('/api/correspondence/sync');
  expect(fetch.mock.calls[2][1].method).toBe('POST');
});

it('surfaces the server reason when enabling is refused', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Gmail sync is switched off' }), {
        status: 409,
      }),
    ),
  );
  await expect(
    saveCorrespondence({
      enabled: true,
      query: 'label:x',
      max_messages_per_run: 1,
      calendar_enabled: false,
      calendar_lookahead_days: 14,
      auto_create_applications: false,
    }),
  ).rejects.toThrow('Gmail sync is switched off');
});
