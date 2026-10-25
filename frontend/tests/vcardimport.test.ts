import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parse, toDraft } from '../src/lib/vcardimport.ts'
import type { Field } from '../src/lib/types.ts'

const field = (key: string, vcard: string, vcard_label = '', applies_to: Field['applies_to'] = 'both') =>
  ({ key, vcard, vcard_label, applies_to, archived: false }) as Field
const FIELDS = [
  field('email', 'email_work'), field('email_private', 'email_home'), field('phone_work', 'tel_work'),
  field('mobile', 'tel_cell'), field('company_phone', 'tel_custom', 'Zentrale'), field('job_title', 'title'),
  field('department', 'department'), field('birthday', 'bday'), field('work_street', 'adr_work_street'),
  field('work_city', 'adr_work_city'), field('work_zip', 'adr_work_zip'), field('keywords', 'categories'),
  field('website', 'url'), field('middle_name', 'n_middle'), field('hotline', 'tel_custom', 'Hotline'),
]

test('iPhone card: names, company, typed and labelled numbers, address, photo', () => {
  const vcf = [
    'BEGIN:VCARD', 'VERSION:3.0', 'N:Muster;Erika;Maria;;', 'FN:Erika Maria Muster',
    'ORG:Beispiel GmbH;Einkauf', 'TITLE:Teamleitung', 'EMAIL;type=INTERNET;type=WORK;type=pref:erika@beispiel.example',
    'TEL;type=CELL;type=VOICE:+49 170 1234567', 'TEL;type=WORK;type=VOICE:+49 511 1000-12',
    'item1.TEL:+49 511 1000', 'item1.X-ABLabel:Zentrale', 'item2.TEL:+49 511 9999', 'item2.X-ABLabel:Pager',
    'ADR;type=WORK:;;Musterstraße 1;Hannover;;30159;Deutschland', 'BDAY:1980-04-12',
    'CATEGORIES:Kunde,Partner', 'PHOTO;ENCODING=b;TYPE=JPEG:/9j/4AAQSkZJRg==',
    'NOTE:zweite\\nZeile', 'END:VCARD', '',
  ].join('\r\n')
  const [card] = parse(vcf)
  const d = toDraft(card, FIELDS)
  assert.equal(d.kind, 'person')
  assert.deepEqual([d.first_name, d.last_name, d.company_name], ['Erika', 'Muster', 'Beispiel GmbH'])
  assert.deepEqual(d.data, {
    middle_name: 'Maria', department: 'Einkauf', job_title: 'Teamleitung', email: 'erika@beispiel.example',
    mobile: '+49 170 1234567', phone_work: '+49 511 1000-12', company_phone: '+49 511 1000', work_street: 'Musterstraße 1',
    work_city: 'Hannover', work_zip: '30159', birthday: '1980-04-12', keywords: ['Kunde', 'Partner'],
  })
  assert.deepEqual(d.unmapped, ['Pager: +49 511 9999', 'Deutschland', 'zweite\nZeile'])
  assert.equal(d.photo?.type, 'image/jpeg')
})

test('vCard 2.1 from Outlook: folded lines, quoted-printable in Latin-1, several cards', () => {
  const vcf = 'BEGIN:VCARD\r\nVERSION:2.1\r\nN;CHARSET=ISO-8859-1;ENCODING=QUOTED-PRINTABLE:M=FCller;J=FCrgen\r\n' +
    'TEL;WORK;VOICE:0511 123\r\nEMAIL;PREF;INTERNET:j.mueller@\r\n firma.example\r\nEND:VCARD\r\n' +
    'BEGIN:VCARD\nVERSION:4.0\nKIND:org\nFN:Beispiel AG\nORG:Beispiel AG\nURL:https://beispiel.example\n' +
    'TEL;VALUE=uri;TYPE=work:tel:+49-511-555\nEND:VCARD\n'
  const cards = parse(vcf)
  assert.equal(cards.length, 2)
  const a = toDraft(cards[0], FIELDS)
  assert.deepEqual([a.last_name, a.first_name, a.data.phone_work, a.data.email], ['Müller', 'Jürgen', '0511 123', 'j.mueller@firma.example'])
  const b = toDraft(cards[1], FIELDS)
  assert.deepEqual([b.kind, b.name, b.data.website, b.data.phone_work], ['company', 'Beispiel AG', 'https://beispiel.example', '+49-511-555'])
})

test('only FN: split into first and last name; escaped separators', () => {
  const d = toDraft(parse('BEGIN:VCARD\nFN:Anna Lena Schulz\nORG:Kunz\\, Kunz & Partner\nEND:VCARD')[0], FIELDS)
  assert.deepEqual([d.kind, d.first_name, d.last_name, d.company_name], ['person', 'Anna Lena', 'Schulz', 'Kunz, Kunz & Partner'])
})

test('quoted-printable soft line breaks are joined, base64 padding is not', () => {
  const vcf = 'BEGIN:VCARD\r\nN:A;B\r\nNOTE;ENCODING=QUOTED-PRINTABLE:erste=0D=0A=\r\nzweite Zeile\r\nPHOTO;ENCODING=b:QU\r\n I=\r\nNOTE:x\r\nEND:VCARD'
  const d = toDraft(parse(vcf)[0], [field('note', 'note')])
  assert.equal(d.data.note, 'erste\r\nzweite Zeile')
  assert.equal(d.photo?.size, 2)
})
