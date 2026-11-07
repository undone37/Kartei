<script lang="ts">
  import { Copy, KeyRound } from '@lucide/svelte'
  import { ApiError, get, post, put } from '../lib/api'
  import { t, terr } from '../lib/i18n.svelte'
  import { copyText, toast } from '../lib/toast.svelte'

  /** Phonebook for desk phones (Yealink, Snom, Grandstream) and number lookup for phone systems. */
  let s = $state<Record<string, any> | null>(null)
  let errors = $state<Record<string, string>>({})
  let allowlist = $state('')
  let password = $state('') // shown once after generating

  get<Record<string, any>>('/api/admin/settings').then((r) => {
    s = r
    allowlist = r.phonebook_allowlist.join('\n')
  })

  const origin = $derived((s?.base_url || location.origin).replace(/\/$/, ''))
  const urls = $derived([
    ['Yealink', `${origin}/phonebook/yealink.xml`, `${origin}/phonebook/yealink.xml?q=#SEARCH`],
    ['Snom', `${origin}/phonebook/snom.xml`, ''],
    ['Grandstream', `${origin}/phonebook/grandstream.xml`, ''],
    ['Swyx (CSV)', `${origin}/phonebook/swyx.csv`, ''],
  ])
  const lookup = $derived(`${origin}/phonebook/lookup?number=`)

  async function save() {
    errors = {}
    try {
      s = await put('/api/admin/settings', { phonebook_enabled: s!.phonebook_enabled, phonebook_username: s!.phonebook_username,
                                              phonebook_allowlist: allowlist.split(/[\s,]+/).filter(Boolean) })
      allowlist = s!.phonebook_allowlist.join('\n')
      toast(t('settings.saved'))
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
      else toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  async function newPassword() {
    password = (await post<{ password: string }>('/api/admin/phonebook/password')).password
    s!.phonebook_password_set = true
  }

  const err = (k: string) => errors[k] ? (errors[k].startsWith('invalid_network:') ? t('mon.bad_network', { v: errors[k].slice(16) }) : terr(errors[k])) : ''
</script>

{#if s}
  <section class="card box">
    <h2>{t('phonebook.title')}</h2>
    <p class="hint">{t('phonebook.hint')}</p>
    <label class="check"><input type="checkbox" bind:checked={s.phonebook_enabled} /> {t('phonebook.enabled')}</label>
    <div class="row2">
      <div>
        <label class="label" for="pb-user">{t('phonebook.username')}</label>
        <input id="pb-user" class="input" bind:value={s.phonebook_username} autocomplete="off" />
        {#if errors.phonebook_username}<div class="error-text">{err('phonebook_username')}</div>{/if}
      </div>
      <div>
        <span class="label">{t('phonebook.password')}</span>
        {#if password}
          <div class="secret"><code>{password}</code><button class="btn icon sm" onclick={() => copyText(password)} aria-label={t('view.copy')}><Copy size={13} /></button></div>
          <p class="hint">{t('phonebook.password_once')}</p>
        {:else}
          <button class="btn" onclick={newPassword}><KeyRound size={14} />{s.phonebook_password_set ? t('phonebook.password_new') : t('phonebook.password_create')}</button>
          {#if !s.phonebook_password_set}<p class="hint">{t('phonebook.password_needed')}</p>{/if}
        {/if}
      </div>
    </div>
    <label class="label" for="pb-allow">{t('phonebook.allowlist')}</label>
    <textarea id="pb-allow" class="input mono" rows="3" bind:value={allowlist} placeholder="10.0.5.0/24"></textarea>
    <p class="hint">{t('phonebook.allowlist_hint')}</p>
    {#if errors.phonebook_allowlist}<div class="error-text">{err('phonebook_allowlist')}</div>{/if}
    <div><button class="btn primary" onclick={save}>{t('common.save')}</button></div>

    <h3>{t('phonebook.urls')}</h3>
    <table class="urls">
      <tbody>
        {#each urls as [brand, url, search] (brand)}
          <tr><th>{brand}</th><td><code>{url}</code></td>
            <td><button class="btn icon sm" onclick={() => copyText(url)} aria-label="{t('view.copy')} {brand}"><Copy size={13} /></button></td></tr>
          {#if search}<tr><th></th><td><code>{search}</code> <span class="muted">({t('phonebook.search')})</span></td>
            <td><button class="btn icon sm" onclick={() => copyText(search)} aria-label="{t('view.copy')} {brand} {t('phonebook.search')}"><Copy size={13} /></button></td></tr>{/if}
        {/each}
        <tr><th>{t('phonebook.lookup')}</th><td><code>{lookup}…</code></td>
          <td><button class="btn icon sm" onclick={() => copyText(lookup)} aria-label="{t('view.copy')} {t('phonebook.lookup')}"><Copy size={13} /></button></td></tr>
      </tbody>
    </table>
    <p class="hint">{t('phonebook.urls_hint')}</p>
  </section>
{/if}

<style>
  .box { padding: 16px 20px; display: grid; gap: 10px; margin-top: 16px; }
  h2 { font-size: 16px; margin: 0; }
  h3 { font-size: 14px; margin: 10px 0 0; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .secret { display: flex; align-items: center; gap: 8px; }
  .secret code { font-size: 13px; padding: 6px 8px; background: var(--panel-2); border-radius: 6px; }
  textarea { width: 100%; }
  .urls { border-collapse: collapse; font-size: 13px; }
  .urls th { text-align: left; font-weight: 500; padding: 4px 12px 4px 0; white-space: nowrap; color: var(--muted); }
  .urls td { padding: 4px 8px 4px 0; overflow-wrap: anywhere; }
  .urls code { font-size: 12.5px; }
  @media (max-width: 700px) { .row2 { grid-template-columns: 1fr; } }
</style>
