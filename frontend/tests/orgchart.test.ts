import { test } from 'node:test'
import assert from 'node:assert/strict'
import { hasOrg, managerField, orgTree, type OrgNode } from '../src/lib/orgchart.ts'
import type { Field, Rec } from '../src/lib/types.ts'

const p = (uid: string, manager?: string) => ({ uid, kind: 'person', last_name: uid, data: manager ? { manager } : {} }) as unknown as Rec
const name = (r: Rec) => r.last_name
const shape = (ns: OrgNode[]): any => ns.map((n) => n.children.length ? { [n.rec.uid]: shape(n.children) } : n.rec.uid)

test('tree: boss at the top, sorted, a manager outside the company makes a root', () => {
  const staff = [p('d', 'b'), p('b', 'a'), p('a'), p('c', 'a'), p('x', 'other-company')]
  assert.deepEqual(shape(orgTree(staff, 'manager', name)), [{ a: [{ b: ['d'] }, 'c'] }, 'x'])
  assert.equal(hasOrg(staff, 'manager'), true)
  assert.equal(hasOrg([p('a'), p('x', 'elsewhere')], 'manager'), false)
})

test('cycles and self-references: everyone appears exactly once', () => {
  const staff = [p('a', 'b'), p('b', 'a'), p('c', 'c'), p('d', 'a')]
  const all: string[] = []
  const walk = (ns: OrgNode[]) => ns.forEach((n) => { all.push(n.rec.uid); walk(n.children) })
  walk(orgTree(staff, 'manager', name))
  assert.deepEqual(all.sort(), ['a', 'b', 'c', 'd'])
})

test('depth limit: deeper people start their own branch', () => {
  const staff = [p('a'), p('b', 'a'), p('c', 'b')]
  assert.deepEqual(shape(orgTree(staff, 'manager', name, 1)), [{ a: ['b'] }, 'c'])
})

test('the manager field is the contact field with the related_manager target', () => {
  const f = (key: string, type: string, vcard: string) => ({ key, type, vcard, archived: false, applies_to: 'person' }) as Field
  assert.equal(managerField([f('ceo', 'contact', 'related_custom'), f('manager', 'contact', 'related_manager')])?.key, 'manager')
  assert.equal(managerField([f('manager', 'text', 'related_manager')]), undefined)
})
