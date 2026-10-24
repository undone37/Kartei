<script lang="ts">
  import { Bookmark, ClipboardCheck, Clock, Copy, History, Inbox, Pencil, ShieldCheck, Star, Trash2, Users } from '@lucide/svelte'
  import Avatar from './Avatar.svelte'
  import { ApiError, get } from '../lib/api'
  import { auditLabel, auditObject, auditValue, visibleChanges } from '../lib/audit'
  import { dateTime, relTime } from '../lib/format'
  import { t, terr } from '../lib/i18n.svelte'
  import { store } from '../lib/store.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { AuditEntry, ListState, Rec } from '../lib/types'

  let { onapply, onscope }: { onapply: (s: ListState) => void; onscope: (scope: 'review' | 'proposals') => void } = $props()

  // maintenance pages (maintainers and admins)
  const tools: { href: string; label: string; icon: typeof Users; n?: number }[] = $derived(store.canEdit ? [
    { href: '/quality', label: t('quality.title'), icon: ShieldCheck },
    { href: '/duplicates', label: t('dupes.title'), icon: Copy },
  ] : [])

  const recs = (uids: string[]) => uids.map((u) => store.byUid.get(u)).filter((r): r is Rec => !!r)
  const recent = $derived(recs(store.recent))
  const favorites = $derived(recs(store.favorites))

  // recent changes: maintainers only; reloaded whenever a sync brought new records
  let changes = $state<AuditEntry[] | null>(null)
  $effect(() => {
    void store.records
    if (!store.canEdit) return
    get<{ entries: AuditEntry[] }>('/api/recent-changes').then((r) => (changes = r.entries)).catch(() => (changes ??= []))
  })
  const NOISE = ['bulk', 'batch_from', 'proposed_by', 'with_company']
  const what = (e: AuditEntry) => visibleChanges(e).filter(([k]) => !NOISE.includes(k)).map(([k]) => auditLabel(e, k))
  const detail = (e: AuditEntry) =>
    visibleChanges(e).map(([k, [a, b]]) => `${auditLabel(e, k)}: ${auditValue(e, k, a)} → ${auditValue(e, k, b)}`).join('\n')

  let renaming = $state<number | null>(null)
  let newName = $state('')
  const fail = (e: unknown) => toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
  async function rename(id: number) {
    if (newName.trim()) await store.renameFilter(id, newName).catch(fail)
    renaming = null
  }
  async function remove(f: { id: number; name: string; shared: boolean }) {
    const ok = await confirmDialog({ title: t('saved.delete_title', { name: f.name }),
                                     message: f.shared ? t('saved.delete_text_shared') : t('saved.delete_text'),
                                     confirmLabel: t('common.delete'), danger: true })
    if (ok) await store.deleteFilter(f.id).then(() => toast(t('saved.deleted'))).catch(fail)
  }
</script>

