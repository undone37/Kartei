<script lang="ts">
  import { get } from '../lib/api'
  import { dateTime } from '../lib/format'
  import { t } from '../lib/i18n.svelte'
  import { auditLabel, auditObject, auditValue, visibleChanges } from '../lib/audit'
  import { store } from '../lib/store.svelte'
  import type { AuditEntry, Field } from '../lib/types'

  // all fields incl. archived ones, so old entries still get names
  let fields = $state<Field[]>(store.fields)
  get<{ fields: Field[] }>('/api/admin/fields').then((r) => (fields = r.fields)).catch(() => {})

  let entries = $state<AuditEntry[]>([])
  let more = $state(false)
  let type = $state('')
  let q = $state('')
  let timer = 0

  async function load(append = false) {
    const p = new URLSearchParams()
    if (type) p.set('target_type', type)
    if (q) p.set('q', q)
    if (append && entries.length) p.set('before', String(entries[entries.length - 1].id))
    const r = await get<{ entries: AuditEntry[]; more: boolean }>(`/api/admin/audit?${p}`)
    entries = append ? [...entries, ...r.entries] : r.entries
    more = r.more
  }
  load()
</script>

<div class="toolbar">
  <select class="select" bind:value={type} onchange={() => load()}>
    <option value="">{t('audit.all_types')}</option>
    {#each ['record', 'proposal', 'field', 'section', 'user', 'settings', 'export', 'token', 'webhook'] as ty}<option value={ty}>{t(`audit.type.${ty}`)}</option>{/each}
  </select>
  <input class="input" placeholder={t('audit.search')} bind:value={q} oninput={() => { clearTimeout(timer); timer = setTimeout(() => load(), 250) }} />
</div>

<table class="grid">
  <thead><tr><th>{t('audit.when')}</th><th>{t('audit.who')}</th><th>{t('audit.what')}</th><th>{t('audit.object')}</th><th>{t('audit.changes')}</th></tr></thead>
  <tbody>
    {#each entries as e (e.id)}
      {@const o = auditObject(e, fields)}
      <tr>
        <td class="nowrap muted tabular">{dateTime(e.at)}</td>
        <td title={e.user}>{store.userName(e.user)}</td>
        <td><span class="badge">{t(`audit.${e.action}`)}</span></td>
        <td>
          {#if o.href}<a href={o.href}>{o.name}</a>{:else}{o.name}{/if}
          <div class="hint">{o.type}</div>
        </td>
        <td class="changes">
          {#each visibleChanges(e).slice(0, 6) as [k, [a, b]]}
            {@const from = auditValue(e, k, a, fields)}
            <div title="{auditLabel(e, k, fields)}: {from} → {auditValue(e, k, b, fields)}">
              <span class="k">{auditLabel(e, k, fields)}</span>
              {#if from !== '—'}<span class="from">{from}</span> →{/if}
              {auditValue(e, k, b, fields)}
            </div>
          {/each}
          {#if visibleChanges(e).length > 6}<div class="hint">+{visibleChanges(e).length - 6}</div>{/if}
        </td>
      </tr>
    {/each}
  </tbody>
</table>
{#if more}<div class="more"><button class="btn" onclick={() => load(true)}>{t('audit.more')}</button></div>{/if}

<style>
  .toolbar { display: flex; gap: 8px; margin-bottom: 12px; max-width: 560px; }
  .toolbar .select { width: 200px; }
  .nowrap { white-space: nowrap; }
  .changes { font-size: 12px; max-width: 480px; }
  .changes > div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .k { color: var(--muted); }
  .from { color: var(--muted); text-decoration: line-through; }
  .more { display: flex; justify-content: center; padding: 16px; }
</style>
