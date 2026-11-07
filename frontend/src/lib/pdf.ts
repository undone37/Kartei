// A small PDF writer for tables (the phone list): A4, portrait or landscape, heading row on every page, page numbers.
// Uses the PDF standard fonts Helvetica / Helvetica-Bold (built into every PDF viewer, nothing embedded) with
// WinAnsiEncoding, so German and most Western European text works; other characters become "?".
// ponytail: one font, plain table layout; a PDF library only if documents get richer (images, wrapping, fonts).

export interface TableDoc {
  title: string
  subtitle: string
  head: string[]
  /** "group": a heading row (e.g. the company) kept together with the row after it; "strong": bold row */
  rows: { kind?: 'row' | 'group' | 'strong'; cells: string[] }[]
  /** footer text per page, e.g. "Page 2 of 5" */
  footer: (page: number, pages: number) => string
  /** shown top left on the first page: a JPEG (any image can be drawn on a canvas and saved as one) */
  logo?: { jpeg: Uint8Array; width: number; height: number }
}

// Helvetica and Helvetica-Bold widths (1/1000 em) for ASCII 32–126, from the standard font metrics (AFM)
const W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
  556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
  722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
  278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
const WB = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
  556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833,
  722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556,
  333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
// WinAnsi (Windows-1252) bytes 0x80–0x9F that differ from Latin-1
const ANSI: Record<string, number> = { '€': 0x80, '‚': 0x82, '„': 0x84, '…': 0x85, '‘': 0x91, '’': 0x92, '“': 0x93,
  '”': 0x94, '•': 0x95, '–': 0x96, '—': 0x97, '™': 0x99, 'Š': 0x8a, 'š': 0x9a, 'Œ': 0x8c, 'œ': 0x9c, 'Ž': 0x8e, 'ž': 0x9e, 'Ÿ': 0x9f }
const SPECIAL: Record<string, number> = { '€': 556, '…': 1000, '–': 556, '—': 1000, '„': 333, '“': 333, '”': 333,
  '‚': 222, '‘': 222, '’': 222, '•': 350, ß: 611, Æ: 1000, æ: 889, Ø: 778, ø: 611, '·': 278, '°': 400, '§': 556 }

/** a character as its WinAnsi byte, or "?" */
function code(ch: string): number {
  const c = ch.codePointAt(0)!
  if (c >= 32 && c < 127) return c
  if (ANSI[ch]) return ANSI[ch]
  if (c >= 0xa0 && c <= 0xff) return c
  const base = ch.normalize('NFD')[0]  // e.g. "ł" has none: "?"
  return base !== ch && base.codePointAt(0)! < 127 ? base.codePointAt(0)! : 63
}

/** text width in points */
export function width(text: string, size: number, bold = false): number {
  const t = bold ? WB : W
  let w = 0
  for (const ch of text) {
    const c = ch.codePointAt(0)!
    if (c >= 32 && c < 127) w += t[c - 32]
    else if (SPECIAL[ch]) w += SPECIAL[ch]
    else {
      const base = ch.normalize('NFD')[0].codePointAt(0)!  // "ä" is as wide as "a"
      w += base >= 32 && base < 127 ? t[base - 32] : 556
    }
  }
  return (w * size) / 1000
}

/** shortened with "…" to fit */
export function fit(text: string, max: number, size: number, bold = false): string {
  if (width(text, size, bold) <= max + 0.01) return text  // 0.01: (w + pad) - pad isn't always w in floating point
  const chars = [...text]
  while (chars.length && width(chars.join('') + '…', size, bold) > max + 0.01) chars.pop()
  return chars.join('').trimEnd() + '…'
}

const str = (text: string) =>
  '(' + [...text].map((ch) => {
    const b = code(ch)
    return b === 40 || b === 41 || b === 92 ? '\\' + String.fromCharCode(b) : String.fromCharCode(b)
  }).join('') + ')'
const n = (v: number) => (Math.round(v * 100) / 100).toString()

