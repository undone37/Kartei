<script lang="ts">
  import { Archive, Download, GripVertical, Plus, Rows3, Upload, X } from '@lucide/svelte'
  import FieldEditor from './FieldEditor.svelte'
  import SectionManager from './SectionManager.svelte'
  import { ApiError, downloadJson, get, post, readJson } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { groupFields, moveField } from '../lib/sections'
  import { toast } from '../lib/toast.svelte'
  import type { Field, Section } from '../lib/types'

  const ACCESS = { read: 'access.all', maintainer: 'access.maintainer', admin: 'access.admin' } as const
  let fields = $state<Field[]>([])
  let sections = $state<Section[]>([])
  let targets = $state<string[]>([])
  let editing = $state<Field | 'new' | null>(null)
  let managing = $state(false) // section manager in the side panel
  let showArchived = $state(false)
  let dragId = $state<number | null>(null)
  let filter = $state<'all' | 'person' | 'company'>('all')
  type ImportRow = { key: string; label: any; status: 'new' | 'changed' | 'unchanged' | 'invalid'; changes?: string[]; errors: Record<string, string> }
  let pending = $state<{ document: any; fields: ImportRow[]; sections: ImportRow[] } | null>(null)

  async function load() {
    const r = await get<{ fields: Field[]; sections: Section[]; vcard_targets: string[] }>('/api/admin/fields')
    fields = r.fields
    sections = r.sections
    targets = r.vcard_targets
  }
  load()

  async function sectionsChanged() {
    await load()
    store.sync()
  }

  const isShown = (f: Field) => (showArchived || !f.archived) && (filter === 'all' || f.applies_to === filter || f.applies_to === 'both')
  // every section (also empty ones, as drop targets) with all fields; the table shows the filtered ones
  const groups = $derived(groupFields(fields, sections, true))

  async function saved() {
    editing = null
    await load()
    store.sync()
  }

  async function exportFields() {
    downloadJson('kartei-fields.json', await get('/api/admin/fields/export'))
  }

  async function importFile(file: File | undefined) {
    if (!file) return
    const document = await readJson(file)
    try {
      const r = await post<{ fields: ImportRow[]; sections: ImportRow[] }>('/api/admin/fields/import', { document })
      editing = null
      managing = false
      pending = { document, fields: r.fields, sections: r.sections }
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  async function applyImport() {
    const r = await post<{ fields: ImportRow[] }>('/api/admin/fields/import', { document: pending!.document, apply: true })
    toast(t('fields.import_done', { n: r.fields.filter((f) => f.status === 'new' || f.status === 'changed').length }))
    pending = null
    await load()
    store.sync()
  }

  // native drag & drop: onto a field (its position and section) or onto a section header (end of that section)
  function drop(section: number | null, target: Field | null = null) {
    const id = dragId
    dragId = null
    if (id == null || id === target?.id) return
    const moved = fields.find((f) => f.id === id)!
    const { ids } = moveField(groups, id, section, target?.id ?? null)
    const changed = moved.section !== section
    fields = ids.map((i, n) => {
      const f = fields.find((f) => f.id === i)!
      return { ...f, order: (n + 1) * 10, section: i === id ? section : f.section }
    })
    post('/api/admin/fields/reorder', { ids, moves: changed ? { [id]: section } : {} })
      .then(() => store.sync())
      .catch((e) => { toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' }); load() })
  }
</script>

<div class="layout" class:has-editor={editing || pending || managing}>
  <div>
    <div class="toolbar">
      <button class="btn primary" onclick={() => { pending = null; managing = false; editing = 'new' }}><Plus size={15} />{t('fields.new')}</button>
      <button class="btn" aria-pressed={managing} onclick={() => { pending = null; editing = null; managing = !managing }}
              title={t('fields.sections_hint')}><Rows3 size={15} />{t('fields.sections')}</button>
      <button class="btn" onclick={exportFields} title={t('fields.export_hint')}><Download size={15} />{t('fields.export')}</button>
      <label class="btn" title={t('fields.import_hint')}><Upload size={15} />{t('fields.import')}
        <input type="file" accept=".json,application/json" hidden onchange={(e) => { importFile(e.currentTarget.files?.[0]); e.currentTarget.value = '' }} /></label>
      <span class="spacer"></span>
      <button class="chip" class:on={filter === 'all'} onclick={() => (filter = 'all')}>{t('filter.all')}</button>
      <button class="chip" class:on={filter === 'person'} onclick={() => (filter = 'person')}>{t('filter.persons')}</button>
      <button class="chip" class:on={filter === 'company'} onclick={() => (filter = 'company')}>{t('filter.companies')}</button>
      <label class="hint arch"><input type="checkbox" bind:checked={showArchived} /> {t('fields.show_archived')}</label>
    </div>
    <table class="grid">
      <thead>
        <tr><th></th><th>{t('fields.label')}</th><th>{t('fields.type')}</th><th>{t('fields.applies_to')}</th>
          <th>{t('fields.access')}</th><th>vCard</th></tr>
      </thead>
      {#each groups as g (g.section?.id ?? 0)}
        {@const sid = g.section?.id ?? null}
      <tbody>
        <tr class="sec" ondragover={(e) => e.preventDefault()} ondrop={() => drop(sid)}>
          <th colspan="6">{g.section ? L(g.section.label) : t('core.section_other')}
            <span class="count">{t('sections.fields', { n: g.fields.filter((f) => !f.archived).length })}</span></th>
        </tr>
        {#if !g.fields.length}
          <tr class="empty" ondragover={(e) => e.preventDefault()} ondrop={() => drop(sid)}><td colspan="6">{t('sections.empty')}</td></tr>
        {/if}
        {#each g.fields.filter(isShown) as f (f.id)}
          <tr class="click" class:archived={f.archived} class:sel={editing !== 'new' && editing?.id === f.id}
              draggable="true" ondragstart={() => (dragId = f.id)} ondragover={(e) => e.preventDefault()}
              ondrop={() => drop(sid, f)} onclick={() => { pending = null; managing = false; editing = f }}>
            <td class="grip"><GripVertical size={14} /></td>
            <td><strong>{L(f.label)}</strong>{#if f.required} *{/if}
              {#if f.archived}<Archive size={12} />{/if}<div class="key">{f.key}</div></td>
            <td>{t(`type.${f.type}`)}{#if f.regex} <span class="badge" title={f.regex}>regex</span>{/if}</td>
            <td>{t(`applies.${f.applies_to}`)}</td>
            <td class="muted">{t(ACCESS[f.visible_to])} / {t(ACCESS[f.editable_by])}</td>
            <td class="muted">{f.vcard ? t(`vcard.${f.vcard}`) : ''}{f.vcard_label ? ` (${f.vcard_label})` : ''}</td>
          </tr>
        {/each}
      </tbody>
      {/each}
    </table>
  </div>
  {#if pending}
    <aside class="preview card">
      <header>
        <h2>{t('fields.import_title')}</h2>
        <button class="btn icon sm ghost" onclick={() => (pending = null)} aria-label={t('common.close')}><X size={15} /></button>
      </header>
      <p class="hint">{t('fields.import_intro')}</p>
      <ul>
        {#each pending.sections as r, i (i)}
          <li>
            <span class="badge" class:ok={r.status === 'new'} class:warn={r.status === 'changed'} class:err={r.status === 'invalid'}>{t(`fields.import_status.${r.status}`)}</span>
            <span class="muted">{t('fields.import_section')}:</span> <strong>{r.label ? L(r.label) : r.key}</strong> <span class="key">{r.key}</span>
            {#each Object.entries(r.errors) as [k, code]}<div class="error-text">{k}: {terr(code)}</div>{/each}
          </li>
        {/each}
        {#each pending.fields as r, i (i)}
          <li>
            <span class="badge" class:ok={r.status === 'new'} class:warn={r.status === 'changed'} class:err={r.status === 'invalid'}>{t(`fields.import_status.${r.status}`)}</span>
            <strong>{r.label ? L(r.label) : r.key}</strong> <span class="key">{r.key}</span>
            {#if r.changes?.length}<div class="muted">{r.changes.join(', ')}</div>{/if}
            {#each Object.entries(r.errors) as [k, code]}<div class="error-text">{k}: {terr(code)}</div>{/each}
          </li>
        {/each}
      </ul>
      <footer>
        <span class="spacer"></span>
        <button class="btn" onclick={() => (pending = null)}>{t('common.cancel')}</button>
        <button class="btn primary" onclick={applyImport}
                disabled={![...pending.fields, ...pending.sections].some((f) => f.status === 'new' || f.status === 'changed')}>{t('fields.import_apply')}</button>
      </footer>
    </aside>
  {:else if managing}
    <SectionManager {sections} {fields} onchanged={sectionsChanged} onclose={() => (managing = false)} />
  {:else if editing}
    {#key editing === 'new' ? 'new' : editing.id}
      <FieldEditor field={editing === 'new' ? null : editing} all={fields} {sections} {targets} onsaved={saved}
                   onsection={sectionsChanged} oncancel={() => (editing = null)} />
    {/key}
  {/if}
</div>

<style>
  .layout { display: grid; grid-template-columns: 1fr; gap: 20px; align-items: start; }
  .layout.has-editor { grid-template-columns: minmax(0, 1fr) 420px; }
  .toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
  .spacer { flex: 1; }
  .arch { display: inline-flex; align-items: center; gap: 6px; margin-left: 8px; }
  .grip { width: 24px; color: var(--faint); cursor: grab; }
  .key { font: 11px ui-monospace, monospace; color: var(--faint); }
  tr.archived td { opacity: 0.5; }
  tr.sec th { padding-top: 14px; text-align: left; font-size: 12px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--muted); background: none; }
  tr.sec .count { margin-left: 8px; font-weight: 400; text-transform: none; letter-spacing: 0; color: var(--faint); }
  tr.empty td { color: var(--faint); font-size: 12px; font-style: italic; }
  .preview { position: sticky; top: 0; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .preview header, .preview footer { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
  .preview h2 { font-size: 16px; }
  .preview p { margin: 0; }
  .preview ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; max-height: 60vh; overflow: auto; }
  .preview li .key { display: inline; }
  tr.sel td { background: var(--accent-soft) !important; }
  @media (max-width: 1100px) { .layout.has-editor { grid-template-columns: 1fr; } }
</style>
