import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pick } from '../src/lib/selection.ts'

const order = ['a', 'b', 'c', 'd', 'e']
const list = (s: Set<string>) => [...s].sort().join('')

test('click toggles one row', () => {
  assert.equal(list(pick(new Set(), order, 'c', null, false)), 'c')
  assert.equal(list(pick(new Set(['c']), order, 'c', 'c', false)), '')
})

test('shift-click selects or clears a range in either direction', () => {
  assert.equal(list(pick(new Set(['b']), order, 'd', 'b', true)), 'bcd')
  assert.equal(list(pick(new Set(['d']), order, 'a', 'd', true)), 'abcd')
  assert.equal(list(pick(new Set(order), order, 'b', 'd', true)), 'ae')
  // anchor scrolled out of the results: just the row
  assert.equal(list(pick(new Set(), order, 'b', 'zz', true)), 'b')
})
