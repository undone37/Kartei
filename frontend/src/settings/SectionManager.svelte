<script lang="ts">
  import { ArrowDown, ArrowUp, Plus, Trash2, X } from '@lucide/svelte'
  import { ApiError, del, patch, post } from '../lib/api'
  import { confirmDialog } from '../lib/confirm.svelte'
  import { L, t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import type { Field, Section } from '../lib/types'

  interface Props { sections: Section[]; fields: Field[]; onchanged: () => void; onclose: () => void }
  let { sections, fields, onchanged, onclose }: Props = $props()

  let label = $state({ de: '', en: '' })
  // deleting a section in use: which one, and where its fields go (section id or 'other')
  let moving = $state<number | null>(null)
  let moveTo = $state('other')
  const used = (s: Section) => fields.filter((f) => !f.archived && f.section === s.id).length
  const fail = (e: unknown) => toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })

  async function add() {
    try {
      await post('/api/admin/sections', { label })
      label = { de: '', en: '' }
      onchanged()
    } catch (e) { fail(e) }
  }

  async function rename(s: Section, lang: 'de' | 'en', value: string) {
    if (value.trim() === s.label[lang]) return
    try {
      await patch(`/api/admin/sections/${s.id}`, { label: { ...s.label, [lang]: value } })
      toast(t('sections.saved'))
    } catch (e) { fail(e) }
    onchanged()
  }

  async function move(i: number, delta: number) {
    const ids = sections.map((s) => s.id)
    ;[ids[i], ids[i + delta]] = [ids[i + delta], ids[i]]
    try { await post('/api/admin/sections/reorder', { ids }) } catch (e) { fail(e) }
    onchanged()
  }

  async function remove(s: Section) {
    if (used(s)) {
      moving = s.id
      moveTo = 'other'
      return
    }
    if (!(await confirmDialog({ title: t('sections.delete_title'), message: t('sections.delete_q', { name: L(s.label) }), confirmLabel: t('common.delete'), danger: true }))) return
    try { await del(`/api/admin/sections/${s.id}`) } catch (e) { fail(e) }
    onchanged()
  }

  async function moveAndRemove(s: Section) {
    const to = moveTo
    const target = to === 'other' ? t('core.section_other') : L(sections.find((x) => String(x.id) === to)?.label)
    if (!(await confirmDialog({ title: t('sections.delete_title'), message: t('sections.move_delete_q', { name: L(s.label), target }), confirmLabel: t('common.delete'), danger: true }))) return
    try { await del(`/api/admin/sections/${s.id}?move_to=${to}`) } catch (e) { fail(e) }
    moving = null
    onchanged()
  }
</script>

<aside class="sections card">
  <header>
    <h2>{t('fields.sections')}</h2>
    <button class="btn icon sm ghost" onclick={onclose} aria-label={t('common.close')}><X size={15} /></button>
  </header>
  <p class="hint">{t('sections.intro')}</p>
  <ul>
    {#each sections as s, i (s.id)}
      <li>
        <div class="row">
          <span class="arrows">
            <button class="btn icon sm ghost" disabled={i === 0} onclick={() => move(i, -1)} aria-label={t('common.up')}><ArrowUp size={13} /></button>
            <button class="btn icon sm ghost" disabled={i === sections.length - 1} onclick={() => move(i, 1)} aria-label={t('common.down')}><ArrowDown size={13} /></button>
          </span>
          <input class="input" value={s.label.de} aria-label="{t('fields.label')} (DE)" onchange={(e) => rename(s, 'de', e.currentTarget.value)} />
          <input class="input" value={s.label.en} aria-label="{t('fields.label')} (EN)" onchange={(e) => rename(s, 'en', e.currentTarget.value)} />
          <button class="btn icon sm ghost" onclick={() => remove(s)} aria-label={t('common.delete')}><Trash2 size={13} /></button>
        </div>
        <div class="meta"><span class="key">{s.key}</span> · {t('sections.fields', { n: used(s) })}</div>
        {#if moving === s.id}
          <div class="move">
            <span>{t('sections.in_use', { n: used(s) })}</span>
            <select class="select" bind:value={moveTo}>
              {#each sections.filter((x) => x.id !== s.id) as x (x.id)}<option value={String(x.id)}>{L(x.label)}</option>{/each}
              <option value="other">{t('core.section_other')}</option>
            </select>
            <span class="actions">
              <button class="btn sm" onclick={() => (moving = null)}>{t('common.cancel')}</button>
              <button class="btn sm danger" onclick={() => moveAndRemove(s)}>{t('sections.move_delete')}</button>
            </span>
          </div>
        {/if}
      </li>
    {/each}
  </ul>
  <form class="row add" onsubmit={(e) => { e.preventDefault(); add() }}>
    <span class="arrows"></span>
    <input class="input" placeholder="DE" aria-label="{t('fields.label')} (DE)" bind:value={label.de} />
    <input class="input" placeholder="EN" aria-label="{t('fields.label')} (EN)" bind:value={label.en} />
    <button class="btn icon sm" type="submit" disabled={!label.de.trim() && !label.en.trim()} aria-label={t('sections.add')} title={t('sections.add')}><Plus size={14} /></button>
  </form>
</aside>

<style>
  .sections { position: sticky; top: 0; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  header { display: flex; align-items: center; justify-content: space-between; }
  h2 { font-size: 16px; }
  p { margin: 0; }
  ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; max-height: 60vh; overflow: auto; }
  .row { display: grid; grid-template-columns: auto 1fr 1fr auto; gap: 4px; align-items: center; }
  .arrows { display: inline-flex; min-width: 52px; }
  .meta { margin-left: 56px; font-size: 12px; color: var(--muted); }
  .key { font: 11px ui-monospace, monospace; color: var(--faint); }
  .move { margin: 6px 0 0 56px; display: flex; flex-direction: column; gap: 6px; padding: 8px; border-radius: var(--radius);
    background: var(--panel-2); }
  .actions { display: flex; gap: 6px; justify-content: flex-end; }
  .add { border-top: 1px solid var(--border); padding-top: 12px; }
</style>
