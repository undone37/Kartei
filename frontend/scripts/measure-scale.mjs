// How the browser copes with many contacts: run against a server with `manage.py seed_scale` data.
// Usage: node scripts/measure-scale.mjs [--base http://localhost:8000] [--user scale000] [--password scale-12345]
// Measures sign-in until the list shows, the transfer size of the full sync, the JS heap, search and scroll latency, reload.
import { chromium } from '@playwright/test'

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt }
const BASE = arg('base', 'http://localhost:8000')
const USER = arg('user', 'scale000')
const PASSWORD = arg('password', 'scale-12345')
const row = (name, value) => console.log(`${name.padEnd(36)}${value}`)

const browser = await chromium.launch({ args: ['--enable-precise-memory-info'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const cdp = await page.context().newCDPSession(page)
await cdp.send('Network.enable')
let bootstrapBytes = 0
const sizes = new Map()
cdp.on('Network.responseReceived', (e) => { if (e.response.url.includes('/api/bootstrap')) sizes.set(e.requestId, 0) })
cdp.on('Network.loadingFinished', (e) => { if (sizes.has(e.requestId)) bootstrapBytes = e.encodedDataLength })

await page.goto(BASE)
await page.locator('input[autocomplete="username"]').fill(USER)
await page.locator('input[type="password"]').fill(PASSWORD)
let t = Date.now()
await page.keyboard.press('Enter')
await page.getByRole('listbox').getByRole('option').first().waitFor({ timeout: 120_000 })
row('sign-in until the list shows', `${((Date.now() - t) / 1000).toFixed(2)} s`)
row('full sync transferred', `${(bootstrapBytes / 1e6).toFixed(1)} MB`)
await page.waitForTimeout(2000)
await cdp.send('HeapProfiler.collectGarbage')
const heap = await page.evaluate(() => performance.memory.usedJSHeapSize)
row('JS heap after sign-in', `${(heap / 1e6).toFixed(0)} MB`)

// search: time from the last keystroke until the list stops changing
const search = async (text) => {
  await page.getByRole('searchbox').fill('')
  t = Date.now()
  await page.getByRole('searchbox').pressSequentially(text)
  await page.evaluate(() => new Promise((done) => {
    let quiet; const obs = new MutationObserver(() => { clearTimeout(quiet); quiet = setTimeout(stop, 150) })
    const stop = () => { obs.disconnect(); done() }
    obs.observe(document.body, { childList: true, subtree: true }); quiet = setTimeout(stop, 150)
  }))
  return Date.now() - t - 150
}
for (const q of ['müller', 'netz energie', 'hannover', 'zzzz']) row(`search "${q}"`, `${await search(q)} ms`)
await page.getByRole('searchbox').fill('')

// scrolling the full list: frames that took longer than 50 ms
const long = await page.evaluate(async () => {
  const box = document.querySelector('[role="listbox"]')
  let el = box; while (el && el.scrollHeight <= el.clientHeight + 1) el = el.parentElement
  el ??= document.scrollingElement
  let slow = 0, last = performance.now()
  for (let i = 0; i < 60; i++) {
    el.scrollTop += 2000
    await new Promise(requestAnimationFrame)
    const now = performance.now(); if (now - last > 50) slow++; last = now
  }
  return slow
})
row('slow frames while scrolling (of 60)', `${long}`)

// a reload starts from the copy in the browser (IndexedDB) and only fetches the changes
t = Date.now()
await page.reload()
await page.getByRole('listbox').getByRole('option').first().waitFor({ timeout: 120_000 })
row('reload until the list shows', `${((Date.now() - t) / 1000).toFixed(2)} s`)
await browser.close()
