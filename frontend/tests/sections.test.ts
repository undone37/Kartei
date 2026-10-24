import assert from 'node:assert/strict'
import { test } from 'node:test'
import { groupFields, moveField } from '../src/lib/sections.ts'
import type { Field, Section } from '../src/lib/types.ts'

const sec = (id: number, order: number): Section => ({ id, key: `s${id}`, label: { de: `S${id}`, en: `S${id}` }, order })
const fld = (id: number, section: number | null, order = id * 10) => ({ id, key: `f${id}`, section, order }) as Field
const sections = [sec(2, 10), sec(1, 20), sec(3, 30)]
const fields = [fld(1, 1), fld(2, 2), fld(3, null), fld(4, 1), fld(5, 99), fld(6, 2, 5)]
const shape = (gs: ReturnType<typeof groupFields>) => gs.map((g) => [g.section?.id ?? null, g.fields.map((f) => f.id)])

test('groups follow section order, fields their order, Other last', () => {
  assert.deepEqual(shape(groupFields(fields, sections)), [[2, [6, 2]], [1, [1, 4]], [null, [3, 5]]])
})

test('all keeps empty sections and Other as drop targets', () => {
  assert.deepEqual(shape(groupFields([], sections, true)), [[2, []], [1, []], [3, []], [null, []]])
})

test('moving within a section: down lands after the target, up before it', () => {
  const g = groupFields([fld(1, 1), fld(2, 1), fld(3, 1)], [sec(1, 10)], true)
  assert.deepEqual(moveField(g, 1, 1, 3).ids, [2, 3, 1])
  assert.deepEqual(moveField(g, 3, 1, 1).ids, [3, 1, 2])
  assert.deepEqual(moveField(g, 2, 1, 3).ids, [1, 3, 2])
})

test('moving into another section or onto its header', () => {
  const g = groupFields(fields, sections, true)
  assert.deepEqual(moveField(g, 1, 2, 2), { ids: [6, 1, 2, 4, 3, 5], section: 2 })
  assert.deepEqual(moveField(g, 1, 3), { ids: [6, 2, 4, 1, 3, 5], section: 3 })
  assert.deepEqual(moveField(g, 6, null), { ids: [2, 1, 4, 3, 5, 6], section: null })
})
