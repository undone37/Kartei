import { del as idbDel, get as idbGet, set as idbSet } from 'idb-keyval'
import { ApiError, del, get, onUnauthorized, patch, post } from './api'
import { setLang, t } from './i18n.svelte'
import { clearDrafts } from './drafts'
import { disablePush, startPush } from './push'
import { buildIndex, displayName, type Indexed, type ListSort, type NameOrder } from './search'
import { RANK, type Field, type Kind, type Section, type Lang, type ListState, type Proposal, type Rec, type Review,
         type PushKind, type SavedFilter, type User } from './types'

// bumped when records gain a property the delta sync wouldn't backfill (2: created_at)
const CACHE_KEY = 'kartei:boot2'
const POLL_MS = 30_000
const OFFLINE_MAX_MS = 24 * 3600_000 // cache shown without the server only this long after the last sync

interface Snapshot {
  username: string
  /** when it was written (ms): offline, only a recent cache is shown */
  savedAt?: number
  cursor: string
  user: User
  defaultLang: Lang
  mapUrl?: string
  printLogo?: string
  fields: Field[]
  sections?: Section[]
  records: Rec[]
  reviews?: Review[]
  proposals?: Proposal[]
  recent?: string[]
  favorites?: string[]
  filters?: SavedFilter[]
}

class Store {
  status = $state<'loading' | 'login' | 'totp' | 'ready'>('loading')
  user = $state.raw<User | null>(null)
  /** running version and source code (user menu), from the session */
  about = $state.raw<{ version: string; source: string } | null>(null)
  defaultLang = $state<Lang>('de')
  /** address link template from the settings ({address}); '' = no link */
  mapUrl = $state('')
  /** logo on the phone list: "kartei", "none", or the version of the organisation's own (/api/print-logo?v=…) */
  printLogo = $state('kartei')
  /** "Sign in with Microsoft" is offered (from the session) */
  sso = $state(false)
  ssoLabel = $state('') // login button text set by the admin; '' = default
  fields = $state.raw<Field[]>([])
  /** field sections in their order */
  sections = $state.raw<Section[]>([])
  records = $state.raw<Rec[]>([])
  reviews = $state.raw<Review[]>([])
  proposals = $state.raw<Proposal[]>([])
  /** dashboard: record uids, newest first; saved filters (own + shared) */
  recent = $state.raw<string[]>([])
  favorites = $state.raw<string[]>([])
  filters = $state.raw<SavedFilter[]>([])
  /** active users a saved filter can be shared with (maintainers and admins only) */
  shareUsers = $state.raw<{ username: string; name: string }[]>([])
  syncing = $state(false)
  offline = $state(false)
  cursor = ''

  byUid = $derived(new Map(this.records.map((r) => [r.uid, r])))
  index: Indexed[] = $derived(buildIndex(this.records, this.fields, this.byUid, this.user?.list_sort))
  rank = $derived(this.user ? RANK[this.user.role] : -1)
  canEdit = $derived(this.rank >= 1)
  isAdmin = $derived(this.rank >= 2)
  /** who points at a person through a contact field (e.g. "reports to"): person uid → [{record, field}] */
  refs = $derived.by(() => {
    const keys = this.fields.filter((f) => f.type === 'contact' && !f.archived)
    const m = new Map<string, { rec: Rec; field: Field }[]>()
    if (!keys.length) return m
    for (const { rec } of this.index) {
      for (const f of keys) {
        const v = rec.data[f.key]
        if (typeof v === 'string' && v !== rec.uid && this.byUid.has(v)) m.set(v, [...(m.get(v) ?? []), { rec, field: f }])
      }
    }
    return m
  })
  /** persons per company uid */
  persons = $derived.by(() => {
    const m = new Map<string, Rec[]>()
    for (const { rec } of this.index) if (rec.company) m.set(rec.company, [...(m.get(rec.company) ?? []), rec])
    return m
  })

