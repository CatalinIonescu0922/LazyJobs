# Authentication

Google sign-in over OpenID Connect. After login the app never talks to Google again:
the session is our own JWT cookie. Google access tokens and refresh tokens are used
once during the callback and discarded.

## Where it lives

- `backend/app/oauth.py` — provider registry, PKCE, the authorization URL, the
  code exchange, userinfo. Nothing here writes to the database.
- `backend/app/session.py` — session JWT, cookie flags, `current_user`.
- `backend/app/routers/auth.py` — HTTP routes and find-or-create of `users` /
  `identities` / `profiles`.
- Data: `users` and `identities` in `backend/app/models.py`.

## Endpoints

| Method and path | Result |
| --- | --- |
| `GET /api/auth/{provider}/login` | 302 to the provider. Sets a five-minute `oauth_flow` cookie holding `state` and the PKCE verifier. |
| `GET /api/auth/{provider}/callback` | Verifies `state` first. Exchanges the code, upserts the user, sets the `session` cookie, clears `oauth_flow`, 302 to `FRONTEND_ORIGIN`. |
| `GET /api/auth/me` | `{id, email, name, avatar_url}` or 401. |
| `POST /api/auth/logout` | 204 and clears `session`. |

v1 `provider` is `google`. Unknown names return 404. Empty `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET` returns 503.

Other routes depend on `current_user` from `session.py`. It reads the `session`
cookie only; a valid `oauth_flow` token is not accepted as a session.

## Cookies

Both cookies are httpOnly, SameSite=Lax, path `/`. `Secure` is off because local
development is `http://localhost`.

`oauth_flow` is a JWT (`purpose=oauth`) so the backend stays stateless: there is no
server-side session store for the round-trip to Google. Lax is required; a Strict
cookie would be omitted when Google redirects back to `/callback`.

`session` is a JWT (`purpose=session`, `sub` is the user id) signed with
`JWT_SECRET`, lasting `JWT_TTL_HOURS` (default two weeks).

## Account linking

Look up `(provider, subject)` first. `subject` is Google's `sub`; it is the stable
id, so a later email change at Google does not create a second user.

If that identity is new:

- No user with that email → create `User`, `Identity`, and an empty `Profile` in
  one transaction. Email is stored lowercased.
- User with that email exists **and** the provider reports `email_verified` → attach
  a new `Identity` to that user.
- User with that email exists and the email is **not** verified → 400. Linking on
  an unverified email is an account-takeover path.

A second sign-in with the same Google account hits the identity row and reuses the
same `users` row.

## Adding a second provider

1. Add client id, secret, and redirect URI to `config.py` / `.env`.
2. Add an entry to `PROVIDERS` in `oauth.py` with that provider's auth, token, and
  userinfo URLs.
3. `identity_from` currently maps OpenID Connect claims (`sub`, `email`,
  `email_verified`, `name`, `picture`). A provider with different claim names needs
  its own mapping; do not change the Google mapping to guess at both.

Google Cloud: OAuth client type Web application, redirect URI
`http://localhost:8000/api/auth/google/callback`. In testing mode only listed test
users can sign in.
