/** Toggle `uid` in a selection. With `shift`, the rows from `anchor` (the last clicked) to `uid` all take the
 *  clicked row's new state, like in a file manager. `order`: uids as listed. */
export function pick(sel: Set<string>, order: string[], uid: string, anchor: string | null, shift: boolean) {
  const out = new Set(sel)
  const on = !sel.has(uid)
  const b = order.indexOf(uid)
  const a = shift && anchor ? order.indexOf(anchor) : -1
  const [from, to] = a < 0 || b < 0 ? [b, b] : [Math.min(a, b), Math.max(a, b)]
  for (const u of b < 0 ? [uid] : order.slice(from, to + 1)) {
    if (on) out.add(u)
    else out.delete(u)
  }
  return out
}