  reviewFor(uid: string) {
    return this.reviews.find((r) => r.record === uid)
  }

  /** proposed new contacts: they have no record yet */
  newProposals = $derived(this.proposals.filter((p) => p.kind === 'create'))

  proposalsFor(uid: string) {
    return this.proposals.filter((p) => p.record === uid)
  }

  /** username -> full name, from the user list the API puts into user fields */
  userNames = $derived.by(() => {
    const m = new Map<string, string>()
    for (const f of this.fields)
      if (f.type === 'user' || f.type === 'users') for (const o of f.options) m.set(o.value, o.de.replace(/ \(inaktiv\)$/, ''))
    return m
  })

  userName(username: string) {
    return username ? this.userNames.get(username) ?? username : ''
  }

  fieldsFor(kind: Kind) {
    return this.fields.filter((f) => !f.archived && (f.applies_to === kind || f.applies_to === 'both'))
  }

  companyName(r: Rec) {
    return r.company ? this.byUid.get(r.company)?.name ?? '' : ''
  }

  name(r: Rec) {
    return displayName(r, this.user?.name_order)
  }

  // ------------------------------------------------------------- lifecycle

  async start() {
    onUnauthorized(() => this.toLogin())
    // polling and resync on focus/online for the whole page life, whichever way the user signs in (sync() does
    // nothing while nobody is signed in)
    setInterval(() => this.sync(), POLL_MS)
    addEventListener('focus', () => this.sync())
    addEventListener('online', () => this.sync())
    // 1) check the session, 2) show the cache if it belongs to that user, 3) fetch deltas
    const cached = (await idbGet(CACHE_KEY).catch(() => undefined)) as Snapshot | undefined
    let session: { authenticated: boolean; default_language: Lang; sso?: boolean; sso_label?: string; user?: User; version?: string; source?: string }
    try {
      session = await get('/api/session')
    } catch {
      // server unreachable: only a recent cache is shown (a shared PC must not show the last user's contacts for ever)
      const fresh = cached && Date.now() - (cached.savedAt ?? 0) < OFFLINE_MAX_MS
      this.offline = true
      if (fresh) this.apply(cached)
      this.status = fresh ? 'ready' : 'login'
      return
    }
    this.defaultLang = session.default_language
    this.sso = !!session.sso
    this.ssoLabel = session.sso_label ?? ''
    if (!session.authenticated) return this.toLogin(session.default_language)
    if (cached && cached.username === session.user!.username) {
      this.apply(cached)
      this.status = 'ready' // render from the cache now, deltas follow
    }
    this.user = session.user!
    this.about = { version: session.version ?? '', source: session.source ?? '' }
    this.applyLang()
    if (this.user.totp_due) return void (this.status = 'totp')
    await this.sync()
    this.status = 'ready'
    startPush()
  }

  private apply(s: Snapshot) {
    this.cursor = s.cursor
    this.user = s.user
    this.defaultLang = s.defaultLang
    this.mapUrl = s.mapUrl ?? ''
    this.printLogo = s.printLogo ?? 'kartei'
    this.fields = s.fields
    this.sections = s.sections ?? []
    this.records = s.records
    this.reviews = s.reviews ?? []
    this.proposals = s.proposals ?? []
    this.prefs(s)
    this.applyLang()
  }

  applyLang() {
    setLang((this.user?.language || this.defaultLang) as Lang)
  }

  /** bumped on sign-out: a sync still in flight from before must not bring the data back (or into the cache) */
  private epoch = 0

  private toLogin(defaultLang?: Lang) {
    this.epoch++
    clearTimeout(this.persistTimer)
    if (defaultLang) this.defaultLang = defaultLang
    this.user = null
    this.records = []
    this.fields = []
    this.sections = []
    this.reviews = []
    this.proposals = []
    this.prefs({})
    this.cursor = ''
    idbDel(CACHE_KEY).catch(() => {})
    // nobody is signed in yet: the browser's language if we have it, else the admin's default
    const browser = navigator.languages.map((l) => l.slice(0, 2)).find((l) => l === 'de' || l === 'en') as Lang | undefined
    setLang(browser ?? this.defaultLang)
    this.status = 'login'
  }

