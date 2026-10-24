<script lang="ts">
  import { FileSpreadsheet, FileText, GripVertical, Play, Plus, Trash2, Eye, ListPlus } from '@lucide/svelte'
  import Combobox from '../components/Combobox.svelte'
  import { ApiError, del, get, patch, post } from '../lib/api'
  import { dateTime, relTime } from '../lib/format'
  import { L, i18n, t, terr, tmsg } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { L10n } from '../lib/types'

  interface Column { header: string; person: string; company: string }
  interface Profile {
    id?: number; name: string; enabled: boolean; format: 'csv' | 'xlsx'; path: string; schedule: 'auto' | 'manual'
    kinds: 'person' | 'company' | 'both'; filter_field: number | null; filter_values: string[]; columns: Column[]
    options: Record<string, any>; effective_options?: Record<string, any>; max_shrink_percent: number
    last_run_at?: string | null; last_status?: string; last_message?: string; last_rows?: number | null
  }
  interface Sources { core: string[]; calc: string[]; fields: { key: string; label: L10n; applies_to: string; type: string }[] }

  const CSV_DEFAULTS = { delimiter: ';', quotechar: '"', quoting: 'minimal', encoding: 'utf-8-sig', line_ending: 'crlf', header: true,
    newlines: 'keep', multi_sep: ', ', date_format: '%d.%m.%Y', decimal_sep: ',', bool_true: 'Ja', bool_false: 'Nein' }
  const XLSX_DEFAULTS = { sheet_name: 'Kontakte', header: true, bold_header: true, autofilter: true, freeze_header: true,
    autowidth: true, date_format: 'DD.MM.YYYY', number_format: '#,##0.00' }

  let profiles = $state<Profile[]>([])
  let sources = $state<Sources>({ core: [], calc: [], fields: [] })
  let root = $state('/export')
  let fieldDefs = $state<any[]>([])
  let edit = $state<Profile | null>(null)
  let errors = $state<Record<string, string>>({})
  let preview = $state<{ header: string[]; rows: any[][]; total: number } | null>(null)
  let dragIdx = $state<number | null>(null)
  let running = $state<number | null>(null)

  async function load() {
    const r = await get('/api/admin/exports')
    profiles = r.exports
    sources = r.sources
    root = r.export_root
  }
  load()
  get('/api/admin/fields').then((r) => (fieldDefs = r.fields))

  const sourceOptions = $derived([
    ...sources.core.map((c) => ({ value: `core:${c}`, label: t(`core.${c}`), hint: t('exports.core') })),
    ...sources.calc.map((c) => ({ value: `calc:${c}`, label: t(`calc.${c}`), hint: t('exports.calc') })),
    ...sources.fields.map((f) => ({ value: `field:${f.key}`, label: L(f.label), hint: f.key })),
  ])
  const selectFields = $derived(fieldDefs.filter((f) => f.type === 'select' || f.type === 'multiselect'))
  const filterField = $derived(selectFields.find((f) => f.id === edit?.filter_field))

  function create(format: 'csv' | 'xlsx') {
    edit = { name: '', enabled: true, format, path: `${root}/kontakte.${format}`, schedule: 'auto', kinds: 'both',
      filter_field: null, filter_values: [], columns: [], options: {}, max_shrink_percent: 10 }
    errors = {}
    preview = null
  }

  function open(p: Profile) {
    edit = structuredClone($state.snapshot(p))
    edit.options = { ...(p.format === 'csv' ? CSV_DEFAULTS : XLSX_DEFAULTS), ...p.effective_options }
    errors = {}
    preview = null
  }

  function opts() {
    if (!edit) return {}
    const defaults = edit.format === 'csv' ? CSV_DEFAULTS : XLSX_DEFAULTS
    return { ...defaults, ...edit.options }
  }

  // option values are always read through o so defaults show up
  const o = $derived(edit ? { ...(edit.format === 'csv' ? CSV_DEFAULTS : XLSX_DEFAULTS), ...edit.options } as Record<string, any> : {})
  const setOpt = (k: string, v: any) => (edit!.options = { ...edit!.options, [k]: v })

  function body() {
    const b = $state.snapshot(edit!) as any
    b.options = opts()
    return b
  }

  async function save() {
    errors = {}
    try {
      const saved = edit!.id ? await patch(`/api/admin/exports/${edit!.id}`, body()) : await post('/api/admin/exports', body())
      edit = null
      toast(t('settings.saved'))
      await load()
      return saved
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
      else toast(t('err.generic'), { kind: 'error' })
    }
  }

  async function showPreview() {
    errors = {}
    try {
      preview = await post('/api/admin/exports/preview', body())
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
    }
  }

  async function run(p: Profile, force = false) {
    running = p.id!
    try {
      const r = await post<Profile>(`/api/admin/exports/${p.id}/run`, { force })
      profiles = profiles.map((x) => (x.id === p.id ? r : x))
      toast(`${p.name}: ${tmsg(r.last_message)}`, { kind: r.last_status === 'error' ? 'error' : 'info' })
    } finally {
      running = null
    }
  }

  async function remove(p: Profile) {
    const ok = await confirmDialog({ title: t('exports.delete_title', { name: p.name }), message: t('exports.delete_text'),
                                     confirmLabel: t('common.delete'), danger: true })
    if (!ok) return
    await del(`/api/admin/exports/${p.id}`)
    edit = null
    load()
  }

  function addAllFields() {
    const have = new Set(edit!.columns.flatMap((c) => [c.person, c.company]))
    for (const f of sources.fields) {
      const src = `field:${f.key}`
      if (have.has(src)) continue
      edit!.columns.push({ header: L(f.label), person: f.applies_to !== 'company' ? src : '', company: f.applies_to !== 'person' ? src : '' })
    }
  }

  function addColumn() {
    edit!.columns.push({ header: '', person: '', company: '' })
  }

  function onPick(c: Column, side: 'person' | 'company', v: string | null) {
    c[side] = v ?? ''
    if (!c.header && v) c.header = sourceOptions.find((s) => s.value === v)?.label ?? ''
  }

  function dropCol(i: number) {
    if (dragIdx == null || dragIdx === i) return
    const cols = edit!.columns
    const [moved] = cols.splice(dragIdx, 1)
    cols.splice(i, 0, moved)
    dragIdx = null
  }

  const cell = (v: any) => (v == null ? '' : Array.isArray(v) ? v.join(', ') : String(v))
