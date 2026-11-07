import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildIndex, digits, matcher } from '../src/lib/search.ts'

test('phone normalization', () => {
  assert.equal(digits('+49 (511) 123-4'), '05111234')
  assert.equal(digits('0049 511 1234'), '05111234')
})

test('search matching', () => {
  const rec: any = { uid: '1', kind: 'person', first_name: 'Jörg', last_name: 'Müller', name: '', company: null,
    legacy_id: '', data: { tel: '+49 511 1234' } }
  const field: any = { key: 'tel', type: 'phone', searchable: true, archived: false, options: [] }
  const [ix] = buildIndex([rec], [field], new Map())
  for (const q of ['müller', 'muller', 'mueller', 'jörg mül', '0511 1234', '511/12']) assert.ok(matcher(q)(ix), q)
  for (const q of ['meier', 'müller 999']) assert.ok(!matcher(q)(ix), q)
})

test('list order and name display', async () => {
  const { compareBy, displayName } = await import('../src/lib/search.ts')
  const p = (first: string, last: string, updated: string, created: string) =>
    ({ kind: 'person', first_name: first, last_name: last, name: '', updated_at: updated, created_at: created }) as any
  const a = p('Zoë', 'Albers', '2026-01-02', '2025-01-01'), b = p('Anna', 'Zander', '2026-03-01', '2024-01-01'),
    c = p('Bert', 'Müller', '2026-02-01', '2026-01-01')
  const order = (s: any) => [a, b, c].sort(compareBy(s)).map((r) => r.last_name)
  assert.deepEqual(order('last_name'), ['Albers', 'Müller', 'Zander'])
  assert.deepEqual(order('first_name'), ['Zander', 'Müller', 'Albers'])
  assert.deepEqual(order('updated'), ['Zander', 'Müller', 'Albers'])
  assert.deepEqual(order('created'), ['Müller', 'Albers', 'Zander'])
  assert.equal(displayName(a), 'Zoë Albers')
  assert.equal(displayName(a, 'last_first'), 'Albers, Zoë')
  assert.equal(displayName({ ...a, first_name: '' }, 'last_first'), 'Albers')
})
