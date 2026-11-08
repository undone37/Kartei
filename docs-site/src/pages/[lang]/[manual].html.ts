import type { APIRoute } from 'astro'
import { build, LANGS, MANUALS } from '../../manuals'

/** The old one-page addresses (/de/admin.html#reverse-proxy) forward to the chapter page that now holds the anchor. */
export function getStaticPaths() {
  return LANGS.flatMap((lang) => MANUALS.map((manual) => ({ params: { lang, manual } })))
}

export const GET: APIRoute = ({ params }) => {
  const lang = params.lang as (typeof LANGS)[number]
  const manual = params.manual as (typeof MANUALS)[number]
  const base = import.meta.env.BASE_URL.replace(/\/$/, '')
  const { anchors } = build(base)
  const home = `${base}/${lang === 'en' ? '' : 'de/'}${manual}/`
  const html = `<!doctype html><html lang="${lang}"><head><meta charset="utf-8">
<title>Kartei</title><link rel="canonical" href="${home}"><meta name="robots" content="noindex">
<script>const m=${JSON.stringify(anchors[lang][manual])};location.replace(m[decodeURIComponent(location.hash.slice(1))]||${JSON.stringify(home)})</script>
<meta http-equiv="refresh" content="0; url=${home}"></head><body><a href="${home}">Kartei</a></body></html>`
  return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
}
