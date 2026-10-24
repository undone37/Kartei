<script lang="ts">
  // Side by side: pick per field which value wins, then merge one record into the other.
  import { GitMerge } from '@lucide/svelte'
  import Avatar from './Avatar.svelte'
  import { ApiError, get, post } from '../lib/api'
  import { go } from '../lib/router.svelte'
  import { store } from '../lib/store.svelte'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { dateTime, fmt, isMulti } from '../lib/format'
  import { toast } from '../lib/toast.svelte'
  import type { Rec } from '../lib/types'

  let { a, b }: { a: string; b: string } = $props()

  let recs = $state<Rec[] | null>(null)
  let pick = $state<Record<string, string>>({})
  let keep = $state('')
  let error = $state('')
  let busy = $state(false)

  function load() {
    get<{ pick: Record<string, string>; records: Rec[] }>(`/api/duplicates/preview?a=${a}&b=${b}`).then((r) => {
      recs = r.records
      pick = r.pick
      keep = [...r.records].sort((x, y) => y.updated_at.localeCompare(x.updated_at))[0].uid // the newer one
    }).catch((e) => (error = terr(e instanceof ApiError ? e.code : 'generic')))
  }
  load()

  const CORE: Record<string, string[]> = { person: ['first_name', 'last_name', 'company'], company: ['name'] }
  const rows = $derived.by(() => {
    if (!recs) return []
    const kind = recs[0].kind
    const fields = store.fieldsFor(kind)
    const show = (r: Rec, key: string): string => {
      const f = fields.find((f) => f.key === key)
      if (f) return fmt(f, r.data[key])
      if (key === 'company') return r.company ? store.byUid.get(r.company)?.name ?? '' : ''
      return String((r as any)[key] ?? '')
    }
    return [...CORE[kind], 'image', ...fields.map((f) => f.key)].filter((k) => k in pick).map((key) => {
      const f = fields.find((f) => f.key === key)
      return { key, label: f ? L(f.label) : t(`core.${key}`), multi: !!f && isMulti(f), values: recs!.map((r) => show(r, key)) }
    })
  })

  async function merge() {
    const other = recs!.find((r) => r.uid !== keep)!
    busy = true
    try {
      const rec = await post<Rec>('/api/duplicates/merge', {
        keep, other: other.uid, pick, versions: Object.fromEntries(recs!.map((r) => [r.uid, r.version])),
      })
      store.upsert(rec)
      store.remove(other.uid)
      store.sync() // moved persons, references
      toast(t('dupes.merged', { name: store.name(other) }))
      go(`/${rec.kind}/${rec.uid}`, true)
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
      if (e instanceof ApiError && e.code === 'version_conflict') load()
    } finally {
      busy = false
    }
  }
</script>

<div class="page">
  <p><a href="/duplicates">← {t('dupes.title')}</a></p>
  <h1>{t('dupes.merge_title')}</h1>
  {#if error}
    <p class="muted">{error}</p>
  {:else if !recs}
    <p class="muted">{t('common.loading')}</p>
  {:else}
    <p class="muted">{t('dupes.merge_hint')}</p>
    <table class="grid">
      <thead>
        <tr>
          <th></th>
          {#each recs as r (r.uid)}
            <th>
              <label class="keep">
                <input type="radio" name="keep" value={r.uid} bind:group={keep} />
                <Avatar rec={r} size={26} />
                <span><a href="/{r.kind}/{r.uid}">{store.name(r) || '—'}</a>
                  <span class="hint">{keep === r.uid ? t('dupes.keeps') : t('dupes.goes')} · {dateTime(r.updated_at)}</span></span>
              </label>
            </th>
          {/each}
          {#if rows.some((x) => x.multi)}<th>{t('dupes.both')}</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each rows as row (row.key)}
          <tr>
            <td class="muted">{row.label}</td>
            {#each recs as r, i (r.uid)}
              <td class:on={pick[row.key] === r.uid || pick[row.key] === 'union'}>
                <label class="val">
                  <input type="radio" name="pick-{row.key}" value={r.uid} bind:group={pick[row.key]} />
                  {#if row.key === 'image'}{#if r.image}<Avatar rec={r} size={36} />{:else}—{/if}
                  {:else}{row.values[i] || '—'}{/if}
                </label>
              </td>
            {/each}
            {#if rows.some((x) => x.multi)}
              <td>{#if row.multi}<input type="radio" name="pick-{row.key}" value="union" bind:group={pick[row.key]} aria-label={t('dupes.both')} />{/if}</td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="actions">
      <button class="btn primary" onclick={merge} disabled={busy}><GitMerge size={15} />{t('dupes.merge')}</button>
    </div>
  {/if}
</div>

<style>
  .page { max-width: 1100px; margin: 0 auto; padding: 24px 28px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  p { margin: 0 0 14px; }
  .keep, .val { display: flex; align-items: center; gap: 8px; cursor: pointer; font-weight: normal; }
  .keep > span { display: flex; flex-direction: column; }
  td.on { background: var(--accent-soft); }
  .val { overflow-wrap: anywhere; }
  .actions { display: flex; justify-content: flex-end; padding: 16px 0; }
</style>
