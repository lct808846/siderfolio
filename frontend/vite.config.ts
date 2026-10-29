import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    allowedHosts: ['localhost', '127.0.0.1'],
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  test: { environment: 'jsdom', include: ['tests/unit/**/*.test.ts'] },
})
