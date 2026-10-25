// End-to-end tests in a real browser against a server with fresh `seed_demo` data (see playwright.config.mjs).
// Users: admin from init_app (E2E_ADMIN_PASSWORD), the demo users from `seed_demo --password` (E2E_PASSWORD).
// Every test puts the data back, so the suite can run again on the same database.
import { test as base, expect } from '@playwright/test'
import { createHmac } from 'node:crypto'
import AxeBuilder from '@axe-core/playwright'

const PW = { admin: process.env.E2E_ADMIN_PASSWORD || 'admin12345', other: process.env.E2E_PASSWORD || 'demo12345' }

/** `as(user)` gives a signed-in page in English; uncaught page errors and console errors fail the test */
const test = base.extend({
  as: async ({ browser }, use) => {
    const contexts = [], errors = []
    await use(async (user, options = {}) => {
      const ctx = await browser.newContext(options)
      contexts.push(ctx)
      ctx.on('weberror', (e) => errors.push(`${user}: ${e.error().message}`))
      ctx.on('console', (m) => { if (m.type() === 'error' && !/status of 4\d\d/.test(m.text())) errors.push(`${user}: ${m.text()}`) })
      const csrf = async () => (await ctx.cookies()).find((c) => c.name === 'csrftoken')?.value ?? ''
      const call = async (method, path, data) => {
        const res = await ctx.request[method](path, { data, headers: { 'X-CSRFToken': await csrf(), Referer: test.info().project.use.baseURL } })
        return res.status() === 204 ? null : res.json()
      }
      if (user) {
        await ctx.request.get('/api/session')
        const res = await ctx.request.post('/api/login', { data: { username: user, password: user === 'admin' ? PW.admin : PW.other },
          headers: { 'X-CSRFToken': await csrf(), Referer: test.info().project.use.baseURL } })
        expect(res.ok(), `login ${user}`).toBeTruthy()
        await call('patch', '/api/me', { language: 'en' })
      }
      const page = await ctx.newPage()
      page.api = call
      page.records = async () => (await call('get', '/api/bootstrap')).records
      // contacts without an open proposal, so the proposal panel doesn't add its own buttons
      page.free = async () => { const b = await call('get', '/api/bootstrap'); const busy = new Set(b.proposals.map((x) => x.record)); return b.records.filter((r) => !busy.has(r.uid)) }
      return page
    })
    for (const ctx of contexts) await ctx.close()
    expect(errors, 'browser errors').toEqual([])
  },
})

const list = (page) => page.getByRole('listbox')
const row = (page, text) => list(page).getByRole('option').filter({ hasText: text }).first()
const search = (page) => page.getByRole('searchbox')
/** pick the first option of a searchable select (Combobox) */
async function choose(page, input) {
  await input.click()
  await page.locator(`#${await input.getAttribute('aria-controls')} [role=option]`).first().click()
}
const dialog = (page) => page.locator('dialog[open]')
const actions = (page) => page.locator('header .actions')
const deleteButton = (page) => actions(page).locator('button.danger')

