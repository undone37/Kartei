<script lang="ts">
  import Combobox from './Combobox.svelte'
  import { fmt, isMulti, isSingle } from '../lib/format'
  import { store } from '../lib/store.svelte'
  import { L, i18n, terr } from '../lib/i18n.svelte'
  import type { Field } from '../lib/types'
  import { validate } from '../lib/validate'

  interface Props { field: Field; value: any; error?: string; disabled?: boolean; company?: string | null; onchange: (v: any) => void }
  /** company: uid of the record's company (or the company itself); contact fields offer its persons */
  let { field, value, error, disabled = false, company = null, onchange }: Props = $props()

  const id = $derived(`f-${field.key}`)
  const help = $derived(L(field.help))
  // live validation (same rules as the server): shown once the field was left or typing paused,
  // so a half-typed email isn't flagged after the first letter
  let touched = $state(false)
  let paused = $state(false)
  let timer = 0
  function typed() {
    paused = false
    clearTimeout(timer)
    timer = setTimeout(() => (paused = true), 700)
  }
  const live = $derived(touched || paused ? validate(field, value) : null)
  const shownError = $derived(error || live)
  const options = $derived.by(() => {
    // user fields: admins and inactive users ("pick": false) are not offered, but a value already set stays shown
    const set = Array.isArray(value) ? value : [value]
    if (field.type !== 'contact')
      return field.options.filter((o) => o.pick !== false || set.includes(o.value)).map((o) => ({
        value: o.value, label: o[i18n.lang] || o.de || o.value,
        hint: field.type === 'user' || field.type === 'users' ? o.value : undefined, // username: shown and searchable
      }))
    const persons = company ? store.persons.get(company) ?? [] : []
    const linked = store.byUid.get(value)
    return [...persons, ...(linked && !persons.includes(linked) ? [linked] : [])]
      .map((p) => ({ value: p.uid, label: store.name(p), hint: String(p.data.job_title ?? '') }))
  })
  // decimals are stored as "1234.50"; show the locale's separator while editing
  const sep = $derived(i18n.lang === 'de' ? ',' : '.')
  const shown = $derived(field.type === 'decimal' && value != null ? String(value).replace('.', sep) : value ?? '')

  function autosize(el: HTMLTextAreaElement) {
    const fit = () => { el.style.height = 'auto'; el.style.height = el.scrollHeight + 2 + 'px' }
    fit()
    el.addEventListener('input', fit)
  }
</script>

<div class="field" class:wide={field.type === 'longtext' || isMulti(field)}>
  {#if field.type === 'checkbox'}
    <label class="check">
      <input type="checkbox" checked={!!value} {disabled} onchange={(e) => onchange(e.currentTarget.checked)} />
      <span>{L(field.label)}{#if field.required} *{/if}</span>
    </label>
  {:else}
    <label class="label" for={id}>{L(field.label)}{#if field.required} *{/if}</label>
    {#if disabled}
      <div class="input readonly">{fmt(field, value)}</div>
    {:else if field.type === 'longtext'}
      <textarea {id} class="input" class:invalid={!!shownError} value={value ?? ''} use:autosize
                aria-describedby={help ? `${id}-help` : undefined}
                onblur={() => (touched = true)} oninput={(e) => { onchange(e.currentTarget.value); typed() }}></textarea>
    {:else if field.type === 'contact'}
      <Combobox {id} {options} value={value ?? null} create={field.open_options} createLabel="combo.use_text" invalid={!!error} onchange={onchange} />
    {:else if isSingle(field)}
      <Combobox {id} {options} create={field.open_options} value={value ?? null} invalid={!!error} onchange={onchange} />
    {:else if isMulti(field)}
      <Combobox {id} {options} create={field.open_options} value={Array.isArray(value) ? value : value ? [value] : []} multiple invalid={!!error} onchange={onchange} />
    {:else}
      <input
        {id}
        class="input"
        class:invalid={!!shownError}
        aria-describedby={help ? `${id}-help` : undefined}
        onblur={() => (touched = true)}
        class:tabular={field.type === 'integer' || field.type === 'decimal' || field.type === 'phone'}
        type={field.type === 'email' ? 'email' : field.type === 'url' ? 'url' : field.type === 'date' ? 'date' : field.type === 'phone' ? 'tel' : 'text'}
        inputmode={field.type === 'integer' ? 'numeric' : field.type === 'decimal' ? 'decimal' : undefined}
        value={shown}
        aria-invalid={!!shownError}
        oninput={(e) => { onchange(e.currentTarget.value); typed() }}
      />
    {/if}
  {/if}
  {#if shownError}<div class="error-text" role="alert">{terr(shownError)}</div>{/if}
  {#if help}<div class="hint help" id="{id}-help">{help}</div>{/if}
</div>

<style>
  .field { min-width: 0; }
  .wide { grid-column: 1 / -1; }
  .check { display: flex; align-items: center; gap: 8px; height: 34px; margin-top: 18px; cursor: pointer; }
  .help { margin-top: 3px; white-space: pre-line; }
  .readonly { display: flex; align-items: center; background: var(--panel-2); color: var(--muted); }
</style>
