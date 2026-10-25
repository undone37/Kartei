<script lang="ts">
  import logo from '../assets/logo.svg'
  import { store } from '../lib/store.svelte'
  import { t } from '../lib/i18n.svelte'
  import TwoFactor from './TwoFactor.svelte'

  /** Right after sign-in when the admin requires two-factor sign-in and the user hasn't set it up yet. */
</script>

<div class="wrap">
  <div class="box">
    <div class="brand"><img class="mark" src={logo} alt="" />Kartei</div>
    <h1>{t('totp.required_title')}</h1>
    <p class="muted">{t('totp.required_hint')}</p>
    <TwoFactor ondone={() => location.reload()} />
    <button class="btn ghost" onclick={() => store.logout()}>{t('top.logout')}</button>
  </div>
</div>

<style>
  .wrap { min-height: 100%; display: grid; place-items: center; padding: 16px; }
  .box { width: 100%; max-width: 440px; display: flex; flex-direction: column; gap: 12px; }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 650; }
  .mark { width: 26px; height: 26px; display: block; }
  h1 { font-size: 20px; }
  .btn { align-self: center; }
</style>
