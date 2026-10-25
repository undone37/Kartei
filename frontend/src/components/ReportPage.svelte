<script lang="ts">
  import { ArrowLeft, Printer } from '@lucide/svelte'
  import { untrack } from 'svelte'
  import logo from '../assets/logo.svg'
  import { get } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { dateTime, fmt } from '../lib/format'
  import { L, t } from '../lib/i18n.svelte'
  import { auditLabel, auditValue } from '../lib/audit'
  import type { AuditEntry, Proposal, Rec } from '../lib/types'

  /** Data subject access report (GDPR Art. 15) for one contact, admins only; printed or saved as PDF by the browser. */
  let { uid }: { uid: string } = $props()
  type Recipient = { system: string; name?: string; fields?: { de: string; en: string }[]; detail?: string[] }
  type Report = { generated_at: string; generated_by: string; record: Rec; image: boolean; in_trash: boolean
                  company: string | null; history: AuditEntry[]; proposals: (Proposal & { decided_at: string | null })[]
                  reviews: { created_at: string; done_at: string | null; assignee: string; outcome: string }[]
                  recipients: Recipient[] }
  let report = $state<Report | null>(null)
  let failed = $state(false)
  // the page is keyed per contact by its parent, so loading once is intended
  get<Report>(`/api/records/${untrack(() => uid)}/report`).then((r) => (report = r), () => (failed = true))

  const rec = $derived(report?.record)
  const values = $derived.by(() => {
    if (!rec) return []
    const core = rec.kind === 'company' ? [{ label: t('core.name'), value: rec.name }]
      : [{ label: t('core.first_name'), value: rec.first_name }, { label: t('core.last_name'), value: rec.last_name },
         { label: t('core.company'), value: report!.company ?? '' }]
    const data = store.fields.filter((f) => rec.data[f.key] != null && rec.data[f.key] !== '')
      .map((f) => ({ label: L(f.label), value: fmt(f, rec.data[f.key]) }))
    return [...core.filter((x) => x.value), ...data]
  })
  const sysName = (r: Recipient) => t(`report.sys.${r.system}`, { name: r.name ?? '' })
  const changes = (e: AuditEntry) => Object.entries(e.changes ?? {})
    .map(([k, [a, b]]) => `${auditLabel(e, k)}: ${a == null ? '' : auditValue(e, k, a) + ' → '}${auditValue(e, k, b)}`)
</script>

<div class="report">
  <div class="controls">
    <a href="/{rec?.kind ?? 'person'}/{uid}" class="back"><ArrowLeft size={15} />{t('report.back')}</a>
    <button class="btn primary" disabled={!report} onclick={() => print()}><Printer size={15} />{t('report.print')}</button>
  </div>
  {#if failed}
    <p class="muted">{t('err.generic')}</p>
  {:else if report && rec}
    <article class="sheet">
      <header>
        <img src={logo} alt="" />
        <div>
          <strong>{t('report.title')}: {store.name(rec)}</strong>
          <span>{t('report.subtitle')}</span>
          <span>{t('report.generated', { date: dateTime(report.generated_at), user: report.generated_by })}</span>
        </div>
      </header>

      <h2>{t('report.data')}</h2>
      {#if report.in_trash}<p>{t('report.in_trash')}</p>{/if}
      <table class="kv"><tbody>
        {#each values as v (v.label)}<tr><th>{v.label}</th><td>{v.value}</td></tr>{/each}
        {#if report.image}<tr><th>{t('report.image')}</th><td>✓</td></tr>{/if}
      </tbody></table>

      <h2>{t('report.recipients')}</h2>
      {#if report.recipients.length}
        <p>{t('report.recipients_hint')}</p>
        <ul>
          {#each report.recipients as r, i (i)}
            <li><strong>{sysName(r)}</strong>
              {#if r.fields}<span class="muted"> – {t('report.fields')} {r.fields.map((f) => L(f)).join(', ') || t('report.none')}</span>{/if}
              {#if r.detail}<span class="muted"> – {t('report.columns')} {r.detail.join(', ') || t('report.none')}</span>{/if}
            </li>
          {/each}
        </ul>
      {:else}<p class="muted">{t('report.none')}</p>{/if}

      <h2>{t('report.history')}</h2>
      <table class="log">
        <thead><tr><th>{t('report.when')}</th><th>{t('report.who')}</th><th>{t('report.what')}</th></tr></thead>
        <tbody>
          {#each report.history as e (e.id)}
            <tr><td class="nw">{dateTime(e.at)}</td><td>{e.user}</td>
              <td><strong>{t(`audit.${e.action}`)}</strong>{#each changes(e) as c (c)}<div class="muted">{c}</div>{/each}</td></tr>
          {/each}
        </tbody>
      </table>

      {#if report.proposals.length}
        <h2>{t('report.proposals')}</h2>
        <ul>{#each report.proposals as p (p.id)}<li>{dateTime(p.created_at)} · {p.proposer} · {p.kind} · {p.status}{#if p.comment} – „{p.comment}“{/if}</li>{/each}</ul>
      {/if}
      {#if report.reviews.length}
        <h2>{t('report.reviews')}</h2>
        <ul>{#each report.reviews as r, i (i)}<li>{dateTime(r.created_at)} · {store.userName(r.assignee)}{#if r.done_at} · {dateTime(r.done_at)} {r.outcome}{/if}</li>{/each}</ul>
      {/if}
    </article>
  {/if}
</div>

<style>
  .report { padding: 20px 28px 40px; }
  .controls { display: flex; align-items: center; justify-content: space-between; max-width: 900px; margin-bottom: 16px; }
  .back { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
  .sheet { max-width: 900px; padding: 24px 28px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); font-size: 13px; }
  header { display: flex; gap: 12px; align-items: flex-start; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
  header img { width: 32px; height: 32px; }
  header div { display: flex; flex-direction: column; gap: 2px; }
  header strong { font-size: 18px; }
  header span { color: var(--muted); font-size: 12px; }
  h2 { font-size: 14px; margin: 20px 0 6px; color: var(--accent-text); }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 4px 12px 4px 0; border-bottom: 1px solid var(--border); vertical-align: top; }
  .kv th { width: 34%; font-weight: 500; color: var(--muted); }
  .log th { color: var(--muted); font-weight: 600; }
  .nw { white-space: nowrap; }
  ul { margin: 4px 0; padding-left: 18px; }
  @media print {
    :global(header.top), :global(aside.side), :global(.toasts), .controls { display: none !important; }
    :global(html), :global(body), :global(.main), :global(main.pane) { display: block !important; height: auto !important;
      overflow: visible !important; background: #fff !important; color: #000 !important; }
    .report { padding: 0; }
    .sheet { border: 0; padding: 0; max-width: none; background: #fff; color: #18181b; }
    tr { break-inside: avoid; }
    h2 { break-after: avoid; }
    @page { size: A4; margin: 15mm 14mm; }
  }
</style>
