// The animated demo in the README: a scripted session with a visible mouse pointer, recorded and turned into an animated WebP.
// Usage: node scripts/demo-video.mjs [--base http://localhost:8000] [--password demo12345] [--out ../manuals/img/en/demo.webp]
// Expects a fresh database with `manage.py seed_demo` data, and ffmpeg on the PATH. Changes one job title.
import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const arg = (name, dflt) => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : dflt }
const BASE = arg('base', 'http://localhost:8000')
const OUT = arg('out', '../manuals/img/en/demo.webp')
const SIZE = { width: 1280, height: 800 }
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

// Playwright's video has no mouse pointer: draw one that follows the mouse, with a ripple on every click
const POINTER = () => {
  addEventListener('DOMContentLoaded', () => {
    const p = document.createElement('div')
    p.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l16 11-7 1.5L9.5 21z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>'
    p.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px)'
    document.body.append(p)
    addEventListener('mousemove', (e) => { p.style.left = `${e.clientX}px`; p.style.top = `${e.clientY}px` }, true)
    addEventListener('mousedown', (e) => {
      const r = document.createElement('div')
      r.style.cssText = `position:fixed;left:${e.clientX - 16}px;top:${e.clientY - 16}px;width:32px;height:32px;border-radius:50%;
        background:rgba(37,99,235,.35);z-index:2147483646;pointer-events:none;transition:transform .45s,opacity .45s`
      document.body.append(r)
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0' })
      setTimeout(() => r.remove(), 500)
    }, true)
  })
}

const browser = await chromium.launch()
const dir = mkdtempSync(join(tmpdir(), 'kartei-demo-'))
const ctx = await browser.newContext({ viewport: SIZE, locale: 'en', colorScheme: 'light', recordVideo: { dir, size: SIZE } })
await ctx.addInitScript(() => { localStorage.setItem('kartei:theme', 'light'); localStorage.setItem('kartei:scope', 'all') })
await ctx.addInitScript(POINTER)
const csrf = async () => (await ctx.cookies()).find((c) => c.name === 'csrftoken')?.value ?? ''
await ctx.request.get(`${BASE}/api/session`)
const res = await ctx.request.post(`${BASE}/api/login`, { data: { username: 'mmuster', password: arg('password', 'demo12345') },
  headers: { 'X-CSRFToken': await csrf(), Referer: BASE } })
if (!res.ok()) throw new Error(`login: ${res.status()}`)
await ctx.request.patch(`${BASE}/api/me`, { data: { language: 'en' }, headers: { 'X-CSRFToken': await csrf(), Referer: BASE } })

const page = await ctx.newPage()
const started = Date.now()
await page.goto(BASE)
await page.getByRole('listbox').getByRole('option').first().waitFor()
let at = { x: SIZE.width / 2, y: SIZE.height / 2 }
await page.mouse.move(at.x, at.y)
const glide = async (locator) => {
  const b = await locator.boundingBox()
  const to = { x: b.x + b.width / 2, y: b.y + b.height / 2 }
  const steps = Math.max(12, Math.round(Math.hypot(to.x - at.x, to.y - at.y) / 18))
  await page.mouse.move(to.x, to.y, { steps })
  at = to
}
const click = async (locator, pause = 900) => { await glide(locator); await wait(200); await locator.click(); await wait(pause) }
const skip = Date.now() - started // the page loading is cut from the video
await wait(700)

// search, open a person
const search = page.getByRole('searchbox')
await click(search, 300)
await search.pressSequentially('koch', { delay: 140 })
await wait(800)
await click(page.getByRole('listbox').getByRole('option').first(), 1500)

// edit and save
await click(page.getByRole('button', { name: 'Edit', exact: true }), 900)
const title = page.getByLabel(/job title/i).first()
await click(title, 200)
await page.keyboard.press('Control+A')
await page.keyboard.type('Head of Grid Operations', { delay: 60 })
await wait(500)
await click(page.getByRole('button', { name: 'Save', exact: true }), 2000)

// share as QR code
await click(page.locator('button:has(.lucide-qr-code)').first(), 2200)
await page.keyboard.press('Escape')
await wait(600)

// a click on a tag filters the list for every contact with it
const tag = page.locator('button.tag.filter').first()
if (await tag.count()) { await click(tag, 1600); await click(page.getByRole('listbox').getByRole('option').nth(1), 2500) }


await wait(1500) // the video loses its last moment when the page closes right away
await ctx.close()
await browser.close()
const video = join(dir, readdirSync(dir).find((f) => f.endsWith('.webm')))
// animated WebP: full colour and far smaller than a GIF; 15 frames per second, 1080 px wide, endless loop
execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', `${skip / 1000}`, '-i', video, '-vf', 'fps=15,scale=1080:-1:flags=lanczos',
  '-c:v', 'libwebp_anim', '-quality', '75', '-compression_level', '6', '-loop', '0', OUT])
rmSync(dir, { recursive: true })
console.log(`${OUT} written`)
