// One confirmation dialog for the whole app (ConfirmDialog.svelte, mounted once in App.svelte).
// `if (!(await confirmDialog({ … }))) return` — null when cancelled, otherwise the state of the optional checkbox.

export interface ConfirmOptions {
  title: string
  message: string
  confirmLabel: string
  /** red confirm button, for deleting */
  danger?: boolean
  /** an extra choice, e.g. "also move its persons to the recycle bin" */
  checkbox?: { label: string; checked?: boolean }
}

export interface Confirmed {
  checked: boolean
}

interface Pending {
  opts: ConfirmOptions
  resolve: (r: Confirmed | null) => void
}

export const confirmState = $state<{ current: Pending | null }>({ current: null })

export function confirmDialog(opts: ConfirmOptions): Promise<Confirmed | null> {
  confirmState.current?.resolve(null) // only one at a time; an older question counts as cancelled
  return new Promise((resolve) => {
    confirmState.current = { opts, resolve }
  })
}

/** called by the dialog when it closes */
export function settle(result: Confirmed | null) {
  const p = confirmState.current
  confirmState.current = null
  p?.resolve(result)
}
