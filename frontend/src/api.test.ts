import { afterEach, expect, it, vi } from 'vitest';
import { startDiagnostic } from './api';

afterEach(() => vi.unstubAllGlobals());

it('recovers the persisted diagnostic ID from an unconfirmed publication response', async () => {
  const run = { id: 'saved-id', status: 'publish_failed' };
  const request = vi
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: { id: 'saved-id' } }),
    })
    .mockResolvedValueOnce({ ok: true, json: async () => run });
  vi.stubGlobal('fetch', request);
  expect(await startDiagnostic()).toEqual(run);
  expect(request.mock.calls[1][0]).toBe('/api/diagnostics/saved-id');
  expect(request).toHaveBeenCalledTimes(2);
});

it('does not invent a task when the database rejected the request', async () => {
  const request = vi.fn().mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({ detail: 'Database unavailable' }),
  });
  vi.stubGlobal('fetch', request);
  await expect(startDiagnostic()).rejects.toThrow('Diagnostic could not be queued');
  expect(request).toHaveBeenCalledTimes(1);
});
