import { api, get, post } from './api'

/** Web Push on this device: the browser subscribes with the server's key, the server sends new reviews/proposals.
 * iPhone: only in the installed app (home screen), iOS 16.4 or newer. */

export const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

const b64u = (b: ArrayBuffer | null) =>
  b ? btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') : ''

function bytes(key: string) {
  const s = atob(key.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(s, (c) => c.charCodeAt(0))
}

/** null when there is no service worker (development server, or not supported) */
async function registration() {
  return pushSupported() ? ((await navigator.serviceWorker.getRegistration()) ?? null) : null
}

export async function pushSubscription() {
  return (await (await registration())?.pushManager.getSubscription()) ?? null
}

/** Asks for permission, subscribes and tells the server. false: the user (or the browser) said no. */
export async function enablePush(): Promise<boolean> {
  const reg = await registration()
  if (!reg || (await Notification.requestPermission()) !== 'granted') return false
  const { key } = await get<{ key: string }>('/api/me/push')
  let sub = await reg.pushManager.getSubscription()
  if (sub && b64u(sub.options.applicationServerKey) !== key) {
    await sub.unsubscribe() // made with an older server key: would never get anything
    sub = null
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes(key) })
  await post('/api/me/push', sub.toJSON())
  return true
}

export async function disablePush() {
  const sub = await pushSubscription()
  if (!sub) return
  await api('DELETE', '/api/me/push', { endpoint: sub.endpoint }).catch(() => {})
  await sub.unsubscribe()
}

const ASKED = 'kartei:push-asked'

/** After signing in and on every app start. Already on: tells the server again (signed in as someone else, server
 * key changed, subscription renewed). Never asked on this device: the browser's own question right away; Safari and
 * Firefox only ask after a tap or click, so then at the first one. Asked once per device; later only via My account. */
export function startPush() {
  if (!pushSupported()) return
  if (Notification.permission === 'granted') {
    pushSubscription().then((sub) => sub && enablePush()).catch(() => {})
    return
  }
  if (Notification.permission !== 'default' || localStorage.getItem(ASKED)) return
  const ask = () => {
    localStorage.setItem(ASKED, '1')
    enablePush().catch(() => {})
  }
  enablePush()
    .then((ok) => {
      if (ok || Notification.permission !== 'default') localStorage.setItem(ASKED, '1')
      else document.addEventListener('click', ask, { once: true, capture: true }) // asking needed a user gesture
    })
    .catch(() => {})
}
