<script lang="ts">
  import { FileUp, SkipForward } from '@lucide/svelte'
  import RecordForm from './RecordForm.svelte'
  import { go } from '../lib/router.svelte'
  import { store } from '../lib/store.svelte'
  import { t } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { type Draft, parse, toDraft } from '../lib/vcardimport'
  import type { Rec } from '../lib/types'

  /** Contacts from .vcf files: each card opens as a pre-filled new-contact form (read only: as a proposal). */
  let cards = $state<Draft[]>([])
  let at = $state(0)
  let pasted = $state('')
  let dragging = $state(false)
  let done = $state<{ created: Rec[]; proposed: number; skipped: number }>({ created: [], proposed: 0, skipped: 0 })

  const card = $derived(cards[at])
  const companyUid = (name: string) => {
    const n = name.trim().toLowerCase()
    return n ? store.records.find((r) => r.kind === 'company' && r.name.trim().toLowerCase() === n)?.uid ?? null : null
  }
  const missingCompany = $derived(card?.kind === 'person' && card.company_name && !companyUid(card.company_name) ? card.company_name : '')

  function load(text: string) {
    const found = parse(text).map((props) => toDraft(props, store.fields, (k) => store.fieldsFor(k)))
    if (!found.length) {
      toast(t('vcardimport.none'), { kind: 'error' })
      return
    }
    cards = found
    at = 0
    done = { created: [], proposed: 0, skipped: 0 }
  }

  async function files(list: FileList | null | undefined) {
    if (!list?.length) return
    load((await Promise.all([...list].map((f) => f.text()))).join('\n'))
  }

  function next(saved?: Rec, proposal?: number) {
    if (saved) done.created.push(saved)
    else if (proposal) done.proposed++
    else done.skipped++
    at++
  }
</script>

<div class="page">
  <h1>{t('vcardimport.title')}</h1>
  {#if !cards.length}
    <p class="muted">{store.canEdit ? t('vcardimport.hint') : t('vcardimport.hint_propose')}</p>
    <label class="drop" class:on={dragging}
           ondragover={(e) => { e.preventDefault(); dragging = true }} ondragleave={() => (dragging = false)}
           ondrop={(e) => { e.preventDefault(); dragging = false; files(e.dataTransfer?.files) }}>
      <FileUp size={22} />
      <span>{t('vcardimport.drop')}</span>
      <input type="file" accept=".vcf,.vcard,text/vcard,text/x-vcard" multiple onchange={(e) => files(e.currentTarget.files)} />
    </label>
    <details>
      <summary>{t('vcardimport.paste')}</summary>
      <textarea class="input" rows="8" bind:value={pasted} placeholder={'BEGIN:VCARD\nVERSION:3.0\nN:Muster;Erika\n…\nEND:VCARD'}></textarea>
      <button class="btn" disabled={!pasted.trim()} onclick={() => load(pasted)}>{t('vcardimport.read')}</button>
    </details>
  {:else if card}
    <div class="step">
      <strong>{t('vcardimport.step', { n: String(at + 1), total: String(cards.length) })}</strong>
      <button class="btn sm" onclick={() => next()}><SkipForward size={14} />{t('vcardimport.skip')}</button>
    </div>
    {#if missingCompany}<div class="note">{t('vcardimport.no_company', { name: missingCompany })}</div>{/if}
    {#if card.unmapped.length}
      <div class="note">{t('vcardimport.unmapped')} {card.unmapped.join(' · ')}</div>
    {/if}
    {#key at}
      <RecordForm rec={null} kind={card.kind} mode={store.canEdit ? 'edit' : 'propose'} photo={card.photo}
                  prefill={{ first_name: card.first_name, last_name: card.last_name, name: card.name,
                             company: card.kind === 'person' ? companyUid(card.company_name) : null, data: card.data }}
                  onclose={next} />
    {/key}
  {:else}
    <p>{t('vcardimport.done', { created: String(done.created.length), proposed: String(done.proposed), skipped: String(done.skipped) })}</p>
    <ul class="created">
      {#each done.created as r (r.uid)}<li><a href="/{r.kind}/{r.uid}">{store.name(r)}</a></li>{/each}
    </ul>
    <div class="actions">
      <button class="btn" onclick={() => (cards = [])}>{t('vcardimport.more')}</button>
      <button class="btn primary" onclick={() => go('/')}>{t('vcardimport.finish')}</button>
    </div>
  {/if}
</div>

<style>
  .page { max-width: 900px; margin: 0 auto; padding: 24px 28px; }
  h1 { font-size: 22px; margin: 0 0 12px; }
  .drop { position: relative; display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 36px 20px; margin: 14px 0;
    border: 1.5px dashed var(--border-strong); border-radius: 12px; color: var(--muted); cursor: pointer; text-align: center; }
  .drop.on, .drop:hover { border-color: var(--accent); color: var(--accent-text); background: var(--accent-soft); }
  .drop input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  details textarea { width: 100%; margin: 8px 0; font: 12px ui-monospace, monospace; }
  .step { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .note { padding: 8px 12px; margin-bottom: 10px; border-radius: 8px; background: var(--panel-2); font-size: 13px; white-space: pre-line; }
  .created { columns: 2; padding-left: 18px; }
  .actions { display: flex; gap: 8px; }
</style>