  /** code: the two-factor code, asked for after the server answered "totp_required" */
  async login(username: string, password: string, code?: string) {
    const { user } = await post<{ user: User }>('/api/login', { username, password, ...(code ? { code } : {}) })
    this.user = user
    this.applyLang()
    if (user.totp_due) return void (this.status = 'totp')
    await this.sync()
    this.status = 'ready'
    startPush()
  }

  /** list order / name display / notification kinds: applied at once, then saved with the user (on every device the same) */
  async setListPrefs(prefs: { list_sort?: ListSort; name_order?: NameOrder; push_off?: PushKind[] }) {
    if (!this.user) return
    const before = this.user
    this.user = { ...this.user, ...prefs }
    try {
      this.user = (await patch<{ user: User }>('/api/me', prefs)).user
      this.persist()
    } catch (e) {
      this.user = before
      throw e
    }
  }

  async logout() {
    await disablePush().catch(() => {}) // signed out on purpose: this device gets nothing more for this user
    await post('/api/logout').catch(() => {})
    clearDrafts() // signing out on purpose: no unsaved input stays in the tab (an expired session keeps it)
    this.toLogin()
  }

  // ------------------------------------------------------------- sync

  private syncPromise: Promise<void> | null = null

  sync(): Promise<void> {
    return (this.syncPromise ??= this.doSync().finally(() => (this.syncPromise = null)))
  }

