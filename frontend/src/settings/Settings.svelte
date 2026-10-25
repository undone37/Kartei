<script lang="ts">
  import Fields from './Fields.svelte'
  import Users from './Users.svelte'
  import System from './System.svelte'
  import Exports from './Exports.svelte'
  import Import from './Import.svelte'
  import Audit from './Audit.svelte'
  import Tokens from './Tokens.svelte'
  import Webhooks from './Webhooks.svelte'
  import ActiveDirectory from './ActiveDirectory.svelte'
  import { store } from '../lib/store.svelte'
  import { t } from '../lib/i18n.svelte'

  let { tab }: { tab: string } = $props()
  const tabs = ['fields', 'users', 'ldap', 'carddav', 'outlook', 'ad', 'review', 'mail', 'exports', 'import', 'api', 'general', 'audit']
</script>

{#if !store.isAdmin}
  <div class="page"><p class="muted">{t('err.forbidden')}</p></div>
{:else}
  <div class="page">
    <h1>{t('top.settings')}</h1>
    <nav class="tabs">
      {#each tabs as name}
        <a href="/settings/{name}" class:on={tab === name}>{t(`settings.${name}`)}</a>
      {/each}
    </nav>
    {#if tab === 'fields'}<Fields />
    {:else if tab === 'users'}<Users />
    {:else if tab === 'ldap' || ['carddav', 'outlook', 'review', 'mail', 'general'].includes(tab)}{#key tab}<System section={tab as any} />{/key}
    {:else if tab === 'exports'}<Exports />
    {:else if tab === 'import'}<Import />
    {:else if tab === 'audit'}<Audit />
    {:else if tab === 'api'}<Tokens /><Webhooks />
    {:else if tab === 'ad'}<ActiveDirectory />
    {/if}
  </div>
{/if}

<style>
  .page { max-width: 1200px; margin: 0 auto; padding: 24px 28px 60px; }
  h1 { font-size: 22px; margin-bottom: 12px; }
  .tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin-bottom: 20px; overflow-x: auto; scrollbar-width: none; }
  .tabs a { padding: 8px 12px; color: var(--muted); font-weight: 500; border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap; }
  .tabs a:hover { color: var(--text); text-decoration: none; }
  .tabs a.on { color: var(--text); border-bottom-color: var(--accent); }
  @media (max-width: 860px) { .page { padding: 14px 16px 60px; } }
</style>
