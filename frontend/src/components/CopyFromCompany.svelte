<script lang="ts">
  import { untrack } from 'svelte'
  import { CopyPlus, Undo2, X } from '@lucide/svelte'
  import { store } from '../lib/store.svelte'
  import { fmt, isEmpty } from '../lib/format'
  import { L, t } from '../lib/i18n.svelte'
  import type { Field, Rec } from '../lib/types'

  interface Props { company: Rec; data: Record<string, any>; editable: Field[]; onapply: (patch: Record<string, any>) => void }
  let { company, data, editable, onapply }: Props = $props()

  const byId = $derived(new Map(store.fields.map((f) => [f.id, f])))
  // person fields that have a company counterpart and where the company has a different value
  const pairs = $derived(
    editable
      .filter((f) => f.copy_from != null)
      .map((f) => ({ field: f, src: byId.get(f.copy_from!)! }))
      .filter(({ field, src }) => src && !isEmpty(company.data[src.key]) &&
        JSON.stringify(company.data[src.key]) !== JSON.stringify(data[field.key])),
  )
  let unchecked = $state(new Set<string>())
  let dismissed = $state(false)
  let undo = $state<Record<string, any> | null>(null)

  // reset when the company changes
  $effect(() => {
    void company.uid
    untrack(() => {
      dismissed = false
      undo = null
      unchecked = new Set(pairs.filter(({ field }) => !isEmpty(data[field.key])).map(({ field }) => field.key))
    })
  })

  function apply() {
    const chosen = pairs.filter(({ field }) => !unchecked.has(field.key))
    undo = Object.fromEntries(chosen.map(({ field }) => [field.key, data[field.key] ?? null]))
    onapply(Object.fromEntries(chosen.map(({ field, src }) => [field.key, structuredClone($state.snapshot(company.data[src.key]))])))
  }

  function toggle(key: string) {
    const s = new Set(unchecked)
    s.has(key) ? s.delete(key) : s.add(key)
    unchecked = s
  }
</script>

{#if undo}
  <div class="panel done">
    <span>{t('copy.applied', { company: company.name })}</span>
    <button type="button" class="btn sm ghost" onclick={() => { onapply(undo!); undo = null }}><Undo2 size={14} />{t('common.undo')}</button>
  </div>
{:else if pairs.length && !dismissed}
  <div class="panel">
    <div class="head">
      <CopyPlus size={16} />
      <strong>{t('copy.title', { company: company.name })}</strong>
      <button type="button" class="btn icon sm ghost" aria-label={t('common.close')} onclick={() => (dismissed = true)}><X size={14} /></button>
    </div>
    <div class="list">
      {#each pairs as { field, src } (field.key)}
        <label class="item">
          <input type="checkbox" checked={!unchecked.has(field.key)} onchange={() => toggle(field.key)} />
          <span class="lbl">{L(field.label)}</span>
          <span class="val">{fmt(src, company.data[src.key])}</span>
          {#if !isEmpty(data[field.key])}<span class="badge warn">{t('copy.overwrites')}</span>{/if}
        </label>
      {/each}
    </div>
    <div class="actions">
      <button type="button" class="btn sm primary" disabled={unchecked.size === pairs.length} onclick={apply}>
        {t('copy.apply', { n: pairs.length - unchecked.size })}
      </button>
    </div>
  </div>
{/if}

<style>
  .panel { border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border)); background: var(--accent-soft);
    border-radius: 10px; padding: 10px 12px; margin-bottom: 16px; }
  .panel.done { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--accent-text); }
  .head { display: flex; align-items: center; gap: 8px; color: var(--accent-text); }
  .head strong { flex: 1; font-weight: 600; }
  .list { display: grid; gap: 2px; margin: 8px 0; }
  .item { display: grid; grid-template-columns: 16px minmax(120px, 0.6fr) 1fr auto; gap: 10px; align-items: center;
    padding: 4px 6px; border-radius: 6px; cursor: pointer; }
  .item:hover { background: color-mix(in srgb, var(--panel) 60%, transparent); }
  .lbl { color: var(--muted); font-size: 13px; }
  .val { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .actions { display: flex; justify-content: flex-end; }
</style>
