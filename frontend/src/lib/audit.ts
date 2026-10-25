// Human-readable audit entries: translated labels for changed keys and formatted values (no raw ids or JSON).
import { store } from './store.svelte'
import { fmt } from './format'
import { L, t } from './i18n.svelte'
import type { AuditEntry, Field } from './types'

const has = (key: string) => t(key) !== key
const yesNo = (v: unknown) => (v ? t('common.yes') : t('common.no'))
const role = (v: string) => (has(`role.${v}`) ? t(`role.${v}`) : v)

/** internal ids mean nothing to readers */
export const visibleChanges = (e: AuditEntry) => Object.entries(e.changes).filter(([k]) => k !== 'id')

/** keys written by workflows (reviews, proposals, batch changes), any target type */
const SPECIAL = ['proposed_by', 'note', 'comment', 'delete', 'reviewed', 'batch_from', 'started', 'adjusted', 'kind', 'reason',
  'bulk', 'normalized', 'merged_from', 'merged_into', 'not_duplicate', 'with_company']

/** labels of settings/user/export/field attributes, reusing the labels of their forms */
const ATTR: Record<string, Record<string, string>> = {
  field: {
    label: 'fields.label', help: 'fields.help', section: 'fields.section', type: 'fields.type', applies_to: 'fields.applies_to',
    options: 'fields.options', open_options: 'fields.open_options', quick_filter: 'fields.quick_filter', required: 'fields.required', min_value: 'fields.min',
    max_value: 'fields.max', decimals: 'fields.decimals', visible_to: 'fields.visible_to', editable_by: 'fields.editable_by',
    searchable: 'fields.searchable', regex: 'fields.regex', vcard: 'fields.vcard', vcard_label: 'fields.vcard_label', import_aliases: 'fields.import_aliases',
    copy_from: 'fields.copy_from', archived: 'audit.attr.archived', order: 'audit.attr.order', key: 'audit.attr.key',
  },
  user: {
    username: 'login.username', password: 'login.password', role: 'users.role', is_active: 'users.active',
    language: 'account.language', first_name: 'core.first_name', last_name: 'core.last_name', email: 'audit.attr.email',
    source: 'users.source', is_superuser: 'audit.attr.is_superuser',
  },
  settings: {
    default_language: 'general.default_language', base_url: 'general.base_url', trash_days: 'general.trash_days',
    export_interval_minutes: 'general.export_interval', ldap_uri: 'ldap.uri', ldap_bind_dn: 'ldap.bind_dn',
    ldap_bind_password_enc: 'ldap.bind_pw', ldap_user_base: 'ldap.user_base', ldap_user_filter: 'ldap.user_filter',
    ldap_ca_cert: 'ldap.ca', ldap_start_tls: 'audit.attr.start_tls', carddav_enabled: 'carddav.enabled',
    carddav_username: 'audit.attr.carddav_username', carddav_password_hash: 'audit.attr.carddav_password',
    carddav_relay_enabled: 'carddav.relay_enabled', carddav_relay_url: 'carddav.relay_url',
    carddav_relay_token: 'carddav.relay_token', carddav_relay_token_enc: 'carddav.relay_token',
    carddav_relay_tls_verify: 'carddav.relay_tls_verify', carddav_relay_ca_cert: 'carddav.relay_ca',
    carddav_relay_max_delete_percent: 'ad.guard',
    graph_enabled: 'graph.enabled', graph_tenant_id: 'graph.tenant', graph_client_id: 'graph.client',
    graph_client_secret_enc: 'graph.secret', graph_group_id: 'graph.group', graph_folder: 'graph.folder',
    review_mode: 'audit.attr.review_mode', review_interval_months: 'review.interval',
    review_campaign_month: 'review.month', review_campaign_day: 'review.day', smtp_host: 'mail.host',
    smtp_port: 'mail.port', smtp_security: 'mail.security', smtp_username: 'mail.username',
    smtp_password_enc: 'mail.password', smtp_from: 'mail.from', review_remind_days: 'review.remind_days',
    proposal_notify: 'review.proposal_notify', proposal_notify_to: 'review.proposal_to',
    ad_enabled: 'ad.enabled', ad_ou: 'ad.ou', ad_bind_dn: 'ad.bind_dn', ad_bind_password_enc: 'ad.bind_pw',
    ad_kinds: 'exports.kinds', ad_columns: 'ad.mapping', ad_max_shrink_percent: 'ad.guard',
    phone_normalize: 'phone.normalize', phone_country_code: 'phone.country_code',
    mail_templates: 'audit.attr.mail_templates', mail_transport: 'audit.attr.mail_transport', mail_graph_sender: 'audit.attr.mail_graph_sender',
  },
  section: { label: 'fields.label', key: 'audit.attr.key', order: 'audit.attr.order' },
  token: { name: 'tokens.name', scope: 'tokens.scope' },
  export: {
    name: 'exports.name', enabled: 'exports.enabled', format: 'exports.format', path: 'exports.path',
    schedule: 'exports.schedule', kinds: 'exports.kinds', filter_field: 'exports.filter_field',
    filter_values: 'exports.filter_values', columns: 'exports.columns', options: 'exports.format_options',
    max_shrink_percent: 'exports.guard', rows: 'dl.rows',
  },
}

