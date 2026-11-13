import { afterEach, expect, it, vi } from 'vitest';
import { cleanupHistory, previewHistory } from './retention-api';

afterEach(() => vi.unstubAllGlobals());
it('sends a read-only preview and an explicit token-bound cleanup', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  await previewHistory();
  expect(fetch.mock.calls[0][0]).toBe('/api/task-history/preview');
  expect(fetch.mock.calls[0][1].method).toBeUndefined();
  fetch.mockResolvedValueOnce(new Response('{}'));
  await cleanupHistory('specific-preview');
  expect(fetch.mock.calls[1][1].method).toBe('POST');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    token: 'specific-preview',
    confirmation: 'delete_completed_task_history',
  });
});
it('does not retry an uncertain deletion after a lost response', async () => {
  const fetch = vi.fn().mockRejectedValue(new TypeError('Network unavailable'));
  vi.stubGlobal('fetch', fetch);
  await expect(cleanupHistory('specific-preview')).rejects.toThrow(
    'Cleanup was not confirmed. Preview again to see what remains.',
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});
it('distinguishes disabled cleanup and an invalid preview', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(new Response('{}', { status: 403 }))
      .mockResolvedValueOnce(new Response('{}', { status: 409 })),
  );
  await expect(cleanupHistory('preview')).rejects.toThrow('disabled');
  await expect(cleanupHistory('preview')).rejects.toThrow('Preview expired or changed');
});
