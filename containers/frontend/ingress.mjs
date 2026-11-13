// Loopback-published entry point. It has no application secrets or Docker access.
import http from 'node:http'

const server = http.createServer((request, response) => {
  const host = request.headers.host?.split(':')[0]
  if (!['127.0.0.1', 'localhost'].includes(host)) {
    response.writeHead(400); response.end('Invalid local host'); return
  }
  const upstream = http.request({ hostname: 'frontend', port: 5173, method: request.method, path: request.url, headers: request.headers }, reply => {
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
