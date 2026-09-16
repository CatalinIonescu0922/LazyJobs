# CV Applier - Build Plan

Execution checklist for [PLAN.md](PLAN.md). Work proceeds one phase at a time; each phase
ends with something you can run and check. Live status for every phase is tracked in
[PROGRESS.md](PROGRESS.md) - check there for where the build currently stands.

The app runs on Google Cloud Platform. The cloud phases below give the exact commands to
run and what their output should look like; the concepts behind them - what a service
account is, why a managed database costs money and a container does not - live in
[LEARNING.md](LEARNING.md).

Conventions used below:

- **Files** - what gets created or changed in that phase.
- **Verify** - the command or click-path that proves the phase works.
- **Done when** - the observable result to look for before moving on.
- `PROJECT_ID`, `BILLING_ACCOUNT_ID`, `SERVICE_URL` and similar capitals in commands are
  placeholders. Substitute your own values; every other name is fixed and is used
  verbatim across phases.

Everything lives in `europe-west1` (Belgium), except Vertex AI, which uses the `global`
endpoint.

---

## Prerequisites

Install the `gcloud` CLI, Docker with Compose, Python 3.12 and Node 20. A Google Cloud
billing account with the $300 / 90-day free trial credit is assumed.

The Google Cloud project comes first, because the OAuth client used for sign-in is a
credential inside it. Phase 4 creates that project. Once it exists:

1. Google Cloud Console, with the phase 4 project selected.
2. APIs and Services, OAuth consent screen: External, add yourself as a test user.
3. Credentials, Create credentials, OAuth client ID, type Web application.
4. Authorised redirect URI: `http://localhost:8000/api/auth/google/callback`. Phase 13
   adds the Cloud Run URL as a second one.
5. Copy the client ID and secret into `backend/.env`.

Phases 1 to 3 were built before the project existed, against a hand-made OAuth client.
If that client lives in some other project, recreate it inside the phase 4 project so
everything bills and audits in one place.

There is no separate LLM key. Vertex AI authenticates with the same Google credentials as
everything else, set up in phase 4.

`backend/.env`:

```
DATABASE_URL=postgresql+psycopg://cv:cv@db:5432/cv_applier
JWT_SECRET=<random 32+ chars>
FRONTEND_ORIGIN=http://localhost:5173
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
GOOGLE_CLOUD_PROJECT=
GCS_BUCKET=
STORAGE_EMULATOR_HOST=http://gcs:4443      # local only, unset in production
VERTEX_LOCATION=global
VERTEX_MODEL=gemini-3.1-flash-lite
COOKIE_SECURE=false                         # true on Cloud Run
```

`DATABASE_URL` points at the compose service named `db`, which phase 5 introduces. Before
that phase the value is whatever SQLite URL you already have.

---

## Phase dependencies

```mermaid
flowchart TD
  S1[Phase 1 Skeleton] --> S2[Phase 2 Models]
  S2 --> S3[Phase 3 Google auth]
  S3 --> S4[Phase 4 GCP guardrails]
  S4 --> S5[Phase 5 Local cloud parity]
  S5 --> S6[Phase 6 CV and profile]
  S5 --> S7[Phase 7 eJobs source]
  S7 --> S8[Phase 8 ATS source]
  S6 --> S9[Phase 9 Matching]
  S7 --> S9
  S8 --> S9
  S9 --> S10[Phase 10 Applications API]
  S10 --> S11[Phase 11 Cover letters]
  S11 --> S12[Phase 12 Data plane]
  S12 --> S13[Phase 13 First deploy]
  S13 --> S14[Phase 14 Scheduled refresh]
  S13 --> S15[Phase 15 Deploy on push]
  S13 --> S16[Phase 16 Frontend shell]
  S6 --> S17[Phase 17 Profile screen]
  S9 --> S18[Phase 18 Matches screen]
  S10 --> S19[Phase 19 Tracker screen]
  S11 --> S19
  S19 --> S20[Phase 20 Polish]
  S15 --> S21[Phase 21 Observability]
```

Phases 7 and 8 do not depend on auth, so the job pipeline can be proven early and
independently if you would rather see results before building screens.

Nothing is deployed until phase 13, and nothing costs money until phase 12. That ordering
is deliberate: the whole application is proven against the compose stack from phase 5
first, so the credit is spent on a system that already works.

---

# Part 1 - Backend, running locally

## Phase 1. Application skeleton

**Goal** - a server that boots, serves docs, and talks to the frontend origin.

**Files** - `backend/app/main.py`, edit `backend/app/config.py`, add `backend/.env.example`,
add `.gitignore`.

Details: FastAPI app with CORS restricted to `FRONTEND_ORIGIN` and `allow_credentials=True`
(required for the session cookie), a `GET /api/health` route, and table creation on
startup via `Base.metadata.create_all`. Config gains the Google and frontend settings
listed above and drops nothing yet.

No Alembic. SQLite plus `create_all` is right for a single-developer project; migrations
become worth it when someone else runs the app.

**Verify** - `uvicorn app.main:app --reload` then `curl localhost:8000/api/health`

**Done when** - health returns 200 and `/docs` lists the route.

Effort: 30 minutes.

---

## Phase 2. Data model for identity

**Goal** - tables that match the auth design.

**Files** - edit `backend/app/models.py`, edit `backend/requirements.txt`.

Changes: remove `password_hash` from `User`, add `name`, `avatar_url` and `last_login_at`.
Add the `Identity` model:

