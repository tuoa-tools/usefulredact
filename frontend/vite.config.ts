import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// In dev, Vite proxies /api to the FastAPI backend so the browser sees one origin (no CORS).
// In the packaged app, FastAPI serves the built files from app/static itself.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_API_URL || 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { outDir: '../app/static', emptyOutDir: true },
  test: { environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], css: false },
});
