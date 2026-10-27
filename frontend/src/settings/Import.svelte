<script lang="ts">
  import { Download, Upload } from '@lucide/svelte'
  import Combobox from '../components/Combobox.svelte'
  import { ApiError, api, downloadJson, readJson } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { L, t, terr, tmsg } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import type { L10n } from '../lib/types'

  type Side = 'person' | 'company'
  interface Mapping {
    format: string; version: number
    columns: Record<string, Record<Side, string>>
    kind: { column: string; company_prefix: string; person_prefix: string }
  }
  interface Preview {
    headers: string[]; samples: string[][]; rows: number; mapping: Mapping; guessed: string[]
    fields: { key: string; label: L10n; applies_to: Side | 'both' }[]
  }

  let file = $state<File | null>(null)
  let preview = $state<Preview | null>(null)
  let mapping = $state<Mapping | null>(null)
  let result = $state<any>(null)
  let busy = $state(false)
  let error = $state('')
  let dragging = $state(false)

  const fail = (e: unknown) =>
    (error = e instanceof ApiError ? (e.body?.detail ? tmsg(e.body.detail) : terr(e.code)) : t('err.generic'))

  const targets = $derived.by(() => {
    const fields = (side: Side) => (preview?.fields ?? [])
      .filter((f) => f.applies_to === side || f.applies_to === 'both')
      .map((f) => ({ value: `field:${f.key}`, label: L(f.label), hint: f.key }))
    const common = [{ value: 'core:legacy_id', label: t('calc.legacy_id') }]
    const make = [{ value: 'new', label: t('import.new_field') }]
    return {
      person: [...common, { value: 'core:first_name', label: t('core.first_name') }, { value: 'core:last_name', label: t('core.last_name') },
        { value: 'core:company', label: t('import.company_link') }, ...make, ...fields('person')],
      company: [...common, { value: 'core:name', label: t('core.name') }, ...make, ...fields('company')],
    }
  })

  async function pick(f: File | null) {
    file = f
    preview = mapping = result = null
    error = ''
    if (!f) return
    const fd = new FormData()
    fd.append('file', f)
    try {
      preview = await api<Preview>('POST', '/api/admin/import/preview', fd)
      mapping = preview.mapping
    } catch (e) {
      fail(e)
    }
  }

  async function loadMapping(f: File | undefined) {
    const doc = f && (await readJson(f))
    if (doc?.format !== 'kartei-import-mapping' || !mapping) return toast(terr('invalid_format'), { kind: 'error' })
    for (const [h, pair] of Object.entries(doc.columns ?? {})) if (h in mapping.columns) Object.assign(mapping.columns[h], pair)
    Object.assign(mapping.kind, doc.kind ?? {})
    result = null
  }

  async function run(dry: boolean) {
    busy = true
    error = ''
    const fd = new FormData()
    fd.append('file', file!)
    fd.append('dry_run', dry ? '1' : '0')
    fd.append('mapping', JSON.stringify(mapping))
    try {
      result = await api('POST', '/api/admin/import', fd)
      if (!dry) store.sync()
    } catch (e) {
      fail(e)
    } finally {
      busy = false
    }
  }
</script>

