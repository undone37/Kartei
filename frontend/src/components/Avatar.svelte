<script lang="ts">
  import { Building2 } from '@lucide/svelte'
  import type { Rec } from '../lib/types'

  let { rec, size = 36 }: { rec: Rec; size?: number } = $props()

  const initials = $derived(
    rec.kind === 'company'
      ? ''
      : ((rec.first_name[0] ?? '') + (rec.last_name[0] ?? '')).toUpperCase() || '?',
  )
  // stable pastel hue per record
  const hue = $derived([...rec.uid].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7))
</script>

<span class="avatar" class:company={rec.kind === 'company'}
      style="--s:{size}px; --h:{hue}">
  {#if rec.image}
    <img src="/api/img/{rec.uid}?v={rec.image}" alt="" loading="lazy" decoding="async" />
  {:else if rec.kind === 'company'}
    <Building2 size={size * 0.5} />
  {:else}
    {initials}
  {/if}
</span>

<style>
  .avatar {
    flex: none; display: inline-grid; place-items: center; width: var(--s); height: var(--s);
    border-radius: 50%; overflow: hidden; font-size: calc(var(--s) * 0.38); font-weight: 600;
    background: light-dark(hsl(var(--h) 70% 92%), hsl(var(--h) 30% 22%));
    color: light-dark(hsl(var(--h) 45% 32%), hsl(var(--h) 60% 80%));
    outline: 1px solid light-dark(rgb(0 0 0 / 0.06), rgb(255 255 255 / 0.08)); outline-offset: -1px;
  }
  .company { border-radius: 22%; background: var(--panel-2); color: var(--muted); }
  img { width: 100%; height: 100%; object-fit: cover; }
  .company img { object-fit: contain; background: #fff; }
</style>
