import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import de from '../src/i18n/de.ts'
import en from '../src/i18n/en.ts'
import { CORE, OPS } from '../src/lib/advanced.ts'

const files = (dir: string): string[] =>
  readdirSync(dir).flatMap((f) => (statSync(join(dir, f)).isDirectory() ? files(join(dir, f)) : [join(dir, f)]))

test('de and en have the same keys', () => {
  assert.deepEqual(Object.keys(en).sort(), Object.keys(de).sort())
})

test('every literal t() key exists', () => {
  const used = new Set<string>()
  for (const f of files('src').filter((f) => /\.(svelte|ts)$/.test(f))) {
    for (const m of readFileSync(f, 'utf8').matchAll(/\bt\('([a-z_.]+)'/g)) used.add(m[1])
  }
  const missing = [...used].filter((k) => !(k in de))
  assert.deepEqual(missing, [])
})

test('dynamic key families are complete', () => {
  const families: Record<string, string[]> = {
    type: ['text', 'longtext', 'integer', 'decimal', 'select', 'multiselect', 'phone', 'email', 'url', 'date', 'checkbox', 'user', 'users', 'contact'],
    role: ['read', 'maintainer', 'admin'],
    applies: ['person', 'company', 'both'],
    settings: ['fields', 'users', 'ldap', 'carddav', 'outlook', 'ad', 'review', 'mail', 'exports', 'import', 'api', 'general', 'audit'],
    scope: ['all', 'responsible', 'internal', 'review', 'proposals', 'responsible_hint', 'internal_hint', 'review_hint', 'proposals_hint'],
    review: ['mode_off', 'mode_rolling', 'mode_campaign'],
    'audit.attr': ['archived', 'order', 'key', 'email', 'start_tls', 'carddav_username', 'carddav_password', 'review_mode',
      'proposed_by', 'note', 'comment', 'delete', 'reviewed', 'batch_from', 'started', 'adjusted', 'kind', 'reason', 'bulk',
      'normalized', 'merged_from', 'merged_into', 'not_duplicate', 'with_company'],
    'audit.label': ['settings', 'reviews', 'outlook', 'ad', 'phones'],
    proposal: ['reason_left', 'reason_company_gone', 'reason_other'],
    audit: ['create', 'update', 'delete', 'restore', 'purge', 'import', 'password', 'reorder', 'preset', 'propose', 'reject', 'review', 'sync', 'withdraw',
      'export', 'merge', 'not_duplicate', 'normalize'],
    'audit.type': ['record', 'field', 'section', 'user', 'settings', 'export', 'token'],
    calc: ['uid', 'legacy_id', 'legacy_or_uid', 'display_name', 'company_name', 'kind', 'created_at', 'updated_at'],
    core: ['first_name', 'last_name', 'name', 'company', 'image'],
    bulk: ['op_set', 'op_clear', 'op_add', 'op_remove', 'op_responsible', 'op_delete'],
    quality: ['no_responsible', 'invalid', 'no_reach', 'no_company', 'empty_company', 'never_reviewed', 'overdue'].map((s) => `sec_${s}`),
    dupes: ['email', 'phone', 'name'].map((r) => `reason_${r}`),
    adv: [...new Set(Object.values(OPS).flat())].map((o) => `op_${o}`)
      .concat(Object.keys(CORE).map((k) => `f_${k.slice(1)}`), ['mode_all', 'mode_any', 'mode_none']),
    'fields.import_status': ['new', 'changed', 'unchanged', 'invalid'],
  }
  // vCard targets come straight from the backend source of truth
  const py = readFileSync('../backend/kartei/vcard.py', 'utf8')
  const block = py.slice(py.indexOf('TARGETS = ['), py.indexOf(']\n', py.indexOf('TARGETS = [')))
  const parts = [...py.matchAll(/_ADR_PARTS = \[(.*?)\]/g)][0][1].match(/"(\w+)"/g)!.map((s) => s.slice(1, -1))
  families.vcard = [...block.matchAll(/"(\w+)"/g)].map((m) => m[1])
    .concat(parts.flatMap((p) => [`adr_work_${p}`, `adr_home_${p}`]))
  // server messages: msg("code", ...) anywhere in the backend
  families.msg = files('../backend/kartei').filter((f) => f.endsWith('.py'))
    .flatMap((f) => [...readFileSync(f, 'utf8').matchAll(/\bmsg\("(\w+)"/g)].map((m) => m[1]))
  for (const [prefix, values] of Object.entries(families)) {
    for (const v of values) assert.ok(`${prefix}.${v}` in de, `${prefix}.${v}`)
  }
})
