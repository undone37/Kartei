<script lang="ts">
  import { ArrowDown, ArrowUp, Plus, Trash2, X } from '@lucide/svelte'
  import { untrack } from 'svelte'
  import Combobox from '../components/Combobox.svelte'
  import { ApiError, del, patch, post } from '../lib/api'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { Field, FieldType, Section } from '../lib/types'

  interface Props {
    field: Field | null; all: Field[]; sections: Section[]; targets: string[]; onsaved: () => void; oncancel: () => void
    /** a section was created from the picker */
    onsection: () => void
  }
  let { field, all, sections, targets, onsaved, oncancel, onsection }: Props = $props()

  const TYPES: FieldType[] = ['text', 'longtext', 'integer', 'decimal', 'select', 'multiselect', 'phone', 'email', 'url', 'date', 'checkbox', 'user', 'users', 'contact']
  const initial = untrack(() => field) // editor is keyed per field by its parent
  let d = $state(initial ? structuredClone($state.snapshot(initial)) : {
    label: { de: '', en: '' }, applies_to: 'person', type: 'text', options: [], open_options: false, quick_filter: false, required: false, min: null, max: null,
    decimals: 2, section: null, visible_to: 'read', editable_by: 'maintainer', searchable: true,
    vcard: '', vcard_label: '', copy_from: null, regex: '', help: { de: '', en: '' }, import_aliases: [],
  } as unknown as Field)
  let errors = $state<Record<string, string>>({})

  const supportsRegex = $derived(['text', 'longtext', 'phone', 'email', 'url'].includes(d.type))
  let sample = $state('')
  const compiled = $derived.by(() => {
    if (!d.regex) return null
    try { return new RegExp(`^(?:${d.regex})$`, 'u') } catch { return undefined }
  })
  const PRESETS = [
    { label: t('fields.preset_zip_de'), re: String.raw`\d{5}` },
    { label: t('fields.preset_zip_intl'), re: String.raw`[A-Za-z0-9][A-Za-z0-9 -]{1,9}` },
    { label: 'K-12345', re: String.raw`K-\d{5}` },
    { label: 'IBAN (DE)', re: String.raw`DE\d{2}( ?\d{4}){4} ?\d{2}` },
    { label: t('fields.preset_domain'), re: String.raw`[^@\s]+@firma\.de` },
    { label: 'A–Z', re: String.raw`[A-ZÄÖÜ]+` },
  ]
  const isSelect = $derived(d.type === 'select' || d.type === 'multiselect')
  const isNumber = $derived(d.type === 'integer' || d.type === 'decimal')
  const sectionOptions = $derived(sections.map((s) => ({ value: String(s.id), label: L(s.label), hint: s.key })))
  const companyFields = $derived(all.filter((f) => !f.archived && (f.applies_to === 'company' || f.applies_to === 'both')))
  const targetOptions = $derived(targets.map((v) => ({ value: v, label: t(`vcard.${v}`) })))
  const needsLabel = $derived(['email_custom', 'tel_custom', 'tel_fax_custom', 'related_custom', 'note_labeled'].includes(d.vcard))

  /** an existing section, none ("Other"), or typed text: create that section */
  async function pickSection(v: string | null) {
    if (v == null || sections.some((s) => String(s.id) === v)) {
      d.section = v == null ? null : Number(v)
      return
    }
    try {
      const s = await post<Section>('/api/admin/sections', { label: { de: v, en: v } })
      d.section = s.id
      onsection()
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  function moveOption(i: number, delta: number) {
    const o = d.options
    ;[o[i], o[i + delta]] = [o[i + delta], o[i]]
  }

  async function save() {
    errors = {}
    try {
      if (field) await patch(`/api/admin/fields/${field.id}`, d)
      else await post('/api/admin/fields', d)
      toast(t('fields.saved'))
      onsaved()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
      else toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  async function setArchived(archived: boolean) {
    if (archived && !(await confirmDialog({ title: t('fields.archive_title', { name: L(field!.label) }), message: t('fields.archive_text'),
                                            confirmLabel: t('fields.archive') }))) return
    await patch(`/api/admin/fields/${field!.id}`, { archived })
    onsaved()
  }

  async function remove() {
    const ok = await confirmDialog({ title: t('fields.delete_title', { name: L(field!.label) }), message: t('fields.delete_text'),
                                     confirmLabel: t('confirm.purge_ok'), danger: true })
    if (!ok) return
    try {
      await del(`/api/admin/fields/${field!.id}`)
      onsaved()
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }
</script>

<aside class="editor card">
  <header>
    <h2>{field ? L(field.label) : t('fields.new')}</h2>
    <button class="btn icon sm ghost" onclick={oncancel} aria-label={t('common.close')}><X size={15} /></button>
  </header>

  <div class="row2">
    <div><label class="label" for="lde">{t('fields.label')} (DE)</label><input id="lde" class="input" class:invalid={errors.label} bind:value={d.label.de} /></div>
    <div><label class="label" for="len">{t('fields.label')} (EN)</label><input id="len" class="input" class:invalid={errors.label} bind:value={d.label.en} /></div>
  </div>
  {#if errors.label}<div class="error-text">{terr(errors.label)}</div>{/if}

  <div class="row2">
    <div><label class="label" for="hde">{t('fields.help')} (DE)</label><textarea id="hde" class="input" rows="2" bind:value={d.help.de}></textarea></div>
    <div><label class="label" for="hen">{t('fields.help')} (EN)</label><textarea id="hen" class="input" rows="2" bind:value={d.help.en}></textarea></div>
  </div>
  <p class="hint">{t('fields.help_hint')}</p>

  <div class="row2">
    <div>
      <label class="label" for="type">{t('fields.type')}</label>
      <select id="type" class="select" bind:value={d.type}>
        {#each TYPES as ty}<option value={ty}>{t(`type.${ty}`)}</option>{/each}
      </select>
      {#if errors.type}<div class="error-text">{terr(errors.type)}</div>{/if}
    </div>
    <div>
      <label class="label" for="applies">{t('fields.applies_to')}</label>
      <select id="applies" class="select" bind:value={d.applies_to}>
        {#each ['person', 'company', 'both'] as a}<option value={a}>{t(`applies.${a}`)}</option>{/each}
      </select>
    </div>
  </div>

  {#if isNumber}
    <div class="row3">
      <div><label class="label" for="min">{t('fields.min')}</label><input id="min" class="input" inputmode="decimal" bind:value={d.min} /></div>
      <div><label class="label" for="max">{t('fields.max')}</label><input id="max" class="input" inputmode="decimal" bind:value={d.max} /></div>
      {#if d.type === 'decimal'}
        <div><label class="label" for="dec">{t('fields.decimals')}</label><input id="dec" class="input" type="number" min="0" max="6" bind:value={d.decimals} /></div>
      {/if}
    </div>
    {#if errors.min}<div class="error-text">{terr(errors.min)}</div>{/if}
  {/if}

  {#if isSelect}
    <div class="opts">
      <span class="label">{t('fields.options')}</span>
      {#each d.options as o, i}
        <div class="opt">
          <input class="input" placeholder={t('fields.value')} bind:value={o.value} />
          <input class="input" placeholder="DE" bind:value={o.de} />
          <input class="input" placeholder="EN" bind:value={o.en} />
          <button class="btn icon sm ghost" disabled={i === 0} onclick={() => moveOption(i, -1)} aria-label={t('common.up')}><ArrowUp size={13} /></button>
          <button class="btn icon sm ghost" disabled={i === d.options.length - 1} onclick={() => moveOption(i, 1)} aria-label={t('common.down')}><ArrowDown size={13} /></button>
          <button class="btn icon sm ghost" onclick={() => d.options.splice(i, 1)} aria-label={t('common.remove')}><Trash2 size={13} /></button>
        </div>
      {/each}
      <button class="btn sm" onclick={() => d.options.push({ value: '', de: '', en: '' })}><Plus size={13} />{t('fields.add_option')}</button>
      <label class="open"><input type="checkbox" bind:checked={d.open_options} /> {t('fields.open_options')}</label>
      {#if errors.options}<div class="error-text">{terr(errors.options)}</div>{/if}
    </div>
  {/if}

  {#if d.type === 'contact'}
    <label class="open"><input type="checkbox" bind:checked={d.open_options} /> {t('fields.free_text')}</label>
  {/if}

    {#if ['select', 'multiselect', 'user', 'users'].includes(d.type)}
    <label class="open"><input type="checkbox" bind:checked={d.quick_filter} /> {t('fields.quick_filter')}</label>
  {/if}

  {#if supportsRegex}
    <div class="regex">
      <label class="label" for="re">{t('fields.regex')}</label>
      <input id="re" class="input mono" class:invalid={errors.regex || compiled === undefined} bind:value={d.regex}
             placeholder={String.raw`\d{5}`} spellcheck="false" autocomplete="off" />
      {#if errors.regex}<div class="error-text">{terr(errors.regex)}</div>
      {:else if compiled === undefined}<div class="error-text">{terr('invalid_regex')}</div>{/if}
      <div class="presets">
        {#each PRESETS as p}<button type="button" class="chip" onclick={() => (d.regex = p.re)}>{p.label}</button>{/each}
      </div>
      {#if d.regex && compiled}
        <div class="tester">
          <input class="input" bind:value={sample} placeholder={t('fields.regex_test')} />
          {#if sample}
            <span class="badge" class:ok={compiled.test(sample.trim())} class:err={!compiled.test(sample.trim())}>
              {compiled.test(sample.trim()) ? t('fields.regex_ok') : t('fields.regex_fail')}
            </span>
          {/if}
        </div>
      {/if}
      <p class="hint">{t('fields.regex_hint')}</p>
    </div>
  {/if}

  <div>
    <label class="label" for="section">{t('fields.section')}</label>
    <Combobox id="section" options={sectionOptions} value={d.section == null ? null : String(d.section)} create
              createLabel="fields.section_create" placeholder={t('fields.section_none')} invalid={!!errors.section}
              onchange={pickSection} />
    {#if errors.section}<div class="error-text">{terr(errors.section)}</div>{/if}
  </div>

  <div class="row2">
    <div>
      <label class="label" for="vis">{t('fields.visible_to')}</label>
      <select id="vis" class="select" bind:value={d.visible_to}>
        <option value="read">{t('access.all')}</option>
        <option value="maintainer">{t('access.maintainer')}</option>
        <option value="admin">{t('access.admin')}</option>
      </select>
    </div>
    <div>
      <label class="label" for="edit">{t('fields.editable_by')}</label>
      <select id="edit" class="select" bind:value={d.editable_by}>
        <option value="maintainer">{t('access.maintainer')}</option>
        <option value="admin">{t('access.admin')}</option>
      </select>
    </div>
  </div>
  <p class="hint">{t('fields.access_hint')}</p>

  <div class="checks">
    <label><input type="checkbox" bind:checked={d.required} /> {t('fields.required')}</label>
    <label><input type="checkbox" bind:checked={d.searchable} /> {t('fields.searchable')}</label>
  </div>

  <div class="row2">
    <div>
      <label class="label" for="vcard">{t('fields.vcard')}</label>
      <Combobox id="vcard" options={targetOptions} value={d.vcard || null} placeholder={t('fields.vcard_none')}
                onchange={(v) => (d.vcard = v ?? '')} />
    </div>
    {#if needsLabel}
      <div><label class="label" for="vlabel">{t('fields.vcard_label')}</label><input id="vlabel" class="input" bind:value={d.vcard_label} placeholder={d.label.de} /></div>
    {/if}
  </div>

  <div>
    <label class="label" for="aliases">{t('fields.import_aliases')}</label>
    <input id="aliases" class="input" value={d.import_aliases.join(', ')} placeholder="BusinessTelephoneNumber, Tel."
           onchange={(e) => (d.import_aliases = e.currentTarget.value.split(',').map((a) => a.trim()).filter(Boolean))} />
    <p class="hint">{t('fields.import_aliases_hint')}</p>
  </div>

  {#if d.applies_to !== 'company'}
    <div>
      <label class="label" for="copy">{t('fields.copy_from')}</label>
      <select id="copy" class="select" bind:value={d.copy_from}>
        <option value={null}>—</option>
        {#each companyFields as f (f.id)}<option value={f.id}>{L(f.label)}</option>{/each}
      </select>
      <p class="hint">{t('fields.copy_hint')}</p>
      {#if errors.copy_from}<div class="error-text">{terr(errors.copy_from)}</div>{/if}
    </div>
  {/if}

  <footer>
    {#if field}
      {#if field.archived}
        <button class="btn sm" onclick={() => setArchived(false)}>{t('fields.unarchive')}</button>
        <button class="btn sm ghost danger" onclick={remove}>{t('common.delete')}</button>
      {:else}
        <button class="btn sm" onclick={() => setArchived(true)} title={t('fields.archive_hint')}>{t('fields.archive')}</button>
      {/if}
    {/if}
    <span class="spacer"></span>
    <button class="btn" onclick={oncancel}>{t('common.cancel')}</button>
    <button class="btn primary" onclick={save}>{t('common.save')}</button>
  </footer>
</aside>

<style>
  .editor { position: sticky; top: 0; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  header { display: flex; align-items: center; justify-content: space-between; }
  h2 { font-size: 16px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .row3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
  .opts { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
  .open { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .opt { display: grid; grid-template-columns: 1fr 1fr 1fr auto auto auto; gap: 4px; width: 100%; }
  .checks { display: flex; gap: 18px; }
  .mono { font: 12px ui-monospace, monospace; }
  .regex { display: flex; flex-direction: column; gap: 6px; }
  .regex .hint { margin: 0; }
  .presets { display: flex; gap: 4px; flex-wrap: wrap; }
  .presets .chip { height: 22px; font-size: 12px; padding: 0 8px; }
  .tester { display: flex; gap: 8px; align-items: center; }
  .checks label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
  .hint { margin: -6px 0 0; }
  footer { display: flex; gap: 6px; align-items: center; border-top: 1px solid var(--border); padding-top: 12px; }
  .spacer { flex: 1; }
</style>
