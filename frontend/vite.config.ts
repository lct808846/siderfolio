import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

const devProxyToken = process.env.ASTROAGENT_DEV_PROXY_TOKEN
const apiTarget = devProxyToken ? 'http://backend:8000' : 'http://127.0.0.1:8000'
const apiProxy = { target: apiTarget, changeOrigin: false }
const untrustedClientHeaders = [
  'x-astroagent-client-address',
  'x-astroagent-client-country',
  'x-astroagent-client-region',
  'x-astroagent-client-city',
  'x-astroagent-edge-client',
  'x-astroagent-edge-country',
  'x-astroagent-edge-region',
  'x-astroagent-edge-city',
  'x-forwarded-for',
]

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    allowedHosts: ['localhost', '127.0.0.1'],
    watch: devProxyToken ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      '/api': devProxyToken ? {
        ...apiProxy,
        configure(proxy) {
          proxy.on('proxyReq', (request, req) => {
            for (const header of untrustedClientHeaders) {
              request.removeHeader(header)
            }
            const peer = (req.socket?.remoteAddress || '').replace(/^::ffff:/, '')
            if (peer) request.setHeader('x-astroagent-client-address', peer)
            request.setHeader('x-astroagent-proxy', devProxyToken)
          })
        },
      } : apiProxy,
      '/health': apiProxy,
      '/docs': apiProxy,
      '/redoc': apiProxy,
      '/openapi.json': apiProxy,
    },
  },
  test: { environment: 'jsdom', include: ['tests/unit/**/*.test.ts'] },
})
