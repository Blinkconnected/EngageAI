/**
 * Browser-native delivery side effects for a live notification push —
 * kept as small, individually-mockable functions (rather than inlined
 * into `RealtimeProvider`'s WebSocket handler) so tests can spy on them
 * without needing a real `AudioContext`/`Notification` in jsdom.
 */

type AudioContextConstructor = new () => AudioContext

function resolveAudioContextConstructor(): AudioContextConstructor | undefined {
  const globalWindow = window as unknown as {
    AudioContext?: AudioContextConstructor
    webkitAudioContext?: AudioContextConstructor
  }
  return globalWindow.AudioContext ?? globalWindow.webkitAudioContext
}

/**
 * Synthesizes a short two-tone chime via the Web Audio API rather than
 * playing a bundled audio file — no asset to source, license, or ship,
 * and it works the same way every other self-contained piece of this
 * app does. Best-effort: a sound failing to play (no Web Audio support,
 * an autoplay restriction, ...) must never break notification delivery.
 */
export function playNotificationSound(): void {
  const AudioContextClass = resolveAudioContextConstructor()
  if (!AudioContextClass) return
  try {
    const context = new AudioContextClass()
    const now = context.currentTime
    ;[880, 1108.73].forEach((frequency, index) => {
      const oscillator = context.createOscillator()
      const gain = context.createGain()
      oscillator.type = 'sine'
      oscillator.frequency.value = frequency
      const start = now + index * 0.12
      gain.gain.setValueAtTime(0, start)
      gain.gain.linearRampToValueAtTime(0.2, start + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.18)
      oscillator.connect(gain)
      gain.connect(context.destination)
      oscillator.start(start)
      oscillator.stop(start + 0.2)
    })
  } catch {
    // See docstring above — best-effort only.
  }
}

export function isBrowserNotificationSupported(): boolean {
  return typeof Notification !== 'undefined'
}

export function getBrowserNotificationPermission(): NotificationPermission | 'unsupported' {
  if (!isBrowserNotificationSupported()) return 'unsupported'
  return Notification.permission
}

/** Must be called from a user gesture (e.g. a settings-page toggle
 * click) — most browsers silently ignore/reject an unprompted call. */
export async function requestBrowserNotificationPermission(): Promise<NotificationPermission> {
  if (!isBrowserNotificationSupported()) return 'denied'
  return Notification.requestPermission()
}

export function showBrowserNotification(title: string, body: string): void {
  if (!isBrowserNotificationSupported() || Notification.permission !== 'granted') return
  try {
    new Notification(title, { body })
  } catch {
    // Some browsers throw constructing a Notification outside certain
    // contexts (e.g. a service-worker-less page in some versions) —
    // never let this break the rest of notification delivery.
  }
}
