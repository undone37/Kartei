<script lang="ts">
  import { Copy, ShieldCheck } from '@lucide/svelte'
  import { ApiError, post } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import type { User } from '../lib/types'

  /** ondone: after the recovery codes were saved (the required setup right after sign-in) */
  let { ondone }: { ondone?: () => void } = $props()

  /** Two-factor sign-in under "My account": set up with a QR code, show recovery codes once, renew, switch off. */
  let setup = $state<{ secret: string; qr: string } | null>(null)
  let code = $state('')
  let password = $state('')
  let pwError = $state('')
  let error = $state('')
  let recovery = $state<string[] | null>(null)
  let busy = $state(false)
  const on = $derived(!!store.user?.totp)
  const noPassword = $derived(store.user?.source === 'scim') // signs in via the identity provider only

  async function start() {
    const r = await post<{ secret: string; uri: string }>('/api/me/totp', { action: 'setup' })
    const { default: qrcode } = await import('qrcode-generator') // only loaded here
    const qr = qrcode(0, 'M')
    qr.addData(r.uri)
    qr.make()
    setup = { secret: r.secret, qr: qr.createDataURL(5, 2) }
    code = error = password = pwError = ''
  }

  async function act(action: 'confirm' | 'recovery' | 'disable') {
    busy = true
    error = pwError = ''
    try {
      const r = await post<{ user?: User; recovery?: string[] }>('/api/me/totp', { action, code, password })
      if (r.user) store.user = r.user
      recovery = r.recovery ?? null
      setup = null
      code = password = ''
      if (action === 'disable') toast(t('totp.disabled'))
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') {
        if (e.fields.password) pwError = terr(e.fields.password)
        if (e.fields.code) error = terr(e.fields.code)
      } else error = e instanceof ApiError && ['too_many_attempts', 'sso_reauth'].includes(e.code) ? terr(e.code) : t('err.generic')
    } finally {
      busy = false
    }
  }

  const copy = () => navigator.clipboard.writeText(recovery!.join('\n')).then(() => toast(t('view.copied')))
</script>

<section class="card">
  <h2><ShieldCheck size={16} />{t('totp.title')}</h2>
  {#if recovery}
    <p>{t('totp.recovery_once')}</p>
    <ul class="codes">{#each recovery as c (c)}<li><code>{c}</code></li>{/each}</ul>
    <div class="row">
      <button class="btn" onclick={copy}><Copy size={14} />{t('totp.copy')}</button>
      <button class="btn primary" onclick={() => { recovery = null; ondone?.() }}>{t('totp.saved')}</button>
    </div>
  {:else if setup}
    <p>{t('totp.scan')}</p>
    <img class="qr" src={setup.qr} alt={t('totp.qr')} />
    <p class="muted small">{t('totp.manual')} <code>{setup.secret}</code></p>
    <label class="label" for="totp-code">{t('totp.code')}</label>
    <input id="totp-code" class="input code" class:invalid={error} bind:value={code} inputmode="numeric" autocomplete="one-time-code" maxlength="6" />
    {#if error}<div class="error-text">{error}</div>{/if}
    {#if !noPassword}
      <label class="label" for="totp-pw">{t('account.old_pw')}</label>
      <input id="totp-pw" class="input" class:invalid={pwError} type="password" bind:value={password} autocomplete="current-password" />
      {#if pwError}<div class="error-text">{pwError}</div>{/if}
    {/if}
    <div class="row">
      <button class="btn" onclick={() => (setup = null)}>{t('common.cancel')}</button>
      <button class="btn primary" disabled={busy || code.trim().length !== 6 || (!password && !noPassword)} onclick={() => act('confirm')}>{t('totp.enable')}</button>
    </div>
  {:else if on}
    <p><span class="badge ok">{t('totp.on')}</span> {t('totp.on_hint')}</p>
    <label class="label" for="totp-code">{t('totp.code_or_recovery')}</label>
    <input id="totp-code" class="input code" class:invalid={error} bind:value={code} autocomplete="one-time-code" />
    {#if error}<div class="error-text">{error}</div>{/if}
    <div class="row">
      <button class="btn" disabled={busy || !code.trim()} onclick={() => act('recovery')}>{t('totp.new_recovery')}</button>
      <button class="btn danger" disabled={busy || !code.trim()} onclick={() => act('disable')}>{t('totp.disable')}</button>
    </div>
  {:else}
    <p class="muted">{t('totp.off_hint')}</p>
    <button class="btn primary" onclick={start}>{t('totp.setup')}</button>
  {/if}
</section>

<style>
  .card { padding: 18px; display: flex; flex-direction: column; gap: 8px; }
  h2 { display: flex; align-items: center; gap: 8px; font-size: 15px; margin-bottom: 4px; }
  p { margin: 0; }
  .qr { width: 180px; height: 180px; image-rendering: pixelated; border-radius: 8px; background: #fff; }
  .code { max-width: 220px; font: 16px ui-monospace, monospace; letter-spacing: 0.1em; }
  .small { font-size: 12px; overflow-wrap: anywhere; }
  .codes { columns: 2; padding-left: 18px; margin: 4px 0; }
  .row { display: flex; gap: 8px; margin-top: 6px; }
</style>
