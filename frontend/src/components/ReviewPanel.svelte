<script lang="ts">
  import { Check, ClipboardCheck, Pencil, Trash2, Undo2, X } from '@lucide/svelte'
  import { ApiError, del, post } from '../lib/api'
  import { go } from '../lib/router.svelte'
  import { store } from '../lib/store.svelte'
  import { dateTime, fmt, relTime } from '../lib/format'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { Proposal, Rec } from '../lib/types'

  interface Props {
    rec: Rec; deleting: boolean; onpropose: () => void; ondeleting: (v: boolean) => void
    onedit: (p: Proposal) => void; onadjust: (p: Proposal) => void
  }
  let { rec, deleting, onpropose, ondeleting, onedit, onadjust }: Props = $props()
  const mine = (p: Proposal) => p.proposer === store.user?.username

  const review = $derived(store.reviewFor(rec.uid))
  const proposals = $derived(store.proposalsFor(rec.uid))
  let comment = $state('')
  let reason = $state<'left' | 'company_gone' | 'other'>('other')
  let commentMissing = $state(false)
  const company = $derived(rec.company ? store.byUid.get(rec.company) : undefined)
  const reasons = $derived(rec.kind === 'company' ? (['company_gone', 'other'] as const)
                           : company ? (['left', 'company_gone', 'other'] as const) : (['left', 'other'] as const))
  $effect(() => {
    if (deleting) reason = reasons[0]
  })
  // a person whose company someone reported as gone
  const companyGone = $derived(rec.company ? store.proposals.find((p) => p.record === rec.company && p.reason === 'company_gone') : undefined)
  const affected = (p: Proposal) => (p.reason === 'company_gone' ? store.persons.get(p.record) ?? [] : [])
  let notes = $state<Record<number, string>>({})
  let busy = $state(false)

  const fieldByKey = $derived(new Map(store.fields.map((f) => [f.key, f])))
  const label = (key: string) => (fieldByKey.get(key) ? L(fieldByKey.get(key)!.label) : t(`core.${key}`))
  const show = (scope: 'core' | 'data', key: string, v: any) => {
    if (v == null || v === '' || (Array.isArray(v) && !v.length)) return '—'
    if (scope === 'core') return key === 'company' ? store.byUid.get(v)?.name ?? '—' : String(v)
    const f = fieldByKey.get(key)
    return f ? fmt(f, v) : String(v)
  }
  const rows = (p: Proposal) =>
    (['core', 'data'] as const).flatMap((s) => Object.keys(p.changes[s] ?? {}).map((k) => ({
      key: k, label: label(k), from: show(s, k, p.base[s]?.[k]), to: show(s, k, p.changes[s]![k]),
      // the contact was edited since: the current value no longer matches what the proposer saw
      drift: JSON.stringify((s === 'core' ? (rec as any)[k] : rec.data[k]) ?? null) !== JSON.stringify(p.base[s]?.[k] ?? null),
    })))

  async function run(fn: () => Promise<any>, ok: string) {
    busy = true
    try {
      const r = await fn()
      if (r?.uid) store.upsert(r)
      if (r?.record?.uid) store.upsert(r.record)
      toast(ok)
      await store.sync()
      return true
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation')
        toast(Object.entries(e.fields).map(([k, c]) => `${label(k)}: ${terr(c)}`).join(' · '), { kind: 'error' })
      else toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
      return false
    } finally {
      busy = false
    }
  }

  async function withdraw(p: Proposal) {
    const ok = await confirmDialog({ title: t('proposal.withdraw_title'), message: t('proposal.withdraw_text'),
                                     confirmLabel: t('proposal.withdraw'), danger: true })
    if (ok) await run(() => del(`/api/proposals/${p.id}`), t('proposal.withdrawn'))
  }

  const confirm = () => run(() => post(`/api/records/${rec.uid}/review/confirm`), t('review.confirmed'))

  async function proposeDelete() {
    commentMissing = reason === 'other' && !comment.trim()
    if (commentMissing) return
    let existing = false
    const ok = await run(async () => {
      existing = !!(await post<{ existing?: boolean }>(`/api/records/${rec.uid}/proposals`, { kind: 'delete', reason, comment })).existing
    }, reason === 'company_gone' && rec.kind === 'person' ? t('proposal.sent_company') : t('proposal.sent'))
    if (ok) {
      if (existing) toast(t('proposal.already_reported'))
      comment = ''
      ondeleting(false)
    }
  }

  async function decide(p: Proposal, action: 'accept' | 'reject') {
    const ok = await run(() => post(`/api/proposals/${p.id}/${action}`, { note: notes[p.id] ?? '' }),
                         t(action === 'accept' ? 'proposal.accepted' : 'proposal.rejected'))
    if (ok && action === 'accept' && p.kind === 'delete') go('/', true) // contact is in the recycle bin now
  }
</script>

