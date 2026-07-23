# Blink Engage — Frontend

React + TypeScript SPA for the Blink Engage agent workspace. See
[`docs/architecture/frontend.md`](../docs/architecture/frontend.md) for the
architecture overview.

## Development

```bash
npm install
npm run dev
```

## Scripts

| Script                 | Purpose                              |
| ---------------------- | ------------------------------------ |
| `npm run dev`          | Start the Vite dev server            |
| `npm run build`        | Type-check and build for production  |
| `npm run preview`      | Preview the production build locally |
| `npm run lint`         | ESLint                               |
| `npm run format`       | Prettier — write                     |
| `npm run format:check` | Prettier — check only                |
| `npm run typecheck`    | `tsc --noEmit`                       |
| `npm run test`         | Vitest (single run)                  |
| `npm run test:watch`   | Vitest (watch mode)                  |
