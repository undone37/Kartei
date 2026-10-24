/** Advanced list filter: nested ALL/ANY/NONE groups of field conditions, evaluated in memory like the search.
 *  Pure (no store, no i18n) so node:test can run it. Incomplete conditions, unknown (archived, hidden) fields and
 *  empty groups are dropped, i.e. they never narrow the list. */
import { digits, expand, fold } from './search.ts'
import type { Field, FieldType, Rec } from './types'

export type Mode = 'all' | 'any' | 'none'
export interface Cond { field: string; op: string; value?: any }
export interface Group { mode: Mode; items: Item[] }
export type Item = Cond | Group
export const isGroup = (x: Item): x is Group => 'items' in x
export const emptyGroup = (): Group => ({ mode: 'all', items: [] })

export type Family = 'text' | 'number' | 'date' | 'choice' | 'multi' | 'bool'
/** operators per family, the first is the default */
export const OPS: Record<Family, string[]> = {
  text: ['contains', 'not_contains', 'eq', 'ne', 'starts', 'empty', 'not_empty'],
  number: ['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'between', 'empty', 'not_empty'],
  date: ['on', 'not_on', 'before', 'on_before', 'after', 'on_after', 'between', 'last', 'older', 'empty', 'not_empty'],
  choice: ['in', 'not_in', 'empty', 'not_empty'],
  multi: ['any', 'all', 'none', 'empty', 'not_empty'],
  bool: ['yes', 'no'],
}

export function family(type: FieldType): Family {
  if (type === 'integer' || type === 'decimal') return 'number'
  if (type === 'date') return 'date'
  if (type === 'select' || type === 'user' || type === 'contact') return 'choice'
  if (type === 'multiselect' || type === 'users') return 'multi'
  if (type === 'checkbox') return 'bool'
  return 'text'
}

/** what the value input looks like for an operator */
export function shape(op: string): 'none' | 'one' | 'list' | 'range' | 'days' {
  if (['empty', 'not_empty', 'yes', 'no'].includes(op)) return 'none'
  if (['in', 'not_in', 'any', 'all', 'none'].includes(op)) return 'list'
  if (op === 'between') return 'range'
  return op === 'last' || op === 'older' ? 'days' : 'one'
}

/** local calendar day, "2026-10-24" */
export const day = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

// per-record derived values (folded text, local day of a timestamp); records are replaced, never mutated, on change
const memo = new WeakMap<Rec, Map<string, any>>()
function cached<T>(r: Rec, k: string, f: () => T): T {
  let m = memo.get(r)
  if (!m) memo.set(r, (m = new Map()))
  if (!m.has(k)) m.set(k, f())
  return m.get(k)
}
const stamp = (iso: string | null | undefined) => (iso ? day(new Date(iso)) : '')

export interface Def { type: FieldType; get: (r: Rec) => any }
/** the record's own columns; '@' can't clash with field keys (slugs) */
export const CORE: Record<string, Def> = {
  '@kind': { type: 'select', get: (r) => r.kind },
  '@first_name': { type: 'text', get: (r) => r.first_name },
  '@last_name': { type: 'text', get: (r) => r.last_name },
  '@name': { type: 'text', get: (r) => r.name },
  '@company': { type: 'contact', get: (r) => r.company },
  '@legacy_id': { type: 'text', get: (r) => r.legacy_id },
  '@created_at': { type: 'date', get: (r) => cached(r, '@created_at', () => stamp(r.created_at)) },
  '@updated_at': { type: 'date', get: (r) => cached(r, '@updated_at', () => stamp(r.updated_at)) },
  '@reviewed_at': { type: 'date', get: (r) => cached(r, '@reviewed_at', () => stamp(r.reviewed_at)) },
  '@updated_by': { type: 'user', get: (r) => r.updated_by },
}

export function defs(fields: Field[]): Map<string, Def> {
  const m = new Map(Object.entries(CORE))
  for (const f of fields) if (!f.archived) m.set(f.key, { type: f.type, get: (r) => r.data[f.key] })
  return m
}

type Test = (r: Rec) => boolean
const blank = (v: any) => v == null || (Array.isArray(v) ? !v.length : String(v).trim() === '')
const num = (v: any) => (blank(v) ? NaN : Number(String(v).replace(',', '.')))
const isDay = (v: any) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)

