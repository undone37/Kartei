<script lang="ts">
  import Avatar from './Avatar.svelte'
  import { store } from '../lib/store.svelte'
  import { fold, type Indexed } from '../lib/search'
  import { t } from '../lib/i18n.svelte'
  import type { Rec } from '../lib/types'

  interface Props {
    items: Indexed[]; selected: string | null; query: string
    /** selection mode (bulk edit): a click toggles the row, shift-click a range */
    picked?: Set<string> | null; onpick?: (uid: string, shift: boolean) => void
  }
  let { items, selected, query, picked = null, onpick }: Props = $props()

  const ROW = 56
  let viewport: HTMLDivElement
  let height = $state(600)
  let scrollTop = $state(0)

  const start = $derived(Math.max(0, Math.floor(scrollTop / ROW) - 6))
  const end = $derived(Math.min(items.length, Math.ceil((scrollTop + height) / ROW) + 6))
  const visible = $derived(items.slice(start, end))

  // keep the selected row in view (keyboard navigation, deep links)
  $effect(() => {
    if (!selected || !viewport) return
    const i = items.findIndex((x) => x.rec.uid === selected)
    if (i < 0) return
    const top = i * ROW
    if (top < viewport.scrollTop) viewport.scrollTop = top
    else if (top + ROW > viewport.scrollTop + height) viewport.scrollTop = top + ROW - height
  })

  // semantic hints from the vCard mapping keep the subtitle generic for admin-defined fields
  const byTarget = $derived.by(() => {
    const m: Record<string, string[]> = {}
    for (const f of store.fields) if (f.vcard) (m[f.vcard] ??= []).push(f.key)
    return m
  })
  const firstOf = (r: Rec, targets: string[]) => {
    for (const tg of targets) for (const k of byTarget[tg] ?? []) if (r.data[k]) return String(r.data[k])
    return ''
  }

  function subtitle(r: Rec) {
    if (r.kind === 'person') {
      return [firstOf(r, ['title']), store.companyName(r)].filter(Boolean).join(' · ')
    }
    const persons = store.persons.get(r.uid)?.length ?? 0
    return [firstOf(r, ['adr_work_city']), persons ? t('list.persons', { n: persons }) : ''].filter(Boolean).join(' · ')
  }

  /** Split text into [plain, match, plain, ...] for the first token that hits. */
  function marks(text: string) {
    const f = fold(text)
    if (!query.trim() || f.length !== text.length) return [text]
    for (const tok of query.trim().split(/\s+/).map(fold).sort((a, b) => b.length - a.length)) {
      const i = f.indexOf(tok)
      if (i >= 0 && tok) return [text.slice(0, i), text.slice(i, i + tok.length), text.slice(i + tok.length)]
    }
    return [text]
  }
</script>

<div class="viewport scroll" class:picking={picked} bind:this={viewport} bind:clientHeight={height}
     onscroll={() => (scrollTop = viewport.scrollTop)} role="listbox" aria-label={t('list.results')} aria-multiselectable={picked ? true : undefined}>
  <div class="spacer" style="height:{items.length * ROW}px">
    {#each visible as { rec }, i (rec.uid)}
      <a class="row" class:sel={picked ? picked.has(rec.uid) : rec.uid === selected} href="/{rec.kind}/{rec.uid}"
         style="transform:translateY({(start + i) * ROW}px)" role="option"
         aria-selected={picked ? picked.has(rec.uid) : rec.uid === selected}
         onclick={(e) => { if (picked) { e.preventDefault(); onpick?.(rec.uid, e.shiftKey) } }}>
        {#if picked}<input type="checkbox" checked={picked.has(rec.uid)} tabindex="-1" aria-hidden="true" />{/if}
        <Avatar {rec} />
        <span class="text">
          <span class="name">
            {#each marks(store.name(rec)) as part, j}{#if j === 1}<mark>{part}</mark>{:else}{part}{/if}{/each}
          </span>
          <span class="sub">{subtitle(rec)}</span>
        </span>
      </a>
    {/each}
  </div>
  {#if !items.length}
    <div class="empty">{query ? t('list.no_results') : t('list.empty')}</div>
  {/if}
</div>

<style>
  .viewport { position: relative; height: 100%; contain: strict; }
  .spacer { position: relative; }
  .row {
    position: absolute; left: 6px; right: 6px; height: 56px; display: flex; align-items: center; gap: 10px;
    padding: 0 12px; border-radius: 8px; color: inherit; text-decoration: none;
    will-change: transform;
  }
  .picking .row { user-select: none; }
  .row input { pointer-events: none; flex: none; }
  .row:hover { background: var(--panel-2); text-decoration: none; }
  .row.sel { background: var(--accent-soft); }
  .text { min-width: 0; display: flex; flex-direction: column; }
  .name, .sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .name { font-weight: 500; }
  .sub { color: var(--muted); font-size: 12px; min-height: 17px; }
  mark { background: color-mix(in srgb, var(--accent) 22%, transparent); color: inherit; border-radius: 2px; }
  .empty { padding: 40px 20px; text-align: center; color: var(--muted); }
</style>
