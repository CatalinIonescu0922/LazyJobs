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

Everything lives in `europe-west3` (Frankfurt), except Vertex AI, which uses the `global`
endpoint.

---

## Prerequisites

Install the `gcloud` CLI, Terraform, Docker with Compose, Python 3.12 and Node 20. A
Google Cloud billing account with the $300 / 90-day free trial credit is assumed.

From phase 4 on, the two CLIs have different jobs and the split is deliberate: Terraform
declares anything that should still exist tomorrow - APIs enabled, service accounts,
databases, buckets, the Cloud Run service itself - and `gcloud` is left for one-off
operations (running a migration through a proxy, pushing an image, executing a job by
hand) and the couple of things Terraform genuinely cannot do for itself. A resource that
appears in a `.tf` file and a resource that appears as a `gcloud` command in this
document are different categories on purpose, not an inconsistency.

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
everything bills and audits in one place. Phase 6 is the first phase that needs steps 1 to
5 finished, because it is the first time a login runs in a browser; an empty
`GOOGLE_CLIENT_ID` was fine until then.

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
  S5 --> S6[Phase 6 Frontend shell and sign-in]
  S6 --> S7[Phase 7 CV and profile]
  S7 --> S8[Phase 8 Job sources and crawler]
  S8 --> S9[Phase 9 LLM extraction tier and coverage]
  S7 --> S10[Phase 10 Matching]
  S9 --> S10
  S10 --> S11[Phase 11 Applications, letters, tracker]
  S11 --> S12[Phase 12 Data plane]
  S12 --> S13[Phase 13 First deploy]
  S13 --> S14[Phase 14 Scheduled refresh]
  S13 --> S15[Phase 15 Deploy on push]
  S13 --> S16[Phase 16 Serve the UI from the image]
  S16 --> S17[Phase 17 Polish]
  S15 --> S18[Phase 18 Observability]
  S9 --> S19[Phase 19 Browser rendering]
  S9 --> S20[Phase 20 Employers and ATS feeds]
```

Phases 19 and 20 block nothing. They need only the crawler from phases 8 and 9, so they
can be done any time after phase 9. The coverage table from that phase says which is
worth doing first, and whether phase 19 has a real board to test against at all.

Every feature phase from 6 to 11 ships its screen together with its API, so each ends with
something to click. Phase 8 needs the profile's country for board discovery, which is why
it follows phase 7.

Nothing is deployed until phase 13, and nothing costs money until phase 12. That ordering
is deliberate: the whole application is proven against the compose stack from phase 5
first, so the credit is spent on a system that already works.

---

# Part 1 - Backend and frontend, running locally

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
identity, and working credentials on your laptop, all of it defined in Terraform except
the one step Terraform cannot do for itself. Nothing chargeable is created here.

**Files** - `infra/bootstrap/main.tf`, `infra/bootstrap/variables.tf`,
`infra/bootstrap/outputs.tf`, `infra/main/main.tf`, `infra/main/variables.tf`, edit
`.gitignore` (add `infra/**/.terraform/`, `infra/**/*.tfstate*`,
`infra/**/terraform.tfvars`), `docs/cloud.md`, edit `backend/requirements.txt` (add
`google-genai`), edit `backend/.env.example`.

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

That is the only hand-run infrastructure step in this whole project. Terraform's own
provider needs a quota project attached to your credentials before it can call any
Google API, and before a project exists there is nothing to attach it to - the same
requirement `gcloud auth application-default set-quota-project` satisfies further down
for the application's own credentials. Everything from here is Terraform, in two root
modules that never share a state file.

### `infra/bootstrap/`

Runs first, because it creates the bucket that will hold every module's state, including
its own. Until that bucket exists, its state has nowhere to live but your laptop.

`infra/bootstrap/main.tf`:

```hcl
terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.44"
    }
  }
}

provider "google" {
  project               = var.project_id
  region                = "europe-west3"
  billing_project       = var.project_id
  user_project_override = true
}

resource "google_project_service" "bootstrap_apis" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "billingbudgets.googleapis.com",
    "storage.googleapis.com",
  ])
  service = each.value
}

resource "google_storage_bucket" "tfstate" {
  name                        = "cv-applier-tfstate-${var.project_id}"
  location                    = "europe-west3"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  depends_on                  = [google_project_service.bootstrap_apis]
}

resource "google_billing_budget" "guardrail" {
  billing_account = var.billing_account_id
  display_name    = "cv-applier"
  amount {
    specified_amount {
      currency_code = "USD"
      units         = "50"
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }
  depends_on = [google_project_service.bootstrap_apis]
}
```

`billing_project` and `user_project_override` on the provider block exist for exactly one
resource above: `google_billing_budget` calls the Billing Budgets API under your own ADC
user credentials, and returns a 403 without a quota project attached. `variables.tf`
declares `project_id` and `billing_account_id` with no defaults; put real values in a
gitignored `infra/bootstrap/terraform.tfvars` rather than typing them on every command.
`outputs.tf` exposes the bucket name for later reference:

```hcl
output "tfstate_bucket" {
  value = google_storage_bucket.tfstate.name
}
```

Apply with local state, because the backend bucket does not exist yet:

```
cd infra/bootstrap
terraform init
terraform apply
```

Then close the loop: point bootstrap's own state at the bucket it just created, so it
stops living only on your laptop. Add to `infra/bootstrap/main.tf`:

```hcl
terraform {
  backend "gcs" {
    bucket = "cv-applier-tfstate-PROJECT_ID"
    prefix = "bootstrap"
  }
}
```

```
terraform init -migrate-state
```

Confirm "yes" when prompted. Only bootstrap ever does this local-then-migrate dance,
because only bootstrap has the chicken-and-egg problem; `infra/main/` uses the same
bucket under a different prefix and has remote state from its very first `init`.

### `infra/main/`

`infra/main/main.tf` handles the remaining APIs and the runtime identity:

```hcl
terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.44"
    }
  }
  backend "gcs" {
    bucket = "cv-applier-tfstate-PROJECT_ID"
    prefix = "main"
  }
}

provider "google" {
  project = var.project_id
  region  = "europe-west3"
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
  ])
  service = each.value
}

