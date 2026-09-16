# Decision log

Why this codebase looks the way it does, and the engineering concept behind each choice.

Entries are appended as decisions are made, not written up afterwards. Entries 1 to 8 are
the exception: they were backfilled from phases 1 to 3, which were already built when this
file started. Everything from entry 9 onward describes the GCP rework and is being written
alongside the work.

Most entries carry an expiry condition. A decision with an expiry condition is a better
decision than one that pretends to be permanent: it records the context it depends on, so
when the context changes the decision can be retired deliberately instead of discovered as
an outage. Entry 20 is the one decision here that has already expired.

Phase numbers refer to the twenty-one phases in [BUILD.md](BUILD.md).

---

## 1. Store no passwords, only external identities

**Phase**: 2, data model for identity.

**The problem**: The app needs to know who is using it, and every account system starts
with the question of what proves that. A password column is the default answer, and it
drags in hashing, reset flows, rate limiting, breach handling and a permanent obligation to
keep a secret that users have reused elsewhere.

**What we did**: `users` in `backend/app/models.py` holds `email`, `name`, `avatar_url`,
`created_at` and `last_login_at`, and nothing else. Proof of identity lives in
`identities`: one row per external login, carrying `provider` and `subject`, unique on
`(provider, subject)` under the constraint `uq_identity_provider_subject`. `subject` is
the provider's stable user id, so changing the email at Google does not create a second
account. Adding GitHub or LinkedIn sign-in later is a new `identities` row shape, not a
change to `users`.

**Why not the obvious alternative**: Email and password is the most understood pattern in
the industry and needs no third party, which matters if you dislike depending on Google
being reachable. Here it buys nothing: the only user is the owner, who has a Google
account, and the cost is a credential store with real consequences if it leaks.

**The concept**: This is the separation of authentication from identity. Authentication is
the act of proving that the person at the keyboard is who they claim; identity is the
account record the application owns and attaches its data to. Federated identity means
delegating the first to an identity provider (Google) while the application, the relying
party, keeps only the second and a pointer to the provider's subject. The consequence
worth internalising is that credential storage is a liability you are allowed to decline:
you cannot leak a password hash you never stored. Every enterprise SSO integration, every
Auth0, Okta or Cognito setup, and every "log in with your work account" button is this
same shape, and they all end up with a table that looks like `identities`.

**Expires when**: something needs an account that no external provider can vouch for, for
example a CLI token or a user with no Google or GitHub login. That is when a credential
table becomes necessary, and it should be magic links or WebAuthn before passwords.

**See it yourself**: `sqlite3 backend/cv_applier.db ".schema users" ".schema identities"`.
There is no password column, and the unique constraint is printed by name. `rg -i password
backend/app` returns nothing.

---

## 2. Keep `state` and the PKCE verifier in a signed cookie, not in memory

**Phase**: 3, Google sign-in.

**The problem**: The OAuth authorization code flow leaves and comes back. Between the
redirect to Google and the callback, the backend has to remember the `state` value it
generated and the PKCE verifier it will need to redeem the code. Something has to hold
that for the length of a human sign-in.

**What we did**: `sign_flow` in `backend/app/oauth.py` puts `provider`, `state` and
`verifier` into a JWT with `purpose=oauth` and a five-minute expiry (`OAUTH_TTL`), and
`set_flow_cookie` sends it as the httpOnly `oauth_flow` cookie. The callback in
`backend/app/routers/auth.py` reads it back with `read_flow_cookie`, which rejects any
token whose `purpose` is not `oauth`, and compares the stored `state` against the query
parameter before doing anything else. No dictionary, no Redis, no server-side session
table.

**Why not the obvious alternative**: A module-level dict keyed by `state` is four lines and
works perfectly on one process. It is the standard tutorial approach and is defensible for
a single-process app that never restarts mid-sign-in. It fails the moment there is more
than one process, and it loses every in-flight login on every deploy.

**The concept**: A stateless service keeps no per-client state in its own memory between
requests; anything that must persist goes either to the client, integrity-protected, or to
a shared store. This is what makes horizontal scaling ordinary: any instance can serve any
request, so you add instances instead of buying a bigger one, and you do not need sticky
sessions pinning a user to the one machine that remembers them. The twelve-factor
formulation is that processes are stateless and share nothing, and that they are
disposable, meaning the platform can kill one at any time. Note that the signature is what
makes this safe: the cookie is client-held data the client cannot forge, which is a
different guarantee from data the client cannot read. This decision was made for
simplicity months before Cloud Run was in the plan, and Cloud Run is exactly the
environment that punishes in-memory state: instances scale from zero to three with no
request affinity, so an in-memory dict would lose most callbacks outright.

**Expires when**: the round-trip needs to carry more than a cookie can hold (about 4 KB),
or in-flight flows need to be revocable server-side. Either forces a shared store.

**See it yourself**: `backend/app/oauth.py`, lines 101 to 138: `sign_flow`,
`set_flow_cookie` and `read_flow_cookie` are the entire mechanism. Then
`rg -n "state" backend/app/routers/auth.py` to see the comparison happen before the code
exchange.

---

## 3. Use Google's tokens once and throw them away

**Phase**: 3, Google sign-in.

**The problem**: The code exchange hands back an access token, and asking for offline
access would hand back a refresh token too. Storing them is the habit, because they look
valuable and it is not obvious yet that nothing will need them.

**What we did**: `fetch_identity` in `backend/app/oauth.py` keeps `access_token` as a local
variable, uses it for exactly one `GET` to Google's userinfo endpoint, and lets it fall out
of scope. `authorization_url` never sends `access_type=offline`, so Google issues no
refresh token at all. Nothing token-shaped reaches the database. After sign-in the app runs
entirely on its own session cookie and never talks to Google again.

**Why not the obvious alternative**: Storing the refresh token is what you do if the app
will later act on the user's behalf at Google, and it is the right call for anything
touching Gmail or Calendar. This app only needs Google to answer one question once: which
account is this.

**The concept**: Minimising secret custody means holding the fewest secrets, with the
shortest lifetime, for the narrowest purpose that still does the job. The reasoning tool is
blast radius: for each secret, ask what an attacker who reads your database can do with it.
A stored Google refresh token is long-lived, works from anywhere, and grants everything in
its scopes, so a database leak becomes a compromise of the user's Google account surface
rather than just of this app. Discarding it means the worst case stays inside this app.
The same argument drives the industry preference for short-lived tokens over long-lived
ones, and for scoping tokens down before storing them, and it is the principle behind
entry 12's refusal to download a service-account key.

**Expires when**: a feature needs to act at Google after login, for example reading job
alert emails. That requires `access_type=offline`, encrypted storage for refresh tokens,
and a revocation path, and it should be a deliberate entry in this log.

**See it yourself**: `rg -n access_token backend/app` returns three lines, all inside
`fetch_identity` in `oauth.py`. There is no token column in `backend/app/models.py`.

---

## 4. Put the session in an httpOnly, SameSite=Lax cookie

**Phase**: 3, Google sign-in.

**The problem**: After the callback the browser needs something it can present on every
later request. The two real options are a cookie the browser manages or a token the
frontend stores and attaches by hand, and the choice determines what an attacker who gets
JavaScript execution on the page can steal.

**What we did**: `backend/app/session.py` signs a JWT with `purpose=session` and `sub` set
to the user id, lasting `JWT_TTL_HOURS` (two weeks by default), and sets it as the
`session` cookie with `COOKIE_KW = {"httponly": True, "samesite": "lax", "secure": False,
"path": "/"}`. `current_user` reads that cookie, rejects a token whose purpose is not
`session`, and loads the user. `oauth_flow` uses the same flags.

**Why not the obvious alternative**: Keeping the JWT in `localStorage` and sending it as an
`Authorization` header is the default in single-page-app tutorials, and it sidesteps CSRF
thinking entirely. The trade is bad here: `localStorage` is readable by any script running
on the page, so one cross-site scripting hole or one compromised npm dependency exfiltrates
a two-week session, whereas an httpOnly cookie cannot be read by script at all.

