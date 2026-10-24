<script lang="ts">
  // A record that isn't in the local list: merged away (follow to the record it lives on in), not synced yet, or gone.
  import { ApiError, get } from '../lib/api'
  import { go } from '../lib/router.svelte'
  import { store } from '../lib/store.svelte'
  import { t } from '../lib/i18n.svelte'
  import type { Rec } from '../lib/types'

  let { uid }: { uid: string } = $props()
  let gone = $state(false)

  $effect(() => {
    gone = false
    get<Rec>(`/api/records/${uid}`).then((r) => {
      if (r.deleted_at) gone = true
      else store.upsert(r)
    }).catch((e) => {
      if (e instanceof ApiError && e.code === 'merged') go(`/${e.body.kind}/${e.body.uid}`, true)
      else gone = true
    })
  })
</script>

{#if gone}<div class="placeholder">{t('view.not_found')}</div>{/if}

<style>
  .placeholder { height: 100%; display: grid; place-content: center; text-align: center; color: var(--muted); }
</style>