```python
class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

Drop `bcrypt` from requirements. Delete any existing `cv_applier.db` rather than
migrating, since there is no real data yet.

**Verify** - `python -c "from app.db import Base, engine; Base.metadata.create_all(engine)"`
then inspect with `sqlite3 cv_applier.db ".schema identities"`

**Done when** - the schema prints with the unique constraint present.

Effort: 20 minutes.

---

## Phase 3. Google sign-in

**Goal** - a real Google login that ends with a session cookie.

**Files** - `backend/app/oauth.py`, `backend/app/session.py`, `backend/app/routers/auth.py`.

`oauth.py` holds the provider registry and the flow mechanics:

```python
@dataclass(frozen=True)
class Provider:
    name: str
    auth_url: str
    token_url: str
    userinfo_url: str
    scopes: str
    client_id: str
    client_secret: str

    def identity_from(self, claims: dict) -> ExternalIdentity: ...


PROVIDERS = {"google": Provider(...)}
```

Flow specifics:

- `/login` builds the authorization URL with `state` and `code_challenge` (S256), and
  stores `state` plus the PKCE verifier in a signed cookie with a five minute expiry.
- `/callback` rejects a mismatched or missing `state` before doing anything else,
  exchanges the code, then reads `sub`, `email`, `email_verified`, `name`, `picture`
  from userinfo.
- Find identity by `(provider, sub)`. If absent and a user with that email exists and
  `email_verified` is true, link a new identity to it. If absent otherwise, create user,
  identity and an empty profile in one transaction.
- Google tokens are used and discarded, never persisted.

`session.py` holds `create_session_token`, the cookie name and flags
(httpOnly, SameSite=Lax, Secure off for localhost), and the `current_user` dependency.

**Verify** - open `http://localhost:8000/api/auth/google/login` in a browser, complete
Google, then `curl -b cookies.txt localhost:8000/api/auth/me`

**Done when** - `me` returns your email, and a second sign-in reuses the same user row
rather than creating a duplicate.

Effort: 2 hours, most of it Google Console setup and redirect URI typos.

---

## Phase 4. GCP project and guardrails

**Goal** - a project with a spending alarm, the APIs it will need switched on, a runtime
identity, and working credentials on your laptop. Nothing chargeable is created here.

**Files** - `docs/cloud.md`, edit `backend/requirements.txt` (add `google-genai`), edit
`backend/.env.example`.

Sign in and create the project. The project id is globally unique and permanent, so pick
something like `cv-applier-<yourname>`.

```
gcloud auth login
gcloud projects create PROJECT_ID --name="CV Applier"
gcloud config set project PROJECT_ID
```

Link the billing account that holds the trial credit. `gcloud billing accounts list`
prints the id in `XXXXXX-XXXXXX-XXXXXX` form.

```
gcloud billing accounts list
gcloud billing projects link PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
```

Set the budget **before** creating anything else. This is the one step that is worthless
if done later, because its whole purpose is to catch a mistake made in a phase that has
not happened yet. The budget command needs its own API on first use:

```
gcloud services enable billingbudgets.googleapis.com

gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="cv-applier" \
  --budget-amount=50USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0
```

A budget alert emails you at 50%, 90% and 100% of $50. It does not cap anything. Nothing
is switched off when the threshold is crossed, so treat the first mail as the signal to
go and look, not as a safety net that already acted.

Enable the APIs the later phases need. Each one is off by default and the error you get
without it names the API, so this list is only here to save round trips.

```
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com
```

Create the identity the deployed app will run as, and grant it the three project-level
roles it needs. The fourth role, `roles/storage.objectAdmin`, is granted in phase 12 on
the bucket alone rather than project-wide, so the app can write CVs and nothing else.

```
gcloud iam service-accounts create cv-applier-run --display-name="CV Applier runtime"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:cv-applier-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:cv-applier-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:cv-applier-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Set up Application Default Credentials so local code authenticates as you, with no key
file anywhere on disk. On Cloud Run the same code picks up the attached service account
instead, which is why no service-account JSON key is ever downloaded in this project.

```
gcloud auth application-default login
gcloud auth application-default set-quota-project PROJECT_ID
```

**Verify** - one Vertex AI call, costing a fraction of a cent:

```python
from google import genai

client = genai.Client(vertexai=True, project="PROJECT_ID", location="global")
print(client.models.generate_content(model="gemini-3.1-flash-lite", contents="Reply with the word ready").text)
```

**Done when** - that script prints text rather than a permission or billing error,
`gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID` shows the $50 budget
with three thresholds, and the project contains no Cloud SQL instance and no bucket.

Two things that confuse everyone once: the trial credit pays for Vertex AI but **not**
for the Gemini API in Google AI Studio - same models, different products, different
billing - and the console now calls Vertex AI the "Gemini Enterprise Agent Platform"
while the docs and everyone else still say Vertex AI.

Effort: 1 hour.

---

## Phase 5. Local cloud-parity stack

**Goal** - the app runs in a container against Postgres and a Cloud Storage emulator, so
the only thing production adds later is a different endpoint and a real database.

**Files** - `backend/Dockerfile`, `docker-compose.yml`, `backend/alembic.ini`,
`backend/alembic/versions/`, edit `backend/app/db.py`, `backend/app/config.py`,
`backend/app/main.py`, `backend/requirements.txt`, delete `backend/cv_applier.db`.

`backend/Dockerfile` is single-stage and slim. Phase 16 adds a first stage for the
frontend build; until then there is nothing to compile.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
ENV PORT=8000
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} \
    --proxy-headers --forwarded-allow-ips="*"
```

