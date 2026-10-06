import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the Atlas API runs separately (`uv run atlas serve`); Vite proxies /api to it.
// In production `npm run build` writes web/dist, which the API serves from the same origin.
export default defineConfig({
  plugins: [react()],
  worker: { format: 'es' },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
