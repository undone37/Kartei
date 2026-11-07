// Unsaved form input, kept per browser tab (sessionStorage) so an expired session doesn't lose it.
const PREFIX = 'kartei:draft:'
const MAX_AGE_MS = 24 * 3600_000

export const draftKeyFor = (mode: string, uid: string | null, kind: string) => `${PREFIX}${mode}:${uid ?? `new-${kind}`}`

export interface Draft { user?: string; at: number; baseVersion: number; comment: string; draft: any }

/** the kept input for this form, if it belongs to this user and is recent */
export function readDraft(key: string, user?: string): Draft | null {
  try {
    const d = JSON.parse(sessionStorage.getItem(key) ?? 'null') as Draft | null
    return d && d.user === user && Date.now() - d.at < MAX_AGE_MS ? d : null
  } catch {
    return null
  }
}

/** an edit of this contact is waiting to be finished (RecordView reopens the form) */
export const hasEditDraft = (uid: string, user?: string) => !!readDraft(draftKeyFor('edit', uid, ''), user)

/** signing out on purpose: nothing of it stays in the tab */
export function clearDrafts() {
  for (const k of Object.keys(sessionStorage)) if (k.startsWith(PREFIX)) sessionStorage.removeItem(k)
}
