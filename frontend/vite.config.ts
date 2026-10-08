import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8020',
        changeOrigin: true,
        cookieDomainRewrite: 'localhost',
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        // Route-level code splitting (React.lazy, see App.tsx) already keeps
        // per-page app code out of the initial bundle -- this instead
        // separates rarely-changing vendor code into its own chunk, so a
        // deploy that only touches app code doesn't bust the browser cache
        // for React/router/query/zustand too. recharts gets its own chunk
        // since it's the single largest dependency and used unevenly across
        // pages (exceljs is already its own async chunk via the dynamic
        // `import('exceljs')` in csv.ts, so it doesn't need listing here).
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query', 'zustand'],
          charts: ['recharts'],
        },
      },
    },
  },
})