<script lang="ts">
  import { X } from '@lucide/svelte'
  import FieldInput from './FieldInput.svelte'
  import { ApiError, post } from '../lib/api'
  import { isEmpty, isMulti } from '../lib/format'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { store } from '../lib/store.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import { personsAlong } from '../lib/deletion'
  import { RANK, type Rec } from '../lib/types'

  interface Props { picked: Set<string>; all: string[]; onpick: (s: Set<string>) => void; onclose: () => void }
  let { picked, all, onpick, onclose }: Props = $props()

  type Op = 'set' | 'clear' | 'add' | 'remove' | 'responsible' | 'delete'
  interface BulkError { uid: string; name: string; fields: Record<string, string> }

  // contact fields pick persons of one company, which makes no sense across a selection
  const editable = $derived(store.fields.filter((f) => !f.archived && f.type !== 'contact' && RANK[f.editable_by] <= store.rank))
  const responsible = $derived(editable.find((f) => f.type === 'user'))
  const ops = $derived<Op[]>(['set', 'clear', ...(editable.some(isMulti) ? ['add', 'remove'] as Op[] : []),
                              ...(responsible ? ['responsible'] as Op[] : []), 'delete'])
  let op = $state<Op>('set')
  let key = $state('')
  let value = $state<any>(null)
  let busy = $state(false)

  const choices = $derived(op === 'add' || op === 'remove' ? editable.filter(isMulti) : editable)
  const field = $derived(op === 'responsible' ? responsible : op === 'delete' ? undefined : choices.find((f) => f.key === key) ?? choices[0])
  const ready = $derived(op === 'delete' || op === 'clear' || !isEmpty(value))

  const fieldKey = $derived(field?.key) // fields are replaced on every sync; only a different field resets the value
  $effect(() => {
    void fieldKey
    void op
    value = field?.type === 'checkbox' ? false : null
  })

  const label = (k: string) => {
    const f = store.fields.find((f) => f.key === k)
    return f ? `${L(f.label)}: ` : ''
  }
  const describe = (e: BulkError) =>
    `${e.name || '—'}: ${Object.entries(e.fields).map(([k, c]) => label(k) + terr(c)).join(', ')}`

  /** delete: ask first; companies in the selection can take their persons along (one checkbox for all) */
  async function confirmDelete() {
    const n = personsAlong(picked, (u) => store.persons.get(u)?.map((p) => p.uid)).length
    const ok = await confirmDialog({
      title: t('bulk.confirm_title', { n: picked.size }),
      message: t('bulk.confirm_text') + (n ? '\n\n' + t('bulk.confirm_companies', { n }) : ''),
      confirmLabel: t('confirm.delete_ok'),
      danger: true,
      checkbox: n ? { label: t('bulk.with_persons', { n }), checked: false } : undefined,
    })
    return ok && { op, with_persons: ok.checked }
  }

  async function apply() {
    const body = op === 'delete' ? await confirmDelete()
      : { op: op === 'responsible' ? 'set' : op, key: field!.key, value: op === 'clear' ? null : value }
    if (!body) return
    busy = true
    try {
      const r = await post<{ records: Rec[]; deleted: string[]; errors: BulkError[] }>('/api/records/bulk', { ...body, uids: [...picked] })
      store.upsertAll(r.records, r.deleted)
      toast(op === 'delete' ? t('bulk.deleted', { n: r.deleted.length }) : t('bulk.done', { n: r.records.length }))
      if (r.errors.length)
        toast(t('bulk.failed', { n: r.errors.length, list: r.errors.slice(0, 3).map(describe).join(' · ') }), { kind: 'error', ms: 10000 })
      onpick(new Set(r.errors.map((e) => e.uid))) // the failed ones stay selected
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    } finally {
      busy = false
    }
  }
</script>

<div class="bulk" role="region" aria-label={t('bulk.title')}>
  <div class="row">
    <strong class="tabular">{t('bulk.selected', { n: picked.size })}</strong>
    {#if picked.size < all.length}<button class="link" onclick={() => onpick(new Set(all))}>{t('bulk.all', { n: all.length })}</button>{/if}
    {#if picked.size}<button class="link" onclick={() => onpick(new Set())}>{t('bulk.none')}</button>{/if}
    <button class="btn icon sm ghost close" onclick={onclose} title={t('bulk.close')} aria-label={t('bulk.close')}><X size={14} /></button>
  </div>
  <div class="row">
    <select class="select" bind:value={op} aria-label={t('bulk.action')}>
      {#each ops as o (o)}<option value={o}>{t(`bulk.op_${o}`)}</option>{/each}
    </select>
    {#if op !== 'delete' && op !== 'responsible'}
      <select class="select" value={field?.key} onchange={(e) => (key = e.currentTarget.value)} aria-label={t('bulk.field')}>
        {#each choices as f (f.key)}<option value={f.key}>{L(f.label)}</option>{/each}
      </select>
    {/if}
  </div>
  {#if field && op !== 'clear'}
    {#key field.key + op}
      <!-- removing only offers existing options; required is checked per record by the server -->
      <FieldInput field={{ ...field, required: false, open_options: op !== 'remove' && field.open_options }} {value}
                  onchange={(v) => (value = v)} />
    {/key}
  {/if}
  <button class="btn" class:primary={op !== 'delete'} class:danger={op === 'delete'} disabled={busy || !picked.size || !ready} onclick={apply}>
    {t('bulk.apply', { n: picked.size })}
  </button>
  <p class="hint">{t('bulk.hint')}</p>
</div>

<style>
  .bulk { display: flex; flex-direction: column; gap: 8px; margin: 0 12px 8px; padding: 10px 12px; border-radius: 10px;
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); background: var(--accent-soft); }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .row .select { flex: 1; min-width: 0; }
  .close { margin-left: auto; }
  .link { border: 0; background: none; color: var(--accent); cursor: pointer; padding: 0; font-size: 13px; }
  .hint { margin: 0; }
</style>
