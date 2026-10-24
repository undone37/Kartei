<script lang="ts">
  import { ClipboardCheck, Copy, Download, ExternalLink, Info, Mail, Pencil, Phone, Star, Trash2, UserPlus, ArrowLeft } from '@lucide/svelte'
  import ReviewPanel from './ReviewPanel.svelte'
  import BatchPanel from './BatchPanel.svelte'
  import { untrack } from 'svelte'
  import Avatar from './Avatar.svelte'
  import History from './History.svelte'
  import RecordForm from './RecordForm.svelte'
  import { ApiError, del, post } from '../lib/api'
  import { go } from '../lib/router.svelte'
  import { store } from '../lib/store.svelte'
  import { fmt, isEmpty, isMulti, relTime, dateTime } from '../lib/format'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { groupFields } from '../lib/sections'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { BatchItem, Field, Proposal, Rec } from '../lib/types'

  let { rec, editing = $bindable(false) }: { rec: Rec; editing?: boolean } = $props()
  let tab = $state<'details' | 'persons' | 'history'>('details')
  // edit form that proposes (new or own pending proposal) or adjusts a proposal before applying it
  let proposing = $state<{ mode: 'propose' | 'adjust'; proposal: Proposal | null } | null>(null)
  let deleting = $state(false) // delete-proposal composer
  // after saving a company: offer to carry the changes over to its persons
  let before: Rec | null = null
  let batch = $state<{ changes: Record<string, [any, any]>; items: BatchItem[] } | null>(null)

  $effect(() => {
    if (editing) before = untrack(() => $state.snapshot(rec) as Rec)
  })

  async function closeEdit(saved?: Rec) {
    const adjusted = proposing?.mode === 'adjust'
    editing = false
    proposing = null
    if (adjusted) return
    if (!saved || saved.kind !== 'company' || !before) return
    const changes: Record<string, [any, any]> = {}
    for (const k of new Set([...Object.keys(before.data), ...Object.keys(saved.data)]))
      if (JSON.stringify(before.data[k] ?? null) !== JSON.stringify(saved.data[k] ?? null)) changes[k] = [before.data[k] ?? null, saved.data[k] ?? null]
    if (!Object.keys(changes).length) return
    const r = await post<{ items: BatchItem[] }>(`/api/records/${saved.uid}/propagate`, { changes }).catch(() => null)
    if (r?.items.length) batch = { changes, items: r.items }
  }

  $effect(() => {
    void rec.uid
    tab = 'details'
    proposing = null
    deleting = false
    batch = null
    store.viewed(rec.uid)
  })

  const favorite = $derived(store.favorites.includes(rec.uid))
  function toggleFavorite() {
    store.toggleFavorite(rec.uid).catch((e) => toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' }))
  }

  async function requestReview() {
    try {
      const r = await post<{ created: number; no_responsible: number }>(`/api/records/${rec.uid}/review/request`)
      toast(r.created ? t('review.requested') : r.no_responsible ? t('review.no_responsible') : t('review.already_open'),
            { kind: r.created ? undefined : 'error' })
      store.sync()
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  const company = $derived(rec.company ? store.byUid.get(rec.company) : undefined)
  const persons = $derived(rec.kind === 'company' ? store.persons.get(rec.uid) ?? [] : [])
  /** filled-in fields by section, in section order */
  const sections = $derived(
    groupFields(store.fieldsFor(rec.kind).filter((f) => !isEmpty(rec.data[f.key])), store.sections).map((g) => ({
      id: g.section?.id ?? 0, title: g.section ? L(g.section.label) : t('core.section_other'),
      items: g.fields.map((f) => ({ f, v: rec.data[f.key] })),
    })),
  )
  const headline = $derived.by(() => {
    const f = store.fields.find((f) => f.vcard === 'title' && !isEmpty(rec.data[f.key]))
    return f ? String(rec.data[f.key]) : ''
  })

  async function copy(text: string) {
    await navigator.clipboard.writeText(text)
    toast(t('view.copied'))
  }

  async function remove() {
    const r = rec
    const name = store.name(r)
    const n = persons.length
    const ok = await confirmDialog({
      title: t('confirm.delete_title'),
      message: n ? t('confirm.company_text', { name, n }) : t('confirm.delete_text', { name }),
      confirmLabel: t('confirm.delete_ok'),
      danger: true,
      // unchecked: the persons usually still exist and only the company link goes stale; deleting them is a choice
      checkbox: n ? { label: t('confirm.with_persons', { n }), checked: false } : undefined,
    })
    if (!ok) return
    try {
      const res = await del<{ deleted: string[] }>(`/api/records/${r.uid}${ok.checked ? '?with_persons=1' : ''}`)
      const deleted = res.deleted ?? [r.uid]
      const along = deleted.filter((u) => u !== r.uid)
      store.upsertAll([], deleted)
      go('/', true)
      toast(along.length ? t('view.deleted_with', { name, n: along.length }) : t('view.deleted', { name }), {
        action: {
          label: t('common.undo'),
          run: async () => {
            try {
              const { persons: backPersons = [], ...back } =
                await post<Rec & { persons?: Rec[] }>(`/api/records/${r.uid}/restore`, along.length ? { persons: along } : {})
              store.upsertAll([back, ...backPersons])
              go(`/${back.kind}/${back.uid}`)
            } catch (e) {
              toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
            }
          },
        },
      })
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  function onkey(e: KeyboardEvent) {
    const el = e.target as HTMLElement
    if (editing || el.closest('input, textarea, select, [contenteditable]') || e.ctrlKey || e.metaKey || e.altKey) return
    if (e.key === 'e' && store.canEdit) {
      e.preventDefault()
      editing = true
    }
  }
</script>

<svelte:window onkeydown={onkey} />

<article class="view">
  <header>
    <a class="back btn icon ghost" href="/" aria-label={t('common.back')}><ArrowLeft size={18} /></a>
    <Avatar {rec} size={56} />
    <div class="title">
      <h1>{store.name(rec) || '—'}</h1>
      <div class="sub">
        {#if headline}<span>{headline}</span>{/if}
        {#if company}<a href="/company/{company.uid}">{company.name}</a>{/if}
        {#if rec.kind === 'company'}<span class="badge">{t('kind.company')}</span>{/if}
      </div>
    </div>
    {#if !editing && !proposing}
      <div class="actions">
        <button class="btn icon star" class:on={favorite} onclick={toggleFavorite} aria-pressed={favorite}
                title={favorite ? t('fav.remove') : t('fav.add')} aria-label={favorite ? t('fav.remove') : t('fav.add')}>
          <Star size={15} fill={favorite ? 'currentColor' : 'none'} /></button>
        {#if store.canEdit}
          <button class="btn" onclick={() => (editing = true)} title="E"><Pencil size={15} />{t('common.edit')}</button>
        {:else}
          <button class="btn" onclick={() => (proposing = { mode: 'propose', proposal: null })}><Pencil size={15} />{t('proposal.change')}</button>
          <button class="btn icon" onclick={() => (deleting = true)} title={t('proposal.delete')}><Trash2 size={15} /></button>
        {/if}
        {#if store.isAdmin}
          <button class="btn icon" onclick={requestReview} title={t('review.request')}><ClipboardCheck size={15} /></button>
        {/if}
        <a class="btn icon" href="/{rec.kind}/{rec.uid}.vcf" download title={t('view.vcard')}><Download size={15} /></a>
        {#if store.canEdit}
          <button class="btn icon danger" onclick={remove} title={t('common.delete')}><Trash2 size={15} /></button>
        {/if}
      </div>
    {/if}
  </header>

  {#if editing || proposing}
    <RecordForm {rec} kind={rec.kind} mode={proposing?.mode ?? 'edit'} proposal={proposing?.proposal ?? null} onclose={closeEdit} />
  {:else}
    {#if batch}
      {#key batch}<BatchPanel company={rec.uid} changes={batch.changes} items={batch.items} onclose={() => (batch = null)} />{/key}
    {/if}
    <ReviewPanel {rec} {deleting} onpropose={() => (store.canEdit ? (editing = true) : (proposing = { mode: 'propose', proposal: null }))} ondeleting={(v) => (deleting = v)}
                 onedit={(p) => (proposing = { mode: 'propose', proposal: p })} onadjust={(p) => (proposing = { mode: 'adjust', proposal: p })} />
    <nav class="tabs" aria-label={t('view.tabs')}>
      <button class:on={tab === 'details'} onclick={() => (tab = 'details')}>{t('view.details')}</button>
      {#if rec.kind === 'company'}
        <button class:on={tab === 'persons'} onclick={() => (tab = 'persons')}>{t('view.persons')} <span class="count">{persons.length}</span></button>
      {/if}
      <button class:on={tab === 'history'} onclick={() => (tab = 'history')}>{t('view.history')}</button>
    </nav>

    {#if tab === 'details'}
      {#if !sections.length}
        <p class="muted empty">{t('view.no_data')}{#if store.canEdit} – <button class="link" onclick={() => (editing = true)}>{t('view.add_data')}</button>{/if}</p>
      {/if}
      {#each sections as s (s.id)}
        <section>
          <h3>{s.title}</h3>
          <dl>
            {#each s.items as { f, v } (f.key)}
              <div class="row" class:wide={f.type === 'longtext'}>
                <dt>{L(f.label)}{#if L(f.help)}<span class="info" title={L(f.help)}><Info size={11} /></span>{/if}</dt>
                <dd>
                  {#if f.type === 'phone'}
                    <a href="tel:{String(v).replace(/[^\d+]/g, '')}" class="tabular"><Phone size={13} />{v}</a>
                    <button class="copy" onclick={() => copy(v)} aria-label={t('view.copy')}><Copy size={13} /></button>
                  {:else if f.type === 'email'}
                    <a href="mailto:{v}"><Mail size={13} />{v}</a>
                    <button class="copy" onclick={() => copy(v)} aria-label={t('view.copy')}><Copy size={13} /></button>
                  {:else if f.type === 'url'}
                    <a href={v} target="_blank" rel="noopener noreferrer">{String(v).replace(/^https?:\/\//, '')}<ExternalLink size={12} /></a>
                  {:else if f.type === 'contact' && store.byUid.get(v)}
                    <a href="/person/{v}">{fmt(f, v)}</a>
                  {:else if isMulti(f)}
                    <span class="tags">{#each fmt(f, v).split(', ') as tag}<span class="tag">{tag}</span>{/each}</span>
                  {:else if f.type === 'longtext'}
                    <span class="long">{v}</span>
                  {:else}
                    <span class:tabular={f.type === 'integer' || f.type === 'decimal'}>{fmt(f, v)}</span>
                  {/if}
                </dd>
              </div>
            {/each}
          </dl>
        </section>
      {/each}
      <footer class="meta">
        {#if rec.legacy_id}<span>{t('view.legacy_id', { id: rec.legacy_id })}</span>{/if}
        <span title={dateTime(rec.updated_at)}>{rec.updated_by ? t('view.updated', { when: relTime(rec.updated_at), user: store.userName(rec.updated_by) })
          : t('view.updated_anon', { when: relTime(rec.updated_at) })}</span>
        <span title={rec.reviewed_at ? dateTime(rec.reviewed_at) : ''}>{rec.reviewed_at
          ? t('view.reviewed', { when: relTime(rec.reviewed_at), user: store.userName(rec.reviewed_by) || '—' }) : t('view.never_reviewed')}</span>
      </footer>
    {:else if tab === 'persons'}
      {#if store.canEdit}
        <a class="btn" href="/new/person?company={rec.uid}"><UserPlus size={15} />{t('view.add_person')}</a>
      {/if}
      <ul class="persons">
        {#each persons as p (p.uid)}
          <li><a href="/person/{p.uid}"><Avatar rec={p} size={28} /><span>{store.name(p)}</span></a></li>
        {:else}
          <li class="muted">{t('view.no_persons')}</li>
        {/each}
      </ul>
    {:else}
      <History uid={rec.uid} />
    {/if}
  {/if}
</article>

<style>
  .view { max-width: 920px; margin: 0 auto; padding: 24px 28px; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
  .back { display: none; }
  .title { flex: 1; min-width: 0; }
  h1 { font-size: 22px; line-height: 1.2; overflow-wrap: anywhere; }
  .sub { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; color: var(--muted); margin-top: 2px; }
  .sub > :not(:last-child)::after { content: '·'; margin-left: 8px; color: var(--faint); }
  .actions { display: flex; gap: 6px; }
  .star.on { color: var(--warn); }
  .tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin-bottom: 18px; }
  .tabs button { border: 0; background: none; padding: 8px 12px; cursor: pointer; color: var(--muted); font-weight: 500;
    border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 0.12s; }
  .tabs button:hover { color: var(--text); }
  .tabs button.on { color: var(--text); border-bottom-color: var(--accent); }
  .count { font-size: 12px; color: var(--faint); font-variant-numeric: tabular-nums; }
  section { margin-bottom: 22px; }
  h3 { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px; font-weight: 600; }
  dl { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px 24px; margin: 0; }
  .row { min-width: 0; }
  .row.wide { grid-column: 1 / -1; }
  dt { font-size: 12px; color: var(--muted); margin-bottom: 1px; }
  .info { display: inline-flex; margin-left: 4px; color: var(--faint); vertical-align: -1px; cursor: help; }
  dd { margin: 0; display: flex; align-items: center; gap: 6px; min-width: 0; overflow-wrap: anywhere; }
  dd a { display: inline-flex; align-items: center; gap: 5px; }
  .copy { border: 0; background: none; padding: 2px; color: var(--faint); cursor: pointer; opacity: 0; transition: opacity 0.12s; border-radius: 4px; }
  .row:hover .copy, .copy:focus-visible { opacity: 1; }
  .copy:hover { color: var(--text); background: var(--panel-2); }
  .long { white-space: pre-wrap; }
  .tags { display: flex; flex-wrap: wrap; gap: 4px; }
  .meta { display: flex; gap: 16px; color: var(--faint); font-size: 12px; border-top: 1px solid var(--border); padding-top: 12px; }
  .empty { padding: 20px 0; }
  .link { border: 0; background: none; color: var(--accent); cursor: pointer; padding: 0; }
  .persons { list-style: none; padding: 0; margin: 12px 0 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 4px; }
  .persons a { display: flex; align-items: center; gap: 10px; padding: 6px 8px; border-radius: 8px; color: inherit; }
  .persons a:hover { background: var(--panel-2); text-decoration: none; }
  @media (max-width: 860px) {
    .view { padding: 14px 16px; }
    .back { display: inline-flex; }
    header { flex-wrap: wrap; }
    .actions { width: 100%; }
  }
</style>