**The concept**: The three cookie flags each stop a different attack. `httpOnly` removes
the cookie from the DOM API, so script cannot read it, which downgrades an XSS bug from
session theft to actions taken while the victim is on the page. `Secure` prevents the
cookie being sent over plain HTTP, defeating a network attacker who strips TLS. `SameSite`
governs whether the cookie rides along on requests initiated by other sites, which is the
defence against cross-site request forgery, where a malicious page makes the victim's
browser perform an authenticated request. `Lax` rather than `Strict` is not laziness: a
`Strict` cookie is withheld on cross-site top-level navigations, and Google's redirect back
to `/api/auth/google/callback` is exactly that, so the `oauth_flow` cookie would be missing
and every sign-in would fail with "Invalid or expired sign-in state". `Lax` still withholds
the cookie on cross-site POSTs and subresource requests, which is where CSRF actually
lives.

**Expires when**: the app is served over HTTPS. `secure` is currently hardcoded `False`
because local development is `http://localhost`; phase 13 introduces the `COOKIE_SECURE`
environment variable, true on Cloud Run and false locally, and both cookie dictionaries
must read it.

**See it yourself**: `rg -n "COOKIE_KW|OAUTH_COOKIE_KW" backend/app` shows both flag sets
and the comments explaining them: `session.py:14` and `oauth.py:18`.

---

## 5. Link accounts only on a provider-verified email

**Phase**: 3, Google sign-in.

**The problem**: A sign-in can arrive with a new `(provider, subject)` pair for an email
address that already has a user. Refusing to link is hostile, since the owner would end up
with two accounts for the same address. Linking on the email alone trusts a string supplied
by a third party.

**What we did**: `find_or_create_user` in `backend/app/routers/auth.py` looks up
`(provider, subject)` first. If that identity is new and no user has the email, it creates
`User`, `Identity` and an empty `Profile` in one transaction with the email lowercased. If
a user with that email exists, it attaches a new `Identity` only when the provider reported
`email_verified`; otherwise it returns 400. `Provider.identity_from` in `oauth.py` reads
that claim as `bool(claims.get("email_verified"))`, so a missing claim counts as
unverified.

**Why not the obvious alternative**: Matching on email and linking silently is what most
small apps do, and with Google alone as the provider it is close to safe, because Google
does verify its addresses. It stops being safe the moment a second provider is added, and
the failure mode is an account takeover rather than a cosmetic bug.

**The concept**: A trust boundary is the line across which data stops being yours and
starts being an input you must validate. Claims in an ID token are inside the boundary for
integrity, since the signature proves the provider sent them, but the meaning of a claim is
still the provider's policy, not a fact. Pre-registration account takeover is the concrete
attack: an attacker signs up at a provider that does not verify ownership using the
victim's address, the application links on the email, and when the victim later signs in
through their real provider they arrive inside an account the attacker already controls.
This class of bug is common enough to be a standard bug-bounty finding, and it is why the
defaulting detail above matters: treating an absent `email_verified` as false is
fail-closed, which is the correct direction for any security check.

**Expires when**: a provider is added whose `email_verified` cannot be trusted, or which
omits it. Linking then needs the application to verify the address itself, by emailing a
confirmation link, rather than believing a claim.

**See it yourself**: `backend/app/routers/auth.py`, lines 118 to 123, the `elif not
ext.email_verified` branch and the comment above it. The claim's default is
`oauth.py:50`.

---

## 6. Make `jobs` a shared cache keyed on `(source, external_id)`

**Phase**: 1, when `models.py` was first written.

**The problem**: Postings are fetched from the outside world repeatedly, by a nightly run
and eventually by more than one user on the same day. Every fetch re-encounters jobs
already stored, and the table has to absorb that without growing duplicates or needing the
fetcher to check first.

**What we did**: `Job` in `backend/app/models.py` has a surrogate integer `id` as its
primary key and a `UniqueConstraint("source", "external_id", name="uq_job_source_id")`
alongside it, plus `fetched_at` to record freshness. The table is not scoped to a user, so
the same row serves everyone. `Application` follows the same pattern with
`uq_application_user_job`, which is what stops a user holding two applications for one job.

**Why not the obvious alternative**: Per-user job rows would remove the need to think about
sharing at all, and any cache-invalidation question with it. It also multiplies storage by
the number of users, refetches the same page once per user, and makes the politeness budget
in the eJobs adapter, one request per second, harder to respect.

**The concept**: A natural key is a value from the problem domain that identifies a row:
here, the pair of which board it came from and that board's own id for the posting. A
surrogate key is an identifier the database invents, with no meaning outside it. Keeping
both is the standard compromise: the surrogate is stable, compact and safe to use in
foreign keys such as `applications.job_id`, while the unique constraint on the natural key
enforces that no two rows claim the same real-world posting. That constraint is also what
makes the insert idempotent, meaning running it twice has the same effect as running it
once, via an upsert (`INSERT ... ON CONFLICT (source, external_id) DO UPDATE` in
PostgreSQL). Idempotency stops being optional as soon as work is triggered by something
that retries: Cloud Scheduler, message queues and webhook senders all deliver at least
once, never exactly once, which is why Stripe's API takes an `Idempotency-Key` header and
why every well-built consumer is written to tolerate a duplicate.

**Expires when**: a source stops exposing a stable id per posting, or the table grows
enough that expired rows need evicting rather than accumulating.

**See it yourself**: `sqlite3 backend/cv_applier.db ".schema jobs"` prints `CONSTRAINT
uq_job_source_id UNIQUE (source, external_id)` next to the integer primary key.

---

## 7. Give job sources one small Protocol, and nothing else

**Phase**: design for phase 7, eJobs source. Not built yet.

**The problem**: There are four candidate sources: eJobs, the ATS boards, BestJobs and
JSearch. Each speaks a different protocol, returns different field names and needs
different politeness handling. Everything downstream, matching and the API, needs one
shape.

**What we did**: PLAN.md's job sources section fixes a `Posting` dataclass and a
`JobSource` Protocol with a `name` attribute and one method,
`fetch(self, profile: Profile, limit: int) -> list[Posting]`. Adapters go in
`backend/app/sources/` with a registry, so adding a source is a file plus a registry entry.
The directory exists but is empty; no adapter is written yet.

**Why not the obvious alternative**: A base class with shared HTTP handling, retries and
rate limiting looks like the tidier design, and it is the right answer once three adapters
demonstrably need the same behaviour. Written first, it guesses at that behaviour from one
example, and every later adapter either inherits machinery it does not want or bends its
own logic to fit the parent.

**The concept**: An interface earns its place where variation genuinely exists, and its
value is proportional to the number of real implementations behind it. Two are committed
for v1 and two more are planned, which is what separates this from speculative
abstraction: a layer introduced for a single implementation on the argument that another
might appear. The repository's own rule bans that outright, and entry 14 is the case where
it was declined. The mechanism chosen matters too: `typing.Protocol` is structural typing,
so an adapter satisfies it by having the right shape, with no base class to inherit and no
registration step, and the type checker verifies conformance rather than the runtime. The
deeper pattern is dependency inversion, where the matching engine depends on `Posting`,
which it owns, rather than on eJobs' HTML, which it does not.

**Expires when**: the second and third adapters are written and turn out to share real
behaviour, such as pagination or the seen-URL set. That shared part becomes a helper
function the adapters call, not a method on the Protocol, which stays one method wide.

**See it yourself**: the job sources section of [PLAN.md](PLAN.md) holds the contract
today; `ls backend/app/sources` shows it is empty. After phase 7,
`rg -n "class JobSource" backend/app/sources/base.py`.

---

## 8. Score matches deterministically, with no LLM call per posting

**Phase**: design for phase 9, matching. Not built yet.

**The problem**: Ranking thousands of postings against a profile is the obvious place to
reach for a language model, since judging fit is fuzzy work. It is also the highest-volume
operation in the app, so whatever goes there gets multiplied by every posting on every run.

