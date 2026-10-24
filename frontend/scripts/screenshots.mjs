// Screenshots for the manuals: `npm run screenshots` (demo server on :8000 with the demo database).
// Usage: node scripts/screenshots.mjs [--lang de,en] [--only name,...] [--out ../manuals/img] [--theme light]
//        [--base http://localhost:8000] [--password demo12345] [--admin-password admin12345]
// Expects a fresh database with `manage.py seed_demo` data.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt }
const BASE = arg('base', 'http://localhost:8000')
const OUT = arg('out', '../manuals/img')
const LANGS = arg('lang', 'de,en').split(',')
const ONLY = arg('only', '') ? arg('only', '').split(',') : null
const THEME = arg('theme', 'light')
// the admin from init_app and the demo users from `manage.py seed_demo --password …`
const DEMO = arg('password', 'demo12345')
const USERS = { admin: arg('admin-password', 'admin12345'), mmuster: DEMO, kkramer: DEMO }

const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const click = (page, text) => page.getByRole('button', { name: text, exact: true }).first().click()

/** name, user, path, optional steps to prepare the screen; selectors avoid UI text so both languages work */
const open = (sel) => async (p) => { await p.locator(sel).first().click(); await wait(500) }
const SHOTS = [
  { name: 'login', user: null, path: '/' },
  { name: 'dashboard', user: 'mmuster', path: '/' },
  { name: 'dashboard-read', user: 'kkramer', path: '/' },
  { name: 'search', user: 'admin', path: '/', steps: async (p) => { await p.keyboard.press('/'); await p.keyboard.type('koch'); await wait(300) } },
  { name: 'filter-menu', user: 'admin', path: '/', steps: open('[popovertarget="filter-menu"]') },
  { name: 'advanced-filter', user: 'mmuster', path: '/', steps: async (p) => {
      await p.locator('[popovertarget="adv-menu"]').first().click(); await wait(300)
      await p.locator('#adv-menu button:has(.lucide-plus)').first().click().catch(() => {}); await wait(300)
    } },
  { name: 'saved-menu', user: 'admin', path: '/', steps: open('[popovertarget="saved-menu"]') },
  { name: 'export-menu', user: 'admin', path: '/', steps: open('[popovertarget="export-menu"]') },
  { name: 'user-menu', user: 'mmuster', path: '/', steps: open('[popovertarget="user-menu"]') },
  { name: 'new-menu', user: 'mmuster', path: '/', steps: open('[popovertarget="new-menu"]') },
  { name: 'person', user: 'mmuster', path: (h) => `/person/${h.person}` },
  { name: 'history', user: 'mmuster', path: (h) => `/person/${h.person}`, steps: open('nav.tabs button:nth-child(2)') },
  { name: 'company', user: 'mmuster', path: (h) => `/company/${h.company}` },
  { name: 'company-persons', user: 'mmuster', path: (h) => `/company/${h.company}`, steps: open('nav.tabs button:nth-child(2)') },
  { name: 'edit', user: 'mmuster', path: (h) => `/person/${h.person}`, steps: async (p) => { await p.keyboard.press('e'); await wait(400) } },
  { name: 'new-person', user: 'mmuster', path: (h) => `/new/person?company=${h.company}` },
  { name: 'review', user: 'kkramer', path: (h) => `/person/${h.review}` },
  { name: 'propose-change', user: 'kkramer', path: (h) => `/person/${h.review}`, steps: open('.panel.review .actions button:nth-child(2)') },
  { name: 'propose-delete', user: 'kkramer', path: (h) => `/person/${h.review}`, steps: open('.panel.review .actions button:nth-child(3)') },
  { name: 'review-list', user: 'kkramer', path: '/?list=review' },
  { name: 'proposal-change', user: 'mmuster', path: (h) => `/${h.change.kind}/${h.change.uid}` },
  { name: 'proposal-delete', user: 'mmuster', path: (h) => `/${h.del.kind}/${h.del.uid}` },
  { name: 'bulk', user: 'mmuster', path: '/', steps: async (p) => {
      await p.locator('button[aria-pressed]').first().click(); await wait(200)
      const rows = p.locator('.list a')
      for (const i of [1, 2, 4]) await rows.nth(i).click()
      await wait(300)
    } },
  { name: 'confirm-delete', user: 'mmuster', path: (h) => `/person/${h.person}`, steps: open('header .actions button.danger') },
  { name: 'confirm-delete-company', user: 'mmuster', path: (h) => `/company/${h.company}`, steps: open('header .actions button.danger') },
  { name: 'settings-sections', user: 'admin', path: '/settings/fields', steps: open('button[aria-pressed]') },
  { name: 'quality', user: 'admin', path: '/quality' },
  { name: 'duplicates', user: 'admin', path: '/duplicates' },
  { name: 'merge', user: 'admin', path: '/duplicates', steps: open('a[href^="/duplicates/"]') },
  { name: 'trash', user: 'mmuster', path: '/trash' },
  { name: 'account', user: 'kkramer', path: '/account' },
  { name: 'mobile', user: 'kkramer', path: '/', viewport: { width: 390, height: 844 } },
  { name: 'mobile-contact', user: 'kkramer', path: (h) => `/person/${h.person}`, viewport: { width: 390, height: 844 } },
  { name: 'dashboard-admin', user: 'admin', path: '/' },
  { name: 'user-menu-admin', user: 'admin', path: '/', steps: open('[popovertarget="user-menu"]') },
  { name: 'dup-hint', user: 'mmuster', path: (h) => `/new/person?company=${h.dupCompany}`, steps: async (p) => {
      await p.locator('#first_name').fill(h0.dupFirst); await p.locator('#last_name').fill(h0.dupLast); await wait(400) } },
  { name: 'batch', user: 'mmuster', path: (h) => `/company/${h.batch.uid}`, steps: async (p, h) => {
      await p.keyboard.press('e'); await wait(300)
      await p.locator('#f-company_phone').fill(h.batch.phone.replace(/\d+$/, '3000')) // new number, same area code
      await p.keyboard.press('Control+s'); await wait(1200)
    }, after: async (ctx, h) => {
      // put the demo company back as it was
      const r = await (await api(ctx, 'get', `/api/records/${h.batch.uid}`)).json()
      await api(ctx, 'patch', `/api/records/${h.batch.uid}`, { version: r.version, data: { company_phone: h.batch.phone } })
    } },
  { name: 'proposal-own', user: 'kkramer', path: (h) => `/${h.change.kind}/${h.change.uid}` },
  { name: 'propose-delete-person', user: 'kkramer', path: (h) => `/person/${h.reviewPerson}`, steps: open('.panel.review .actions button:nth-child(3)') },
  { name: 'proposal-company-gone', user: 'mmuster', path: (h) => `/company/${h.gone}` },
  { name: 'quality-open', user: 'admin', path: '/quality', steps: async (p) => { await p.locator('details.card summary').nth(5).click(); await wait(300) } },
  { name: 'settings-field-editor', user: 'admin', path: '/settings/fields', steps: open('tr.click >> nth=2') },
  { name: 'settings-export-editor', user: 'admin', path: '/settings/exports', steps: open('tr.click') },
  { name: 'settings-review-rolling', user: 'admin', path: '/settings/review', steps: open('input[type=radio][value=rolling]') },
  { name: 'settings-general-phones', user: 'admin', path: '/settings/general', steps: open('button:has(.lucide-phone)') },
  { name: 'settings-carddav-password', user: 'admin', path: '/settings/carddav', steps: open('button:has(.lucide-key-round)') },
  { name: 'settings-api-token', user: 'admin', path: '/settings/api', steps: async (p) => {
      await p.locator('form.toolbar input:not([type=radio])').fill('Telefonanlage')
      await p.locator('form.toolbar input[type=radio][value=write]').check().catch(() => {})
      await p.locator('form.toolbar button').click(); await wait(600)
    }, after: async (ctx) => {
      const { tokens } = await (await api(ctx, 'get', '/api/admin/tokens')).json()
      for (const tk of tokens.filter((x) => x.name === 'Telefonanlage')) await api(ctx, 'delete', `/api/admin/tokens/${tk.id}`)
    } },
  ...['fields', 'users', 'ldap', 'carddav', 'outlook', 'ad', 'review', 'mail', 'exports', 'import', 'api', 'general', 'audit']
    .map((tab) => ({ name: `settings-${tab}`, user: 'admin', path: `/settings/${tab}` })),
]