Both details in that command exist for Cloud Run and matter there, not locally. Cloud Run
injects `PORT` and a container that hardcodes a port fails to start with a health-check
error that never mentions ports. `--proxy-headers --forwarded-allow-ips="*"` makes Uvicorn
trust `X-Forwarded-Proto`, without which the app builds its OAuth redirect URI as `http://`
behind Cloud Run's TLS termination and Google rejects it.

`docker-compose.yml` runs three services: `app` built from `backend/`, `db` on
`postgres:16` with a named volume so data survives a restart, and `gcs` on
`fsouza/fake-gcs-server`. The emulator is reached by setting `STORAGE_EMULATOR_HOST` to
`http://gcs:4443`; the application uses the real `google-cloud-storage` client either way,
so there is one code path and no storage abstraction to maintain.

Move off SQLite entirely. Add `psycopg[binary]` and point `DATABASE_URL` at
`postgresql+psycopg://cv:cv@db:5432/cv_applier`. Then adopt Alembic: `alembic init`, set
`target_metadata` to `Base.metadata`, autogenerate the first migration from the models as
they already are, and delete the `create_all` call from startup.

```
docker compose run --rm app alembic revision --autogenerate -m "initial schema"
docker compose run --rm app alembic upgrade head
```

Alembic arrives now rather than at deploy time because `create_all` on startup races when
more than one Cloud Run instance cold starts at once, and a race in schema creation is a
miserable thing to debug from logs.

**Verify** - `docker compose up --build`, then re-run every check from phases 1 to 3
against the stack: `curl localhost:8000/api/health`, open `http://localhost:8000/docs`,
and complete a full Google sign-in followed by `curl -b cookies.txt localhost:8000/api/auth/me`.

**Done when** - all three pass, `docker compose exec db psql -U cv -d cv_applier -c "\d identities"`
shows the table Alembic built, and `backend/cv_applier.db` is gone from the repository.

Effort: 3 hours.

---

## Phase 6. CV upload and profile

**Goal** - upload a real CV and get an editable structured profile.

**Files** - `backend/app/cv.py`, `backend/app/storage.py`, `backend/app/llm.py`
(extraction only), `backend/app/routers/profile.py`, `backend/app/schemas.py`,
edit `backend/requirements.txt` (add `google-cloud-storage`, drop `openai`).

Details: `cv.py` dispatches on file extension, `pdfplumber` for PDF and `python-docx` for
DOCX, returning plain text; reject anything else with a 400. `storage.py` writes the
uploaded file to the bucket in `GCS_BUCKET` with the `google-cloud-storage` client;
locally that client talks to the emulator because `STORAGE_EMULATOR_HOST` is set, and in
production the variable is unset and the same code reaches Cloud Storage. `llm.py` sends
the text with a JSON-schema-shaped prompt to Vertex AI and parses the response into
profile fields:

```python
from google import genai

client = genai.Client(vertexai=True, project=settings.google_cloud_project, location=settings.vertex_location)
response = client.models.generate_content(model=settings.vertex_model, contents=prompt)
```

There is no keyword-extraction fallback. Credentials come from the cloud project - your
own ADC locally, the attached service account in production - so "no key configured" is
not a state this app can be in, and a fallback path nobody exercises is a liability.

`PATCH /api/profile` accepts corrections to every extracted field plus the search
preferences.

Guard rails worth having: cap upload size at about 5 MB, and truncate CV text before the
model call so a 40 page CV cannot blow the context window.

**Verify** - upload your own CV in both formats through `/docs`, then `GET /api/profile`,
then confirm the object landed:
`curl http://localhost:4443/storage/v1/b/$GCS_BUCKET/o`

**Done when** - skills and titles come back recognisably correct, a `PATCH` sticks, and
the uploaded file is listed in the emulator bucket.

Effort: 2.5 hours.

---

## Phase 7. eJobs source

**Goal** - real Romanian postings in the database.

**Files** - `backend/app/sources/base.py`, `backend/app/sources/ejobs.py`,
`backend/app/sources/registry.py`, `backend/app/routers/jobs.py`.

Details: `base.py` carries the `Posting` dataclass and `JobSource` protocol from
[PLAN.md](PLAN.md) section 7. `ejobs.py` does discovery from the category sitemaps plus
`rss-listings.xml`, filters to URLs not already in `jobs`, then fetches each detail page
and extracts the `JobPosting` node from the JSON-LD `@graph`. One second between requests,
identifying User-Agent, and a hard cap on pages per run so a first run cannot spider the
whole site.

Romanian remote detection: check `jobLocationType` first, then look for "remote",
"de acasa", "telemunca" and "hibrid" in the title and description, on diacritic-normalised
text.

`POST /api/jobs/refresh` runs the enabled sources and upserts on `(source, external_id)`.

**Verify** - `POST /api/jobs/refresh`, then
`docker compose exec db psql -U cv -d cv_applier -c "select company, title, locations from jobs limit 10"`

**Done when** - ten real listings with populated company, location and description.

Effort: 3 hours. This is the phase most likely to need iteration on parsing.

---

## Phase 8. ATS source and coverage check

**Goal** - ATS boards wired in, and an honest answer on whether they help for Romania.

