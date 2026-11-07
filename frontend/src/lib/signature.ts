// Email signature → new contact: the text is turned into vCard properties, so `toDraft` maps them onto the fields
// exactly like an imported .vcf (labels, phone types, address parts, company link). Local heuristics only; whatever
// isn't recognised is listed, never dropped silently.
import type { Field, Kind } from './types'
import { type Draft, type Prop, toDraft } from './vcardimport.ts'

const EMAIL = /[\w.%+-]+@[\w-]+(?:\.[\w-]+)+/
const URL_RE = /\b(?:https?:\/\/|www\.)[^\s|·•,;]+/i
const NUMBER = /^\+?[\d\s()/.\-–]{6,}$/
const LABEL = /^(tel(?:efon)?|phone|fon|direkt|durchwahl|direct|office|zentrale|t|mobil(?:e|funk)?|handy|cell|m|fax|telefax|f)\s*\.?\s*[:.]?\s*/i
const ZIP_CITY = /^(?:(?:D|A|CH|DE|AT)[- ])?(\d{4,5})\s+(\p{Lu}[\p{L} .'\-()/]+)$/u
const STREET = /(str(?:\.|aße|asse)|weg|platz|allee|gasse|ring|damm|ufer|chaussee|markt|road|street|avenue|lane)\b.*\d|\d+\s*[a-z]?$/iu
const COUNTRY = /^(deutschland|germany|österreich|austria|schweiz|switzerland|suisse|svizzera|nederland|netherlands|france|frankreich|italia|italien|luxemburg|luxembourg)$/i
const COMPANY = /\b(GmbH|AG|KG|SE|OHG|UG|e\.\s?V\.|eG|mbH|GbR|KGaA|Ltd\.?|Limited|Inc\.?|LLC|plc|S\.A\.|B\.V\.|N\.V\.|S\.r\.l\.|Sp\. z o\.o\.|Stiftung|Verein|Verband)(?=\W|$)/
const GREETING = /^(mit )?(freundlich|beste|viele|herzlich|liebe)\w* gr(ü|ue)(ß|ss)\w*|^(best|kind|warm)( regards)?|^regards|^cheers|^mfg$|^vg$|^lg$|^--\s*$|^gruß|^sent from|^gesendet von/i
const LEGAL = /^(geschäftsführ|vorstand|aufsichtsrat|sitz( der gesellschaft)?|registergericht|amtsgericht|hrb|hra|ust|steuer|vat|ceo:|managing director|this e-?mail|diese e-?mail|confidential|vertraulich)/i
const TITLES = /^((?:prof\.|dr\.|dipl\.-[\w.]+|mag\.|ing\.)\s*)+/i

const esc = (v: string) => v.replace(/[\\,;]/g, (c) => '\\' + c)
const prop = (name: string, value: string, type: string[] = []): Prop => ({ name, params: type.length ? { TYPE: type } : {}, value, group: '' })
const words = (s: string) => s.split(/\s+/).filter(Boolean)
const isName = (s: string) => {
  const w = words(s.replace(TITLES, ''))
  return w.length >= 2 && w.length <= 4 && w.every((x) => /^\p{Lu}[\p{L}'’.-]*$/u.test(x) || /^(von|van|de|der|den|zu|da|di|le|la)$/i.test(x))
}

/** the pieces of a signature as vCard properties, plus the lines nothing was found in */
export function signatureProps(text: string): { props: Prop[]; rest: string[] } {
  const props: Prop[] = []
  const rest: string[] = []
  const free: string[] = []  // text lines in order: name, job title, company candidates
  const adr = { street: '', city: '', zip: '', country: '' }
  let lastStreet = ''
  // one line can hold several pieces: "Tel. 0511 1000-12 | Fax -99 | www.example.com"
  const segs = text.replace(/\r/g, '').split('\n').flatMap((l) => l.split(/\s+[|·•]\s+|\t+|\s{3,}/)).map((s) => s.trim()).filter(Boolean)
  for (const raw of segs) {
    let s = raw.replace(/^[-–*>]\s*/, '')
    if (GREETING.test(s) || LEGAL.test(s) || s.length > 120) continue
    const mail = s.match(EMAIL)
    if (mail) {
      props.push(prop('EMAIL', mail[0], ['WORK']))
      s = s.replace(/^(e-?mail|mail)\s*[:.]?\s*/i, '').replace(mail[0], '').trim()
      if (!s) continue
    }
    const url = s.match(URL_RE)
    if (url) {
      props.push(prop('URL', /^https?:/i.test(url[0]) ? url[0] : 'https://' + url[0]))
      s = s.replace(/^(web|internet|homepage)\s*[:.]?\s*/i, '').replace(url[0], '').trim()
      if (!s) continue
    }
    const label = s.match(LABEL)
    const num = s.slice(label?.[0].length ?? 0).trim()
    if (NUMBER.test(num) && num.replace(/\D/g, '').length >= 6 && (label || /^[+0(]/.test(num))) {
      const l = (label?.[1] ?? '').toLowerCase()
      const type = /^(fax|telefax|f)$/.test(l) ? ['FAX', 'WORK'] : /^(mobil|mobile|mobilfunk|handy|cell|m)$/.test(l) ? ['CELL']
        : !label && /^(\+49\s*\(?0?\)?\s*|0)1[5-7]/.test(num) ? ['CELL'] : ['WORK']  // German mobile prefixes
      props.push(prop('TEL', num, type))
      continue
    }
    // "Musterstraße 1, 30159 Hannover" in one line
    const parts = s.split(/,\s*/)
    const zc = parts.map((p) => p.match(ZIP_CITY)).findIndex(Boolean)
    if (zc >= 0 && !adr.city) {
      const m = parts[zc].match(ZIP_CITY)!
      adr.zip = m[1]
      adr.city = m[2].trim()
      adr.street = parts.slice(0, zc).join(', ') || lastStreet
      if (adr.street && adr.street === lastStreet && free.includes(lastStreet)) free.splice(free.indexOf(lastStreet), 1)
      if (parts[zc + 1] && COUNTRY.test(parts[zc + 1])) adr.country = parts[zc + 1]
      continue
    }
    if (COUNTRY.test(s) && adr.city) { adr.country = s; continue }
    if (STREET.test(s) && /\d/.test(s) && !COMPANY.test(s)) lastStreet = s
    free.push(s)
  }
  // company: the line with a legal form; name: the first line that looks like one; job title: the line after the name
  const company = free.find((l) => COMPANY.test(l))
  const name = free.find((l) => l !== company && isName(l))
  let title = ''
  if (name) {
    const after = free[free.indexOf(name) + 1]
    if (after && after !== company && after !== lastStreet && !/\d/.test(after) && words(after).length <= 8) title = after
  }
  let first = '', last = '', prefix = ''
  if (name) {
    prefix = (name.match(TITLES)?.[0] ?? '').trim()
    const w = words(name.replace(TITLES, ''))
    const particle = w.findIndex((x, i) => i > 0 && /^(von|van|de|der|den|zu|da|di|le|la)$/i.test(x))
    const split = particle > 0 ? particle : w.length - 1
    first = w.slice(0, split).join(' ')
    last = w.slice(split).join(' ')
  } else {
    // no name line: "erika.muster@…" still gives one
    const local = props.find((p) => p.name === 'EMAIL')?.value.split('@')[0] ?? ''
    const m = local.match(/^([a-zäöü]+)[._-]([a-zäöü-]+)$/i)
    if (m && company) [first, last] = [m[1], m[2]].map((x) => x[0].toUpperCase() + x.slice(1))
  }
  if (first || last) {
    props.push(prop('N', [last, first, '', prefix, ''].map(esc).join(';')), prop('FN', [first, last].filter(Boolean).join(' ')))
  }
  if (company) props.push(prop('ORG', esc(company)))
  if (title) props.push(prop('TITLE', title))
  if (adr.city || adr.street) props.push(prop('ADR', ['', '', adr.street, adr.city, '', adr.zip, adr.country].map(esc).join(';'), ['WORK']))
  rest.push(...free.filter((l) => l !== name && l !== company && l !== title && l !== adr.street))
  return { props, rest }
}

/** pasted signature → the same draft a .vcf card gives; unrecognised lines end up in `unmapped` */
export function fromText(text: string, fields: Field[], kindOf?: (k: Kind) => Field[]): Draft | null {
  const { props, rest } = signatureProps(text)
  if (!props.length) return null
  const d = toDraft(props, fields, kindOf)
  d.unmapped.push(...rest)
  return d
}
