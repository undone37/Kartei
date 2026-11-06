<script lang="ts">
  import { DatabaseBackup, RefreshCw, ShieldCheck } from '@lucide/svelte'
  import { ApiError, get, post, put } from '../lib/api'
  import { t, terr } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { dateTime } from '../lib/format'

  let s = $state<Record<string, any> | null>(null)
  let errors = $state<Record<string, string>>({})
  // "back up now" / "test restore" requested at: polled until the exporter reports a newer run
  let pending = $state<{ backup?: string; restore?: string }>({})

  const load = () => get<Record<string, any>>('/api/admin/settings').then((r) => {
    s = r
    if (r.backup_requested) pending.backup = r.backup_requested
    if (r.restore_test_requested) pending.restore = r.restore_test_requested
  })
  load()

  $effect(() => {
    if (!pending.backup && !pending.restore) return
    const id = setInterval(async () => {
      const r = await get<Record<string, any>>('/api/admin/settings').catch(() => null)
      if (!r || !s) return
      const newer = (st: any, since?: string) => since && st?.at && Date.parse(st.at) >= Date.parse(since)
      if (newer(r.backup_status, pending.backup)) { s.backup_status = r.backup_status; pending.backup = undefined }
      if (newer(r.restore_test_status, pending.restore)) { s.restore_test_status = r.restore_test_status; pending.restore = undefined }
    }, 3000)
    return () => clearInterval(id)
  })

  async function save() {
    errors = {}
    try {
      s = await put('/api/admin/settings', { backup_enabled: s!.backup_enabled, backup_time: s!.backup_time, backup_keep_days: s!.backup_keep_days })
      toast(t('settings.saved'))
      return true
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
      else toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
      return false
    }
  }

  async function request(what: 'run' | 'restore-test') {
    const r = await post<Record<string, any>>(`/api/admin/backup/${what}`)
    if (what === 'run') pending.backup = r.backup_requested
    else pending.restore = r.restore_test_requested
  }

  const size = (n: number) => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`
</script>

{#if s}
  <div class="stack">
    <form class="card box" onsubmit={(e) => { e.preventDefault(); save() }}>
      <p class="hint">{t('backup.hint', { dir: s.backup_root })}</p>
      <label class="check"><input type="checkbox" bind:checked={s.backup_enabled} /> {t('backup.enabled')}</label>
      <div class="row2">
        <div>
          <label class="label" for="bt">{t('backup.time')}</label>
          <input id="bt" class="input narrow" type="time" bind:value={s.backup_time} />
          {#if errors.backup_time}<div class="error-text">{terr(errors.backup_time)}</div>{/if}
        </div>
        <div>
          <label class="label" for="bk">{t('backup.keep')}</label>
          <input id="bk" class="input narrow" type="number" min="1" max="365" bind:value={s.backup_keep_days} />
          {#if errors.backup_keep_days}<div class="error-text">{terr(errors.backup_keep_days)}</div>{/if}
        </div>
      </div>
      <div class="actions">
        <button type="button" class="btn" class:spin={pending.backup} disabled={!!pending.backup} onclick={() => request('run')}>
          {#if pending.backup}<RefreshCw size={15} />{:else}<DatabaseBackup size={15} />{/if}{t('backup.run')}</button>
        <button type="button" class="btn" class:spin={pending.restore} disabled={!!pending.restore || !s.backup_status?.files?.length}
                onclick={() => request('restore-test')}>
          {#if pending.restore}<RefreshCw size={15} />{:else}<ShieldCheck size={15} />{/if}{t('backup.restore_test')}</button>
        <span class="spacer"></span>
        <button class="btn primary">{t('common.save')}</button>
      </div>
    </form>

    <section class="card box">
      <h2>{t('backup.last')}</h2>
      {#if !s.backup_status?.at}
        <p class="muted">{t('backup.never')}</p>
      {:else}
        <div class="result" class:bad={s.backup_status.error}>
          {#if s.backup_status.error}<strong>{t('graph.failed')}:</strong> {s.backup_status.error}
          {:else}{t('backup.ok', { at: dateTime(s.backup_status.at), file: s.backup_status.file, size: size(s.backup_status.size), s: s.backup_status.seconds })}{/if}
        </div>
      {/if}
      {#if s.restore_test_status?.at}
        <div class="result" class:bad={s.restore_test_status.error}>
          {#if s.restore_test_status.error}<strong>{t('backup.restore_failed')}:</strong> {s.restore_test_status.error}
          {:else}
            {t('backup.restore_ok', { at: dateTime(s.restore_test_status.at), file: s.restore_test_status.file })}
            <span class="hint">{Object.entries(s.restore_test_status.tables ?? {}).map(([k, [a, b]]: [string, any]) => `${t(`backup.t.${k}`)}: ${a} / ${b}`).join(' · ')}</span>
          {/if}
        </div>
      {/if}
      {#if s.backup_status?.files?.length}
        <table class="grid">
          <thead><tr><th>{t('backup.file')}</th><th>{t('backup.size')}</th><th>{t('backup.when')}</th></tr></thead>
          <tbody>
            {#each s.backup_status.files as f (f.name)}
              <tr><td class="mono">{f.name}</td><td class="tabular">{size(f.size)}</td><td class="tabular muted">{dateTime(f.at)}</td></tr>
            {/each}
          </tbody>
        </table>
        {#if s.backup_status.free != null}<p class="hint">{t('backup.free', { n: s.backup_status.free })}</p>{/if}
      {/if}
      <p class="hint">{t('backup.restore_hint')}</p>
    </section>
  </div>
{/if}

<style>
  .stack { display: flex; flex-direction: column; gap: 20px; max-width: 820px; }
  .box { padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  h2 { font-size: 15px; margin: 0; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .narrow { width: 140px; }
  .check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .spacer { flex: 1; }
  .mono { font: 12px ui-monospace, monospace; }
  .hint { margin: 0; }
  .result { padding: 10px 12px; border-radius: 8px; background: var(--ok-soft); color: var(--ok); display: grid; gap: 4px; overflow-wrap: anywhere; }
  .result.bad { background: var(--danger-soft); color: var(--danger); }
  .result .hint { color: var(--muted); }
  .spin :global(svg) { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (max-width: 640px) { .row2 { grid-template-columns: 1fr; } }
</style>