**Files** - `backend/app/sources/ats.py`, `backend/app/sources/companies.py`.

Details: one fetcher with three response mappings.

- Greenhouse: `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
- Lever: `api.lever.co/v0/postings/{slug}?mode=json`
- Ashby: `api.ashbyhq.com/posting-api/job-board/{slug}`

`companies.py` is a plain list of `(provider, slug)` pairs. Seed it with known-good slugs
(`stripe`, `databricks`, `gitlab`, `figma`, `coinbase` on Greenhouse) plus any Romanian
employers found while building.

Before going further, count how many fetched roles are Romania-eligible, meaning located
in Romania or genuinely remote-EU. Write the number in this file. If it is negligible,
mark ATS as secondary and move BestJobs into scope from the later-phase list in
[PLAN.md](PLAN.md) section 16.

**Verify** - `POST /api/jobs/refresh`, then group by source and count Romania-eligible rows.

**Done when** - the count exists and the decision is recorded.

Effort: 2 hours including the measurement.

---

## Phase 9. Matching

**Goal** - ranked matches with a readable reason.

**Files** - `backend/app/matching.py`, extend `backend/app/routers/jobs.py`.

Details: normalise text (lowercase, strip diacritics), apply the hard filters, then score
title overlap, skills overlap and recency into 0 to 100. Build the reason string from the
actual matched skills. Keep the small Romanian/English synonym map beside the scorer.

This is pure functions over plain data, so it is the one part worth unit testing: a
handful of fabricated postings asserting order and filter behaviour.

**Verify** - `GET /api/matches` after phases 6 and 7

**Done when** - the top results are plausibly yours, and every result carries a reason.

Effort: 2 hours.

---

## Phase 10. Applications API

**Goal** - the review queue as data.

**Files** - `backend/app/routers/applications.py`.

Details: create from a match (guarding the `(user, job)` uniqueness), list filtered by
status, patch status, notes and letter. Validate status transitions against the lifecycle
in [PLAN.md](PLAN.md) section 5 and stamp `submitted_at` when entering `submitted`.

**Verify** - create, patch through to `submitted`, list by status

**Done when** - an invalid transition is rejected and `submitted_at` is set exactly once.

Effort: 1 hour.

---

## Phase 11. Cover letters

**Goal** - a draft worth editing rather than rewriting.

**Files** - extend `backend/app/llm.py`, extend the applications router.

Details: `draft_cover_letter(profile, job)` gets the profile summary, the matched skills
and the job description, and is told to write in the language of the posting, which
matters on eJobs where half the listings are Romanian. Store on the application and move
status to `drafted`.

The call goes to Vertex AI through the same `genai.Client` built in phase 6, with the
same `gemini-3.1-flash-lite` model, so there is one client and one set of credentials in
the codebase. A letter costs about $0.005.

**Verify** - draft a letter for a real eJobs match and read it

**Done when** - the letter names the company and role and reads like your CV, not a template.

Effort: 1 hour.

---

# Part 2 - Running on GCP

## Phase 12. Data plane

**Goal** - the database, the bucket and the secrets that production will use, with the
schema already migrated into place.

**Files** - extend `docs/cloud.md`.

This is the phase where the billing clock starts. Everything before it was free. From the
moment the Cloud SQL instance exists it bills about $10 a month whether or not anybody
uses it, which is the only meaningful running cost in the whole project.

```
gcloud sql instances create cv-applier-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=europe-west1 \
  --storage-size=10GB \
  --storage-type=SSD \
  --availability-type=zonal

gcloud sql databases create cv_applier --instance=cv-applier-db
gcloud sql users create cv --instance=cv-applier-db --password=DB_PASSWORD
```

The instance has no authorized networks, so nothing on the internet can open a connection
to it. Access goes exclusively through the Cloud SQL Auth Proxy, which authenticates with
IAM rather than with an IP allowlist: locally you run the proxy yourself, and Cloud Run
runs it for you as a unix socket at `/cloudsql/INSTANCE_CONNECTION_NAME`, which is why no
VPC connector appears anywhere in this project. Going further and creating the instance
with `--no-assign-ip` would require a VPC network and, on the Cloud Run side, a connector
or direct VPC egress to reach it, which buys nothing here and is why the default address
is left in place with an empty allowlist. `db-f1-micro` is shared-core with 0.6 GB of
memory, enough for one person's job search and not for anything more.

The bucket is named after the project so it is globally unique, and uses uniform
bucket-level access, which means one IAM policy for the whole bucket instead of per-object
ACLs. It is not public; the app reads and writes it as the service account.

```
gcloud storage buckets create gs://cv-applier-uploads-PROJECT_ID \
  --location=europe-west1 \
  --uniform-bucket-level-access

gcloud storage buckets add-iam-policy-binding gs://cv-applier-uploads-PROJECT_ID \
  --member="serviceAccount:cv-applier-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

That is the fourth role from phase 4, granted here because it is scoped to the bucket
rather than to the project.

Two secrets go into Secret Manager. Cloud Run injects them as environment variables in
phase 13, so the application keeps reading plain `os.environ` and never imports a Secret
Manager client.

```
printf '%s' "$JWT_SECRET" | gcloud secrets create jwt-secret --data-file=-
printf '%s' "$GOOGLE_CLIENT_SECRET" | gcloud secrets create google-client-secret --data-file=-
```

Finally, run the migration against Cloud SQL through the proxy. In one terminal:

