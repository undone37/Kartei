import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseNumber, validate } from '../src/lib/validate.ts'
import type { Field } from '../src/lib/types.ts'

const f = (type: Field['type'], extra: Partial<Field> = {}) => ({ key: 'x', type, required: false, regex: '', min: null, max: null, ...extra }) as Field

test('required and empty', () => {
  assert.equal(validate(f('text'), ''), null)
  assert.equal(validate(f('text', { required: true }), '  '), null) // whitespace is a value; the server trims
  assert.equal(validate(f('text', { required: true }), ''), 'required')
  assert.equal(validate(f('multiselect', { required: true }), []), 'required')
})

test('email, phone, url, date', () => {
  assert.equal(validate(f('email'), 'a.meier@acme.com'), null)
  for (const bad of ['a.meier', 'a@b', 'a b@c.de', 'a@@c.de']) assert.equal(validate(f('email'), bad), 'invalid_email', bad)
  for (const ok of ['0511 1000-12', '+49 (0)511 1000 12', '0170/1234567']) assert.equal(validate(f('phone'), ok), null, ok)
  assert.equal(validate(f('phone'), '0511 abc'), 'invalid_phone')
  assert.equal(validate(f('url'), 'acme.com'), null)
  assert.equal(validate(f('url'), 'https://acme.com/x'), null)
  assert.equal(validate(f('url'), 'nicht eine url'), 'invalid_url')
  assert.equal(validate(f('date'), '2026-10-24'), null)
  assert.equal(validate(f('date'), '24.10.2026'), 'invalid_date')
})

test('numbers like the server', () => {
  assert.equal(parseNumber('1.234,5'), 1234.5)
  assert.equal(parseNumber('1234.5'), 1234.5)
  assert.ok(Number.isNaN(parseNumber('12a')))
  assert.equal(validate(f('integer'), '12,5'), 'invalid_integer')
  assert.equal(validate(f('integer'), 'zwölf'), 'invalid_number')
  assert.equal(validate(f('decimal', { min: '0', max: '100' }), '100,01'), 'too_large')
  assert.equal(validate(f('decimal', { min: '0' }), '-1'), 'too_small')
  assert.equal(validate(f('integer', { min: '1', max: '10' }), '10'), null)
})

test('regex and length', () => {
  const zip = f('text', { regex: String.raw`\d{5}` })
  assert.equal(validate(zip, '10115'), null)
  assert.equal(validate(zip, '4814'), 'pattern_mismatch')
  assert.equal(validate(f('text', { regex: '(' }), 'x'), null) // broken pattern: left to the server
  assert.equal(validate(f('text'), 'x'.repeat(1001)), 'too_long')
  assert.equal(validate(f('longtext'), 'x'.repeat(1001)), null)
})
