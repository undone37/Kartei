<script lang="ts">
  import { Download, Eye, Plus, RefreshCw, Trash2, Upload } from '@lucide/svelte'
  import Combobox from '../components/Combobox.svelte'
  import { ApiError, downloadJson, get, post, put, readJson } from '../lib/api'
  import { dateTime, relTime } from '../lib/format'
  import { L, t, terr, tmsg } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import type { L10n } from '../lib/types'

  interface Column { attr: string; person: string; company: string }
  const KEYS = ['ad_enabled', 'ad_ou', 'ad_bind_dn', 'ad_kinds', 'ad_columns', 'ad_max_shrink_percent']

  let s = $state<Record<string, any> | null>(null)
  let errors = $state<Record<string, string>>({})
  let bindPw = $state('')
  let busy = $state(false)
  let dry = $state<any>(null)
  let syncSince = $state<string | null>(null)
  const st = $derived(s?.ad_status)
  let sources = $state<{ core: string[]; calc: string[]; fields: { key: string; label: L10n }[] }>({ core: [], calc: [], fields: [] })

  get<Record<string, any>>('/api/admin/settings').then((r) => {
    s = r
    syncSince = r.ad_sync_requested
  })
  get('/api/admin/exports').then((r) => (sources = r.sources))

  const sourceOptions = $derived([
    ...sources.core.map((c) => ({ value: `core:${c}`, label: t(`core.${c}`), hint: t('exports.core') })),
    ...sources.calc.map((c) => ({ value: `calc:${c}`, label: t(`calc.${c}`), hint: t('exports.calc') })),
    ...sources.fields.map((f) => ({ value: `field:${f.key}`, label: L(f.label), hint: f.key })),
  ])

  // same as the Outlook sync: the exporter runs it, poll until a newer status is reported
  $effect(() => {
    if (!syncSince) return
    const since = Date.parse(syncSince)
    const id = setInterval(async () => {
      const r = await get<Record<string, any>>('/api/admin/settings').catch(() => null)
      if (r?.ad_status?.at && Date.parse(r.ad_status.at) >= since) {
        s!.ad_status = r.ad_status
        syncSince = null
      }
    }, 3000)
    return () => clearInterval(id)
  })

  // the mapping as a file (examples/ad-mapping.json); importing replaces the rows, saving applies them
  async function loadMapping(f: File | undefined) {
    const doc = f && (await readJson(f))
    if (doc?.format !== 'kartei-ad-mapping' || !Array.isArray(doc.columns)) return toast(terr('invalid_format'), { kind: 'error' })
    s!.ad_columns = doc.columns.map((c: Column) => ({ attr: c.attr ?? '', person: c.person ?? '', company: c.company ?? '' }))
  }

  async function save(quiet = false) {
    errors = {}
    const snap = $state.snapshot(s) as Record<string, any>
    const body: Record<string, any> = Object.fromEntries(KEYS.map((k) => [k, snap[k]]))
    if (bindPw) body.ad_bind_password = bindPw
    try {
      s = await put('/api/admin/settings', body)
      bindPw = ''
      if (!quiet) toast(t('settings.saved'))
      return true
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
      else toast(t('err.generic'), { kind: 'error' })
      return false
    }
  }

  async function dryRun() {
    busy = true
    dry = null
    if (await save(true)) dry = await post('/api/admin/ad/dry-run').catch(() => ({ error: t('err.generic') }))
    busy = false
  }

  async function syncNow() {
    if (!(await save(true))) return
    try {
      syncSince = (await post<Record<string, any>>('/api/admin/ad/sync')).ad_sync_requested
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }
</script>

{#if s}
  <form class="card form" onsubmit={(e) => { e.preventDefault(); save() }}>
    <p class="hint">{t('ad.hint')}</p>
    <label class="check"><input type="checkbox" bind:checked={s.ad_enabled} /> {t('ad.enabled')}</label>
    {#if errors.ad_enabled}<div class="error-text">{terr(errors.ad_enabled)}</div>{/if}
    <div>
      <label class="label" for="ou">{t('ad.ou')}</label>
      <input id="ou" class="input mono" bind:value={s.ad_ou} placeholder="OU=Kartei,OU=Kontakte,DC=example,DC=local" />
      <p class="hint">{t('ad.ou_hint')}</p>
    </div>
    <div class="row2">
      <div><label class="label" for="adn">{t('ad.bind_dn')}</label><input id="adn" class="input mono" bind:value={s.ad_bind_dn} placeholder={s.ldap_bind_dn || 'CN=svc-kartei-ad,OU=Service,DC=example,DC=local'} /></div>
      <div><label class="label" for="apw">{t('ad.bind_pw')}</label>
        <input id="apw" class="input" type="password" bind:value={bindPw} placeholder={s.ad_bind_password_set ? '••••••••' : ''} autocomplete="new-password" /></div>
    </div>
    <p class="hint">{t('ad.bind_hint')}</p>
    <div class="row2">
      <div><label class="label" for="ak">{t('exports.kinds')}</label>
        <select id="ak" class="select" bind:value={s.ad_kinds}>
          <option value="both">{t('applies.both')}</option><option value="person">{t('filter.persons')}</option><option value="company">{t('filter.companies')}</option>
        </select></div>
      <div><label class="label" for="ag">{t('ad.guard')}</label>
        <input id="ag" class="input" type="number" min="0" max="100" bind:value={s.ad_max_shrink_percent} />
        <p class="hint">{t('ad.guard_hint')}</p>
        {#if errors.ad_max_shrink_percent}<div class="error-text">{terr(errors.ad_max_shrink_percent)}</div>{/if}</div>
    </div>

    <div class="maphead">
      <h3>{t('ad.mapping')}</h3>
      <button type="button" class="btn sm" onclick={() => downloadJson('kartei-ad-mapping.json', { format: 'kartei-ad-mapping', version: 1, columns: $state.snapshot(s!.ad_columns) })}><Download size={13} />{t('mapping.export')}</button>
      <label class="btn sm"><Upload size={13} />{t('mapping.import')}
        <input type="file" accept=".json,application/json" hidden onchange={(e) => { loadMapping(e.currentTarget.files?.[0]); e.currentTarget.value = '' }} /></label>
    </div>
    <p class="hint">{t('ad.mapping_hint')}</p>
    {#if errors.ad_columns}<div class="error-text">{terr(errors.ad_columns)}</div>{/if}
    <div class="cols">
      <div class="colhead"><span>{t('ad.attr')}</span><span>{t('exports.person_source')}</span><span>{t('exports.company_source')}</span><span></span></div>
      {#each s.ad_columns as c, i (i)}
        <div class="col">
          <input class="input mono" bind:value={c.attr} placeholder="telephoneNumber" />
          {#each ['person', 'company'] as const as side}
            {#if (s.ad_kinds === 'both' || s.ad_kinds === side) && c[side].startsWith('const:')}
              <input class="input" value={c[side].slice(6)} oninput={(e) => (c[side] = 'const:' + e.currentTarget.value)} placeholder={t('exports.const')} />
            {:else if s.ad_kinds === 'both' || s.ad_kinds === side}
              <Combobox options={sourceOptions} value={c[side] || null} placeholder={t('exports.empty_col')} onchange={(v) => (c[side] = v ?? '')} />
            {:else}<span></span>{/if}
          {/each}
          <span class="colact">
            <button type="button" class="btn icon sm ghost" title={t('exports.const')} onclick={() => { c.person = c.person.startsWith('const:') ? '' : 'const:'; c.company = c.company.startsWith('const:') ? '' : 'const:' }}>“”</button>
            <button type="button" class="btn icon sm ghost" onclick={() => s!.ad_columns.splice(i, 1)} aria-label={t('common.remove')}><Trash2 size={13} /></button>
          </span>
        </div>
      {/each}
      <div><button type="button" class="btn sm" onclick={() => s!.ad_columns.push({ attr: '', person: '', company: '' } as Column)}><Plus size={13} />{t('ad.add_attr')}</button></div>
    </div>

    <div class="test">
      <button type="button" class="btn" onclick={dryRun} disabled={busy || !s.ad_ou}><Eye size={15} />{t('ad.dry_run')}</button>
      <button type="button" class="btn" class:spin={syncSince} onclick={syncNow} disabled={!!syncSince || !s.ad_enabled}><RefreshCw size={15} />{t('graph.sync_now')}</button>
    </div>
    {#if dry}
      <div class="result" class:info={!dry.error && !dry.blocked} class:bad={dry.error || dry.blocked}>
        {#if dry.error}<strong>{t('graph.failed')}:</strong> {tmsg(dry.error)}
        {:else}
          <strong>{t('ad.dry_result', dry)}</strong>
          {#if dry.blocked}<div>{tmsg(dry.blocked)}</div>{/if}
          {#each [['add', 'ad.would_add'], ['rename', 'ad.would_rename'], ['modify', 'ad.would_modify'], ['delete', 'ad.would_delete']] as [k, key]}
            {#if dry[k].length}
              <div class="sample">
                <span class="label">{t(key)}</span>
                {#each dry[k] as row}
                  <div class="mono" title={row.dn}>{row.name}{#if row.to} → {row.to}{/if}{#if row.attrs} ({row.attrs.join(', ')}){/if}</div>
                {/each}
              </div>
            {/if}
          {/each}
        {/if}
      </div>
    {/if}
    <div class="result" class:info={!st?.error} class:bad={st?.error}>
      <strong>{t('graph.last')}</strong>
      {#if syncSince}<div>{t('graph.syncing')}</div>{/if}
      {#if !st?.at}<div>{t('graph.never')}</div>
      {:else}
        <div title={dateTime(st.at)}>{relTime(st.at)}</div>
        {#if st.error}<div>{tmsg(st.error)}</div>
        {:else}<div>{t('ad.result', st)}</div>
          {#each st.failed as f}<div class="err-line">{f}</div>{/each}{/if}
      {/if}
    </div>
    <div class="result info">
      <strong>{t('ad.setup')}</strong>
      <div class="hint">{t('ad.setup_rights')}</div>
      <div class="hint">{t('ad.setup_marker')}</div>
      <div class="hint">{t('ad.setup_interval')}</div>
    </div>
    <div class="actions"><button class="btn primary">{t('common.save')}</button></div>
  </form>
{/if}

<style>
  .form { max-width: 860px; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  .maphead { display: flex; align-items: center; gap: 6px; }
  .maphead h3 { flex: 1; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  h3 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-top: 6px; }
  .mono { font: 12px ui-monospace, monospace; }
  .cols { display: flex; flex-direction: column; gap: 6px; }
  .colhead, .col { display: grid; grid-template-columns: 1fr 1.3fr 1.3fr 64px; gap: 8px; align-items: center; }
  .colhead { font-size: 12px; color: var(--muted); }
  .colact { display: flex; gap: 2px; }
  .test { display: flex; gap: 8px; }
  .result { padding: 10px 12px; border-radius: 8px; background: var(--ok-soft); color: var(--ok); display: grid; gap: 4px; overflow-wrap: anywhere; }
  .result.bad { background: var(--danger-soft); color: var(--danger); }
  .result.info { background: var(--panel-2); color: var(--text); }
  .sample { display: grid; gap: 2px; margin-top: 6px; }
  .spin :global(svg) { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .err-line { color: var(--danger); font-size: 12px; }
  .hint { margin: 2px 0 0; }
  .actions { display: flex; justify-content: flex-end; }
  @media (max-width: 640px) { .row2, .colhead, .col { grid-template-columns: 1fr; } }
</style>