```
gcloud sql instances describe cv-applier-db --format='value(connectionName)'
./cloud-sql-proxy PROJECT_ID:europe-west1:cv-applier-db --port 5433
```

In another, with the proxy still running:

```
cd backend
DATABASE_URL="postgresql+psycopg://cv:DB_PASSWORD@127.0.0.1:5433/cv_applier" alembic upgrade head
```

**Verify** -

```
gcloud sql instances list
gcloud storage ls gs://cv-applier-uploads-PROJECT_ID
gcloud secrets list
psql "postgresql://cv:DB_PASSWORD@127.0.0.1:5433/cv_applier" -c "\dt"
```

**Done when** - the instance is `RUNNABLE`, both secrets are listed, and `\dt` through the
proxy shows the same tables the compose stack has.

If you stop work for a while, `gcloud sql instances patch cv-applier-db --activation-policy=NEVER`
stops the instance and with it the compute charge. Storage is still billed on a stopped
instance, so the bill drops to roughly $1.70 a month rather than to zero.

Effort: 2 hours.

---

## Phase 13. First deploy

**Goal** - the real application on a public URL, signing you in with Google.

**Files** - extend `docs/cloud.md`.

Create the image repository and build into it. Tag with the commit sha, never `latest`;
phase 15 explains why.

```
gcloud artifacts repositories create cv-applier \
  --repository-format=docker \
  --location=europe-west1 \
  --description="CV Applier images"

gcloud auth configure-docker europe-west1-docker.pkg.dev

TAG=$(git rev-parse --short HEAD)
docker build -t europe-west1-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG backend
docker push europe-west1-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG
```

Deploy. The service runs as the phase 4 service account, mounts the Cloud SQL socket,
takes its configuration as environment variables and its two secrets from Secret Manager.

```
gcloud run deploy cv-applier \
  --image=europe-west1-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG \
  --region=europe-west1 \
  --service-account=cv-applier-run@PROJECT_ID.iam.gserviceaccount.com \
  --add-cloudsql-instances=PROJECT_ID:europe-west1:cv-applier-db \
  --min-instances=0 --max-instances=3 \
  --allow-unauthenticated \
  --set-env-vars="DATABASE_URL=postgresql+psycopg://cv:DB_PASSWORD@/cv_applier?host=/cloudsql/PROJECT_ID:europe-west1:cv-applier-db,GOOGLE_CLOUD_PROJECT=PROJECT_ID,GCS_BUCKET=cv-applier-uploads-PROJECT_ID,VERTEX_LOCATION=global,VERTEX_MODEL=gemini-3.1-flash-lite,COOKIE_SECURE=true,GOOGLE_CLIENT_ID=YOUR_CLIENT_ID" \
  --set-secrets="JWT_SECRET=jwt-secret:latest,GOOGLE_CLIENT_SECRET=google-client-secret:latest"
```

`--allow-unauthenticated` lets the public reach the service; the application still does
its own session-cookie auth, and Google sign-in is what actually gates it. The database
password rides in `DATABASE_URL` rather than in Secret Manager; if that stops feeling
acceptable, move the whole URL into a secret the same way as the other two.

The service URL is only known after the first deploy, and two settings depend on it, so
read it back and update:

```
SERVICE_URL=$(gcloud run services describe cv-applier --region=europe-west1 --format='value(status.url)')

gcloud run services update cv-applier --region=europe-west1 \
  --update-env-vars="FRONTEND_ORIGIN=$SERVICE_URL,GOOGLE_REDIRECT_URI=$SERVICE_URL/api/auth/google/callback"
```

Then, in the console, add `$SERVICE_URL/api/auth/google/callback` as a second authorised
redirect URI on the OAuth client from the prerequisites. Keep the localhost one: the same
client serves both environments.

Four production gotchas, each of which produces a failure that does not point at its own
cause:

- Cloud Run injects `PORT` and the container must bind `0.0.0.0:$PORT`. A container that
  hardcodes 8000 fails its health check with an error that never mentions ports. The
  phase 5 Dockerfile already handles this.
- Cloud Run terminates TLS and forwards the original scheme in `X-Forwarded-Proto`.
  Without `--proxy-headers --forwarded-allow-ips="*"`, Uvicorn builds the OAuth redirect
  URI as `http://` and Google rejects it as a mismatch.
- The session cookie needs `Secure=true` here and `false` on `http://localhost`, which is
  exactly what `COOKIE_SECURE` is for. Set wrongly, sign-in appears to succeed and then
  every subsequent request is a 401.
- Schema changes are applied by Alembic through the proxy, as in phase 12. Never put
  `create_all` back on startup: with `--max-instances=3`, several instances can cold start
  at once and race each other creating the same tables.

**Verify** - open `$SERVICE_URL/api/health`, then `$SERVICE_URL/api/auth/google/login` in a
browser and complete a real Google sign-in. Logs are at
`gcloud run services logs read cv-applier --region=europe-west1 --limit=50`.

**Done when** - sign-in against the live URL ends on the app with a session cookie, and
`/api/auth/me` returns your email over HTTPS.

Effort: 2 hours, most of it the redirect URI and the cookie flags.

---

## Phase 14. Scheduled refresh

**Goal** - job sources refreshed nightly without anyone clicking anything.

**Files** - `backend/app/refresh.py`, extend `docs/cloud.md`.

