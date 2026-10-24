<script lang="ts">
  import logo from '../assets/logo.svg'
  import { ApiError } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { i18n, setLang, t, terr } from '../lib/i18n.svelte'

  let username = $state('')
  let password = $state('')
  let error = $state('')
  let busy = $state(false)

  async function submit(e: SubmitEvent) {
    e.preventDefault()
    busy = true
    error = ''
    try {
      await store.login(username.trim(), password)
    } catch (err) {
      error = err instanceof ApiError ? terr(err.code) : t('err.generic')
      password = ''
    } finally {
      busy = false
    }
  }
</script>

<div class="wrap">
  <form class="card" onsubmit={submit}>
    <div class="brand"><img class="mark" src={logo} alt="" />Kartei</div>
    <h1>{t('login.title')}</h1>
    <label class="label" for="u">{t('login.username')}</label>
    <!-- svelte-ignore a11y_autofocus -->
    <input id="u" class="input" bind:value={username} autocomplete="username" autofocus required />
    <label class="label" for="p">{t('login.password')}</label>
    <input id="p" class="input" type="password" bind:value={password} autocomplete="current-password" required />
    {#if error}<div class="error-text" role="alert">{error}</div>{/if}
    <button class="btn primary" disabled={busy || !username || !password}>{t('login.submit')}</button>
    <div class="langs">
      <button type="button" class="chip" class:on={i18n.lang === 'de'} onclick={() => setLang('de')}>Deutsch</button>
      <button type="button" class="chip" class:on={i18n.lang === 'en'} onclick={() => setLang('en')}>English</button>
    </div>
  </form>
</div>

<style>
  .wrap { height: 100%; display: grid; place-items: center; padding: 16px; }
  .card { width: 100%; max-width: 360px; padding: 28px; display: flex; flex-direction: column; gap: 6px; box-shadow: var(--shadow); }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 650; margin-bottom: 18px; }
  .mark { width: 26px; height: 26px; display: block; }
  h1 { font-size: 20px; margin-bottom: 12px; }
  .label { margin-top: 8px; }
  .btn { margin-top: 16px; height: 38px; justify-content: center; }
  .langs { display: flex; gap: 6px; justify-content: center; margin-top: 18px; }
</style>