**What we did**: Matching, as specified in PLAN.md, is hard filters on location, remote and
expiry, then a score from 0 to 100 built from title overlap, skills overlap and a recency
boost, plus a readable reason string per match such as "matches 7 of your skills". Romanian
diacritics are normalised and a small synonym map covers the Dezvoltator and Developer
duplication. No model is called. The model is used twice per user instead: once to extract
the profile from the CV, once to draft a cover letter. `backend/app/matching.py` does not
exist yet.

**Why not the obvious alternative**: Sending each posting and the profile to the model
would produce better rankings on the hard cases, particularly for roles whose titles do not
resemble the candidate's. It is genuinely better at the judgement. It costs money per
posting, takes seconds per call, and returns a different answer for the same inputs
tomorrow.

**The concept**: The design rule is to put the expensive, nondeterministic component only
where judgement is actually required, and to keep everything else in code that returns the
same answer every time. The consequences compound. Testability: a deterministic scorer can
be asserted exactly in a unit test, while an LLM-based one can only be measured
statistically against a labelled set someone has to build. Cost: at
`gemini-3.1-flash-lite` prices of $0.25 per million input tokens and $1.50 per million
output tokens, a cover letter costs about $0.005, which is negligible once per application
and ruinous once per posting per night. Latency: a filter over thousands of rows in
SQL-and-Python is instant, and an API round trip is not. Explainability: the reason string
is derivable because the score is a formula, so the ranking is auditable rather than a
black box. This is the same reasoning by which production recommender systems use a cheap
retrieval stage over everything and an expensive model over the shortlist.

**Expires when**: the score visibly ranks the wrong jobs first and adjusting the weights
stops helping. The next move is an LLM re-rank of the top twenty, not of all of them, which
keeps the cost bounded by a constant.

**See it yourself**: the matching section of [PLAN.md](PLAN.md). After phase 9,
`rg -n "def score" backend/app/matching.py`.

---

## 9. Use Vertex AI, not the AI Studio Gemini API

**Phase**: 4, GCP project and guardrails. Not built yet.

**The problem**: The project runs on a Google Cloud free trial: $300 of credit, valid 90
days from billing-account creation, unused credit expiring. Gemini is reachable through two
different Google products, and the naive path, an API key from AI Studio, is the one every
quickstart shows.

**What we did**: All model calls go through Vertex AI, which the $300 credit can pay for.
The credit cannot pay for the Gemini API in Google AI Studio. Same models, two products,
two billing systems. The SDK is `google-genai`, used as
`from google import genai; client = genai.Client(vertexai=True, project=..., location=...)`;
the older `vertexai.generative_models` module was deprecated on 2025-06-24 and removed on
2026-06-24, so any example using it is stale. The model is `gemini-3.1-flash-lite`, released
2026-05-07 and supported until at least 2027-05-07. `gemini-2.5-flash` is not used because
it retires on 2026-10-20. `VERTEX_LOCATION` is `global`, since non-global endpoints cost
10% more. The `openai` dependency and the `OPENAI_API_KEY`, `OPENAI_BASE_URL` and
`OPENAI_MODEL` variables are removed. One naming warning: Google's docs now brand Vertex AI
as "Gemini Enterprise Agent Platform", so the console will disagree with the product name
everyone uses.

**Why not the obvious alternative**: AI Studio is easier. An API key in an environment
variable, no project, no service account, no IAM. If there were no credit to spend it
would be a reasonable choice, and its own free tier might even cover this volume. Here it
would mean paying out of pocket while $300 sat unused, and doing the cloud learning the
project exists for through a side door.

**The concept**: The same capability is frequently sold as two products with different
billing, quotas, terms and support commitments, and the choice between them is an
architectural decision made at procurement time rather than a detail of configuration.
Credits, free tiers and trials come with terms that constrain design, and those terms have
to be read before the design, not after: this trial also blocks GPUs and TPUs, Cloud
Marketplace, quota-increase requests, Windows Server VMs and managed third-party generative
models, caps Compute Engine at eight concurrent cores, and excludes SLAs and support. The
second half of the concept is model lifecycle: hosted models carry retirement dates, so the
model id is a dated dependency, and picking one with a year of support left is the
difference between a scheduled upgrade and an outage. The pattern recurs everywhere, in
AWS Bedrock against a vendor's own API, in Azure OpenAI against OpenAI, and in region-
specific free tiers such as Cloud Storage's, which is US-only and therefore does not apply
to this project.

**Expires when**: the 90-day credit window closes and the account becomes pay-as-you-go, at
which point the two products should be priced against each other again. Also on any
announced retirement date for `gemini-3.1-flash-lite`.

**See it yourself**: not runnable yet. Phase 4 ends with one cheap call that proves the
route works:

```
python -c "
from google import genai
c = genai.Client(vertexai=True, project='PROJECT_ID', location='global')
print(c.models.generate_content(model='gemini-3.1-flash-lite', contents='ping').text)"
```

---

## 10. Run PostgreSQL everywhere and drop SQLite entirely

**Phase**: 5, local cloud-parity stack. Not built yet.

**The problem**: The backend was built on SQLite because it needs no server, and production
was always going to be a managed database. That leaves the app developed against one engine
and deployed against another, with SQLAlchemy in between making the difference look like a
connection string.

**What we did**: PostgreSQL 16 in both places. Locally a container in `docker-compose.yml`
with `DATABASE_URL=postgresql+psycopg://cv:cv@db:5432/cv_applier`; in production Cloud SQL
instance `cv-applier-db`, `db-f1-micro`, 10 GB SSD, single zone, no HA, reached over the
built-in Cloud SQL Auth Proxy on a unix socket at `/cloudsql/INSTANCE_CONNECTION_NAME`,
with an empty authorized-network list and no VPC connector. SQLite is removed, not kept as
an option, which
also removes the `check_same_thread` special case in `backend/app/db.py`. The driver added
is `psycopg[binary]`. This is the only meaningful running cost in the project, about $10 a
month, and it has no free tier.

**Why not the obvious alternative**: Keeping SQLite locally is free, starts instantly, and
needs no Docker, which is a real advantage on a laptop and the reason the split existed.
Plenty of projects run that way successfully, especially when the ORM covers all database
access and the schema is simple.

**The concept**: Dev/prod parity is the tenth factor of the twelve-factor app: keep
development, staging and production as similar as possible, and specifically resist
substituting a lighter backing service locally, because the divergence surfaces as bugs
that only reproduce where you cannot debug them. The failures here are concrete rather than
theoretical. SQLite has permissive typing, so inserting the string `abc` into an `INTEGER`
column stores it as text and SQLite reports its type as `text`, while PostgreSQL rejects
the insert; a bug caught by the database in production would pass silently in development.
SQLite serialises writers with database-level locking, whereas PostgreSQL uses MVCC and
row-level locks, so the nightly refresh writing while a request reads behaves differently
under the two, and neither engine's concurrency bugs predict the other's: SQLite raises
"database is locked" under concurrent writes that PostgreSQL absorbs, and PostgreSQL
raises deadlock and serialisation failures that SQLite never produces, so testing against
one leaves the other's failure mode unexercised. JSON columns, of which this schema has
several on `profiles` and
`jobs`, are text in SQLite and a real indexable type in PostgreSQL, with different
comparison semantics. The general lesson is that an ORM abstracts the query syntax, not the
database's behaviour; the abstraction is leaky exactly where correctness lives.

**Expires when**: the 0.6 GB of memory in `db-f1-micro` becomes the bottleneck, which it
will under any serious workload, or the $10 a month stops being worth parity.

**See it yourself**: today `rg -n sqlite backend/app/db.py backend/app/config.py` shows the
two places it is wired in. The typing difference is one command:
`sqlite3 :memory: "create table t (n integer); insert into t values ('abc'); select n,
typeof(n) from t;"` prints `abc|text`. After phase 5:
`docker compose exec db psql -U cv -d cv_applier -c "\dt"`.

---

## 11. Read configuration only from the environment

**Phase**: 5 locally, 12 in production. Not built yet.

