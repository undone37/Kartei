<script lang="ts">
  import Avatar from './Avatar.svelte'
  import { store } from '../lib/store.svelte'
  import { orgTree, type OrgNode } from '../lib/orgchart'
  import type { Rec } from '../lib/types'

  /** the company's persons as a tree along the "reports to" field; a nested list, so keyboard and screen readers just work */
  let { staff, field }: { staff: Rec[]; field: string } = $props()
  const roots = $derived(orgTree(staff, field, (r) => store.name(r)))
  const titleKey = $derived(store.fields.find((f) => f.vcard === 'title' && !f.archived)?.key)
  const job = (r: Rec) => (titleKey ? r.data[titleKey] : '') ?? ''
</script>

{#snippet tree(nodes: OrgNode[])}
  <ul>
    {#each nodes as n (n.rec.uid)}
      <li>
        <a class="person" href="/person/{n.rec.uid}">
          <Avatar rec={n.rec} size={28} />
          <span><strong>{store.name(n.rec)}</strong>{#if job(n.rec)}<small>{job(n.rec)}</small>{/if}</span>
        </a>
        {#if n.children.length}{@render tree(n.children)}{/if}
      </li>
    {/each}
  </ul>
{/snippet}

<div class="org">{@render tree(roots)}</div>

<style>
  /* connector lines: each nested item hangs off a vertical line with a short horizontal tick */
  .org :global(ul) { list-style: none; margin: 0; padding-left: 0; }
  .org :global(ul ul) { margin-left: 13px; padding-left: 20px; }
  .org :global(ul ul > li) { position: relative; }
  .org :global(ul ul > li::before) { content: ''; position: absolute; left: -20px; top: 20px; width: 16px; border-top: 1px solid var(--border-strong); }
  .org :global(ul ul > li::after) { content: ''; position: absolute; left: -20px; top: 0; bottom: 0; border-left: 1px solid var(--border-strong); }
  .org :global(ul ul > li:last-child::after) { bottom: auto; height: 20px; }  /* the line stops at the last tick */
  .org :global(li) { padding: 3px 0; }
  .person { display: inline-flex; align-items: center; gap: 10px; padding: 4px 10px 4px 4px; border-radius: 8px; color: var(--text); }
  .person:hover { background: var(--panel-2); text-decoration: none; }
  .person span { display: flex; flex-direction: column; line-height: 1.25; }
  strong { font-weight: 500; }
  small { color: var(--muted); font-size: 12.5px; }
</style>