<div class="card box">
  <p>{t('import.hint')}</p>
  <label class="drop" class:on={dragging}
         ondragover={(e) => { e.preventDefault(); dragging = true }} ondragleave={() => (dragging = false)}
         ondrop={(e) => { e.preventDefault(); dragging = false; pick(e.dataTransfer?.files?.[0] ?? null) }}>
    <Upload size={18} />
    <span>{file ? file.name : t('import.pick')}</span>
    <input type="file" accept=".csv,text/csv" hidden onchange={(e) => pick(e.currentTarget.files?.[0] ?? null)} />
  </label>

  {#if preview && mapping}
    <div class="head">
      <h3>{t('import.mapping')}</h3>
      <span class="spacer"></span>
      <button class="btn sm" onclick={() => downloadJson('kartei-import-mapping.json', mapping)}><Download size={13} />{t('mapping.export')}</button>
      <label class="btn sm"><Upload size={13} />{t('mapping.import')}
        <input type="file" accept=".json,application/json" hidden onchange={(e) => { loadMapping(e.currentTarget.files?.[0]); e.currentTarget.value = '' }} /></label>
    </div>
    <p class="hint">{t('import.mapping_hint')}</p>
    <table class="grid">
      <thead><tr><th>{t('import.column')}</th><th>{t('import.sample')}</th><th>{t('import.person_target')}</th><th>{t('import.company_target')}</th></tr></thead>
      <tbody>
        {#each preview.headers as h, i (h)}
          <tr>
            <td><strong>{h}</strong>
              {#if preview.guessed.includes(h)}<span class="badge warn" title={t('import.guessed_hint')}>{t('import.guessed')}</span>{/if}</td>
            <td class="muted sample">{preview.samples.map((r) => r[i]).filter(Boolean).slice(0, 2).join(' · ')}</td>
            {#each ['person', 'company'] as const as side}
              <td><Combobox options={targets[side]} value={mapping.columns[h][side] || null} placeholder={t('import.ignore')}
                            onchange={(v) => { mapping!.columns[h][side] = v ?? ''; result = null }} /></td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>

    <h3>{t('import.kind')}</h3>
    <div class="row3">
      <div>
        <label class="label" for="kc">{t('import.kind_column')}</label>
        <select id="kc" class="select" bind:value={mapping.kind.column} onchange={() => (result = null)}>
          <option value="">{t('import.kind_auto')}</option>
          {#each preview.headers as h}<option value={h}>{h}</option>{/each}
        </select>
      </div>
      <div><label class="label" for="cp">{t('import.company_prefix')}</label>
        <input id="cp" class="input" bind:value={mapping.kind.company_prefix} oninput={() => (result = null)} placeholder="F-" /></div>
      <div><label class="label" for="pp">{t('import.person_prefix')}</label>
        <input id="pp" class="input" bind:value={mapping.kind.person_prefix} oninput={() => (result = null)} placeholder="P-" /></div>
    </div>
    <p class="hint">{mapping.kind.column ? t('import.kind_column_hint') + ' ' : ''}{t('import.kind_hint')}</p>

    <div class="actions">
      <button class="btn" disabled={busy} onclick={() => run(true)}>{t('import.dry')}</button>
      <button class="btn primary" disabled={busy || !result?.dry_run} onclick={() => run(false)}>{t('import.commit')}</button>
    </div>
  {/if}
  {#if error}<div class="error-text">{error}</div>{/if}
  {#if result}
    <div class="result" class:dry={result.dry_run}>
      <strong>{result.dry_run ? t('import.dry_result') : t('import.done')}</strong>
      <div>{t('import.rows', { n: result.rows })}</div>
      <div>{t('import.persons', { c: result.persons_created, u: result.persons_updated })}</div>
      <div>{t('import.companies', { c: result.companies_created, u: result.companies_updated })}</div>
      {#if result.warnings.length}
        <details open>
          <summary>{t('import.warnings', { n: result.warnings.length })}</summary>
          <ul>{#each result.warnings as w}<li>{tmsg(w)}</li>{/each}</ul>
        </details>
      {/if}
    </div>
  {/if}
</div>

<style>
  .box { max-width: 1040px; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  p { margin: 0; color: var(--muted); }
  .hint { margin-top: -8px; }
  h3 { font-size: 14px; margin: 0; }
  .head { display: flex; align-items: center; gap: 6px; }
  .spacer { flex: 1; }
  .sample { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .grid td { vertical-align: middle; }
  .grid td:nth-child(n + 3) { min-width: 220px; }
  .row3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  .drop { display: flex; align-items: center; gap: 10px; padding: 24px; border: 2px dashed var(--border-strong); border-radius: 10px; cursor: pointer; color: var(--muted); justify-content: center; }
  .drop:hover, .drop.on { border-color: var(--accent); color: var(--text); }
  .actions { display: flex; gap: 8px; }
  .result { padding: 12px; border-radius: 8px; background: var(--ok-soft); display: grid; gap: 4px; }
  .result.dry { background: var(--panel-2); }
  ul { margin: 6px 0 0; padding-left: 18px; font: 12px ui-monospace, monospace; max-height: 240px; overflow: auto; }
  @media (max-width: 640px) { .row3 { grid-template-columns: 1fr; } }
</style>