**The problem**: Production needs real secrets: the Google client secret, the JWT secret,
the database password. Secret Manager is the right place to keep them on GCP, and the
documented way to use it is to call its API from the application with the client library.

**What we did**: The application reads configuration exclusively from environment
variables, through the `Settings` class in `backend/app/config.py`, which is a pydantic
`BaseSettings` with `env_file=".env"` for local development. In production the secrets live
in Secret Manager and Cloud Run injects them as environment variables at instance start.
The application never imports or calls a Secret Manager client. The new variables are
`DATABASE_URL`, `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET`, `STORAGE_EMULATOR_HOST` (local only),
`VERTEX_LOCATION`, `VERTEX_MODEL` and `COOKIE_SECURE`.

**Why not the obvious alternative**: Calling Secret Manager from the app gives you rotation
without a redeploy and an audit trail of every access, which is the correct design for a
system with many secrets and a compliance requirement. It also puts a GCP dependency in the
startup path of every process, needs credentials before it can fetch credentials, and has
to be mocked in every test.

**The concept**: Twelve-factor config says configuration is everything that varies between
deployments and belongs in the environment, strictly separated from code, so the same build
artifact runs in every environment. The structural point is who does the work: the platform
injects the dependency rather than the application fetching it, which is dependency
injection applied at the deployment boundary instead of service location inside the
process. What this buys is portability and testability in the same stroke: the code runs on
a laptop with a `.env` file, on Cloud Run with injected secrets, and on any other host that
can set environment variables, with no GCP-specific branch and nothing to stub. It also
sidesteps the free-tier limit of 10,000 secret access operations per month, because Cloud
Run reads each secret once per instance start rather than once per request. The
counterweight to know is that environment variables are visible to anything that can read
the process environment and are easy to leak into logs and crash reports, so this is a
trade rather than a free win.

**Expires when**: a secret has to be rotated without a redeploy, or secrets become
per-tenant rather than per-deployment. Both force a runtime fetch with a cache.

**See it yourself**: `backend/app/config.py` is the whole configuration surface; every
setting is a field with a default. `rg -ni "secretmanager|secret_manager" backend/` returns
nothing, and should still return nothing after phase 12.

---

## 12. Authenticate with Application Default Credentials, and never download a key

**Phase**: 4, GCP project and guardrails. Not built yet.

**The problem**: Code calling Vertex AI and Cloud Storage has to prove which identity it
is. The path of least resistance, widely shown in tutorials, is to create a service
account, download its JSON key and point `GOOGLE_APPLICATION_CREDENTIALS` at the file.

**What we did**: Application Default Credentials everywhere. Locally, `gcloud auth
application-default login` writes user credentials that the client libraries discover
automatically. On Cloud Run, the service runs as the attached service account
`cv-applier-run@PROJECT_ID.iam.gserviceaccount.com` and the libraries obtain short-lived
tokens from the metadata server. No service-account JSON key is ever created or downloaded,
so `GOOGLE_APPLICATION_CREDENTIALS` is never set and the application contains no
credential-loading code at all.

**Why not the obvious alternative**: A downloaded key is simple, works from anywhere and
requires no understanding of the platform's identity model, which is precisely why it is
so common. If a workload genuinely runs somewhere with no identity provider at all, it can
be the only option, but that is not this project.

**The concept**: Keyless authentication means the workload never holds a long-lived
credential; it holds an identity that the platform attaches, and exchanges it for tokens
that expire in minutes and are rotated for it. Workload identity is the general name for
this: the compute resource itself is the principal, so authorisation is granted to "the
Cloud Run service" rather than to a file somebody has to protect. The reason this matters
more than most hardening advice is empirical: leaked long-lived service-account keys,
committed to repositories, pasted into CI logs, left in laptop backups or embedded in
container images, are among the most common causes of real cloud breaches, and a key has no
expiry, works from any IP address and is indistinguishable from legitimate use. The
important shift in thinking is that the fix is not guarding the key better with a vault, a
scanner and a rotation policy, but never having one, which removes the entire failure mode
instead of managing it. The same pattern is everywhere: IAM roles for EC2, IRSA on EKS,
managed identities on Azure, and OIDC federation from GitHub Actions, all of which exist to
delete the same secret.

**Expires when**: something outside GCP needs to act as this service account, for example a
CI system Cloud Build cannot cover. The answer then is Workload Identity Federation, which
exchanges an external OIDC token for a Google token, not a downloaded key.

**See it yourself**: not runnable yet. After phase 4, `gcloud auth application-default
print-access-token` prints a token that expires within the hour, and
`rg -n GOOGLE_APPLICATION_CREDENTIALS backend/` returns nothing, as it does today.

---

## 13. Run as a dedicated service account with four narrow roles

**Phase**: 4, GCP project and guardrails. Not built yet.

**The problem**: Cloud Run will run as some identity. The default is the project's default
compute service account, which already exists and needs no setup, and which every service
in the project shares.

**What we did**: A dedicated runtime identity,
`cv-applier-run@PROJECT_ID.iam.gserviceaccount.com`, with exactly four roles:
`roles/cloudsql.client` to connect through the Auth Proxy, `roles/aiplatform.user` to call
Vertex AI, `roles/secretmanager.secretAccessor` so Cloud Run can inject the secrets, and
`roles/storage.objectAdmin` granted on the `cv-applier-uploads-PROJECT_ID` bucket only,
not project-wide. Three project-level bindings and one resource-level binding, and nothing
else.

**Why not the obvious alternative**: The default service account is one fewer thing to
create, and for a single-service personal project the practical risk is low. The cost is
that it comes with broad project-level editor permissions, is shared by every workload in
the project, and teaches the wrong instinct at exactly the point where the habit is cheap
to form.

**The concept**: Least privilege means an identity holds only the permissions its job
requires, granted on the narrowest resource that works, and it is enforced by the grants
rather than by the code's good behaviour. Its value is measured in blast radius: if this
service is compromised, the attacker inherits precisely these four capabilities, so they
can read and write one bucket and call one API, but cannot delete the database, create
resources or read other projects' data. Default service accounts are over-permissioned by
construction, because a default has to work for every plausible workload, and breadth is
the only way to achieve that. The resource-level grant on the bucket is the part worth
copying: most IAM systems allow binding at several scopes, and choosing the tightest one is
usually a single flag rather than a design effort. One identity per workload is the
companion rule, since shared identities make the blast radius the union of everything that
uses them and make audit logs impossible to attribute.

**Expires when**: a new integration needs a capability these four roles do not cover. The
response is to add a fifth narrow role, not to widen an existing one or reach for
`roles/editor`.

**See it yourself**: not runnable yet. After phase 4:

```
gcloud projects get-iam-policy PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:cv-applier-run@PROJECT_ID.iam.gserviceaccount.com" \
  --format="value(bindings.role)"
gcloud storage buckets get-iam-policy gs://cv-applier-uploads-PROJECT_ID
```

The first lists three roles, the second shows the fourth.

---

## 14. Run a Cloud Storage emulator locally, not a storage abstraction

**Phase**: 5, local cloud-parity stack. Not built yet.

**The problem**: Uploaded CVs go to Cloud Storage in production. Local development needs
somewhere for them to go, and the instinctive fix is to define a storage interface with a
GCS implementation and a local-filesystem one.

**What we did**: `docker-compose.yml` runs `fsouza/fake-gcs-server` as the `gcs` service
and sets `STORAGE_EMULATOR_HOST=http://gcs:4443`. The application uses the real
`google-cloud-storage` client in both environments: one code path, a different endpoint,
and the variable is simply unset in production. Production writes to
`cv-applier-uploads-PROJECT_ID`, with uniform bucket-level access and no public access.

**Why not the obvious alternative**: A `Storage` interface with two backends is the
textbook answer and needs no Docker. It also produces two implementations where only one
ever runs in production, so the local one is the only one exercised during development and
it differs in ways that matter: no object generations, no metadata, different exceptions,
different path semantics. Every bug it hides is a bug that first appears after deploy.

