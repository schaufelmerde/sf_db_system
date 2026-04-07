import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    proxy: {
      '/api':             'http://localhost:8000',
      '/snapshots':       'http://localhost:8000',
      '/dataset-images':  'http://localhost:8000',
      '/cam': {
        target: 'http://localhost:5000',
        rewrite: (path) => path.replace(/^\/cam/, ''),
      },
    },
  },
})
