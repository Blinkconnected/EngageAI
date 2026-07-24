// Mirrors shared/api/client.ts's fallback so MSW intercepts the same
// absolute URLs Axios actually requests in a jsdom test environment
// (import.meta.env.VITE_API_BASE_URL is unset under Vitest).
export const API_BASE_URL = 'http://localhost:8000/api/v1'