async function login(ctx, user, lang) {
  const r = ctx.request
  await r.get(`${BASE}/api/session`)
  const csrf = async () => (await ctx.cookies()).find((c) => c.name === 'csrftoken')?.value ?? ''
  await r.post(`${BASE}/api/logout`, { headers: { 'X-CSRFToken': await csrf() } })
  if (!user) return
  const res = await r.post(`${BASE}/api/login`, { data: { username: user, password: USERS[user] }, headers: { 'X-CSRFToken': await csrf(), Referer: BASE } })
  if (!res.ok()) throw new Error(`login ${user}: ${res.status()}`)
  await r.patch(`${BASE}/api/me`, { data: { language: lang }, headers: { 'X-CSRFToken': await csrf(), Referer: BASE } })
}

async function api(ctx, method, path, body) {
  const csrf = (await ctx.cookies()).find((c) => c.name === 'csrftoken')?.value ?? ''
  return ctx.request[method](`${BASE}${path}`, { data: body, headers: { 'X-CSRFToken': csrf, Referer: BASE } })
}

let h0 = {}
async function hints(ctx, lang) {
  // a person with company, a company with persons, a contact under review and the pending proposals
  await login(ctx, 'kkramer', lang)
  const kb = await (await ctx.request.get(`${BASE}/api/bootstrap`)).json()
  const review = kb.reviews[0]?.record
  const reviewPerson = kb.reviews.map((r) => r.record).find((u) => kb.records.find((x) => x.uid === u)?.kind === 'person')
  await login(ctx, 'admin', lang)
  const b = await (await ctx.request.get(`${BASE}/api/bootstrap`)).json()
  const kind = (uid) => ({ uid, kind: b.records.find((r) => r.uid === uid)?.kind ?? 'person' })
  const change = b.proposals.find((p) => p.kind === 'change')
  const del = b.proposals.find((p) => p.kind === 'delete' && p.reason !== 'company_gone')
  const company = b.records.filter((r) => r.kind === 'company')
    .map((c) => ({ c, n: b.records.filter((r) => r.company === c.uid).length })).sort((a, z) => z.n - a.n)[0]?.c
  const person = b.records.find((r) => r.kind === 'person' && r.company && Object.keys(r.data).length > 4)
  const byName = (n) => b.records.find((r) => r.kind === 'company' && r.name === n)
  // a person whose name exists twice in the same company (for the duplicate hint)
  const twin = b.records.find((r) => r.kind === 'person' && b.records.some((o) => o !== r && o.kind === 'person' &&
    o.first_name === r.first_name && o.last_name === r.last_name && o.company === r.company))
  const demo = byName('Demo Netz GmbH')
  const gone = b.proposals.find((p) => p.reason === 'company_gone')
  h0 = { dupFirst: twin?.first_name ?? 'Greta', dupLast: twin?.last_name ?? 'Wagner' }
  return { company: company?.uid, person: person?.uid, review, reviewPerson, change: change && kind(change.record), del: del && kind(del.record),
           dupCompany: twin?.company ?? company?.uid, batch: demo && { uid: demo.uid, phone: demo.data.company_phone }, gone: gone?.record }
}