**The concept**: Substitute at the boundary you do not own, not inside the code you do.
Putting the test double at the network edge, as an emulator speaking the real API, keeps
the code under test byte-identical to the code that runs in production, so the client
library, its retries, its error types and its serialisation are all covered. An interface
inside the application moves the seam inwards and leaves the real integration untested by
construction. This is also the reason the repository's rule against single-use abstractions
applies here and not in entry 7: a storage interface would have exactly one production
implementation forever, whereas the job-source Protocol has four candidate sources behind
it. The same
technique appears as LocalStack for AWS, Testcontainers for databases, WireMock for HTTP
dependencies and Google's own Firestore and Pub/Sub emulators. The honest limit is that
emulators lag the real service, and `fake-gcs-server` does not implement IAM or signed-URL
verification, so anything depending on those has to be proven against a real bucket.

**Expires when**: the app needs a Cloud Storage feature the emulator does not implement,
such as signed URLs verified by Google, lifecycle rules or IAM conditions. At that point
the test for that feature moves to a real bucket rather than a new abstraction appearing.

**See it yourself**: not runnable yet. After phase 5, `docker compose ps` lists the app
alongside `db` and `gcs`, and `rg -n STORAGE_EMULATOR_HOST backend/app` should return
nothing, because the switch lives in the environment and not in the code.

---

## 15. Treat the container image as the artifact, tagged by commit sha

**Phase**: 13, first deploy. Not built yet.

**The problem**: Deployment needs a definition of the thing being deployed. If that
definition is "whatever building main produces right now", then what is running cannot be
named, rollback has no target and two instances started minutes apart can differ.

**What we did**: One image is built per commit, pushed to Artifact Registry at
`europe-west1-docker.pkg.dev/PROJECT_ID/cv-applier/backend` and tagged with the commit sha.
That exact image is what Cloud Run is pointed at, and promoting a change means deploying an
already-built image rather than rebuilding it. Phase 15 wires this into a Cloud Build
trigger on push to main. The free Artifact Registry allowance is 0.5 GB and a slim image is
around 200 MB, so at most two tags are kept.

**Why not the obvious alternative**: `:latest` is what every Docker tutorial uses and it is
one word shorter in every command. It is a mutable pointer: two pulls at different times
return different bytes, the digest running in production is not recorded anywhere you
control, a rollback has nothing to roll back to because the previous build was overwritten,
and an instance that cold-starts after a push can be running different code from its
siblings.

**The concept**: An immutable artifact is a build output identified by its content, which
never changes after it is produced, and which is therefore the unit that moves through
environments: build once, deploy many. Combined with a reproducible build, meaning the same
source and dependencies produce the same image, this makes two questions answerable that
are otherwise guesswork: what is running, and how do I get back to what was running an hour
ago. The commit sha is doing double duty as the link from the running artifact to the source
that produced it, which is what makes an incident investigable. This is the same idea as a
Git commit hash, a lockfile pinning transitive dependencies, a Docker digest rather than a
tag, and the distinction between a Maven release and a SNAPSHOT. The general habit is to
distrust mutable identifiers anywhere in a deployment path.

**Expires when**: more than two tags need retaining, which requires a cleanup policy on the
repository and starts costing money beyond the 0.5 GB free allowance.

**See it yourself**: not runnable yet. After phase 13:

```
gcloud artifacts docker images list \
  europe-west1-docker.pkg.dev/PROJECT_ID/cv-applier/backend --include-tags
gcloud run services describe cv-applier --region=europe-west1 \
  --format="value(spec.template.spec.containers[0].image)"
```

The digest in the second output should appear in the first.

---

## 16. Deploy on Cloud Run with min-instances zero and accept cold starts

**Phase**: 13, first deploy. Not built yet.

**The problem**: This app will be idle almost all of the time, with one user who opens it
occasionally and a nightly batch run. Any deployment model that bills for uptime bills
almost entirely for waiting.

**What we did**: Cloud Run service `cv-applier` with `--min-instances=0`,
`--max-instances=3` and `--allow-unauthenticated`, since the app does its own session
cookie authentication. Idle costs nothing, and the first request after an idle period pays
a cold start. The free tier covers 2 million requests, 180,000 vCPU-seconds and 360,000
GiB-seconds per month, which this project will not approach, so the expected Cloud Run bill
is $0. The container must bind `0.0.0.0:$PORT` using the `PORT` variable Cloud Run injects;
a container hardcoded to 8000 fails to start with a health-check error that never mentions
ports.

**Why not the obvious alternative**: `--min-instances=1` removes cold starts and is the
right call for anything user-facing at scale, where a few seconds of first-request latency
is a product problem. It also means paying for an instance that is idle the overwhelming
majority of the time, to improve a latency nobody is measuring on a personal tool.

**The concept**: Serverless economics charge for work rather than for capacity: you pay per
request and per unit of CPU and memory time while a request is in flight, which turns a
fixed monthly cost into a variable one proportional to use. Scale to zero is the limit case,
where an unused service costs nothing, and the price of it is the cold start: with no warm
instance, the next request waits for a container to be scheduled, the image pulled if
necessary and the process to boot. That is a latency-versus-cost dial, and choosing a
position on it should follow from who is waiting and how often. The part worth noticing is
that scale to zero is only available because of the earlier decisions: the session lives in
a signed cookie, the data lives in Cloud SQL and files live in Cloud Storage, so no instance
holds anything worth preserving and the platform is free to destroy all of them between two
requests. A stateful process cannot be scaled to zero, which is why entry 2's statelessness
is the enabling condition rather than a separate nicety.

**Expires when**: cold-start latency becomes annoying in real use, or a warm cache inside
the process turns out to be worth paying an idle instance for.

**See it yourself**: not runnable yet. After phase 13, `gcloud run services describe
cv-applier --region=europe-west1` shows the scaling bounds, and timing
`curl -s -o /dev/null -w "%{time_total}\n" https://SERVICE_URL/api/health` twice in a row
shows the cold start on the first call and its absence on the second.

---

## 17. Run the nightly refresh as a Cloud Run job, not an HTTP route

**Phase**: 14, scheduled refresh. Not built yet.

**The problem**: Sources have to be refreshed nightly. The app is already an HTTP service,
so the cheap-looking option is a route that runs the refresh and a scheduler that calls it
once a day.

**What we did**: A separate Cloud Run job, `cv-applier-refresh`, built from the same image
and running the refresh to completion, invoked by the Cloud Scheduler job
`cv-applier-nightly` on cron `0 5 * * *` in Europe/Bucharest. It is not an HTTP endpoint,
and the scheduler never calls the public service. A manual refresh triggered by the
signed-in owner is a separate question and stays a user action.

**Why not the obvious alternative**: `POST /api/jobs/refresh` on the running service needs
no new infrastructure and is testable with `curl`, which is genuinely attractive during
development. In production it fails in three distinct ways, set out below.

**The concept**: The public request surface and privileged batch work have different
requirements, and merging them means the stricter set of constraints is silently dropped.
A request has a client waiting and therefore a timeout, so work that legitimately takes
many minutes, fetching pages at one per second, does not fit the request/response lifetime;
a job has no waiting client, runs to completion, reports success or failure and is retried
by the platform. Batch work also competes for the same instances as user traffic under
`--max-instances=3`, so a long fetch loop degrades the interactive app. The third cost is
the one that is easy to miss: the service is deployed `--allow-unauthenticated` because it
authenticates users with its own session cookie, and Cloud Scheduler has no session cookie,
so an endpoint would have to accept a service account's OIDC token instead. That is a
second authentication scheme in the same service, guarding an internet-reachable route that
does expensive privileged work. The general shape, a web process for requests and a worker
or job process for everything else, is the same split as a Celery or Sidekiq worker, a
Kubernetes CronJob, or the web and worker dynos in a Heroku-style deployment.

**Expires when**: the owner needs to trigger a refresh on demand from the UI, or the run
outgrows a single job and needs fanning out per source.

**See it yourself**: not runnable yet. After phase 14, `gcloud scheduler jobs describe
cv-applier-nightly --location=europe-west1` shows the `0 5 * * *` schedule and the
Europe/Bucharest timezone, and `gcloud run jobs execute cv-applier-refresh
--region=europe-west1 --wait` runs it by hand.

