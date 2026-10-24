import type { Field, Rec } from './types'

const CHOICE = ['select', 'multiselect', 'user', 'users'] // option labels are searchable too
const EXPAND: Record<string, string> = { ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' }

/** Lowercase + diacritics stripped. "Lübeck" -> "lubeck" */
export const fold = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ß/g, 'ss')
/** Lowercase + german transliteration. "Lübeck" -> "luebeck" */
export const expand = (s: string) => s.toLowerCase().replace(/[äöüß]/g, (c) => EXPAND[c])

/** "+49 (511) 123-4" -> "05111234", "0511/1234" -> "05111234" */
export function digits(s: string) {
  let d = s.replace(/[^\d+]/g, '')
  if (d.startsWith('+49')) d = '0' + d.slice(3)
  else if (d.startsWith('0049')) d = '0' + d.slice(4)
  return d.replace(/\+/g, '00')
}

export interface Indexed {
  rec: Rec
  hay: string
  tel: string
}

export function displayName(r: Rec) {
  return r.kind === 'company' ? r.name : `${r.first_name} ${r.last_name}`.trim()
}

export function buildIndex(records: Rec[], fields: Field[], byUid: Map<string, Rec>): Indexed[] {
  const searchable = fields.filter((f) => f.searchable && !f.archived)
  const collator = new Intl.Collator('de', { sensitivity: 'base', numeric: true })
  const sortKey = (r: Rec) => (r.kind === 'company' ? r.name : `${r.last_name} ${r.first_name}`)
  return records
    .map((rec) => {
      const parts = [rec.first_name, rec.last_name, rec.name, rec.legacy_id]
      if (rec.company) parts.push(byUid.get(rec.company)?.name ?? '')
      const tel: string[] = []
      for (const f of searchable) {
        const v = rec.data[f.key]
        if (v == null || v === '') continue
        if (f.type === 'phone') tel.push(digits(String(v)))
        if (f.type === 'contact') {
          const linked = byUid.get(v)
          parts.push(linked ? displayName(linked) : String(v))
          continue
        }
        if (CHOICE.includes(f.type)) {
          for (const x of Array.isArray(v) ? v : [v]) {
            const o = f.options.find((o) => o.value === x)
            parts.push(x, o?.de ?? '', o?.en ?? '')
          }
        } else parts.push(String(v))
      }
      const text = parts.join(' ')
      return { rec, hay: fold(text) + ' ' + expand(text), tel: tel.join(' ') }
    })
    .sort((a, b) => collator.compare(sortKey(a.rec), sortKey(b.rec)))
}

/** All tokens must match (AND). Digit tokens also match normalized phone numbers. */
export function matcher(query: string) {
  const tokens = query.trim().split(/\s+/).filter(Boolean)
  if (!tokens.length) return () => true
  const prepared = tokens.map((tok) => ({ text: fold(tok), tel: /^[\d+()/-]{3,}$/.test(tok) ? digits(tok) : '' }))
  return (x: Indexed) => prepared.every((p) => x.hay.includes(p.text) || (p.tel && x.tel.includes(p.tel)))
}
