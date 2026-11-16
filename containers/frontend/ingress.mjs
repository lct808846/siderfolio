// Loopback-published entry point. It has no application secrets or Docker access.
import http from 'node:http'
const site = new URL(process.env.ASTROAGENT_SITE_ORIGIN || 'http://127.0.0.1:5173')
if (site.protocol !== 'https:' && !['127.0.0.1', 'localhost'].includes(site.hostname)) throw new Error('Remote site requires HTTPS')

const server = http.createServer((request, response) => {
  const host = request.headers.host?.split(':')[0]
  if (!['127.0.0.1', 'localhost', site.hostname].includes(host)) {
    response.writeHead(400); response.end('Invalid local host'); return
  }
  const path = (request.url || '/').split('?')[0]
  if (path === '/health' || path === '/__internal/health') {
    const local = path === '/__internal/health' && ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(request.socket.remoteAddress || '')
    response.writeHead(local ? 200 : 404); response.end(local ? 'ok' : ''); return
  }
  const headers = { ...request.headers, 'x-astroagent-edge-client': request.socket.remoteAddress || '' }
  delete headers['x-astroagent-client-address']
  const upstream = http.request({ hostname: 'frontend', port: 5173, method: request.method, path: request.url, headers }, reply => {
    response.writeHead(reply.statusCode || 502, reply.headers)
    reply.pipe(response)
  })
  upstream.on('error', () => {
    if (!response.headersSent) response.writeHead(502, { 'Content-Type': 'text/plain' })
    response.end('Frontend unavailable')
  })
  upstream.setTimeout(360000, () => upstream.destroy())
  request.on('aborted', () => upstream.destroy())
  request.pipe(upstream)
})
server.listen(5173, '0.0.0.0')
