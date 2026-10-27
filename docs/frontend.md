# Frontend

The browser UI: a Vite, React and TypeScript app in `frontend/`. Phase 6 built the shell
only: sign-in, a protected Home page, and the router and API wrapper that later pages
plug into.

## Where it lives

- `frontend/src/main.tsx` - mounts React, the TanStack Query client and the router.
- `frontend/src/router.tsx` - the routes and `ProtectedRoute`, the wrapper that makes a
  route require a session.
- `frontend/src/api.ts` - `api()`, a `fetch` wrapper, and `meQuery`, the session query.
- `frontend/src/pages/SignIn.tsx` and `frontend/src/pages/Home.tsx` - the two pages.
- `frontend/vite.config.ts` - the dev server and the `/api` proxy.

The frontend holds no state of its own about who is signed in. The session is the
`session` cookie set by the backend (see [auth.md](auth.md)), and the frontend asks
`GET /api/auth/me` whether it is valid.

## Routes

| Path | Element | Requires session |
| --- | --- | --- |
| `/sign-in` | `SignIn` | no |
| `/` | `Home` | yes |

Every later page is a child of the `ProtectedRoute` element in `router.tsx`.

## Contracts

- `api(path, init)` always sends `credentials: "include"`. A non-2xx response throws
  `ApiError` with the backend's `detail` as its message. A 204 returns `undefined`.
- A 401 from any call, other than on `/sign-in` itself, does a full page navigation to
  `/sign-in`. This is the single place the app handles an expired session.
- `meQuery` is the cache key `["me"]`. It has `retry: false`, because a 401 is an answer
  (signed out), not a transient failure.
- Sign-out calls `POST /api/auth/logout`, removes the `["me"]` cache entry and navigates
  to `/sign-in`. Removing the cache entry stops a Back button press from showing the
  old user.

## Sign-in is a plain link, not a fetch

"Continue with Google" is an `<a href="/api/auth/google/login">`. The backend answers
with a redirect to Google, and Google redirects back to the backend's callback, which
sets the cookie and redirects to the frontend origin. A `fetch` cannot follow that chain
into a browser session, so the button must be a navigation.

## Dev proxy

Vite proxies `/api` to `http://localhost:8000`, so the browser sees one origin
(`localhost:5173`) and the cookies are same-origin. Nothing in the frontend hard-codes
the backend address. Production serving (phase 16) will put the built files behind the
backend instead, and the relative `/api` paths keep working unchanged.

The Google redirect URI is `http://localhost:8000/...`, which the browser visits
directly. Because of that, the browser must reach the backend on port 8000 on the same
`localhost` as the frontend. On a remote development machine this is done with SSH
port forwarding, see [AGENTS.md](../AGENTS.md).

## Constraints

- Tailwind is loaded through the Vite plugin, with a single `@import "tailwindcss"` in
  `src/index.css`. There is no Tailwind config file.
- `npm run build` runs `tsc --noEmit` and then `vite build`. The type check is the only
  linting for now.
- The frontend is not a Compose service. It runs on the host with `npm run dev` during
  development.