/** TOTP (RFC 6238) like an authenticator app: the code for the current step plus `steps` */
function totpCode(secret, steps = 0) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const ch of secret) bits += alphabet.indexOf(ch).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000) + steps))
  const h = createHmac('sha1', key).update(counter).digest()
  const o = h[h.length - 1] & 15
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, '0')
}
test.describe('accessibility', () => {
  // WCAG 2.1 A/AA checks (axe-core) on the main screens, in both themes; serious and critical findings fail
  for (const theme of ['light', 'dark']) {
    test(`main screens have no serious accessibility problems (${theme})`, async ({ as }) => {
      const opts = { colorScheme: theme }
      const pages = [[null, '/'], ['mmuster', '/'], ['mmuster', 'person'], ['mmuster', '/new/person'], ['mmuster', '/phonelist'],
        ['mmuster', '/account'], ['admin', '/settings/fields'], ['admin', '/settings/users'], ['admin', '/settings/api']]
      const found = []
      for (const [user, path] of pages) {
        const page = await as(user, opts)
        await page.addInitScript((t) => localStorage.setItem('kartei:theme', t), theme)
        const target = path === 'person' ? `/person/${(await page.records()).find((r) => r.kind === 'person').uid}` : path
        await page.goto(target)
        await page.waitForLoadState('networkidle')
        const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
        for (const v of r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical'))
          found.push(`${path}: ${v.id} – ${v.nodes[0].target.join(' ')}`)
      }
      expect(found).toEqual([])
    })
  }
})

test.describe('sign-in', () => {
  test('a wrong password is refused, the right one opens the dashboard', async ({ as }) => {
    await as('kkramer') // sets the user's language to English
    const page = await as(null)
    await page.goto('/')
    await page.getByRole('button', { name: 'English' }).click()
    await page.locator('#u').fill('kkramer')
    await page.locator('#p').fill('wrong-password')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await page.locator('#p').fill(PW.other)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(list(page)).toBeVisible()
    await expect(page.getByText('Recently viewed')).toBeVisible()
  })
})

test.describe('two-factor sign-in', () => {
  test('set up with the app, then sign in with password and code', async ({ as }) => {
    const user = await as('lschmidt')
    await user.goto('/account')
    await user.getByRole('button', { name: 'Set up' }).click()
    await expect(user.getByRole('img', { name: 'QR code for the authenticator app' })).toBeVisible()
    const secret = (await user.locator('code').first().textContent()).trim()
    await user.getByLabel('Code from the app').fill(totpCode(secret))
    await user.locator('#totp-pw').fill(process.env.E2E_PASSWORD || 'demo12345')
    await user.getByRole('button', { name: 'Switch on' }).click()
    await expect(user.getByText('Keep these recovery codes safe')).toBeVisible()
    const recovery = (await user.locator('.codes code').allTextContents()).map((c) => c.trim())
    expect(recovery).toHaveLength(8)
    try {
      const page = await as(null)
      await page.goto('/')
      await page.locator('#u').fill('lschmidt')
      await page.locator('#p').fill(process.env.E2E_PASSWORD || 'demo12345')
      await page.getByRole('button', { name: 'Sign in' }).click()
      await expect(page.getByText('Enter the code from your authenticator app')).toBeVisible()
      await page.locator('#c').fill('000000')
      await page.getByRole('button', { name: 'Sign in' }).click()
      await expect(page.getByRole('alert')).toHaveText('The code is not correct')
      await page.locator('#c').fill(totpCode(secret, 1)) // the next step: the setup already used the current one
      await page.getByRole('button', { name: 'Sign in' }).click()
      await expect(page.getByRole('listbox')).toBeVisible()
    } finally {
      await user.api('post', '/api/me/totp', { action: 'disable', code: recovery[0] })
    }
  })
})

test.describe('two-factor policy', () => {
  test('required for everyone: setup right after sign-in, then the app', async ({ as }) => {
    const admin = await as('admin')
    await admin.api('put', '/api/admin/settings', { totp_required: 'all' })
    // the admin is affected as well: it sets up its own two-factor sign-in through the API
    const { secret: adminSecret } = await admin.api('post', '/api/me/totp', { action: 'setup' })
    const adminCodes = (await admin.api('post', '/api/me/totp', { action: 'confirm', code: totpCode(adminSecret), password: PW.admin })).recovery
    let recovery = []
    try {
      const page = await as('lschmidt')
      await page.goto('/')
      await expect(page.getByRole('heading', { name: 'Set up two-factor sign-in' })).toBeVisible()
      await page.getByRole('button', { name: 'Set up' }).click()
      const secret = (await page.locator('code').first().textContent()).trim()
      await page.getByLabel('Code from the app').fill(totpCode(secret))
      await page.locator('#totp-pw').fill(PW.other)
      await page.getByRole('button', { name: 'Switch on' }).click()
      await expect(page.getByText('Keep these recovery codes safe')).toBeVisible()
      recovery = (await page.locator('.codes code').allTextContents()).map((c) => c.trim())
      await page.getByRole('button', { name: 'Saved them' }).click()
      await expect(page.getByRole('listbox')).toBeVisible()
    } finally {
      await admin.api('put', '/api/admin/settings', { totp_required: 'none' })
      await admin.api('post', '/api/me/totp', { action: 'disable', code: adminCodes[0] })
      if (recovery.length) {
        const user = await as(null)
        await user.api('get', '/api/session')
        await user.api('post', '/api/login', { username: 'lschmidt', password: PW.other, code: recovery[0] })
        await user.api('post', '/api/me/totp', { action: 'disable', code: recovery[1] })
      }
    }
  })
})

test.describe('finding contacts', () => {
  test('search by part of a phone number in another notation; Enter opens the hit', async ({ as }) => {
    const page = await as('kkramer')
    const p = (await page.records()).find((r) => r.kind === 'person' && r.data.phone_work)
    await page.goto('/')
    await expect(list(page)).toBeVisible()
    await page.keyboard.press('/')
    await expect(search(page)).toBeFocused()
    await page.keyboard.type('0' + p.data.phone_work.replace(/\D/g, '').slice(2)) // +49 511 … typed as 0511…
    await expect(list(page).getByRole('option')).toHaveCount(1)
    await expect(row(page, p.last_name)).toBeVisible()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(new RegExp(`/person/${p.uid}`))
    await expect(page.getByRole('heading', { name: `${p.first_name} ${p.last_name}` })).toBeVisible()
  })

  test('umlauts and spelling variants find the same contacts', async ({ as }) => {
    const page = await as('kkramer')
    await page.goto('/')
    const hits = async (q) => { await search(page).fill(q); await page.waitForTimeout(200); return list(page).getByRole('option').count() }
    const n = await hits('müller')
    expect(n).toBeGreaterThan(0)
    expect(await hits('mueller')).toBe(n)
    expect(await hits('MULLER')).toBe(n)
  })

  test('the quick filter narrows the list', async ({ as }) => {
    const page = await as('mmuster')
    await page.goto('/')
    const count = page.getByText(/^\d+ entr(y|ies)$/).first()
    const all = await count.textContent()
    await page.locator('[popovertarget="filter-menu"]').click()
    await choose(page, page.locator('#filter-menu input[role=combobox]').first())
    await expect(count).not.toHaveText(all)
  })
})

test.describe('phone list', () => {
  test('the current list as a printable phone list, grouped by company', async ({ as }) => {
    const page = await as('kkramer')
    const all = await page.records()
    const c = all.find((r) => r.kind === 'company' && all.some((p) => p.company === r.uid && p.data.phone_work))
    await page.goto('/')
    await search(page).fill(c.name)
    await page.locator('[popovertarget="export-menu"]').click()
    await page.getByRole('link', { name: /Phone list/ }).click()
    await expect(page).toHaveURL(/\/phonelist$/)
    const sheet = page.locator('article.sheet')
    await expect(sheet.locator('tr.co').first()).toHaveText(new RegExp(c.name))
    const person = all.find((p) => p.company === c.uid && p.data.phone_work)
    await expect(sheet.getByRole('row').filter({ hasText: `${person.last_name}, ${person.first_name}` }).first()).toContainText(
      person.data.phone_work.slice(-3))
    await page.getByLabel('by name').check()
    await expect(sheet.locator('tr.co')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Print / PDF' })).toBeEnabled()
  })
})

test.describe('roles', () => {
  test('read only: no edit, new contacts only as proposals, no settings', async ({ as }) => {
    const page = await as('kkramer')
    const p = (await page.free()).find((r) => r.kind === 'person')
    await page.goto(`/person/${p.uid}`)
    await expect(actions(page).getByRole('button', { name: 'Propose change' })).toBeVisible()
    await expect(actions(page).getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'New', exact: true }).click()
    await expect(page.getByRole('link', { name: 'Propose new person' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Person', exact: true })).toHaveCount(0)
    expect((await page.api('get', '/api/admin/settings')).error).toBeTruthy()
  })

  test('every settings tab opens for the admin', async ({ as }) => {
    const page = await as('admin')
    for (const tab of ['fields', 'users', 'ldap', 'carddav', 'outlook', 'ad', 'review', 'mail', 'exports', 'import', 'api', 'general', 'audit']) {
      await page.goto(`/settings/${tab}`)
      await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    }
  })
})

test.describe('webhooks', () => {
  test('an admin adds a webhook, sees the secret once, tests and deletes it', async ({ as }) => {
    const page = await as('admin')
    await page.goto('/settings/api')
    const form = page.locator('form').filter({ has: page.getByLabel('Address (URL)') }) // waits for the webhooks section
    await form.getByLabel('Name').fill('E2E hook')
    await form.getByLabel('Address (URL)').fill('http://127.0.0.1:9/unreachable')
    await form.getByRole('button', { name: 'Add webhook' }).click()
    await expect(page.getByText(/^whsec_/)).toBeVisible()
    const row = page.getByRole('row').filter({ hasText: 'E2E hook' })
    try {
      await row.getByRole('button', { name: 'Send test event' }).click()
      await expect(page.getByText(/Test event not delivered/)).toBeVisible()
      await page.reload()
      await expect(page.getByText(/^whsec_/)).toHaveCount(0) // shown only once
    } finally {
      await row.getByRole('button', { name: 'Delete' }).click()
      await dialog(page).getByRole('button', { name: 'Delete' }).click()
      await expect(row).toHaveCount(0)
    }
  })
})

test.describe('editing', () => {
  test('a maintainer edits a person; the change is saved and in the history', async ({ as }) => {
    const page = await as('mmuster')
    const p = (await page.free()).find((r) => r.kind === 'person' && r.data.job_title)
    try {
      await page.goto(`/person/${p.uid}`)
      await expect(page.getByRole('heading', { name: `${p.first_name} ${p.last_name}` })).toBeVisible()
      await page.keyboard.press('e') // shortcut for Edit
      await page.locator('#f-job_title').fill('E2E Teamleitung')
      await page.keyboard.press('Control+s')
      await expect(page.locator('#f-job_title')).toHaveCount(0) // back to the view
      await page.reload()
      await expect(page.getByText('E2E Teamleitung').first()).toBeVisible()
      await page.getByRole('button', { name: 'History' }).click()
      await expect(page.getByText(p.data.job_title).first()).toBeVisible()
    } finally {
      const r = (await page.records()).find((x) => x.uid === p.uid)
      await page.api('patch', `/api/records/${p.uid}`, { version: r.version, data: { job_title: p.data.job_title } })
    }
  })

  test('invalid input is flagged while typing and blocks saving', async ({ as }) => {
    const page = await as('mmuster')
    const p = (await page.free()).find((r) => r.kind === 'person' && r.data.email)
    await page.goto(`/person/${p.uid}`)
    await actions(page).getByRole('button', { name: 'Edit', exact: true }).click()
    await page.locator('#f-email').fill('not-an-email')
    await page.locator('#f-email').blur()
    await expect(page.getByText('Not a valid email address')).toBeVisible()
    await page.keyboard.press('Control+s')
    await expect(page.locator('#f-email')).toBeVisible() // still in the form
    expect((await page.records()).find((r) => r.uid === p.uid).data.email).toBe(p.data.email)
  })

  test('administrators are not offered as internal contacts', async ({ as }) => {
    const page = await as('mmuster')
    const p = (await page.free()).find((r) => r.kind === 'person')
    await page.goto(`/person/${p.uid}`)
    await actions(page).getByRole('button', { name: 'Edit', exact: true }).click()
    const input = page.locator('#f-internal_contacts')
    await input.click()
    const list = page.locator(`#${await input.getAttribute('aria-controls')}`)
    await expect(list.getByRole('option').first()).toBeVisible()
    await expect(list.getByRole('option', { name: /\badmin\b/ })).toHaveCount(0)
    await expect(list.getByRole('option', { name: /mmuster/ })).toHaveCount(1)
  })

  test('a new person at a company', async ({ as }) => {
    const page = await as('mmuster')
    const c = (await page.records()).find((r) => r.kind === 'company')
    await page.goto(`/new/person?company=${c.uid}`)
    await page.locator('#first_name').fill('Erika')
    await page.locator('#last_name').fill('Endtoend')
    await choose(page, page.locator('#f-internal_contact')) // required in the example field set
    await page.keyboard.press('Control+s')
    await expect(page).toHaveURL(/\/person\/[0-9a-f-]{36}/)
    const uid = page.url().split('/person/')[1]
    try {
      await expect(page.getByRole('heading', { name: 'Erika Endtoend' })).toBeVisible()
      expect((await page.records()).find((x) => x.uid === uid).company).toBe(c.uid)
    } finally {
      await page.api('delete', `/api/records/${uid}`)
      const admin = await as('admin')
      await admin.api('delete', `/api/trash/${uid}`)
    }
  })
})

test.describe('reviews and proposals', () => {
  test('read only proposes a change, a maintainer applies it', async ({ as }) => {
    const reader = await as('kkramer')
    const p = (await reader.free()).find((r) => r.kind === 'person' && r.data.department)
    await reader.goto(`/person/${p.uid}`)
    await actions(reader).getByRole('button', { name: 'Propose change' }).click()
    await reader.locator('#f-department').fill('E2E Abteilung')
    await reader.getByRole('button', { name: 'Send proposal' }).click()
    await expect(reader.getByText('E2E Abteilung').first()).toBeVisible()

    const editor = await as('mmuster')
    try {
      await editor.goto(`/person/${p.uid}`)
      await editor.getByRole('button', { name: 'Apply', exact: true }).click()
      await expect(editor.getByText('Proposal applied')).toBeVisible()
      await expect.poll(async () => (await editor.records()).find((r) => r.uid === p.uid).data.department).toBe('E2E Abteilung')
    } finally {
      const r = (await editor.records()).find((x) => x.uid === p.uid)
      await editor.api('patch', `/api/records/${p.uid}`, { version: r.version, data: { department: p.data.department } })
    }
  })
})

test.describe('new contact proposals', () => {
  test('read only proposes a new person, a maintainer creates it', async ({ as }) => {
    const reader = await as('kkramer')
    await reader.goto('/')
    await reader.getByRole('button', { name: 'New' }).click()
    await reader.getByRole('link', { name: 'Propose new person' }).click()
    await expect(reader.getByText('The contact is not created directly')).toBeVisible()
    await reader.locator('#first_name').fill('Paula')
    await reader.locator('#last_name').fill('Proposal')
    await choose(reader, reader.locator('#company'))
    await choose(reader, reader.locator('#f-internal_contact'))
    await reader.locator('#proposal-comment').fill('neue Kollegin')
    await reader.getByRole('button', { name: 'Send proposal' }).click()
    await expect(reader).toHaveURL(/\/proposal\/\d+/)
    const id = reader.url().split('/proposal/')[1]
    await expect(reader.getByRole('heading', { name: 'Paula Proposal' })).toBeVisible()
    await expect(reader.getByText('Awaiting approval')).toBeVisible()

    const editor = await as('mmuster')
    await editor.goto('/')
    await editor.getByRole('tab', { name: /Proposals/ }).click()
    await editor.getByRole('link', { name: /Paula Proposal/ }).click()
    await expect(editor).toHaveURL(new RegExp(`/proposal/${id}$`))
    await editor.getByRole('button', { name: 'Create', exact: true }).click()
    await expect(editor).toHaveURL(/\/person\/[0-9a-f-]{36}/)
    const uid = editor.url().split('/person/')[1]
    try {
      await expect(editor.getByRole('heading', { name: 'Paula Proposal' })).toBeVisible()
      expect((await editor.records()).some((r) => r.uid === uid)).toBe(true)
    } finally {
      await editor.api('delete', `/api/records/${uid}`)
      await (await as('admin')).api('delete', `/api/trash/${uid}`)
    }
  })
})

test.describe('vCard import', () => {
  test('a maintainer imports a .vcf: pre-filled form, linked company, skip, summary', async ({ as }) => {
    const page = await as('mmuster')
    const c = (await page.records()).find((r) => r.kind === 'company')
    const vcf = ['BEGIN:VCARD', 'VERSION:3.0', 'N:Vogelsang;Vera;;;', `ORG:${c.name};Einkauf`, 'TITLE:Einkauf',
      'EMAIL;TYPE=WORK:vera.vogelsang@beispiel.example', 'TEL;TYPE=CELL:+49 170 5550101', 'END:VCARD',
      'BEGIN:VCARD', 'VERSION:3.0', 'KIND:org', 'FN:Zweite Testfirma', 'ORG:Zweite Testfirma', 'END:VCARD'].join('\r\n')
    await page.goto('/')
    await page.getByRole('button', { name: 'New' }).click()
    await page.getByRole('link', { name: 'Import from vCard …' }).click()
    await page.locator('input[type=file]').setInputFiles({ name: 'contacts.vcf', mimeType: 'text/vcard', buffer: Buffer.from(vcf) })
    await expect(page.getByText('Contact 1 of 2')).toBeVisible()
    await expect(page.locator('#last_name')).toHaveValue('Vogelsang')
    await expect(page.locator('#f-email')).toHaveValue('vera.vogelsang@beispiel.example')
    await expect(page.locator('#f-mobile')).toHaveValue('+49 170 5550101')
    await choose(page, page.locator('#f-internal_contact'))
    await page.keyboard.press('Control+s')
    await expect(page.getByText('Contact 2 of 2')).toBeVisible()
    await page.getByRole('button', { name: 'Skip' }).click()
    await expect(page.getByText('Done: 1 created, 0 proposed, 1 skipped.')).toBeVisible()
    const r = (await page.records()).find((x) => x.last_name === 'Vogelsang')
    try {
      expect(r.company).toBe(c.uid)
    } finally {
      await page.api('delete', `/api/records/${r.uid}`)
      await (await as('admin')).api('delete', `/api/trash/${r.uid}`)
    }
  })
})

test.describe('deleting', () => {
  test('delete asks first; the contact goes to the recycle bin and comes back', async ({ as }) => {
    const page = await as('mmuster')
    const p = (await page.free()).find((r) => r.kind === 'person')
    const exists = async () => (await page.records()).some((r) => r.uid === p.uid)
    await page.goto(`/person/${p.uid}`)
    await deleteButton(page).click()
    await dialog(page).getByRole('button', { name: 'Cancel' }).click()
    expect(await exists()).toBe(true)

    await deleteButton(page).click()
    await dialog(page).getByRole('button', { name: 'Move to recycle bin' }).click()
    await expect.poll(exists).toBe(false)
    await page.goto('/trash')
    await page.getByRole('row').filter({ hasText: `${p.first_name} ${p.last_name}` }).first().getByRole('button', { name: 'Restore' }).click()
    await expect.poll(exists).toBe(true)
  })

  test('a company can take its persons along; undo brings all back', async ({ as }) => {
    const page = await as('mmuster')
    const all = await page.records()
    const c = all.find((r) => r.kind === 'company' && all.some((p) => p.company === r.uid))
    const team = [c.uid, ...all.filter((p) => p.company === c.uid).map((p) => p.uid)]
    const live = async () => (await page.records()).filter((r) => team.includes(r.uid)).length
    await page.goto(`/company/${c.uid}`)
    await deleteButton(page).click()
    await dialog(page).getByRole('checkbox').check()
    await dialog(page).getByRole('button', { name: 'Move to recycle bin' }).click()
    await expect.poll(live).toBe(0)
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect.poll(live).toBe(team.length)
  })
})

test.describe('phone layout', () => {
  test('list and contact on a small screen', async ({ as }) => {
    const page = await as('kkramer', { viewport: { width: 390, height: 844 } })
    const p = (await page.records()).find((r) => r.kind === 'person')
    await page.goto('/')
    await row(page, `${p.first_name} ${p.last_name}`).click()
    await expect(page.getByRole('heading', { name: `${p.first_name} ${p.last_name}` })).toBeVisible()
    await expect(list(page)).toBeHidden()
  })
})
