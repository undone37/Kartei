import { i18n, t } from './i18n.svelte'
import type { Field } from './types'
import { store } from './store.svelte'
export { isMulti, isSingle } from './types'

export const isEmpty = (v: unknown) => v == null || v === '' || (Array.isArray(v) && v.length === 0)

export function optionLabel(f: Field, value: string) {
  const o = f.options.find((o) => o.value === value)
  return o ? o[i18n.lang] || o.de || o.value : value
}

export function fmt(f: Field, v: any): string {
  if (isEmpty(v)) return ''
  switch (f.type) {
    case 'decimal':
      return new Intl.NumberFormat(i18n.lang, { minimumFractionDigits: f.decimals, maximumFractionDigits: f.decimals })
        .format(Number(v))
    case 'integer':
      return new Intl.NumberFormat(i18n.lang).format(Number(v))
    case 'date':
      return new Intl.DateTimeFormat(i18n.lang, { dateStyle: 'medium' }).format(new Date(v + 'T00:00:00'))
    case 'select':
    case 'user':
      return optionLabel(f, v)
    case 'multiselect':
    case 'users':
      return (Array.isArray(v) ? v : [v]).map((x) => optionLabel(f, x)).join(', ')
    case 'contact': {
      // a linked person (uid) or free text
      const r = store.byUid.get(v)
      return r ? store.name(r) : String(v)
    }
    case 'checkbox':
      return v ? t('common.yes') : t('common.no')
    default:
      return String(v)
  }
}

export function relTime(iso: string) {
  const diff = (Date.parse(iso) - Date.now()) / 1000
  const rtf = new Intl.RelativeTimeFormat(i18n.lang, { numeric: 'auto' })
  for (const [unit, s] of [['year', 31536000], ['month', 2592000], ['day', 86400], ['hour', 3600], ['minute', 60]] as const) {
    if (Math.abs(diff) >= s) return rtf.format(Math.round(diff / s), unit)
  }
  return rtf.format(Math.round(diff), 'second')
}

export const dateTime = (iso: string) =>
  new Intl.DateTimeFormat(i18n.lang, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
