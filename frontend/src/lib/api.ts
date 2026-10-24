export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public fields: Record<string, string> = {},
    public body: any = {},
  ) {
    super(code)
  }
}

const listeners = new Set<() => void>()
/** Called when any request comes back 401 (session expired). */
export const onUnauthorized = (fn: () => void) => listeners.add(fn)

function csrf() {
  return document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] ?? ''
}

export async function api<T = any>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-CSRFToken': csrf() }
  let payload: BodyInit | undefined
  if (body instanceof Blob || body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  if (body instanceof Blob) headers['Content-Type'] = body.type
  let res: Response
  try {
    res = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'offline')
  }
  const isJson = res.headers.get('Content-Type')?.startsWith('application/json')
  const data = isJson ? await res.json() : undefined
  if (res.status === 401 && !url.endsWith('/login')) listeners.forEach((fn) => fn())
  if (!res.ok) throw new ApiError(res.status, data?.error ?? `http_${res.status}`, data?.fields ?? {}, data)
  return data as T
}

export const get = <T = any>(url: string) => api<T>('GET', url)
export const post = <T = any>(url: string, body?: unknown) => api<T>('POST', url, body ?? {})
export const patch = <T = any>(url: string, body: unknown) => api<T>('PATCH', url, body)
export const put = <T = any>(url: string, body: unknown) => api<T>('PUT', url, body)
export const del = <T = any>(url: string) => api<T>('DELETE', url)

/** POST and save the response as a file, named by its Content-Disposition. */
export async function download(url: string, body: unknown) {
  let res: Response
  try {
    res = await fetch(url, { method: 'POST', credentials: 'same-origin', body: JSON.stringify(body),
                             headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/json' } })
  } catch {
    throw new ApiError(0, 'offline')
  }
  if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).error ?? `http_${res.status}`)
  const name = res.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? 'export'
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(await res.blob()), download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

/** Save data as a pretty-printed JSON file (field files, column mappings). */
export function downloadJson(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' })
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

/** Parse an uploaded JSON file; null if it isn't JSON. */
export async function readJson(file: File): Promise<any> {
  try {
    return JSON.parse(await file.text())
  } catch {
    return null
  }
}