`refresh.py` is a module entrypoint that calls the same source-registry code the
`POST /api/jobs/refresh` route calls, then exits. It runs as a Cloud Run job sharing the
image built in phase 13, with a different command.

This is a job rather than a route on the public service for three reasons. The refresh
takes minutes and Cloud Run requests have a request timeout and are billed for their whole
duration; the work is privileged and belongs to nobody's session; and a public endpoint
that triggers expensive work would need its own authentication on top of the user session
that it does not have.

```
gcloud run jobs create cv-applier-refresh \
  --image=europe-west1-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG \
  --region=europe-west1 \
  --service-account=cv-applier-run@PROJECT_ID.iam.gserviceaccount.com \
  --set-cloudsql-instances=PROJECT_ID:europe-west1:cv-applier-db \
  --command=python --args=-m,app.refresh \
  --task-timeout=30m --max-retries=1 \
  --set-env-vars="DATABASE_URL=postgresql+psycopg://cv:DB_PASSWORD@/cv_applier?host=/cloudsql/PROJECT_ID:europe-west1:cv-applier-db,GOOGLE_CLOUD_PROJECT=PROJECT_ID,GCS_BUCKET=cv-applier-uploads-PROJECT_ID,VERTEX_LOCATION=global,VERTEX_MODEL=gemini-3.1-flash-lite"
```

Run it once by hand before scheduling it:

```
gcloud run jobs execute cv-applier-refresh --region=europe-west1 --wait
```

The scheduler calls the Cloud Run Admin API as the same runtime service account, which
therefore needs permission to invoke this one job. That binding is on the job, not on the
project.

```
gcloud run jobs add-iam-policy-binding cv-applier-refresh \
  --region=europe-west1 \
  --member="serviceAccount:cv-applier-run@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud scheduler jobs create http cv-applier-nightly \
  --location=europe-west1 \
  --schedule="0 5 * * *" \
  --time-zone="Europe/Bucharest" \
  --uri="https://run.googleapis.com/v2/projects/PROJECT_ID/locations/europe-west1/jobs/cv-applier-refresh:run" \
  --http-method=POST \
  --oauth-service-account-email="cv-applier-run@PROJECT_ID.iam.gserviceaccount.com"
```

**Verify** - `gcloud scheduler jobs run cv-applier-nightly --location=europe-west1`, then
`gcloud run jobs executions list --job=cv-applier-refresh --region=europe-west1`

**Done when** - the forced run shows a succeeded execution, and the next morning the job
count is higher than it was the night before.

Effort: 1 hour.

---

## Phase 15. Deploy on push

**Goal** - a push to `main` ends up serving traffic without a laptop in the loop.

**Files** - `cloudbuild.yaml`, `cleanup-policy.json`, extend `docs/cloud.md`.

```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-t", "europe-west1-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA", "backend"]
  - name: gcr.io/cloud-builders/docker
    args: ["push", "europe-west1-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA"]
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - deploy
      - cv-applier
      - --image=europe-west1-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA
      - --region=europe-west1
options:
  logging: CLOUD_LOGGING_ONLY
```

The trigger connects the repository to that file. Connecting the GitHub repository is a
one-time console step under Cloud Build, Repositories.

```
gcloud builds triggers create github \
  --name=cv-applier-main \
  --region=europe-west1 \
  --repo-owner=GITHUB_OWNER \
  --repo-name=GITHUB_REPO \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
```

The build's own service account needs to deploy and to act as the runtime account:

```
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/run.developer"

gcloud iam service-accounts add-iam-policy-binding \
  cv-applier-run@PROJECT_ID.iam.gserviceaccount.com \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

Images are tagged `$SHORT_SHA` rather than `latest` because `latest` destroys the link
between a running revision and the code inside it. Two deploys of `:latest` look identical
in the console while running different code, a rollback has no earlier tag to go back to,
and the tag silently moves under a revision that has already started. With a sha tag,
every Cloud Run revision names the commit it came from.

Artifact Registry is free only up to 0.5 GB and this image is roughly 200 MB, so a handful
of builds fills it. Keep the recent few and let the rest expire:

```json
[
  {
    "name": "keep-recent",
    "action": {"type": "Keep"},
    "mostRecentVersions": {"keepCount": 2}
  },
  {
    "name": "delete-old",
    "action": {"type": "Delete"},
    "condition": {"olderThan": "30d"}
  }
]
```

```
gcloud artifacts repositories set-cleanup-policies cv-applier \
  --location=europe-west1 \
  --policy=cleanup-policy.json
```

**Verify** - push a trivial change to `main`, watch
`gcloud builds list --region=europe-west1 --limit=5`, then confirm the new revision:
`gcloud run revisions list --service=cv-applier --region=europe-west1`

**Done when** - the push produced a green build and a new revision whose image tag is that
commit's sha, and `gcloud artifacts docker images list europe-west1-docker.pkg.dev/PROJECT_ID/cv-applier/backend`
holds no more than two images, which is what keeps the repository inside the free 0.5 GB.

Effort: 1.5 hours.

---

# Part 3 - Frontend

## Phase 16. Shell and sign-in

**Files** - Vite scaffold in `frontend/`, `src/api.ts`, `src/pages/SignIn.tsx`,
router with a protected-route wrapper, edit `backend/Dockerfile`.

Details: Vite proxy for `/api` to port 8000 so cookies are same-origin in development.
`api.ts` is a thin `fetch` wrapper with `credentials: "include"` that redirects to sign-in
on a 401. The sign-in page is one button linking to `/api/auth/google/login`.

This phase also turns `backend/Dockerfile` into a multi-stage build. The first stage runs
`npm ci && npm run build` on `frontend/`, and the final Python stage copies the compiled
assets in and serves them from the backend:

```dockerfile
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app app
COPY --from=frontend /frontend/dist static
ENV PORT=8000
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} \
    --proxy-headers --forwarded-allow-ips="*"