/** fields: all field definitions (admins pass the full list incl. archived ones), used for record keys and ids */
export function auditLabel(e: Pick<AuditEntry, 'target_type'>, key: string, fields: Field[] = store.fields): string {
  if (SPECIAL.includes(key)) return t(`audit.attr.${key}`)
  if (e.target_type === 'record' || e.target_type === 'proposal') { // a proposed new contact holds record values
    const f = fields.find((f) => f.key === key)
    if (f) return L(f.label)
    return has(`core.${key}`) ? t(`core.${key}`) : key
  }
  if (e.target_type === 'settings') {
    const g = key.match(/^ldap_group_(\w+)$/)
    if (g) return `${t('ldap.groups')}: ${role(g[1])}`
  }
  // label_de / help_en / section_de … → "Bezeichnung (DE)"
  const lang = key.match(/^(\w+)_(de|en)$/)
  const base = lang ? lang[1] : key
  const k = ATTR[e.target_type]?.[base]
  return k ? t(k) + (lang ? ` (${lang[2].toUpperCase()})` : '') : key
}

export function auditValue(e: Pick<AuditEntry, 'target_type'>, key: string, v: any, fields: Field[] = store.fields): string {
  if (v == null || v === '' || (Array.isArray(v) && !v.length)) return '—'
  if (v === '***') return '••••'
  const fieldName = (id: any) => { const f = fields.find((f) => f.id === Number(id)); return f ? L(f.label) : `#${id}` }
  if (key === 'started' && typeof v === 'object')
    return t('review.started', { n: v.created ?? 0, open: v.already_open ?? 0, missing: v.no_responsible ?? 0 })
  if (key === 'reviewed') return v === 'confirmed' ? t('review.confirmed') : String(v)
  if (key === 'delete' || key === 'adjusted' || key === 'bulk') return yesNo(v)
  if (key === 'normalized') return typeof v === 'number' ? t('phone.done', { n: v }) : yesNo(v)
  if (key === 'reason') return t(`proposal.reason_${v}`)
  if (key === 'kind') return v === 'person' || v === 'company' ? t(`kind.${v}`) : v === 'delete' ? t('proposal.title_delete')
    : v === 'create' ? t('proposal.title_new') : t('proposal.title_change')
  if (e.target_type === 'record' || e.target_type === 'proposal') {
    const f = fields.find((f) => f.key === key)
    if (f) return fmt(f, v) || '—'
  }
  if (e.target_type === 'field') {
    if (key === 'type') return t(`type.${v}`)
    if (key === 'applies_to') return t(`applies.${v}`)
    if (key === 'visible_to' || key === 'editable_by') return role(v)
    if (key === 'copy_from') return fieldName(v)
    if (key === 'section') { const s = store.sections.find((s) => s.id === Number(v)); return s ? L(s.label) : `#${v}` }
    if (key === 'vcard') return has(`vcard.${v}`) ? t(`vcard.${v}`) : v
    if (key === 'options' && Array.isArray(v)) return v.map((o) => o?.de || o?.value || o).join(', ')
  }
  if (e.target_type === 'user') {
    if (key === 'role') return role(v)
    if (key === 'language') return v === 'en' ? 'English' : v === 'de' ? 'Deutsch' : t('account.lang_default')
  }
  if (e.target_type === 'settings') {
    if (key === 'review_mode') return t(`review.mode_${v}`)
    if (key === 'default_language') return v === 'en' ? 'English' : 'Deutsch'
    if (key === 'ad_kinds') return t(`applies.${v}`)
    if (key === 'ad_columns' && Array.isArray(v)) return t('audit.val.columns', { n: v.length })
  }
  if (e.target_type === 'token' && key === 'scope') return t(`tokens.scope_${v}`)
  if (e.target_type === 'export') {
    if (key === 'kinds') return t(`applies.${v}`)
    if (key === 'schedule') return has(`exports.${v}`) ? t(`exports.${v}`) : v
    if (key === 'filter_field') return fieldName(v)
    if (key === 'columns' && Array.isArray(v)) return t('audit.val.columns', { n: v.length })
  }
  if (typeof v === 'boolean') return yesNo(v)
  if (Array.isArray(v)) return v.map((x) => (typeof x === 'object' ? JSON.stringify(x) : String(x))).join(', ')
  if (typeof v === 'object') return t('audit.val.changed') // e.g. export format options: details in the export itself
  return String(v)
}

/** the object column: name and type of what was changed */
export function auditObject(e: AuditEntry, fields: Field[] = store.fields): { name: string; type: string; href?: string } {
  if (e.target_type === 'record') {
    const kind = e.kind ?? 'person'
    return { name: e.target_label || '—', type: t(`kind.${kind}`), href: e.action === 'purge' || !e.kind ? undefined : `/${kind}/${e.target_id}` }
  }
  if (e.target_type === 'field') {
    const f = fields.find((f) => String(f.id) === e.target_id)
    return { name: f ? L(f.label) : e.target_label, type: t('audit.type.field') }
  }
  if (e.target_type === 'proposal') return { name: e.target_label, type: t('audit.type.proposal'), href: `/proposal/${e.target_id}` }
  if (e.target_type === 'settings') {
    const name = has(`audit.label.${e.target_label}`) ? t(`audit.label.${e.target_label}`) : e.target_label
    return { name, type: t('audit.type.settings') }
  }
  return { name: e.target_label, type: t(`audit.type.${e.target_type}`) }
}
