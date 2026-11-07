import { t } from './i18n.svelte'

export interface Toast {
  id: number
  text: string
  kind: 'info' | 'error'
  action?: { label: string; run: () => void }
}

export const toasts = $state<Toast[]>([])
let next = 1

export function toast(text: string, opts: { kind?: Toast['kind']; action?: Toast['action']; ms?: number } = {}) {
  const t: Toast = { id: next++, text, kind: opts.kind ?? 'info', action: opts.action }
  toasts.push(t)
  setTimeout(() => dismiss(t.id), opts.ms ?? (opts.action ? 8000 : 4000))
}

export function dismiss(id: number) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

/** Copy to the clipboard with feedback either way (it fails e.g. without HTTPS or when the browser refuses). */
export function copyText(text: string) {
  return navigator.clipboard.writeText(text).then(() => toast(t('view.copied')), () => toast(t('view.copy_failed'), { kind: 'error' }))
}
