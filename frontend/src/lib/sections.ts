// Field sections: grouping for the contact view/form and the field list, and drag & drop between sections.
import type { Field, Section } from './types'

export interface Group { section: Section | null; fields: Field[] }

const byOrder = <T extends { order: number; id: number }>(a: T, b: T) => a.order - b.order || a.id - b.id

/** Fields grouped by section: sections in their order, fields in field order, "Other" (no or unknown section) last.
 *  Empty groups are dropped unless `all` (the settings list shows every section as a drop target). */
export function groupFields(fields: Field[], sections: Section[], all = false): Group[] {
  const groups: Group[] = [...sections].sort(byOrder).map((section) => ({ section, fields: [] }))
  const other: Group = { section: null, fields: [] }
  const byId = new Map(groups.map((g) => [g.section!.id, g]))
  for (const f of [...fields].sort(byOrder)) (byId.get(f.section as number) ?? other).fields.push(f)
  return [...groups, other].filter((g) => all || g.fields.length)
}

/** Move field `id` onto field `target` (or to the end of section `to` when target is null).
 *  Within a section a field dragged downwards lands after the target, otherwise before it.
 *  Returns the new flat field order and the field's new section. */
export function moveField(groups: Group[], id: number, to: number | null, target: number | null = null):
  { ids: number[]; section: number | null } {
  const lists = groups.map((g) => g.fields.map((f) => f.id))
  const from = lists.findIndex((l) => l.includes(id))
  const into = groups.findIndex((g) => (g.section?.id ?? null) === to)
  if (from < 0 || into < 0) return { ids: lists.flat(), section: to }
  const src = lists[from], dst = lists[into]
  const oldIdx = src.indexOf(id)
  src.splice(oldIdx, 1)
  let at = target == null || target === id ? dst.length : dst.indexOf(target)
  if (at < 0) at = dst.length
  else if (target != null && from === into && oldIdx <= at) at += 1 // dragged down: after the target
  dst.splice(at, 0, id)
  return { ids: lists.flat(), section: to }
}