---

## 18. Ship the compiled frontend inside the backend image

**Phase**: 16, shell and sign-in. Not built yet.

**The problem**: The React app and the API have to reach the browser somehow. The default
in modern tooling is to host the frontend separately, on a CDN or a static host, and have it
call the API on another domain.

**What we did**: Phase 16 turns `backend/Dockerfile` into a multi-stage build: one stage
builds the Vite bundle, the final stage copies the built assets into the backend image, and
FastAPI serves them. Browser and API therefore share one origin, the Cloud Run URL. During
local development Vite still runs on port 5173, which is why the CORS middleware in
`backend/app/main.py` and the `FRONTEND_ORIGIN` setting exist at all. One deployment detail
belongs here: Cloud Run terminates TLS and forwards the original scheme in
`X-Forwarded-Proto`, so uvicorn needs `--proxy-headers --forwarded-allow-ips="*"` or the
app builds its OAuth redirect URI as `http://` and Google rejects it.

**Why not the obvious alternative**: A CDN-hosted frontend gives edge caching, a deploy
that does not touch the backend, and a smaller backend image. Those are real benefits, and
at meaningful traffic or with a separate frontend team they dominate. For one developer,
one region and a personal tool, they buy nothing and cost a second deploy pipeline.

**The concept**: An origin is the triple of scheme, host and port, and the browser's
same-origin policy is defined in terms of it. Serving the app and its API from one origin
means the browser never makes a cross-origin request, which removes several things at once:
no CORS preflight `OPTIONS` requests and no `Access-Control-Allow-Credentials` negotiation,
no origin allowlist to keep in sync with deployment URLs, and, most importantly, the session
cookie is first-party rather than third-party. That last point is worth more each year, as
Safari's tracking prevention and Chrome's third-party cookie changes make cross-site cookies
progressively less reliable; a split frontend would push the session towards
`SameSite=None; Secure` or a token in a header, reopening the trade in entry 4 in the worse
direction. The honest counter-case is that same-origin couples the two deploys, so the
frontend cannot ship without the backend, and static assets are served by an application
process rather than an edge cache.

**Expires when**: the frontend needs its own release cadence, or asset latency outside
Belgium becomes a real complaint. A CDN in front of the same origin is the intermediate
step before splitting them.

**See it yourself**: today `rg -n "CORSMiddleware|allow_origins" backend/app/main.py` shows
the local-development machinery on lines 20 to 26. After phase 16,
`curl -s http://localhost:8000/ | head -5` returns the built `index.html` from the same
origin as `/api/health`.

---

## 19. Create the budget alert before the first chargeable resource

**Phase**: 4, GCP project and guardrails. Not built yet.

**The problem**: A trial with $300 of credit and a card attached is exactly the setup where
a mistake is expensive: a misconfigured instance, a runaway loop calling a paid API, or a
resource left running after an experiment. Nothing about the design makes this visible by
default.

**What we did**: A $50 budget on the billing account, with alerts at 50%, 90% and 100%,
created in phase 4 before anything chargeable exists. Phase 4 deliberately creates no
billable resource; the billing clock starts in phase 12 with Cloud SQL. The expected steady
state is about $12 a month, roughly $36 across the 90-day window, so the threshold is set
well above the plan and will only fire on something unintended.

**Why not the obvious alternative**: Watching the billing console when you remember to is
what most people do, and with a $300 credit that auto-closes rather than charging the card
it is not reckless. It also means the first signal of a mistake arrives whenever you next
look, which for a project touched in the evenings could be a week of a runaway resource.

**The concept**: Cost is a runtime property of a running system, not a number agreed once
before it is built. It is produced continuously by the design and the traffic, it varies
without anyone changing anything, and it is therefore observable in the same way as latency
or error rate, which means it deserves a monitor and a threshold like any other signal.
Ordering matters: a budget created before the first resource can never be forgotten later,
and an alert costs nothing to have. The detail that catches people out is that a budget
alert notifies, it does not cap; spending continues past 100%, and a real hard stop requires
separate machinery such as a Pub/Sub-triggered function that detaches the billing account,
or resource-level limits like `--max-instances=3`, which is the actual ceiling on runaway
request cost here. The broader habit is unit economics: knowing the cost of one cover letter
is about $0.005 makes it possible to reason about the bill before the bill arrives, which is
what FinOps practice formalises.

**Expires when**: the credit window closes and the account becomes pay-as-you-go, or actual
monthly spend approaches the $50 threshold, at which point the threshold is no longer a
signal of something wrong.

**See it yourself**: not runnable yet. After phase 4, `gcloud billing budgets list
--billing-account=BILLING_ACCOUNT_ID` shows the budget and its three thresholds.

---

## 20. Replace `create_all` with Alembic, retiring the no-migrations decision

**Phase**: 5, local cloud-parity stack. Not built yet.

**The problem**: Schema changes are currently applied by deleting the database. That was
fine while the only data was test rows, and it stops being fine the moment there is a real
uploaded CV and a real application history, or the moment more than one process starts at
once.

**What we did**: Alembic joins the dependencies in phase 5 and takes over the schema. The
`Base.metadata.create_all(bind=engine)` call in the lifespan handler of
`backend/app/main.py` goes away, replaced by versioned migration scripts applied with
`alembic upgrade head`, run explicitly rather than on startup, and run against Cloud SQL as
its own step in phase 12. The instruction in `AGENTS.md` to delete `backend/cv_applier.db`
and restart is retired along with SQLite.

**Why not the obvious alternative**: There is no reasonable alternative now, which is the
point of this entry. The alternative was the original decision: no migration tool, because
`create_all` is one line, and a schema under daily redesign with no data worth keeping is
genuinely better served by dropping the database than by writing a migration for every
change. That decision was correct when it was made, and phases 1 to 3 were built faster
because of it.

**The concept**: A schema migration is an ordered, versioned, reviewable script that moves
a database from one schema to the next, checked into the repository next to the code that
depends on it. `create_all` is not a weak migration tool, it is a different thing: it
creates tables that do not exist and never inspects or alters the ones that do, so adding a
column to `Profile` is silently a no-op against an existing database and the only way to
apply it is to destroy the data. Two specific things invalidated the original decision.
Data that cannot casually be deleted, since a user's parsed CV and application history are
the product. And concurrent startup: `create_all` issues DDL when the process boots, so two
Cloud Run instances cold-starting at the same moment race on creating the same tables,
which is why Alembic must arrive in phase 5, before the first deploy, rather than after.
Every serious stack has the same tool, Flyway and Liquibase on the JVM, Rails and Django
migrations, and all of them converge on the same discipline: migrations are
forward-compatible with the previous code version, because during a rollout both versions
are running at once, which is the expand/contract pattern.

This is the one decision in this log that has already expired, and it expired on schedule
rather than during an incident, because the condition that would invalidate it, real data
plus more than one process, was foreseeable. That is the whole argument for writing an
expiry condition into every entry: it converts a future surprise into a scheduled piece of
work, and it means a decision can be defended on its original context instead of being
defended forever.

**Expires when**: a migration needs to run against a table large enough that locking it
blocks requests. At that point a single migration step is no longer the unit of work, and
the process becomes expand/contract across two deploys.

**See it yourself**: today `rg -n create_all backend/app/main.py` returns line 14, the call
in the lifespan handler. After phase 5 it returns nothing, and `alembic current`, run in
the app container, reports the applied revision.

---

## 21. Provision GCP with Terraform, not the console or one-off commands

**Phase**: 4, GCP project and guardrails. Not built yet.

**The problem**: Every resource so far has been described in this document as a `gcloud`
command or a console click-path. Both work, and both share the same failure mode: the
only record of what exists is either your memory of what you ran, or nothing at all if you
clicked it. Rebuilding the project after deleting it, or explaining to a future reader
exactly what state GCP is in, means re-deriving it from prose.

