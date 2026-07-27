import type { ReactNode } from 'react'
import { Provider } from 'react-redux'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { BrowserRouter } from 'react-router-dom'
import { store } from './store'
import { queryClient } from './queryClient'
import { queryPersister } from './persister'
import { AppThemeProvider } from './AppThemeProvider'
import { registerOfflineMutationDefaults } from '../features/conversations/api'

// Runs once, at module load, before anything renders — not on every
// AppProviders render. See registerOfflineMutationDefaults's own
// docstring for why a real (non-closure) mutationFn needs to be
// registered for offline-queued mutations to survive a reload.
registerOfflineMutationDefaults(queryClient)

const ONE_DAY_MS = 24 * 60 * 60 * 1000

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <Provider store={store}>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{
          persister: queryPersister,
          maxAge: ONE_DAY_MS,
          dehydrateOptions: {
            // Only ever persist paused mutations (e.g. a reply sent while
            // offline) across a reload — never cached read data, which
            // could go stale or, for conversation/customer content, isn't
            // something that belongs sitting in localStorage. See
            // docs/architecture/frontend.md's "Offline support" section.
            shouldDehydrateQuery: () => false,
          },
        }}
        onSuccess={() => {
          // Restoring only rebuilds paused mutations in the cache — it
          // doesn't retry them itself. If still offline this is a no-op
          // (mutations stay paused until onlineManager reports online),
          // exactly like a mutation paused earlier in the same session.
          void queryClient.resumePausedMutations()
        }}
      >
        <AppThemeProvider>
          <BrowserRouter>{children}</BrowserRouter>
        </AppThemeProvider>
        {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
      </PersistQueryClientProvider>
    </Provider>
  )
}