{#if review}
  <div class="panel review">
    <ClipboardCheck size={18} />
    <div class="text">
      <strong>{t('review.title')}</strong>
      <span>{rec.kind === 'company' ? t('review.ask_company') : t('review.ask_person')}</span>
    </div>
    <div class="actions">
      <button class="btn primary" disabled={busy} onclick={confirm}><Check size={15} />{t('review.ok')}</button>
      <!-- maintainers edit directly (saving completes the review); others propose -->
      <button class="btn" disabled={busy} onclick={onpropose}><Pencil size={15} />{store.canEdit ? t('common.edit') : t('proposal.change')}</button>
      {#if !store.canEdit}
        <button class="btn" disabled={busy} onclick={() => ondeleting(true)}><Trash2 size={15} />{t('proposal.delete')}</button>
      {/if}
    </div>
  </div>
{/if}

{#if deleting}
  <div class="panel">
    <div class="text wide">
      <strong>{rec.kind === 'company' ? t('proposal.delete_company') : t('proposal.delete_person')}</strong>
      <div class="reasons" role="radiogroup" aria-label={t('proposal.reason')}>
        {#each reasons as r (r)}
          <label><input type="radio" bind:group={reason} value={r} /> {t(`proposal.reason_${r}`)}</label>
        {/each}
      </div>
      {#if reason === 'company_gone'}
        <div class="hint">{t('proposal.company_gone_hint', { company: rec.kind === 'company' ? rec.name : company?.name ?? '',
                                                             n: (store.persons.get(rec.kind === 'company' ? rec.uid : rec.company ?? '') ?? []).length })}</div>
      {/if}
      <textarea class="input" class:invalid={commentMissing} rows="2" bind:value={comment} oninput={() => (commentMissing = false)}
                placeholder={reason === 'other' ? t('proposal.comment_required') : t('proposal.comment_optional')}></textarea>
      {#if commentMissing}<div class="error-text">{terr('required')}</div>{/if}
    </div>
    <div class="actions">
      <button class="btn" onclick={() => ondeleting(false)}>{t('common.cancel')}</button>
      <button class="btn danger" disabled={busy} onclick={proposeDelete}>{t('proposal.send')}</button>
    </div>
  </div>
{/if}

{#if companyGone}
  <div class="panel info">
    <span>{t('proposal.company_reported', { company: company?.name ?? '' })}</span>
    <a href="/company/{rec.company}">{t('proposal.open_company')}</a>
  </div>
{/if}

{#each proposals as p (p.id)}
  <div class="panel proposal" class:del={p.kind === 'delete'}>
    <div class="text wide">
      <strong>{p.kind === 'delete' ? t('proposal.title_delete') : t('proposal.title_change')}{#if p.reason}: {t(`proposal.reason_${p.reason}`)}{/if}</strong>
      <span class="muted">{store.userName(p.proposer)} · <time title={dateTime(p.created_at)}>{relTime(p.created_at)}</time></span>
      {#if p.comment}<q>{p.comment}</q>{/if}
      {#if affected(p).length}
        <div class="affected">
          {t('proposal.affected', { n: affected(p).length })}
          {#each affected(p).slice(0, 12) as a (a.uid)}<a href="/person/{a.uid}">{store.name(a)}</a>{/each}
          {#if affected(p).length > 12}<span class="muted">+{affected(p).length - 12}</span>{/if}
        </div>
      {/if}
      {#if p.kind === 'change'}
        <table>
          <tbody>
            {#each rows(p) as r (r.key)}
              <tr>
                <th>{r.label}</th>
                <td class="from">{r.from}</td>
                <td class="arrow">→</td>
                <td>{r.to}{#if r.drift} <span class="badge warn" title={t('proposal.drift_hint')}>{t('proposal.drift')}</span>{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      {#if store.canEdit}
        <input class="input" bind:value={notes[p.id]} placeholder={t('proposal.note_ph')} />
      {/if}
    </div>
    {#if store.canEdit}
      <div class="actions">
        <button class="btn" disabled={busy} onclick={() => decide(p, 'reject')}><X size={15} />{t('proposal.reject')}</button>
        {#if p.kind === 'change'}
          <button class="btn" disabled={busy} onclick={() => onadjust(p)}><Pencil size={15} />{t('proposal.adjust')}</button>
        {/if}
        <button class="btn" class:primary={p.kind === 'change'} class:danger={p.kind === 'delete'} disabled={busy}
                onclick={() => decide(p, 'accept')}><Check size={15} />{p.kind === 'delete' ? t('proposal.accept_delete') : t('proposal.accept')}</button>
      </div>
    {:else}
      <div class="actions">
        <span class="badge">{t('proposal.pending')}</span>
        {#if mine(p)}
          {#if p.kind === 'change'}<button class="btn sm" disabled={busy} onclick={() => onedit(p)}><Pencil size={13} />{t('common.edit')}</button>{/if}
          <button class="btn sm" disabled={busy} onclick={() => withdraw(p)}><Undo2 size={13} />{t('proposal.withdraw')}</button>
        {/if}
      </div>
    {/if}
  </div>
{/each}

<style>
  .panel { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; padding: 12px 14px; margin-bottom: 14px;
    border: 1px solid var(--border); border-radius: 10px; background: var(--panel-2); }
  .review { background: var(--accent-soft); border-color: color-mix(in srgb, var(--accent) 35%, transparent); color: var(--accent-text); align-items: center; }
  .proposal { border-left: 3px solid var(--accent); }
  .proposal.del { border-left-color: var(--danger); }
  .text { flex: 1 1 260px; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .text.wide { flex-basis: 100%; }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
  q { font-style: italic; color: var(--muted); }
  .reasons { display: flex; flex-direction: column; gap: 4px; margin: 2px 0; }
  .reasons label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .affected { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 13px; color: var(--danger); }
  .info { align-items: center; justify-content: space-between; }
  table { border-collapse: collapse; font-size: 13px; margin: 4px 0; }
  th { text-align: left; font-weight: 500; color: var(--muted); padding: 2px 12px 2px 0; white-space: nowrap; vertical-align: top; }
  td { padding: 2px 6px 2px 0; vertical-align: top; white-space: pre-wrap; word-break: break-word; }
  .from { color: var(--muted); text-decoration: line-through; }
  .arrow { color: var(--faint); }
  .badge.warn { background: var(--warn-soft); color: var(--warn); }
</style>
