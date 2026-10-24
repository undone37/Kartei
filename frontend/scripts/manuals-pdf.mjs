// The manuals as print-ready PDFs in the Kartei look: cover, contents with page numbers, numbered chapters.
// Usage: node scripts/manuals-pdf.mjs [--out ../dist] [--version 1.0.0]
// Needs pandoc (>= 3) and pdftotext (poppler-utils); Chromium comes from Playwright.
import { chromium } from 'playwright'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt }
const ROOT = resolve(import.meta.dirname, '../..')
const OUT = resolve(arg('out', join(ROOT, 'dist')))
const VERSION = arg('version', '').replace(/^v/, '') || (() => {
  try { return execFileSync('git', ['describe', '--tags', '--always'], { cwd: ROOT }).toString().trim().replace(/^v/, '') } catch { return 'dev' }
})()

const MANUALS = [
  { lang: 'de', role: 'user', file: 'Kartei-Benutzerhandbuch-DE.pdf', title: 'Benutzerhandbuch', sub: 'Kontakte finden, prüfen und pflegen – für die Rollen Nur Lesen und Bearbeiter' },
  { lang: 'de', role: 'admin', file: 'Kartei-Administrationshandbuch-DE.pdf', title: 'Administrationshandbuch', sub: 'Installation, Einrichtung und Betrieb' },
  { lang: 'en', role: 'user', file: 'Kartei-User-manual-EN.pdf', title: 'User manual', sub: 'Finding, reviewing and maintaining contacts – for the Read only and Maintainer roles' },
  { lang: 'en', role: 'admin', file: 'Kartei-Administrator-manual-EN.pdf', title: 'Administrator manual', sub: 'Installation, configuration and operation' },
]
const WORDS = {
  de: { chapter: 'Kapitel', contents: 'Inhalt', about: 'Über dieses Handbuch', page: 'Seite', of: 'von', version: 'Version', doc: 'Dokumentation' },
  en: { chapter: 'Chapter', contents: 'Contents', about: 'About this manual', page: 'Page', of: 'of', version: 'Version', doc: 'Documentation' },
}

// Kartei design tokens (frontend/src/app.css, light theme)
const T = { ink: '#18181b', muted: '#71717a', border: '#e4e4e7', panel2: '#f2f2f4', accent: '#4f46e5', soft: '#eef2ff',
  accentText: '#3730a3', deep: '#1e1b4b', light: '#c7d2fe', lighter: '#a5b4fc', warn: '#b45309', warnSoft: '#fffbeb' }
const FONT = "'Noto Sans', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
const MONO = "'DejaVu Sans Mono', 'Noto Sans Mono', ui-monospace, monospace"
const LOGO = 'data:image/svg+xml;base64,' + readFileSync(join(ROOT, 'logo.svg')).toString('base64')

