<script lang="ts">
  import { RotateCcw, Trash2 } from '@lucide/svelte'
  import Avatar from './Avatar.svelte'
  import { ApiError, del, get, post } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { dateTime, relTime } from '../lib/format'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { Rec } from '../lib/types'

  let records = $state<Rec[] | null>(null)

  const load = () => get<{ records: Rec[] }>('/api/trash').then((r) => (records = r.records))
  load()

  async function restore(r: Rec) {
    const back = await post<Rec>(`/api/records/${r.uid}/restore`)
    store.upsert(back)
    records = records!.filter((x) => x.uid !== r.uid)
    toast(t('trash.restored', { name: store.name(r) }))
  }

  async function purge(r: Rec) {
    const n = r.kind === 'company' ? store.persons.get(r.uid)?.length ?? 0 : 0 // live persons linked to it
    const ok = await confirmDialog({
      title: t('trash.purge_title', { name: store.name(r) }),
      message: t('trash.purge_text') + (n ? '\n\n' + t('trash.purge_persons', { n }) : ''),
      confirmLabel: t('confirm.purge_ok'),
      danger: true,
    })
    if (!ok) return
    try {
      await del(`/api/trash/${r.uid}`)
      records = records!.filter((x) => x.uid !== r.uid)
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }
</script>

<div class="page">
  <h1>{t('trash.title')}</h1>
  <p class="muted">{t('trash.hint')}</p>
  {#if !records}
    <p class="muted">{t('common.loading')}</p>
  {:else if !records.length}
    <p class="empty muted">{t('trash.empty')}</p>
  {:else}
    <table class="grid">
      <thead><tr><th></th><th>{t('core.name')}</th><th>{t('trash.deleted')}</th><th></th></tr></thead>
      <tbody>
        {#each records as r (r.uid)}
          <tr>
            <td style="width:44px"><Avatar rec={r} size={28} /></td>
            <td>{store.name(r)} {#if r.kind === 'company'}<span class="badge">{t('kind.company')}</span>{/if}</td>
            <td class="muted" title={dateTime(r.deleted_at!)}>{relTime(r.deleted_at!)} · {store.userName(r.updated_by)}</td>
            <td><div class="act">
              <button class="btn sm" onclick={() => restore(r)}><RotateCcw size={14} />{t('trash.restore')}</button>
              {#if store.isAdmin}
                <button class="btn sm icon danger" title={t('trash.purge')} aria-label={t('trash.purge')} onclick={() => purge(r)}><Trash2 size={14} /></button>
              {/if}
            </div></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .page { max-width: 920px; margin: 0 auto; padding: 24px 28px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  p { margin: 0 0 18px; }
  .act { display: flex; gap: 6px; justify-content: flex-end; align-items: center; }
  .empty { padding: 40px 0; text-align: center; }
</style>
