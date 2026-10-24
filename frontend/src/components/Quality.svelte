<script lang="ts">
  import { Copy } from '@lucide/svelte'
  import { get } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { fmt } from '../lib/format'

  type Item = string | { uid: string; key: string; error: string }
  type Section = { count: number; items: Item[] }
  let q = $state<Record<string, any> | null>(null)
  get('/api/quality').then((r) => (q = r))

  const SECTIONS = ['no_responsible', 'invalid', 'no_reach', 'no_company', 'empty_company', 'never_reviewed', 'overdue']
  const uidOf = (i: Item) => (typeof i === 'string' ? i : i.uid)
  const field = (key: string) => store.fields.find((f) => f.key === key)
</script>

<div class="page">
  <h1>{t('quality.title')}</h1>
  <p class="muted">{t('quality.hint')}</p>
  {#if !q}
    <p class="muted">{t('common.loading')}</p>
  {:else}
    <a class="card row dup" href="/duplicates">
      <Copy size={16} /><span>{t('quality.duplicates')}</span>
      <span class="badge" class:ok={!q.duplicates.count} class:warn={q.duplicates.count}>{q.duplicates.count}</span>
    </a>
    {#each SECTIONS.filter((k) => q![k]) as k (k)}
      {@const s = q[k] as Section}
      <details class="card">
        <summary class="row">
          <span>{t(`quality.sec_${k}`, { months: q.review_interval_months })}</span>
          <span class="badge" class:ok={!s.count} class:warn={s.count}>{s.count}</span>
        </summary>
        <ul>
          {#each s.items as item, i (i)}
            {@const r = store.byUid.get(uidOf(item))}
            <li>
              {#if r}<a href="/{r.kind}/{r.uid}">{store.name(r) || '—'}</a>
                {#if r.kind === 'person' && store.companyName(r)}<span class="muted"> · {store.companyName(r)}</span>{/if}
                {#if r.kind === 'company'}<span class="badge">{t('kind.company')}</span>{/if}
              {:else}<span class="muted">{uidOf(item)}</span>{/if}
              {#if typeof item !== 'string'}
                {@const f = field(item.key)}
                <span class="err">{f ? L(f.label) : item.key}: {terr(item.error)}</span>
                {#if r && f}<span class="muted val">„{fmt(f, r.data[item.key])}“</span>{/if}
              {/if}
            </li>
          {/each}
        </ul>
        {#if s.count > s.items.length}<p class="hint more">{t('quality.more', { n: s.count - s.items.length })}</p>{/if}
      </details>
    {/each}
  {/if}
</div>

<style>
  .page { max-width: 920px; margin: 0 auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 10px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  p { margin: 0 0 8px; }
  .row { display: flex; align-items: center; gap: 10px; padding: 12px 16px; cursor: pointer; }
  .row .badge { margin-left: auto; }
  .dup { color: var(--text); }
  .dup:hover { text-decoration: none; background: var(--panel-2); }
  summary { list-style: none; }
  summary::-webkit-details-marker { display: none; }
  details[open] summary { border-bottom: 1px solid var(--border); }
  ul { margin: 0; padding: 8px 16px 12px; list-style: none; display: grid; gap: 4px; max-height: 420px; overflow: auto; }
  li { font-size: 13.5px; }
  .err { color: var(--danger); margin-left: 8px; font-size: 12.5px; }
  .val { font-size: 12.5px; margin-left: 4px; }
  .more { padding: 0 16px 12px; }
</style>
