import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Suppress noisy ECONNREFUSED errors during backend startup.
// Node wraps parallel connection attempts in an AggregateError,
// so we check both the top-level code and the nested errors array.
function silenceECONNREFUSED(proxy) {
  proxy.on('error', (err, _req, res) => {
    const isRefused = err.code === 'ECONNREFUSED' ||
      (Array.isArray(err.errors) && err.errors.every(e => e.code === 'ECONNREFUSED'))
    if (isRefused) return
    console.error('[proxy]', err.message)
    if (res && typeof res.writeHead === 'function' && !res.headersSent) {
      res.writeHead(502)
      res.end('Bad Gateway')
    }
  })
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    proxy: {
      '/api':            { target: 'http://localhost:8000', configure: silenceECONNREFUSED },
      '/snapshots':      { target: 'http://localhost:8000', configure: silenceECONNREFUSED },
      '/dataset-images': { target: 'http://localhost:8000', configure: silenceECONNREFUSED },
      '/ws':             { target: 'ws://localhost:8000',   ws: true, configure: silenceECONNREFUSED },
      '/cam': {
        target: 'http://localhost:5000',
        rewrite: (path) => path.replace(/^\/cam/, ''),
        configure: silenceECONNREFUSED,
      },
    },
  },
})
