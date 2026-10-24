<script lang="ts">
  // The app's single confirmation dialog, driven by confirmDialog() in lib/confirm.svelte.ts. Native <dialog>:
  // modal with focus trap, Esc or a click on the backdrop cancels, Enter confirms (the confirm button has focus).
  import { TriangleAlert } from '@lucide/svelte'
  import { confirmState, settle } from '../lib/confirm.svelte'
  import { t } from '../lib/i18n.svelte'

  let dialog: HTMLDialogElement
  let checked = $state(false)
  const p = $derived(confirmState.current)

  $effect(() => {
    if (!p) return
    checked = p.opts.checkbox?.checked ?? false
    dialog.returnValue = ''
    if (!dialog.open) dialog.showModal()
    dialog.querySelector<HTMLButtonElement>('button[value=ok]')?.focus()
  })

  function onclose() {
    settle(dialog.returnValue === 'ok' ? { checked } : null)
  }

  // the form fills the dialog, so a click on the dialog itself is a click on the backdrop
  function onpointerdown(e: PointerEvent) {
    if (e.target === dialog) dialog.close()
  }
</script>

<dialog bind:this={dialog} class="confirm" aria-labelledby="confirm-title" aria-describedby="confirm-message"
        {onclose} {onpointerdown}>
  {#if p}
    <form method="dialog">
      <div class="head">
        {#if p.opts.danger}<span class="icon" aria-hidden="true"><TriangleAlert size={18} /></span>{/if}
        <h2 id="confirm-title">{p.opts.title}</h2>
      </div>
      <p id="confirm-message">{p.opts.message}</p>
      {#if p.opts.checkbox}
        <label class="check"><input type="checkbox" bind:checked />{p.opts.checkbox.label}</label>
      {/if}
      <div class="buttons">
        <button class="btn" value="cancel">{t('common.cancel')}</button>
        <button class="btn" class:primary={!p.opts.danger} class:fill={p.opts.danger} value="ok">{p.opts.confirmLabel}</button>
      </div>
    </form>
  {/if}
</dialog>

<style>
  .confirm { width: min(460px, calc(100vw - 32px)); padding: 0; border: 1px solid var(--border); border-radius: 12px;
    background: var(--panel); color: var(--text); box-shadow: var(--shadow-lg); }
  .confirm[open] { animation: in 0.16s cubic-bezier(0.2, 0.8, 0.2, 1); }
  .confirm::backdrop { background: light-dark(rgb(24 24 27 / 0.35), rgb(0 0 0 / 0.6)); }
  form { display: flex; flex-direction: column; gap: 12px; padding: 20px 22px 18px; }
  .head { display: flex; align-items: center; gap: 10px; }
  .icon { flex: none; display: grid; place-items: center; width: 32px; height: 32px; border-radius: 50%;
    background: var(--danger-soft); color: var(--danger); }
  h2 { font-size: 16px; }
  p { margin: 0; color: var(--muted); white-space: pre-line; }
  .check { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border-radius: var(--radius);
    background: var(--panel-2); cursor: pointer; }
  .check input { margin-top: 2px; flex: none; }
  .buttons { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
  .btn.fill { background: var(--danger); border-color: var(--danger); color: light-dark(#fff, #0f0f12); }
  .btn.fill:hover { background: color-mix(in srgb, var(--danger) 88%, var(--text)); }
  @keyframes in { from { opacity: 0; transform: translateY(6px) scale(0.98); } }
</style>
