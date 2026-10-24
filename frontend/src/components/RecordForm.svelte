<script lang="ts">
  import { ImagePlus, Trash2, TriangleAlert } from '@lucide/svelte'
  import { onMount, tick, untrack } from 'svelte'
  import Avatar from './Avatar.svelte'
  import Combobox from './Combobox.svelte'
  import CopyFromCompany from './CopyFromCompany.svelte'
  import FieldInput from './FieldInput.svelte'
  import { ApiError, api, patch, post } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { isEmpty } from '../lib/format'
  import { validate } from '../lib/validate'
  import { L, i18n, t, terr } from '../lib/i18n.svelte'
  import { digits, fold } from '../lib/search'
  import { groupFields } from '../lib/sections'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import { RANK, type Field, type Kind, type Proposal, type Rec } from '../lib/types'

  interface Props {
    rec: Rec | null; kind: Kind; presetCompany?: string | null; onclose: (saved?: Rec) => void
    /** propose: the change goes to a maintainer (with `proposal`: edit that pending proposal);
        adjust: a maintainer edits `proposal` and applies it */
    mode?: 'edit' | 'propose' | 'adjust'; proposal?: Proposal | null
  }
  let { rec, kind, presetCompany = null, onclose, mode = 'edit', proposal = null }: Props = $props()
  const propose = untrack(() => mode !== 'edit')
  let comment = $state(untrack(() => (mode === 'propose' ? proposal?.comment ?? '' : '')))

  const blank = () => ({ first_name: '', last_name: '', name: '', company: presetCompany, data: {} as Record<string, any> })
  // the form is keyed per record by its parent, so capturing the initial record is intended
  const initial = untrack(() => rec)
  let draft = $state(initial ? structuredClone({ first_name: initial.first_name, last_name: initial.last_name, name: initial.name,
    company: initial.company, data: $state.snapshot(initial.data) }) : blank())
  // start from the proposed values
  for (const [k, v] of Object.entries(untrack(() => proposal)?.changes.core ?? {})) (draft as any)[k] = v
  for (const [k, v] of Object.entries(untrack(() => proposal)?.changes.data ?? {})) {
    if (v == null) delete draft.data[k]
    else draft.data[k] = v
  }
  let baseVersion = $state(initial?.version ?? 0)
  let errors = $state<Record<string, string>>({})
  let saving = $state(false)
  let conflict = $state<Rec | null>(null)
  let confirmDiscard = $state(false)
  let pendingImage = $state<Blob | null>(null)
  let pendingPreview = $state<string | null>(null)
  let firstInput: HTMLInputElement | undefined = $state()

  const fields = $derived(store.fieldsFor(kind))
  const canEdit = (f: Field) => Math.max(store.rank, propose ? RANK.maintainer : 0) >= RANK[f.editable_by]
  const editable = $derived(fields.filter(canEdit))
  /** sections in section order; the fields of the section keyed like the kind ("person"/"company") go into the header block */
  const sections = $derived(groupFields(fields, store.sections))
  const coreFields = $derived(sections.find((s) => s.section?.key === kind)?.fields ?? [])
  const otherSections = $derived(sections.filter((s) => s.section?.key !== kind).map((g) => ({
    id: g.section?.id ?? 0, title: g.section ? L(g.section.label) : t('core.section_other'), fields: g.fields,
  })))

  const companies = $derived(
    store.index.filter((x) => x.rec.kind === 'company').map((x) => ({ value: x.rec.uid, label: x.rec.name })),
  )
  const company = $derived(draft.company ? store.byUid.get(draft.company) ?? null : null)

  const dirty = $derived(
    JSON.stringify($state.snapshot(draft)) !==
      JSON.stringify(rec ? { first_name: rec.first_name, last_name: rec.last_name, name: rec.name, company: rec.company, data: rec.data } : blank()),
  )

  // --- duplicates (instant, from memory)
  const duplicates = $derived.by(() => {
    const emails = new Set<string>(), phones = new Set<string>()
    for (const f of fields) {
      const v = draft.data[f.key]
      if (isEmpty(v)) continue
      if (f.type === 'email') emails.add(String(v).toLowerCase())
      if (f.type === 'phone' && digits(String(v)).length >= 6) phones.add(digits(String(v)))
    }
    const name = fold(kind === 'person' ? `${draft.first_name} ${draft.last_name}` : draft.name).trim()
    if (!emails.size && !phones.size && name.length < 3) return []
    const out: { rec: Rec; why: string }[] = []
    for (const { rec: r } of store.index) {
      if (r.uid === rec?.uid || r.kind !== kind) continue
      let why = ''
      for (const f of fields) {
        const v = r.data[f.key]
        if (isEmpty(v)) continue
        if (f.type === 'email' && emails.has(String(v).toLowerCase())) why = t('dup.email')
        else if (f.type === 'phone' && phones.has(digits(String(v)))) why = t('dup.phone')
      }
      if (!why && name.length >= 3 && fold(store.name(r)).trim() === name &&
          (kind === 'company' || r.company === draft.company)) why = t('dup.name')
      if (why) out.push({ rec: r, why })
      if (out.length >= 3) break
    }
    return out
  })

  onMount(() => firstInput?.focus())

  function setData(key: string, value: any) {
    draft.data[key] = value
    if (errors[key]) delete errors[key]
  }

  function normalized(data: Record<string, any>) {
    const out: Record<string, any> = {}
    for (const f of fields) {
      if (!(f.key in data)) continue
      let v = data[f.key]
      if (f.type === 'decimal' && typeof v === 'string' && i18n.lang === 'en') v = v.replace(/,/g, '')
      out[f.key] = v
    }
    return out
  }

  /** the same checks as the server, so problems show at once and the first one gets the focus */
  function clientErrors() {
    const found: Record<string, string> = {}
    if (kind === 'person' ? !(draft.first_name.trim() || draft.last_name.trim()) : !draft.name.trim())
      found[kind === 'person' ? 'last_name' : 'name'] = 'required'
    for (const f of fields) {
      if (!canEdit(f)) continue
      const e = validate(f, draft.data[f.key])
      if (e) found[f.key] = e
    }
    return found
  }

  async function save() {
    if (saving) return
    errors = clientErrors()
    if (Object.keys(errors).length) {
      toast(t('form.fix_errors'), { kind: 'error' })
      await tick()
      document.querySelector<HTMLElement>('.form .invalid, .form [aria-invalid="true"]')?.focus()
      return
    }
    saving = true
    try {
      let saved: Rec
      const data = normalized($state.snapshot(draft.data))
      if (!rec) {
        const core = kind === 'person'
          ? { first_name: draft.first_name, last_name: draft.last_name, company: draft.company }
          : { name: draft.name }
        saved = await post<Rec>('/api/records', { kind, ...core, data: Object.fromEntries(Object.entries(data).filter(([, v]) => !isEmpty(v))) })
        if (pendingImage) saved = await api<Rec>('PUT', `/api/img/${saved.uid}`, pendingImage)
        toast(t('form.created', { name: store.name(saved) }))
      } else {
        // diff against the version this form started from, not the latest one: after "keep mine" in a
        // conflict only the fields the user actually changed are sent, the colleague's other edits stay
        const base = initial!
        const body: Record<string, any> = { version: baseVersion }
        for (const k of ['first_name', 'last_name', 'name', 'company'] as const) if (draft[k] !== base[k]) body[k] = draft[k]
        const changed: Record<string, any> = {}
        for (const k of new Set([...Object.keys(data), ...Object.keys(base.data)])) {
          if (fields.some((f) => f.key === k && canEdit(f)) && JSON.stringify(data[k] ?? null) !== JSON.stringify(base.data[k] ?? null)) {
            changed[k] = data[k] ?? null
          }
        }
        if (Object.keys(changed).length) body.data = changed
        if (mode === 'propose') {
          const payload = { ...body, kind: 'change', comment }
          if (proposal) await patch(`/api/proposals/${proposal.id}`, payload)
          else await post(`/api/records/${rec.uid}/proposals`, payload)
          toast(t('proposal.sent'))
          store.sync()
          onclose()
          return
        }
        if (mode === 'adjust') {
          const { version: _, ...override } = body
          const r = await post<{ record: Rec }>(`/api/proposals/${proposal!.id}/accept`, { override, note: comment })
          store.upsert(r.record)
          toast(t('proposal.accepted'))
          store.sync()
          onclose(r.record)
          return
        }
        saved = Object.keys(body).length > 1 ? await patch<Rec>(`/api/records/${rec.uid}`, body) : rec
      }
      store.upsert(saved)
      onclose(saved)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') {
        errors = e.fields
        toast(t('form.fix_errors'), { kind: 'error' })
      } else if (e instanceof ApiError && e.code === 'version_conflict') {
        conflict = e.body.record
      } else {
        toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
      }
    } finally {
      saving = false
    }
  }

  function keepMine() {
    baseVersion = conflict!.version
    store.upsert(conflict!)
    conflict = null
    save()
  }

  function takeTheirs() {
    store.upsert(conflict!)
    onclose(conflict!)
  }

  function cancel() {
    if (dirty && !confirmDiscard) confirmDiscard = true
    else onclose()
  }

  function onkey(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault()
      save()
    } else if (e.key === 'Escape' && !e.defaultPrevented) {
      e.preventDefault()
      cancel()
    }
  }

  // --- image: downscale in the browser so uploads stay small and fast
  async function pickImage(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0]
    if (!file) return
    try {
      const bmp = await createImageBitmap(file)
      const scale = Math.min(1, 512 / Math.max(bmp.width, bmp.height))
      const canvas = new OffscreenCanvas(Math.round(bmp.width * scale), Math.round(bmp.height * scale))
      canvas.getContext('2d')!.drawImage(bmp, 0, 0, canvas.width, canvas.height)
      const png = kind === 'company' && file.type === 'image/png'
      const blob = await canvas.convertToBlob({ type: png ? 'image/png' : 'image/jpeg', quality: 0.85 })
      if (rec) {
        const saved = await api<Rec>('PUT', `/api/img/${rec.uid}`, blob)
        store.upsert(saved)
        baseVersion = saved.version
        rec = saved
      } else {
        pendingImage = blob
        pendingPreview = URL.createObjectURL(blob)
      }
    } catch (err) {
      toast(err instanceof ApiError ? terr(err.code) : t('err.invalid_image'), { kind: 'error' })
    }
  }

  async function removeImage() {
    if (!rec) {
      pendingImage = null
      pendingPreview = null
      return
    }
    // the stored image is deleted at once, outside of saving the form
    const ok = await confirmDialog({ title: t('form.remove_image_title'), message: t('form.remove_image_text'),
                                     confirmLabel: t('form.remove_image'), danger: true })
    if (!ok) return
    const saved = await api<Rec>('DELETE', `/api/img/${rec.uid}`)
    store.upsert(saved)
    baseVersion = saved.version
    rec = saved
  }
