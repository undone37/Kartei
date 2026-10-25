import type { Group } from './advanced'
export type Role = 'read' | 'maintainer' | 'admin'
export type Lang = 'de' | 'en'
export type Kind = 'person' | 'company'
export type L10n = { de: string; en: string }
export type FieldType =
  | 'text' | 'longtext' | 'integer' | 'decimal' | 'select' | 'multiselect'
  | 'phone' | 'email' | 'url' | 'date' | 'checkbox' | 'user' | 'users' | 'contact'

/** select-like types; user fields arrive from the API with the user list as options */
export const isSingle = (f: Field) => f.type === 'select' || f.type === 'user'
export const isMulti = (f: Field) => f.type === 'multiselect' || f.type === 'users'

/** pick: false = user fields: an admin or inactive user, shown for existing values but not offered */
export interface Option { value: string; de: string; en: string; pick?: false }

export interface Field {
  id: number
  key: string
  label: L10n
  applies_to: Kind | 'both'
  type: FieldType
  options: Option[]
  open_options: boolean
  quick_filter: boolean
  required: boolean
  min: string | null
  max: string | null
  decimals: number
  /** FieldSection id; null = "Other" */
  section: number | null
  order: number
  visible_to: Role
  editable_by: Role
  searchable: boolean
  regex: string
  help: L10n
  vcard: string
  vcard_label: string
  copy_from: number | null
  archived: boolean
  import_aliases: string[]
}

/** a named group of fields; key "person" / "company" = header block of that form */
export interface Section { id: number; key: string; label: L10n; order: number }

export interface Rec {
  uid: string
  kind: Kind
  legacy_id: string
  first_name: string
  last_name: string
  name: string
  company: string | null
  image: number | null
  data: Record<string, any>
  version: number
  created_at?: string // missing in caches from before it was sent
  updated_at: string
  updated_by: string
  deleted_at: string | null
  reviewed_at: string | null
  reviewed_by: string
}

/** an open review assigned to the current user */
export interface Review { id: number; record: string; created_at: string; reason: string }

/** a pending change/deletion proposal (maintainers see all, others their own) */
export interface Proposal {
  id: number
  /** null for a proposed new contact (kind 'create') until it is accepted */
  record: string | null
  record_kind: Kind
  /** name of the contact, for a new contact the proposed name */
  label: string
  kind: 'change' | 'delete' | 'create'
  changes: { core?: Record<string, any>; data?: Record<string, any> }
  base: { core?: Record<string, any>; data?: Record<string, any> }
  comment: string
  reason: '' | 'left' | 'company_gone' | 'other'
  proposer: string
  created_at: string
  status: string
}

export interface User {
  id: number
  username: string
  first_name: string
  last_name: string
  email: string
  role: Role
  language: '' | Lang
  source: 'local' | 'ldap'
  is_active: boolean
  is_superuser: boolean
  last_login: string | null
  /** two-factor sign-in is on */
  totp?: boolean
}

export interface AuditEntry {
  id: number
  at: string
  user: string
  action: string
  target_type: string
  target_id: string
  target_label: string
  kind?: 'person' | 'company' | null
  changes: Record<string, [any, any]>
}

export const RANK: Record<Role, number> = { read: 0, maintainer: 1, admin: 2 }

/** a person update proposed after a company change (see /api/records/<uid>/propagate) */
export interface BatchItem { uid: string; name: string; key: string; old: any; new: any }

/** what the list shows: search text, sidebar scope, kind chip, field filters and the advanced filter (lib/advanced) */
export interface ListState { q: string; scope: string; kind: 'all' | Kind; filters: Record<string, string[]>; adv?: Group }

/** a named list state, own or shared by a maintainer */
export interface SavedFilter { id: number; name: string; state: ListState; shared: boolean; owner: string; mine: boolean }
