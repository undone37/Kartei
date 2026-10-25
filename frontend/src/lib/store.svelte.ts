import { del as idbDel, get as idbGet, set as idbSet } from 'idb-keyval'
import { ApiError, del, get, onUnauthorized, patch, post } from './api'
import { setLang } from './i18n.svelte'
import { buildIndex, displayName, type Indexed } from './search'
import { RANK, type Field, type Kind, type Section, type Lang, type ListState, type Proposal, type Rec, type Review,
         type SavedFilter, type User } from './types'

// bumped when records gain a property the delta sync wouldn't backfill (2: created_at)
const CACHE_KEY = 'kartei:boot2'
const POLL_MS = 30_000

interface Snapshot {
  username: string
  cursor: string
  user: User
  defaultLang: Lang
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
  syncing = $state(false)
  offline = $state(false)
  cursor = ''

  byUid = $derived(new Map(this.records.map((r) => [r.uid, r])))
  index: Indexed[] = $derived(buildIndex(this.records, this.fields, this.byUid))
  rank = $derived(this.user ? RANK[this.user.role] : -1)
  canEdit = $derived(this.rank >= 1)
  isAdmin = $derived(this.rank >= 2)
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
    return displayName(r)
  }

  // ------------------------------------------------------------- lifecycle

  async start() {
    onUnauthorized(() => this.toLogin())
    idbDel('kartei:boot').catch(() => {}) // ponytail: drop the pre-2 cache; remove after a release or two
    // 1) render from cache immediately, 2) check session, 3) fetch deltas
    const cached = (await idbGet(CACHE_KEY).catch(() => undefined)) as Snapshot | undefined
    if (cached) this.apply(cached)
    let session: { authenticated: boolean; default_language: Lang; sso?: boolean; sso_label?: string; user?: User; version?: string; source?: string }
    try {
      session = await get('/api/session')
    } catch {
      this.offline = true
      this.status = cached ? 'ready' : 'login'
      return
    }
    this.defaultLang = session.default_language
    this.sso = !!session.sso
    this.ssoLabel = session.sso_label ?? ''
    if (!session.authenticated) return this.toLogin(session.default_language)
    if (cached && cached.username !== session.user!.username) {
      this.records = []
      this.cursor = ''
    }
    this.user = session.user!
    this.about = { version: session.version ?? '', source: session.source ?? '' }
    this.applyLang()
    if (this.user.totp_due) return void (this.status = 'totp')
    await this.sync()
    this.status = 'ready'
    setInterval(() => this.sync(), POLL_MS)
    addEventListener('focus', () => this.sync())
    addEventListener('online', () => this.sync())
  }

  private apply(s: Snapshot) {
    this.cursor = s.cursor
    this.user = s.user
    this.defaultLang = s.defaultLang
    this.fields = s.fields
    this.sections = s.sections ?? []
    this.records = s.records
    this.reviews = s.reviews ?? []
    this.proposals = s.proposals ?? []
    this.prefs(s)
    this.applyLang()
    this.status = 'ready'
  }

  applyLang() {
    setLang((this.user?.language || this.defaultLang) as Lang)
  }

  private toLogin(defaultLang?: Lang) {
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
  }

  async logout() {
    await post('/api/logout').catch(() => {})
    this.toLogin()
  }

  // ------------------------------------------------------------- sync

  private syncPromise: Promise<void> | null = null

  sync(): Promise<void> {
    return (this.syncPromise ??= this.doSync().finally(() => (this.syncPromise = null)))
  }

  private async doSync() {
    if (!this.user) return
    this.syncing = true
    try {
      if (this.cursor) {
        const ch = await get(`/api/changes?since=${encodeURIComponent(this.cursor)}`)
        if (!ch.reset) {
          this.merge(ch.records, ch.deleted)
          this.fields = ch.fields
          this.sections = ch.sections ?? []
          this.reviews = ch.reviews
          this.proposals = ch.proposals
          this.prefs(ch)
          this.user = ch.user
          this.defaultLang = ch.default_language
          this.cursor = ch.cursor
          this.applyLang()
          this.offline = false
          this.persist()
          return
        }
      }
      const b = await get('/api/bootstrap')
      this.cursor = b.cursor
      this.user = b.user
      this.defaultLang = b.default_language
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
        username: this.user.username, cursor: this.cursor, user: $state.snapshot(this.user) as User,
        defaultLang: this.defaultLang, fields: this.fields, sections: this.sections, records: this.records,
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

  private prefs(s: { recent?: string[]; favorites?: string[]; filters?: SavedFilter[] }) {
    this.recent = s.recent ?? []
    this.favorites = s.favorites ?? []
    this.filters = s.filters ?? []
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

  async saveFilter(name: string, state: ListState, shared: boolean) {
    const f = await post<SavedFilter>('/api/filters', { name, state, shared })
    this.filters = [...this.filters, f].sort((a, b) => a.name.localeCompare(b.name))
    this.persist()
  }

  async renameFilter(id: number, name: string) {
    const f = await patch<SavedFilter>(`/api/filters/${id}`, { name })
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
