<script lang="ts">
  import { Copy, KeyRound, RefreshCw, Send } from '@lucide/svelte'
  import { ApiError, get, post, put } from '../lib/api'
  import { t, terr, tmsg } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { dateTime } from '../lib/format'

  interface Check { name: string; status: 'ok' | 'warn' | 'crit'; detail: string; age_s: number | null }
  interface Status { status: Check['status']; version: string; at: string; checks: Check[]; metrics: Record<string, number> }

  let s = $state<Record<string, any> | null>(null)
  let errors = $state<Record<string, string>>({})
  let allowlist = $state('')
  let token = $state('') // shown once after generating
  let status = $state<Status | null>(null)
  let loading = $state(false)
  let syslogTest = $state<{ ok?: boolean; error?: string } | null>(null)
  let testing = $state(false)

  get<Record<string, any>>('/api/admin/settings').then((r) => {
    s = r
    allowlist = r.monitoring_allowlist.join('\n')
  })
  async function refresh() {
    loading = true
    status = await get<Status>('/api/admin/monitoring/status').catch(() => null)
    loading = false
  }
  refresh()

  const origin = $derived((s?.base_url || location.origin).replace(/\/$/, ''))
  const statusUrl = $derived(`${origin}/api/monitoring/status`)
  const copy = (v: string) => navigator.clipboard.writeText(v).then(() => toast(t('view.copied')))
  const age = (sec: number | null) => sec == null ? '—' : sec < 120 ? `${sec} s` : sec < 7200 ? `${Math.round(sec / 60)} min` : `${Math.round(sec / 3600)} h`
  const checkName = (n: string) => {
    const [base, rest] = n.split(/:(.*)/s)
    const key = `mon.check.${base}`
    return (t(key) !== key ? t(key) : base) + (rest ? `: ${rest}` : '')
  }

  async function save() {
    errors = {}
    const body = { ...$state.snapshot(s), monitoring_allowlist: allowlist.split(/[\s,]+/).filter(Boolean) } as Record<string, any>
    try {
      s = await put('/api/admin/settings', body)
      allowlist = s!.monitoring_allowlist.join('\n')
      toast(t('settings.saved'))
      return true
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
      else toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
      return false
    }
  }

  async function genToken() {
    token = (await post<{ token: string }>('/api/admin/monitoring/token')).token
    s!.monitoring_token_set = true
  }

  async function testSyslog() {
    testing = true
    syslogTest = null
    if (await save()) syslogTest = await post('/api/admin/syslog/test').catch(() => ({ error: t('err.generic') }))
    testing = false
  }

  const err = (k: string) => errors[k] ? (errors[k].startsWith('invalid_network:') ? t('mon.bad_network', { v: errors[k].slice(16) }) : terr(errors[k])) : ''
</script>

