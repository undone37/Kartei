// vCard import: parse .vcf text (vCard 2.1, 3.0, 4.0) and map each card onto the admin-defined fields through their
// vCard targets (the same targets the CardDAV rendering uses), so a card opens as a pre-filled "new contact" form.
import type { Field, Kind } from './types'

export interface Prop { name: string; params: Record<string, string[]>; value: string; group: string }
export interface Draft {
  kind: Kind
  first_name: string; last_name: string; name: string
  /** company name from ORG, for persons: linked to an existing company by the importer */
  company_name: string
  data: Record<string, any>
  photo: Blob | null
  /** values without a matching field, e.g. a second mobile number: shown so nothing is silently lost */
  unmapped: string[]
}

/** unfold continuation lines (RFC 6350 3.2) */
function unfold(text: string) {
  return text.replace(/\r\n|\r/g, '\n').replace(/\n[ \t]/g, '')
}

/** quoted-printable (vCard 2.1, e.g. older Outlook) in its CHARSET, UTF-8 if none */
function qp(value: string, charset = 'UTF-8') {
  const bytes: number[] = []
  for (let i = 0; i < value.length; i++) {
    const hex = value[i] === '=' ? value.slice(i + 1, i + 3) : ''
    if (/^[0-9A-F]{2}$/i.test(hex)) { bytes.push(parseInt(hex, 16)); i += 2 }
    else bytes.push(value.charCodeAt(i) & 0xff)
  }
  try {
    return new TextDecoder(charset.toLowerCase()).decode(new Uint8Array(bytes))
  } catch {
    return new TextDecoder().decode(new Uint8Array(bytes))
  }
}

const unescape = (v: string) => v.replace(/\\n/gi, '\n').replace(/\\([,;\\])/g, '$1')
/** split on separators that are not escaped */
const split = (v: string, sep: string) => v.split(new RegExp(`(?<!\\\\)${sep === ';' ? ';' : ','}`)).map(unescape)

export function parse(text: string): Prop[][] {
  const cards: Prop[][] = []
  let cur: Prop[] | null = null
  const lines = unfold(text).split('\n')
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i]
    // vCard 2.1 quoted-printable: a trailing "=" continues the value on the next line (only there: base64 ends in "=")
    if (/ENCODING=QUOTED-PRINTABLE/i.test(line.split(':')[0])) while (line.endsWith('=') && i + 1 < lines.length) line = line.slice(0, -1) + lines[++i]
    const m = line.match(/^(?:([\w-]+)\.)?([\w-]+)((?:;[^:]*)?):(.*)$/)
    if (!m) continue
    const [, group = '', rawName, rawParams, rawValue] = m
    const name = rawName.toUpperCase()
    if (name === 'BEGIN' && rawValue.trim().toUpperCase() === 'VCARD') cur = []
    else if (name === 'END' && cur) { cards.push(cur); cur = null }
    else if (cur) {
      const params: Record<string, string[]> = {}
      for (const p of rawParams.split(';').filter(Boolean)) {
        const [k, v] = p.includes('=') ? p.split(/=(.*)/s) : ['TYPE', p] // vCard 2.1: ;WORK;VOICE
        for (const x of v.replace(/^"|"$/g, '').split(',')) (params[k.toUpperCase()] ??= []).push(x.toUpperCase())
      }
      const value = params.ENCODING?.includes('QUOTED-PRINTABLE') ? qp(rawValue, params.CHARSET?.[0]) : rawValue
      cur.push({ name, params, value, group })
    }
  }
  return cards
}

const types = (p: Prop) => new Set(p.params.TYPE ?? [])

function photo(p: Prop): Blob | null {
  const data = p.value.match(/^data:([^;,]+)?(?:;base64)?,(.*)$/s)
  const b64 = data ? data[2] : p.params.ENCODING?.some((e) => e === 'B' || e === 'BASE64') ? p.value : null
  if (!b64) return null
  try {
    const bin = atob(b64.replace(/\s/g, ''))
    const type = data?.[1] ?? (types(p).has('PNG') ? 'image/png' : 'image/jpeg')
    return new Blob([Uint8Array.from(bin, (c) => c.charCodeAt(0))], { type })
  } catch {
    return null
  }
}

function bday(v: string) {
  const m = v.replace(/-/g, '').match(/^(\d{4})(\d{2})(\d{2})/)
  return m ? `${m[1]}-${m[2]}-${m[3]}` : ''
}

