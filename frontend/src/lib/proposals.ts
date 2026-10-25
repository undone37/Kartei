// Field names and values of a proposal's changes, shared by the proposal panels and the page of a proposed new contact
import { store } from './store.svelte'
import { fmt } from './format'
import { L, t } from './i18n.svelte'
import type { Proposal } from './types'

export const fieldName = (key: string) => {
  const f = store.fields.find((f) => f.key === key)
  return f ? L(f.label) : t(`core.${key}`)
}

export const valueText = (scope: 'core' | 'data', key: string, v: any) => {
  if (v == null || v === '' || (Array.isArray(v) && !v.length)) return '—'
  if (scope === 'core') return key === 'company' ? store.byUid.get(v)?.name ?? '—' : String(v)
  const f = store.fields.find((f) => f.key === key)
  return f ? fmt(f, v) : String(v)
}

/** the proposed values, in field order (core fields first) */
export const proposedValues = (p: Proposal) => {
  const order = new Map(store.fields.map((f, i) => [f.key, i]))
  const data = Object.keys(p.changes.data ?? {}).sort((a, b) => (order.get(a) ?? 1e9) - (order.get(b) ?? 1e9))
  return [
    ...Object.keys(p.changes.core ?? {}).map((k) => ({ key: k, label: fieldName(k), value: valueText('core', k, p.changes.core![k]) })),
    ...data.map((k) => ({ key: k, label: fieldName(k), value: valueText('data', k, p.changes.data![k]) })),
  ]
}