```

The build context becomes the repository root, so the `docker build` and `cloudbuild.yaml`
paths from phases 13 and 15 change from `backend` to `.` accordingly.

One image serving both halves makes production single-origin: the API and the UI share a
scheme and host, so there is no CORS preflight to configure and the session cookie is
first-party rather than a third-party cookie that browsers are steadily restricting.
Development keeps the Vite proxy, which produces the same single-origin effect through a
different mechanism.

**Verify** - `npm run dev`, click through Google, land back in the app authenticated.

**Done when** - a reload keeps you signed in and logout clears it, and the deployed image
serves the built UI at `$SERVICE_URL/`.

Effort: 3 hours including Tailwind, TanStack Query and the multi-stage build.

---

## Phase 17. Profile screen

**Files** - `src/pages/Profile.tsx`, upload component, preferences form.

Details: drag-and-drop or file picker limited to `.pdf` and `.docx`, a parsing spinner
(the model call takes a few seconds), then editable chips for skills and titles and plain
inputs for the preferences. Save issues the `PATCH`.

**Done when** - you can fix a wrongly extracted skill and see it persist across reload.

Effort: 3 hours.

---

## Phase 18. Matches screen

**Files** - `src/pages/Matches.tsx`, match card component.

Details: a "Refresh jobs" button that calls the refresh endpoint and shows progress, then
ranked cards with score, reason, company, location, posted date, a link to the original
posting, and two actions: save to applications, or dismiss. Filter controls for remote
only and minimum score.

**Done when** - refreshing brings in new eJobs listings and saving one creates a row in
the tracker.

Effort: 3 hours.

---

## Phase 19. Tracker screen

**Files** - `src/pages/Applications.tsx`, status badge, letter editor drawer.

Details: table grouped by status with counts, a drawer to read and edit the cover letter
with a copy button, a notes field, and the status control. The apply link and the
"I submitted this" confirmation sit next to each other, since that pairing is the actual
workflow.

**Done when** - you can take one job from match to submitted and later mark it as an
interview.

Effort: 3 hours.

---

## Phase 20. Polish

**Files** - across both apps, plus `README.md`.

Details: empty states that explain the next action, error toasts, loading skeletons, and
a README covering setup, the Google OAuth steps and how to run both halves. Re-read the
diff against [.cursor/rules/coding-style.mdc](.cursor/rules/coding-style.mdc) and strip
any comment that restates its code.

Effort: 2 hours.

---

# Part 4 - Operating it

## Phase 21. Observability and cost hygiene

**Goal** - see what the deployed app is doing, see what it costs, and know how to switch
it all off.

**Files** - `backend/app/logging.py`, edit `backend/app/main.py`, extend `docs/cloud.md`.

Log one JSON object per line on stdout. Cloud Logging reads stdout from Cloud Run and, when
a line parses as JSON, lifts its keys into `jsonPayload` where they become queryable
fields; a plain text line is one opaque string you can only match with a substring search.
`severity` and `message` are the two keys Cloud Logging treats specially.

```python
class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"severity": record.levelname, "message": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload)
```

Log the events worth asking questions about later: a refresh finishing with its per-source
counts, a CV parsed with its token usage, a letter drafted with the job id.

One query worth keeping, in the Logs Explorer or through the CLI:

```
gcloud logging read '
resource.type="cloud_run_revision"
resource.labels.service_name="cv-applier"
jsonPayload.event="jobs_refreshed"
' --limit=20 --format="table(timestamp, jsonPayload.source, jsonPayload.count)"
```

Then look at the money. The billing console's Credits page shows the trial credit
burning down and how many of the 90 days remain; the Reports page broken down by service
should show Cloud SQL as nearly the whole bill and everything else near zero. Check the
phase 4 budget is still attached with `gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID`.

| Service | Cost to us | Why |
| --- | --- | --- |
| Cloud Run | $0 | Free tier covers 2M requests, 180k vCPU-seconds and 360k GiB-seconds a month. Scale to zero means an idle app costs nothing. |
| Cloud SQL `db-f1-micro` + 10 GB SSD | about $10 a month | $0.0105 an hour for the instance plus about $1.70 a month for storage. No free tier. This is the only meaningful running cost. |
| Cloud Storage | under $0.10 a month | The 5 GB free tier is US-only, so `europe-west1` bills from the first byte at about $0.02 per GB-month. |
| Vertex AI, `gemini-3.1-flash-lite` | about $0.005 per cover letter | $0.25 per million input tokens, $1.50 per million output tokens. |
| Artifact Registry | $0 | 0.5 GB free. A slim image is around 200 MB, so keep at most two tags. |
| Secret Manager | $0 | 6 active secret versions and 10,000 access operations free per month. |
| Cloud Build | $0 | 2,500 build-minutes free per month. |
| Cloud Scheduler | $0 | 3 jobs free per month. |
| Cloud Logging | $0 | First 50 GiB per project per month. |

Roughly $12 a month, so about $36 across the 90-day credit window, leaving the large
majority of the $300 unspent.

### Teardown checklist

Every chargeable thing phases 4 to 15 created, in dependency order. Deleting the project
removes all of it at once, but the itemised list is what you need when you want to keep
the project and stop the bill.

| Resource | Command |
| --- | --- |
| Scheduler job `cv-applier-nightly` | `gcloud scheduler jobs delete cv-applier-nightly --location=europe-west1` |
| Build trigger `cv-applier-main` | `gcloud builds triggers delete cv-applier-main --region=europe-west1` |
| Cloud Run job `cv-applier-refresh` | `gcloud run jobs delete cv-applier-refresh --region=europe-west1` |
| Cloud Run service `cv-applier` | `gcloud run services delete cv-applier --region=europe-west1` |
| Artifact Registry repo `cv-applier` | `gcloud artifacts repositories delete cv-applier --location=europe-west1` |
| Cloud SQL instance `cv-applier-db` | `gcloud sql instances delete cv-applier-db` |
| Bucket `cv-applier-uploads-PROJECT_ID` | `gcloud storage rm --recursive gs://cv-applier-uploads-PROJECT_ID` |
| Secrets | `gcloud secrets delete jwt-secret` and `gcloud secrets delete google-client-secret` |
| Service account `cv-applier-run` | `gcloud iam service-accounts delete cv-applier-run@PROJECT_ID.iam.gserviceaccount.com` |
| Budget | `gcloud billing budgets delete BUDGET_ID --billing-account=BILLING_ACCOUNT_ID` |
| Everything, including the project | `gcloud projects delete PROJECT_ID` |

