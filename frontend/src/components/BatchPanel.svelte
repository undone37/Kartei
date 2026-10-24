<script lang="ts">
  import { Users } from '@lucide/svelte'
  import { ApiError, post } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { fmt } from '../lib/format'
  import { L, t, terr, tmsg } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import type { BatchItem } from '../lib/types'
  import { untrack } from 'svelte'
  interface Props { company: string; changes: Record<string, [any, any]>; items: BatchItem[]; onclose: () => void }
  let { company, changes, items, onclose }: Props = $props()

  const id = (i: BatchItem) => `${i.uid}:${i.key}`
  let picked = $state(new Set(untrack(() => items).map(id))) // parent keys the panel per batch
  let busy = $state(false)
  const persons = $derived(new Set(items.map((i) => i.uid)).size)
  const field = (key: string) => store.fields.find((f) => f.key === key)
  const show = (key: string, v: any) => {
    const f = field(key)
    return v == null || v === '' ? '—' : f ? fmt(f, v) : String(v)
  }

  function toggle(i: BatchItem) {
    const s = new Set(picked)
    if (!s.delete(id(i))) s.add(id(i))
    picked = s
  }

  async function apply() {
    busy = true
    try {
      const selected = items.filter((i) => picked.has(id(i))).map((i) => ({ uid: i.uid, key: i.key }))
      const r = await post<{ updated: number; errors: string[] }>(`/api/records/${company}/propagate`, { changes, selected })
      toast(t('batch.done', { n: r.updated }))
      if (r.errors.length) toast(r.errors.map(tmsg).join(' · '), { kind: 'error' })
      await store.sync()
      onclose()
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    } finally {
      busy = false
    }
  }
</script>

<div class="panel">
  <div class="head">
    <Users size={18} />
    <div>
      <strong>{t('batch.title', { n: persons })}</strong>
      <div class="hint">{t('batch.hint')}</div>
    </div>
  </div>
  <table>
    <tbody>
      {#each items as i (id(i))}
        <tr class:off={!picked.has(id(i))}>
          <td><input type="checkbox" checked={picked.has(id(i))} onchange={() => toggle(i)} aria-label={i.name} /></td>
          <td><a href="/person/{i.uid}">{i.name}</a></td>
          <th>{field(i.key) ? L(field(i.key)!.label) : i.key}</th>
          <td class="from">{show(i.key, i.old)}</td>
          <td class="arrow">→</td>
          <td>{show(i.key, i.new)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  <div class="actions">
    <button class="btn" onclick={onclose}>{t('batch.skip')}</button>
    <button class="btn primary" disabled={busy || !picked.size} onclick={apply}>{t('batch.apply', { n: picked.size })}</button>
  </div>
</div>

<style>
  .panel { padding: 12px 14px; margin-bottom: 14px; border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    border-radius: 10px; background: var(--accent-soft); display: flex; flex-direction: column; gap: 10px; }
  .head { display: flex; gap: 10px; align-items: flex-start; color: var(--accent-text); }
  .head .hint { color: var(--muted); }
  table { border-collapse: collapse; font-size: 13px; }
  td, th { padding: 3px 10px 3px 0; text-align: left; vertical-align: top; }
  th { font-weight: 500; color: var(--muted); white-space: nowrap; }
  tr.off { opacity: 0.5; }
  .from { color: var(--muted); text-decoration: line-through; }
  .arrow { color: var(--faint); }
  .actions { display: flex; gap: 6px; justify-content: flex-end; }
</style>
