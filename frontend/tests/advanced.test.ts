import assert from 'node:assert/strict'
import { test } from 'node:test'
import { compile, count, defs, family, OPS, shape, type Group } from '../src/lib/advanced.ts'

const F = (key: string, type: string, archived = false): any => ({ key, type, archived, options: [] })
const fields = [F('city', 'text'), F('tel', 'phone'), F('staff', 'integer'), F('revenue', 'decimal'), F('since', 'date'),
  F('status', 'select'), F('tags', 'multiselect'), F('owner', 'user'), F('team', 'users'), F('vip', 'checkbox'),
  F('assistant', 'contact'), F('old', 'text', true)]
const D = defs(fields)
const TODAY = new Date(2026, 9, 24) // 2026-10-24

let n = 0
const rec = (data: Record<string, any>, core: Record<string, any> = {}): any => ({
  uid: String(++n), kind: 'person', first_name: '', last_name: '', name: '', company: null, legacy_id: '',
  updated_at: '2026-10-01T10:00:00Z', updated_by: '', reviewed_at: null, data, ...core,
})
const A = rec({ city: 'Lübeck', tel: '+49 511 1234', staff: 12, revenue: '1234.50', since: '2020-05-01', status: 'customer',
  tags: ['a', 'b'], owner: 'jdoe', team: ['jdoe', 'mmax'], vip: true, assistant: 'u-9', old: 'x' },
  { first_name: 'Jörg', last_name: 'Müller', reviewed_at: '2026-10-20T08:00:00Z', created_at: '2024-01-01T00:00:00Z' })
const B = rec({ city: 'Köln', tel: '0221 / 98 76', staff: '3', since: '2026-10-10', status: 'lead', tags: ['c'], team: ['mmax'] },
  { kind: 'company', name: 'Weiß GmbH', reviewed_at: '2025-01-01T08:00:00Z', updated_by: 'jdoe' })
const C = rec({}, { first_name: 'Ana' })
const ALL = [A, B, C]

const run = (g: Group) => { const t = compile(g, D, TODAY); return ALL.filter((r) => !t || t(r)).map((r) => r.uid) }
const one = (field: string, op: string, value?: any) => run({ mode: 'all', items: [{ field, op, value }] })
const ids = (...rs: any[]) => rs.map((r) => r.uid)

test('text operators, umlauts and case', () => {
  assert.deepEqual(one('city', 'contains', 'LUBE'), ids(A))
  assert.deepEqual(one('city', 'contains', 'lueb'), ids(A))
  assert.deepEqual(one('city', 'eq', 'lübeck'), ids(A))
  assert.deepEqual(one('city', 'ne', 'Lübeck'), ids(B, C)) // empty counts as "is not"
  assert.deepEqual(one('city', 'not_contains', 'ö'), ids(A, C))
  assert.deepEqual(one('city', 'starts', 'ko'), ids(B))
  assert.deepEqual(one('@name', 'contains', 'weiss'), ids(B))
  assert.deepEqual(one('@last_name', 'eq', 'mueller'), ids(A))
  assert.deepEqual(one('city', 'empty'), ids(C))
  assert.deepEqual(one('city', 'not_empty'), ids(A, B))
})

test('phone fields compare digits', () => {
  assert.deepEqual(one('tel', 'eq', '0511/1234'), ids(A))
  assert.deepEqual(one('tel', 'starts', '+49 221'), ids(B))
  assert.deepEqual(one('tel', 'contains', '9876'), ids(B))
})

test('numbers', () => {
  assert.deepEqual(one('staff', 'eq', '12'), ids(A))
  assert.deepEqual(one('staff', 'ne', '12'), ids(B, C))
  assert.deepEqual(one('staff', 'lt', '12'), ids(B))
  assert.deepEqual(one('staff', 'le', '12'), ids(A, B))
  assert.deepEqual(one('staff', 'gt', '3'), ids(A))
  assert.deepEqual(one('staff', 'ge', '3'), ids(A, B))
  assert.deepEqual(one('staff', 'between', ['4', '']), ids(A))
  assert.deepEqual(one('revenue', 'between', ['1000', '1234,5']), ids(A))
  assert.deepEqual(one('revenue', 'empty'), ids(B, C))
})

