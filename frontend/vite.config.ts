import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev requests flow through the Go gateway (JWT/TraceID/SSE flush),
// exactly like production.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_GATEWAY_URL ?? 'http://127.0.0.1:8080',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
