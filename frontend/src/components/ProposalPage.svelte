<script lang="ts">
  import { Building2, Check, Pencil, Undo2, UserRound, X } from '@lucide/svelte'
  import RecordForm from './RecordForm.svelte'
  import { ApiError, del, post } from '../lib/api'
  import { go } from '../lib/router.svelte'
  import { store } from '../lib/store.svelte'
  import { dateTime, relTime } from '../lib/format'
  import { t, terr } from '../lib/i18n.svelte'
  import { fieldName, proposedValues } from '../lib/proposals'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { Rec } from '../lib/types'

  /** a proposed new contact (proposal kind "create"): it has no record until a maintainer accepts it */
  let { id }: { id: number } = $props()
  const p = $derived(store.newProposals.find((x) => x.id === id))
  const mine = $derived(p?.proposer === store.user?.username)
  let form = $state<null | 'edit' | 'adjust'>(null)
  let note = $state('')
  let busy = $state(false)

  async function decide(action: 'accept' | 'reject') {
    busy = true
    try {
      const r = await post<{ record: Rec | null }>(`/api/proposals/${id}/${action}`, { note })
      if (r.record) store.upsert(r.record)
      toast(t(action === 'accept' ? 'proposal.accepted' : 'proposal.rejected'))
      await store.sync()
      go(r.record ? `/${r.record.kind}/${r.record.uid}` : '/', true)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation')
        toast(Object.entries(e.fields).map(([k, c]) => `${fieldName(k)}: ${terr(c)}`).join(' · '), { kind: 'error' })
      else toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    } finally {
      busy = false
    }
  }

  async function withdraw() {
    const ok = await confirmDialog({ title: t('proposal.withdraw_title'), message: t('proposal.withdraw_text'),
                                     confirmLabel: t('proposal.withdraw'), danger: true })
    if (!ok) return
    await del(`/api/proposals/${id}`)
    toast(t('proposal.withdrawn'))
    await store.sync()
    go('/', true)
  }
</script>

<div class="page">
  {#if !p}
    <p class="muted">{t('proposal.gone')}</p>
    <a href="/">{t('proposal.back')}</a>
  {:else if form}
    <h1>{p.record_kind === 'person' ? t('proposal.title_new_person') : t('proposal.title_new_company')}</h1>
    {#key form}
      <RecordForm rec={null} kind={p.record_kind} mode={form === 'adjust' ? 'adjust' : 'propose'} proposal={p}
                  onclose={(saved) => (saved ? go(`/${saved.kind}/${saved.uid}`, true) : (form = null))} />
    {/key}
  {:else}
    <header>
      <span class="icon">{#if p.record_kind === 'person'}<UserRound size={22} />{:else}<Building2 size={22} />{/if}</span>
      <div>
        <h1>{p.label}</h1>
        <span class="badge">{p.record_kind === 'person' ? t('proposal.title_new_person') : t('proposal.title_new_company')}</span>
      </div>
    </header>
    <div class="panel">
      <span class="muted">{store.userName(p.proposer)} · <time title={dateTime(p.created_at)}>{relTime(p.created_at)}</time></span>
      {#if p.comment}<q>{p.comment}</q>{/if}
      <table>
        <tbody>
          {#each proposedValues(p) as r (r.key)}<tr><th>{r.label}</th><td>{r.value}</td></tr>{/each}
        </tbody>
      </table>
      {#if store.canEdit}
        <input class="input" bind:value={note} placeholder={t('proposal.note_ph')} />
        <div class="actions">
          <button class="btn" disabled={busy} onclick={() => decide('reject')}><X size={15} />{t('proposal.reject')}</button>
          <button class="btn" disabled={busy} onclick={() => (form = 'adjust')}><Pencil size={15} />{t('proposal.adjust')}</button>
          <button class="btn primary" disabled={busy} onclick={() => decide('accept')}><Check size={15} />{t('proposal.accept_create')}</button>
        </div>
      {:else}
        <div class="actions">
          <span class="badge">{t('proposal.pending')}</span>
          {#if mine}
            <button class="btn sm" onclick={() => (form = 'edit')}><Pencil size={13} />{t('common.edit')}</button>
            <button class="btn sm" onclick={withdraw}><Undo2 size={13} />{t('proposal.withdraw')}</button>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .page { max-width: 760px; padding: 24px 28px; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
  .icon { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 12px; background: var(--panel-2); color: var(--muted); }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .panel { display: flex; flex-direction: column; gap: 10px; padding: 14px 16px; border-radius: 10px; background: var(--panel-2);
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); }
  q { font-style: italic; color: var(--muted); }
  table { border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 3px 16px 3px 0; white-space: nowrap; vertical-align: top; }
  td { padding: 3px 0; }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
</style>