test('dates', () => {
  assert.deepEqual(one('since', 'on', '2020-05-01'), ids(A))
  assert.deepEqual(one('since', 'not_on', '2020-05-01'), ids(B, C))
  assert.deepEqual(one('since', 'before', '2026-01-01'), ids(A))
  assert.deepEqual(one('since', 'on_after', '2026-10-10'), ids(B))
  assert.deepEqual(one('since', 'between', ['2026-10-01', '2026-10-31']), ids(B))
  assert.deepEqual(one('since', 'last', '30'), ids(B))
  assert.deepEqual(one('@reviewed_at', 'older', '365'), ids(B)) // never reviewed is empty, not "older"
  assert.deepEqual(one('@reviewed_at', 'last', '7'), ids(A))
  assert.deepEqual(one('@created_at', 'empty'), ids(B, C)) // missing in old caches = empty
  assert.deepEqual(one('@updated_at', 'on', '2026-10-01'), ids(A, B, C))
})

test('choices, multi values, checkbox', () => {
  assert.deepEqual(one('status', 'in', ['customer', 'lead']), ids(A, B))
  assert.deepEqual(one('status', 'not_in', ['lead']), ids(A, C))
  assert.deepEqual(one('@kind', 'in', ['company']), ids(B))
  assert.deepEqual(one('owner', 'in', ['jdoe']), ids(A))
  assert.deepEqual(one('@updated_by', 'in', ['jdoe']), ids(B))
  assert.deepEqual(one('assistant', 'in', ['u-9']), ids(A))
  assert.deepEqual(one('tags', 'any', ['b', 'c']), ids(A, B))
  assert.deepEqual(one('tags', 'all', ['a', 'b']), ids(A))
  assert.deepEqual(one('team', 'none', ['jdoe']), ids(B, C))
  assert.deepEqual(one('team', 'empty'), ids(C))
  assert.deepEqual(one('vip', 'yes'), ids(A))
  assert.deepEqual(one('vip', 'no'), ids(B, C))
})

test('nested groups', () => {
  // persons in Lübeck, or companies reviewed more than a year ago
  const g: Group = { mode: 'any', items: [
    { mode: 'all', items: [{ field: '@kind', op: 'in', value: ['person'] }, { field: 'city', op: 'eq', value: 'luebeck' }] },
    { mode: 'all', items: [{ field: '@kind', op: 'in', value: ['company'] },
      { mode: 'any', items: [{ field: '@reviewed_at', op: 'older', value: '365' }, { field: '@reviewed_at', op: 'empty' }] }] },
  ] }
  assert.deepEqual(run(g), ids(A, B))
  assert.deepEqual(run({ mode: 'none', items: g.items }), ids(C))
  assert.equal(count(g, D), 5)
})

test('empty groups, incomplete conditions and unknown fields are ignored', () => {
  assert.equal(compile({ mode: 'all', items: [] }, D), null)
  assert.equal(compile({ mode: 'none', items: [{ mode: 'any', items: [] }] }, D), null)
  const junk: Group = { mode: 'any', items: [
    { field: 'old', op: 'eq', value: 'x' }, // archived
    { field: 'gone', op: 'eq', value: 'x' }, // hidden or deleted field
    { field: 'city', op: 'contains', value: '' }, // no value yet
    { field: 'city', op: 'in', value: ['x'] }, // operator of another type
    { field: 'status', op: 'in', value: [] },
    { field: 'staff', op: 'gt', value: 'abc' },
    { field: 'since', op: 'last', value: '' },
  ] }
  assert.equal(compile(junk, D), null)
  assert.equal(count(junk, D), 0)
  // in an ANY group the ignored ones don't turn it into "match all"
  assert.deepEqual(run({ mode: 'any', items: [...junk.items, { field: 'city', op: 'eq', value: 'köln' }] }), ids(B))
})

test('every field type has operators with a known value shape', () => {
  for (const f of fields) {
    for (const op of OPS[family(f.type)]) assert.ok(['none', 'one', 'list', 'range', 'days'].includes(shape(op)))
  }
})

test('10k records stay well under a frame', () => {
  const many = Array.from({ length: 10000 }, (_, i) => rec({ city: i % 2 ? 'Lübeck' : 'Köln', staff: i, tel: `0511 ${i}` }))
  const g: Group = { mode: 'all', items: [{ field: 'city', op: 'contains', value: 'lübe' },
    { mode: 'any', items: [{ field: 'staff', op: 'gt', value: '5000' }, { field: 'tel', op: 'contains', value: '12' }] }] }
  many.filter(compile(g, D)!) // warm the per-record cache, like the first keystroke
  // best of 5 against a loose bound: catches algorithmic regressions, not a busy machine or a slow CI runner
  let ms = Infinity, hits = 0
  for (let i = 0; i < 5; i++) {
    const t0 = performance.now()
    hits = many.filter(compile(g, D)!).length
    ms = Math.min(ms, performance.now() - t0)
  }
  assert.ok(hits > 2000)
  assert.ok(ms < 50, `${ms.toFixed(1)} ms`)
})
