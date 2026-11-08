/**
 * The manuals (../manuals/{en,de}/{user,admin}.md) stay one Markdown file each: the PDF manuals and the screenshot
 * script use them as they are. For the site, each manual becomes an overview page (the text before the first chapter)
 * plus one page per chapter (## heading). DE and EN have the same chapters in the same order, so both languages use
 * the English chapter slug and the language switch lands on the same chapter.
 *
 * Kramdown syntax is turned into what Starlight understands: `> … {: .tip}` / `{: .warn}` into asides, `{#id}` on
 * headings dropped (links are rewritten anyway), `![…](…){: width="320"}` into <img width>. Links to `#anchor` and to
 * `user.html#anchor` are rewritten to the page that now holds the heading. The old addresses (`/de/admin.html#x`)
 * keep working through redirect pages (src/pages/[lang]/[manual].html.ts) built from the same anchor map.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

export const LANGS = ['en', 'de'] as const
export const MANUALS = ['user', 'admin'] as const
type Lang = (typeof LANGS)[number]
type Manual = (typeof MANUALS)[number]

// ponytail: relative to the working directory (npm scripts run in docs-site/); import.meta.url moves when bundled
export const SRC = resolve(process.cwd(), '../manuals') + '/'
const WORDS = {
  en: { overview: 'About this manual', tip: 'Tip', warn: 'Caution' },
  de: { overview: 'Über dieses Handbuch', tip: 'Tipp', warn: 'Achtung' },
}

/** Heading id as kramdown (GFM) and github-slugger make it: lower case, only letters, digits, marks, _ - and spaces. */
export function slug(text: string) {
  return text.toLowerCase().trim().replace(/[^\p{L}\p{N}\p{M}\p{Pc}\- ]/gu, '').replace(/ /g, '-')
}

/** Unique per scope like both generators: the second "Emails" becomes "emails-1". */
function slugger() {
  const seen = new Map<string, number>()
  return (text: string) => {
    const base = slug(text)
    const n = seen.get(base)
    seen.set(base, (n ?? -1) + 1)
    return n === undefined ? base : `${base}-${n + 1}`
  }
}

const HEADING = /^(#{2,6}) +(.+?)(?: *\{#([^}]+)\})? *$/

/** Plain text of a heading as it ends up in the HTML (no Markdown emphasis or code marks). */
function plain(md: string) {
  return md.replace(/`([^`]*)`/g, '$1').replace(/\*\*?([^*]+)\*\*?/g, '$1').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').trim()
}

export interface Page {
  id: string // content id, e.g. "user/reviews" or "de/user/reviews"
  lang: Lang
  manual: Manual
  title: string
  order: number
  body: string // Markdown for Starlight
  source: string // repo path of the Markdown source
}

interface Parsed {
  title: string
  intro: string
  chapters: { title: string; lines: string[] }[]
}

function parse(lang: Lang, manual: Manual): Parsed {
  const text = readFileSync(`${SRC}${lang}/${manual}.md`, 'utf8').replace(/^---\n[\s\S]*?\n---\n/, '')
  const lines = text.split('\n')
  let title = ''
  const intro: string[] = []
  const chapters: Parsed['chapters'] = []
  let fence = false
  for (const line of lines) {
    if (/^(```|~~~)/.test(line)) fence = !fence
    if (!fence && /^# /.test(line) && !title) title = line.slice(2).trim()
    else if (!fence && /^## /.test(line)) chapters.push({ title: plain(line.match(HEADING)![2]), lines: [line] })
    else (chapters.at(-1)?.lines ?? intro).push(line)
  }
  return { title, intro: intro.join('\n').trim(), chapters }
}

/** Old anchor (kramdown id of the one-page manual) → new address, per language and manual. */
export type AnchorMap = Record<string, string>

