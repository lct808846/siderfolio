// Production-build local static server and API proxy. No Vite dependency at runtime.
import http from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { lookup } from 'node:dns/promises'
import { isIP } from 'node:net'
import { gzipSync } from 'node:zlib'

const root = path.resolve(fileURLToPath(new URL('./dist/', import.meta.url)))
const port = Number(process.env.FRONTEND_PORT || 5173)
const backend = new URL(process.env.ASTROAGENT_API_TARGET || 'http://127.0.0.1:8000')
const backendAgent = new http.Agent({ keepAlive: true, keepAliveMsecs: 30000, maxSockets: 64 })
const containerMode = process.env.ASTROAGENT_DEPLOYMENT_MODE === 'container'
if (backend.protocol !== 'http:' || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash || (containerMode ? backend.origin !== 'http://backend:8000' : !['127.0.0.1', 'localhost', '[::1]'].includes(backend.hostname))) throw new Error('Unsupported fixed API origin')
const proxyToken = containerMode ? (await readFile('/run/secrets/proxy_token', 'utf8')).trim() : ''
const site = new URL(process.env.ASTROAGENT_SITE_ORIGIN || 'http://127.0.0.1:5173')
if (site.protocol !== 'https:' && !['127.0.0.1', 'localhost'].includes(site.hostname)) throw new Error('Remote site requires HTTPS')
const publicPages = new Set(['/login', '/register', '/activate', '/resend', '/forgot-password', '/reset-password'])
let ingressCache = { addresses: new Set(), expiresAt: 0 }
async function ingressAddresses() {
  const now = Date.now()
  if (now < ingressCache.expiresAt && ingressCache.addresses.size > 0) return ingressCache.addresses
  const entries = await lookup('ingress', { all: true })
  const next = new Set(entries.map(item => item.address))
  ingressCache = { addresses: next, expiresAt: now + 10000 }
  return next
}
async function clientAddress(req) {
  const address = (req.socket.remoteAddress || '').replace(/^::ffff:/, '')
  if (containerMode) {
    try {
      const trusted = await ingressAddresses()
      const claimed = req.headers['x-astroagent-edge-client']
      if (trusted.has(address) && typeof claimed === 'string' && isIP(claimed)) return claimed.replace(/^::ffff:/, '')
    } catch { /* Unknown proxies never get to select an authentication source. */ }
  }
  return address
}
async function signedIn(req) {
  const address = containerMode ? await clientAddress(req) : ''
  return new Promise(resolve => {
    const check = http.request(new URL('/api/v1/auth/session', backend), { agent: backendAgent, headers: { host: '127.0.0.1:8000', cookie: req.headers.cookie || '', ...(containerMode ? { 'x-astroagent-proxy': proxyToken, 'x-astroagent-client-address': address } : {}) } }, reply => { reply.resume(); resolve(reply.statusCode || 503) })
    check.setTimeout(5000, () => check.destroy())
    check.on('error', () => resolve(503)); check.end()
  })
}
if (containerMode && !/^[0-9a-f]{64}$/.test(proxyToken)) throw new Error('Proxy credential is missing')
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf' }
const compressibleExt = new Set(['.html', '.js', '.css', '.svg', '.json'])
const staticCache = new Map()
async function loadStaticAsset(file) {
  const cached = staticCache.get(file)
  if (cached) return cached
  const info = await stat(file)
  if (!info.isFile()) return null
  const raw = await readFile(file)
  const ext = path.extname(file)
  const gzipped = compressibleExt.has(ext) && raw.length > 1024 ? gzipSync(raw, { level: 6 }) : null
  const entry = { raw, gzipped, contentType: mime[ext] || 'application/octet-stream' }
  if (staticCache.size < 128) staticCache.set(file, entry)
  return entry
}
const server = http.createServer(async (req, res) => {
  const host = req.headers.host?.split(':')[0]
  if (!['127.0.0.1', 'localhost', site.hostname].includes(host)) { res.writeHead(400); return res.end('Invalid trusted host') }
  let url
  try { url = new URL(req.url || '/', 'http://127.0.0.1') } catch { res.writeHead(400); return res.end() }
  // Email links are cross-site document navigations. Loading their public page
  // must not activate/reset anything; writes still require same-origin CSRF.
  const publicNavigation = ['GET', 'HEAD'].includes(req.method) && publicPages.has(url.pathname)
    && req.headers['sec-fetch-mode'] === 'navigate' && req.headers['sec-fetch-dest'] === 'document'
  if (req.headers['sec-fetch-site'] === 'cross-site' && !publicNavigation) { res.writeHead(403); return res.end('Unsupported request origin') }
  if (url.pathname === '/__internal/health') {
    const local = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress || '')
    res.writeHead(local ? 200 : 404); return res.end(local ? 'ok' : '')
  }
  if (url.pathname === '/health') { res.writeHead(404); return res.end() }
  if (url.pathname.startsWith('/api/') || ['/health', '/docs', '/redoc', '/openapi.json', '/docs/oauth2-redirect'].includes(url.pathname)) {
    const headers = { ...req.headers, host: '127.0.0.1:8000' }
    for (const name of ['x-astroagent-proxy', 'x-astroagent-client-address', 'x-astroagent-edge-client', 'forwarded', 'x-forwarded-host', 'x-forwarded-for', 'x-forwarded-proto', 'proxy-authorization', 'connection', 'upgrade']) delete headers[name]
    if (containerMode) headers['x-astroagent-proxy'] = proxyToken
    if (containerMode) headers['x-astroagent-client-address'] = await clientAddress(req)
    const upstream = http.request(new URL(url.pathname + url.search, backend), { agent: backendAgent, method: req.method, headers }, reply => {
      res.writeHead(reply.statusCode || 502, reply.headers)
      if (reply.headers['content-type']?.includes('text/event-stream')) res.flushHeaders()
      reply.pipe(res)
    })
    upstream.on('error', () => {
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: { code: 'backend_unavailable', message: '后端未连接，请启动本机服务。', retryable: true } }))
      } else if (!res.writableEnded) {
        res.end()
      }
    })
    upstream.setTimeout(360000, () => upstream.destroy())
    req.on('aborted', () => upstream.destroy())
    res.on('close', () => { if (!res.writableEnded) upstream.destroy() })
    req.pipe(upstream)
    return
  }
  if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end() }
  try {
    const pathname = decodeURIComponent(url.pathname)
    let file = path.resolve(root, '.' + pathname)
    if (file !== root && !file.startsWith(root + path.sep)) { res.writeHead(404); return res.end() }
    if (!path.extname(pathname)) file = path.join(root, 'index.html')
    const isHtmlEntry = file === path.join(root, 'index.html')
    if (isHtmlEntry && !publicPages.has(pathname)) {
      const status = await signedIn(req)
      if (status === 401) { res.writeHead(302, { Location: '/login?next=' + encodeURIComponent(url.pathname + url.search), 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' }); return res.end() }
      if (status !== 200) { res.writeHead(503, { 'Cache-Control': 'no-store' }); return res.end('Identity service unavailable') }
    }
    const asset = await loadStaticAsset(file)
    if (!asset) { res.writeHead(404); return res.end() }
    const isImmutableBundle = pathname.startsWith('/assets/') && !isHtmlEntry
    const acceptsGzip = /\bgzip\b/i.test(String(req.headers['accept-encoding'] || ''))
    const useGzip = Boolean(asset.gzipped && acceptsGzip)
    const body = useGzip ? asset.gzipped : asset.raw
    res.writeHead(200, {
      'Content-Type': asset.contentType,
      'Content-Length': String(body.length),
      ...(useGzip ? { 'Content-Encoding': 'gzip', Vary: 'Accept-Encoding' } : {}),
      'Cache-Control': isImmutableBundle ? 'public, max-age=31536000, immutable' : 'no-store',
      'Referrer-Policy': 'no-referrer',
      'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': "default-src 'self'; img-src 'self' blob: data:; frame-src 'self' blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    })
    res.end(req.method === 'HEAD' ? undefined : body)
  } catch { res.writeHead(404); res.end('Not found') }
})
server.listen(port, containerMode ? '0.0.0.0' : '127.0.0.1', () => console.log(`AstroAgent frontend port ${port}`))