  private async doSync() {
    if (!this.user) return
    const epoch = this.epoch
    this.syncing = true
    try {
      if (this.cursor) {
        const ch = await get(`/api/changes?since=${encodeURIComponent(this.cursor)}`)
        if (epoch !== this.epoch) return // signed out meanwhile
        if (!ch.reset) {
          this.merge(ch.records, ch.deleted)
          // unchanged fields/sections keep their identity: every index over all records is derived from them
          if (JSON.stringify(ch.fields) !== JSON.stringify(this.fields)) this.fields = ch.fields
          if (JSON.stringify(ch.sections ?? []) !== JSON.stringify(this.sections)) this.sections = ch.sections ?? []
          this.reviews = ch.reviews
          this.proposals = ch.proposals
          this.prefs(ch)
          this.user = ch.user
          this.defaultLang = ch.default_language
          this.mapUrl = ch.map_url ?? ''
          this.printLogo = ch.print_logo ?? 'kartei'
          this.cursor = ch.cursor
          this.applyLang()
          this.offline = false
          this.persist()
          return
        }
      }
      const b = await get('/api/bootstrap')
      if (epoch !== this.epoch) return
      this.cursor = b.cursor
      this.user = b.user
      this.defaultLang = b.default_language
      this.mapUrl = b.map_url ?? ''
      this.printLogo = b.print_logo ?? 'kartei'
      this.fields = b.fields
      this.sections = b.sections ?? []
      this.records = b.records
      this.reviews = b.reviews
      this.proposals = b.proposals
      this.prefs(b)
      this.applyLang()
      this.offline = false
      this.persist()
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) this.offline = true
      else if (!(e instanceof ApiError && e.status === 401)) console.error(e)
    } finally {
      this.syncing = false
    }
  }

  private merge(changed: Rec[], deleted: string[]) {
    if (!changed.length && !deleted.length) return
    const m = new Map(this.byUid)
    for (const r of changed) {
      const cur = m.get(r.uid)
      if (!cur || r.version >= cur.version) m.set(r.uid, r)
    }
    for (const uid of deleted) m.delete(uid)
    this.records = [...m.values()]
  }

  private persistTimer = 0
  persist() {
    clearTimeout(this.persistTimer)
    this.persistTimer = setTimeout(() => {
      if (!this.user) return
      const snap: Snapshot = {
        username: this.user.username, savedAt: Date.now(), cursor: this.cursor, user: $state.snapshot(this.user) as User,
        defaultLang: this.defaultLang, mapUrl: this.mapUrl, printLogo: this.printLogo, fields: this.fields, sections: this.sections, records: this.records,
        reviews: this.reviews, proposals: this.proposals,
        recent: this.recent, favorites: this.favorites, filters: this.filters,
      }
      idbSet(CACHE_KEY, snap).catch(() => {})
    }, 300)
  }

  // ------------------------------------------------------------- local mutations

  upsert(r: Rec) {
    this.merge([r], [])
    this.persist()
  }

  remove(uid: string) {
    this.merge([], [uid])
    this.persist()
  }

  upsertAll(changed: Rec[], deleted: string[] = []) {
    this.merge(changed, deleted)
    this.persist()
  }

  // ------------------------------------------------------------- dashboard: recent, favorites, saved filters

  private prefs(s: { recent?: string[]; favorites?: string[]; filters?: SavedFilter[]; share_users?: { username: string; name: string }[] }) {
    this.recent = s.recent ?? []
    this.favorites = s.favorites ?? []
    this.filters = s.filters ?? []
    if (s.share_users) this.shareUsers = s.share_users
  }

  /** choices for sharing a saved filter: everyone, a role, or single users */
  shareOptions() {
    return [{ value: 'all', label: t('saved.share_all') },
      ...(['read', 'maintainer', 'admin'] as const).map((r) => ({ value: `role:${r}`, label: t('saved.share_role', { role: t(`role.${r}`) }) })),
      ...this.shareUsers.map((u) => ({ value: `user:${u.username}`, label: u.name, hint: u.username }))]
  }

  private viewTimer = 0
  /** a record was opened; posted after a pause so browsing with the arrow keys only records where you stop */
  viewed(uid: string) {
    clearTimeout(this.viewTimer)
    this.viewTimer = setTimeout(() => {
      if (this.recent[0] === uid) return
      this.recent = [uid, ...this.recent.filter((u) => u !== uid)].slice(0, 20)
      this.persist()
      post('/api/me/viewed', { uid }).catch(() => {}) // fire and forget
    }, 1500)
  }

  async toggleFavorite(uid: string) {
    const on = !this.favorites.includes(uid)
    const before = this.favorites
    this.favorites = on ? [uid, ...before] : before.filter((u) => u !== uid)
    try {
      this.favorites = (await post<{ favorites: string[] }>('/api/me/favorite', { uid, on })).favorites
      this.persist()
    } catch (e) {
      this.favorites = before
      throw e
    }
  }

  async saveFilter(name: string, state: ListState, share: string[]) {
    const f = await post<SavedFilter>('/api/filters', { name, state, share })
    this.filters = [...this.filters, f].sort((a, b) => a.name.localeCompare(b.name))
    this.persist()
  }

  async renameFilter(id: number, name: string) {
    const f = await patch<SavedFilter>(`/api/filters/${id}`, { name })
    this.filters = this.filters.map((x) => (x.id === id ? f : x))
    this.persist()
  }

  async publishFilter(id: number, flags: { outlook_folder?: boolean; carddav_book?: boolean }) {
    const f = await patch<SavedFilter>(`/api/filters/${id}`, flags)
    this.filters = this.filters.map((x) => (x.id === id ? f : x))
    this.persist()
  }

  async shareFilter(id: number, share: string[]) {
    const f = await patch<SavedFilter>(`/api/filters/${id}`, { share })
    this.filters = this.filters.map((x) => (x.id === id ? f : x))
    this.persist()
  }

  async deleteFilter(id: number) {
    await del(`/api/filters/${id}`)
    this.filters = this.filters.filter((x) => x.id !== id)
    this.persist()
  }

  setFields(fields: Field[]) {
    this.fields = fields.filter((f) => !f.archived)
  }
}

export const store = new Store()
