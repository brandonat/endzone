import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

// Draft night only: this app is never deployed, so it always talks to
// draft_server.py running on this machine.
export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:8001',
    },
  },
})
