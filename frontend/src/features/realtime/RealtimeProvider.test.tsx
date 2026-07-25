/**
 * First WebSocket test in this codebase — no prior mocking precedent
 * exists (confirmed via a full-repo search before writing this). A
 * minimal fake `WebSocket` class stood in for jsdom's real one via
 * `vi.stubGlobal`, matching this codebase's existing preference for
 * hand-built fakes over a mocking library wherever a simple one suffices
 * (e.g. the backend's `_FakeWebSocket` for the agent gateway tests).
 */
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, waitFor } from '@testing-library/react'
import { Provider } from 'react-redux'
import { QueryClientProvider } from '@tanstack/react-query'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { authenticated, loggedOut } from '../auth/authSlice'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { NOTIFICATIONS_KEY, PREFERENCES_KEY, UNREAD_COUNT_KEY } from '../notifications/api'
import * as deliveryEffects from '../notifications/deliveryEffects'
import { RealtimeProvider } from './RealtimeProvider'

class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []

  readyState = FakeWebSocket.OPEN
  url: string
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.onclose?.()
  }

  emit(frame: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

function renderProvider() {
  store.dispatch(authenticated({ accessToken: 'mock-access-token', refreshToken: 'mock-refresh' }))
  return render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <RealtimeProvider>
          <div />
        </RealtimeProvider>
      </QueryClientProvider>
    </Provider>,
  )
}

/** RealtimeProvider fetches preferences itself on mount (so every tab's
 * cache is populated, not just one that visited Settings > Notifications
 * > Preferences) — tests that depend on that matrix being resolved must
 * wait for it explicitly, the same way production's async fetch would
 * settle before a live WS frame arrives in practice. */
async function waitForPreferencesLoaded() {
  await waitFor(() => expect(queryClient.getQueryData(PREFERENCES_KEY)).toBeDefined())
}

describe('RealtimeProvider', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    FakeWebSocket.instances = []
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('connects a WebSocket to the agent gateway once authenticated', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    renderProvider()

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    expect(FakeWebSocket.instances[0].url).toContain('/ws/agent?token=mock-access-token')
  })

  it('fetches notification preferences itself so every tab has them cached', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    renderProvider()

    await waitForPreferencesLoaded()
    expect(queryClient.getQueryData(PREFERENCES_KEY)).toBeInstanceOf(Array)
  })

  it('invalidates notification queries and fires delivery effects on a "notification" frame', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const soundSpy = vi.spyOn(deliveryEffects, 'playNotificationSound').mockImplementation(() => {})
    const browserSpy = vi
      .spyOn(deliveryEffects, 'showBrowserNotification')
      .mockImplementation(() => {})
    renderProvider()
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    await waitForPreferencesLoaded()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    act(() => {
      FakeWebSocket.instances[0].emit({
        type: 'notification',
        id: 'n1',
        notification_type: 'conversation.assignment_changed',
        title: 'New conversation assigned',
        body: 'Take a look.',
        payload: {},
      })
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: NOTIFICATIONS_KEY })
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: UNREAD_COUNT_KEY })
    })
    expect(soundSpy).toHaveBeenCalledWith()
    expect(browserSpy).toHaveBeenCalledWith('New conversation assigned', 'Take a look.')
  })

  it('honors a disabled preference for one channel while a sibling channel still fires', async () => {
    server.use(
      http.get(`${API_BASE_URL}/notifications/preferences`, () =>
        HttpResponse.json({
          items: [
            {
              notification_type: 'conversation.assignment_changed',
              label: 'New conversation assigned',
              channel: 'sound',
              enabled: false,
            },
            {
              notification_type: 'conversation.assignment_changed',
              label: 'New conversation assigned',
              channel: 'browser',
              enabled: true,
            },
          ],
        }),
      ),
    )
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const soundSpy = vi.spyOn(deliveryEffects, 'playNotificationSound').mockImplementation(() => {})
    const browserSpy = vi
      .spyOn(deliveryEffects, 'showBrowserNotification')
      .mockImplementation(() => {})
    renderProvider()
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    await waitForPreferencesLoaded()

    act(() => {
      FakeWebSocket.instances[0].emit({
        type: 'notification',
        id: 'n2',
        notification_type: 'conversation.assignment_changed',
        title: 'New conversation assigned',
        body: 'Take a look.',
        payload: {},
      })
    })

    await waitFor(() => expect(browserSpy).toHaveBeenCalledWith('New conversation assigned', 'Take a look.'))
    expect(soundSpy).not.toHaveBeenCalled()
  })

  it('invalidates notification queries but does not fire delivery effects on a "notifications_changed" frame', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const soundSpy = vi.spyOn(deliveryEffects, 'playNotificationSound').mockImplementation(() => {})
    const browserSpy = vi
      .spyOn(deliveryEffects, 'showBrowserNotification')
      .mockImplementation(() => {})
    renderProvider()
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    act(() => {
      FakeWebSocket.instances[0].emit({ type: 'notifications_changed' })
    })

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: NOTIFICATIONS_KEY })
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: UNREAD_COUNT_KEY })
    })
    expect(soundSpy).not.toHaveBeenCalled()
    expect(browserSpy).not.toHaveBeenCalled()
  })

  it('silently ignores a malformed frame', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    renderProvider()
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))

    expect(() => {
      FakeWebSocket.instances[0].onmessage?.({ data: 'not json' })
    }).not.toThrow()
  })
})
