<script lang="ts">
  import { Plus, X } from '@lucide/svelte'
  import Combobox from './Combobox.svelte'
  import { CORE, emptyGroup, family, isGroup, OPS, shape, type Cond, type Group, type Mode } from '../lib/advanced'
  import { L, i18n, t } from '../lib/i18n.svelte'
  import { store } from '../lib/store.svelte'

  /** the condition builder in the list's "advanced filter" popover; edits `adv` in place */
  let { adv = $bindable(), n }: { adv: Group; n: number } = $props()
  const DEPTH = 3 // levels of groups, the outermost included

  const core = $derived(Object.entries(CORE).map(([key, d]) => ({ key, type: d.type, label: t(`adv.f_${key.slice(1)}`) })))
  const custom = $derived(store.fields.filter((f) => !f.archived).map((f) => ({ key: f.key, type: f.type, label: L(f.label) })))
  const byKey = $derived(new Map([...core, ...custom].map((f) => [f.key, f])))

  // lazily derived: only computed once a condition needs them
  const users = $derived([...store.userNames].map(([value, label]) => ({ value, label, hint: value })))
  const recs = (kind: string) => store.index.filter((x) => x.rec.kind === kind).map((x) => ({ value: x.rec.uid, label: store.name(x.rec) }))
  const companies = $derived(recs('company'))
  const persons = $derived(recs('person'))
  function options(key: string) {
    if (key === '@kind') return [{ value: 'person', label: t('kind.person') }, { value: 'company', label: t('kind.company') }]
    if (key === '@company') return companies
    if (key === '@updated_by') return users
    const f = store.fields.find((f) => f.key === key)
    if (f?.type === 'contact') return persons
    return (f?.options ?? []).map((o) => ({ value: o.value, label: o[i18n.lang] || o.de || o.value,
                                            hint: f?.type === 'user' || f?.type === 'users' ? o.value : undefined }))
  }

  const blank = (): Cond => ({ field: '', op: '' })
  function setField(c: Cond, key: string) {
    const f = byKey.get(key)
    c.field = key
    c.op = f ? OPS[family(f.type)][0] : ''
    c.value = undefined
  }
  function setOp(c: Cond, op: string) {
    if (shape(op) !== shape(c.op)) c.value = undefined
    c.op = op
  }
  const at = (c: Cond, i: number) => (Array.isArray(c.value) ? c.value[i] : '') ?? ''
  const setAt = (c: Cond, i: number, v: string) => (c.value = i ? [at(c, 0), v] : [v, at(c, 1)])
</script>