export function tablePdf(input: TableDoc): Uint8Array<ArrayBuffer> {
  // a column nobody has a value in (e.g. private fax) says nothing on paper: left out, the others get its space
  const keep = input.head.map((_, i) => i === 0 || input.rows.some((r) => (r.cells[i] ?? '').trim()))
  const doc = { ...input, head: input.head.filter((_, i) => keep[i]),
                rows: input.rows.map((r) => ({ ...r, cells: r.cells.filter((_, i) => keep[i]) })) }
  const pad = 8, margin = 40
  // natural column widths: the widest cell of each column, then the page that fits them
  const measure = (sz: number) => doc.head.map((h, i) => Math.max(width(h, sz, true),
    ...doc.rows.filter((r) => r.kind !== 'group').map((r) => width(r.cells[i] ?? '', sz, r.kind === 'strong'))) + pad)
  const total = (ws: number[]) => ws.reduce((a, b) => a + b, 0)
  const landscape = total(measure(9)) > 595.28 - 2 * margin
  const [pw, ph] = landscape ? [841.89, 595.28] : [595.28, 841.89]
  const avail = pw - 2 * margin
  // too wide even in landscape: smaller text first (down to 7 pt), shortening cells only after that
  let size = 9
  while (size > 7 && total(measure(size)) > avail) size -= 0.5
  const lead = Math.round(size * 1.45 * 10) / 10
  const widths = measure(size)
  let over = widths.reduce((a, b) => a + b, 0) - avail
  while (over > 0.5) {  // too wide even in landscape: take from the widest column, step by step
    const i = widths.indexOf(Math.max(...widths))
    const cut = Math.min(over, widths[i] * 0.1 + 1)
    widths[i] -= cut
    over -= cut
  }
  const xs = widths.map((_, i) => margin + widths.slice(0, i).reduce((a, b) => a + b, 0))

  // pages: lists of drawing operations
  const pages: string[][] = []
  let ops: string[] = [], y = 0
  const text = (x: number, yy: number, t: string, bold = false, sz = size) =>
    ops.push(`BT /${bold ? 'F2' : 'F1'} ${sz} Tf ${n(x)} ${n(yy)} Td ${str(t)} Tj ET`)
  const line = (yy: number, gray: number, w = 0.5) =>
    ops.push(`${gray} G ${w} w ${n(margin)} ${n(yy)} m ${n(pw - margin)} ${n(yy)} l S`)
  const headRow = () => {
    doc.head.forEach((h, i) => text(xs[i], y, fit(h, widths[i] - pad, size, true), true))
    line(y - 4, 0.45, 0.8)
    y -= lead + 2
  }
  const newPage = () => {
    ops = []
    pages.push(ops)
    y = ph - margin
    if (pages.length === 1) {
      let x = margin
      if (doc.logo) {  // 30 pt high, at most 140 pt wide, next to the title
        const h = Math.min(30, (140 * doc.logo.height) / doc.logo.width), w = (h * doc.logo.width) / doc.logo.height
        ops.push(`q ${n(w)} 0 0 ${n(h)} ${n(margin)} ${n(y - 26)} cm /Im1 Do Q`)
        x += w + 12
      }
      text(x, y - 8, doc.title, true, 16)
      ops.push('0.4 g')
      text(x, y - 24, doc.subtitle, false, 9)
      ops.push('0 g')
      y -= 46
    }
    headRow()
  }
  const bottom = margin + 24
  const indent = doc.rows.some((x) => x.kind === 'group') ? 8 : 0
  let stripe = 0  // every other row lightly shaded; counted afresh under each group heading
  newPage()
  doc.rows.forEach((r, k) => {
    const group = r.kind === 'group'
    const need = group ? lead * 2 + 6 : lead  // a heading never ends a page alone
    if (y - need < bottom) newPage()
    if (group) {
      stripe = 0
      if (k) y -= 6
      ops.push('0.22 0.19 0.64 rg')
      text(xs[0], y, fit(r.cells[0] ?? '', avail, size, true), true)
      ops.push('0 g')
      // a company's own numbers stand in its heading row
      r.cells.slice(1).forEach((c, i) => c && text(xs[i + 1], y, fit(c, widths[i + 1] - pad, size), false))
      line(y - 4, 0.6)
    } else {
      if (stripe++ % 2) ops.push(`0.95 g ${n(margin)} ${n(y - 4)} ${n(avail)} ${n(lead)} re f 0 g`)
      const ind = (i: number) => (i === 0 && r.kind !== 'strong' ? indent : 0)  // persons under their company heading
      r.cells.forEach((c, i) => c && text(xs[i] + ind(i), y, fit(c, widths[i] - pad - ind(i), size, r.kind === 'strong'), r.kind === 'strong'))
      line(y - 4, 0.88, 0.4)
    }
    y -= lead
  })
  pages.forEach((p, i) => {
    p.push('0.4 g')
    const f = doc.footer(i + 1, pages.length)
    p.push(`BT /F1 8 Tf ${n(pw - margin - width(f, 8))} ${n(margin - 4)} Td ${str(f)} Tj ET`)
  })

  // the file: catalog, page tree, two fonts, then a page and a content stream per page; offsets in the xref table
  const objs: string[] = []
  const add = (body: string) => objs.push(body)
  add('<< /Type /Catalog /Pages 2 0 R >>')
  const kids = pages.map((_, i) => `${5 + i * 2} 0 R`).join(' ')
  add(`<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>`)
  add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
  add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')
  const image = 5 + pages.length * 2  // the logo comes after the pages
  const xobj = doc.logo ? ` /XObject << /Im1 ${image} 0 R >>` : ''
  pages.forEach((p, i) => {
    const stream = p.join('\n')
    add(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${n(pw)} ${n(ph)}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >>${xobj} >> /Contents ${6 + i * 2} 0 R >>`)
    add(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`)  // one char = one byte (WinAnsi)
  })
  if (doc.logo) {
    const { jpeg, width: iw, height: ih } = doc.logo
    let bytes = ''
    for (let i = 0; i < jpeg.length; i += 8192) bytes += String.fromCharCode(...jpeg.subarray(i, i + 8192))
    add(`<< /Type /XObject /Subtype /Image /Width ${iw} /Height ${ih} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n${bytes}\nendstream`)
  }
  let out = '%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'
  const offsets = objs.map((body, i) => {
    const at = out.length
    out += `${i + 1} 0 obj\n${body}\nendobj\n`
    return at
  })
  const xref = out.length
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R /Info << /Producer (Kartei) /Title ${str(doc.title)} >> >>\nstartxref\n${xref}\n%%EOF\n`
  return Uint8Array.from(out, (c) => c.charCodeAt(0))
}