{#snippet recList(list: Rec[], empty: string)}
  <ul class="recs">
    {#each list as r (r.uid)}
      <li><a href="/{r.kind}/{r.uid}"><Avatar rec={r} size={26} /><span class="name">{store.name(r)}</span>
        <span class="sub">{r.kind === 'person' ? store.companyName(r) : t('kind.company')}</span></a></li>
    {:else}
      <li class="muted empty">{empty}</li>
    {/each}
  </ul>
{/snippet}

<div class="dash">
  <div class="stats">
    {#if store.reviews.length}
      <button class="stat todo" onclick={() => onscope('review')}>
        <ClipboardCheck size={18} /><span class="n tabular">{store.reviews.length}</span>{t('dash.reviews')}</button>
    {/if}
    {#if store.canEdit && store.proposals.length}
      <button class="stat todo" onclick={() => onscope('proposals')}>
        <Inbox size={18} /><span class="n tabular">{store.proposals.length}</span>{t('dash.proposals')}</button>
    {/if}
    {#each tools as x (x.href)}
      <a class="stat" href={x.href}><x.icon size={18} />{#if x.n != null}<span class="n tabular">{x.n}</span>{/if}{x.label}</a>
    {/each}
  </div>

  <div class="grid">
    <section class="card">
      <h2><Clock size={15} />{t('dash.recent')}</h2>
      {@render recList(recent.slice(0, 10), t('dash.no_recent'))}
    </section>
    <section class="card">
      <h2><Star size={15} />{t('dash.favorites')}</h2>
      {@render recList(favorites, t('dash.no_favorites'))}
    </section>
    <section class="card">
      <h2><Bookmark size={15} />{t('saved.title')}</h2>
      <ul class="filters">
        {#each store.filters as f (f.id)}
          <li>
            {#if renaming === f.id}
              <form onsubmit={(e) => { e.preventDefault(); rename(f.id) }}>
                <!-- svelte-ignore a11y_autofocus -->
                <input class="input" bind:value={newName} aria-label={t('saved.rename')} autofocus
                       onkeydown={(e) => e.key === 'Escape' && (renaming = null)} onblur={() => rename(f.id)} />
              </form>
            {:else}
              <button class="apply" onclick={() => onapply(f.state)}>{f.name}</button>
              {#if f.shared}<span class="badge" title={f.mine ? '' : f.owner}>{t('saved.shared')}</span>{/if}
              {#if f.mine}
                <button class="btn icon sm ghost" title={t('saved.rename')} aria-label={t('saved.rename')}
                        onclick={() => { renaming = f.id; newName = f.name }}><Pencil size={13} /></button>
                <button class="btn icon sm ghost danger" title={t('common.delete')} aria-label={t('common.delete')}
                        onclick={() => remove(f)}><Trash2 size={13} /></button>
              {/if}
            {/if}
          </li>
        {:else}
          <li class="muted empty">{t('saved.none')}</li>
        {/each}
      </ul>
    </section>
    {#if store.canEdit}
      <section class="card wide">
        <h2><History size={15} />{t('dash.changes')}</h2>
        {#if !changes}
          <p class="muted empty">{t('common.loading')}</p>
        {:else}
          <ul class="changes">
            {#each changes as e (e.id)}
              {@const o = auditObject(e)}
              <li title={detail(e)}>
                {#if o.href && store.byUid.get(e.target_id)}<a href={o.href}>{o.name}</a>{:else}<span>{o.name}</span>{/if}
                <span class="what">{t(`audit.${e.action}`)}{#if e.action === 'update' && what(e).length}: {what(e).slice(0, 3).join(', ')}{what(e).length > 3 ? ' …' : ''}{/if}{#if e.changes.bulk}<span class="badge">{t('audit.attr.bulk')}</span>{/if}</span>
                <span class="muted when">{store.userName(e.user)} · <time datetime={e.at} title={dateTime(e.at)}>{relTime(e.at)}</time></span>
              </li>
            {:else}
              <li class="muted empty">{t('dash.no_changes')}</li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}
  </div>

  <p class="hint keys"><kbd>/</kbd> {t('help.search')} · <kbd>↑</kbd><kbd>↓</kbd> {t('help.nav')} {#if store.canEdit} · <kbd>E</kbd> {t('help.edit')} · <kbd>N</kbd> {t('help.new')}{/if}</p>
</div>

<style>
  .dash { max-width: 1040px; margin: 0 auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 16px; }
  .stats { display: flex; gap: 10px; flex-wrap: wrap; }
  .stats:empty { display: none; }
  .stat { display: inline-flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: 10px; border: 1px solid var(--border);
    background: var(--panel); color: var(--text); cursor: pointer; font-weight: 500; transition: background-color 0.12s; }
  .stat:hover { background: var(--panel-2); text-decoration: none; }
  .stat .n { font-size: 18px; font-weight: 650; }
  .stat.todo { border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: var(--accent-soft); color: var(--accent-text); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
  .card { padding: 14px 16px; min-width: 0; }
  .wide { grid-column: 1 / -1; }
  h2 { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--muted); margin-bottom: 8px; }
  ul { list-style: none; margin: 0; padding: 0; }
  .recs a { display: flex; align-items: center; gap: 9px; padding: 5px 6px; margin: 0 -6px; border-radius: 7px; color: inherit; min-width: 0; }
  .recs a:hover { background: var(--panel-2); text-decoration: none; }
  .name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: none; max-width: 60%; }
  .sub { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .filters li { display: flex; align-items: center; gap: 4px; min-height: 32px; }
  .filters form { flex: 1; }
  .filters .input { height: 28px; }
  .apply { flex: 1; min-width: 0; text-align: left; border: 0; background: none; padding: 5px 6px; margin-left: -6px; border-radius: 7px;
    color: var(--accent); font-weight: 500; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .apply:hover { background: var(--panel-2); }
  .changes li { display: grid; grid-template-columns: minmax(120px, 1fr) 2fr auto; gap: 12px; align-items: baseline;
    padding: 6px 0; border-bottom: 1px solid var(--border); }
  .changes li:last-child { border-bottom: 0; }
  .changes a, .changes span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .what .badge { margin-left: 6px; }
  .when { font-size: 12px; }
  .empty { padding: 6px 0; display: block; }
  .keys { text-align: center; }
  @media (max-width: 860px) {
    .dash { padding: 14px 16px; }
    .changes li { grid-template-columns: 1fr; gap: 0; }
  }
</style>
