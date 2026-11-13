// Production-build local static server and API proxy. No Vite dependency at runtime.
import http from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(fileURLToPath(new URL('./dist/', import.meta.url)))
const port = Number(process.env.FRONTEND_PORT || 5173)
const backend = new URL(process.env.ASTROAGENT_API_TARGET || 'http://127.0.0.1:8000')
const containerMode = process.env.ASTROAGENT_DEPLOYMENT_MODE === 'container'
if (backend.protocol !== 'http:' || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash || (containerMode ? backend.origin !== 'http://backend:8000' : !['127.0.0.1', 'localhost', '[::1]'].includes(backend.hostname))) throw new Error('Unsupported fixed API origin')
const proxyToken = containerMode ? (await readFile('/run/secrets/proxy_token', 'utf8')).trim() : ''
if (containerMode && !/^[0-9a-f]{64}$/.test(proxyToken)) throw new Error('Proxy credential is missing')
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json' }
const server = http.createServer(async (req, res) => {
  const host = req.headers.host?.split(':')[0]
  if (!['127.0.0.1', 'localhost'].includes(host)) { res.writeHead(400); return res.end('Invalid local host') }
  if (req.headers['sec-fetch-site'] === 'cross-site') { res.writeHead(403); return res.end('Unsupported request origin') }
  let url
  try { url = new URL(req.url || '/', 'http://127.0.0.1') } catch { res.writeHead(400); return res.end() }
  if (url.pathname.startsWith('/api/') || ['/health', '/docs', '/redoc', '/openapi.json', '/docs/oauth2-redirect'].includes(url.pathname)) {
    const headers = { ...req.headers, host: '127.0.0.1:8000' }
    for (const name of ['x-astroagent-proxy', 'forwarded', 'x-forwarded-host', 'x-forwarded-for', 'x-forwarded-proto', 'proxy-authorization', 'connection', 'upgrade']) delete headers[name]
    if (containerMode) headers['x-astroagent-proxy'] = proxyToken
    const upstream = http.request(new URL(url.pathname + url.search, backend), { method: req.method, headers }, reply => {
      res.writeHead(reply.statusCode || 502, reply.headers); reply.pipe(res)
    })
    upstream.on('error', () => { if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: { code: 'backend_unavailable', message: '后端未连接，请启动本机服务。', retryable: true } })) })
    upstream.setTimeout(360000, () => upstream.destroy())
    req.on('aborted', () => upstream.destroy())
    req.pipe(upstream)
    return
  }
  if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end() }
  try {
    const pathname = decodeURIComponent(url.pathname)
    let file = path.resolve(root, '.' + pathname)
    if (file !== root && !file.startsWith(root + path.sep)) { res.writeHead(404); return res.end() }
    if (!path.extname(pathname)) file = path.join(root, 'index.html')
    if (!(await stat(file)).isFile()) { res.writeHead(404); return res.end() }
    const bytes = await readFile(file)
    res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; img-src 'self' blob: data: http://127.0.0.1:* http://localhost:*; style-src 'self' 'unsafe-inline'; connect-src 'self' http://127.0.0.1:* http://localhost:*; script-src 'self'; object-src 'none'; frame-ancestors 'none'" })
    res.end(req.method === 'HEAD' ? undefined : bytes)
  } catch { res.writeHead(404); res.end('Not found') }
})
server.listen(port, containerMode ? '0.0.0.0' : '127.0.0.1', () => console.log(`AstroAgent frontend port ${port}`))
