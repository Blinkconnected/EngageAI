/**
 * Shared React Query key constants for state that's read from multiple,
 * otherwise-unrelated modules (e.g. `shared/api/client.ts`'s refresh-token
 * interceptor needs to invalidate the session query without importing the
 * `features/session` module, which itself imports the client).
 */
export const SESSION_QUERY_KEY = ['session', 'me'] as const