export function build(base: string) {
  const root = base.replace(/\/$/, '')
  const parsed = Object.fromEntries(LANGS.map((l) => [l, Object.fromEntries(MANUALS.map((m) => [m, parse(l, m)]))])) as
    Record<Lang, Record<Manual, Parsed>>
  for (const m of MANUALS) {
    if (parsed.en[m].chapters.length !== parsed.de[m].chapters.length) {
      throw new Error(`manuals/${m}.md: EN and DE need the same chapters (${parsed.en[m].chapters.length} vs ${parsed.de[m].chapters.length})`)
    }
  }
  const prefix = (l: Lang) => (l === 'en' ? '' : `${l}/`)
  const chapterSlugs = Object.fromEntries(MANUALS.map((m) => {
    const s = slugger()
    return [m, parsed.en[m].chapters.map((c) => s(c.title))]
  })) as Record<Manual, string[]>
  const pageUrl = (l: Lang, m: Manual, i: number | null) =>
    `${root}/${prefix(l)}${m}/${i === null ? '' : chapterSlugs[m][i] + '/'}`

  // pass 1: where every old anchor lives now
  const anchors = {} as Record<Lang, Record<Manual, AnchorMap>>
  for (const l of LANGS) {
    anchors[l] = {} as Record<Manual, AnchorMap>
    for (const m of MANUALS) {
      const map: AnchorMap = {}
      const old = slugger()
      old(parsed[l][m].title) // the h1 had an id too
      parsed[l][m].chapters.forEach((c, i) => {
        const now = slugger()
        let fence = false
        for (const line of c.lines) {
          if (/^(```|~~~)/.test(line)) fence = !fence
          const h = !fence && line.match(HEADING)
          if (!h) continue
          const auto = old(plain(h[2]))
          const url = h[1] === '##' ? pageUrl(l, m, i) : `${pageUrl(l, m, i)}#${now(plain(h[2]))}`
          map[auto] = url
          if (h[3]) map[h[3]] = url
        }
      })
      anchors[l][m] = map
    }
  }

  // pass 2: the pages
  const pages: Page[] = []
  for (const l of LANGS) {
    for (const m of MANUALS) {
      const link = (target: string) => {
        const [file, hash = ''] = target.split('#')
        const other = (file.match(/^(user|admin)\.html$/)?.[1] ?? (file === '' ? m : null)) as Manual | null
        if (!other) return target
        if (!hash) return pageUrl(l, other, null)
        return anchors[l][other][hash] ?? (console.warn(`manuals/${l}/${m}.md: unknown anchor #${hash}`), pageUrl(l, other, null))
      }
      const convert = (lines: string[]) => markdown(lines, l, link, root)
      const p = parsed[l][m]
      const source = `manuals/${l}/${m}.md`
      pages.push({ id: `${prefix(l)}${m}`, lang: l, manual: m, title: p.title, order: 0, source,
        body: convert(p.intro.split('\n')) })
      p.chapters.forEach((c, i) => pages.push({
        id: `${prefix(l)}${m}/${chapterSlugs[m][i]}`, lang: l, manual: m, title: c.title, order: i + 1, source,
        body: convert(c.lines.slice(1)),
      }))
    }
  }
  return { pages, anchors, words: WORDS }
}

/** Kramdown → Starlight Markdown for one page; headings move up one level (the chapter is the page title). */
function markdown(lines: string[], lang: Lang, link: (t: string) => string, root: string) {
  const out: string[] = []
  let fence = false
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i]
    if (/^\s*(```|~~~)/.test(line)) fence = !fence
    if (fence || /^\s*(```|~~~)/.test(line)) { out.push(line); continue }
    // > text … followed by {: .tip} / {: .warn}: an aside
    if (line.startsWith('>') && !lines[i - 1]?.startsWith('>')) {
      let j = i
      while (lines[j + 1]?.startsWith('>')) j++
      const kind = lines[j + 1]?.match(/^\{: \.(tip|warn)\}\s*$/)?.[1]
      if (kind) {
        const body = lines.slice(i, j + 1).map((x) => x.replace(/^> ?/, ''))
        const w = WORDS[lang]
        out.push(`:::${kind === 'tip' ? 'tip' : 'caution'}[${kind === 'tip' ? w.tip : w.warn}]`,
          ...body.map((x) => rewrite(x, link, root)), ':::')
        i = j + 1
        continue
      }
    }
    const h = line.match(HEADING)
    if (h) line = `${h[1].slice(1)} ${h[2]}`
    out.push(rewrite(line, link, root))
  }
  return out.join('\n').trim() + '\n'
}

function rewrite(line: string, link: (t: string) => string, root: string) {
  return line
    // images with a width: HTML (Markdown has no width)
    .replace(/!\[([^\]]*)\]\(\.\.\/img\/([^)\s]+)\)\{: width="(\d+)"\}/g,
      (_, alt, src, w) => `<img src="${root}/img/${src}" alt="${alt.replace(/"/g, '&quot;')}" width="${w}" />`)
    .replace(/(!\[[^\]]*\]\()\.\.\/img\//g, `$1${root}/img/`)
    .replace(/(?<!!)\[([^\]]+)\]\(((?:user|admin)\.html(?:#[^)]*)?|#[^)]+)\)/g, (_, text, target) => `[${text}](${link(target)})`)
}
