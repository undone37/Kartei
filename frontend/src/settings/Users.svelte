<script lang="ts">
  import { KeyRound, Plus, Trash2 } from '@lucide/svelte'
  import { ApiError, del, get, patch, post } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { relTime } from '../lib/format'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { confirmDialog } from '../lib/confirm.svelte'
  import type { Role, User } from '../lib/types'

  let users = $state<User[]>([])
  let creating = $state(false)
  let draft = $state({ username: '', first_name: '', last_name: '', email: '', password: '', role: 'read' as Role })
  let errors = $state<Record<string, string>>({})
  let pwFor = $state<number | null>(null)
  let newPw = $state('')

  const load = () => get<{ users: User[] }>('/api/admin/users').then((r) => (users = r.users))
  load()

  const fail = (e: unknown) => toast(e instanceof ApiError ? terr(e.code === 'validation' ? Object.values(e.fields)[0] : e.code) : t('err.generic'), { kind: 'error' })

  async function create(e: SubmitEvent) {
    e.preventDefault()
    errors = {}
    try {
      await post('/api/admin/users', draft)
      creating = false
      draft = { username: '', first_name: '', last_name: '', email: '', password: '', role: 'read' }
      load()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'validation') errors = err.fields
      else fail(err)
    }
  }

  async function update(u: User, body: Partial<User> & { password?: string }) {
    try {
      const r = await patch<User>(`/api/admin/users/${u.id}`, body)
      users = users.map((x) => (x.id === u.id ? r : x))
      return true
    } catch (err) {
      fail(err)
      load()
      return false
    }
  }

  async function setPassword(u: User) {
    if (await update(u, { password: newPw })) {
      toast(t('users.pw_set'))
      pwFor = null
      newPw = ''
    }
  }

  async function remove(u: User) {
    const name = [u.first_name, u.last_name].join(' ').trim() || u.username
    const ok = await confirmDialog({ title: t('users.delete_title', { name }), message: t('users.delete_text'),
                                     confirmLabel: t('common.delete'), danger: true })
    if (!ok) return
    try {
      await del(`/api/admin/users/${u.id}`)
      load()
    } catch (err) {
      fail(err)
    }
  }
</script>

<div class="toolbar">
  <button class="btn primary" onclick={() => (creating = !creating)}><Plus size={15} />{t('users.new')}</button>
  <span class="hint">{t('users.hint')}</span>
</div>

{#if creating}
  <form class="card create" onsubmit={create}>
    <div><label class="label" for="un">{t('login.username')} *</label><input id="un" class="input" class:invalid={errors.username} bind:value={draft.username} autocomplete="off" />
      {#if errors.username}<div class="error-text">{terr(errors.username)}</div>{/if}</div>
    <div><label class="label" for="fn">{t('core.first_name')}</label><input id="fn" class="input" bind:value={draft.first_name} /></div>
    <div><label class="label" for="ln">{t('core.last_name')}</label><input id="ln" class="input" bind:value={draft.last_name} /></div>
    <div><label class="label" for="em">{t('audit.attr.email')}</label><input id="em" class="input" type="email" bind:value={draft.email} /></div>
    <div><label class="label" for="pw">{t('login.password')} *</label><input id="pw" class="input" class:invalid={errors.password} type="password" bind:value={draft.password} autocomplete="new-password" />
      {#if errors.password}<div class="error-text">{terr(errors.password)}</div>{/if}</div>
    <div><label class="label" for="ro">{t('users.role')}</label>
      <select id="ro" class="select" bind:value={draft.role}>
        {#each ['read', 'maintainer', 'admin'] as r}<option value={r}>{t(`role.${r}`)}</option>{/each}
      </select></div>
    <div class="actions"><button type="button" class="btn" onclick={() => (creating = false)}>{t('common.cancel')}</button><button class="btn primary">{t('common.create')}</button></div>
  </form>
{/if}

<table class="grid">
  <thead><tr><th>{t('login.username')}</th><th>{t('core.name')}</th><th>{t('users.source')}</th><th>{t('users.role')}</th><th>{t('users.active')}</th><th>{t('users.last_login')}</th><th></th></tr></thead>
  <tbody>
    {#each users as u (u.id)}
      <tr>
        <td><strong>{u.username}</strong>{#if u.id === store.user?.id} <span class="badge">{t('users.you')}</span>{/if}</td>
        <td>{[u.first_name, u.last_name].join(' ')}</td>
        <td><span class="badge">{u.source === 'local' ? t('users.local') : u.source.toUpperCase()}</span></td>
        <td>
          {#if u.source !== 'local' || u.is_superuser}
            <span title={u.is_superuser ? t('users.superuser_role') : t(`users.${u.source}_role`)}>{t(`role.${u.role}`)}</span>
          {:else}
            <select class="select sm" value={u.role} aria-label={`${t('users.role')}: ${u.username}`} onchange={(e) => update(u, { role: e.currentTarget.value as Role })}>
              {#each ['read', 'maintainer', 'admin'] as r}<option value={r}>{t(`role.${r}`)}</option>{/each}
            </select>
          {/if}
        </td>
        <td><input type="checkbox" checked={u.is_active} aria-label={`${t('users.active')}: ${u.username}`} disabled={u.id === store.user?.id || u.source !== 'local'} onchange={(e) => update(u, { is_active: e.currentTarget.checked })} /></td>
        <td class="muted">{u.last_login ? relTime(u.last_login) : '—'}</td>
        <td class="act">
          {#if pwFor === u.id}
            <input class="input pw" type="password" placeholder={t('account.new_pw')} bind:value={newPw} autocomplete="new-password" />
            <button class="btn sm primary" onclick={() => setPassword(u)}>{t('common.save')}</button>
            <button class="btn sm" onclick={() => (pwFor = null)}>{t('common.cancel')}</button>
          {:else}
            {#if u.source === 'local'}<button class="btn sm icon ghost" title={t('users.set_pw')} onclick={() => { pwFor = u.id; newPw = '' }}><KeyRound size={14} /></button>{/if}
            {#if u.id !== store.user?.id}<button class="btn sm icon ghost danger" title={t('common.delete')} aria-label={t('common.delete')} onclick={() => remove(u)}><Trash2 size={14} /></button>{/if}
          {/if}
        </td>
      </tr>
    {/each}
  </tbody>
</table>

<style>
  .toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .create { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; padding: 16px; margin-bottom: 16px; }
  .create .actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 6px; }
  .select.sm { height: 28px; width: auto; }
  .act { text-align: right; white-space: nowrap; }
  .act > :global(* + *) { margin-left: 4px; }
  .pw { height: 28px; width: 180px; }
</style>
