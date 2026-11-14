import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Where the dev server forwards /api requests (our FastAPI backend).
  const backend = env.VITE_DEV_BACKEND || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // Dev proxy: the browser calls /api/... on the Vite server and Vite
      // forwards it to the backend. Same origin => no CORS problems.
      proxy: {
        '/api': { target: backend, changeOrigin: true },
      },
    },
  }
})