Of these, only Cloud SQL and Cloud Storage cost anything while idle. If you want the data
kept and the bill mostly gone, stop the instance rather than deleting it, as in phase 12.

When the trial ends the billing account closes rather than charging a card, so the
failure mode of forgetting all this is that the app stops, not that you get a bill.

**Verify** - `gcloud logging read` returns structured rows with your own field names, and
the billing report for the last seven days matches the table above.

**Done when** - the query works, the burn-down is roughly on the predicted line, and the
teardown checklist is written into `docs/cloud.md`.

Effort: 2 hours.

---

## Documentation deliverables

Each phase ships its doc in the same change as its code, per the docs rule. Written for an
agent with no prior context: what the subsystem does, where it lives, the contract it
exposes, and the constraints the code cannot show.

- Phase 1: `AGENTS.md` at the root - stack, how to run both halves, index into `docs/`.
- Phase 3: `docs/auth.md` - the OAuth flow, why no Google tokens are stored, the verified
  email rule for account linking, and how to add a second provider.
- Phases 4 and 5: `docs/cloud.md` - the GCP project layout, what runs where, the local
  compose stack and how it mirrors production, the credentials model.
- Phase 6: `docs/profile.md` - CV parsing path, the extraction contract, where the
  uploaded file is stored.
- Phases 6 and 11: `docs/llm.md` - the two Vertex AI prompts, the model choice, the
  language rule, and why Vertex AI rather than AI Studio.
- Phases 7 and 8: `docs/sources.md` - the `JobSource` contract, one section per adapter,
  the politeness rules, and the Romania coverage finding from phase 8.
- Phase 9: `docs/matching.md` - the scoring formula, the hard filters, the bilingual
  normalisation.
- Phases 12 to 15: extend `docs/cloud.md` - the deployment topology, the service account
  roles, and the deploy command.
- Phase 16: `docs/frontend.md` - routing, the API wrapper, the auth redirect behaviour.
- Phase 21: extend `docs/cloud.md` - the cost model and the teardown checklist.

## Parallel work and subagents

Per the feature workflow rule, the lead fixes the contracts first, then splits. Four
points in this plan split cleanly:

- Phase 4 is console and CLI work that touches no application code, so it can run
  alongside phase 5 once the environment variable names are fixed. Contract to fix first:
  the `.env` block in the prerequisites.
- Phases 7 and 8 are one workstream (job sources) that is independent of phases 3 and 6
  (auth and profile). Contract to fix first: the `Posting` dataclass and `JobSource`
  protocol in `backend/app/sources/base.py`.
- Phases 17, 18 and 19 are three independent screens once the API exists. Contract to fix
  first: the response shapes in `src/api.ts` and the shared components each screen may
  use. Each subagent owns its own page file and nothing else.
- Phase 20 polish is not parallelisable and stays with the lead.

Everything else is sequential because each phase consumes the previous one's output. The
cloud phases in particular are strictly ordered: each one creates the resource the next
one refers to by name.

## Totals and sequencing

Part 1 is roughly 18 hours, part 2 roughly 6, part 3 roughly 14, part 4 roughly 2, so
about 40 hours in total.

The first moment the project is genuinely useful is the end of phase 11, when you can get
a ranked list and a drafted letter through `/docs` without any UI, and without a cloud
bill. The first moment it is useful from a phone is the end of phase 13.

Phases 4 and 5 look like a detour from the feature work, and they are what makes phases 12
to 15 short: by the time anything is deployed, the container, the database engine and the
storage client have all already been proven locally.

## Deferred, with triggers

- BestJobs adapter - when phase 8 shows ATS contributes little for Romania.
- JSearch key - when you want LinkedIn and Indeed listings in the results.
- Playwright auto-fill for ATS forms - after the tracker proves the workflow.
- Cloud SQL backups and a second environment - when losing the data would actually matter.
