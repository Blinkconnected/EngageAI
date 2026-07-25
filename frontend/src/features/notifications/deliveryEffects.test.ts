import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getBrowserNotificationPermission,
  isBrowserNotificationSupported,
  playNotificationSound,
  requestBrowserNotificationPermission,
  showBrowserNotification,
} from './deliveryEffects'

describe('playNotificationSound', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('creates oscillators through a stubbed AudioContext without throwing', () => {
    const oscillatorStart = vi.fn()
    const createOscillator = vi.fn(() => ({
      type: '',
      frequency: { value: 0 },
      connect: vi.fn(),
      start: oscillatorStart,
      stop: vi.fn(),
    }))
    const createGain = vi.fn(() => ({
      gain: {
        setValueAtTime: vi.fn(),
        linearRampToValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn(),
      },
      connect: vi.fn(),
    }))

    class AudioContextStub {
      currentTime = 0
      destination = {}
      createOscillator = createOscillator
      createGain = createGain
    }
    vi.stubGlobal('AudioContext', AudioContextStub)

    expect(() => playNotificationSound()).not.toThrow()

    expect(createOscillator).toHaveBeenCalledTimes(2) // a two-tone chime
    expect(oscillatorStart).toHaveBeenCalledTimes(2)
  })

  it('does nothing when no AudioContext constructor exists at all', () => {
    vi.stubGlobal('AudioContext', undefined)
    vi.stubGlobal('webkitAudioContext', undefined)
    expect(() => playNotificationSound()).not.toThrow()
  })

  it('never throws even if the AudioContext constructor itself throws', () => {
    vi.stubGlobal(
      'AudioContext',
      vi.fn(() => {
        throw new Error('autoplay blocked')
      }),
    )
    expect(() => playNotificationSound()).not.toThrow()
  })
})

describe('browser notification support/permission', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reports unsupported when window.Notification does not exist', () => {
    vi.stubGlobal('Notification', undefined)
    expect(isBrowserNotificationSupported()).toBe(false)
    expect(getBrowserNotificationPermission()).toBe('unsupported')
  })

  it('reports the current Notification.permission when supported', () => {
    vi.stubGlobal('Notification', { permission: 'granted' })
    expect(isBrowserNotificationSupported()).toBe(true)
    expect(getBrowserNotificationPermission()).toBe('granted')
  })

  it('requestBrowserNotificationPermission resolves "denied" when unsupported', async () => {
    vi.stubGlobal('Notification', undefined)
    await expect(requestBrowserNotificationPermission()).resolves.toBe('denied')
  })

  it('requestBrowserNotificationPermission delegates to Notification.requestPermission', async () => {
    const requestPermission = vi.fn().mockResolvedValue('granted')
    vi.stubGlobal('Notification', { permission: 'default', requestPermission })
    await expect(requestBrowserNotificationPermission()).resolves.toBe('granted')
    expect(requestPermission).toHaveBeenCalledTimes(1)
  })
})

describe('showBrowserNotification', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does nothing when unsupported', () => {
    vi.stubGlobal('Notification', undefined)
    expect(() => showBrowserNotification('Title', 'Body')).not.toThrow()
  })

  it('does nothing when permission is not granted', () => {
    const NotificationCtor = vi.fn()
    vi.stubGlobal('Notification', Object.assign(NotificationCtor, { permission: 'default' }))
    showBrowserNotification('Title', 'Body')
    expect(NotificationCtor).not.toHaveBeenCalled()
  })

  it('constructs a Notification with the given title/body when granted', () => {
    const NotificationCtor = vi.fn()
    vi.stubGlobal('Notification', Object.assign(NotificationCtor, { permission: 'granted' }))
    showBrowserNotification('Title', 'Body')
    expect(NotificationCtor).toHaveBeenCalledWith('Title', { body: 'Body' })
  })

  it('never throws even if the Notification constructor itself throws', () => {
    const NotificationCtor = vi.fn(() => {
      throw new Error('not allowed in this context')
    })
    vi.stubGlobal('Notification', Object.assign(NotificationCtor, { permission: 'granted' }))
    expect(() => showBrowserNotification('Title', 'Body')).not.toThrow()
  })
})
