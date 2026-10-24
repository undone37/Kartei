// Client-side field validation while typing. Mirrors backend/kartei/validation.py (same error codes, translated via
// err.*); the server stays authoritative. Selects, users and contacts come from pickers and need no check here.
import type { Field } from './types'

export const REGEX_TYPES = ['text', 'longtext', 'phone', 'email', 'url']
const PHONE = /^\+?[0-9 ()/-]{3,40}$/
// ponytail: close to Django's EmailValidator for real-world addresses, the server catches the exotic rest
const EMAIL = /^[^\s@"(),:;<>[\\\]]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i

const empty = (v: unknown) => v == null || v === '' || (Array.isArray(v) && v.length === 0)

/** "1.234,5" (German) or "1234.5" -> number, like the server's _num; NaN if invalid */
export function parseNumber(v: unknown): number {
  let s = String(v).trim().replace(/ /g, '')
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.')
  return /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(s) ? Number(s) : NaN
}

function validUrl(v: string) {
  try {
    const u = new URL(v.includes('://') ? v : `https://${v}`)
    return (u.protocol === 'http:' || u.protocol === 'https:') && (u.hostname.includes('.') || u.hostname === 'localhost')
  } catch {
    return false
  }
}

/** Error code for a value, or null. `required` is checked here too. */
export function validate(f: Field, value: unknown): string | null {
  if (empty(value)) return f.required ? 'required' : null
  const s = typeof value === 'string' ? value.trim() : String(value)
  switch (f.type) {
    case 'text':
    case 'longtext':
      if (s.length > (f.type === 'longtext' ? 20000 : 1000)) return 'too_long'
      break
    case 'integer':
    case 'decimal': {
      const n = parseNumber(value)
      if (Number.isNaN(n)) return 'invalid_number'
      if (f.type === 'integer' && !Number.isInteger(n)) return 'invalid_integer'
      if (f.min != null && n < Number(f.min)) return 'too_small'
      if (f.max != null && n > Number(f.max)) return 'too_large'
      break
    }
    case 'phone':
      if (!PHONE.test(s.replace(/\s+/g, ' '))) return 'invalid_phone'
      break
    case 'email':
      if (!EMAIL.test(s)) return 'invalid_email'
      break
    case 'url':
      if (!validUrl(s)) return 'invalid_url'
      break
    case 'date':
      if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || Number.isNaN(Date.parse(s))) return 'invalid_date'
      break
  }
  if (f.regex && REGEX_TYPES.includes(f.type)) {
    // JS and Python regex agree for common patterns; if the browser can't compile it, the server still checks
    let re: RegExp | null = null
    try { re = new RegExp(`^(?:${f.regex})$`, 'u') } catch { /* server checks */ }
    if (re && !re.test(s)) return 'pattern_mismatch'
  }
  return null
}
