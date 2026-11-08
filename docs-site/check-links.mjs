// After `astro build`: every internal link and #anchor in dist/ must exist, including the targets of the redirect
// pages for the old one-page addresses (/de/admin.html#…). Run: npm run check (CI does).
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const DIST = 'dist', BASE = '/Kartei'
const files = readdirSync(DIST, { recursive: true }).filter((f) => f.endsWith('.html')).map((f) => join(DIST, f))
const ids = new Map()
const page = (url) => {
  let p = join(DIST, decodeURI(url.slice(BASE.length)))
  if (existsSync(p) && statSync(p).isDirectory()) p = join(p, 'index.html')
  if (!existsSync(p)) return null
  if (!ids.has(p)) ids.set(p, new Set([...readFileSync(p, 'utf8').matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])))
  return ids.get(p)
}
const bad = []
const check = (from, url) => {
  const [path, hash] = url.split('#')
  const target = path ? page(path) : page(from)
  if (!target) bad.push(`${from}: ${url} (no page)`)
  else if (hash && !target.has(decodeURIComponent(hash)) && hash !== '_top') bad.push(`${from}: ${url} (no #${hash})`)
}
let n = 0
for (const f of files) {
  const html = readFileSync(f, 'utf8')
  const self = BASE + '/' + f.slice(DIST.length + 1).replace(/index\.html$/, '')
  for (const [, url] of html.matchAll(/\shref="([^"]+)"/g)) {
    if (url.startsWith(BASE + '/') && !/\.(css|js|svg|png|webp|xml|ico)$/.test(url.split('#')[0])) { check(self, url); n++ }
    else if (url.startsWith('#') && url.length > 1) { check(self, url); n++ }
  }
  const map = html.match(/const m=(\{.*?\});location/)?.[1]
  if (map) for (const url of Object.values(JSON.parse(map))) { check(self, url); n++ }
  for (const [, src] of html.matchAll(/\ssrc="(\/Kartei\/img\/[^"]+)"/g)) if (!existsSync(join(DIST, src.slice(BASE.length)))) bad.push(`${self}: ${src} (no image)`)
}
console.log(`${files.length} pages, ${n} internal links checked`)
if (bad.length) { console.error(bad.join('\n')); process.exit(1) }
