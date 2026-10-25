<script lang="ts">
  import { untrack } from 'svelte'
  import { ClipboardCheck, Copy, KeyRound, Phone, PlugZap, RefreshCw, Send, UserPlus } from '@lucide/svelte'
  import { ApiError, get, post, put } from '../lib/api'
  import { store } from '../lib/store.svelte'
  import { i18n, t, terr, tmsg } from '../lib/i18n.svelte'
  import { toast } from '../lib/toast.svelte'
  import { dateTime, relTime } from '../lib/format'

  let { section }: { section: 'ldap' | 'carddav' | 'outlook' | 'review' | 'mail' | 'general' } = $props()

  let s = $state<Record<string, any> | null>(null)
  let errors = $state<Record<string, string>>({})
  let bindPw = $state('')
  let testUser = $state('')
  let testResult = $state<any>(null)
  let testing = $state(false)
  let newCardPw = $state('')
  let graphSecret = $state('')
  let smtpPw = $state('')
  // email templates: an override is stored only where it differs from the default
  let tplKind = $state<'review' | 'reminder' | 'proposals'>('review')
  let tplLang = $state<'de' | 'en'>('de')
  const tplValue = (part: 'subject' | 'body') =>
    s?.mail_templates?.[tplKind]?.[tplLang]?.[part] ?? s?.mail_template_defaults?.[tplKind]?.[tplLang]?.[part] ?? ''
  function setTpl(part: 'subject' | 'body', value: string) {
    const def = s!.mail_template_defaults[tplKind][tplLang]
    const cur = { ...def, ...(s!.mail_templates?.[tplKind]?.[tplLang] ?? {}), [part]: value }
    const all = { ...(s!.mail_templates ?? {}) }
    const langs = { ...(all[tplKind] ?? {}) }
    if (cur.subject === def.subject && cur.body === def.body) delete langs[tplLang]
    else langs[tplLang] = cur
    if (Object.keys(langs).length) all[tplKind] = langs
    else delete all[tplKind]
    s!.mail_templates = all
  }
  function resetTpl() {
    const def = s!.mail_template_defaults[tplKind][tplLang]
    setTpl('subject', def.subject)
    setTpl('body', def.body)
  }
  let mailTo = $state(store.user?.email ?? '')
  let mailResult = $state<any>(null)
  let reviewStats = $state<any>(null)
  const loadStats = () => get('/api/admin/reviews').then((r) => (reviewStats = r))
  if (untrack(() => section) === 'review') loadStats() // keyed per tab by the parent

  async function startReviews(scope: 'all' | 'due') {
    if (!(await save())) return
    const r = await post<any>('/api/admin/reviews', { scope }).catch(() => null)
    if (r) toast(t('review.started', { n: r.created, open: r.already_open, missing: r.no_responsible }))
    loadStats()
    store.sync()
  }

  async function testMail() {
    testing = true
    mailResult = null
    if (await save()) mailResult = await post('/api/admin/mail/test', { to: mailTo }).catch(() => ({ error: t('err.generic') }))
    testing = false
  }
  let graphTest = $state<any>(null)

  // one-time cleanup of numbers saved before normalization: count first, then apply
  let phoneRun = $state<{ count: number; sample: { uid: string; kind: string; name: string; old: string; new: string }[] } | null>(null)
  async function checkPhones() {
    if (await save()) phoneRun = await post('/api/admin/phones/normalize', { dry_run: true })
  }
  async function normalizePhones() {
    const r = await post<{ count: number }>('/api/admin/phones/normalize', { dry_run: false })
    toast(t('phone.done', { n: r.count }))
    phoneRun = null
    store.sync()
  }

  let syncSince = $state<string | null>(null) // "sync now" requested at; cleared once a newer run is reported

  get<Record<string, any>>('/api/admin/settings').then((r) => {
    s = r
    syncSince = r.graph_sync_requested
    relaySince = r.carddav_relay_requested
  })

  $effect(() => {
    if (!syncSince) return
    const since = Date.parse(syncSince)
    const id = setInterval(async () => {
      const r = await get<Record<string, any>>('/api/admin/settings').catch(() => null)
      if (r?.graph_status?.at && Date.parse(r.graph_status.at) >= since) {
        s!.graph_status = r.graph_status
        syncSince = null
      }
    }, 3000)
    return () => clearInterval(id)
  })

  async function syncNow() {
    if (!(await save())) return
    try {
      syncSince = (await post<Record<string, any>>('/api/admin/graph/sync')).graph_sync_requested
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  async function save() {
    errors = {}
    const body = { ...$state.snapshot(s) } as Record<string, any>
    if (bindPw) body.ldap_bind_password = bindPw
    if (graphSecret) body.graph_client_secret = graphSecret
    if (smtpPw) body.smtp_password = smtpPw
    try {
      s = await put('/api/admin/settings', body)
      bindPw = ''
      graphSecret = ''
      smtpPw = ''
      toast(t('settings.saved'))
      store.sync()
      return true
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation') errors = e.fields
      else toast(t('err.generic'), { kind: 'error' })
      return false
    }
  }

  async function test() {
    testing = true
    testResult = null
    await save()
    testResult = await post('/api/admin/ldap/test', { username: testUser }).catch(() => ({ error: t('err.generic') }))
    testing = false
  }

  async function importUsers() {
    testing = true
    if (await save()) s!.ldap_users_status = await post('/api/admin/ldap/import-users').catch(() => ({ error: t('err.generic') }))
    testing = false
  }

  async function testGraph() {
    testing = true
    graphTest = null
    if (await save()) graphTest = await post('/api/admin/graph/test').catch(() => ({ error: t('err.generic') }))
    testing = false
  }

  // CardDAV relay in the DMZ: same "sync now" polling as the Outlook sync
  let relayTest = $state<any>(null)
  let relaySince = $state<string | null>(null)
  $effect(() => {
    if (!relaySince) return
    const since = Date.parse(relaySince)
    const id = setInterval(async () => {
      const r = await get<Record<string, any>>('/api/admin/settings').catch(() => null)
      if (r?.carddav_relay_status?.at && Date.parse(r.carddav_relay_status.at) >= since) {
        s!.carddav_relay_status = r.carddav_relay_status
        relaySince = null
      }
    }, 3000)
    return () => clearInterval(id)
  })
  async function genRelayToken() {
    const r = await post<Record<string, any>>('/api/admin/carddav/relay-token')
    s!.carddav_relay_token_sha256 = r.carddav_relay_token_sha256 // keep unsaved edits in the form
  }
  async function testRelay() {
    testing = true
    relayTest = null
    if (await save()) relayTest = await post('/api/admin/carddav/relay-test').catch(() => ({ error: t('err.generic') }))
    testing = false
  }
  async function relaySync() {
    if (!(await save())) return
    try {
      relaySince = (await post<Record<string, any>>('/api/admin/carddav/relay-sync')).carddav_relay_requested
    } catch (e) {
      toast(e instanceof ApiError ? terr(e.code) : t('err.generic'), { kind: 'error' })
    }
  }

  async function genCardPw() {
    const r = await post<{ password: string }>('/api/admin/carddav/password')
    newCardPw = r.password
    s!.carddav_password_set = true
  }

  const davUrl = $derived(`${(s?.carddav_relay_enabled && s?.carddav_relay_url) || s?.base_url || location.origin}`.replace(/\/$/, '') + '/carddav/')
  const copy = (v: string) => navigator.clipboard.writeText(v).then(() => toast(t('view.copied')))
</script>

{#if s}
  <form class="card form" onsubmit={(e) => { e.preventDefault(); save() }}>
    {#if section === 'general'}
      <div>
        <label class="label" for="lang">{t('general.default_language')}</label>
        <select id="lang" class="select" bind:value={s.default_language}>
          <option value="de">Deutsch</option><option value="en">English</option>
        </select>
      </div>
      <div>
        <label class="label" for="base">{t('general.base_url')}</label>
        <input id="base" class="input" bind:value={s.base_url} placeholder="https://kartei.example.de" />
        <p class="hint">{t('general.base_url_hint')}</p>
      </div>
      <div class="row2">
        <div>
          <label class="label" for="trash">{t('general.trash_days')}</label>
          <input id="trash" class="input" type="number" min="0" bind:value={s.trash_days} />
          <p class="hint">{t('general.trash_hint')}</p>
          {#if errors.trash_days}<div class="error-text">{terr(errors.trash_days)}</div>{/if}
          <label class="check"><input type="checkbox" bind:checked={s.purge_anonymize} /> {t('general.purge_anonymize')}</label>
          <p class="hint">{t('general.purge_anonymize_hint')}</p>
        </div>
        <div>
          <label class="label" for="iv">{t('general.export_interval')}</label>
          <input id="iv" class="input" type="number" min="1" bind:value={s.export_interval_minutes} />
          {#if errors.export_interval_minutes}<div class="error-text">{terr(errors.export_interval_minutes)}</div>{/if}
        </div>
      </div>
      <h3>{t('phone.title')}</h3>
      <label class="check"><input type="checkbox" bind:checked={s.phone_normalize} /> {t('phone.normalize')}</label>
      <div>
        <label class="label" for="pcc">{t('phone.country_code')}</label>
        <input id="pcc" class="input narrow" bind:value={s.phone_country_code} placeholder="+49" />
        <p class="hint">{t('phone.hint')}</p>
        {#if errors.phone_country_code}<div class="error-text">{terr(errors.phone_country_code)}</div>{/if}
      </div>
      <div class="test"><button type="button" class="btn" onclick={checkPhones}><Phone size={15} />{t('phone.check')}</button></div>
      {#if phoneRun}
        <div class="result info">
          <strong>{t('phone.found', { n: phoneRun.count })}</strong>
          {#each phoneRun.sample as x, i (i)}<div class="hint"><a href="/{x.kind}/{x.uid}">{x.name}</a>: {x.old} → {x.new}</div>{/each}
          {#if phoneRun.count}<div><button type="button" class="btn" onclick={normalizePhones}>{t('phone.apply', { n: phoneRun.count })}</button></div>{/if}
        </div>
      {/if}
    {:else if section === 'ldap'}
      <p class="hint">{t('ldap.hint')}</p>
      <div class="result info">
        <label class="check"><input type="checkbox" bind:checked={s.oidc_enabled} /> {t('sso.enabled')}</label>
        <div class="hint">{t('sso.hint', { uri: `${(s.base_url || location.origin).replace(/\/$/, '')}/api/oidc/callback` })}</div>
        {#if errors.oidc_enabled}<div class="error-text">{terr(errors.oidc_enabled)}</div>{/if}
      </div>
      <div>
        <label class="label" for="uri">{t('ldap.uri')}</label>
        <input id="uri" class="input" bind:value={s.ldap_uri} placeholder="ldaps://dc01.example.local" />
      </div>
      <label class="check"><input type="checkbox" bind:checked={s.ldap_start_tls} /> StartTLS</label>
      <div class="row2">
        <div><label class="label" for="bdn">{t('ldap.bind_dn')}</label><input id="bdn" class="input" bind:value={s.ldap_bind_dn} placeholder="CN=svc-kartei,OU=Service,DC=example,DC=local" /></div>
        <div><label class="label" for="bpw">{t('ldap.bind_pw')}</label>
          <input id="bpw" class="input" type="password" bind:value={bindPw} placeholder={s.ldap_bind_password_set ? '••••••••' : ''} autocomplete="new-password" /></div>
      </div>
      <div class="row2">
        <div><label class="label" for="base">{t('ldap.user_base')}</label><input id="base" class="input" bind:value={s.ldap_user_base} placeholder="OU=Users,DC=example,DC=local" /></div>
        <div><label class="label" for="flt">{t('ldap.user_filter')}</label><input id="flt" class="input" bind:value={s.ldap_user_filter} />
          {#if errors.ldap_user_filter}<div class="error-text">{terr(errors.ldap_user_filter)}</div>{/if}</div>
      </div>
      <h3>{t('ldap.groups')}</h3>
      {#each ['admin', 'maintainer', 'read'] as role}
        <div><label class="label" for="g-{role}">{t(`role.${role}`)}</label>
          <input id="g-{role}" class="input" bind:value={s[`ldap_group_${role}`]} placeholder="CN=Kartei-{role},OU=Groups,DC=example,DC=local" /></div>
      {/each}
      <div>
        <label class="label" for="ca">{t('ldap.ca')}</label>
        <textarea id="ca" class="input mono" rows="4" bind:value={s.ldap_ca_cert} placeholder="-----BEGIN CERTIFICATE-----"></textarea>
      </div>
      <div class="test">
        <input class="input" bind:value={testUser} placeholder={t('ldap.test_user')} />
        <button type="button" class="btn" onclick={test} disabled={testing || !s.ldap_uri}><PlugZap size={15} />{t('ldap.test')}</button>
      </div>
      {#if testResult}
        <div class="result" class:bad={testResult.error || !testResult.bind}>
          {#if testResult.error}<strong>{t('ldap.failed')}:</strong> {tmsg(testResult.error)}
          {:else}
            <div>✓ {t('ldap.bind_ok')}</div>
            {#if testUser}
              {#if testResult.user}
                <div>✓ {testResult.user.dn}</div>
                <div>{t('ldap.role')}: <strong>{testResult.user.role ? t(`role.${testResult.user.role}`) : t('ldap.no_role')}</strong></div>
              {:else}<div>✗ {t('ldap.user_not_found')}</div>{/if}
            {/if}
          {/if}
        </div>
      {/if}
      <h3>{t('ldap.import')}</h3>
      <p class="hint">{t('ldap.import_hint')}</p>
      <div class="test">
        <button type="button" class="btn" onclick={importUsers} disabled={testing || !s.ldap_uri}><UserPlus size={15} />{t('ldap.import_now')}</button>
      </div>
      {@const us = s.ldap_users_status}
      {#if us?.at}
        <div class="result" class:info={!us.error} class:bad={us.error}>
          <div title={dateTime(us.at)}>{t('graph.last')}: {relTime(us.at)}</div>
          {#if us.error}<div>{tmsg(us.error)}</div>{:else}<div>{t('ldap.import_result', us)}</div>{/if}
        </div>
      {/if}
    {:else if section === 'review'}
      <p class="hint">{t('review.settings_hint')}</p>
      <div class="modes">
        {#each ['off', 'rolling', 'campaign'] as m}
          <label class="check"><input type="radio" bind:group={s.review_mode} value={m} /> {t(`review.mode_${m}`)}</label>
        {/each}
      </div>
      {#if s.review_mode === 'rolling'}
        <div>
          <label class="label" for="rim">{t('review.interval')}</label>
          <input id="rim" class="input narrow" type="number" min="1" max="120" bind:value={s.review_interval_months} />
          {#if errors.review_interval_months}<div class="error-text">{terr(errors.review_interval_months)}</div>{/if}
        </div>
      {:else if s.review_mode === 'campaign'}
        <div>
          <span class="label">{t('review.campaign_date')}</span>
          <div class="date">
            <input class="input narrow" type="number" min="1" max="31" bind:value={s.review_campaign_day} aria-label={t('review.day')} />
            <select class="select" bind:value={s.review_campaign_month} aria-label={t('review.month')}>
              {#each Array.from({ length: 12 }, (_, i) => i + 1) as m}
                <option value={m}>{new Intl.DateTimeFormat(i18n.lang, { month: 'long' }).format(new Date(2000, m - 1, 1))}</option>
              {/each}
            </select>
          </div>
          {#if errors.review_campaign_day || errors.review_campaign_month}<div class="error-text">{terr('invalid_number')}</div>{/if}
        </div>
      {/if}
      <div>
        <label class="label" for="rrd">{t('review.remind_days')}</label>
        <input id="rrd" class="input narrow" type="number" min="0" max="365" bind:value={s.review_remind_days} />
        <p class="hint">{t('review.remind_hint')}</p>
        {#if errors.review_remind_days}<div class="error-text">{terr(errors.review_remind_days)}</div>{/if}
      </div>
      {#if reviewStats}
        <div class="result info">
          <strong>{t('review.status')}</strong>
          <div>{t('review.stat_open', { n: reviewStats.open })}{#if reviewStats.unnotified}{' · '}{t('review.stat_unnotified', { n: reviewStats.unnotified })}{/if}{#if reviewStats.reminded}{' · '}{t('review.stat_reminded', { n: reviewStats.reminded })}{/if}</div>
          {#if s.review_mode === 'rolling'}<div>{t('review.stat_due', { n: reviewStats.due })}</div>{/if}
          {#if reviewStats.next_campaign}<div>{t('review.stat_next', { date: new Intl.DateTimeFormat(i18n.lang, { dateStyle: 'long' }).format(new Date(reviewStats.next_campaign)) })}</div>{/if}
          {#if reviewStats.no_responsible}
            <div class="err-line">{t('review.stat_missing', { n: reviewStats.no_responsible })}</div>
            <div class="missing">
              {#each reviewStats.no_responsible_sample as r (r.uid)}<a href="/{r.kind}/{r.uid}">{r.name || '—'}</a>{/each}
            </div>
          {/if}
        </div>
      {/if}
      <div class="test">
        {#if s.review_mode === 'rolling'}
          <button type="button" class="btn" onclick={() => startReviews('due')}><ClipboardCheck size={15} />{t('review.start_due')}</button>
        {/if}
        <button type="button" class="btn" onclick={() => startReviews('all')}><ClipboardCheck size={15} />{t('review.start_all')}</button>
      </div>
      <p class="hint">{t('review.mail_hint')}</p>
      <h3>{t('review.proposals')}</h3>
      <label class="check"><input type="checkbox" bind:checked={s.proposal_notify} /> {t('review.proposal_notify')}</label>
      {#if s.proposal_notify}
        <div>
          <label class="label" for="pnt">{t('review.proposal_to')}</label>
          <input id="pnt" class="input" bind:value={s.proposal_notify_to} placeholder="team@example.de, chef@example.de" />
          <p class="hint">{t('review.proposal_to_hint')}</p>
          {#if errors.proposal_notify_to}<div class="error-text">{terr(errors.proposal_notify_to)}</div>{/if}
        </div>
      {/if}
    {:else if section === 'mail'}
      <p class="hint">{t('mail.hint')}</p>
      <div class="modes" role="radiogroup" aria-label={t('mail.transport')}>
        <label class="check"><input type="radio" bind:group={s.mail_transport} value="smtp" /> {t('mail.via_smtp')}</label>
        <label class="check"><input type="radio" bind:group={s.mail_transport} value="graph" /> {t('mail.via_graph')}</label>
      </div>
      {#if s.mail_transport === 'graph'}
        <p class="hint">{t('mail.graph_hint')}</p>
        <div><label class="label" for="gms">{t('mail.graph_sender')}</label>
          <input id="gms" class="input" type="email" bind:value={s.mail_graph_sender} placeholder="kartei@example.de" /></div>
      {:else}
      <div class="row2">
        <div><label class="label" for="sh">{t('mail.host')}</label><input id="sh" class="input" bind:value={s.smtp_host} placeholder="smtp.example.de" /></div>
        <div class="row2">
          <div><label class="label" for="sp">{t('mail.port')}</label><input id="sp" class="input" type="number" bind:value={s.smtp_port} />
            {#if errors.smtp_port}<div class="error-text">{terr(errors.smtp_port)}</div>{/if}</div>
          <div><label class="label" for="ss">{t('mail.security')}</label>
            <select id="ss" class="select" bind:value={s.smtp_security}>
              <option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option><option value="none">{t('mail.none')}</option>
            </select></div>
        </div>
      </div>
      <div class="row2">
        <div><label class="label" for="su">{t('mail.username')}</label><input id="su" class="input" bind:value={s.smtp_username} autocomplete="off" /></div>
        <div><label class="label" for="spw">{t('mail.password')}</label>
          <input id="spw" class="input" type="password" bind:value={smtpPw} placeholder={s.smtp_password_set ? '••••••••' : ''} autocomplete="new-password" /></div>
      </div>
      <div><label class="label" for="sf">{t('mail.from')}</label><input id="sf" class="input" bind:value={s.smtp_from} placeholder="Kartei <kartei@example.de>" /></div>
      {/if}
      <div class="test">
        <input class="input" type="email" bind:value={mailTo} placeholder={t('mail.test_to')} />
        <button type="button" class="btn" onclick={testMail} disabled={testing || (s.mail_transport === 'graph' ? !s.mail_graph_sender : !s.smtp_host)}><Send size={15} />{t('mail.test')}</button>
      </div>
      {#if mailResult}
        <div class="result" class:bad={tmsg(mailResult.error)}>
          {#if mailResult.error}<strong>{t('graph.failed')}:</strong> {tmsg(mailResult.error)}{:else}✓ {t('mail.test_ok', { to: mailResult.to })}{/if}
        </div>
      {/if}
      <h3>{t('mail.templates')}</h3>
      <p class="hint">{t('mail.templates_hint')}</p>
      <div class="row2">
        <div><label class="label" for="mtk">{t('mail.template')}</label>
          <select id="mtk" class="select" bind:value={tplKind}>
            {#each ['review', 'reminder', 'proposals'] as k}<option value={k}>{t(`mail.tpl_${k}`)}</option>{/each}
          </select></div>
        <div><label class="label" for="mtl">{t('account.language')}</label>
          <select id="mtl" class="select" bind:value={tplLang}><option value="de">Deutsch</option><option value="en">English</option></select></div>
      </div>
      <div><label class="label" for="mts">{t('mail.subject')}</label>
        <input id="mts" class="input" value={tplValue('subject')} oninput={(e) => setTpl('subject', e.currentTarget.value)} /></div>
      <div><label class="label" for="mtb">{t('mail.body')}</label>
        <textarea id="mtb" class="input mono" rows="9" value={tplValue('body')} oninput={(e) => setTpl('body', e.currentTarget.value)}></textarea>
        {#if errors.mail_templates}<div class="error-text">{terr(errors.mail_templates)}</div>{/if}</div>
      <div class="test">
        <span class="hint">{t('mail.placeholders')}</span>
        <button type="button" class="btn sm" onclick={resetTpl} disabled={!s.mail_templates?.[tplKind]?.[tplLang]}>{t('mail.reset')}</button>
      </div>
    {:else if section === 'outlook'}
      <p class="hint">{t('graph.hint')}</p>
      <label class="check"><input type="checkbox" bind:checked={s.graph_enabled} /> {t('graph.enabled')}</label>
      {#if errors.graph_enabled}<div class="error-text">{terr(errors.graph_enabled)}</div>{/if}
      <div class="row2">
        <div><label class="label" for="gt">{t('graph.tenant')}</label><input id="gt" class="input mono" bind:value={s.graph_tenant_id} placeholder="00000000-0000-0000-0000-000000000000" /></div>
        <div><label class="label" for="gc">{t('graph.client')}</label><input id="gc" class="input mono" bind:value={s.graph_client_id} placeholder="00000000-0000-0000-0000-000000000000" /></div>
      </div>
      <div class="row2">
        <div><label class="label" for="gs">{t('graph.secret')}</label>
          <input id="gs" class="input" type="password" bind:value={graphSecret} placeholder={s.graph_client_secret_set ? '••••••••' : ''} autocomplete="new-password" /></div>
        <div><label class="label" for="gg">{t('graph.group')}</label><input id="gg" class="input mono" bind:value={s.graph_group_id} placeholder="00000000-0000-0000-0000-000000000000" /></div>
      </div>
      <div>
        <label class="label" for="gf">{t('graph.folder')}</label>
        <input id="gf" class="input" bind:value={s.graph_folder} />
        <p class="hint">{t('graph.folder_hint')}</p>
        {#if errors.graph_folder}<div class="error-text">{terr(errors.graph_folder)}</div>{/if}
      </div>
      <div class="test">
        <button type="button" class="btn" onclick={testGraph} disabled={testing}><PlugZap size={15} />{t('graph.test')}</button>
        <button type="button" class="btn" class:spin={syncSince} onclick={syncNow} disabled={!!syncSince || !s.graph_enabled}><RefreshCw size={15} />{t('graph.sync_now')}</button>
      </div>
      {#if graphTest}
        <div class="result" class:bad={tmsg(graphTest.error)}>
          {#if graphTest.error}<strong>{t('graph.failed')}:</strong> {tmsg(graphTest.error)}
          {:else}<div>✓ {t('graph.test_ok', { n: graphTest.mailboxes })}</div>
            {#each graphTest.sample as mail}<div class="hint">{mail}</div>{/each}{/if}
        </div>
      {/if}
      {@const st = s.graph_status}
      <div class="result" class:info={!st?.error} class:bad={st?.error}>
        <strong>{t('graph.last')}</strong>
        {#if syncSince}<div>{t('graph.syncing')}</div>{/if}
        {#if !st?.at}<div>{t('graph.never')}</div>
        {:else}
          <div title={dateTime(st.at)}>{relTime(st.at)}</div>
          {#if st.error}<div>{tmsg(st.error)}</div>
          {:else}<div>{t('graph.result', { photos: 0, ...st })}</div>
            {#each st.failed as f}<div class="err-line">{tmsg(f)}</div>{/each}{/if}
        {/if}
      </div>
      <div class="result info">
        <strong>{t('graph.setup')}</strong>
        <div class="hint">1. {t('graph.setup_app')}</div>
        <div class="hint">2. {t('graph.setup_scope')}</div>
        <div class="hint">{t('graph.fields_hint')}</div>
      </div>
    {:else}
      <label class="check"><input type="checkbox" bind:checked={s.carddav_enabled} /> {t('carddav.enabled')}</label>
      <div class="row2">
        <div><label class="label" for="cu">{t('login.username')}</label><input id="cu" class="input" bind:value={s.carddav_username} /></div>
        <div>
          <span class="label">{t('login.password')}</span>
          <button type="button" class="btn" onclick={genCardPw}><KeyRound size={15} />{s.carddav_password_set ? t('carddav.regen') : t('carddav.gen')}</button>
        </div>
      </div>
      {#if newCardPw}
        <div class="result">
          {t('carddav.once')}<br />
          <code>{newCardPw}</code> <button type="button" class="btn sm icon ghost" onclick={() => copy(newCardPw)}><Copy size={13} /></button>
        </div>
      {/if}
      <h3>{t('carddav.relay')}</h3>
      <p class="hint">{t('carddav.relay_hint')}</p>
      <label class="check"><input type="checkbox" bind:checked={s.carddav_relay_enabled} /> {t('carddav.relay_enabled')}</label>
      {#if errors.carddav_relay_enabled}<div class="error-text">{terr(errors.carddav_relay_enabled)}</div>{/if}
      {#if s.carddav_relay_enabled && s.carddav_enabled}<div class="err-line">{t('carddav.relay_builtin_on')}</div>{/if}
      <div>
        <label class="label" for="rurl">{t('carddav.relay_url')}</label>
        <input id="rurl" class="input" bind:value={s.carddav_relay_url} placeholder="https://carddav.example.de" />
        {#if errors.carddav_relay_url}<div class="error-text">{terr(errors.carddav_relay_url)}</div>{/if}
      </div>
      <div>
        <span class="label">{t('carddav.relay_token')}</span>
        <div class="test">
          <button type="button" class="btn" onclick={genRelayToken}><KeyRound size={15} />{s.carddav_relay_token_sha256 ? t('carddav.relay_token_regen') : t('carddav.relay_token_gen')}</button>
        </div>
        {#if s.carddav_relay_token_sha256}
          <p class="hint">{t('carddav.relay_token_hint')}</p>
          <div><code>{s.carddav_relay_token_sha256}</code> <button type="button" class="btn sm icon ghost" onclick={() => copy(s!.carddav_relay_token_sha256)}><Copy size={13} /></button></div>
        {/if}
      </div>
      <label class="check"><input type="checkbox" bind:checked={s.carddav_relay_tls_verify} /> {t('carddav.relay_tls_verify')}</label>
      {#if s.carddav_relay_tls_verify}
        <div>
          <label class="label" for="rca">{t('carddav.relay_ca')}</label>
          <textarea id="rca" class="input mono" rows="3" bind:value={s.carddav_relay_ca_cert} placeholder="-----BEGIN CERTIFICATE-----"></textarea>
          {#if errors.carddav_relay_ca_cert}<div class="error-text">{terr(errors.carddav_relay_ca_cert)}</div>{/if}
        </div>
      {/if}
      <div>
        <label class="label" for="rguard">{t('ad.guard')}</label>
        <input id="rguard" class="input narrow" type="number" min="0" max="100" bind:value={s.carddav_relay_max_delete_percent} />
        <p class="hint">{t('ad.guard_hint')}</p>
        {#if errors.carddav_relay_max_delete_percent}<div class="error-text">{terr(errors.carddav_relay_max_delete_percent)}</div>{/if}
      </div>
      <div class="test">
        <button type="button" class="btn" onclick={testRelay} disabled={testing || !s.carddav_relay_url}><PlugZap size={15} />{t('carddav.relay_test')}</button>
        <button type="button" class="btn" class:spin={relaySince} onclick={relaySync} disabled={!!relaySince || !s.carddav_relay_enabled}><RefreshCw size={15} />{t('graph.sync_now')}</button>
      </div>
      {#if relayTest}
        <div class="result" class:bad={relayTest.error}>
          {#if relayTest.error}<strong>{t('graph.failed')}:</strong> {tmsg(relayTest.error)}{:else}✓ {t('carddav.relay_test_ok', relayTest)}{/if}
        </div>
      {/if}
      {#if s.carddav_relay_enabled || s.carddav_relay_status?.at}
        {@const rs = s.carddav_relay_status}
        <div class="result" class:info={!rs?.error} class:bad={rs?.error}>
          <strong>{t('graph.last')}</strong>
          {#if relaySince}<div>{t('graph.syncing')}</div>{/if}
          {#if !rs?.at}<div>{t('graph.never')}</div>
          {:else}
            <div title={dateTime(rs.at)}>{relTime(rs.at)}</div>
            {#if rs.error}<div>{tmsg(rs.error)}</div>{:else}<div>{t('carddav.relay_result', rs)}</div>{/if}
          {/if}
        </div>
      {/if}
      <div class="result info">
        <strong>{t('carddav.setup')}</strong>
        <div>{t('carddav.server')}: <code>{davUrl}</code> <button type="button" class="btn sm icon ghost" onclick={() => copy(davUrl)}><Copy size={13} /></button></div>
        <div class="hint">{t('carddav.ios')}</div>
        <div class="hint">{t('carddav.android')}</div>
        <div class="hint">{t('carddav.fields_hint')}</div>
      </div>
    {/if}
    <div class="actions"><button class="btn primary">{t('common.save')}</button></div>
  </form>
{/if}

<style>
  .form { max-width: 720px; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  h3 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-top: 6px; }
  .mono { font: 12px ui-monospace, monospace; }
  .test { display: flex; gap: 8px; }
  .result { padding: 10px 12px; border-radius: 8px; background: var(--ok-soft); color: var(--ok); display: grid; gap: 4px; overflow-wrap: anywhere; }
  .result.bad { background: var(--danger-soft); color: var(--danger); }
  .result.info { background: var(--panel-2); color: var(--text); }
  .spin :global(svg) { animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .modes { display: flex; gap: 18px; flex-wrap: wrap; }
  .narrow { width: 100px; }
  .date { display: flex; gap: 8px; }
  .date .select { width: auto; }
  .missing { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 13px; }
  .err-line { color: var(--danger); font-size: 12px; }
  code { font: 13px ui-monospace, monospace; }
  .hint { margin: 2px 0 0; }
  .actions { display: flex; justify-content: flex-end; }
  @media (max-width: 640px) { .row2 { grid-template-columns: 1fr; } }
</style>
