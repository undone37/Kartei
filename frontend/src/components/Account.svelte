<script lang="ts">
  import TwoFactor from './TwoFactor.svelte'
  import { ApiError, patch } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'

  let oldPw = $state('')
  let newPw = $state('')
  let errors = $state<Record<string, string>>({})

  async function setLanguage(language: string) {
    const r = await patch('/api/me', { language })
    store.user = r.user
    store.applyLang()
  }

  async function changePw(e: SubmitEvent) {
    e.preventDefault()
    errors = {}
    try {
      await patch('/api/me', { old_password: oldPw, password: newPw })
      oldPw = newPw = ''
      toast(t('account.pw_changed'))
    } catch (err) {
      if (err instanceof ApiError) errors = err.fields
    }
  }
</script>

<div class="page">
  <h1>{t('top.account')}</h1>
  <section class="card">
    <h2>{t('account.language')}</h2>
    <select class="select" aria-label={t('account.language')} value={store.user?.language ?? ''} onchange={(e) => setLanguage(e.currentTarget.value)}>
      <option value="">{t('account.lang_default', { lang: store.defaultLang === 'de' ? 'Deutsch' : 'English' })}</option>
      <option value="de">Deutsch</option>
      <option value="en">English</option>
    </select>
  </section>
  {#if store.user?.source === 'local'}
    <form class="card" onsubmit={changePw}>
      <h2>{t('account.password')}</h2>
      <label class="label" for="old">{t('account.old_pw')}</label>
      <input id="old" class="input" type="password" bind:value={oldPw} autocomplete="current-password" />
      {#if errors.old_password}<div class="error-text">{terr(errors.old_password)}</div>{/if}
      <label class="label" for="new">{t('account.new_pw')}</label>
      <input id="new" class="input" type="password" bind:value={newPw} autocomplete="new-password" />
      {#if errors.password}<div class="error-text">{terr(errors.password)}</div>{/if}
      <button class="btn primary" disabled={!oldPw || !newPw}>{t('common.save')}</button>
    </form>
  {:else}
    <p class="muted">{t('account.ldap_hint')}</p>
  {/if}
  <TwoFactor />
</div>

<style>
  .page { max-width: 560px; margin: 0 auto; padding: 24px 28px; display: grid; gap: 16px; }
  h1 { font-size: 22px; }
  h2 { font-size: 15px; margin-bottom: 10px; }
  .card { padding: 18px; display: flex; flex-direction: column; gap: 6px; }
  .card .btn { align-self: flex-start; margin-top: 10px; }
</style>
