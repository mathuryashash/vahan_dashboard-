import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        // Not 'localhost': Node's DNS resolution on this machine prefers
        // ::1, but uvicorn only binds the IPv4 wildcard -- that mismatch
        // made every proxied /api call 502 despite the backend being up.
        target: 'http://127.0.0.1:8020',
        changeOrigin: true,
      }
    }
  }
})