import de from '../i18n/de'
import en from '../i18n/en'
import type { L10n, Lang } from './types'

const dicts: Record<Lang, Record<string, string>> = { de, en }
export const i18n = $state({ lang: (navigator.language?.startsWith('de') ? 'de' : 'en') as Lang })

/** Translate a key; {name} placeholders are filled from params. Falls back to German, then the key. */
export function t(key: string, params: Record<string, string | number> = {}): string {
  // "{key}_one" is used for n === 1 when present (both languages pluralize the same way)
  const k = params.n === 1 && `${key}_one` in dicts.de ? `${key}_one` : key
  const s = dicts[i18n.lang][k] ?? dicts.de[k] ?? key
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m))
}

/** Pick the active language from a {de, en} pair (falls back to the other one if empty). */
export const L = (v: L10n | undefined) => (v ? v[i18n.lang] || v.de || v.en : '')

/** Translate an API error code (field errors use the same codes). */
export const terr = (code: string) => {
  const [base, arg] = code.split(':')
  return dicts.de[`err.${base}`] ? t(`err.${base}`, { arg: arg ?? '' }) : t('err.generic')
}

/** Server messages stored as text: "@code {params}" -> msg.<code>; anything else (external errors) as is. */
export function tmsg(s: string | null | undefined): string {
  const m = s?.match(/^@(\w+) ([\s\S]*)$/)
  if (!m) return s ?? ''
  let p: Record<string, any> = {}
  try { p = JSON.parse(m[2]) } catch { /* keep empty */ }
  if (typeof p.error === 'string') p.error = terr(p.error) // nested error codes, e.g. invalid_email
  if (p[`field_${i18n.lang}`]) p.field = p[`field_${i18n.lang}`]
  return t(`msg.${m[1]}`, p)
}

export function setLang(lang: Lang) {
  i18n.lang = lang
  document.documentElement.lang = lang
}
