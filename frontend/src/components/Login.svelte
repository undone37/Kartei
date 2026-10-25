<script lang="ts">
  import logo from '../assets/logo.svg'
  import { ApiError } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { i18n, setLang, t, terr } from '../lib/i18n.svelte'

  let username = $state('')
  let password = $state('')
  // a failed "Sign in with Microsoft" comes back as /?login_error=<code>
  const ssoError = new URLSearchParams(location.search).get('login_error')
  let error = $state(ssoError ? terr(ssoError) : '')
  if (ssoError) history.replaceState(null, '', '/')
  let busy = $state(false)
  /** second step: the password was right, the account has two-factor sign-in */
  let needCode = $state(false)
  let code = $state('')

  async function submit(e: SubmitEvent) {
    e.preventDefault()
    busy = true
    error = ''
    try {
      await store.login(username.trim(), password, needCode ? code.trim() : undefined)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'totp_required') needCode = true
      else {
        error = err instanceof ApiError ? terr(err.code) : t('err.generic')
        if (needCode) code = ''
        else password = ''
      }
    } finally {
      busy = false
    }
  }
</script>

<div class="wrap">
  <form class="card" onsubmit={submit}>
    <div class="brand"><img class="mark" src={logo} alt="" />Kartei</div>
    <h1>{t('login.title')}</h1>
    {#if needCode}
      <p class="muted">{t('totp.login_hint')}</p>
      <label class="label" for="c">{t('totp.code')}</label>
      <!-- svelte-ignore a11y_autofocus -->
      <input id="c" class="input" bind:value={code} inputmode="numeric" autocomplete="one-time-code" autofocus required />
      {#if error}<div class="error-text" role="alert">{error}</div>{/if}
      <button class="btn primary" disabled={busy || !code.trim()}>{t('login.submit')}</button>
      <button type="button" class="btn ghost" onclick={() => { needCode = false; code = ''; password = ''; error = '' }}>{t('common.cancel')}</button>
    {:else}
      <label class="label" for="u">{t('login.username')}</label>
      <!-- svelte-ignore a11y_autofocus -->
      <input id="u" class="input" bind:value={username} autocomplete="username" autofocus required />
      <label class="label" for="p">{t('login.password')}</label>
      <input id="p" class="input" type="password" bind:value={password} autocomplete="current-password" required />
      {#if error}<div class="error-text" role="alert">{error}</div>{/if}
      <button class="btn primary" disabled={busy || !username || !password}>{t('login.submit')}</button>
    {/if}
    {#if store.sso && !needCode}
      <div class="or"><span>{t('sso.or')}</span></div>
      <a class="btn ms" href="/api/oidc/start"><svg viewBox="0 0 21 21" width="16" height="16" aria-hidden="true"><path fill="#f25022" d="M1 1h9v9H1z"/><path fill="#7fba00" d="M11 1h9v9h-9z"/><path fill="#00a4ef" d="M1 11h9v9H1z"/><path fill="#ffb900" d="M11 11h9v9h-9z"/></svg>{t('sso.button')}</a>
    {/if}
    <div class="langs">
      <button type="button" class="chip" class:on={i18n.lang === 'de'} onclick={() => setLang('de')}>Deutsch</button>
      <button type="button" class="chip" class:on={i18n.lang === 'en'} onclick={() => setLang('en')}>English</button>
    </div>
  </form>
</div>

<style>
  .or { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; margin: 4px 0; }
  .or::before, .or::after { content: ''; flex: 1; border-top: 1px solid var(--border); }
  .ms { justify-content: center; gap: 10px; }
  .wrap { height: 100%; display: grid; place-items: center; padding: 16px; }
  .card { width: 100%; max-width: 360px; padding: 28px; display: flex; flex-direction: column; gap: 6px; box-shadow: var(--shadow); }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 650; margin-bottom: 18px; }
  .mark { width: 26px; height: 26px; display: block; }
  h1 { font-size: 20px; margin-bottom: 12px; }
  .label { margin-top: 8px; }
  .btn { margin-top: 16px; height: 38px; justify-content: center; }
  .langs { display: flex; gap: 6px; justify-content: center; margin-top: 18px; }
</style>
