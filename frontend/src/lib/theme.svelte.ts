// Light/dark choice per device ('' = follow the system). index.html applies it before the first paint.
export type Theme = '' | 'light' | 'dark'
const KEY = 'kartei:theme'

export const theme = $state({ value: (localStorage.getItem(KEY) ?? '') as Theme })

export function setTheme(value: Theme) {
  theme.value = value
  if (value) localStorage.setItem(KEY, value)
  else localStorage.removeItem(KEY)
  applyTheme()
}

/** html[data-theme] drives CSS light-dark(); the meta tag colors the browser/PWA title bar */
export function applyTheme() {
  const v = theme.value
  if (v) document.documentElement.dataset.theme = v
  else delete document.documentElement.dataset.theme
  const dark = v === 'dark' || (!v && matchMedia('(prefers-color-scheme: dark)').matches)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#17171b' : '#ffffff')
}

matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => theme.value || applyTheme())
