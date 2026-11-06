<script lang="ts">
  // Share one contact: its vCard as a QR code (scanned with a phone's camera) and as a file to download.
  // Native <dialog> like ConfirmDialog: modal, focus trap, Esc or a click on the backdrop closes it.
  import { Download, X } from '@lucide/svelte'
  import { t } from '../lib/i18n.svelte'
  import { displayName } from '../lib/search'
  import type { Rec } from '../lib/types'

  let { rec, onclose }: { rec: Rec; onclose: () => void } = $props()
  let dialog: HTMLDialogElement
  let flavour = $state<'ios' | 'android'>(/android/i.test(navigator.userAgent) ? 'android' : 'ios')
  let qr = $state<string | null>(null)
  let tooLong = $state(false)

  $effect(() => {
    if (!dialog.open) dialog.showModal()
  })

  $effect(() => {
    const url = `/${rec.kind}/${rec.uid}.vcf?qr=1&flavour=${flavour}`
    qr = null
    tooLong = false
    Promise.all([fetch(url).then((r) => r.text()), import('qrcode-generator')]).then(([vcf, { default: qrcode }]) => {
      const code = qrcode(0, 'L')
      // the library writes each character as one byte (Latin-1): hand it the UTF-8 bytes so umlauts survive
      code.addData(String.fromCharCode(...new TextEncoder().encode(vcf)), 'Byte')
      try {
        code.make()
        qr = code.createSvgTag({ cellSize: 4, margin: 4, scalable: true })
      } catch { // more than a QR code holds (about 2.9 KB): the download still works
        tooLong = true
      }
    })
  })

  // the content fills the dialog, so a click on the dialog itself is a click on the backdrop
  function onpointerdown(e: PointerEvent) {
    if (e.target === dialog) dialog.close()
  }
</script>

<dialog bind:this={dialog} class="share" aria-labelledby="share-title" {onclose} {onpointerdown}>
  <div class="body">
    <div class="head">
      <h2 id="share-title">{t('share.title')}</h2>
      <button class="btn icon ghost" onclick={() => dialog.close()} aria-label={t('common.close')}><X size={16} /></button>
    </div>
    <div class="seg" role="group" aria-label={t('share.phone')}>
      <button class:on={flavour === 'ios'} aria-pressed={flavour === 'ios'} onclick={() => (flavour = 'ios')}>iPhone</button>
      <button class:on={flavour === 'android'} aria-pressed={flavour === 'android'} onclick={() => (flavour = 'android')}>Android</button>
    </div>
    <div class="qr" role="img" aria-label={t('share.qr_alt', { name: displayName(rec) })}>
      {#if qr}{@html qr}{:else if tooLong}<p class="muted">{t('share.too_long')}</p>{/if}
    </div>
    <p class="hint">{t('share.hint')}</p>
    <a class="btn primary" href="/{rec.kind}/{rec.uid}.vcf?flavour={flavour}" download><Download size={15} />{t('share.download')}</a>
  </div>
</dialog>

<style>
  .share { width: min(380px, calc(100vw - 32px)); padding: 0; border: 1px solid var(--border); border-radius: 12px;
    background: var(--panel); color: var(--text); box-shadow: var(--shadow-lg); }
  .share::backdrop { background: light-dark(rgb(24 24 27 / 0.35), rgb(0 0 0 / 0.6)); }
  .body { display: flex; flex-direction: column; gap: 12px; padding: 18px 20px 20px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { font-size: 16px; }
  .seg { display: flex; gap: 2px; padding: 2px; border-radius: 8px; background: var(--panel-2); align-self: center; }
  .seg button { border: 0; background: none; padding: 4px 14px; border-radius: 6px; font: inherit; color: var(--muted); cursor: pointer; }
  .seg button.on { background: var(--panel); color: var(--text); box-shadow: 0 1px 2px rgb(0 0 0 / 0.08); }
  /* always dark modules on white: phone cameras read that best, also in dark mode */
  .qr { display: grid; place-items: center; aspect-ratio: 1; width: 100%; background: #fff; border-radius: 8px; color: #000; }
  .qr :global(svg) { width: 100%; height: 100%; }
  .qr p { padding: 16px; text-align: center; color: #52525b; }
  .hint { margin: 0; text-align: center; }
  .btn.primary { justify-content: center; }
</style>
