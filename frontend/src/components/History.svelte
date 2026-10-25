<script lang="ts">
  import { Undo2 } from '@lucide/svelte'
  import { ApiError, get, patch } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { dateTime, relTime } from '../lib/format'
  import { t, terr } from '../lib/i18n.svelte'
  import { auditLabel, auditValue } from '../lib/audit'
  import { confirmDialog } from '../lib/confirm.svelte'
  import { toast } from '../lib/toast.svelte'
  import { RANK, type AuditEntry, type Rec } from '../lib/types'

  let { uid }: { uid: string } = $props()
  let entries = $state<AuditEntry[] | null>(null)
  let failed = $state(false)
  let reload = $state(0)

  $effect(() => {
    void reload
    entries = null
    failed = false
    get<{ entries: AuditEntry[] }>(`/api/records/${uid}/history`)
      .then((r) => (entries = r.entries))
      .catch(() => (failed = true))
  })

  // --- restore: set the fields of a change back to their values before it (maintainers)
  const CORE = ['first_name', 'last_name', 'name', 'company']
  const same = (a: any, b: any) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
  /** the fields of an entry that can go back, with current and old value; the history stores company names */
  function revertible(e: AuditEntry, r: Rec) {
    if (!store.canEdit || !['update', 'import', 'merge'].includes(e.action)) return []
    const out: { key: string; now: any; old: any; value: any }[] = []
    for (const [key, [old]] of Object.entries(e.changes)) {
      if (CORE.includes(key)) {
        if (key === 'company') {
          const matches = old == null ? [null] : store.records.filter((c) => c.kind === 'company' && c.name === old).map((c) => c.uid)
          if (matches.length === 1 && !same(r.company, matches[0])) out.push({ key, now: store.companyName(r) || null, old, value: matches[0] })
        } else if (!same((r as any)[key] || null, old || null)) out.push({ key, now: (r as any)[key], old, value: old ?? '' })
        continue
      }
      const f = store.fields.find((f) => f.key === key)
      if (f && !f.archived && store.rank >= RANK[f.editable_by] && !same(r.data[key], old)) out.push({ key, now: r.data[key], old, value: old ?? null })
    }
    return out
  }

  async function restore(e: AuditEntry) {
    const r = store.byUid.get(uid)
    if (!r) return
    const items = revertible(e, r)
    const ok = await confirmDialog({
      title: t('history.restore_title'),
      message: items.map((x) => `${label(x.key)}: ${show(x.key, x.now)} → ${show(x.key, x.old)}`).join('\n'),
      confirmLabel: t('history.restore'),
    })
    if (!ok) return
    const body: Record<string, any> = { version: r.version, data: {} }
    for (const x of items) {
      if (CORE.includes(x.key)) body[x.key] = x.value
      else body.data[x.key] = x.value
    }
    try {
      store.upsert(await patch<Rec>(`/api/records/${uid}`, body))
      toast(t('history.restored'))
      reload++
    } catch (err) {
      if (err instanceof ApiError && err.code === 'version_conflict') {
        toast(t('history.conflict'), { kind: 'error' })
        store.sync()
      } else if (err instanceof ApiError && err.code === 'validation') {
        toast(Object.entries(err.fields).map(([k, c]) => `${label(k)}: ${terr(c)}`).join(' · '), { kind: 'error' })
      } else toast(err instanceof ApiError ? terr(err.code) : t('err.generic'), { kind: 'error' })
    }
  }

  const rec = { target_type: 'record' }
  const label = (key: string) => auditLabel(rec, key)
  const show = (key: string, v: any) => auditValue(rec, key, v)
</script>

{#if failed}
  <p class="muted">{t('err.generic')}</p>
{:else if !entries}
  <p class="muted">{t('common.loading')}</p>
{:else if !entries.length}
  <p class="muted">{t('history.empty')}</p>
{:else}
  <ol class="timeline">
    {#each entries as e (e.id)}
      <li>
        <div class="meta">
          <span class="action">{t(`audit.${e.action}`)}</span>
          <span class="muted">{store.userName(e.user)} · <time title={dateTime(e.at)}>{relTime(e.at)}</time></span>
          {#if store.byUid.get(uid) && revertible(e, store.byUid.get(uid)!).length}
            <button class="btn sm ghost restore" onclick={() => restore(e)} title={t('history.restore_hint')}><Undo2 size={13} />{t('history.restore')}</button>
          {/if}
        </div>
        {#if Object.keys(e.changes).length}
          <table class="changes">
            <tbody>
              {#each Object.entries(e.changes) as [key, [from, to]] (key)}
                <tr>
                  <th>{label(key)}</th>
                  <td class="from">{show(key, from)}</td>
                  <td class="arrow">→</td>
                  <td>{show(key, to)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </li>
    {/each}
  </ol>
{/if}

<style>
  .restore { margin-left: auto; }
  .timeline { list-style: none; margin: 0; padding: 0; }
  li { position: relative; padding: 0 0 18px 18px; border-left: 2px solid var(--border); margin-left: 4px; }
  li::before { content: ''; position: absolute; left: -6px; top: 4px; width: 10px; height: 10px; border-radius: 50%;
    background: var(--panel); border: 2px solid var(--accent); }
  li:last-child { border-left-color: transparent; }
  .meta { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .action { font-weight: 600; }
  .changes { margin-top: 6px; border-collapse: collapse; font-size: 13px; }
  .changes th { text-align: left; font-weight: 500; color: var(--muted); padding: 2px 12px 2px 0; white-space: nowrap; vertical-align: top; }
  .changes td { padding: 2px 6px 2px 0; vertical-align: top; white-space: pre-wrap; word-break: break-word; }
  .from { color: var(--muted); text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--muted) 50%, transparent); }
  .arrow { color: var(--faint); }
</style>
