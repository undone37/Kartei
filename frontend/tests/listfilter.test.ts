import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync } from 'node:fs'
import { listTest, type ListQuery } from '../src/lib/listfilter.ts'
import { buildIndex } from '../src/lib/search.ts'
import { emptyGroup } from '../src/lib/advanced.ts'
import type { Field, Rec } from '../src/lib/types.ts'

// the same cases run against the server's copy (backend/kartei/test_filters.py): both must give the same contacts
const FILE = new URL('./filter-cases.json', import.meta.url)
const doc = JSON.parse(readFileSync(FILE, 'utf8'))
const fields = doc.fields as Field[]
const records = doc.records as Rec[]
const index = buildIndex(records, fields, new Map(records.map((r) => [r.uid, r])))
const [y, m, d] = doc.today.split('-').map(Number)
const run = (s: any) => {
  const q: ListQuery = { q: s.q, scope: s.scope, kind: s.kind, adv: s.adv ?? emptyGroup(),
                         filters: Object.entries(s.filters as Record<string, string[]>).filter(([, v]) => v.length) }
  return index.filter(listTest(q, fields, doc.me, new Date(y, m - 1, d, 15))).map((x) => x.rec.uid).sort()
}

if (process.env.WRITE_EXPECTED) {  // regenerate after a deliberate change: WRITE_EXPECTED=1 node --test …
  for (const c of doc.cases) c.expect = run(c.state)
  writeFileSync(FILE, JSON.stringify(doc, null, 1) + '\n')
}
for (const c of doc.cases) test(`list filter: ${c.name}`, () => assert.deepEqual(run(c.state), c.expect))
