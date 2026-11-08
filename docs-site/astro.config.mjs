// The documentation site (https://undone37.github.io/Kartei/): Starlight with the Kartei look.
// Content: src/content/docs (start pages) and ../manuals (the manuals, split into chapter pages by src/manuals.ts).
import starlight from '@astrojs/starlight'
import { defineConfig } from 'astro/config'

export default defineConfig({
  site: 'https://undone37.github.io',
  base: '/Kartei',
  integrations: [
    starlight({
      title: 'Kartei',
      description: 'The contact directory for persons and companies: manuals for users and administrators.',
      logo: { src: './src/logo.svg' },
      favicon: '/favicon.svg',
      defaultLocale: 'root',
      locales: {
        root: { label: 'English', lang: 'en' },
        de: { label: 'Deutsch', lang: 'de' },
      },
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/undone37/Kartei' }],
      sidebar: [
        { label: 'User manual', translations: { de: 'Benutzerhandbuch' }, items: [{ autogenerate: { directory: 'user' } }] },
        { label: 'Administrator manual', translations: { de: 'Administrationshandbuch' }, items: [{ autogenerate: { directory: 'admin' } }] },
        {
          label: 'More', translations: { de: 'Mehr' },
          items: [
            { label: 'Releases and PDF manuals', translations: { de: 'Versionen und PDF-Handbücher' }, link: 'https://github.com/undone37/Kartei/releases/latest' },
            { label: 'Changelog', translations: { de: 'Änderungen' }, link: 'https://github.com/undone37/Kartei/blob/main/CHANGELOG.md' },
            { label: 'REST API', link: 'https://github.com/undone37/Kartei/blob/main/docs/API.md' },
          ],
        },
      ],
      customCss: ['./src/styles/kartei.css'],
      head: [{
        tag: 'script',
        // language: on the first visit the browser's (German if it prefers German, else English); the language switch
        // remembers an explicit choice. Static hosting has no Accept-Language, so this runs in the browser, before
        // the page is shown.
        content: `(() => {
  const KEY = 'kartei-lang', de = location.pathname.startsWith('/Kartei/de/') || location.pathname === '/Kartei/de'
  addEventListener('change', (e) => {
    if (e.target.closest?.('starlight-lang-select')) localStorage.setItem(KEY, e.target.value.includes('/Kartei/de/') ? 'de' : 'en')
  })
  let want = localStorage.getItem(KEY)
  if (!want) {
    want = navigator.languages.map((l) => l.slice(0, 2).toLowerCase()).find((l) => l === 'de' || l === 'en') || 'en'
    localStorage.setItem(KEY, want)
  }
  if (want === 'de' && !de) location.replace(location.pathname.replace(/^\\/Kartei\\/?/, '/Kartei/de/') + location.search + location.hash)
  if (want === 'en' && de) location.replace(location.pathname.replace(/^\\/Kartei\\/de\\/?/, '/Kartei/') + location.search + location.hash)
})()`,
      }, {
        tag: 'script',
        // screenshots: click (or Enter) to enlarge
        content: `addEventListener('DOMContentLoaded', () => {
  const imgs = document.querySelectorAll('.sl-markdown-content img')
  if (!imgs.length) return
  const d = document.body.appendChild(document.createElement('dialog'))
  d.className = 'kt-zoom'
  const big = d.appendChild(document.createElement('img'))
  d.addEventListener('click', () => d.close())
  for (const img of imgs) {
    const show = () => { big.src = img.currentSrc || img.src; big.alt = img.alt; d.showModal() }
    img.tabIndex = 0
    img.addEventListener('click', show)
    img.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); show() } })
  }
})`,
      }],
      lastUpdated: false,
      pagination: true,
    }),
  ],
})
