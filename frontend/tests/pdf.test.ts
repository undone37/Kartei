import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fit, tablePdf, width } from '../src/lib/pdf.ts'

const latin1 = (b: Uint8Array) => String.fromCharCode(...b)
const doc = (rows: number, cols = 3) => tablePdf({
  title: 'Telefonliste', subtitle: '7. November 2026 · 3 Einträge',
  head: ['Name', ...Array.from({ length: cols - 1 }, (_, i) => `Spalte ${i + 1}`)],
  rows: Array.from({ length: rows }, (_, i) => ({ kind: i % 10 === 0 ? 'group' as const : 'row' as const,
                                                    cells: [`Müller (${i})`, ...Array(cols - 1).fill('+49 511 1000-12')] })),
  footer: (p, n) => `Seite ${p} von ${n}`,
})

test('a valid file: header, objects at the offsets the xref table names, trailer', () => {
  const s = latin1(doc(5))
  assert.ok(s.startsWith('%PDF-1.4\n'))
  const xref = Number(s.match(/startxref\n(\d+)/)![1])
  assert.equal(s.slice(xref, xref + 4), 'xref')
  const offsets = [...s.slice(xref).matchAll(/^(\d{10}) 00000 n $/gm)].map((m) => Number(m[1]))
  offsets.forEach((o, i) => assert.equal(s.slice(o, o + `${i + 1} 0 obj`.length), `${i + 1} 0 obj`))
  assert.ok(s.trimEnd().endsWith('%%EOF'))
  // stream lengths match: every content stream is exactly as long as declared
  for (const m of s.matchAll(/<< \/Length (\d+) >>\nstream\n/g)) {
    const start = m.index! + m[0].length
    assert.equal(s.slice(start + Number(m[1]), start + Number(m[1]) + 10), '\nendstream')
  }
})

test('umlauts as WinAnsi bytes, parentheses escaped, unknown characters as "?"', () => {
  const s = latin1(tablePdf({ title: 'Ä (x) \\ ł', subtitle: '', head: ['Straße'], rows: [], footer: () => '' }))
  assert.ok(s.includes('(\xc4 \\(x\\) \\\\ ?)'))  // Ä is 0xC4; "ł" has no WinAnsi code
  assert.ok(s.includes('(Stra\xdfe)'))
})

test('long lists span pages, each with the heading row and a page number', () => {
  const s = latin1(doc(200))
  const pages = Number(s.match(/\/Count (\d+)/)![1])
  assert.ok(pages >= 4)
  assert.equal((s.match(/\(Spalte 1\)/g) ?? []).length, pages)
  assert.ok(s.includes(`(Seite ${pages} von ${pages})`))
})

test('many columns: landscape; too wide still: cells shortened with "…"', () => {
  assert.ok(latin1(doc(3, 3)).includes('/MediaBox [0 0 595.28 841.89]'))
  assert.ok(latin1(doc(3, 9)).includes('/MediaBox [0 0 841.89 595.28]'))
  assert.equal(fit('kurz', 100, 9), 'kurz')
  const cut = fit('Beispielwerke Nord GmbH & Co. KG Niederlassung Hannover', 80, 9)
  assert.ok(cut.endsWith('…') && width(cut, 9) <= 80)
})

test('columns without any value are left out', () => {
  const s = latin1(tablePdf({ title: 'T', subtitle: '', head: ['Name', 'Fax', 'Mobil'], rows: [{ cells: ['A', '', '0170 1'] }],
                              footer: () => '' }))
  assert.ok(s.includes('(Mobil)') && !s.includes('(Fax)'))
})

test('a logo is embedded once as a JPEG image, rows alternate', () => {
  const jpeg = Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 0xff, 0xd9])
  const s = latin1(tablePdf({ title: 'T', subtitle: '', head: ['Name'], rows: [{ cells: ['A'] }, { cells: ['B'] }, { cells: ['C'] }],
                              footer: () => '', logo: { jpeg, width: 30, height: 10 } }))
  assert.match(s, /\/Subtype \/Image \/Width 30 \/Height 10 .*\/Filter \/DCTDecode \/Length 9 >>\nstream\n\xff\xd8\xff/)
  assert.ok(s.includes('/Im1 Do'))
  assert.equal((s.match(/re f/g) ?? []).length, 1)  // of three rows, the second is shaded
  const xref = Number(s.match(/startxref\n(\d+)/)![1])  // offsets still right with the binary image
  const offsets = [...s.slice(xref).matchAll(/^(\d{10}) 00000 n $/gm)].map((m) => Number(m[1]))
  offsets.forEach((o, i) => assert.equal(s.slice(o, o + `${i + 1} 0 obj`.length), `${i + 1} 0 obj`))
})
