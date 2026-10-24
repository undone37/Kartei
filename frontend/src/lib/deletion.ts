/** Moving companies to the recycle bin can take their persons along. Pure (no store) so node:test can run it.
 *  Returns the persons that would go along: those of the companies among `uids` that aren't in `uids` themselves. */
export function personsAlong(uids: Iterable<string>, personsOf: (uid: string) => string[] | undefined): string[] {
  const sel = new Set(uids)
  const out = new Set<string>()
  for (const uid of sel) for (const p of personsOf(uid) ?? []) if (!sel.has(p)) out.add(p)
  return [...out]
}
