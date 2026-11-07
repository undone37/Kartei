// What the contact list shows for a list state (kind, "my contacts", quick filters, advanced filter, search), as one
// test per record. Pure, so the server's copy (backend/kartei/filters.py, used for Outlook folders and CardDAV books
// from saved filters) is checked against the same cases: tests/filter-cases.json.
import { compile, defs, type Group } from './advanced.ts'
import { matcher, type Indexed } from './search.ts'
import type { Field, Kind, Rec } from './types'

export type Scope = 'all' | 'responsible' | 'internal' | 'review' | 'proposals'

/** "my contacts": every single-user field counts as responsible, every multi-user field as internal contacts */
export const scopeKeys = (fields: Field[]) => ({
  responsible: fields.filter((f) => f.type === 'user' && !f.archived).map((f) => f.key),
  internal: fields.filter((f) => f.type === 'users' && !f.archived).map((f) => f.key),
})

export function inScope(r: Rec, scope: Scope, keys: ReturnType<typeof scopeKeys>, me: string | undefined,
                        sets: { review?: Set<string>; proposals?: Set<string> } = {}) {
  if (scope === 'all') return true
  if (scope === 'review') return !!sets.review?.has(r.uid)
  if (scope === 'proposals') return !!sets.proposals?.has(r.uid)
  return keys[scope].some((k) => (Array.isArray(r.data[k]) ? r.data[k].includes(me) : r.data[k] === me))
}

export interface ListQuery {
  q: string; scope: Scope; kind: 'all' | Kind
  /** quick filters: field key -> values, a record matches one of them */
  filters: [string, string[]][]
  adv: Group
}

export function listTest(s: ListQuery, fields: Field[], me: string | undefined, today = new Date(),
                         sets: { review?: Set<string>; proposals?: Set<string> } = {}) {
  const match = matcher(s.q)
  const at = compile(s.adv, defs(fields), today)
  const keys = scopeKeys(fields)
  return (x: Indexed) => {
    if (s.kind !== 'all' && x.rec.kind !== s.kind) return false
    if (!inScope(x.rec, s.scope, keys, me, sets)) return false
    if (at && !at(x.rec)) return false
    for (const [key, vals] of s.filters) {
      const v = x.rec.data[key]
      if (!(Array.isArray(v) ? v : [v]).some((y) => vals.includes(y))) return false
    }
    return match(x)
  }
}
