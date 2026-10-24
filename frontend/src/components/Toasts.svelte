<script lang="ts">
  import { dismiss, toasts } from '../lib/toast.svelte'
</script>

<div class="toasts" aria-live="polite">
  {#each toasts as toast (toast.id)}
    <div class="toast" class:error={toast.kind === 'error'}>
      <span>{toast.text}</span>
      {#if toast.action}
        <button onclick={() => { toast.action!.run(); dismiss(toast.id) }}>{toast.action.label}</button>
      {/if}
    </div>
  {/each}
</div>

<style>
  .toasts { position: fixed; bottom: 20px; left: 50%; translate: -50% 0; display: flex; flex-direction: column; gap: 8px; z-index: 100; pointer-events: none; }
  .toast { pointer-events: auto; display: flex; align-items: center; gap: 14px; padding: 10px 14px; border-radius: 10px;
    background: light-dark(#18181b, #f4f4f5); color: light-dark(#fafafa, #18181b); box-shadow: var(--shadow-lg); min-width: 240px; max-width: 90vw;
    animation: in 0.18s cubic-bezier(0.2, 0.8, 0.2, 1); }
  .toast.error { background: light-dark(#7f1d1d, #fecaca); }
  button { margin-left: auto; border: 0; background: none; color: light-dark(#a5b4fc, #4338ca); font-weight: 600; cursor: pointer; padding: 0; }
  @keyframes in { from { opacity: 0; transform: translateY(8px) scale(0.98); } }
</style>