</script>

<svelte:window onkeydown={onkey} />

<form class="form" onsubmit={(e) => { e.preventDefault(); save() }} novalidate>
  {#if conflict}
    <div class="banner warn">
      <TriangleAlert size={16} />
      <span>{t('form.conflict', { user: store.userName(conflict.updated_by) })}</span>
      <button type="button" class="btn sm" onclick={takeTheirs}>{t('form.take_theirs')}</button>
      <button type="button" class="btn sm primary" onclick={keepMine}>{t('form.keep_mine')}</button>
    </div>
  {/if}
  {#if confirmDiscard}
    <div class="banner">
      <span>{t('form.discard_q')}</span>
      <button type="button" class="btn sm" onclick={() => (confirmDiscard = false)}>{t('form.keep_editing')}</button>
      <button type="button" class="btn sm danger" onclick={() => onclose()}>{t('form.discard')}</button>
    </div>
  {/if}

  {#if propose}
    <div class="banner">{mode === 'adjust' ? t('proposal.adjust_hint', { user: proposal?.proposer ?? '' }) : t('proposal.form_hint')}</div>
  {/if}

  <section class="core">
    <div class="photo" class:hidden={propose}>
      {#if pendingPreview}
        <img src={pendingPreview} alt="" class="preview" class:company={kind === 'company'} />
      {:else if rec}
        <Avatar {rec} size={72} />
      {:else}
        <Avatar rec={{ uid: 'new', kind, first_name: draft.first_name, last_name: draft.last_name } as Rec} size={72} />
      {/if}
      <div class="photo-actions">
        <label class="btn icon sm ghost" title={t('form.image')}>
          <ImagePlus size={15} />
          <input type="file" accept="image/png,image/jpeg,image/webp" hidden onchange={pickImage} />
        </label>
        {#if rec?.image || pendingImage}
          <button type="button" class="btn icon sm ghost" title={t('form.remove_image')} onclick={removeImage}><Trash2 size={15} /></button>
        {/if}
      </div>
    </div>
    <div class="grid">
      {#if kind === 'person'}
        <div>
          <label class="label" for="first_name">{t('core.first_name')}</label>
          <input id="first_name" class="input" bind:this={firstInput} bind:value={draft.first_name} autocomplete="off" />
        </div>
        <div>
          <label class="label" for="last_name">{t('core.last_name')} *</label>
          <input id="last_name" class="input" class:invalid={errors.last_name} bind:value={draft.last_name} autocomplete="off"
                 oninput={() => delete errors.last_name} />
          {#if errors.last_name}<div class="error-text">{terr(errors.last_name)}</div>{/if}
        </div>
        <div class="wide">
          <label class="label" for="company">{t('core.company')}</label>
          <Combobox id="company" options={companies} value={draft.company} placeholder={t('form.pick_company')}
                    invalid={!!errors.company} onchange={(v) => (draft.company = v)} />
        </div>
      {:else}
        <div class="wide">
          <label class="label" for="name">{t('core.name')} *</label>
          <input id="name" class="input" class:invalid={errors.name} bind:this={firstInput} bind:value={draft.name} autocomplete="off"
                 oninput={() => delete errors.name} />
          {#if errors.name}<div class="error-text">{terr(errors.name)}</div>{/if}
        </div>
      {/if}
      {#each coreFields as f (f.key)}
        <FieldInput field={f} value={draft.data[f.key]} error={errors[f.key]} disabled={!canEdit(f)} company={kind === 'company' ? rec?.uid : draft.company} onchange={(v) => setData(f.key, v)} />
      {/each}
    </div>
  </section>

  {#if duplicates.length}
    <div class="banner warn dup">
      <TriangleAlert size={16} />
      <span>{t('dup.title')}</span>
      {#each duplicates as d (d.rec.uid)}
        <a href="/{d.rec.kind}/{d.rec.uid}" target="_blank" rel="noopener">{store.name(d.rec)}</a>
        <span class="muted">({d.why})</span>
      {/each}
    </div>
  {/if}

  {#if kind === 'person' && company}
    <CopyFromCompany {company} data={draft.data} {editable} onapply={(p) => { for (const [k, v] of Object.entries(p)) setData(k, v) }} />
  {/if}

  {#each otherSections as s (s.id)}
    <section>
      <h3>{s.title}</h3>
      <div class="grid">
        {#each s.fields as f (f.key)}
          <FieldInput field={f} value={draft.data[f.key]} error={errors[f.key]} disabled={!canEdit(f)} company={kind === 'company' ? rec?.uid : draft.company} onchange={(v) => setData(f.key, v)} />
        {/each}
      </div>
    </section>
  {/each}

  {#if propose}
    <div>
      <label class="label" for="proposal-comment">{mode === 'adjust' ? t('proposal.note') : t('proposal.comment')}</label>
      <textarea id="proposal-comment" class="input" rows="2" bind:value={comment}
                placeholder={mode === 'adjust' ? t('proposal.note_ph') : t('proposal.comment_ph')}></textarea>
    </div>
  {/if}

  <div class="footer">
    <span class="hint"><kbd>Ctrl</kbd> + <kbd>S</kbd> {t('form.save_hint')} · <kbd>Esc</kbd> {t('form.cancel_hint')}</span>
    <button type="button" class="btn" onclick={cancel}>{t('common.cancel')}</button>
    <button type="submit" class="btn primary" disabled={saving}>{mode === 'adjust' ? t('proposal.accept') : propose ? t('proposal.send') : rec ? t('common.save') : t('common.create')}</button>
  </div>
</form>

<style>
  .form { display: flex; flex-direction: column; gap: 4px; padding-bottom: 80px; }
  section { margin-bottom: 20px; }
  h3 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 10px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px 16px; }
  .wide { grid-column: 1 / -1; }
  .core { display: flex; gap: 20px; align-items: flex-start; }
  .core .grid { flex: 1; }
  .hidden { display: none !important; }
  .photo { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .photo-actions { display: flex; gap: 2px; }
  .preview { width: 72px; height: 72px; border-radius: 50%; object-fit: cover; }
  .preview.company { border-radius: 22%; object-fit: contain; background: #fff; }
  .banner { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 8px 12px; border-radius: 8px;
    background: var(--panel-2); margin-bottom: 12px; }
  .banner.warn { background: var(--warn-soft); color: var(--warn); }
  .banner.warn a { font-weight: 500; }
  .banner > span:first-of-type { flex: 1 1 auto; }
  .dup > span:first-of-type { flex: 0 0 auto; }
  .footer {
    position: sticky; bottom: 0; display: flex; align-items: center; gap: 8px; justify-content: flex-end;
    padding: 12px 0; margin-top: 8px; background: linear-gradient(to bottom, transparent, var(--panel) 30%);
  }
  .footer .hint { margin-right: auto; }
  @media (max-width: 640px) {
    .core { flex-direction: column; align-items: stretch; }
    .footer .hint { display: none; }
  }
</style>
