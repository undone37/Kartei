<script lang="ts">
  import { GitMerge, X } from '@lucide/svelte'
  import Avatar from './Avatar.svelte'
  import Merge from './Merge.svelte'
  import { get, post } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { t } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'

  /** a, b: the pair on the merge screen (/duplicates/<a>/<b>) */
  let { a, b }: { a?: string; b?: string } = $props()

  type Pair = { a: string; b: string; kind: 'person' | 'company'; reasons: string[] }
  let pairs = $state<Pair[] | null>(null)
  $effect(() => {
    if (!a) get<{ pairs: Pair[] }>('/api/duplicates').then((r) => (pairs = r.pairs))
  })

  async function dismiss(p: Pair) {
    await post('/api/duplicates/dismiss', { a: p.a, b: p.b })
    pairs = pairs!.filter((x) => x !== p)
    toast(t('dupes.dismissed'))
  }
</script>

{#if a && b}
  {#key a + b}<Merge {a} {b} />{/key}
{:else}
  <div class="page">
    <h1>{t('dupes.title')}</h1>
    <p class="muted">{t('dupes.hint')}</p>
    {#if !pairs}
      <p class="muted">{t('common.loading')}</p>
    {:else if !pairs.length}
      <p class="empty muted">{t('dupes.empty')}</p>
    {:else}
      <table class="grid">
        <thead><tr><th>{t('dupes.records')}</th><th>{t('dupes.reason')}</th><th></th></tr></thead>
        <tbody>
          {#each pairs as p (p.a + p.b)}
            <tr>
              <td>
                {#each [p.a, p.b] as uid (uid)}
                  {@const r = store.byUid.get(uid)}
                  {#if r}
                    <div class="who"><Avatar rec={r} size={22} /><a href="/{r.kind}/{r.uid}">{store.name(r) || '—'}</a>
                      {#if r.kind === 'person' && store.companyName(r)}<span class="muted">· {store.companyName(r)}</span>{/if}</div>
                  {/if}
                {/each}
              </td>
              <td>{#each p.reasons as reason (reason)}<span class="badge">{t(`dupes.reason_${reason}`)}</span> {/each}</td>
              <td class="act">
                <a class="btn sm" href="/duplicates/{p.a}/{p.b}"><GitMerge size={14} />{t('dupes.compare')}</a>
                <button class="btn sm" onclick={() => dismiss(p)}><X size={14} />{t('dupes.not_duplicate')}</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
{/if}

<style>
  .page { max-width: 920px; margin: 0 auto; padding: 24px 28px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  p { margin: 0 0 18px; }
  .who { display: flex; align-items: center; gap: 8px; padding: 2px 0; }
  .act { text-align: right; white-space: nowrap; }
  .act .btn { margin-left: 4px; }
  .empty { padding: 40px 0; text-align: center; }
</style>