function leaf(c: Cond, d: Def | undefined, today: Date): Test | null {
  if (!d || !c || typeof c.op !== 'string') return null
  const fam = family(d.type)
  if (!OPS[fam].includes(c.op)) return null
  const { op, value } = c
  const get = d.get
  if (op === 'empty') return (r) => blank(get(r))
  if (op === 'not_empty') return (r) => !blank(get(r))
  if (op === 'yes') return (r) => !!get(r)
  if (op === 'no') return (r) => !get(r)
  const not = (t: Test | null): Test | null => t && ((r) => !t(r))

  if (fam === 'text') {
    if (blank(value)) return null
    if (op === 'ne') return not(leaf({ ...c, op: 'eq' }, d, today))
    if (op === 'not_contains') return not(leaf({ ...c, op: 'contains' }, d, today))
    const cmp = { eq: (a: string, b: string) => a === b, contains: (a: string, b: string) => a.includes(b),
                  starts: (a: string, b: string) => a.startsWith(b) }[op as 'eq']
    const n = String(value)
    const nf = [fold(n), expand(n)]
    // phone numbers compare by digits ("+49 511 1234" is "0511/1234"), unless the needle has none
    const nd = d.type === 'phone' ? digits(n) : ''
    return (r) => {
      const v = get(r)
      if (blank(v)) return false
      if (nd) return cmp(cached(r, 'd' + c.field, () => digits(String(v))), nd)
      const [a, b] = cached(r, 't' + c.field, () => [fold(String(v)), expand(String(v))])
      return cmp(a, nf[0]) || cmp(b, nf[1])
    }
  }
  if (fam === 'number' || fam === 'date') {
    const val = fam === 'number' ? (r: Rec) => num(get(r)) : (r: Rec) => (get(r) || '') as string
    const ok = fam === 'number' ? (x: any) => !Number.isNaN(x) : (x: any) => x !== ''
    const parse = fam === 'number' ? num : (v: any) => (isDay(v) ? v : '')
    if (op === 'last' || op === 'older') {
      const n = Number.parseInt(value, 10)
      if (!(n >= 0)) return null
      const now = day(today), from = day(new Date(today.getFullYear(), today.getMonth(), today.getDate() - n))
      return op === 'last' ? (r) => { const x = val(r); return ok(x) && x >= from && x <= now }
                           : (r) => { const x = val(r); return ok(x) && x < from }
    }
    if (op === 'between') {
      const [lo, hi] = Array.isArray(value) ? value.map(parse) : [parse(''), parse('')]
      if (!ok(lo) && !ok(hi)) return null
      return (r) => { const x = val(r); return ok(x) && (!ok(lo) || x >= lo) && (!ok(hi) || x <= hi) }
    }
    const n = parse(value)
    if (!ok(n)) return null
    const cmp = {
      eq: (x: any) => x === n, on: (x: any) => x === n, lt: (x: any) => x < n, before: (x: any) => x < n,
      le: (x: any) => x <= n, on_before: (x: any) => x <= n, gt: (x: any) => x > n, after: (x: any) => x > n,
      ge: (x: any) => x >= n, on_after: (x: any) => x >= n,
    }[op === 'ne' ? 'eq' : op === 'not_on' ? 'on' : op as 'eq']
    const t: Test = (r) => { const x = val(r); return ok(x) && cmp(x) }
    return op === 'ne' || op === 'not_on' ? not(t) : t
  }
  // choice / multi: a list of option values (usernames, record uids)
  const set = new Set((Array.isArray(value) ? value : []).map(String))
  if (!set.size) return null
  const list = (r: Rec) => { const v = get(r); return blank(v) ? [] : Array.isArray(v) ? v : [v] }
  const any: Test = (r) => list(r).some((x) => set.has(x))
  if (op === 'in' || op === 'any') return any
  if (op === 'not_in' || op === 'none') return not(any)
  return (r) => { const l = list(r); return [...set].every((x) => l.includes(x)) } // all
}

/** A predicate for the group, or null when it doesn't restrict anything. `today` is injectable for tests. */
export function compile(g: Group, defs: Map<string, Def>, today = new Date()): Test | null {
  const tests = (g?.items ?? [])
    .map((x) => (isGroup(x) ? compile(x, defs, today) : leaf(x, defs.get(x?.field), today)))
    .filter((t): t is Test => !!t)
  if (!tests.length) return null
  if (g.mode === 'any') return (r) => tests.some((t) => t(r))
  if (g.mode === 'none') return (r) => !tests.some((t) => t(r))
  return (r) => tests.every((t) => t(r))
}

/** effective conditions (the ones compile() keeps) */
export function count(g: Group, defs: Map<string, Def>): number {
  return (g?.items ?? []).reduce((n, x) => n + (isGroup(x) ? count(x, defs) : leaf(x, defs.get(x?.field), new Date()) ? 1 : 0), 0)
}
