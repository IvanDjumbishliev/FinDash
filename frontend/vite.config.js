import { env } from 'node:process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8000',
    },
  },
})