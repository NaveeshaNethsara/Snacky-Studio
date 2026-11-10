import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173, strictPort: true,
    proxy: { '/api': process.env.SNACKY_API_URL || 'http://127.0.0.1:8000', '/static': process.env.SNACKY_API_URL || 'http://127.0.0.1:8000' },
  },
  build: { outDir: '../app/web', emptyOutDir: true },
  test: { environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], exclude: ['e2e/**', 'node_modules/**'] },
});
