<script lang="ts">
  import { Copy, Plus, Trash2 } from '@lucide/svelte'
  import { ApiError, del, get, post } from '../lib/api'
  import { dateTime, relTime } from '../lib/format'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'

  type Scope = 'read' | 'write'
  type Token = { id: number; name: string; scope: Scope; created_at: string; created_by: string; last_used_at: string | null }
  let tokens = $state<Token[]>([])
  let name = $state('')
  let scope = $state<Scope>('read')
  let error = $state('')
  let created = $state<{ name: string; scope: Scope; token: string } | null>(null)

  const load = () => get<{ tokens: Token[] }>('/api/admin/tokens').then((r) => (tokens = r.tokens))
  load()

  async function create(e: SubmitEvent) {
    e.preventDefault()
    error = ''
    try {
      created = await post('/api/admin/tokens', { name, scope })
      name = ''
      scope = 'read'
      load()
    } catch (err) {
      error = err instanceof ApiError && err.code === 'validation' ? terr(err.fields.name) : t('err.generic')
    }
  }

  async function revoke(tk: Token) {
    const ok = await confirmDialog({ title: t('tokens.revoke_title', { name: tk.name }), message: t('tokens.revoke_text'),
                                     confirmLabel: t('tokens.revoke'), danger: true })
    if (!ok) return
    await del(`/api/admin/tokens/${tk.id}`).catch(() => toast(t('err.generic'), { kind: 'error' }))
    load()
  }

  const base = `${location.origin}/api/v1/contacts`
  const copy = (v: string) => navigator.clipboard.writeText(v).then(() => toast(t('view.copied')))
</script>

<p class="hint">{t('tokens.hint')}</p>
<form class="toolbar" onsubmit={create}>
  <input class="input" class:invalid={error} bind:value={name} placeholder={t('tokens.name')} aria-label={t('tokens.name')} />
  <div class="scopes" role="radiogroup" aria-label={t('tokens.scope')}>
    {#each ['read', 'write'] as const as s (s)}
      <label class="check"><input type="radio" name="scope" bind:group={scope} value={s} /> {t(`tokens.scope_${s}`)}</label>
    {/each}
  </div>
  <button class="btn primary"><Plus size={15} />{t('tokens.new')}</button>
  {#if error}<span class="error-text">{error}</span>{/if}
</form>

{#if created}
  <div class="result">
    {t('tokens.once', { name: created.name })} {t(`tokens.once_${created.scope}`)}<br />
    <code>{created.token}</code> <button type="button" class="btn sm icon ghost" onclick={() => copy(created!.token)}><Copy size={13} /></button>
  </div>
{/if}

<table class="grid">
  <thead><tr><th>{t('tokens.name')}</th><th>{t('tokens.scope')}</th><th>{t('tokens.created')}</th><th>{t('tokens.last_used')}</th><th></th></tr></thead>
  <tbody>
    {#each tokens as tk (tk.id)}
      <tr>
        <td><strong>{tk.name}</strong></td>
        <td><span class="badge" class:warn={tk.scope === 'write'}>{t(`tokens.scope_${tk.scope}`)}</span></td>
        <td class="muted" title={dateTime(tk.created_at)}>{relTime(tk.created_at)}{tk.created_by ? ` · ${tk.created_by}` : ''}</td>
        <td class="muted">{#if tk.last_used_at}<span title={dateTime(tk.last_used_at)}>{relTime(tk.last_used_at)}</span>{:else}{t('tokens.never')}{/if}</td>
        <td class="act"><button class="btn sm icon ghost danger" title={t('tokens.revoke')} onclick={() => revoke(tk)}><Trash2 size={14} /></button></td>
      </tr>
    {:else}
      <tr><td colspan="5" class="muted">{t('tokens.none')}</td></tr>
    {/each}
  </tbody>
</table>

<div class="result info">
  <strong>{t('tokens.usage')}</strong>
  <code>curl -H "Authorization: Bearer kt_…" {base}</code>
  <div class="hint">{t('tokens.usage_delta')}</div>
  <div class="hint">{t('tokens.usage_fields')}</div>
  <div class="hint">{t('tokens.usage_write')}</div>
</div>

<style>
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 8px 0 12px; max-width: 720px; }
  .scopes { display: flex; gap: 16px; flex-basis: 100%; }
  .check { display: flex; align-items: center; gap: 6px; cursor: pointer; }
  .result { padding: 10px 12px; border-radius: 8px; background: var(--ok-soft); color: var(--ok); display: grid; gap: 4px; overflow-wrap: anywhere; margin-bottom: 12px; max-width: 720px; }
  .result.info { background: var(--panel-2); color: var(--text); margin-top: 16px; }
  code { font: 13px ui-monospace, monospace; }
  .act { text-align: right; white-space: nowrap; }
</style>