const CSS = (w) => `
@page { size: A4; margin: 20mm 18mm 22mm 18mm; }
html { font: 10pt/1.55 ${FONT}; color: ${T.ink}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; }
a { color: ${T.accent}; text-decoration: none; }
p, li { orphans: 3; widows: 3; }
h1, h2, h3 { color: ${T.deep}; line-height: 1.25; letter-spacing: -0.01em; break-after: avoid; }
h1 { break-before: page; font-size: 24pt; font-weight: 700; margin: 0 0 14pt; padding-bottom: 10pt; border-bottom: 1px solid ${T.border}; }
h1[data-number]::before { content: "${w.chapter} " attr(data-number); display: block; margin-bottom: 6pt; color: ${T.accent};
  font-size: 9pt; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; }
h1 .header-section-number { display: none; }
h2 { font-size: 13.5pt; font-weight: 650; margin: 20pt 0 6pt; }
h3 { font-size: 11pt; font-weight: 650; margin: 14pt 0 4pt; }
.header-section-number { color: ${T.accent}; margin-right: 6pt; }
img { display: block; width: auto; height: auto; max-width: 100%; max-height: 112mm; margin: 8pt 0 14pt; border: 1px solid ${T.border}; border-radius: 6px; break-inside: avoid; }
p:has(> img + img) { display: flex; gap: 8mm; align-items: flex-start; break-inside: avoid; } /* phone screenshots side by side */
p:has(> img + img) img { margin: 4pt 0 10pt; }
table { width: 100%; border-collapse: separate; border-spacing: 0; margin: 8pt 0 14pt; font-size: 9pt; border: 1px solid ${T.border}; border-radius: 6px; overflow: hidden; break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: ${T.soft}; color: ${T.accentText}; font-weight: 600; text-align: left; }
th, td { padding: 5pt 8pt; vertical-align: top; border-bottom: 1px solid ${T.border}; }
tbody tr:last-child td { border-bottom: 0; }
code { font: 8.5pt ${MONO}; padding: 0.5pt 3pt; border-radius: 3px; background: ${T.panel2}; }
pre { padding: 8pt 10pt; border-radius: 6px; background: ${T.panel2}; white-space: pre-wrap; break-inside: avoid; }
pre code { padding: 0; background: none; }
kbd { font: 8pt ${MONO}; padding: 0 4pt; border: 1px solid #d4d4d8; border-bottom-width: 2px; border-radius: 4px; }
blockquote { margin: 10pt 0; padding: 8pt 11pt; border-radius: 6px; background: ${T.panel2}; break-inside: avoid; }
blockquote p { margin: 0; }
.tip > blockquote { background: ${T.soft}; color: ${T.accentText}; }
.warn > blockquote { background: ${T.warnSoft}; color: ${T.warn}; }
.tip a, .warn a { color: inherit; text-decoration: underline; }
/* contents */
.toc h1 { break-before: auto; }
.toc ol { list-style: none; margin: 0; padding: 0; }
.toc li { margin: 0; }
.toc a { display: flex; gap: 6pt; color: ${T.ink}; }
.toc .l1 > a { font-weight: 600; margin-top: 7pt; color: ${T.deep}; }
.toc .l2 > a { padding-left: 22pt; color: ${T.muted}; font-size: 9pt; }
.toc .n { min-width: 16pt; color: ${T.accent}; }
.toc .l2 .n { min-width: 26pt; }
.toc .t { flex: 1; display: flex; }
.toc .t::after { content: ""; flex: 1; margin: 0 4pt 3pt; border-bottom: 1px dotted #d4d4d8; }
.toc .p { min-width: 16pt; text-align: right; font-variant-numeric: tabular-nums; }
.mk { font-size: 1px; color: #fff; }
`

// cover: its own named page without margins and footer, part of the same document so links keep working
const COVER = (m, w) => `<section class="cover">
<div class="brand"><img src="${LOGO}" alt="">Kartei</div>
<img class="mark" src="${LOGO}" alt="">
<div class="main"><div class="label">${w.doc}</div><div class="title">${m.title}</div><div class="sub">${m.sub}</div></div>
<div class="meta">${w.version} ${VERSION} · ${new Intl.DateTimeFormat(m.lang, { month: 'long', year: 'numeric' }).format(new Date())}</div>
</section>`
const COVER_CSS = `
@page cover { margin: 0; background: ${T.deep}; @bottom-left { content: none } @bottom-right { content: none } }
.cover { page: cover; width: 210mm; height: 297mm; position: relative; overflow: hidden; color: #fff; }
.cover .brand { position: absolute; top: 24mm; left: 22mm; display: flex; align-items: center; gap: 12px; font-size: 20pt; font-weight: 650; letter-spacing: -0.02em; }
.cover .brand img { width: 15mm; height: 15mm; margin: 0; border: 0; }
.cover .mark { position: absolute; right: -40mm; bottom: -30mm; width: 190mm; max-width: none; max-height: none; margin: 0; border: 0; opacity: 0.07; }
.cover .main { position: absolute; left: 22mm; right: 30mm; top: 118mm; }
.cover .label { color: ${T.lighter}; font-size: 10pt; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; }
.cover .title { margin: 6mm 0; font-size: 40pt; line-height: 1.1; font-weight: 700; letter-spacing: -0.02em; }
.cover .sub { color: ${T.light}; font-size: 14pt; line-height: 1.45; max-width: 140mm; }
.cover .meta { position: absolute; left: 22mm; bottom: 24mm; color: ${T.lighter}; font-size: 10pt; }
`

