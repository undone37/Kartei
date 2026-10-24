import assert from 'node:assert/strict'
import { test } from 'node:test'
import { personsAlong } from '../src/lib/deletion.ts'

// company uid -> its persons; persons and companies without persons aren't in the map
const persons = new Map([['c1', ['p1', 'p2']], ['c2', ['p3']], ['c3', []]])
const of = (uid: string) => persons.get(uid)

test('a company takes its persons along', () => {
  assert.deepEqual(personsAlong(['c1'], of), ['p1', 'p2'])
  assert.deepEqual(personsAlong(['c3'], of), [])
})

test('selected persons and plain persons are not counted again', () => {
  assert.deepEqual(personsAlong(['c1', 'p1', 'x'], of), ['p2'])
  assert.deepEqual(personsAlong(['p1', 'p3'], of), [])
})

test('several companies', () => {
  assert.deepEqual(personsAlong(new Set(['c2', 'c1']), of).sort(), ['p1', 'p2', 'p3'])
})
