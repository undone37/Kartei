<script lang="ts">
  import { Copy, KeyRound, Plus, Send, Trash2 } from '@lucide/svelte'
  import { ApiError, del, get, patch, post } from '../lib/api'
  import { dateTime, relTime } from '../lib/format'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'

  const EVENTS = ['contact.created', 'contact.updated', 'contact.deleted', 'contact.restored'] as const
  type Status = { at?: string; ok?: boolean; code?: number | null; error?: string }
  type Hook = { id: number; name: string; url: string; events: string[]; enabled: boolean; created_at: string; created_by: string
                last_status: Status; pending: number; failed: number }
  let hooks = $state<Hook[]>([])
  let name = $state('')
  let url = $state('')
  let events = $state<string[]>([])
  let errors = $state<Record<string, string>>({})
  let secret = $state<{ name: string; secret: string } | null>(null)
  let busy = $state(0)

  const load = () => get<{ webhooks: Hook[] }>('/api/admin/webhooks').then((r) => (hooks = r.webhooks))
  load()

  async function create(e: SubmitEvent) {
    e.preventDefault()
    errors = {}
    try {
      const r = await post<Hook & { secret: string }>('/api/admin/webhooks', { name, url, events })
      secret = { name: r.name, secret: r.secret }
      name = url = ''
      events = []
      load()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'validation') errors = err.fields
      else toast(t('err.generic'), { kind: 'error' })
    }
  }

  async function toggle(h: Hook) {
    await patch(`/api/admin/webhooks/${h.id}`, { enabled: !h.enabled }).catch(() => toast(t('err.generic'), { kind: 'error' }))
    load()
  }

  async function test(h: Hook) {
    busy = h.id
    try {
      const r = await post<{ ok: boolean; code: number | null; error: string }>(`/api/admin/webhooks/${h.id}/test`)
      toast(r.ok ? t('hooks.test_ok', { code: String(r.code) }) : t('hooks.test_failed', { error: r.error }), { kind: r.ok ? 'info' : 'error' })
    } finally {
      busy = 0
      load()
    }
  }

  async function newSecret(h: Hook) {
    const ok = await confirmDialog({ title: t('hooks.secret_title', { name: h.name }), message: t('hooks.secret_text'),
                                     confirmLabel: t('hooks.secret_new') })
    if (!ok) return
    const r = await post<{ secret: string }>(`/api/admin/webhooks/${h.id}/secret`)
    secret = { name: h.name, secret: r.secret }
  }

  async function remove(h: Hook) {
    const ok = await confirmDialog({ title: t('hooks.delete_title', { name: h.name }), message: t('hooks.delete_text'),
                                     confirmLabel: t('common.delete'), danger: true })
    if (!ok) return
    await del(`/api/admin/webhooks/${h.id}`).catch(() => toast(t('err.generic'), { kind: 'error' }))
    load()
  }

  const copy = (v: string) => navigator.clipboard.writeText(v).then(() => toast(t('view.copied')))
  const eventName = (e: string) => t(`hooks.event_${e.split('.')[1]}`)
</script>

<h2>{t('hooks.title')}</h2>
<p class="hint">{t('hooks.hint')}</p>
<form class="toolbar" onsubmit={create}>
  <input class="input name" class:invalid={errors.name} bind:value={name} placeholder={t('hooks.name')} aria-label={t('hooks.name')} />
  <input class="input url" class:invalid={errors.url} bind:value={url} placeholder="https://intranet.example.de/kartei-hook" aria-label={t('hooks.url')} />
  <div class="events" role="group" aria-label={t('hooks.events')}>
    {#each EVENTS as e (e)}
      <label class="check"><input type="checkbox" bind:group={events} value={e} /> {eventName(e)}</label>
    {/each}
    <span class="muted">{t('hooks.events_hint')}</span>
  </div>
  <button class="btn primary"><Plus size={15} />{t('hooks.new')}</button>
  {#each Object.entries(errors) as [k, code] (k)}<span class="error-text">{t(`hooks.${k}`)}: {terr(code)}</span>{/each}
</form>

{#if secret}
  <div class="result">
    {t('hooks.secret_once', { name: secret.name })}<br />
    <code>{secret.secret}</code> <button type="button" class="btn sm icon ghost" onclick={() => copy(secret!.secret)}><Copy size={13} /></button>
  </div>
{/if}

<table class="grid">
  <thead><tr><th>{t('hooks.name')}</th><th>{t('hooks.events')}</th><th>{t('hooks.last')}</th><th>{t('hooks.active')}</th><th></th></tr></thead>
  <tbody>
    {#each hooks as h (h.id)}
      <tr>
        <td><strong>{h.name}</strong><div class="muted small">{h.url}</div></td>
        <td>{#if h.events.length}{#each h.events as e (e)}<span class="badge">{eventName(e)}</span> {/each}{:else}<span class="muted">{t('hooks.all')}</span>{/if}</td>
        <td>
          {#if h.last_status.at}
            <span class="badge" class:ok={h.last_status.ok} class:warn={!h.last_status.ok}
                  title={h.last_status.error || ''}>{h.last_status.ok ? t('hooks.ok') : h.last_status.error || t('hooks.failed')}</span>
            <span class="muted small" title={dateTime(h.last_status.at)}>{relTime(h.last_status.at)}</span>
          {:else}<span class="muted">{t('tokens.never')}</span>{/if}
          {#if h.pending}<div class="muted small">{t('hooks.pending', { n: String(h.pending) })}</div>{/if}
          {#if h.failed}<div class="error-text small">{t('hooks.given_up', { n: String(h.failed) })}</div>{/if}
        </td>
        <td><input type="checkbox" checked={h.enabled} onchange={() => toggle(h)} aria-label={t('hooks.active')} /></td>
        <td class="act">
          <button class="btn sm icon ghost" title={t('hooks.test')} aria-label={t('hooks.test')} disabled={busy === h.id} onclick={() => test(h)}><Send size={14} /></button>
          <button class="btn sm icon ghost" title={t('hooks.secret_new')} aria-label={t('hooks.secret_new')} onclick={() => newSecret(h)}><KeyRound size={14} /></button>
          <button class="btn sm icon ghost danger" title={t('common.delete')} aria-label={t('common.delete')} onclick={() => remove(h)}><Trash2 size={14} /></button>
        </td>
      </tr>
    {:else}
      <tr><td colspan="5" class="muted">{t('hooks.none')}</td></tr>
    {/each}
  </tbody>
</table>

<style>
  h2 { font-size: 16px; margin: 28px 0 4px; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 8px 0 12px; max-width: 720px; }
  .name { flex: 0 1 200px; }
  .url { flex: 1 1 300px; }
  .events { display: flex; flex-wrap: wrap; gap: 6px 16px; flex-basis: 100%; align-items: center; }
  .check { display: flex; align-items: center; gap: 6px; cursor: pointer; }
  .result { padding: 10px 12px; border-radius: 8px; background: var(--ok-soft); color: var(--ok); display: grid; gap: 4px; overflow-wrap: anywhere; margin-bottom: 12px; max-width: 720px; }
  code { font: 13px ui-monospace, monospace; }
  .small { font-size: 12px; }
  .act { text-align: right; white-space: nowrap; }
</style>