resource "google_service_account" "runtime" {
  account_id   = "cv-applier-run"
  display_name = "CV Applier runtime"
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/aiplatform.user",
    "roles/secretmanager.secretAccessor",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
```

`storage.googleapis.com` is deliberately missing from that list: bootstrap already
turned it on for the state bucket, and `main` reuses it for the uploads bucket in phase
12 without re-declaring it. An API is enabled by exactly one module - if both declared
it, neither would fully own it, and a `terraform destroy` on one could disable an API the
other still needs.

The fourth role, `roles/storage.objectAdmin`, is granted in phase 12 on the uploads
bucket resource itself rather than here, so it stays scoped to that bucket and not to
the whole project.

```
cd ../main
terraform init
terraform apply
```

Set up Application Default Credentials so local code, including Terraform itself,
authenticates as you, with no key file anywhere on disk. On Cloud Run the same code picks
up the attached service account instead, which is why no service-account JSON key is
ever downloaded in this project.

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

Then confirm what Terraform is actually tracking, rather than trusting memory of what ran:

```
gcloud storage ls gs://cv-applier-tfstate-PROJECT_ID/bootstrap/ gs://cv-applier-tfstate-PROJECT_ID/main/
(cd infra/bootstrap && terraform state list)
(cd infra/main && terraform state list)
```

**Done when** - the Vertex script prints text rather than a permission or billing error,
both state files live in the bucket rather than on disk, `gcloud billing budgets list
--billing-account=BILLING_ACCOUNT_ID` shows the $50 budget with three thresholds, and the
project contains no Cloud SQL instance and no uploads bucket.

Three things that confuse everyone once: the trial credit pays for Vertex AI but **not**
for the Gemini API in Google AI Studio - same models, different products, different
billing; the console now calls Vertex AI the "Gemini Enterprise Agent Platform" while the
docs and everyone else still say Vertex AI; and `google_billing_budget` fails with a bare
403 under personal ADC credentials unless the provider block above carries
`billing_project` and `user_project_override = true` - easy to forget, since none of the
other resources in this phase need it.

Effort: 1.5 hours, the extra half hour being the state-bucket migration the first time
you see it.

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

## Phase 6. Frontend shell and sign-in

**Goal** - a browser UI you can sign in through, so every later phase is checked by
clicking and not only through `/docs` and `curl`.

**Files** - Vite scaffold in `frontend/`, `src/api.ts`, `src/pages/SignIn.tsx`,
`src/pages/Home.tsx`, a router with a protected-route wrapper, `docs/frontend.md`.

Details: Vite with React, TypeScript, Tailwind, TanStack Query and React Router, with a
proxy for `/api` to port 8000 so cookies are same-origin in development. `api.ts` is a thin
`fetch` wrapper with `credentials: "include"` that redirects to sign-in on a 401. The
sign-in page is one button linking to `/api/auth/google/login`. `Home` shows the signed-in
name and avatar from `GET /api/auth/me` with a sign-out button, and is the navigation frame
that each later phase adds a page to.

The frontend runs on the host with `npm run dev`, next to the compose stack, and is not a
fourth compose service. It needs hot reload and nothing else; phase 16 builds it into the
production image.

This is the first time a real Google login runs end to end. Phases 3 and 5 only exercised
the pieces, because `GOOGLE_CLIENT_ID` has never been set. Do the OAuth client steps from
Prerequisites before this phase, not during it.

**Verify** - `docker compose up`, `npm run dev`, open `http://localhost:5173`, click
Continue with Google, and land on Home showing your own name.

**Done when** - a reload keeps you signed in, sign-out returns you to the sign-in page, and
visiting a protected page while signed out redirects to sign-in.

Effort: 2 hours.

---

## Phase 7. CV upload and profile

**Goal** - upload a real CV in the browser and get an editable structured profile.

**Files** - backend: `backend/app/cv.py`, `backend/app/storage.py`, `backend/app/llm.py`
(profile extraction), `backend/app/routers/profile.py`, `backend/app/schemas.py`, an Alembic
revision adding `profiles.country`, `profiles.city` and `profiles.salary_currency`, edit `backend/requirements.txt` (add
`google-cloud-storage`, drop `openai`), edit `backend/app/config.py` and
`backend/.env.example` to drop the OpenAI settings. Frontend: `src/pages/Profile.tsx`, an
upload component and a preferences form. Docs: `docs/profile.md`, and start `docs/llm.md`.

Details: `cv.py` dispatches on file extension, `pdfplumber` for PDF and `python-docx` for
DOCX, returning plain text; reject anything else with a 400. `storage.py` writes the
uploaded file to the bucket in `GCS_BUCKET` with the `google-cloud-storage` client;
locally that client talks to the emulator because `STORAGE_EMULATOR_HOST` is set, and in
production the variable is unset and the same code reaches Cloud Storage. `llm.py` sends
the text with a JSON-schema-shaped prompt to Vertex AI and parses the response into
profile fields, including `country` as an ISO alpha-2 code and `city`, both read from the
address on the CV (empty when there is none). Phase 8 uses the country to decide which job
boards to look for, and phase 20 uses the city to find employers:

```python
from google import genai

client = genai.Client(vertexai=True, project=settings.google_cloud_project, location=settings.vertex_location)
response = client.models.generate_content(model=settings.vertex_model, contents=prompt)
```

There is no keyword-extraction fallback. Credentials come from the cloud project - your
own ADC locally, the attached service account in production - so "no key configured" is
not a state this app can be in, and a fallback path nobody exercises is a liability.

`PATCH /api/profile` accepts corrections to every extracted field plus the search
preferences. `country` must match `^[A-Z]{2}$`. `min_salary` is a monthly amount in   
`salary_currency`, an ISO 4217 code, and the salary filter in phase 10 stays off while the
currency is empty.

Guard rails worth having: cap upload size at about 5 MB, and truncate CV text before the
model call so a 40 page CV cannot blow the context window.

The Profile screen: a drag-and-drop area or file picker limited to `.pdf` and `.docx`, a
parsing spinner (the model call takes a few seconds), then editable chips for skills and
titles, a country select, a city input, and plain inputs for the preferences, with a currency select
beside the minimum salary. The country select is built from the browser's
`Intl.DisplayNames` and the currency select from `Intl.supportedValuesOf("currency")`, so
there is no list to maintain. Save issues the `PATCH`.

**Verify** - in the browser, upload your own CV as a PDF and again as a DOCX, and read what
comes back. Fix a wrong skill, save, and reload. Then confirm the object landed:
`curl http://localhost:4443/storage/v1/b/$GCS_BUCKET/o`

**Done when** - skills, titles and country come back recognisably correct, a correction
survives a reload, and the uploaded file is listed in the emulator bucket.

Effort: 5.5 hours.

---

## Phase 8. Job sources and the generic crawler

**Goal** - real postings from job boards found for your country, read by one crawler with no
per-site code, and a screen that shows what it found.

**Files** - backend: `backend/app/sources/posting.py`, `fetch.py`, `discover.py`,
`extract.py` (the JSON-LD tier only), `crawl.py`, `backend/app/textnorm.py`, extend
`backend/app/llm.py`, `backend/app/routers/sources.py`, `backend/app/schemas.py`, an
Alembic revision, edit `backend/requirements.txt` (add `beautifulsoup4` and `pycountry`),
and unit tests for `fetch.py`, `extract.py` and `textnorm.py`. Frontend:
`src/pages/Sources.tsx`. Docs: `docs/sources.md`.

The design is in [PLAN.md](PLAN.md) section 7, including the validation steps and the rules
the crawler never breaks. What each module owns:

- `posting.py` - the `Posting` dataclass.
- `fetch.py` - the one HTTP client everything uses: `robots.txt` read per host, one
  request per second per host, the address guard applied to every request and every
  redirect hop, `https` only, size limits, an identifying User-Agent. Redirects are
  followed by hand so each hop is checked against the address guard and the `robots.txt`
  of its own host, and a hop to any host other than the source's own or its `www.`
  counterpart is refused.
- `discover.py` - `propose` (the discovery prompt for the profile's country) and
  `validate` (the five steps in section 7).
- `extract.py` - find the `JobPosting` node leniently, map it to a `Posting`, strip
  descriptions to plain text, normalise country names to ISO alpha-2 with `pycountry`,
  turn `baseSalary` into a monthly range from its `unitText`, and detect remote.
- `textnorm.py` - one `normalise` function (lowercase, strip diacritics and punctuation,
  drop legal suffixes such as `SRL`, `SA`, `Ltd` and `GmbH`) and `fingerprint(company,
  title, city)` built on it. Phase 10 reuses `normalise` for hidden companies and matching.
- `crawl.py` - `refresh_source`: read the chosen sitemaps, order newest first, drop URLs
  already in `jobs`, take up to 100, extract, upsert on `(source, external_id)` with the
  fingerprint, setting `first_seen_at` on insert only.
- `llm.py` gains `propose_job_boards(country)` and `pick_posting_sitemaps(samples)`.

The Alembic revision creates `job_sources`, widens `jobs.source` to 255 and
`jobs.external_id` to 1024, and adds to `jobs`: `eligible_countries`, `expires_at`,
`salary_min`, `salary_max`, `salary_currency`, `fingerprint` (indexed) and `first_seen_at`.

Three pieces have sharp edges and are worth unit tests, built from saved real pages and
not from invented ones. The address guard must refuse loopback, private and link-local
addresses, `169.254.169.254` in particular, and an `https` redirect that lands on one.
The JSON-LD mapper must read a posting wrapped in `@graph`, one with raw control characters
inside strings (We Work Remotely has them), one with `applicantLocationRequirements`, and
one with a yearly and one with an hourly `baseSalary`. The fingerprint must give the same
value for one job on two boards and for a title with and without a "(m/f)" marker, and a
different value for the same title in another city. Everything else is verified against
live boards.

The Job boards screen: a table of boards with kind, status and its reason in plain words,
extraction tier, posting count and last refresh; a "Find boards for `<country>`" button; an
add-a-domain input; an on and off switch; and a Refresh button per row, plus "Refresh all",
which runs the rows one after another and shows which one is running.

**Verify** - with a country set on the profile, open Job boards and click Find boards.
About twenty candidates appear. Refresh them one by one. Expect eJobs, HiPo, Remotive,
RemoteOK and We Work Remotely to become `active` on the `jsonld` tier, and the boards that
refused the earlier probe, Indeed and Jooble among them, to end `failed` with a reason in
plain words. LinkedIn is the one to watch: its bare domain answers differently from `www`,
so it tests the per-host `robots.txt` rule, and it must not end `active`. Then
`docker compose exec db psql -U cv -d cv_applier -c "select source, count(*) from jobs group by source"`
and `... -c "select company, title, locations, eligible_countries from jobs limit 10"`
and, for duplicates,
`... -c "select fingerprint, count(*), array_agg(distinct source) from jobs group by fingerprint having count(*) > 1 limit 10"`

**Done when** - ten real listings with company, location and description from at least
three different boards, a remote posting carrying its `eligible_countries`, every row
carrying a fingerprint and a `first_seen_at`, a failed board showing why, and the unit
tests pass.

Effort: 6.5 hours. This is the phase most likely to need iteration, and the iteration is on
the validation step, not on parsing.

---

## Phase 9. LLM extraction tier and coverage check

**Goal** - boards with no structured data become readable too, and there is an honest
number for how much of your market the crawler reaches.

**Files** - extend `backend/app/sources/extract.py`, extend `backend/app/llm.py`, edit
`backend/app/sources/crawl.py` and `discover.py`, extend `src/pages/Sources.tsx`, extend
`docs/sources.md`.

Details: the second extraction tier from [PLAN.md](PLAN.md) section 7. `extract.py` reduces
a page to its visible text plus any embedded JSON payload (BestJobs keeps the posting in
`__NEXT_DATA__`), truncates it, and `llm.py`'s `extract_posting(page_text)` asks Vertex AI
for the `Posting` fields, with the salary as a monthly range when the page states one and
`null` as the answer when the page is not a single posting.
Validation falls through to this tier when the JSON-LD tier fails on its three sample pages.
The cap for this tier is 30 pages per run, because each page costs about a tenth of a cent.

The Sources screen now shows, per board, which tier it runs on and how many postings the
last run added, skipped and failed.

Then the measurement. For every board discovered for your country, record how many
postings it produced and by which tier, which boards failed and why, and how many postings
in total are open to you: located in your country, or remote with `eligible_countries` empty
or containing it. Write the table in this file under this phase. The table decides what
comes next. Boards that failed with `needs a browser` point to phase 19, a thin share of
postings at the companies you care about points to phase 20, and neither is a reason to
write site-specific scrapers.

**Verify** - refresh BestJobs from the Job boards screen and confirm it validates on the
`llm` tier and its postings land in `jobs`. Then
`docker compose exec db psql -U cv -d cv_applier -c "select source, count(*), count(*) filter (where remote) as remote from jobs group by source order by 2 desc"`

**Done when** - at least one board with no JSON-LD yields postings through the LLM tier,
the coverage table is written in this file, and the decision it implies is recorded.

Effort: 2.5 hours including the measurement.

---

## Phase 10. Matching and the Matches screen

**Goal** - ranked matches with a readable reason, shown as cards.

**Files** - backend: `backend/app/matching.py`, `backend/app/routers/matches.py`,
`backend/app/schemas.py`, an Alembic revision adding `profiles.hidden_companies` and
`profiles.keyword_query`, and extend `backend/app/routers/profile.py` to accept both.
Frontend: `src/pages/Matches.tsx`, a match card component, and a hidden-companies list on
`src/pages/Profile.tsx`. Docs: `docs/matching.md`.

Details: normalise text with `textnorm.normalise`, apply the hard filters, collapse
duplicates, then score title overlap, skills overlap, recency and a seniority check into 0
to 100. The rules are in [PLAN.md](PLAN.md) section 9. In short:

- The location filter treats a remote posting as a match only when `eligible_countries` is
  empty or contains the profile's country, which keeps a "remote, US only" role out of a
  Romanian user's list.
- A company in `hidden_companies` is dropped. Names are stored through `normalise`, so
  hiding "ERPA PREMIUM VISION S.R.L." also hides the same company on another board.
- A salary filter applies only when the profile has a `salary_currency`, the posting
  states a salary in that currency, and its top figure is below your minimum. Anything
  else passes.
- The keyword query is a hard filter. Words, quoted phrases, `AND`, `OR`, `NOT` and
  parentheses, with adjacent words meaning `AND`. It runs on the normalised title and
  description, and a one-letter token such as `R` matches only as its own word. An empty
  query matches everything. `GET /api/matches?q=` overrides the saved query for that
  request.
- Postings sharing a `fingerprint` become one match: the live posting, the other places it
  is on, and a repost count from the distinct URLs on the same board. Within one
  normalised company, a description with a high word overlap against an older posting
  joins that group as well. Pick the threshold in this phase by comparing a few real
  reposts with a few genuine different jobs, and record the number in `docs/matching.md`.
  An employer's own feed (phase 20) is preferred over a board, so the apply link goes
  straight to the company.
- Recency, and the "newer than" filter, count from the earliest of the group's `posted_at`
  and `first_seen_at`.
- The seniority check reads a level from the title with a small Romanian and English word
  list, kept beside the synonym map, and subtracts points for a gap of two levels or more
  against `years_experience`. No level word means no penalty.
- The reason string is built from the matched skills, with age and reposts appended when
  they matter.

This is pure functions over plain data, so it is worth unit testing: a handful of
fabricated postings asserting order and filter behaviour. Cover a remote posting
restricted to another country being filtered out, an expired posting being dropped, a
hidden company being dropped, a known-too-low salary being dropped while an unstated one
passes, two postings with one fingerprint collapsing into one match that lists both
boards, two postings at one company with different titles and a near-copy description
collapsing and keeping the earlier date, `pandas OR r` keeping a description that contains
`R` as a word and dropping one that only contains `recruiting`, and a "senior" title
ranking below a "junior" one for a candidate with one year of experience.

The Matches screen: ranked cards with score, reason, company, location, the boards the job
appears on, and a link to the original posting; a keyword box for the boolean query; filter
controls for remote only, minimum score and "newer than" (default 30 days, measured from
the earliest date in the duplicate group, which is how a reposted old job drops out); and a
"hide this company" action on each card that appends to `hidden_companies` through
`PATCH /api/profile`. The keyword box saves back to `keyword_query` on the profile. The
Profile screen lists hidden companies with a control to unhide one, so the choice is
reversible. The save and dismiss actions on each card arrive with the Applications API in
phase 11.

**Verify** - open Matches with the profile from phase 7 and the postings from phases 8 and
9, and read the top ten against your own sense of what fits. `GET /api/matches` returns the
same list. Hide a company, confirm its cards vanish and then reappear after unhiding it on
the Profile screen. Find a job that appears on two boards and confirm it shows once with
both boards listed.

**Done when** - the top results are plausibly yours, every result carries a reason, no
remote posting closed to your country appears, a job on several boards shows once, a
reworded repost counts from its earlier date, a boolean query narrows the list, a hidden
company stays hidden across a reload, and the unit tests pass.

Effort: 8 hours.

---

## Phase 11. Applications, cover letters and the Tracker

**Goal** - the review queue as data, a cover letter draft worth editing rather than
rewriting, and a screen to take one job from match to submitted.

**Files** - backend: `backend/app/routers/applications.py`, extend `backend/app/llm.py`,
`backend/app/schemas.py`. Frontend: `src/pages/Applications.tsx`, a status badge, a letter
editor drawer, and the save and dismiss actions on the match card from phase 10. Docs:
extend `docs/llm.md`.

Details, applications: create from a match (guarding the `(user, job)` uniqueness), list
filtered by status, patch status, notes and letter. Validate status transitions against the
lifecycle in [PLAN.md](PLAN.md) section 5 and stamp `submitted_at` when entering
`submitted`.

Details, letters: `draft_cover_letter(profile, job)` gets the profile summary, the matched
skills and the job description, and is told to write in the language of the posting, which
matters on Romanian boards where many listings are in Romanian. Store on the application
and move status to `drafted`. The call goes to Vertex AI through the same `genai.Client`
built in phase 7, with the same `gemini-3.1-flash-lite` model, so there is one client and
one set of credentials in the codebase. A letter costs about $0.005.

The Tracker screen: a table grouped by status with counts, a drawer to read and edit the
cover letter with a copy button, a notes field, and the status control. The apply link and
the "I submitted this" confirmation sit next to each other, since that pairing is the
actual workflow.

Build the API first and check it through `/docs`, then the screen. They are separable once
the response shapes are fixed in `schemas.py`.

**Verify** - in the browser, save one match, draft its letter and read it, edit it, then
move the application through to `submitted` and later to `interview`. Try an invalid
transition, such as `matched` straight to `interview`, and confirm it is refused.

**Done when** - an invalid transition is rejected, `submitted_at` is set exactly once, the
letter names the company and role and reads like your CV and not a template, and you can
take one job from match to submitted without leaving the browser.

Effort: 5 hours.

---

# Part 2 - Running on GCP

## Phase 12. Data plane

**Goal** - the database, the bucket and the secret containers that production will use,
declared in Terraform, with the schema already migrated into place. The database
password and the secret values are the two things that never go in a `.tf` file.

**Files** - extend `infra/main/main.tf`, extend `docs/cloud.md`.

This is the phase where the billing clock starts. Everything before it was free. From the
moment the Cloud SQL instance exists it bills about $10 a month whether or not anybody
uses it, which is the only meaningful running cost in the whole project.

```hcl
resource "google_sql_database_instance" "db" {
  name                = "cv-applier-db"
  database_version    = "POSTGRES_16"
  region              = "europe-west3"
  deletion_protection = false

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_size         = 10
    disk_type         = "SSD"
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "app" {
  name     = "cv_applier"
  instance = google_sql_database_instance.db.name
}
```

`deletion_protection = false` is a deliberate choice, not an oversight. The provider
defaults this to `true`, which is the right instinct for a database with real users and
the wrong one here, where phase 18's whole teardown checklist depends on
`terraform destroy` being able to actually remove this instance before the credit runs
out. The instance keeps its default address with an empty authorized-network list, so
nothing on the internet can open a connection to it; access goes exclusively through the
Cloud SQL Auth Proxy, which authenticates with IAM rather than an IP allowlist -
`--no-assign-ip` would need a VPC network and a connector on the Cloud Run side to reach
it, which buys nothing here.

The database user and its password are not in this file, and never will be. Terraform
state is a plaintext record of everything it manages, and a live database credential is
exactly the thing not to hand it, so the user is created the same way as before:

```
gcloud sql users create cv --instance=cv-applier-db --password=DB_PASSWORD
```

The bucket is named after the project so it is globally unique:

```hcl
resource "google_storage_bucket" "uploads" {
  name                        = "cv-applier-uploads-${var.project_id}"
  location                    = "europe-west3"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
}

resource "google_storage_bucket_iam_member" "uploads_admin" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
```

That IAM binding is the fourth role mentioned in phase 4, granted here because it is
scoped to this one bucket rather than to the whole project.

Two secret *containers* go into Secret Manager. Terraform creates the empty container;
the value inside it is set by hand, for the same reason the database password is:

```hcl
resource "google_secret_manager_secret" "jwt" {
  secret_id = "jwt-secret"
  replication { auto {} }
}

resource "google_secret_manager_secret" "google_client_secret" {
  secret_id = "google-client-secret"
  replication { auto {} }
}
```

```
terraform apply

printf '%s' "$JWT_SECRET" | gcloud secrets versions add jwt-secret --data-file=-
printf '%s' "$GOOGLE_CLIENT_SECRET" | gcloud secrets versions add google-client-secret --data-file=-
```

Finally, run the migration against Cloud SQL through the proxy, exactly as before -
Terraform provisions an empty database and stops there. It does not know about Alembic
and does not run migrations; schema is data-shaped, not infrastructure-shaped, and stays
with the application's own tooling. In one terminal:

```
gcloud sql instances describe cv-applier-db --format='value(connectionName)'
./cloud-sql-proxy PROJECT_ID:europe-west3:cv-applier-db --port 5433
```

In another, with the proxy still running:

```
cd backend
DATABASE_URL="postgresql+psycopg://cv:DB_PASSWORD@127.0.0.1:5433/cv_applier" alembic upgrade head
```

**Verify** -

```
terraform -chdir=infra/main state list | grep -E 'sql|bucket|secret'
gcloud sql instances list
gcloud storage ls gs://cv-applier-uploads-PROJECT_ID
gcloud secrets list
psql "postgresql://cv:DB_PASSWORD@127.0.0.1:5433/cv_applier" -c "\dt"
```

**Done when** - Terraform's own state list shows the instance, both buckets and both
secret containers, the instance is `RUNNABLE`, both secrets have a version, and `\dt`
through the proxy shows the same tables the compose stack has.

If you stop work for a while, `gcloud sql instances patch cv-applier-db --activation-policy=NEVER`
stops the instance and with it the compute charge. Storage is still billed on a stopped
instance, so the bill drops to roughly $1.70 a month rather than to zero. This is an
operational toggle, not a change to anything Terraform should track, so it stays a
`gcloud` command: flipping it back on is one command, not a plan and an apply.

Effort: 2.5 hours.

---

## Phase 13. First deploy

**Goal** - the real application on a public URL, signing you in with Google, with the
Cloud Run service itself declared in Terraform and its running image left to Cloud Build.

**Files** - extend `infra/main/main.tf`, extend `infra/main/variables.tf`, extend
`docs/cloud.md`.

The repository, in Terraform, with its cleanup policy attached directly to the resource
rather than as a separate command:

```hcl
resource "google_artifact_registry_repository" "backend" {
  location               = "europe-west3"
  repository_id          = "cv-applier"
  format                 = "DOCKER"
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition { tag_state = "ANY" }
  }

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions { keep_count = 2 }
  }

  depends_on = [google_project_service.apis]
}
```

`keep-recent` overrides `delete-old` for whichever two versions are newest, which is what
keeps this inside Artifact Registry's free 0.5 GB: a slim image is around 200 MB, so a
handful of untracked builds would fill it.

```
terraform apply
```

Build and push. An image build is not infrastructure, so it stays a plain Docker command
run by hand, tagged with the commit sha, never `latest`; phase 15 explains why.

```
gcloud auth configure-docker europe-west3-docker.pkg.dev

TAG=$(git rev-parse --short HEAD)
docker build -t europe-west3-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG backend
docker push europe-west3-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG
```

Now the service, in Terraform, pointed at the image you just pushed:

```hcl
resource "google_cloud_run_v2_service" "app" {
  name     = "cv-applier"
  location = "europe-west3"
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
    containers {
      image = "europe-west3-docker.pkg.dev/${var.project_id}/cv-applier/backend:TAG"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.uploads.name
      }
      env {
        name  = "VERTEX_LOCATION"
        value = "global"
      }
      env {
        name  = "VERTEX_MODEL"
        value = "gemini-3.1-flash-lite"
      }
      env {
        name  = "COOKIE_SECURE"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLIENT_ID"
        value = var.google_client_id
      }
      env {
        name  = "DATABASE_URL"
        value = "postgresql+psycopg://cv:${var.db_password}@/cv_applier?host=/cloudsql/${google_sql_database_instance.db.connection_name}"
      }
      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_client_secret.secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.db.connection_name]
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.app.name
  location = google_cloud_run_v2_service.app.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
```

`db_password` and `google_client_id` are declared in `infra/main/variables.tf`, supplied
the same way as `project_id`; `db_password` is marked `sensitive = true`, which hides it
from `plan` and `apply` output but not from state - state was always going to hold this
connection string, so nothing new is exposed by Terraform managing it, the same trade the
project already accepted by putting the password in `DATABASE_URL` rather than in Secret
Manager in the first place. If that stops feeling acceptable, move the whole URL into a
third secret, referenced with the same `secret_key_ref` pattern already used for
`JWT_SECRET` and `GOOGLE_CLIENT_SECRET` above.

`google_cloud_run_v2_service_iam_member` with `member = "allUsers"` is the Terraform
equivalent of `--allow-unauthenticated`: it lets the public reach the service, and the
application still does its own session-cookie auth, with Google sign-in the thing that
actually gates it.

`lifecycle.ignore_changes` on the image field is the one line in this whole project doing
the most quiet work. Phase 15's Cloud Build pipeline redeploys a new image to this same
service on every push, straight past Terraform. Without that line, the next unrelated
`apply` - raising `max_instance_count`, say - would read the old tag still sitting in
this file and silently roll the live service back to it. Worth knowing before it
surprises you: the provider sends the *entire* service definition on every update rather
than a targeted patch, so `ignore_changes` only stops Terraform from *planning* a change
to the image - it does not protect you from *applying* a plan that was saved before the
last deploy happened. The safe habit is to always run `plan` and `apply` back to back
against fresh state, never to apply an old saved plan file.

```
terraform apply
```

`GOOGLE_REDIRECT_URI` and `FRONTEND_ORIGIN` are conspicuously absent from the `env`
blocks above, for a genuine reason rather than an oversight: Cloud Run only assigns the
service's URL once this resource has been created, so Terraform cannot reference a value
that does not exist yet on the same apply that creates it. Read it back and set those two
imperatively, the one ordering problem in this phase that patching by hand is the
ordinary answer to, not a compromise:

```
SERVICE_URL=$(gcloud run services describe cv-applier --region=europe-west3 --format='value(status.url)')

gcloud run services update cv-applier --region=europe-west3 \
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
`gcloud run services logs read cv-applier --region=europe-west3 --limit=50`.

**Done when** - sign-in against the live URL ends on the app with a session cookie,
`/api/auth/me` returns your email over HTTPS, and `terraform -chdir=infra/main plan`
reports no changes at all - not even to the image field, which `ignore_changes` hides
from the diff entirely.

Effort: 2.5 hours, most of it the redirect URI, the cookie flags, and watching
`ignore_changes` actually do its job for the first time.

---

## Phase 14. Scheduled refresh

**Goal** - job sources refreshed nightly without anyone clicking anything, the job and
its trigger both declared in Terraform.

**Files** - `backend/app/refresh.py`, extend `infra/main/main.tf`, extend `docs/cloud.md`.

`refresh.py` is a module entrypoint that loops the same `refresh_source` function the
`POST /api/sources/{id}/refresh` route calls over every `active` source, then exits.
Sources that are `candidate`, `disabled` or `failed` are skipped. It runs as a Cloud Run job
sharing the image built in phase 13, with a different command.

This is a job rather than a route on the public service for three reasons. The refresh
takes minutes and Cloud Run requests have a request timeout and are billed for their whole
duration; the work is privileged and belongs to nobody's session; and a public endpoint
that triggers expensive work would need its own authentication on top of the user session
that it does not have.

```hcl
resource "google_cloud_run_v2_job" "refresh" {
  name     = "cv-applier-refresh"
  location = "europe-west3"

  template {
    template {
      service_account = google_service_account.runtime.email
      max_retries     = 1
      timeout         = "1800s"

      containers {
        image   = "europe-west3-docker.pkg.dev/${var.project_id}/cv-applier/backend:TAG"
        command = ["python"]
        args    = ["-m", "app.refresh"]

        env {
          name  = "DATABASE_URL"
          value = "postgresql+psycopg://cv:${var.db_password}@/cv_applier?host=/cloudsql/${google_sql_database_instance.db.connection_name}"
        }
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "GCS_BUCKET"
          value = google_storage_bucket.uploads.name
        }
        env {
          name  = "VERTEX_LOCATION"
          value = "global"
        }
        env {
          name  = "VERTEX_MODEL"
          value = "gemini-3.1-flash-lite"
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.db.connection_name]
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }
}
```

The `ignore_changes` path has an extra `template[0]` compared to the service in phase 13:
a Cloud Run job nests an execution template inside the job template, where a service has
only one level. Copying the service's path verbatim compiles and silently does nothing,
because there is no `template[0].containers[0]` on a job to match against - it is worth
checking `terraform plan` actually reports no image diff after a manual deploy, rather
than assuming the line is working.

The scheduler needs permission to invoke this one job, on the job itself rather than on
the project:

```hcl
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  name     = google_cloud_run_v2_job.refresh.name
  location = google_cloud_run_v2_job.refresh.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_scheduler_job" "nightly" {
  name      = "cv-applier-nightly"
  region    = "europe-west3"
  schedule  = "0 5 * * *"
  time_zone = "Europe/Bucharest"

  http_target {
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/europe-west3/jobs/cv-applier-refresh:run"
    http_method = "POST"
    oauth_token {
      service_account_email = google_service_account.runtime.email
    }
  }
}
```

```
terraform apply
```

Run it once by hand before trusting the schedule:

```
gcloud run jobs execute cv-applier-refresh --region=europe-west3 --wait
```

**Verify** - `gcloud scheduler jobs run cv-applier-nightly --location=europe-west3`, then
`gcloud run jobs executions list --job=cv-applier-refresh --region=europe-west3`

**Done when** - the forced run shows a succeeded execution, and the next morning the job
count is higher than it was the night before.

Effort: 1.5 hours.

---

## Phase 15. Deploy on push

**Goal** - a push to `main` ends up serving traffic without a laptop in the loop, with
the trigger declared in Terraform on top of the one manual step Terraform cannot do.

**Files** - `cloudbuild.yaml`, extend `infra/main/main.tf`, extend
`infra/main/variables.tf`, extend `docs/cloud.md`.

```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-t", "europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA", "backend"]
  - name: gcr.io/cloud-builders/docker
    args: ["push", "europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA"]
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - deploy
      - cv-applier
      - --image=europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA
      - --region=europe-west3
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - jobs
      - update
      - cv-applier-refresh
      - --image=europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA
      - --region=europe-west3
options:
  logging: CLOUD_LOGGING_ONLY
```

The second `gcloud run jobs update` step exists because the phase 14 job otherwise never
sees a new image after the day it was created: only the service gets redeployed by the
first three steps, and a refresh job silently running last month's code is a worse bug
than a slow one, because nothing about it looks broken.

Connecting the GitHub repository is the other step in this project that stays outside
Terraform, alongside creating the project itself back in phase 4, and it is a genuine
exception rather than a shortcut: it means installing Google's Cloud Build GitHub App on
your repository, which is GitHub's own one-time authorization flow, not Google's, and has
no `gcloud` or Terraform equivalent. Do this once, under Cloud Build, Repositories,
Connect Repository, GitHub (2nd generation), and note the connection name it creates.

Terraform reads that connection back as a data source - it was never a Terraform
resource, so there is nothing to import - and builds the repository reference and the
trigger on top of it:

```hcl
data "google_cloudbuildv2_connection" "github" {
  location = "europe-west3"
  name     = "cv-applier-github"
}

resource "google_cloudbuildv2_repository" "repo" {
  location          = "europe-west3"
  name              = "cv-applier"
  parent_connection = data.google_cloudbuildv2_connection.github.name
  remote_uri        = "https://github.com/GITHUB_OWNER/GITHUB_REPO.git"
}

resource "google_cloudbuild_trigger" "on_push" {
  location = "europe-west3"

  repository_event_config {
    repository = google_cloudbuildv2_repository.repo.id
    push { branch = "^main$" }
  }

  filename        = "cloudbuild.yaml"
  service_account = "projects/${var.project_id}/serviceAccounts/${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "build_deployer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

resource "google_service_account_iam_member" "build_impersonates_runtime" {
  service_account_id = google_service_account.runtime.name
  role                = "roles/iam.serviceAccountUser"
  member              = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}
```

`service_account` on the trigger has to be the full `projects/.../serviceAccounts/...`
path shown above. Leaving it unset does not fail loudly - it silently falls back to the
default Cloud Build service account, which lacks the roles above, and the trigger then
fails every run with a plain "invalid argument" that never says which account it tried
or why. `project_number` is `gcloud projects describe PROJECT_ID --format='value(projectNumber)'`,
added to `infra/main/variables.tf` alongside the others.

```
terraform apply
```

Images are tagged `$SHORT_SHA` rather than `latest` because `latest` destroys the link
between a running revision and the code inside it. Two deploys of `:latest` look identical
in the console while running different code, a rollback has no earlier tag to go back to,
and the tag silently moves under a revision that has already started. With a sha tag,
every Cloud Run revision names the commit it came from. The cleanup policy that keeps
Artifact Registry inside its free 0.5 GB is already on the repository resource from
phase 13, so there is nothing further to configure here.

**Verify** - push a trivial change to `main`, watch
`gcloud builds list --region=europe-west3 --limit=5`, then confirm the new revision:
`gcloud run revisions list --service=cv-applier --region=europe-west3`

**Done when** - the push produced a green build, a new revision whose image tag is that
commit's sha, a refresh job pointed at the same tag, and
`gcloud artifacts docker images list europe-west3-docker.pkg.dev/PROJECT_ID/cv-applier/backend`
holds no more than two images.

Effort: 2 hours, longer than it looks because the GitHub connection step is fiddly the
first time.

---

# Part 3 - Shipping the frontend

The screens already exist, built alongside their APIs in phases 6 to 11 and run locally
through the Vite dev server. What is left is packaging them for the deployed image.

## Phase 16. Serve the UI from the image

**Goal** - the deployed service serves the built UI, so the live URL is the app and not
just an API.

**Files** - edit `backend/Dockerfile`, `backend/app/main.py`, `docker-compose.yml`,
`cloudbuild.yaml`, extend `docs/frontend.md`.

Details: this phase turns `backend/Dockerfile` into a multi-stage build. The first stage
runs `npm ci && npm run build` on `frontend/`, and the final Python stage copies the
compiled assets in and serves them from the backend:

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

The build context becomes the repository root, so `docker-compose.yml` changes to
`build: { context: ., dockerfile: backend/Dockerfile }` and the `docker build` and
`cloudbuild.yaml` paths from phases 13 and 15 change from `backend` to `.` accordingly.

FastAPI serves the `static/` directory and falls back to `index.html` for any path that is
not under `/api`. Without the fallback, a reload on `/matches` is a 404, because React
Router owns that route and the server has never heard of it.

One image serving both halves makes production single-origin: the API and the UI share a
scheme and host, so there is no CORS preflight to configure and the session cookie is
first-party rather than a third-party cookie that browsers are steadily restricting.
Development keeps the Vite proxy, which produces the same single-origin effect through a
different mechanism.

**Verify** - `docker compose up --build`, then open `http://localhost:8000/`, sign in, and
reload on `/matches` to prove the fallback. After the next deploy,
`curl -s $SERVICE_URL/ | head -5` returns the built `index.html`.

**Done when** - the compose image serves the built UI at `http://localhost:8000/` with
every screen working and a reload on a deep link intact, and the deployed image serves it
at `$SERVICE_URL/`.

Effort: 1 hour.

---

## Phase 17. Polish

**Files** - across both apps, plus `README.md`.

Details: empty states that explain the next action, error toasts, loading skeletons, and
a README covering setup, the Google OAuth steps and how to run both halves. Re-read the
diff against [.cursor/rules/coding-style.mdc](.cursor/rules/coding-style.mdc) and strip
any comment that restates its code.

Effort: 2 hours.

---

# Part 4 - Operating it

## Phase 18. Observability and cost hygiene

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
| Cloud Storage | under $0.10 a month | The 5 GB free tier is US-only, so `europe-west3` bills from the first byte at about $0.02 per GB-month. |
| Terraform state bucket | under $0.01 a month | A handful of small JSON files, billed the same as the uploads bucket. |
| Vertex AI, `gemini-3.1-flash-lite` | about $0.005 per cover letter | $0.25 per million input tokens, $1.50 per million output tokens. |
| Vertex AI, board discovery and extraction | under $0.001 per discovery call, about $0.001 per board validated, about $0.001 per page on a board that needs the LLM tier | Same prices. The one cost that grows with the number of boards: a board on the LLM tier at its cap of 30 pages a run is at most about $0.04 a night, so about $1 a month. Boards with JSON-LD cost nothing. |
| Artifact Registry | $0 | 0.5 GB free. A slim image is around 200 MB, so keep at most two tags. |
| Secret Manager | $0 | 6 active secret versions and 10,000 access operations free per month. |
| Cloud Build | $0 | 2,500 build-minutes free per month. |
| Cloud Scheduler | $0 | 3 jobs free per month. |
| Cloud Logging | $0 | First 50 GiB per project per month. |

Roughly $12 a month, so about $36 across the 90-day credit window, leaving the large
majority of the $300 unspent. A few boards on the LLM tier add a few dollars at most.

### Teardown checklist

Almost everything phases 4 to 15 created is a Terraform resource now, so two
`terraform destroy` runs undo almost all of it - `main` first, then `bootstrap`, the
reverse of the order they were created in, because `main`'s state lives in the bucket
`bootstrap` manages, and destroying `bootstrap` first would pull that bucket out from
under `main` mid-command.

```
cd infra/main && terraform destroy
cd ../bootstrap && terraform destroy
```

`deletion_protection = false` on the Cloud SQL instance, set back in phase 12, is what
lets the first command actually succeed rather than erroring on the database. The SQL
user and every secret version created by hand are destroyed as children of the
resources that own them - no separate command needed - and destroying the Artifact
Registry repository removes every image inside it the same way.

Three things `terraform destroy` cannot touch, because Terraform never created them:

| Resource | What to do |
| --- | --- |
| The GitHub App installation from phase 15 | Uninstall it from your GitHub account's Applications settings - the connection was always a data source, never a Terraform resource |
| The project and the billing link | `gcloud projects delete PROJECT_ID`, phase 4's one manual step undone the same way it was made |
| Nothing else | The budget lives under the billing account and is destroyed along with everything else in `bootstrap` |

Deleting the project is the bigger hammer: it removes everything at once, Terraform-managed
or not, right if you are done experimenting, wrong if you expect to come back and
`terraform apply` again on the same project later.

Of everything above, only Cloud SQL and Cloud Storage cost anything while idle. If you
want the data kept and the bill mostly gone without destroying anything, stop the
instance rather than tearing it down, as in phase 12.

When the trial ends the billing account closes rather than charging a card, so the
failure mode of forgetting all this is that the app stops, not that you get a bill.

**Verify** - `gcloud logging read` returns structured rows with your own field names, and
the billing report for the last seven days matches the table above.

**Done when** - the query works, the burn-down is roughly on the predicted line, and the
teardown checklist is written into `docs/cloud.md`.

Effort: 2 hours.

---

# Part 5 - Extending reach

Both phases extend the crawler from phases 8 and 9 and block nothing. Start from the
coverage table in phase 9: it shows which boards failed and why, and so which of these two
phases has something real to work on.

## Phase 19. Browser rendering for JavaScript-heavy boards

**Goal** - boards whose pages are empty until a script runs become readable, through
Playwright, and then go through the same two extraction tiers as every other board.

**Files** - `backend/app/sources/render.py`, edit `fetch.py` (share the address guard),
`discover.py` (validation fallback) and `crawl.py`, an Alembic revision adding
`job_sources.needs_render`, edit `backend/requirements.txt` (add `playwright`) and
`backend/Dockerfile` (install Chromium), extend `src/pages/Sources.tsx` (show that a board
renders in a browser), extend `docs/sources.md` and `docs/cloud.md`.

Pick the target first. Take a board from the phase 9 coverage table that failed with `needs
a browser` or `no postings found` and looks like a script-built page. If the table shows no
such board, skip this phase: none of the twelve boards probed so far needed it, so there
would be nothing to verify against.

Details: `render.py` exposes `render(url) -> html`. It launches headless Chromium, opens the
page with the same honest User-Agent, waits for the network to go quiet or a 15 second cap,
and returns the DOM. The rules from [PLAN.md](PLAN.md) section 7 apply unchanged:

- Every request the browser makes goes through `fetch.py`'s address guard, through
  Playwright's request-routing hook, and is aborted if the address is private, loopback
  or link-local. Images, fonts and media are blocked.
- `robots.txt` is read first, as for any fetch. No stealth plugins, no proxies, and a 403
  from the page is still a refusal.
- One page at a time, a hard timeout per page, and a lower page cap than the plain
  tiers because each page takes seconds.

Validation gains a step: when a plain fetch returns an empty shell, meaning almost no
visible text and no JSON-LD, retry through `render`. If tier 1 or tier 2 then yields
postings, store `needs_render = true` on the source, and `crawl.py` renders its pages from
then on.

Decide where Chromium runs in this phase, from numbers, not before. It adds hundreds of
megabytes to an image that the plan sizes at about 200 MB against Artifact Registry's 0.5 GB
free tier, it needs more memory than the API service does, and it executes untrusted
JavaScript. The options are one heavier image for everything or a heavier image for the
refresh job only, and the choice goes in `docs/cloud.md` next to the measured size and
memory.

One unit test: a browser request to `169.254.169.254` is aborted by the routing hook.

**Verify** - refresh the chosen board from the Job boards screen and confirm it validates
with `needs_render` set and that its postings land in `jobs`.

**Done when** - the board yields at least ten real postings, the test above passes, and
the image size and memory figures are written down.

Effort: 4 hours.

---

## Phase 20. Employers and their ATS feeds

**Goal** - jobs straight from the public ATS feeds companies already publish, with the
company's own apply link. A company comes from the model, from an apply link on a board
posting, or from a URL you paste.

Read [PLAN.md](PLAN.md) section 2, "Can employers' own job feeds be read?", and the
employer section in 7 first. The numbers matter for expectations: in a test over the ten
largest employers in each of three Romanian cities, about one in six had a feed we could
read, and the banks, telecoms and retailers mostly sit on portals this phase does not
cover. The phase adds depth at companies like Endava, Continental and Accenture, and it does
not replace the boards.

**Files** - backend: `backend/app/sources/employers.py` (find an employer's ATS and verify
it), `backend/app/sources/ats.py` (one reader per provider), extend `backend/app/llm.py`
with `propose_employers(city, country, titles)` and `classify_employer(name, blurb)`, edit
`discover.py`, `crawl.py` and `matching.py`, edit
`backend/app/routers/sources.py` (the `kind` parameter, and accepting an ATS URL), an
Alembic revision adding the ATS columns to `job_sources` and `jobs.experience_level`, and
unit tests. Frontend: extend `src/pages/Sources.tsx` with a "Find employers in `<city>`"
button and accept an ATS URL in the add box. Docs: extend `docs/sources.md` and
`docs/llm.md`.

Details: the steps are in section 7.

- `llm.py`'s `propose_employers` asks for the largest employers in the profile's city that
  hire for the profile's titles, as `{company, website}`. A name and a domain, not a
  careers URL: only 18 of the 30 URLs the model gave in the test were reachable.
  Discovery refuses to run until the profile has a city.
- `employers.py` finds the ATS for a named company. It fetches the home page and the usual
  careers paths with `fetch.py`, looks for links to Greenhouse, Lever, Ashby,
  SmartRecruiters, Workable, Recruitee and Workday and takes their identifiers, and falls
  back to slugs derived from the company name. A script-shell page is rendered through
  phase 19 if it exists. A source that already has a slug, from an apply link or a pasted
  URL, skips that search. Then the ownership check: a feed that names its company must
  match, and one that does not must contain a job in the candidate's country.
- `ats.py` has one reader per provider, each mapping a feed to the `Posting` dataclass
  with the employer's own `apply_url`. Greenhouse, Lever, Ashby, SmartRecruiters, Workable
  and Recruitee use their documented public feeds. Workday uses the JSON endpoint its
  careers site calls, `POST /wday/cxs/{tenant}/{site}/jobs`, which is undocumented and can
  change. Read each provider's terms and check the live response shape when writing its
  reader. Some feeds omit descriptions and need one more request per new posting, within the
  cap of 100 per run.
- `crawl.py` branches on `extraction = "ats"`. After a board posting is stored, an
  `apply_url` on a known ATS host is parsed into a provider and a slug and stored as an
  employer candidate. That URL is not fetched. These sources are refreshed like boards and
  by the nightly job. The employer portion stops after 15 minutes and resumes the next
  night at the sources least recently checked.
- `llm.py` gains `classify_employer(name, blurb)`. It runs once when an employer source is
  first stored. An agency is saved `disabled` with the reason `staffing agency`. A failed
  call leaves the source a candidate and says the check did not run.
- The SmartRecruiters reader passes the profile's country, and any feed that returns
  locations drops out-of-country jobs before it fetches a description.
- `experience_level` from a feed, when the feed has one, is stored and matching prefers it
  to a level word in the title.

Where the test found a feed, save a real response per provider as a unit-test fixture.
Two tests are worth writing: each reader maps its saved response to the right `Posting`
fields, and the ownership check rejects the Accenture-on-Recruitee case, a 2-job board that
belongs to a different company and has nothing in the candidate's country.

**Verify** - with a profile whose city is Cluj-Napoca or Timisoara, click "Find employers
in `<city>`". Ten or so candidates appear. Refresh them one by one. Expect some to become
`active` with their ATS shown, for example Endava on SmartRecruiters or Continental, and the
rest to end `failed` with a reason such as `no supported ATS found`. Paste
`https://jobs.smartrecruiters.com/endava` and confirm it skips the career-page search.
Refresh a board that carries an ATS apply link and confirm a new employer candidate
appears from that link alone. Then
`docker compose exec db psql -U cv -d cv_applier -c "select source, count(*) from jobs group by source"`
and confirm that a job found on both a board and its employer's feed shows once in Matches,
with the employer's apply link. An agency, if one comes back, is `disabled` with the
reason `staffing agency` and produces no matches until you switch it on.

**Done when** - at least three employers in your city validate and yield postings, each
posting has the company's own apply link, a pasted ATS URL and a harvested apply link both
become employer sources, the ownership check rejects the false-match fixture, an agency
comes back disabled, and a cross-source duplicate shows once with the direct link.

Effort: 8 hours.

---

## Documentation deliverables

Each phase ships its doc in the same change as its code, per the docs rule. Written for an
agent with no prior context: what the subsystem does, where it lives, the contract it
exposes, and the constraints the code cannot show.

- Phase 1: `AGENTS.md` at the root - stack, how to run both halves, index into `docs/`.
- Phase 3: `docs/auth.md` - the OAuth flow, why no Google tokens are stored, the verified
  email rule for account linking, and how to add a second provider.
- Phases 4 and 5: `docs/cloud.md` - the GCP project layout, the `infra/bootstrap` and
  `infra/main` Terraform modules and why they are split, what runs where, the local
  compose stack and how it mirrors production, the credentials model.
- Phase 6: `docs/frontend.md` - routing, the API wrapper, the auth redirect behaviour, the
  dev proxy.
- Phase 7: `docs/profile.md` - CV parsing path, the extraction contract, where the uploaded
  file is stored.
- Phases 7, 9 and 11: `docs/llm.md` - every Vertex AI prompt, the model choice, the
  language rule for letters, the untrusted-input rule for page text, and why Vertex AI
  rather than AI Studio.
- Phases 8, 9, 19 and 20: `docs/sources.md` - how boards are discovered and validated, the
  two extraction tiers, the rules the crawler never breaks, how the fingerprint is built and
  why `first_seen_at` is never updated, the coverage finding from phase 9, how browser
  rendering is guarded, and how an employer's ATS feed is found from a name, an apply link
  or a pasted URL, how an agency is labelled once, and which providers are read.
- Phase 10: `docs/matching.md` - the scoring formula, the hard filters including remote
  eligibility, salary, the boolean keyword query and hidden companies, duplicate grouping
  including the description-overlap threshold, the seniority check, and the bilingual
  normalisation.
- Phases 12 to 15: extend `docs/cloud.md` - the deployment topology, the service account
  roles, and the deploy command.
- Phase 16: extend `docs/frontend.md` - how the bundle is built into the image and served.
- Phase 18: extend `docs/cloud.md` - the cost model and the teardown checklist.
- Phase 19: extend `docs/cloud.md` - where Chromium runs, with the measured image size and
  memory.

## Parallel work and subagents

Per the feature workflow rule, the lead fixes the contracts first, then splits. Four
points in this plan split cleanly:

- Phase 4 is Terraform and CLI work that touches no application code, so it can run
  alongside phase 5 once the environment variable names are fixed. Contract to fix first:
  the `.env` block in the prerequisites.
- The crawler core of phase 8, which is `fetch.py`, `extract.py` and their unit tests, is
  pure code with no dependency on the profile, so it can be built alongside phase 7.
  Contract to fix first: the `Posting` dataclass in `backend/app/sources/posting.py`.
- Within each of phases 7, 8, 10 and 11, the API and its screen are separable once the
  response shapes are fixed. Contract to fix first: the response models in
  `backend/app/schemas.py` and the matching types in `frontend/src/api.ts`. Each subagent
  owns its own files, one the router and modules, the other the page, and nothing else.
- Phases 19 and 20 touch different modules (`render.py` against `employers.py` and
  `ats.py`) and share only the `Posting` dataclass, so they can be built side by side.
  Phase 20 can use phase 19's rendering when it exists and does not need it. They both edit
  `crawl.py` and `Sources.tsx`, so the lead makes those two small edits itself.

Phase 17 polish is not parallelisable and stays with the lead.

Everything else is sequential because each phase consumes the previous one's output. The
cloud phases in particular are strictly ordered: each one creates the resource the next
one refers to by name.

## Totals and sequencing

Part 1 is roughly 36 hours, part 2 roughly 6, part 3 roughly 3, part 4 roughly 2, part 5
roughly 12, so about 59 hours in total.

The first moment the project is genuinely useful is the end of phase 11, when you can sign
in, upload a CV, see ranked matches from boards found for your country and draft a letter,
all in the browser and without a cloud bill. The first moment it is useful from a phone is
the end of phase 16, when the deployed image serves the UI.

Phases 4 and 5 look like a detour from the feature work, and they are what makes phases 12
to 15 short: by the time anything is deployed, the container, the database engine and the
storage client have all already been proven locally.

## Deferred, with triggers

- More ATS providers (SuccessFactors, Oracle Recruiting, Taleo, iCIMS) - when the coverage
  table shows employers you care about on one of them. Each is one more small reader in
  `ats.py`.
- Description embeddings - when a paraphrased repost still appears as a new job after the
  word-overlap check in phase 10. The fingerprint stays the blocking key.
- Auto-filling ATS forms with Playwright - clicking and form filling, after the tracker
  proves the workflow. Rendering pages is phase 19.
- Cloud SQL backups and a second environment - when losing the data would actually matter.
