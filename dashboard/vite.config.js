import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/health':       'http://localhost:8000',
      '/prices':       'http://localhost:8000',
      '/saturation':   'http://localhost:8000',
      '/declarations': 'http://localhost:8000',
      '/farmer':       'http://localhost:8000',
      '/predict':      'http://localhost:8000',
      '/webhook':      'http://localhost:8000',
      '/internal':     'http://localhost:8000',
      '/satellite':    'http://localhost:8000',
    },
  },
})