**What we did**: Every GCP resource in this project - APIs, the service account and its
roles, Cloud SQL, the buckets, Secret Manager containers, Cloud Run, the scheduler - is
declared in Terraform, across the two modules `infra/bootstrap/` and `infra/main/`
described in entry 22. `terraform plan` shows what would change before anything does, and
`terraform apply` is the only command that touches real infrastructure. `gcloud` remains
for the handful of things that are not desired state - running a migration, pushing an
image, executing a job by hand - and for the one seed step Terraform cannot do for itself.

**Why not the obvious alternative**: Clicking through the console is genuinely faster for
a single resource, has autocomplete for every field, and needs no tool installed. For a
project this size, typing the equivalent `gcloud` commands from this document is almost as
fast as writing the Terraform for the same resource. Both are real costs against a real
benefit, which is why this entry exists rather than being assumed.

**The concept**: Infrastructure as code means the desired state of the system is a text
file, checked into version control, and a tool reconciles reality to match it rather than
a person performing steps. The distinction worth holding onto is declarative versus
imperative: a `gcloud` command is an instruction, "do this," which says nothing about what
should be true afterward and nothing about what else might already be true; a Terraform
resource block is an assertion, "this should exist, configured exactly this way," and the
tool works out the steps. That difference is what makes `terraform plan` a dry run with
teeth: it diffs desired state against real state and shows the exact change before you
approve it, which a `gcloud` command or a console click never offers. It is also what
makes the whole project reproducible from a fresh checkout instead of from a person's
memory of what they ran, and reviewable as a diff instead of invisible. The same shift is
why Kubernetes manifests replaced kubectl-run scripts, why CloudFormation and Terraform
both outcompeted click-ops at any team size, and why "configuration drift" - the state of
things quietly diverging from what anyone intended - is a named failure mode with tooling
built specifically to detect it.

**Expires when**: a second person needs to change this infrastructure at the same time, at
which point state locking and a review step in CI matter more than they do for one person
applying from a laptop.

**See it yourself**: not runnable yet. After phase 4, `terraform -chdir=infra/main plan`
with no pending changes prints "No changes," which is the tool asserting that reality
matches the file, not a guess.

---

## 22. Split Terraform into a bootstrap module and a main module

**Phase**: 4, GCP project and guardrails. Not built yet.

**The problem**: Terraform needs somewhere to store its own state - the record of what it
created and with what configuration - and the natural place is a GCS bucket in this same
project. That bucket does not exist until Terraform creates it, which means the very first
`terraform apply` needs a backend that does not exist yet, created by the tool that needs
the backend to run.

**What we did**: Two Terraform root modules that never share a state file.
`infra/bootstrap/` runs first, with local state, because the one thing it creates is the
`cv-applier-tfstate-PROJECT_ID` bucket, plus the budget and the handful of APIs
bootstrapping itself needs. Once that bucket exists, bootstrap adds a `backend "gcs"`
block pointing at its own creation and `terraform init -migrate-state` moves its state off
the laptop and into the bucket, closing the loop. `infra/main/` never has this problem: it
points at the same bucket under a different prefix from its very first `init`, and holds
everything else - the runtime service account, Cloud SQL, the uploads bucket, Cloud Run,
the scheduler. `main` also never gets permission to create or move its own backend; the
bucket it depends on is not one of the resources it manages.

**Why not the obvious alternative**: One module, with local state, is the simplest thing
that could work and is exactly how every Terraform tutorial starts. It works until the
laptop is unavailable, at which point the state - the only record of what exists and how
it maps to the `.tf` files - is unavailable with it, and "reproducible at any time"
quietly becomes "reproducible if this one laptop survives."

**The concept**: This is a specific, well-known instance of a bootstrapping problem: a
system that needs infrastructure to manage infrastructure cannot use that infrastructure
for its own first step. The general answer is the same everywhere it appears - a compiler
that compiles itself needs an earlier compiler to build the first version, a blockchain's
genesis block has no previous block to reference, a new Kubernetes cluster needs something
outside the cluster to create the cluster - which is to shrink the unavoidable manual or
external part to the smallest possible seed and be explicit about exactly what it is,
rather than pretending the whole system is self-hosting from step one. The second reason
for the split, independent of the chicken-and-egg problem, is privilege separation: the
service account that manages application infrastructure should not also be able to
relocate or delete the record of what that infrastructure is, the same way a database's
application user should not hold permission to drop its own audit log.

**Expires when**: the project moves to a team or a CI pipeline running `terraform apply`,
at which point state locking and a dedicated Terraform service account, rather than
personal ADC credentials, become worth the setup cost.

**See it yourself**: not runnable yet. After phase 4,
`gcloud storage ls gs://cv-applier-tfstate-PROJECT_ID/` lists a `bootstrap/` and a `main/`
prefix, each holding its own state, and nothing under either exists on disk.

---

## 23. Keep Terraform state in a dedicated bucket, never beside app data

**Phase**: 4, GCP project and guardrails. Not built yet.

**The problem**: Terraform's state file is a JSON record of every resource it manages and
every attribute Terraform read back about it, which by phase 13 includes the Cloud SQL
connection name embedded in a database URL and, if `db_password` is supplied as a
Terraform variable, the password itself. It needs to live somewhere.

**What we did**: A bucket that exists for exactly one purpose,
`cv-applier-tfstate-PROJECT_ID`, separate from `cv-applier-uploads-PROJECT_ID` where CVs
land, with versioning turned on and uniform bucket-level access. No application code ever
reads or writes to it; only Terraform does, running as whoever's ADC credentials are
applying at the time.

**Why not the obvious alternative**: One bucket for everything is one fewer resource to
create and one fewer name to remember, and one already existed for uploads by phase 12.
The two have nothing in common once you ask who should be allowed to read them: a CV is
one user's document, and state is a record that can contain infrastructure credentials, so
a bucket policy generous enough for the first is already too generous for the second.

**The concept**: State deserves the same instinct as a secret, because in this project it
sometimes is one: a database password lives there the moment any resource references it,
whether or not it looks like a credential in the `.tf` file that produced it. Remote state,
kept in a bucket rather than on a laptop, solves reproducibility, but reproducibility and
confidentiality are different axes and a fix for one says nothing about the other. The two
mitigations here address them separately: a dedicated bucket with narrow IAM limits who
can read a file that might contain a credential, and versioning is a rollback path if a bad
apply overwrites good state, the infrastructure equivalent of entry 15's argument for
immutable, addressable artifacts over one mutable `:latest` pointer. Terraform Cloud and
Terraform Enterprise exist substantially to formalise this exact concern - encrypted
state, audited access, locking - for teams past the point where a bucket and a habit are
enough.

**Expires when**: state needs to be read by more than one person or CI pipeline at a time,
which is when state locking (the GCS backend supports it natively) starts mattering, or
when a secret genuinely needs to be kept out of state entirely rather than just
access-controlled, which is entry 24.

**See it yourself**: not runnable yet. After phase 4,
`gcloud storage buckets describe gs://cv-applier-tfstate-PROJECT_ID --format="value(versioning.enabled)"`
prints `True`, and `gcloud storage buckets get-iam-policy gs://cv-applier-tfstate-PROJECT_ID`
lists only your own account, not the runtime service account - the application has no
business reading its own infrastructure's state.

---

## 24. Keep secret values out of Terraform; containers only

**Phase**: 4 and 12, GCP project and guardrails; data plane. Not built yet.

**The problem**: Secret Manager, Cloud SQL users, and Cloud Run's environment all need
real values eventually - a JWT signing secret, a database password, an OAuth client
secret - and Terraform can create all three kinds of resource. Writing the value directly
into a resource block is the shortest path from "I have a secret" to "it is deployed."

**What we did**: A single rule, applied everywhere a secret shows up: Terraform manages
the *container*, never the *value*. `google_secret_manager_secret` resources create empty
`jwt-secret` and `google-client-secret` entries with no version; the actual bytes are set
afterward with `gcloud secrets versions add`. The Cloud SQL user and its password are
created with `gcloud sql users create`, never a Terraform resource. Cloud Run reads the
two Secret Manager values through `value_source.secret_key_ref`, so the running service
never has the value typed into a `.tf` file either. The one deliberate exception is the
database password inside `DATABASE_URL`, which does land in Terraform state because Cloud
Run needs the whole connection string as one value - entry 11 already accepted this same
value sitting in a `--set-env-vars` string before Terraform existed in this plan, so
nothing new is exposed, only relocated.

