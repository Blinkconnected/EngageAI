import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister'

/** Backs only the offline-mutation-queue persistence wired in
 * AppProviders.tsx (`shouldDehydrateQuery: () => false` there means
 * cached read data — conversations, messages, customers — is never
 * written here, only paused mutations). `localStorage` rather than
 * `sessionStorage` specifically so a queued reply survives closing and
 * reopening the tab/browser, not just a reload within the same tab. */
export const queryPersister = createSyncStoragePersister({
  storage: window.localStorage,
  key: 'blinkengage-offline-mutation-queue',
})
