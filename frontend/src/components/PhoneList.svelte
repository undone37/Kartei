<script lang="ts">
  import { ArrowLeft, Printer } from '@lucide/svelte'
  import logo from '../assets/logo.svg'
  import { store } from '../lib/store.svelte'
  import { fmt } from '../lib/format'
  import { L, i18n, t } from '../lib/i18n.svelte'
  import type { Field, Rec } from '../lib/types'

  /** A printable phone list of the contacts in the current list (search, list and filters apply); the browser's
      print dialog saves it as PDF. */
  let { items }: { items: Rec[] } = $props()

  let group = $state<'company' | 'name'>('company')
  let onlyReachable = $state(true)
  const collator = new Intl.Collator('de', { sensitivity: 'base', numeric: true })
  const nameOf = (r: Rec) => (r.kind === 'company' ? r.name : [r.last_name, r.first_name].filter(Boolean).join(', '))

  // columns: the phone and email fields; preselected are the phone fields someone in the list has a value in
  const candidates = $derived(store.fields.filter((f) => !f.archived && (f.type === 'phone' || f.type === 'email')))
  const used = (f: Field) => items.some((r) => r.data[f.key])
  let picked = $state<string[] | null>(null)
  const columns = $derived(picked ? candidates.filter((f) => picked!.includes(f.key))
                                  : candidates.filter((f) => f.type === 'phone' && used(f)).slice(0, 4))
  const role = $derived(store.fields.find((f) => f.key === 'job_title' && !f.archived))

  const reachable = (r: Rec) => !onlyReachable || columns.some((f) => r.data[f.key])
  const sorted = (rs: Rec[]) => [...rs].sort((a, b) => collator.compare(nameOf(a), nameOf(b)))

  /** company groups: the company (if listed) and its listed persons; persons without company last */
  const groups = $derived.by(() => {
    const byCompany = new Map<string, { company: Rec | null; persons: Rec[] }>()
    for (const r of items) {
      const key = r.kind === 'company' ? r.uid : r.company ?? ''
      const g = byCompany.get(key) ?? { company: key ? store.byUid.get(key) ?? null : null, persons: [] }
      if (r.kind === 'person') g.persons.push(r)
      byCompany.set(key, g)
    }
    const listed = new Set(items.map((r) => r.uid))
    return [...byCompany.entries()]
      .map(([key, g]) => ({ key, company: g.company && listed.has(g.company.uid) ? g.company : null,
                            title: g.company?.name ?? t('phonelist.no_company'), persons: sorted(g.persons.filter(reachable)) }))
      .filter((g) => g.persons.length || (g.company && reachable(g.company)))
      .sort((a, b) => (a.key === '') !== (b.key === '') ? (a.key === '' ? 1 : -1) : collator.compare(a.title, b.title))
  })
  const flat = $derived(sorted(items.filter(reachable)))
  const count = $derived(group === 'company' ? groups.reduce((n, g) => n + g.persons.length + (g.company ? 1 : 0), 0) : flat.length)
  const today = $derived(new Intl.DateTimeFormat(i18n.lang, { dateStyle: 'long' }).format(new Date()))
  const value = (r: Rec, f: Field) => (r.data[f.key] ? fmt(f, r.data[f.key]) : '')
  const toggle = (key: string, on: boolean) => {
    const now = columns.map((f) => f.key)
    picked = on ? [...now, key] : now.filter((k) => k !== key)
  }
</script>

