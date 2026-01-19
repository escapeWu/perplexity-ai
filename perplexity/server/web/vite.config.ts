/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tsconfigPaths from 'vite-tsconfig-paths'

// https://vitejs.dev/config https://vitest.dev/config
export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  base: '/admin/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/pool': 'http://127.0.0.1:8000',
      '/heartbeat': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/v1': 'http://127.0.0.1:8000',
    },
  },
  test: {
    globals: true,
    environment: 'happy-dom',
    setupFiles: '.vitest/setup',
    include: ['**/test.{ts,tsx}'],
  },
})
