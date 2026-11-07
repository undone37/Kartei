import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fromText } from '../src/lib/signature.ts'
import type { Field } from '../src/lib/types.ts'

const field = (key: string, vcard: string, vcard_label = '') => ({ key, vcard, vcard_label, applies_to: 'both', archived: false }) as Field
const FIELDS = [
  field('email', 'email_work'), field('phone_work', 'tel_work'), field('mobile', 'tel_cell'), field('fax', 'tel_fax_work'),
  field('job_title', 'title'), field('website', 'url'), field('salutation_title', 'n_prefix'),
  field('work_street', 'adr_work_street'), field('work_city', 'adr_work_city'), field('work_zip', 'adr_work_zip'),
  field('work_country', 'adr_work_country'),
]
const read = (text: string) => fromText(text, FIELDS)!

test('German signature: greeting, name, title, company, address, labelled numbers, legal footer', () => {
  const d = read(`Mit freundlichen Grüßen

Erika Muster
Leitung Einkauf

Beispielwerke Nord GmbH
Musterstraße 12
30159 Hannover

Tel.: +49 511 1000-12
Mobil: +49 170 1234567
Fax: +49 511 1000-99
E-Mail: erika.muster@beispiel.example
www.beispiel.example

Geschäftsführer: Max Beispiel · Amtsgericht Hannover HRB 12345`)
  assert.equal(d.kind, 'person')
  assert.deepEqual([d.first_name, d.last_name, d.company_name], ['Erika', 'Muster', 'Beispielwerke Nord GmbH'])
  assert.deepEqual(d.data, {
    job_title: 'Leitung Einkauf', work_street: 'Musterstraße 12', work_zip: '30159', work_city: 'Hannover',
    phone_work: '+49 511 1000-12', mobile: '+49 170 1234567', fax: '+49 511 1000-99',
    email: 'erika.muster@beispiel.example', website: 'https://www.beispiel.example',
  })
  assert.deepEqual(d.unmapped, [])
})

test('one-line pieces separated by | and ·', () => {
  const d = read(`Jonas Koch | Vertrieb
Fiktiv Software KG · Codegasse 8, 04109 Leipzig
T +49 341 1333-44 | M +49 160 9997381 | jonas.koch@fiktiv.example`)
  assert.deepEqual([d.first_name, d.last_name, d.company_name], ['Jonas', 'Koch', 'Fiktiv Software KG'])
  assert.equal(d.data.job_title, 'Vertrieb')
  assert.deepEqual([d.data.work_street, d.data.work_zip, d.data.work_city], ['Codegasse 8', '04109', 'Leipzig'])
  assert.deepEqual([d.data.phone_work, d.data.mobile], ['+49 341 1333-44', '+49 160 9997381'])
})

test('English signature with academic title, unlabelled numbers and country', () => {
  const d = read(`Best regards,
Dr. Anna Fischer
Head of Research
Demo Netz Ltd
12 Sample Road, 10115 Berlin, Germany
+49 30 1234567
0151 2345678
anna.fischer@demonetz.example`)
  assert.deepEqual([d.first_name, d.last_name], ['Anna', 'Fischer'])
  assert.equal(d.data.salutation_title, 'Dr.')
  assert.equal(d.data.job_title, 'Head of Research')
  assert.equal(d.company_name, 'Demo Netz Ltd')
  assert.equal(d.data.work_country, 'Germany')
  assert.deepEqual([d.data.phone_work, d.data.mobile], ['+49 30 1234567', '0151 2345678'])  // 015x: mobile
})

test('Austria and Switzerland: 4-digit postcodes, country line, name particles', () => {
  const at = read(`Lukas von Berg
Musterfirma Energie AG
Ringstraße 5
A-1010 Wien
Österreich
Telefon +43 1 234567`)
  assert.deepEqual([at.first_name, at.last_name], ['Lukas', 'von Berg'])
  assert.deepEqual([at.data.work_zip, at.data.work_city, at.data.work_country], ['1010', 'Wien', 'Österreich'])
  const ch = read(`Clara Becker\nPlatzhalter Logistik GmbH\nBahnhofplatz 3, 8001 Zürich\nDirekt: +41 44 123 45 67`)
  assert.deepEqual([ch.data.work_zip, ch.data.work_city, ch.data.phone_work], ['8001', 'Zürich', '+41 44 123 45 67'])
})

test('no name line: the name comes from first.last@ when a company is known', () => {
  const d = read(`Beispiel Stiftung\nmia.becker@stiftung.example\nTel 0511 4711`)
  assert.deepEqual([d.kind, d.first_name, d.last_name], ['person', 'Mia', 'Becker'])
})

test('only a company: becomes a company', () => {
  const d = read(`Musterfirma Energie AG\nIndustriestraße 1\n45127 Essen\nZentrale: 0201 123456\ninfo@musterfirma.example`)
  assert.equal(d.kind, 'company')
  assert.equal(d.name, 'Musterfirma Energie AG')
  assert.equal(d.data.work_city, 'Essen')
})

test('what is not recognised is listed, and a second mobile number does not get lost', () => {
  const d = read(`Tim Richter\nProjektleitung\nBeispielwerke Nord GmbH\nBesuchen Sie uns auf der Messe!\nMobil: 0170 1111111\nMobil: 0170 2222222`)
  assert.equal(d.data.mobile, '0170 1111111')
  assert.ok(d.unmapped.includes('0170 2222222'))
  assert.ok(d.unmapped.includes('Besuchen Sie uns auf der Messe!'))
})

test('nothing usable gives no draft', () => {
  assert.equal(fromText('Viele Grüße\n--\nGesendet von meinem iPhone', FIELDS), null)
})
