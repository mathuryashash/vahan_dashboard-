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
        //
        // Path-based rather than the old package-name object: the app imports
        // `react-dom/client` (not `react-dom`) and React pulls in `scheduler`,
        // neither of which the name list matched, so ~190 kB of react-dom
        // landed in the `index` app chunk (B15: "index is 250 kB"). Matching
        // on node_modules paths puts every runtime dep where it belongs.
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](recharts|d3-[^\\/]+|victory-vendor|internmap|decimal\.js-light|recharts-scale|react-smooth|eventemitter3|fast-equals|tiny-invariant|lodash)[\\/]/.test(id)) return 'charts'
          if (/[\\/]node_modules[\\/]exceljs[\\/]/.test(id)) return undefined
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@remix-run|@tanstack|zustand|use-sync-external-store)[\\/]/.test(id)) return 'vendor'
          return undefined
        },
      },
    },
  },
})