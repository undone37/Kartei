const SERVER = /^\/(api|static|carddav|django-admin|\.well-known)(\/|$)|^\/sw\.js$/

export const route = $state({ path: location.pathname, search: location.search })

export function go(url: string, replace = false) {
  if (url === location.pathname + location.search) return
  history[replace ? 'replaceState' : 'pushState']({}, '', url)
  route.path = location.pathname
  route.search = location.search
}

addEventListener('popstate', () => {
  route.path = location.pathname
  route.search = location.search
})

/** Intercept clicks on internal <a href> so navigation never reloads the page. */
addEventListener('click', (e) => {
  const a = (e.target as HTMLElement).closest?.('a')
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || a.target || a.hasAttribute('download')) return
  const url = new URL(a.href, location.href)
  // the SPA owns every path except what the server handles itself
  if (url.origin !== location.origin || SERVER.test(url.pathname) || url.pathname.endsWith('.vcf')) return
  e.preventDefault()
  go(url.pathname + url.search)
})
