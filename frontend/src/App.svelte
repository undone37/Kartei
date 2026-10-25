<script lang="ts">
  import logo from './assets/logo.svg'
  import { Bookmark, Building2, ChevronDown, Copy, Download, Filter, ListChecks, LogOut, Monitor, Moon, Sun, Plus, Printer, RefreshCw, Search, Settings, ShieldCheck, SlidersHorizontal, Trash2, User, UserRound, WifiOff, X } from '@lucide/svelte'
  import AdvancedFilter from './components/AdvancedFilter.svelte'
  import Combobox from './components/Combobox.svelte'
  import Login from './components/Login.svelte'
  import RecordForm from './components/RecordForm.svelte'
  import ProposalPage from './components/ProposalPage.svelte'
  import PhoneList from './components/PhoneList.svelte'
  import RecordList from './components/RecordList.svelte'
  import RecordView from './components/RecordView.svelte'
  import Toasts from './components/Toasts.svelte'
  import ConfirmDialog from './components/ConfirmDialog.svelte'
  import Trash from './components/Trash.svelte'
  import Account from './components/Account.svelte'
  import BulkBar from './components/BulkBar.svelte'
  import Dashboard from './components/Dashboard.svelte'
  import { ApiError, download, patch } from './lib/api'
  import { pick } from './lib/selection'
  import { toast } from './lib/toast.svelte'
  import Missing from './components/Missing.svelte'
  import { go, route } from './lib/router.svelte'
  import { store } from './lib/store.svelte'
  import { L, i18n, t, terr } from './lib/i18n.svelte'
  import { compile, count, defs, emptyGroup, type Group } from './lib/advanced'
  import { matcher } from './lib/search'
  import { setTheme, theme } from './lib/theme.svelte'
  import { isMulti, isSingle, type Kind, type ListState, type Rec } from './lib/types'

  store.start()

  let query = $state('')
  let kind = $state<'all' | Kind>('all')
  let filters = $state<Record<string, string[]>>({})
  let adv = $state<Group>(emptyGroup())
  type Scope = 'all' | 'responsible' | 'internal' | 'review' | 'proposals'
  // the review mail links to /?list=review
  let scope = $state<Scope>((new URLSearchParams(location.search).get('list') as Scope) ||
                            (localStorage.getItem('kartei:scope') as Scope) || 'all')
  $effect(() => localStorage.setItem('kartei:scope', scope))
  let searchEl: HTMLInputElement | undefined = $state()
  let editing = $state(false)

  // ------------------------------------------------------------- routing
  const parts = $derived(route.path.split('/').filter(Boolean))
  const view = $derived.by(() => {
    const [a, b] = parts
    if (a === 'person' || a === 'company') return { name: 'record' as const, uid: b }
    if (a === 'new' && (b === 'person' || b === 'company')) return { name: 'new' as const, kind: b as Kind }
    if (a === 'proposal' && b) return { name: 'proposal' as const, id: Number(b) }
    if (a === 'phonelist') return { name: 'phonelist' as const }
    if (a === 'trash') return { name: 'trash' as const }
    if (a === 'settings') return { name: 'settings' as const, tab: b ?? 'fields' }
    if (a === 'account') return { name: 'account' as const }
    if (a === 'quality') return { name: 'quality' as const }
    if (a === 'duplicates') return { name: 'duplicates' as const, a: b, b: parts[2] }
    return { name: 'list' as const }
  })
  const selected = $derived(view.name === 'record' ? view.uid : null)
  const current = $derived(selected ? store.byUid.get(selected) : undefined)
  const presetCompany = $derived(new URLSearchParams(route.search).get('company'))

  $effect(() => {
    void selected
    editing = false
  })

  // ------------------------------------------------------------- filtering
  // quick filter: the choice/user fields the admin marked "show in quick filter"
  const filterFields = $derived(store.fields.filter((f) => !f.archived && f.quick_filter && (isSingle(f) || isMulti(f))))
  const activeFilters = $derived(Object.entries(filters).filter(([, v]) => v.length))
  // advanced filter: compiled once per edit, not per record
  const advDefs = $derived(defs(store.fields))
  const advTest = $derived(compile(adv, advDefs))
  const advCount = $derived(count(adv, advDefs))

  // "my contacts": every single-user field counts as responsible, every multi-user field as internal contacts
  const userKeys = $derived({
    responsible: store.fields.filter((f) => f.type === 'user' && !f.archived).map((f) => f.key),
    internal: store.fields.filter((f) => f.type === 'users' && !f.archived).map((f) => f.key),
  })
  const reviewUids = $derived(new Set(store.reviews.map((r) => r.record)))
  const proposalUids = $derived(new Set(store.proposals.flatMap((p) => (p.record ? [p.record] : []))))
  const proposalCount = $derived(proposalUids.size + store.newProposals.length)
  const inScope = (r: Rec, s: Scope) => {
    if (s === 'all') return true
    if (s === 'review') return reviewUids.has(r.uid)
    if (s === 'proposals') return proposalUids.has(r.uid)
    const me = store.user?.username
    return userKeys[s].some((k) => (Array.isArray(r.data[k]) ? r.data[k].includes(me) : r.data[k] === me))
  }
  // review/proposal lists only appear while there is something in them
  const scopes = $derived([
    ...(['responsible', 'internal'] as const).filter((s) => userKeys[s].length),
    ...(reviewUids.size ? ['review' as const] : []),
    ...(proposalCount ? ['proposals' as const] : []), // read-only users: their own pending proposals
  ])
  const activeScope = $derived<Scope>(scope !== 'all' && scopes.includes(scope) ? scope : 'all')
  const scopeCounts = $derived({
    responsible: store.records.filter((r) => inScope(r, 'responsible')).length,
    internal: store.records.filter((r) => inScope(r, 'internal')).length,
    review: reviewUids.size,
    proposals: proposalCount,
  })

  const results = $derived.by(() => {
    const match = matcher(query)
    const fs = activeFilters
    const sc = activeScope
    const at = advTest
    return store.index.filter((x) => {
      if (kind !== 'all' && x.rec.kind !== kind) return false
      if (!inScope(x.rec, sc)) return false
      if (at && !at(x.rec)) return false
      for (const [key, vals] of fs) {
        const v = x.rec.data[key]
        if (!(Array.isArray(v) ? v : [v]).some((y) => vals.includes(y))) return false
      }
      return match(x)
    })
  })
  const counts = $derived.by(() => {
    const rs = store.records.filter((r) => inScope(r, activeScope))
    return { person: rs.filter((r) => r.kind === 'person').length, company: rs.filter((r) => r.kind === 'company').length }
  })

  // ------------------------------------------------------------- keyboard
  function open(r: Rec, replace = false) {
    go(`/${r.kind}/${r.uid}`, replace)
  }

  function step(delta: number) {
    if (!results.length) return
    const i = results.findIndex((x) => x.rec.uid === selected)
    const next = results[Math.max(0, Math.min(results.length - 1, i < 0 ? 0 : i + delta))]
    open(next.rec, true)
  }

  function onkey(e: KeyboardEvent) {
    if (store.status !== 'ready' || e.ctrlKey || e.metaKey || e.altKey || editing || view.name === 'new') return
    const inField = (e.target as HTMLElement).closest('input, textarea, select, [contenteditable]')
    const inSearch = e.target === searchEl
    if (inField && !inSearch) return
    if (e.key === '/' && !inSearch) {
      e.preventDefault()
      searchEl?.focus()
      searchEl?.select()
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (view.name !== 'list' && view.name !== 'record') return
      e.preventDefault()
      step(e.key === 'ArrowDown' ? 1 : -1)
    } else if (e.key === 'Enter' && inSearch && results.length) {
      e.preventDefault()
      open(selected && results.some((x) => x.rec.uid === selected) ? current! : results[0].rec)
      searchEl?.blur()
    } else if (e.key === 'Escape' && inSearch) {
      if (query) query = ''
      else searchEl?.blur()
    } else if (!inField && store.user && (e.key === 'n' || e.key === 'N')) { // read only: propose a new contact
      e.preventDefault()
      go(e.key === 'N' ? '/new/company' : '/new/person')
    }
  }

  // ------------------------------------------------------------- saved filters, export, selection
  const listState = (): ListState => ({ q: query, scope: activeScope, kind, filters: Object.fromEntries(activeFilters),
                                        ...(advCount ? { adv: $state.snapshot(adv) } : {}) })
  function applyState(s: ListState) {
    query = s.q
    scope = s.scope as Scope
    kind = s.kind
    filters = { ...s.filters }
    adv = s.adv ? structuredClone(s.adv) : emptyGroup() // older saved filters have none
    document.getElementById('saved-menu')?.hidePopover()
  }
  let saveName = $state('')
  let saveShared = $state(false)
  async function saveFilter(e: SubmitEvent) {
    e.preventDefault()
    try {
      await store.saveFilter(saveName, listState(), saveShared)
      toast(t('saved.saved', { name: saveName }))
      saveName = ''
      saveShared = false
    } catch (err) {
      toast(err instanceof ApiError ? terr(err.code) : t('err.generic'), { kind: 'error' })
    }
  }

  async function exportList(format: 'csv' | 'xlsx') {
    document.getElementById('export-menu')?.hidePopover()
    try {
      await download('/api/export', { format, uids: results.map((x) => x.rec.uid) })
    } catch (err) {
      toast(err instanceof ApiError ? terr(err.code) : t('err.generic'), { kind: 'error' })
    }
  }

  // selection mode for bulk edits: null = off
  let picked = $state.raw<Set<string> | null>(null)
  let anchor: string | null = null
  function onpick(uid: string, shift: boolean) {
    picked = pick(picked ?? new Set(), results.map((x) => x.rec.uid), uid, anchor, shift)
    anchor = uid
  }

  async function setLang(lang: 'de' | 'en') {
    const r = await patch('/api/me', { language: lang })
    store.user = r.user
    store.applyLang()
  }

  const settingsPage = () => import('./settings/Settings.svelte') // admin-only, keep it out of the main bundle
  const qualityPage = () => import('./components/Quality.svelte') // maintainers only, like settings
  const duplicatesPage = () => import('./components/Duplicates.svelte')

  const userLabel = $derived(store.user ? [store.user.first_name, store.user.last_name].join(' ').trim() || store.user.username : '')
  const showList = $derived(view.name === 'list' || view.name === 'record' || view.name === 'proposal')
