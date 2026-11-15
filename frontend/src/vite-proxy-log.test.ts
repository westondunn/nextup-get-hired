// @vitest-environment node
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer as createTcpServer, type AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer, type Logger, type ProxyOptions } from 'vite';
import { expect, test } from 'vitest';
import config from '../vite.config';

// The address Google redirects back to carries an authorization code in its query string
// (docs/decisions/0003-google-connection.md, section 4). Vite logs the address of a
// request it could not proxy, so the proxy options cut the query string off that address.
// This runs a real Vite dev server with those options against a port nothing listens on.

async function unusedPort(): Promise<number> {
  const probe = createTcpServer();
  await new Promise<void>((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const { port } = probe.address() as AddressInfo;
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  return port;
}

test('a failed proxy request to the consent callback is logged without its query string', async () => {
  const proxy = (config as { server: { proxy: Record<string, ProxyOptions> } }).server.proxy;
  const logged: string[] = [];
  const logger: Logger = {
    hasWarned: false,
    info: () => {},
    warn: () => {},
    warnOnce: () => {},
    error: (message) => logged.push(message),
    clearScreen: () => {},
    hasErrorLogged: () => false,
  };
  const root = mkdtempSync(join(tmpdir(), 'nextup-proxy-log-'));
  const server = await createServer({
    configFile: false,
    root,
    appType: 'custom',
    customLogger: logger,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: {
      host: '127.0.0.1',
      port: 0,
      watch: null,
      proxy: { '/api': { ...proxy['/api'], target: `http://127.0.0.1:${await unusedPort()}` } },
    },
  });
  try {
    await server.listen();
    const { port } = server.httpServer!.address() as AddressInfo;
    const base = `http://127.0.0.1:${port}`;
    const callback = await fetch(
      `${base}/api/google/callback?state=SYNTHETIC-STATE&code=SYNTHETIC-CODE`,
    );
    const other = await fetch(`${base}/api/jobs?search=kept`);
    expect([callback.status, other.status]).toEqual([502, 502]);
  } finally {
    await server.close();
    rmSync(root, { recursive: true, force: true });
  }
  const text = logged.join('\n');
  expect(text).toContain('http proxy error: /api/google/callback');
  expect(text).not.toContain('SYNTHETIC');
  expect(text).not.toContain('/api/google/callback?');
  // Every other address is logged as before.
  expect(text).toContain('http proxy error: /api/jobs?search=kept');
});