const browser = await chromium.launch()
for (const lang of LANGS) {
  mkdirSync(`${OUT}/${lang}`, { recursive: true })
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: THEME, locale: lang })
  // every screen starts from the same list (a ?list= link still wins)
  await ctx.addInitScript((theme) => { localStorage.setItem('kartei:theme', theme); localStorage.setItem('kartei:scope', 'all') }, THEME)
  const h = await hints(ctx, lang)
  let current = 'admin'
  for (const s of SHOTS) {
    if (ONLY && !ONLY.includes(s.name)) continue
    if (s.user !== current) { await login(ctx, s.user, lang); current = s.user }
    const page = await ctx.newPage()
    try {
      if (s.viewport) await page.setViewportSize(s.viewport)
      await page.goto(BASE + (typeof s.path === 'function' ? s.path(h) : s.path))
      await page.waitForLoadState('networkidle')
      await wait(400)
      if (s.steps) await s.steps(page, h)
      await page.screenshot({ path: `${OUT}/${lang}/${s.name}.png` })
      console.log(lang, s.name)
    } catch (e) {
      console.error(`FAILED ${lang} ${s.name}: ${e.message.split('\n')[0]}`) // keep going, report at the end
    } finally {
      await page.close()
      if (s.after) await s.after(ctx, h)
    }
  }
  await ctx.close()
}
// leave the demo users on the default language again
const ctx = await browser.newContext()
for (const u of Object.keys(USERS)) {
  await login(ctx, u, '')
}
await browser.close()