</script>

<svelte:window onkeydown={onkey} />

{#if store.status === 'loading'}
  <div class="boot"><div class="spinner"></div></div>
{:else if store.status === 'login'}
  <Login />
{:else}
  <div class="app">
    <header class="top">
      <a class="logo" href="/" aria-label="Kartei"><img class="mark" src={logo} alt="" /><span class="word">Kartei</span></a>
      <label class="search">
        <Search size={16} />
        <input bind:this={searchEl} bind:value={query} type="search" placeholder={t('top.search')}
               autocomplete="off" spellcheck="false" aria-label={t('top.search')} />
        {#if query}
          <button class="clear" onclick={() => { query = ''; searchEl?.focus() }} aria-label={t('common.clear')}><X size={14} /></button>
        {:else}
          <kbd>/</kbd>
        {/if}
      </label>
      <div class="right">
        {#if store.offline}
          <span class="status warn" title={t('top.offline')}><WifiOff size={16} /></span>
        {:else}
          <button class="btn icon ghost status" class:spin={store.syncing} onclick={() => store.sync()} title={t('top.sync')}>
            <RefreshCw size={16} />
          </button>
        {/if}
        <!-- read only: the same menu proposes the new contact to a maintainer -->
        <button class="btn primary" popovertarget="new-menu"><Plus size={16} /><span class="hide-sm">{t('top.new')}</span><ChevronDown size={14} /></button>
        <div id="new-menu" popover class="menu" style="right: 64px">
          <a href="/new/person" onclick={() => document.getElementById('new-menu')?.hidePopover()}>
            <UserRound size={16} />{store.canEdit ? t('kind.person') : t('new.propose_person')}<kbd>N</kbd></a>
          <a href="/new/company" onclick={() => document.getElementById('new-menu')?.hidePopover()}>
            <Building2 size={16} />{store.canEdit ? t('kind.company') : t('new.propose_company')}<kbd>⇧ N</kbd></a>
        </div>
        <button class="btn icon ghost user" popovertarget="user-menu" aria-label={userLabel}><User size={18} /></button>
        <div id="user-menu" popover class="menu" style="right: 12px">
          <div class="who"><strong>{userLabel}</strong><span class="muted">{t(`role.${store.user?.role}`)}</span></div>
          <div class="langs">
            <button class="chip" class:on={i18n.lang === 'de'} onclick={() => setLang('de')}>Deutsch</button>
            <button class="chip" class:on={i18n.lang === 'en'} onclick={() => setLang('en')}>English</button>
          </div>
          <div class="langs" role="group" aria-label={t('theme.label')}>
            <button class="chip" class:on={theme.value === ''} onclick={() => setTheme('')} title={t('theme.system')}><Monitor size={13} />{t('theme.system')}</button>
            <button class="chip" class:on={theme.value === 'light'} onclick={() => setTheme('light')} title={t('theme.light')}><Sun size={13} />{t('theme.light')}</button>
            <button class="chip" class:on={theme.value === 'dark'} onclick={() => setTheme('dark')} title={t('theme.dark')}><Moon size={13} />{t('theme.dark')}</button>
          </div>
          <a href="/account" onclick={() => document.getElementById('user-menu')?.hidePopover()}><User size={16} />{t('top.account')}</a>
          {#if store.canEdit}
            <a href="/trash" onclick={() => document.getElementById('user-menu')?.hidePopover()}><Trash2 size={16} />{t('top.trash')}</a>
            <a href="/quality" onclick={() => document.getElementById('user-menu')?.hidePopover()}><ShieldCheck size={16} />{t('quality.title')}</a>
            <a href="/duplicates" onclick={() => document.getElementById('user-menu')?.hidePopover()}><Copy size={16} />{t('dupes.title')}</a>
          {/if}
          {#if store.isAdmin}
            <a href="/settings/fields" onclick={() => document.getElementById('user-menu')?.hidePopover()}><Settings size={16} />{t('top.settings')}</a>
          {/if}
          <button onclick={() => store.logout()}><LogOut size={16} />{t('top.logout')}</button>
          {#if store.about}
            <div class="about">Kartei {store.about.version} · <a href={store.about.source} target="_blank" rel="noopener">{t('top.source')}</a></div>
          {/if}
        </div>
      </div>
    </header>

    <div class="main" class:detail={view.name !== 'list'} class:full={!showList}>
      {#if showList}
        <aside class="side">
          {#if scopes.length}
            <div class="scopes" role="tablist">
              <button role="tab" aria-selected={activeScope === 'all'} class:on={activeScope === 'all'} onclick={() => (scope = 'all')}>{t('scope.all')}</button>
              {#each scopes as s (s)}
                <button role="tab" aria-selected={activeScope === s} class:on={activeScope === s} class:todo={s === 'review' || s === 'proposals'}
                        title={t(`scope.${s}_hint`)}
                        onclick={() => (scope = s)}>{t(`scope.${s}`)} <span class="n">{scopeCounts[s]}</span></button>
              {/each}
            </div>
          {/if}
          <div class="filters">
            <button class="chip" class:on={kind === 'all'} onclick={() => (kind = 'all')}>{t('filter.all')}</button>
            <button class="chip" class:on={kind === 'person'} onclick={() => (kind = 'person')}>{t('filter.persons')} <span class="n">{counts.person}</span></button>
            <button class="chip" class:on={kind === 'company'} onclick={() => (kind = 'company')}>{t('filter.companies')} <span class="n">{counts.company}</span></button>
            {#if filterFields.length}
              <button class="chip" class:on={activeFilters.length} popovertarget="filter-menu" title={t('filter.fields')}
                      aria-label={t('filter.fields')}><Filter size={13} />{activeFilters.length || ''}</button>
            {/if}
            <button class="chip" class:on={advCount} popovertarget="adv-menu" title={t('adv.title')} aria-label={t('adv.title')}>
              <SlidersHorizontal size={13} />{advCount || ''}</button>
          </div>
          {#if activeFilters.length || advCount}
            <div class="active">
              {#if advCount}
                <span class="tag"><button popovertarget="adv-menu">{t('adv.chip', { n: advCount })}</button>
                  <button aria-label={t('adv.reset')} onclick={() => (adv = emptyGroup())}><X size={11} /></button></span>
              {/if}
              {#each activeFilters as [key, vals] (key)}
                {@const f = store.fields.find((f) => f.key === key)}
                <span class="tag">{f ? L(f.label) : key}: {vals.length}
                  <button aria-label={t('common.remove')} onclick={() => (filters[key] = [])}><X size={11} /></button></span>
              {/each}
            </div>
          {/if}
          <div class="listbar">
            <span class="count tabular">{t('list.count', { n: results.length })}</span>
            <button class="btn icon sm ghost" popovertarget="saved-menu" title={t('saved.title')} aria-label={t('saved.title')}><Bookmark size={15} /></button>
            <button class="btn icon sm ghost" popovertarget="export-menu" title={t('dl.title')} aria-label={t('dl.title')} disabled={!results.length}><Download size={15} /></button>
            {#if store.canEdit}
              <button class="btn icon sm ghost" class:on={picked} aria-pressed={!!picked} title={t('bulk.title')} aria-label={t('bulk.title')}
                      onclick={() => { picked = picked ? null : new Set(); anchor = null }}><ListChecks size={15} /></button>
            {/if}
          </div>
          {#if picked && store.canEdit}
            <BulkBar {picked} all={results.map((x) => x.rec.uid)} onpick={(s) => (picked = s)} onclose={() => (picked = null)} />
          {/if}
          {#if activeScope === 'proposals' && store.newProposals.length}
            <!-- proposed new contacts have no record yet: listed above the contacts with proposals -->
            <nav class="newprops" aria-label={t('proposal.new_list')}>
              {#each store.newProposals as p (p.id)}
                <a href="/proposal/{p.id}" class:on={view.name === 'proposal' && view.id === p.id}>
                  {#if p.record_kind === 'person'}<UserRound size={15} />{:else}<Building2 size={15} />{/if}
                  <span class="nm">{p.label}</span><span class="badge">{t('proposal.new_badge')}</span></a>
              {/each}
            </nav>
          {/if}
          <div class="list"><RecordList items={results} {selected} {query} picked={store.canEdit ? picked : null} {onpick} /></div>
        </aside>
      {/if}
      <main class="pane scroll">
        {#if view.name === 'record'}
          {#if current}
            {#key current.uid}<RecordView rec={current} bind:editing />{/key}
          {:else}
            <Missing uid={view.uid} />
          {/if}
        {:else if view.name === 'new'}
          <div class="newform">
            <h1>{store.canEdit ? (view.kind === 'person' ? t('new.person') : t('new.company'))
                               : view.kind === 'person' ? t('new.propose_person') : t('new.propose_company')}</h1>
            {#key view.kind + presetCompany}
              <RecordForm rec={null} kind={view.kind} {presetCompany} mode={store.canEdit ? 'edit' : 'propose'}
                          onclose={(saved, proposal) => (saved ? go(`/${saved.kind}/${saved.uid}`, true)
                                                         : proposal ? go(`/proposal/${proposal}`, true) : history.back())} />
            {/key}
          </div>
        {:else if view.name === 'phonelist'}
          <PhoneList items={results.map((x) => x.rec)} />
        {:else if view.name === 'proposal'}
          {#key view.id}<ProposalPage id={view.id} />{/key}
        {:else if view.name === 'trash'}
          <Trash />
        {:else if view.name === 'settings'}
          {#await settingsPage() then { default: SettingsPage }}<SettingsPage tab={view.tab} />{/await}
        {:else if view.name === 'account'}
          <Account />
        {:else if view.name === 'quality'}
          {#await qualityPage() then { default: QualityPage }}<QualityPage />{/await}
        {:else if view.name === 'duplicates'}
          {#await duplicatesPage() then { default: DuplicatesPage }}<DuplicatesPage a={view.a} b={view.b} />{/await}
        {:else}
          <Dashboard onapply={applyState} onscope={(s) => (scope = s)} />
        {/if}
      </main>
    </div>

    <div id="saved-menu" popover class="menu list-menu">
      {#each store.filters as f (f.id)}
        <button onclick={() => applyState(f.state)}><Bookmark size={15} /><span class="fname">{f.name}</span>
          {#if f.shared}<span class="badge">{t('saved.shared')}</span>{/if}</button>
      {:else}
        <p class="muted none">{t('saved.none')}</p>
      {/each}
      <form class="save" onsubmit={saveFilter}>
        <input class="input" bind:value={saveName} placeholder={t('saved.save_as')} aria-label={t('saved.save_as')} maxlength="100" />
        <div class="save-row">
          {#if store.canEdit}<label><input type="checkbox" bind:checked={saveShared} />{t('saved.share')}</label>{/if}
          <button class="btn sm primary" disabled={!saveName.trim()}>{t('common.save')}</button>
        </div>
      </form>
    </div>
    <div id="export-menu" popover class="menu list-menu">
      <button onclick={() => exportList('xlsx')}><Download size={15} />{t('dl.xlsx', { n: results.length })}</button>
      <button onclick={() => exportList('csv')}><Download size={15} />{t('dl.csv', { n: results.length })}</button>
      <a href="/phonelist" onclick={() => document.getElementById('export-menu')?.hidePopover()}><Printer size={15} />{t('phonelist.menu', { n: results.length })}</a>
    </div>

    <div id="adv-menu" popover class="menu adv-menu"><AdvancedFilter bind:adv n={results.length} /></div>
    {#if filterFields.length}
      <div id="filter-menu" popover class="menu filter-menu">
        {#each filterFields as f (f.key)}
          <div class="ff">
            <span class="label">{L(f.label)}</span>
            <Combobox multiple value={filters[f.key] ?? []}
                      options={f.options.map((o) => ({ value: o.value, label: o[i18n.lang] || o.de,
                                                       hint: f.type === 'user' || f.type === 'users' ? o.value : undefined }))}
                      onchange={(v) => (filters[f.key] = v)} />
          </div>
        {/each}
        {#if activeFilters.length}<button class="btn sm" onclick={() => (filters = {})}>{t('filter.reset')}</button>{/if}
      </div>
    {/if}
  </div>
{/if}
<Toasts />
<ConfirmDialog />

<style>
  .boot { height: 100%; display: grid; place-items: center; }
  .spinner { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--border); border-top-color: var(--accent); animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .app { height: 100%; display: flex; flex-direction: column; }
  .top { flex: none; height: 52px; display: flex; align-items: center; gap: 16px; padding: 0 12px 0 16px;
    background: var(--panel); border-bottom: 1px solid var(--border); }
  .logo { display: flex; align-items: center; gap: 8px; color: var(--text); font-weight: 650; letter-spacing: -0.02em; width: 168px; }
  .logo:hover { text-decoration: none; }
  .mark { width: 26px; height: 26px; display: block; }
  .search { flex: 1; min-width: 0; max-width: 560px; display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 10px;
    border-radius: 10px; background: var(--panel-2); border: 1px solid transparent; color: var(--muted); cursor: text;
    transition: border-color 0.12s, background-color 0.12s; }
  .search:focus-within { background: var(--panel); border-color: var(--accent); }
  .search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text); height: 100%; }
  .search input::-webkit-search-cancel-button { display: none; }
  .clear { border: 0; background: none; padding: 2px; color: var(--muted); cursor: pointer; display: inline-flex; }
  .right { margin-left: auto; display: flex; align-items: center; gap: 6px; }
  .status { color: var(--muted); }
  .status.warn { color: var(--warn); display: inline-flex; padding: 0 8px; }
  .spin :global(svg) { animation: spin 0.8s linear infinite; }

  .menu { position: fixed; inset: auto; top: 56px; margin: 0; min-width: 220px; padding: 6px; border: 1px solid var(--border);
    border-radius: 10px; background: var(--panel); box-shadow: var(--shadow-lg); color: var(--text); }
  .menu a, .menu > button { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border-radius: 6px;
    color: inherit; border: 0; background: none; cursor: pointer; text-align: left; }
  .menu a:hover, .menu > button:hover { background: var(--panel-2); text-decoration: none; }
  .menu kbd { margin-left: auto; }
  .who { display: flex; flex-direction: column; padding: 6px 10px 8px; border-bottom: 1px solid var(--border); margin-bottom: 6px; }
  .langs { display: flex; gap: 6px; padding: 2px 10px 8px; }
  .filter-menu { top: 140px; left: 12px; width: 320px; gap: 10px; padding: 12px; }
  .filter-menu:popover-open { display: grid; }
  .adv-menu { top: 110px; left: 12px; width: min(560px, calc(100vw - 24px)); max-height: calc(100dvh - 130px); overflow: auto;
    padding: 12px; overscroll-behavior: contain; }

  .main { flex: 1; min-height: 0; display: grid; grid-template-columns: 380px 1fr; }
  .main.full { grid-template-columns: 1fr; }
  .side { min-height: 0; display: flex; flex-direction: column; border-right: 1px solid var(--border); background: var(--panel); }
  .scopes { display: flex; flex-wrap: wrap; gap: 2px; margin: 12px 12px 0; padding: 3px; border-radius: 9px; background: var(--panel-2); }
  .scopes button { flex: 1 1 auto; display: flex; align-items: center; justify-content: center; gap: 5px; min-width: 0;
    border: 0; background: none; padding: 5px 6px; border-radius: 7px; color: var(--muted); font-weight: 500;
    font-size: 12.5px; white-space: nowrap; cursor: pointer; transition: color 0.12s, background-color 0.12s; }
  .scopes button:hover { color: var(--text); }
  .scopes button.on { background: var(--panel); color: var(--text); box-shadow: 0 1px 2px rgb(0 0 0 / 0.12); }
  .scopes .todo .n { color: light-dark(#fff, #0f0f12); background: var(--accent); border-radius: 8px; padding: 0 5px; }  /* like .btn.primary */
  .scopes .n { font-size: 11px; color: var(--faint); font-variant-numeric: tabular-nums; }
  .filters { display: flex; gap: 6px; padding: 12px 12px 6px; flex-wrap: wrap; }
  .filters .n { color: var(--faint); font-size: 12px; font-variant-numeric: tabular-nums; }
  .chip.on .n { color: inherit; opacity: 0.7; }
  .active { display: flex; gap: 4px; flex-wrap: wrap; padding: 0 12px 6px; }
  .active button { border: 0; background: none; padding: 0; display: inline-flex; color: inherit; cursor: pointer; }
  .listbar { display: flex; align-items: center; gap: 2px; padding: 0 12px 4px 18px; color: var(--faint); }
  .listbar .count { flex: 1; font-size: 12px; }
  .listbar .btn { color: var(--muted); }
  .listbar .btn.on { color: var(--accent); background: var(--accent-soft); }
  .list-menu { top: 150px; left: 12px; width: 320px; }
  .list-menu .fname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .list-menu .none { margin: 6px 10px; }
  .save { display: grid; gap: 6px; padding: 8px 4px 2px; margin-top: 6px; border-top: 1px solid var(--border); }
  .save-row { display: flex; align-items: center; gap: 8px; justify-content: flex-end; }
  .save-row label { display: flex; align-items: center; gap: 6px; margin-right: auto; font-size: 13px; }
  .list { flex: 1; min-height: 0; }
  .about { padding: 8px 10px 2px; border-top: 1px solid var(--border); margin-top: 4px; font-size: 12px; color: var(--muted); }
  .about a { display: inline; width: auto; padding: 0; color: var(--accent); }
  .about a:hover { background: none; text-decoration: underline; }
  .newprops { display: flex; flex-direction: column; gap: 2px; padding: 0 8px 6px; border-bottom: 1px solid var(--border); margin-bottom: 4px; }
  .newprops a { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 8px; color: var(--text); }
  .newprops a:hover, .newprops a.on { background: var(--panel-2); text-decoration: none; }
  .newprops .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pane { min-height: 0; background: var(--panel); }
  .newform { max-width: 920px; margin: 0 auto; padding: 24px 28px; }
  .newform h1 { font-size: 22px; margin-bottom: 18px; }

  @media (max-width: 860px) {
    .logo { width: auto; }
    .logo .word, .hide-sm, .search kbd { display: none; }
    .top { gap: 8px; padding: 0 8px 0 12px; }
    .main { grid-template-columns: 1fr; }
    .main.detail .side { display: none; }
    .main:not(.detail) .pane { display: none; }
    .newform { padding: 14px 16px; }
  }
</style>
