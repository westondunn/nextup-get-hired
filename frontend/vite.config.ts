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
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
