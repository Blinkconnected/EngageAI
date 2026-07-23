# Frontend Architecture

## Stack

Vite + React 19 + TypeScript, Material UI (MUI) v9, Redux Toolkit,
React Query (`@tanstack/react-query`), React Router v7, Axios.

## Structure

```
frontend/src/
  app/            Composition root: Redux store, typed hooks, React Query
                  client, theme provider, route table (AppProviders,
                  AppRoutes, AppThemeProvider).
  theme/          MUI theme + emotion cache (LTR/RTL) factory functions.
  features/       Feature-sliced modules; each owns its Redux slice, API
                  hooks, and components (e.g. `features/auth`, `features/ui`).
  shared/api/     Axios instance with auth header + refresh-token
                  interceptor, shared across features.
  pages/          Route-level page components with no feature-specific
                  state of their own.
  test/           Vitest setup (jest-dom matchers).
```

## Branding

Blink Engage adopts the Blink Connected brand identity:

- **Colors**: primary `#8CC63F` (brand green, dark variant `#6BA82D`) on a
  warm near-black `#171412`; light-mode background `#F2F2F0`; divider
  `#E4E3E1`.
- **Typography**: "Baloo 2" for headings (h1–h6), "Nunito Sans" for body
  text and UI chrome — loaded via Google Fonts in `index.html`.
- **Shape**: 12px base border radius, pill-shaped (`border-radius: 999px`)
  buttons and chips, soft low-opacity shadows instead of MUI's default
  heavy elevation, a subtle brand-green glow on primary button hover.

Theme construction lives in `theme/theme.ts` (`createAppTheme(mode,
direction)`) and `theme/emotionCache.ts` (RTL-aware Emotion cache using
`stylis-plugin-rtl`).

## State management

- **Redux Toolkit** (`app/store.ts`) owns cross-cutting client state:
  `auth` (tokens + current user, persisted to `sessionStorage`/
  `localStorage`) and `ui` (theme mode + text direction, persisted to
  `localStorage`, defaulting to the OS `prefers-color-scheme`).
- **React Query** owns all server state (nothing server-derived is
  duplicated into Redux). Mutations such as login dispatch into the `auth`
  slice on success.

## Authentication flow

- `shared/api/client.ts` attaches the current access token to every
  request and, on a `401`, transparently calls `/auth/refresh` once
  (de-duplicated via a shared in-flight promise) before retrying the
  original request. A failed refresh logs the user out.
- `features/auth/ProtectedRoute.tsx` gates authenticated routes and
  redirects to `/login`, preserving the original destination.

## RTL / i18n readiness

Direction (`ltr`/`rtl`) is a first-class piece of `ui` state. Toggling it
flips `document.documentElement[dir]`, swaps the Emotion cache (so MUI's
`sx`/`styled` output gets RTL-flipped via `stylis-plugin-rtl`), and MUI's
`theme.direction` is kept in sync so component internals (e.g. drawer
anchoring) also flip.

## Testing & quality gates

- `vitest` + `@testing-library/react` (jsdom environment) for unit and
  component tests.
- `eslint` (flat config: `typescript-eslint`, `react-hooks`,
  `react-refresh`, `eslint-config-prettier`), `prettier`, and `tsc --noEmit`
  must all pass before a milestone is committed.
