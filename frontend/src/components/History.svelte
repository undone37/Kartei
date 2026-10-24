<script lang="ts">
  import { get } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { dateTime, relTime } from '../lib/format'
  import { t } from '../lib/i18n.svelte'
  import { auditLabel, auditValue } from '../lib/audit'
  import type { AuditEntry } from '../lib/types'

  let { uid }: { uid: string } = $props()
  let entries = $state<AuditEntry[] | null>(null)
  let failed = $state(false)

  $effect(() => {
    entries = null
    failed = false
    get<{ entries: AuditEntry[] }>(`/api/records/${uid}/history`)
      .then((r) => (entries = r.entries))
      .catch(() => (failed = true))
  })

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
