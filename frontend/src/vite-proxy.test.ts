import { expect, test } from 'vitest';
import config from '../vite.config';

// The API accepts local host names only and refuses a state-changing request whose Origin
// differs from its Host (docs/decisions/0001-local-session-boundary.md). Both checks need
// the dev-server proxy to forward the browser's Host header unchanged. Vite rewrites Host
// to the target's when the target is a plain string or changeOrigin is true.
test('the /api proxy forwards the browser Host header unchanged', () => {
  const proxy = (config as { server?: { proxy?: Record<string, unknown> } }).server?.proxy ?? {};
  expect(Object.keys(proxy)).toEqual(['/api']);
  const options = proxy['/api'] as Record<string, unknown>;
  expect(typeof options).toBe('object');
  expect(typeof options.target).toBe('string');
  expect(options.changeOrigin).toBe(false);
  expect(Object.keys(options).sort()).toEqual(['changeOrigin', 'target']);
});