const ADR = ['pobox', 'extra', 'street', 'city', 'state', 'zip', 'country']

export function toDraft(props: Prop[], fields: Field[], kindOf?: (k: Kind) => Field[]): Draft {
  const get = (n: string) => props.find((p) => p.name === n)
  const labels = new Map(props.filter((p) => p.name === 'X-ABLABEL' && p.group).map((p) => [p.group, p.value.replace(/^_\$!<|>!\$_$/g, '')]))
  const n = get('N') ? split(get('N')!.value, ';') : []
  const org = get('ORG') ? split(get('ORG')!.value, ';') : []
  const isCompany = get('KIND')?.value.toLowerCase() === 'org' || get('X-ABSHOWAS')?.value.toUpperCase() === 'COMPANY'
    || (!n.some(Boolean) && !!org[0] && (!get('FN') || get('FN')!.value === org[0]))
  const kind: Kind = isCompany ? 'company' : 'person'
  const own = kindOf ? kindOf(kind) : fields
  const d: Draft = { kind, first_name: '', last_name: '', name: '', company_name: '', data: {}, photo: null, unmapped: [] }

  // a value goes to the first empty field with that target; a labelled one (iOS item label, e.g. "Zentrale") only to a
  // field with the same vCard label, or else one without a label, never into a field labelled for something else
  const put = (target: string, value: any, label = '', shown = String(value)) => {
    if (value == null || value === '' || (Array.isArray(value) && !value.length)) return
    const cands = own.filter((f) => f.vcard === target && !f.archived)
    const same = (f: Field) => f.vcard_label.toLowerCase() === label.toLowerCase()
    const order = label ? [...cands.filter(same), ...cands.filter((f) => !f.vcard_label)] : cands
    const f = order.find((f) => d.data[f.key] == null)
    if (f) d.data[f.key] = value
    else d.unmapped.push(label ? `${label}: ${shown}` : shown)
  }

  if (kind === 'company') d.name = org[0] || get('FN')?.value || ''
  else {
    ;[d.last_name = '', d.first_name = ''] = n
    if (!d.last_name && !d.first_name && get('FN')) {
      const parts = unescape(get('FN')!.value).trim().split(/\s+/)
      d.last_name = parts.pop() ?? ''
      d.first_name = parts.join(' ')
    }
    put('n_middle', n[2])
    put('n_prefix', n[3])
    put('n_suffix', n[4])
    d.company_name = org[0] ?? ''
    put('department', org.slice(1).filter(Boolean).join(', '))
  }
  for (const p of props) {
    const t = types(p)
    const label = labels.get(p.group) ?? ''
    const v = unescape(p.value).trim()
    switch (p.name) {
      case 'NICKNAME': put('nickname', v); break
      case 'X-PHONETIC-FIRST-NAME': put('phonetic_first', v); break
      case 'X-PHONETIC-MIDDLE-NAME': put('phonetic_middle', v); break
      case 'X-PHONETIC-LAST-NAME': put('phonetic_last', v); break
      case 'TITLE': case 'ROLE': if (!own.some((f) => f.vcard === 'title' && d.data[f.key])) put('title', v); break
      case 'BDAY': put('bday', bday(v)); break
      case 'URL': put('url', v.replace(/^\w+:(?=https?:)/, '')); break
      case 'NOTE': put('note', v); break
      case 'CATEGORIES': put('categories', split(p.value, ',').map((x) => x.trim()).filter(Boolean)); break
      case 'EMAIL': {
        const target = label ? 'email_custom' : t.has('HOME') ? 'email_home' : 'email_work'
        put(target, v, label)
        break
      }
      case 'TEL': {
        const num = v.replace(/^tel:/i, '')
        const fax = t.has('FAX')
        const target = label ? (fax ? 'tel_fax_custom' : 'tel_custom')
          : fax ? (t.has('HOME') ? 'tel_fax_home' : 'tel_fax_work')
          : t.has('CELL') ? 'tel_cell' : t.has('HOME') ? 'tel_home' : t.has('X-ASSISTANT') || t.has('ASSISTANT') ? 'tel_assistant' : 'tel_work'
        put(target, num, label)
        break
      }
      case 'ADR': {
        const parts = split(p.value, ';')
        const where = t.has('HOME') ? 'home' : 'work'
        ADR.forEach((a, i) => put(`adr_${where}_${a}`, (parts[i] ?? '').trim()))
        break
      }
      case 'PHOTO': case 'LOGO': d.photo ??= photo(p); break
    }
  }
  return d
}
