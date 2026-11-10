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

After authentication, `ProtectedRoute` loads the profile before rendering a protected
page. Users without an uploaded CV are sent to `/profile` to complete initial setup;
users whose profile has `has_cv` set continue to `/` as the main page. The profile page
remains available for later corrections.

The main page is the job results view. The first CV upload automatically discovers and
refreshes the user's sources, then opens the dashboard with roles filtered to hybrid and
onsite work in the profile city. The dashboard provides manual keyword, location, work
mode, and posted-date filters over cached results. `/sources` remains an advanced
source-management screen rather than part of the normal first-login workflow. The
dashboard reads cached jobs immediately; crawling happens automatically after CV upload,
so a slow or unavailable board cannot block the main page.

Job cards from Himalayas and Remote OK show a "via" credit line that links to the source,
because their terms ask for a visible link back. The list is `CREDITED_SOURCES` in
`src/pages/Home.tsx`; add a source's domain there when its terms require a credit.

## Companies screen

`/companies` (`src/pages/Companies.tsx`, reached from the header nav) shows the `companies` list the
backend builds, served by `GET /api/companies` (contract and meaning in `docs/sources.md`, Company
discovery). A summary strip gives the counts, "Read directly" has a card per employer feed (provider
badge, jobs, "updated 2 hours ago", a status chip with its reason when the feed is not active, and a
link to the careers page), and "Companies that hire in your country" is a card grid with four filter
tabs (all, with a feed, no readable feed, not checked yet) and a name search.

- The summary strip and the feed cards come from one unfiltered query (status all, no search, first
  page), so they do not move while the list below reloads. It is the same cache entry as the first
  page of the All tab.
- Paging is one query per page of 60 (`useQueries`, offsets 0, 60, 120 and so on), concatenated;
  "Show more" appears while fewer than `total_matching` companies are shown. A failed page shows a
  retry button in place of "Show more", so pages never load out of order. The list is keyed by
  `status:search`, so changing the tab or the applied search starts again at the first page.
- The search is debounced by 300 ms and has no button.
- A company logo is the image at `logo_url`. When that is empty, or the image fails to load, a rounded
  square with the first two initials is shown, its colour taken from a hash of the name so it is stable.
- The API sends UTC timestamps without a timezone suffix, so `ago()` appends "Z" before building a
  `Date`; it is the only place timestamps are parsed.
- Not checked in a browser: the page sits behind Google sign-in and was only type-checked, built and
  reviewed against the API contract.

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