**Why not the obvious alternative**: A `sensitive = true` Terraform variable feels like it
solves this, and it solves one thing: it hides the value from `plan` and `apply` output on
your screen. It does not touch state, which is written as plain JSON regardless of any
`sensitive` flag on the variable that produced a value, so a secret passed this way is
exactly as exposed in the state file as if it had been typed in literally.

**The concept**: Terraform state is not a secrets manager and was never designed as one;
it is a cache of the last-known-real values of everything Terraform touches, stored as
plain text by default because the tool's job is diffing and applying, not access control.
The `sensitive` flag is a display feature, not a security boundary - a distinction worth
learning once here rather than by finding a password with `grep` in a `.tfstate` file
later. The safer design is not to encrypt or restrict the container that might hold a
credential, though the narrow bucket IAM from entry 23 does that too as a second layer,
but to make sure the credential is never handed to that container in the first place. This
is the same instinct as entry 12's refusal to download a service-account key: the
strongest protection for a secret is one that never has to be protected because it does
not exist in that form.

**Expires when**: a secret needs to be created *by* Terraform because no human step should
exist to set it - for example, a per-environment password generated fresh on every
`apply`. That is a real use case (Terraform's `random_password` resource exists for it),
and taking it means accepting the value in state and compensating with tighter state
access, not pretending the trade disappeared.

**See it yourself**: not runnable yet. After phase 12,
`terraform -chdir=infra/main state show google_secret_manager_secret.jwt` prints the
container's metadata and no value, because there is no value in that resource to print;
`gcloud secrets versions access latest --secret=jwt-secret` is the only command in this
project that can produce the real one.

---

## 25. Let Terraform own the Cloud Run service, but not its image

**Phase**: 13, first deploy. Not built yet.

**The problem**: The Cloud Run service is created once, in Terraform, and then redeployed
on every push by Cloud Build for the rest of the project's life, which means two systems
both have an opinion about the same resource's container image: the `.tf` file says
whatever tag was current when it was last edited, and the live service says whatever
Cloud Build most recently pushed to it.

**What we did**: `lifecycle { ignore_changes = [template[0].containers[0].image] }` on the
`google_cloud_run_v2_service` resource. Terraform still creates the service - the scaling
bounds, the service account, the environment variables, the Cloud SQL volume - and simply
stops tracking that one field once the service exists, leaving Cloud Build free to change
it on every deploy without Terraform trying to put it back. The Cloud Run job in phase 14
needs the identical treatment, one nesting level deeper, because a job's execution
template sits inside its job template where a service has only one level;
`ignore_changes = [template[0].template[0].containers[0].image]` is the line that
actually matches, and the service's own path silently matches nothing on a job.

**Why not the obvious alternative**: Letting one system own the whole resource is the
clean answer on paper: either Terraform deploys every image, or Cloud Run is not in
Terraform at all and every setting is pushed via `gcloud`. The first throws away the reason
Cloud Build exists, fast automatic deploys on every push without a local Terraform run; the
second throws away everything else this entry's siblings give the rest of the resource -
review, reproducibility, a plan before a change.

**The concept**: This is drift by design rather than drift by accident, and the fix is to
tell the tool which field it does not own rather than fighting it. `ignore_changes` splits
ownership of one resource across two systems along a field boundary: Terraform owns the
shell - everything that should look the same on the next `apply` regardless of what has
deployed since - and the CI pipeline owns the one field that changes on a schedule
Terraform is not part of. The same shape appears wherever infrastructure-as-code and
continuous deployment touch the same object: an ECS task definition's image tag managed
outside the Terraform-defined service, a Kubernetes Deployment's image field left to Argo
CD or Flux while Terraform or Helm owns the rest of the manifest. The sharp edge worth
carrying forward is that `ignore_changes` is a planning-time filter, not an apply-time
guarantee: the provider sends the whole resource definition on every update, so applying a
plan that was computed before the last external deploy can still roll the image backward.
The rule that avoids this is procedural, not technical - always `plan` and `apply`
together, against fresh state, never from a saved plan file that might predate the last
deploy.

**Expires when**: the deploy pipeline and the Terraform apply need to be the same
operation, for example if deploys should themselves go through a review step. At that
point the image belongs in the `.tf` file and Terraform apply becomes the deploy
mechanism, which is a valid design, just a different one from this project's.

**See it yourself**: not runnable yet. After phase 15, push a trivial change to `main`,
let it deploy, then run `terraform -chdir=infra/main plan`: it should report no change to
the Cloud Run service at all, despite the live image having just changed underneath it.

---

## 26. Accept one console step: GitHub's own authorization for Cloud Build

**Phase**: 15, deploy on push. Not built yet.

**The problem**: A Cloud Build trigger needs to read a GitHub repository and receive its
push events, which means something has to prove to GitHub that Cloud Build is allowed to
see this repository. That proof is an authorization grant, and it is GitHub's flow, not
Google's.

**What we did**: One console step, done once: under Cloud Build, Repositories, Connect
Repository, GitHub (2nd generation), which installs Google's Cloud Build GitHub App on the
repository. Everything downstream of that grant is Terraform: the connection it creates is
read back with a `data "google_cloudbuildv2_connection"` block rather than a resource,
because Terraform never created it and importing something you are about to read as a
data source anyway adds a step for no benefit, and the repository reference and the
trigger built on top of that data source are ordinary managed resources.

**Why not the obvious alternative**: Forcing this into Terraform is possible in the narrow
technical sense - `google_cloudbuildv2_connection` is a real resource, and it accepts a
GitHub App installation id and an OAuth token - but both of those inputs have to come from
somewhere, and that somewhere is the same interactive GitHub authorization this entry is
about. Wrapping it in a resource block would not remove the manual step, it would just
hide it one layer down and add the risk of a stored token going stale silently.

**The concept**: Not every integration between two systems has an API-shaped equivalent of
a click. GitHub's App installation flow exists specifically so a human, logged into GitHub,
can see and approve exactly what access is being granted to exactly which repositories,
and short-circuiting that with a script is either impossible or a worse version of the
same grant with none of the visibility. The honest bar for infrastructure-as-code is
"everything that can reasonably be declarative," not "everything," and telling the two
apart is a judgment call that improves with exposure to more of these boundaries, not a
rule that can be looked up. The corollary worth carrying forward is what to do once you
find one of these seams: not to fight it, but to shrink it to its smallest form, one click,
noted down, and hand Terraform a read-only view of the result, which is exactly entry 22's
answer to the project-creation seed applied to a different boundary.

**Expires when**: GitHub or Google ships a fully non-interactive, API-driven equivalent of
the App installation grant - a service-to-service credential exchange with no human
approval step - at which point this stops being a real exception and becomes just another
resource.

**See it yourself**: not runnable yet. After phase 15,
`terraform -chdir=infra/main state list | grep cloudbuild` lists the repository and the
trigger as managed resources; the connection itself is absent from that list because it
was always a data source, and `gcloud builds connections describe cv-applier-github
--region=europe-west1` is what actually shows it exists.

---

## How this file is maintained

An entry is appended in the same change as the work it describes, at the moment the
decision is taken, while the alternatives are still fresh. An entry written weeks later
becomes a justification rather than a record.

Entries are never retroactively tidied. The wording, the reasoning and the uncertainty stay
as they were, because the value of the log is that it shows what was known at the time.
Numbers are never reused and entries are never renumbered.

When a decision is replaced, the old entry is marked, not deleted: add a line
`**Superseded by**: entry N` directly under its title and leave everything below it
untouched. The reasoning that led to the original choice is the part worth keeping, since it
is usually still correct about its own context. Entry 20 is the first example, and it holds
the retired no-migrations decision inside itself rather than erasing it.