<div class="stack">
  <section class="card box">
    <div class="head">
      <h2>{t('mon.status')}</h2>
      {#if status}<span class="badge {status.status === 'ok' ? 'ok' : status.status === 'warn' ? 'warn' : 'err'}">{t(`mon.state.${status.status}`)}</span>{/if}
      <span class="spacer"></span>
      <button class="btn sm" class:spin={loading} onclick={refresh}><RefreshCw size={13} />{t('mon.refresh')}</button>
    </div>
    {#if status}
      <table class="grid">
        <thead><tr><th>{t('mon.check')}</th><th>{t('mon.state')}</th><th>{t('mon.age')}</th><th>{t('mon.detail')}</th></tr></thead>
        <tbody>
          {#each status.checks as c (c.name)}
            <tr>
              <td>{checkName(c.name)}</td>
              <td><span class="badge {c.status === 'ok' ? 'ok' : c.status === 'warn' ? 'warn' : 'err'}">{t(`mon.state.${c.status}`)}</span></td>
              <td class="tabular muted">{age(c.age_s)}</td>
              <td class="detail">{c.detail}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="metrics">
        {#each Object.entries(status.metrics) as [k, v]}<div><span class="muted">{k}</span> <strong class="tabular">{v}</strong></div>{/each}
      </div>
      <p class="hint">{t('mon.version', { v: status.version })} · {dateTime(status.at)}</p>
    {/if}
  </section>

  {#if s}
    <form class="card box" onsubmit={(e) => { e.preventDefault(); save() }}>
      <h2>{t('mon.access')}</h2>
      <p class="hint">{t('mon.access_hint')}</p>
      <div class="result info">
        <div><code>{origin}/healthz</code> · <code>{origin}/readyz</code> – {t('mon.probes')}</div>
        <div><code>{statusUrl}</code> <button type="button" class="btn sm icon ghost" aria-label={t('mon.copy_url')} onclick={() => copy(statusUrl)}><Copy size={13} /></button>
          · <code>?format=prtg</code></div>
      </div>
      <div>
        <span class="label">{t('mon.token')}</span>
        <button type="button" class="btn" onclick={genToken}><KeyRound size={15} />{s.monitoring_token_set ? t('mon.token_regen') : t('mon.token_gen')}</button>
      </div>
      {#if token}
        <div class="result">
          {t('carddav.once')}<br />
          <code>{token}</code> <button type="button" class="btn sm icon ghost" aria-label={t('mon.copy_token')} onclick={() => copy(token)}><Copy size={13} /></button>
        </div>
      {/if}
      <div>
        <label class="label" for="allow">{t('mon.allowlist')}</label>
        <textarea id="allow" class="input mono" rows="3" bind:value={allowlist} placeholder="10.0.5.20&#10;10.0.6.0/24"></textarea>
        <p class="hint">{t('mon.allowlist_hint')}</p>
        {#if errors.monitoring_allowlist}<div class="error-text">{err('monitoring_allowlist')}</div>{/if}
      </div>

      <h2>{t('mon.syslog')}</h2>
      <p class="hint">{t('mon.syslog_hint')}</p>
      <label class="check"><input type="checkbox" bind:checked={s.syslog_enabled} /> {t('mon.syslog_enabled')}</label>
      <div class="row3">
        <div><label class="label" for="sh">{t('mon.syslog_host')}</label><input id="sh" class="input" bind:value={s.syslog_host} placeholder="siem.example.local" />
          {#if errors.syslog_host}<div class="error-text">{err('syslog_host')}</div>{/if}</div>
        <div><label class="label" for="sp">{t('mon.syslog_port')}</label><input id="sp" class="input" type="number" min="1" max="65535" bind:value={s.syslog_port} />
          {#if errors.syslog_port}<div class="error-text">{err('syslog_port')}</div>{/if}</div>
        <div><label class="label" for="spr">{t('mon.syslog_protocol')}</label>
          <select id="spr" class="select" bind:value={s.syslog_protocol}>
            <option value="udp">UDP</option><option value="tcp">TCP</option><option value="tls">TLS</option>
          </select></div>
      </div>
      {#if s.syslog_protocol === 'tls'}
        <div>
          <label class="label" for="sca">{t('mon.syslog_ca')}</label>
          <textarea id="sca" class="input mono" rows="3" bind:value={s.syslog_ca_cert} placeholder="-----BEGIN CERTIFICATE-----"></textarea>
        </div>
        <label class="check"><input type="checkbox" bind:checked={s.syslog_tls_verify} /> {t('mon.syslog_verify')}</label>
      {/if}
      <div class="row3">
        <div><label class="label" for="sf">{t('mon.syslog_facility')}</label>
          <select id="sf" class="select" bind:value={s.syslog_facility}>
            {#each ['local0', 'local1', 'local2', 'local3', 'local4', 'local5', 'local6', 'local7', 'auth', 'authpriv', 'daemon', 'user'] as f}<option value={f}>{f}</option>{/each}
          </select></div>
        <div class="span2"><label class="label" for="sc">{t('mon.syslog_content')}</label>
          <select id="sc" class="select" bind:value={s.syslog_content}>
            <option value="audit">{t('mon.content_audit')}</option>
            <option value="audit_and_app">{t('mon.content_all')}</option>
          </select></div>
      </div>
      <div class="test">
        <button type="button" class="btn" onclick={testSyslog} disabled={testing}><Send size={15} />{t('mon.syslog_test')}</button>
      </div>
      {#if syslogTest}
        <div class="result" class:bad={syslogTest.error}>
          {#if syslogTest.error}<strong>{t('graph.failed')}:</strong> {tmsg(syslogTest.error)}{:else}✓ {t('mon.syslog_sent')}{/if}
        </div>
      {/if}
      {#if s.syslog_enabled && s.syslog_status?.at}
        <div class="result" class:bad={s.syslog_status.error} class:info={!s.syslog_status.error}>
          {#if s.syslog_status.error}<strong>{t('mon.syslog_failing')}:</strong> {s.syslog_status.error}{:else}{t('mon.syslog_ok', { at: dateTime(s.syslog_status.at) })}{/if}
        </div>
      {/if}

      <h2>{t('mon.audit')}</h2>
      <div>
        <label class="label" for="ret">{t('mon.retention')}</label>
        <input id="ret" class="input narrow" type="number" min="0" bind:value={s.audit_signin_days} />
        <p class="hint">{t('mon.retention_hint')}</p>
        {#if errors.audit_signin_days}<div class="error-text">{err('audit_signin_days')}</div>{/if}
      </div>
      <div class="actions"><button class="btn primary">{t('common.save')}</button></div>
    </form>
  {/if}
</div>

<style>
  .stack { display: flex; flex-direction: column; gap: 20px; max-width: 900px; }
  .box { padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  h2 { font-size: 15px; margin: 4px 0 0; }
  .head { display: flex; align-items: center; gap: 10px; }
  .head h2 { margin: 0; }
  .spacer { flex: 1; }
  .detail { font-size: 12px; overflow-wrap: anywhere; max-width: 380px; }
  .metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 4px 16px; font-size: 13px; }
  .metrics div { display: flex; justify-content: space-between; gap: 8px; }
  .row3 { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; }
  .span2 { grid-column: span 2; }
  .check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .mono { font: 12px ui-monospace, monospace; }
  code { font: 13px ui-monospace, monospace; overflow-wrap: anywhere; }
  .narrow { width: 120px; }
  .hint { margin: 2px 0 0; }
  .test, .actions { display: flex; gap: 8px; }
  .actions { justify-content: flex-end; }
  .result { padding: 10px 12px; border-radius: 8px; background: var(--ok-soft); color: var(--ok); display: grid; gap: 4px; overflow-wrap: anywhere; }
  .result.bad { background: var(--danger-soft); color: var(--danger); }
  .result.info { background: var(--panel-2); color: var(--text); }
  .spin :global(svg) { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (max-width: 640px) { .row3 { grid-template-columns: 1fr; } .span2 { grid-column: auto; } }
</style>
