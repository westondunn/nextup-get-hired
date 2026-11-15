import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    allowedHosts: ['frontend'],
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:18000',
        // Forward the browser's Host header unchanged. The API accepts local host names
        // only and compares Origin with Host (docs/decisions/0001-local-session-boundary.md).
        // A plain string target would make Vite rewrite Host to the target's.
        changeOrigin: false,
        // When the API cannot be reached, Vite logs the address of the failed request.
        // The address Google redirects back to carries an authorization code in its query
        // string, which must not reach a log (docs/decisions/0003-google-connection.md,
        // section 4). This listener is registered before Vite's own and cuts the query
        // string off that one address.
        configure: (proxy) => {
          proxy.on('error', (_error, request) => {
            if (request.url?.startsWith('/api/google/callback')) {
              request.url = request.url.split('?')[0];
            }
          });
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
