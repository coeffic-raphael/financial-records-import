# Frontend

React interface for the financial records import workflow. See the
[project README](../README.md) for the whole picture; this file covers the
frontend only.

## Run

```bash
npm install
cp .env.example .env
npm run dev
```

The backend must be running on the port named by `VITE_API_BASE_URL`. See
[`../backend`](../backend).

## Checks

```bash
npm run build     # tsc, then the production build
npx vitest run    # API client and session store
```

## Shape

```
src/
  lib/        apiClient (the ONLY place that calls fetch), types, query client
  stores/     the session, and nothing else
  hooks/      one file for every server read and write
  components/ presentational pieces
  pages/      one container per screen
```

Two rules explain most of the structure:

- **Server state belongs to TanStack Query, session state to Zustand.** No
  server data passes through the store: duplicating it there would create two
  sources of truth and reintroduce by hand the invalidation Query already does.
- **A component either fetches or renders, never both.** The container owns the
  hook, the presentational one takes props.

## Two things worth knowing before changing this

**Every refresh is shared.** The API revokes a whole token family when a revoked
refresh token comes back, because reuse means it was copied. Two rotations
started at once therefore look like theft and end the session. React StrictMode
makes this concrete: it invokes effects twice, so session restoration must go
through the same single in-flight promise as the retry path.

**Amounts are strings and are never recomputed.** A JSON number would be parsed
into a float and lose precision. The server is the only arithmetic authority;
this code displays what it is given.
