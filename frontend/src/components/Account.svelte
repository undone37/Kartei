<script lang="ts">
  import TwoFactor from './TwoFactor.svelte'
  import { ApiError, patch, post } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { disablePush, enablePush, pushSubscription, pushSupported } from '../lib/push'
  import { RANK, type PushKind } from '../lib/types'

  let oldPw = $state('')
  let newPw = $state('')
  let errors = $state<Record<string, string>>({})

  async function setLanguage(language: string) {
    const r = await patch('/api/me', { language })
    store.user = r.user
    store.applyLang()
  }

  // Web Push on this device: unsupported (e.g. iPhone outside the installed app), blocked, off or on
  let push = $state<'unsupported' | 'denied' | 'off' | 'on'>('off')
  let pushBusy = $state(false)
  async function pushState() {
    if (!pushSupported() || !(await navigator.serviceWorker.getRegistration())) push = 'unsupported'
    else if (Notification.permission === 'denied') push = 'denied'
    else push = (await pushSubscription()) ? 'on' : 'off'
  }
  pushState()

  async function togglePush(on: boolean) {
    pushBusy = true
    try {
      if (on) await enablePush()
      else await disablePush()
    } finally {
      pushBusy = false
      await pushState()
    }
  }

  // which notifications, saved with the account (all devices); proposals only reach maintainers and admins
  const kinds = $derived(([...(RANK[store.user?.role ?? 'read'] >= RANK.maintainer ? ['review', 'proposals'] : ['review']), 'decided'] as PushKind[]))
  function setKind(kind: PushKind, on: boolean) {
    const off = new Set(store.user?.push_off ?? [])
    if (on) off.delete(kind)
    else off.add(kind)
    store.setListPrefs({ push_off: [...off] }).catch(() => toast(t('err.generic'), { kind: 'error' }))
  }

  async function testPush() {
    const r = await post<{ sent: number }>('/api/me/push', { test: true })
    toast(t('push.test_sent', { n: r.sent }))
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
    <p class="muted">{t(store.user?.source === 'scim' ? 'account.scim_hint' : 'account.ldap_hint')}</p>
  {/if}
  <TwoFactor />
  <section class="card">
    <h2>{t('push.title')}</h2>
    <p class="muted">{t('push.hint')}</p>
    {#if push === 'unsupported'}
      <p class="muted">{t('push.unsupported')}</p>
    {:else if push === 'denied'}
      <p class="error-text">{t('push.denied')}</p>
    {:else if push === 'on'}
      <p>{t('push.on')}</p>
      <div class="row">
        <button class="btn" onclick={testPush}>{t('push.test')}</button>
        <button class="btn ghost" disabled={pushBusy} onclick={() => togglePush(false)}>{t('push.disable')}</button>
      </div>
    {:else}
      <button class="btn primary" disabled={pushBusy} onclick={() => togglePush(true)}>{t('push.enable')}</button>
    {/if}
    <fieldset>
      <legend class="label">{t('push.kinds')}</legend>
      {#each kinds as kind (kind)}
        <label class="check">
          <input type="checkbox" checked={!store.user?.push_off?.includes(kind)}
                 onchange={(e) => setKind(kind, e.currentTarget.checked)} />
          {t(`push.kind_${kind}`)}
        </label>
      {/each}
    </fieldset>
  </section>
</div>

<style>
  .page { max-width: 560px; margin: 0 auto; padding: 24px 28px; display: grid; gap: 16px; }
  h1 { font-size: 22px; }
  h2 { font-size: 15px; margin-bottom: 10px; }
  .card { padding: 18px; display: flex; flex-direction: column; gap: 6px; }
  .card .btn { align-self: flex-start; margin-top: 10px; }
  .row { display: flex; gap: 8px; }
  fieldset { border: 0; padding: 0; margin: 10px 0 0; display: grid; gap: 6px; }
  .check { display: flex; gap: 8px; align-items: center; }
</style>