/** kramdown → pandoc markdown: front matter and title go to the cover, `{: .tip}` becomes a div, site links become text */
function prepare(md, w) {
  md = md.replace(/^---\n[\s\S]*?\n---\n/, '').replace(/^# .*\n/m, `## ${w.about} {.unnumbered}\n`)
  const out = []
  for (const line of md.split('\n')) {
    const ial = line.trim().match(/^\{:\s*\.(\w+)\s*\}$/)
    if (!ial) { out.push(line); continue }
    let start = out.length
    while (start && out[start - 1].startsWith('>')) start--
    out.splice(start, Infinity, `::: ${ial[1]}`, ...out.slice(start), ':::')
  }
  return out.join('\n').replaceAll('){: ', '){').replace(/\[([^\]]+)\]\((?:\.\.\/(?:de|en)\/)?(?:user|admin)\.html[^)]*\)/g, '$1')
}

const FOOTER_CSS = (m, w) => `
@page { @bottom-left { content: "Kartei · ${m.title} · ${w.version} ${VERSION}"; font: 7.5pt ${FONT}; color: ${T.muted}; }
        @bottom-right { content: "${w.page} " counter(page) " ${w.of} " counter(pages); font: 7.5pt ${FONT}; color: ${T.muted}; } }
`

async function pdf(page, html, path) {
  const file = join(tmp, 'page.html')  // images are file:// URLs, so the page must be a file too
  writeFileSync(file, html)
  await page.goto(pathToFileURL(file).href, { waitUntil: 'load' })
  await page.pdf({ path, format: 'A4', printBackground: true, preferCSSPageSize: true })
}

const browser = await chromium.launch()
const page = await browser.newPage()
const tmp = mkdtempSync(join(tmpdir(), 'kartei-pdf-'))
mkdirSync(OUT, { recursive: true })
try {
  for (const m of MANUALS) {
    const w = WORDS[m.lang]
    const dir = join(ROOT, 'manuals', m.lang)
    let body = execFileSync('pandoc', ['-f', 'markdown-implicit_figures', '-t', 'html5', '--shift-heading-level-by=-1', '--number-sections'],
      { input: prepare(readFileSync(join(dir, `${m.role}.md`), 'utf8'), w), maxBuffer: 64 << 20 }).toString()
    body = body.replace(/<colgroup>[\s\S]*?<\/colgroup>/g, '').replace(/src="\.\.\/img\//g, `src="${pathToFileURL(join(ROOT, 'manuals/img')).href}/`)

    // contents from the chapter (h1) and section (h2) headings; each heading gets a marker to find its page
    const heads = []
    body = body.replace(/<h([12])([^>]*)>([\s\S]*?)<\/h\1>/g, (all, lvl, attrs, inner) => {
      const id = attrs.match(/id="([^"]+)"/)?.[1]
      if (!id) return all
      const num = attrs.match(/data-number="([^"]+)"/)?.[1] || ''
      heads.push({ lvl, id, num, text: inner.replace(/<[^>]+>/g, '').trim().replace(/^[\d.]+\s+/, '') })
      return `<h${lvl}${attrs}>${inner}<span class="mk">QQ${heads.length - 1}QQ</span></h${lvl}>`
    })
    const toc = (pages) => `<section class="toc"><h1>${w.contents}</h1><ol>${heads.map((h, i) =>
      `<li class="l${h.lvl}"><a href="#${h.id}"><span class="n">${h.num}</span><span class="t">${h.text}</span><span class="p">${pages?.[i] ?? '00'}</span></a></li>`).join('')}</ol></section>`
    const doc = (pages, marks) => `<!doctype html><html lang="${m.lang}"><head><meta charset="utf-8"><title>Kartei – ${m.title}</title>
      <style>${CSS(w)}${FOOTER_CSS(m, w)}${COVER_CSS}</style></head><body>${COVER(m, w)}${toc(pages)}${marks ? body : body.replace(/<span class="mk">QQ\d+QQ<\/span>/g, '')}</body></html>`

    // pass 1: find each heading's page; pass 2: the final PDF with the page numbers in the contents
    const body1 = join(tmp, `${m.role}-${m.lang}-1.pdf`)
    await pdf(page, doc(null, true), body1)
    const pages = {}
    execFileSync('pdftotext', [body1, '-']).toString().split('\f').forEach((text, p) => {
      for (const [, i] of text.matchAll(/QQ(\d+)QQ/g)) pages[i] ??= p + 1
    })
    await pdf(page, doc(pages, false), join(OUT, m.file))
    console.log(join(OUT, m.file))
  }
} finally {
  await browser.close()
  rmSync(tmp, { recursive: true, force: true })
}