<div class="phonelist">
  <div class="controls">
    <a href="/" class="back"><ArrowLeft size={15} />{t('phonelist.back')}</a>
    <h1>{t('phonelist.title')}</h1>
    <p class="muted">{t('phonelist.hint')}</p>
    <div class="opts">
      <div class="seg" role="radiogroup" aria-label={t('phonelist.group')}>
        <label><input type="radio" bind:group={group} value="company" /> {t('phonelist.by_company')}</label>
        <label><input type="radio" bind:group={group} value="name" /> {t('phonelist.by_name')}</label>
      </div>
      <label><input type="checkbox" bind:checked={onlyReachable} /> {t('phonelist.only_reachable')}</label>
    </div>
    <div class="opts" role="group" aria-label={t('phonelist.columns')}>
      <span class="muted">{t('phonelist.columns')}:</span>
      {#each candidates as f (f.key)}
        <label><input type="checkbox" checked={columns.includes(f)} onchange={(e) => toggle(f.key, e.currentTarget.checked)} /> {L(f.label)}</label>
      {/each}
    </div>
    <button class="btn primary" onclick={() => print()} disabled={!count}><Printer size={15} />{t('phonelist.print')}</button>
  </div>

  <article class="sheet">
    <header>
      <img src={logo} alt="" />
      <div>
        <strong>{t('phonelist.title')}</strong>
        <span>{today} · {t('list.count', { n: count })}</span>
      </div>
    </header>
    <table>
      <thead>
        <tr>
          <th>{t('core.name')}</th>
          {#if group === 'name'}<th>{t('core.company')}</th>{/if}
          {#if role}<th>{L(role.label)}</th>{/if}
          {#each columns as f (f.key)}<th>{L(f.label)}</th>{/each}
        </tr>
      </thead>
      {#if group === 'company'}
        {#each groups as g (g.key)}
          <tbody>
            <tr class="co">
              <td colspan={g.company ? 1 + (role ? 1 : 0) : 1 + (role ? 1 : 0) + columns.length}>{g.title}</td>
              {#if g.company}{#each columns as f (f.key)}<td>{value(g.company, f)}</td>{/each}{/if}
            </tr>
            {#each g.persons as r (r.uid)}
              <tr>
                <td class="nm">{nameOf(r)}</td>
                {#if role}<td>{r.data[role.key] ?? ''}</td>{/if}
                {#each columns as f (f.key)}<td class="num">{value(r, f)}</td>{/each}
              </tr>
            {/each}
          </tbody>
        {/each}
      {:else}
        <tbody>
          {#each flat as r (r.uid)}
            <tr>
              <td class="nm" class:strong={r.kind === 'company'}>{nameOf(r)}</td>
              <td>{r.kind === 'person' ? store.companyName(r) : ''}</td>
              {#if role}<td>{r.data[role.key] ?? ''}</td>{/if}
              {#each columns as f (f.key)}<td class="num">{value(r, f)}</td>{/each}
            </tr>
          {/each}
        </tbody>
      {/if}
    </table>
    {#if !count}<p class="muted">{t('phonelist.empty')}</p>{/if}
  </article>
</div>

<style>
  .phonelist { padding: 20px 28px 40px; }
  .controls { display: flex; flex-direction: column; gap: 10px; max-width: 900px; margin-bottom: 20px; }
  .controls h1 { font-size: 22px; margin: 0; }
  .controls p { margin: 0; }
  .back { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
  .opts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; }
  .opts label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
  .seg { display: flex; gap: 14px; }
  .controls .btn { align-self: flex-start; }

  .sheet { max-width: 1000px; padding: 22px 26px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); }
  .sheet header { display: flex; align-items: center; gap: 12px; padding-bottom: 12px; margin-bottom: 8px; border-bottom: 1px solid var(--border); }
  .sheet header img { width: 32px; height: 32px; }
  .sheet header div { display: flex; flex-direction: column; }
  .sheet header strong { font-size: 18px; }
  .sheet header span { color: var(--muted); font-size: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th { text-align: left; font-weight: 600; color: var(--muted); padding: 6px 10px 6px 0; border-bottom: 1px solid var(--border-strong); }
  td { padding: 3px 10px 3px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr.co td { padding-top: 12px; font-weight: 650; color: var(--accent-text); border-bottom: 1px solid var(--border-strong); }
  td.nm { padding-left: 10px; }
  td.nm.strong { font-weight: 600; padding-left: 0; }
  .num { font-variant-numeric: tabular-nums; white-space: nowrap; }

  /* printing: only the sheet, light, A4 */
  @media print {
    :global(header.top), :global(aside.side), :global(.toasts), .controls { display: none !important; }
    :global(html), :global(body), :global(.main), :global(main.pane) { display: block !important; height: auto !important;
      overflow: visible !important; background: #fff !important; color: #000 !important; }
    .phonelist { padding: 0; }
    .sheet { max-width: none; border: 0; padding: 0; background: #fff; color: #18181b; }
    thead { display: table-header-group; }
    tr { break-inside: avoid; }
    tbody { break-inside: auto; }
    tr.co { break-after: avoid; }
    tr.co td { color: #3730a3; }
    @page { size: A4; margin: 14mm 12mm; }
  }
</style>
