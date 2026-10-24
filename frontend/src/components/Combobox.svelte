<script lang="ts">
  import { X, ChevronDown, Check, Plus } from '@lucide/svelte'
  import { fold } from '../lib/search'
  import { t } from '../lib/i18n.svelte'

  interface Opt { value: string; label: string; hint?: string; isNew?: boolean }
  interface Props {
    options: Opt[]
    value: string | string[] | null
    multiple?: boolean
    placeholder?: string
    invalid?: boolean
    id?: string
    /** accessible name when there is no <label for={id}> */
    label?: string
    /** offer the typed text as a new option; createLabel: i18n key of that entry, gets {v} */
    create?: boolean
    createLabel?: string
    onchange: (value: any) => void
  }
  let { options, value, multiple = false, placeholder = '', invalid = false, id, label, create = false, createLabel = 'combo.add', onchange }: Props = $props()

  let query = $state('')
  let open = $state(false)
  let control: HTMLDivElement | undefined = $state()
  // the list is positioned against the window (fixed), not its container: inside popovers or scrolled panels an
  // absolute list would make the container scroll or get clipped. Opens upwards when there's no room below.
  let place = $state('')
  function position() {
    if (!control) return
    const r = control.getBoundingClientRect()
    const below = innerHeight - r.bottom - 8, above = r.top - 8
    const up = below < 180 && above > below
    const max = Math.min(260, Math.max(120, up ? above - 4 : below - 4))
    place = `left:${r.left}px;width:${r.width}px;max-height:${max}px;` +
      (up ? `bottom:${innerHeight - r.top + 4}px` : `top:${r.bottom + 4}px`)
  }
  $effect(() => {
    if (!open) return
    position()
    addEventListener('scroll', position, true) // any scrolling ancestor
    addEventListener('resize', position)
    return () => { removeEventListener('scroll', position, true); removeEventListener('resize', position) }
  })
  let active = $state(0)
  let input: HTMLInputElement
  let listEl: HTMLUListElement | undefined = $state()
  const listId = `cb-${Math.random().toString(36).slice(2, 9)}`

  const selected = $derived(multiple ? ((value as string[]) ?? []) : value ? [value as string] : [])
  const labelOf = (v: string) => options.find((o) => o.value === v)?.label ?? v
  const filtered = $derived.by(() => {
    const q = fold(query.trim())
    const list = q ? options.filter((o) => fold(o.label + ' ' + (o.hint ?? '')).includes(q)) : options
    return list.slice(0, 100) // ponytail: render cap keeps huge lists (companies) instant; typing narrows further
  })

  const typed = $derived(query.trim().replace(/\s+/g, ' '))
  const items = $derived.by(() => {
    const q = fold(typed)
    const exists = (v: string) => fold(v) === q
    if (!create || !q || options.some((o) => exists(o.value) || exists(o.label)) || selected.some(exists)) return filtered
    return [...filtered, { value: typed, label: typed, isNew: true }]
  })

  $effect(() => {
    void items
    active = 0
  })

  function pick(o: Opt) {
    if (multiple) {
      const cur = selected
      onchange(cur.includes(o.value) ? cur.filter((v) => v !== o.value) : [...cur, o.value])
      query = ''
      input.focus()
    } else {
      onchange(o.value)
      query = ''
      open = false
    }
  }

  function remove(v: string) {
    onchange(multiple ? selected.filter((x) => x !== v) : null)
  }

  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      open = true
      active = Math.min(active + 1, items.length - 1)
      scrollActive()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      active = Math.max(active - 1, 0)
      scrollActive()
    } else if (e.key === 'Enter' && open && items[active]) {
      e.preventDefault()
      pick(items[active])
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation()
      open = false
    } else if (e.key === 'Backspace' && !query && selected.length && multiple) {
      remove(selected[selected.length - 1])
    }
  }

  function scrollActive() {
    queueMicrotask(() => listEl?.children[active]?.scrollIntoView({ block: 'nearest' }))
  }
</script>

<div class="combo" class:open class:invalid>
  <div class="control" bind:this={control} onclick={() => input.focus()} role="presentation">
    {#if multiple}
      {#each selected as v (v)}
        <span class="tag">{labelOf(v)}
          <button type="button" class="x" aria-label={t('common.remove')} onclick={(e) => { e.stopPropagation(); remove(v) }}><X size={12} /></button>
        </span>
      {/each}
    {:else if selected.length && !query}
      <span class="single">{labelOf(selected[0])}</span>
    {/if}
    <input
      bind:this={input}
      {id}
      aria-label={label}
      bind:value={query}
      placeholder={selected.length ? '' : placeholder}
      role="combobox"
      aria-expanded={open}
      aria-controls={listId}
      aria-autocomplete="list"
      autocomplete="off"
      onfocus={() => (open = true)}
      onblur={() => setTimeout(() => (open = false), 120)}
      oninput={() => (open = true)}
      onkeydown={key}
    />
    {#if !multiple && selected.length}
      <button type="button" class="x clear" aria-label={t('common.clear')} onclick={(e) => { e.stopPropagation(); remove(selected[0]) }}><X size={14} /></button>
    {:else}
      <ChevronDown size={14} class="chev" />
    {/if}
  </div>
  {#if open}
    <ul class="menu" id={listId} role="listbox" bind:this={listEl} aria-multiselectable={multiple} style={place}>
      {#each items as o, i (o.isNew ? '\0new' : o.value)}
        <li role="option" aria-selected={selected.includes(o.value)} class:active={i === active} class:new={o.isNew}
            onmousedown={(e) => { e.preventDefault(); pick(o) }} onmouseenter={() => (active = i)}>
          <span class="check">{#if o.isNew}<Plus size={14} />{:else if selected.includes(o.value)}<Check size={14} />{/if}</span>
          <span class="lbl">{o.isNew ? t(createLabel, { v: o.label }) : o.label}</span>
          {#if o.hint}<span class="hint">{o.hint}</span>{/if}
        </li>
      {:else}
        <li class="empty">{t('common.no_matches')}</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .combo { position: relative; }
  .control {
    display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-height: 34px; padding: 3px 8px;
    border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--panel); cursor: text;
    transition: border-color 0.12s, box-shadow 0.12s;
  }
  .open .control { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 20%, transparent); }
  .invalid .control { border-color: var(--danger); }
  input { flex: 1; min-width: 60px; border: 0; outline: 0; background: transparent; height: 26px; padding: 0 2px; }
  .single { position: absolute; left: 10px; pointer-events: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: calc(100% - 40px); }
  .x { display: inline-flex; border: 0; background: none; padding: 0; cursor: pointer; color: inherit; opacity: 0.6; }
  .x:hover { opacity: 1; }
  .clear { margin-left: auto; }
  .control :global(.chev) { margin-left: auto; color: var(--faint); }
  .menu {
    position: fixed; z-index: 1000; max-height: 260px; overflow: auto;
    margin: 0; padding: 4px; list-style: none; background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); box-shadow: var(--shadow-lg);
  }
  li { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
  li.active { background: var(--panel-2); }
  li .check { width: 14px; color: var(--accent); display: inline-flex; }
  li .lbl { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  li .hint { color: var(--muted); font-size: 12px; }
  li.empty { color: var(--muted); cursor: default; }
  li.new { color: var(--accent-text); }
</style>
