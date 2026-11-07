// Org chart of a company from a "reports to" field (a contact field with the vCard target related_manager).
import type { Field, Rec } from './types'

export interface OrgNode { rec: Rec; children: OrgNode[] }

/** the field that says who someone reports to; none = no org chart */
export const managerField = (fields: Field[]) =>
  fields.find((f) => f.type === 'contact' && f.vcard === 'related_manager' && !f.archived && f.applies_to !== 'company')

/** Trees of the company's persons. Roots: no manager, or one outside the company. A cycle (A → B → A) can't hang
 *  from anywhere: its first member becomes a root, so everybody appears exactly once. */
export function orgTree(staff: Rec[], key: string, name: (r: Rec) => string, maxDepth = 20): OrgNode[] {
  const byUid = new Map(staff.map((r) => [r.uid, r]))
  const boss = (r: Rec) => { const m = r.data[key]; return typeof m === 'string' && m !== r.uid && byUid.has(m) ? m : null }
  const under = new Map<string, Rec[]>()
  for (const r of staff) { const m = boss(r); if (m) under.set(m, [...(under.get(m) ?? []), r]) }
  const sort = (rs: Rec[]) => [...rs].sort((a, b) => name(a).localeCompare(name(b)))
  const seen = new Set<string>()
  const node = (r: Rec, depth: number): OrgNode => {
    seen.add(r.uid)
    const kids = depth < maxDepth ? sort(under.get(r.uid) ?? []).filter((c) => !seen.has(c.uid)) : []
    return { rec: r, children: kids.map((c) => node(c, depth + 1)) }
  }
  const roots = sort(staff.filter((r) => !boss(r))).map((r) => node(r, 0))
  for (const r of sort(staff)) if (!seen.has(r.uid)) roots.push(node(r, 0))  // left over: cycles, or too deep
  return roots
}

/** is there anything worth drawing: at least one person reports to someone in the same company */
export const hasOrg = (staff: Rec[], key: string) => {
  const ids = new Set(staff.map((r) => r.uid))
  return staff.some((r) => r.data[key] !== r.uid && ids.has(r.data[key]))
}