</script>

{#if !edit}
  <div class="toolbar">
    <button class="btn primary" onclick={() => create('csv')}><FileText size={15} />{t('exports.new_csv')}</button>
    <button class="btn" onclick={() => create('xlsx')}><FileSpreadsheet size={15} />{t('exports.new_xlsx')}</button>
    <span class="hint">{t('exports.root', { root })}</span>
  </div>
  <table class="grid">
    <thead><tr><th>{t('exports.name')}</th><th>{t('exports.format')}</th><th>{t('exports.path')}</th><th>{t('exports.schedule')}</th><th>{t('exports.last_run')}</th><th></th></tr></thead>
    <tbody>
      {#each profiles as p (p.id)}
        <tr class="click" onclick={() => open(p)}>
          <td><strong>{p.name}</strong> {#if !p.enabled}<span class="badge">{t('exports.disabled')}</span>{/if}</td>
          <td>{p.format.toUpperCase()}</td>
          <td class="mono">{p.path}</td>
          <td>{t(`exports.${p.schedule}`)}</td>
          <td>
            {#if p.last_run_at}
              <span class="badge" class:ok={p.last_status === 'ok'} class:err={p.last_status === 'error'}>{p.last_status}</span>
              <span class="muted" title={dateTime(p.last_run_at)}>{relTime(p.last_run_at)}</span>
              <div class="msg" class:bad={p.last_status === 'error'}>{tmsg(p.last_message)}</div>
            {:else}<span class="muted">—</span>{/if}
          </td>
          <td class="act" onclick={(e) => e.stopPropagation()}>
            <button class="btn sm" disabled={running === p.id} onclick={() => run(p)}><Play size={13} />{t('exports.run')}</button>
            {#if p.last_status === 'error'}<button class="btn sm danger" disabled={running === p.id} onclick={() => run(p, true)} title={t('exports.force_hint')}>{t('exports.force')}</button>{/if}
          </td>
        </tr>
      {:else}
        <tr><td colspan="6" class="muted">{t('exports.empty')}</td></tr>
      {/each}
    </tbody>
  </table>
{:else}
  <div class="editor">
    <div class="card block">
      <div class="row3">
        <div><label class="label" for="n">{t('exports.name')}</label><input id="n" class="input" class:invalid={errors.name} bind:value={edit.name} />
          {#if errors.name}<div class="error-text">{terr(errors.name)}</div>{/if}</div>
        <div class="span2"><label class="label" for="p">{t('exports.path')}</label><input id="p" class="input mono" class:invalid={errors.path} bind:value={edit.path} />
          {#if errors.path}<div class="error-text">{terr(errors.path)}</div>{:else}<p class="hint">{t('exports.path_hint')}</p>{/if}</div>
      </div>
      <div class="row4">
        <div><label class="label" for="f">{t('exports.format')}</label>
          <select id="f" class="select" bind:value={edit.format} onchange={() => (edit!.options = {})}><option value="csv">CSV</option><option value="xlsx">XLSX</option></select></div>
        <div><label class="label" for="k">{t('exports.kinds')}</label>
          <select id="k" class="select" bind:value={edit.kinds}>
            <option value="both">{t('applies.both')}</option><option value="person">{t('filter.persons')}</option><option value="company">{t('filter.companies')}</option>
          </select></div>
        <div><label class="label" for="s">{t('exports.schedule')}</label>
          <select id="s" class="select" bind:value={edit.schedule}><option value="auto">{t('exports.auto')}</option><option value="manual">{t('exports.manual')}</option></select></div>
        <div><label class="label" for="g">{t('exports.guard')}</label>
          <input id="g" class="input" type="number" min="0" max="100" bind:value={edit.max_shrink_percent} />
          <p class="hint">{t('exports.guard_hint')}</p></div>
      </div>
      <div class="row3">
        <div><label class="label" for="ff">{t('exports.filter_field')}</label>
          <select id="ff" class="select" bind:value={edit.filter_field} onchange={() => (edit!.filter_values = [])}>
            <option value={null}>—</option>
            {#each selectFields as f (f.id)}<option value={f.id}>{L(f.label)}</option>{/each}
          </select></div>
        {#if filterField}
          <div class="span2"><span class="label">{t('exports.filter_values')}</span>
            <Combobox multiple value={edit.filter_values} options={filterField.options.map((o: any) => ({ value: o.value, label: o[i18n.lang] || o.de }))}
                      onchange={(v) => (edit!.filter_values = v)} /></div>
        {/if}
      </div>
      <label class="check"><input type="checkbox" bind:checked={edit.enabled} /> {t('exports.enabled')}</label>
    </div>

    <div class="card block">
      <div class="head">
        <h3>{t('exports.columns')}</h3>
        <button class="btn sm" onclick={addColumn}><Plus size={13} />{t('exports.add_column')}</button>
        <button class="btn sm" onclick={addAllFields}><ListPlus size={13} />{t('exports.add_all')}</button>
      </div>
      {#if errors.columns}<div class="error-text">{terr(errors.columns)}</div>{/if}
      <div class="cols">
        <div class="colhead"><span></span><span>{t('exports.header')}</span><span>{t('exports.person_source')}</span><span>{t('exports.company_source')}</span><span></span></div>
        {#each edit.columns as c, i (i)}
          <div class="col" draggable="true" ondragstart={() => (dragIdx = i)} ondragover={(e) => e.preventDefault()} ondrop={() => dropCol(i)} role="listitem">
            <span class="grip"><GripVertical size={14} /></span>
            <input class="input" bind:value={c.header} />
            {#if edit.kinds !== 'company'}
              {#if c.person.startsWith('const:')}
                <input class="input" value={c.person.slice(6)} oninput={(e) => (c.person = 'const:' + e.currentTarget.value)} placeholder={t('exports.const')} />
              {:else}
                <Combobox options={sourceOptions} value={c.person || null} placeholder={t('exports.empty_col')} onchange={(v) => onPick(c, 'person', v)} />
              {/if}
            {:else}<span></span>{/if}
            {#if edit.kinds !== 'person'}
              {#if c.company.startsWith('const:')}
                <input class="input" value={c.company.slice(6)} oninput={(e) => (c.company = 'const:' + e.currentTarget.value)} placeholder={t('exports.const')} />
              {:else}
                <Combobox options={sourceOptions} value={c.company || null} placeholder={t('exports.empty_col')} onchange={(v) => onPick(c, 'company', v)} />
              {/if}
            {:else}<span></span>{/if}
            <span class="colact">
              <button class="btn icon sm ghost" title={t('exports.const')} onclick={() => { c.person = c.person.startsWith('const:') ? '' : 'const:'; c.company = c.company.startsWith('const:') ? '' : 'const:' }}>“”</button>
              <button class="btn icon sm ghost" onclick={() => edit!.columns.splice(i, 1)} aria-label={t('common.remove')}><Trash2 size={13} /></button>
            </span>
          </div>
        {/each}
      </div>
    </div>

    <div class="card block">
      <h3>{t('exports.format_options', { format: edit.format.toUpperCase() })}</h3>
      {#if edit.format === 'csv'}
        <div class="row4">
          <div><label class="label" for="d">{t('csv.delimiter')}</label>
            <select id="d" class="select" value={o.delimiter} onchange={(e) => setOpt('delimiter', e.currentTarget.value)}>
              <option value=";">; ({t('csv.semicolon')})</option><option value=",">, ({t('csv.comma')})</option><option value={'\t'}>{t('csv.tab')}</option><option value="|">|</option>
            </select></div>
          <div><label class="label" for="q">{t('csv.quoting')}</label>
            <select id="q" class="select" value={o.quoting} onchange={(e) => setOpt('quoting', e.currentTarget.value)}>
              <option value="minimal">{t('csv.q_minimal')}</option><option value="all">{t('csv.q_all')}</option><option value="nonnumeric">{t('csv.q_nonnumeric')}</option>
            </select></div>
          <div><label class="label" for="qc">{t('csv.quotechar')}</label>
            <input id="qc" class="input" maxlength="1" value={o.quotechar} oninput={(e) => setOpt('quotechar', e.currentTarget.value)} /></div>
          <div><label class="label" for="enc">{t('csv.encoding')}</label>
            <select id="enc" class="select" value={o.encoding} onchange={(e) => setOpt('encoding', e.currentTarget.value)}>
              <option value="utf-8-sig">UTF-8 + BOM (Excel)</option><option value="utf-8">UTF-8</option><option value="cp1252">Windows-1252</option>
            </select></div>
          <div><label class="label" for="le">{t('csv.line_ending')}</label>
            <select id="le" class="select" value={o.line_ending} onchange={(e) => setOpt('line_ending', e.currentTarget.value)}>
              <option value="crlf">CRLF (Windows)</option><option value="lf">LF (Unix)</option>
            </select></div>
          <div><label class="label" for="nl">{t('csv.newlines')}</label>
            <select id="nl" class="select" value={o.newlines} onchange={(e) => setOpt('newlines', e.currentTarget.value)}>
              <option value="keep">{t('csv.nl_keep')}</option><option value="space">{t('csv.nl_space')}</option>
            </select></div>
          <div><label class="label" for="ms">{t('csv.multi_sep')}</label>
            <input id="ms" class="input" value={o.multi_sep} oninput={(e) => setOpt('multi_sep', e.currentTarget.value)} /></div>
          <div><label class="label" for="df">{t('csv.date_format')}</label>
            <select id="df" class="select" value={o.date_format} onchange={(e) => setOpt('date_format', e.currentTarget.value)}>
              <option value="%d.%m.%Y">31.12.2026</option><option value="%Y-%m-%d">2026-12-31</option><option value="%m/%d/%Y">12/31/2026</option>
            </select></div>
          <div><label class="label" for="ds">{t('csv.decimal_sep')}</label>
            <select id="ds" class="select" value={o.decimal_sep} onchange={(e) => setOpt('decimal_sep', e.currentTarget.value)}>
              <option value=",">1234,56</option><option value=".">1234.56</option>
            </select></div>
          <div><label class="label" for="bt">{t('csv.bool')}</label>
            <div class="pair"><input id="bt" class="input" value={o.bool_true} oninput={(e) => setOpt('bool_true', e.currentTarget.value)} />
              <input class="input" value={o.bool_false} oninput={(e) => setOpt('bool_false', e.currentTarget.value)} aria-label={t('common.no')} /></div></div>
        </div>
        <label class="check"><input type="checkbox" checked={o.header} onchange={(e) => setOpt('header', e.currentTarget.checked)} /> {t('csv.header')}</label>
      {:else}
        <div class="row4">
          <div><label class="label" for="sn">{t('xlsx.sheet')}</label><input id="sn" class="input" maxlength="31" value={o.sheet_name} oninput={(e) => setOpt('sheet_name', e.currentTarget.value)} /></div>
          <div><label class="label" for="xd">{t('csv.date_format')}</label><input id="xd" class="input mono" value={o.date_format} oninput={(e) => setOpt('date_format', e.currentTarget.value)} /></div>
          <div><label class="label" for="xn">{t('xlsx.number_format')}</label><input id="xn" class="input mono" value={o.number_format} oninput={(e) => setOpt('number_format', e.currentTarget.value)} /></div>
        </div>
        <div class="checks">
          {#each ['header', 'bold_header', 'autofilter', 'freeze_header', 'autowidth'] as k}
            <label class="check"><input type="checkbox" checked={o[k]} onchange={(e) => setOpt(k, e.currentTarget.checked)} /> {t(`xlsx.${k}`)}</label>
          {/each}
        </div>
      {/if}
      {#if errors.options}<div class="error-text">{terr(errors.options)}</div>{/if}
    </div>

    {#if preview}
      <div class="card block">
        <h3>{t('exports.preview', { n: preview.total })}</h3>
        <div class="scroll pv">
          <table class="grid">
            <thead><tr>{#each preview.header as h}<th>{h}</th>{/each}</tr></thead>
            <tbody>{#each preview.rows as row}<tr>{#each row as v}<td>{cell(v)}</td>{/each}</tr>{/each}</tbody>
          </table>
        </div>
      </div>
    {/if}

    <div class="footer">
      {#if edit.id}<button class="btn danger" onclick={() => remove(edit!)}><Trash2 size={14} />{t('common.delete')}</button>{/if}
      <span class="spacer"></span>
      <button class="btn" onclick={showPreview}><Eye size={15} />{t('exports.show_preview')}</button>
      <button class="btn" onclick={() => (edit = null)}>{t('common.cancel')}</button>
      <button class="btn primary" onclick={save}>{t('common.save')}</button>
    </div>
  </div>
{/if}

<style>
  .toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  .mono { font: 12px ui-monospace, monospace; }
  .msg { font-size: 12px; color: var(--muted); max-width: 320px; }
  .msg.bad { color: var(--danger); }
  .act { text-align: right; white-space: nowrap; }
  .editor { display: flex; flex-direction: column; gap: 16px; }
  .block { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .row3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .row4 { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
  .span2 { grid-column: span 2; }
  .check { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
  .checks { display: flex; gap: 18px; flex-wrap: wrap; }
  .head { display: flex; align-items: center; gap: 8px; }
  .head h3 { flex: 1; }
  h3 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .cols { display: flex; flex-direction: column; gap: 6px; }
  .colhead, .col { display: grid; grid-template-columns: 20px 1fr 1.3fr 1.3fr 64px; gap: 8px; align-items: center; }
  .colhead { font-size: 12px; color: var(--muted); }
  .grip { color: var(--faint); cursor: grab; }
  .colact { display: flex; gap: 2px; }
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
  .pv { max-height: 360px; }
  .pv td { white-space: pre-wrap; font-size: 13px; }
  .footer { display: flex; gap: 8px; position: sticky; bottom: 0; padding: 12px 0; background: linear-gradient(to bottom, transparent, var(--panel) 30%); }
  .spacer { flex: 1; }
  @media (max-width: 860px) { .row3 { grid-template-columns: 1fr; } .span2 { grid-column: auto; } }
</style>