<div class="head">
  <strong>{t('adv.title')}</strong>
  <span class="muted tabular" aria-live="polite">{t('list.count', { n })}</span>
  {#if adv.items.length}<button class="btn sm ghost" onclick={() => (adv = emptyGroup())}>{t('adv.reset')}</button>{/if}
</div>
{@render group(adv, 0)}

{#snippet group(g: Group, depth: number, remove?: () => void)}
  <div class="group" class:nested={depth > 0} role="group" aria-label={t(`adv.mode_${g.mode}`)}>
    <div class="ghead">
      <select class="select" aria-label={t('adv.mode')} value={g.mode} onchange={(e) => (g.mode = e.currentTarget.value as Mode)}>
        {#each ['all', 'any', 'none'] as m (m)}<option value={m}>{t(`adv.mode_${m}`)}</option>{/each}
      </select>
      {#if remove}
        <button class="btn icon sm ghost" title={t('adv.remove_group')} aria-label={t('adv.remove_group')} onclick={remove}><X size={14} /></button>
      {/if}
    </div>
    {#each g.items as item, i (item)}
      {#if isGroup(item)}
        {@render group(item, depth + 1, () => g.items.splice(i, 1))}
      {:else}
        {@render cond(item, () => g.items.splice(i, 1))}
      {/if}
    {:else}
      <p class="hint none">{t('adv.none')}</p>
    {/each}
    <div class="gfoot">
      <button class="btn sm ghost" onclick={() => g.items.push(blank())}><Plus size={14} />{t('adv.add_cond')}</button>
      {#if depth < DEPTH - 1}
        <button class="btn sm ghost" onclick={() => g.items.push({ mode: 'all', items: [blank()] })}><Plus size={14} />{t('adv.add_group')}</button>
      {/if}
    </div>
  </div>
{/snippet}

{#snippet cond(c: Cond, remove: () => void)}
  {@const f = byKey.get(c.field)}
  {@const sh = shape(c.op)}
  <div class="cond">
    <select class="select" aria-label={t('adv.field')} value={c.field} onchange={(e) => setField(c, e.currentTarget.value)}>
      <option value="" disabled>{t('adv.pick_field')}</option>
      {#if c.field && !f}<option value={c.field} disabled>{t('adv.unknown')}</option>{/if}
      <optgroup label={t('adv.core')}>
        {#each core as x (x.key)}<option value={x.key}>{x.label}</option>{/each}
      </optgroup>
      {#if custom.length}
        <optgroup label={t('adv.fields')}>
          {#each custom as x (x.key)}<option value={x.key}>{x.label}</option>{/each}
        </optgroup>
      {/if}
    </select>
    {#if f}
      <select class="select" aria-label={t('adv.op')} value={c.op} onchange={(e) => setOp(c, e.currentTarget.value)}>
        {#each OPS[family(f.type)] as op (op)}<option value={op}>{t(`adv.op_${op}`)}</option>{/each}
      </select>
    {/if}
    <button class="btn icon sm ghost x" title={t('adv.remove')} aria-label={t('adv.remove')} onclick={remove}><X size={14} /></button>
    {#if f && sh !== 'none'}
      {@const type = f.type === 'date' ? 'date' : 'text'}
      {@const mode = f.type === 'integer' || f.type === 'decimal' ? 'decimal' : undefined}
      <div class="val">
        {#if sh === 'list'}
          <Combobox multiple label={t('adv.value')} value={Array.isArray(c.value) ? c.value : []} options={options(f.key)}
                    create={f.type === 'contact' || f.key === '@updated_by'} createLabel="combo.use_text" onchange={(v) => (c.value = v)} />
        {:else if sh === 'days'}
          <input class="input tabular" type="number" min="0" inputmode="numeric" aria-label={t('adv.days')}
                 value={c.value ?? ''} oninput={(e) => (c.value = e.currentTarget.value)} />
          <span class="muted">{t('adv.days')}</span>
        {:else if sh === 'range'}
          <input class="input" {type} inputmode={mode} aria-label={t('adv.from')} placeholder={t('adv.from')}
                 value={at(c, 0)} oninput={(e) => setAt(c, 0, e.currentTarget.value)} />
          <span class="muted">–</span>
          <input class="input" {type} inputmode={mode} aria-label={t('adv.to')} placeholder={t('adv.to')}
                 value={at(c, 1)} oninput={(e) => setAt(c, 1, e.currentTarget.value)} />
        {:else}
          <input class="input" {type} inputmode={mode} aria-label={t('adv.value')} class:tabular={mode || f.type === 'phone'}
                 value={c.value ?? ''} oninput={(e) => (c.value = e.currentTarget.value)} />
        {/if}
      </div>
    {/if}
  </div>
{/snippet}

<style>
  .head { display: flex; align-items: center; gap: 8px; padding: 2px 2px 10px; }
  .head .muted { margin-right: auto; font-size: 12px; }
  .group { display: grid; gap: 8px; }
  .nested { padding: 8px 0 4px 10px; border-left: 2px solid var(--border-strong); }
  .ghead { display: flex; align-items: center; gap: 6px; }
  .ghead .select { width: auto; max-width: 100%; height: 28px; font-size: 13px; }
  .cond { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px; border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--panel-2); }
  .cond > .select { flex: 1 1 150px; min-width: 0; }
  .cond .x { margin-left: auto; align-self: center; }
  .val { flex: 1 1 100%; display: flex; align-items: center; gap: 6px; min-width: 0; }
  .val > :global(*) { flex: 1; min-width: 0; }
  .val > span { flex: none; }
  .gfoot { display: flex; flex-wrap: wrap; gap: 4px; }
  .none { margin: 0; }
</style>
