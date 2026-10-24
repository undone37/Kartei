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
