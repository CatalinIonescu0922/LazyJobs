# CV Applier - Build Plan

The steps for [PLAN.md](PLAN.md), one phase at a time. Each phase ends with something you
can run and check. [PROGRESS.md](PROGRESS.md) says which phase is current, and
[LEARNING.md](LEARNING.md) holds the reasons behind each decision.

Conventions:

- **Files**: what is created or changed in the phase.
- **Verify**: the command or click path that proves it works.
- **Done when**: the observable result to look for before moving on.
- Capitals in commands are placeholders. `PROJECT_ID` is `cv-applier-ionescu-catalin` (see
  [docs/cloud.md](docs/cloud.md)) and `DB_PASSWORD` is the password chosen in phase 2.
  Every other name is fixed and used verbatim across phases.
- From phase 2 the database is Cloud SQL, and `psql "$CLOUD_DB"` means `psql
  "postgresql://cv:$DB_PASSWORD@127.0.0.1:5433/cv_applier"` with the proxy container up.
  Before phase 2 the same queries run in the local container with
  `docker compose exec -T db psql -U cv -d cv_applier`.

Everything lives in `europe-west3` (Frankfurt), except Vertex AI, which uses the `global`
endpoint. Docker Compose commands run from the repository root.

---

## Already built

Not redone here. The phases below start from this.

| Area | Where it is described |
| --- | --- |
| Skeleton, Google sign-in, session cookie | [docs/auth.md](docs/auth.md) |
| CV upload, Vertex AI extraction, editable profile | [docs/profile.md](docs/profile.md) |
| Frontend shell and screens: Sign-in, Home, Profile, Sources, Companies | [docs/frontend.md](docs/frontend.md) |
| Generic sitemap crawler, model tier, Himalayas, Greenhouse and Workday readers, ATS directory, company probing | [docs/sources.md](docs/sources.md) |
| GCP project, Terraform state bucket, budget, runtime service account | [docs/cloud.md](docs/cloud.md) |
| Compose stack with PostgreSQL 16 and a storage emulator, Alembic | [AGENTS.md](AGENTS.md) |

## Prerequisites

On the machine: `gcloud`, Terraform, Docker with Compose, `psql`, Python 3.12 and Node 20.
Application Default Credentials set up with `gcloud auth application-default login` and
`gcloud auth application-default set-quota-project PROJECT_ID`. The Google OAuth client
exists and `http://localhost:8000/api/auth/google/callback` is an authorized redirect URI.

`backend/.env`, with the lines marked for a later phase added when that phase starts:

```
DATABASE_URL=postgresql+psycopg://cv:cv@db:5432/cv_applier
GCS_BUCKET=cv-applier-local
STORAGE_EMULATOR_HOST=http://gcs:4443
JWT_SECRET=<random 32+ characters>
FRONTEND_ORIGIN=http://localhost:5173
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
COOKIE_SECURE=false
GOOGLE_CLOUD_PROJECT=PROJECT_ID
VERTEX_LOCATION=global
VERTEX_MODEL=gemini-3.1-flash-lite
CRAWL_WORKERS=6
PAGES_PER_RUN=100          # phase 1; 600 once you want the backlog to drain
LLM_PAGES_PER_RUN=30       # phase 1; 150 once you want the backlog to drain
ADMIN_EMAILS=you@example.com   # phase 3
GATHER_COUNTRIES=RO            # phase 3
REFRESH_INTERVAL_HOURS=12
GATHER_RUN_MINUTES=25          # phase 4
LLM_DAILY_LIMIT=20             # phase 6
LLM_MAX_CONCURRENT=4           # phase 6
```

`DATABASE_URL`, `GCS_BUCKET` and `STORAGE_EMULATOR_HOST` change in phase 2.

---

## Phase dependencies

```mermaid
flowchart TD
  P1["1 Back to green"] --> P2["2 Persist in GCP"]
  P2 --> P3["3 One global catalog"]
  P3 --> P4["4 The gatherer"]
  P3 --> P5["5 The feed"]
  P4 -. gathering runs while 5 and 6 are built .-> P5
  P5 --> P6["6 Favorites and on-click CV and letter"]
  P6 --> P7["7 Deploy the API and UI"]
  P4 --> P8["8 The refresh in the cloud"]
  P7 --> P8
  P7 --> P9["9 Deploy on push"]
  P8 --> P10["10 Observability, cost, teardown"]
  P9 --> P10
  P4 --> P11["11 Retire gone jobs (later)"]
  P10 --> P12["12 Wider reach (later)"]
  P10 --> P13["13 Polish (later)"]
```

---

# Part A - Make the data safe and shared

## Phase 1. Back to green

**Goal**: the database, the code, the running process and the tests agree again, and the
refresh runs.

**Files**: `backend/app/models.py`, delete
`backend/alembic/versions/ae354c484b8a_add_job_dead_job_posting.py`,
`backend/app/sources/crawl.py`, `backend/app/config.py`, `backend/.env.example`.

The refresh stopped on 2026-11-12 because the model has a column the database does not
(PLAN.md section 2). Do not apply the pending migration and do not just restart:

- The revision adds `dead_posting` as NOT NULL with no default to a table that has rows,
  which PostgreSQL refuses (`column ... contains null values`), and Compose runs
  `alembic upgrade head` before the server, so a restart would stop the app before it
  serves anything.
- It has never been applied anywhere (`alembic current` prints `f9a0b1c2d3e4`), so deleting
  it changes no database. Dead URLs are persisted properly in phase 3, as a table.

Steps:

1. Remove `dead_posting` (and the `ARRAY` import it needed) from `JobSource` and delete the
   revision file. `docker compose exec app alembic heads` now prints `f9a0b1c2d3e4`, the
   same as `alembic current`.
2. Make the two page caps settings: `PAGES_PER_RUN` (default 100) and `LLM_PAGES_PER_RUN`
   (default 30) replace the constants `MAX_POSTINGS` and `MAX_LLM_POSTINGS` in
   `crawl.py`. The defaults are today's values, so nothing changes until `.env` says so.
   Setting `600` and `150` lets the backlog start draining at once, ahead of the rewrite;
   phase 2 then moves whatever it gathers into Cloud SQL.
3. In `backend/.env.example`, drop the unused `OPENAI_*` lines and `GOOGLE_CLOUD_LOCATION`
   (the setting is `VERTEX_LOCATION`).
4. Run the tests.
5. `docker compose restart app`. The code is bind-mounted, but uvicorn does not reload, so
   the process that has been running since 2026-11-12 still has the old model.

**Verify**:

```
docker run --rm -e PYTHONPATH=/app -e LOG_FILE=/tmp/test.log -v "$PWD/backend":/app -w /tmp \
  lazyjobs-app:latest python -m pytest /app/tests -q -p no:cacheprovider
docker compose restart app
docker compose exec -T db psql -U cv -d cv_applier -c "select max(last_refreshed_at) from job_sources"
rg -a "Scheduled refresh (started|failed)" backend/logs/app.log | tail -n 3
```

Allow the first tick, which runs 60 seconds after start and takes one slice of the due
sources; catching up four days takes several ticks.

**Done when**: all 424 tests pass, `alembic current` equals `alembic heads`, a tick logs
`Scheduled refresh started`, and `max(last_refreshed_at)` is later than 2026-11-16.

The guard against a repeat is built in phase 4: the app refuses to start when the database
is not at the code's revision, and a stale catalog shows in the UI.

Effort: 30 minutes.

---

## Phase 2. Persist in GCP

**Goal**: everything the app has stored lives in Cloud SQL and the real uploads bucket,
declared in Terraform, and every laptop reads and writes the same data.

**Files**: `infra/main/main.tf`, `docker-compose.yml`, `docker-compose.isolated.yml` (new),
`backend/.env.example`, `backend/alembic/env.py`, `backend/app/db.py`,
`docs/cloud.md`, `AGENTS.md`.

From the moment the instance exists it bills about $10 a month whether or not anyone uses
it. That is the point: the data stops depending on one disk.

### 2.1 The billing account

Open the Billing overview. It says Free trial account or Paid account, and the Free credit
pane shows the remaining credit and days with an Activate button. Write the trial's end
date into [PROGRESS.md](PROGRESS.md); it is no later than 2026-12-23 (PLAN.md section 2).

The trial never charges the card by itself. If it ends without an upgrade, billing is
disabled on the project, everything is stopped, and after a 30-day grace period the
resources and their data are permanently deleted, so a missed date costs the data and not
money. Upgrading (Activate) before then keeps the resources running and keeps any unused
credit until the original 90 days are up, so doing it early costs nothing extra. After
that the card is charged for usage beyond the remaining credit, about $12 to $15 a month
for this project. Decide to upgrade, with the $50 budget alert kept, before the end date.
The click itself can wait until Cloud SQL is verified, but it is part of this phase being
done.

### 2.2 Terraform

Add to `infra/main/main.tf`, then `terraform plan` and `terraform apply`:

```hcl
resource "google_sql_database_instance" "db" {
  name                = "cv-applier-db"
  database_version    = "POSTGRES_16"
  region              = "europe-west3"
  deletion_protection = false

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_size         = 10
    disk_type         = "SSD"

    backup_configuration {
      enabled    = true
      start_time = "01:00"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "app" {
  name     = "cv_applier"
  instance = google_sql_database_instance.db.name
}

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

resource "google_secret_manager_secret" "values" {
  for_each  = toset(["jwt-secret", "google-client-secret", "database-url"])
  secret_id = each.value

  replication {
    auto {}
  }
}
```

Notes on the choices:

- `deletion_protection = false` is deliberate: the teardown in phase 10 depends on
  `terraform destroy` being able to remove the instance. Every teardown starts with a dump,
  because the instance now holds users' data.
- `edition = "ENTERPRISE"` is explicit because the edition decides which tiers are allowed.
- The instance keeps its default address with an empty authorized-network list, so nothing
  on the internet can open a connection; access is through the Cloud SQL Auth Proxy, which
  authenticates with IAM.
- The user, its password and every secret value are not in this file, because Terraform
  state is plaintext.

### 2.3 The user and the secrets

```
set -a; . backend/.env; set +a      # JWT_SECRET and GOOGLE_CLIENT_SECRET come from here
DB_PASSWORD=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)   # no characters that need URL-encoding
gcloud sql users create cv --instance=cv-applier-db --password="$DB_PASSWORD"

printf '%s' "$JWT_SECRET"           | gcloud secrets versions add jwt-secret --data-file=-
printf '%s' "$GOOGLE_CLIENT_SECRET" | gcloud secrets versions add google-client-secret --data-file=-
printf '%s' "postgresql+psycopg://cv:$DB_PASSWORD@/cv_applier?host=/cloudsql/PROJECT_ID:europe-west3:cv-applier-db" \
  | gcloud secrets versions add database-url --data-file=-
```

Keep `DB_PASSWORD` in `backend/.env` (gitignored) for laptops. The password never goes
through Terraform: Cloud Run reads the whole `database-url` secret (phase 7).

### 2.4 Take the data out of the local database

Stop the app first so nothing changes during the dump, and keep the dumps out of the
repository: they contain people's CVs.

```
mkdir -p ~/lazyjobs-backups
docker compose stop app
docker compose exec -T db pg_dump -U cv -d cv_applier --no-owner --no-acl > ~/lazyjobs-backups/local-full.sql
docker compose exec -T db pg_dump -U cv -d cv_applier --data-only --no-owner --no-acl \
  --exclude-table=alembic_version > ~/lazyjobs-backups/local-data.sql
docker compose exec -T db psql -U cv -d cv_applier -c "select (select count(*) from users) users, (select count(*) from profiles) profiles, (select count(*) from jobs) jobs, (select count(*) from job_sources) job_sources, (select count(*) from companies) companies, (select count(*) from ats_boards) ats_boards"
```

Write the counts down. On 2026-11-16 they were 2, 2, 1,730, 49, 1,192 and 12,244, and
`jobs` grows once phase 1's refresh runs.

### 2.5 Compose: the proxy, and two modes

The base `docker-compose.yml` becomes the laptop-and-Cloud-SQL mode. Add the proxy, give
`app` `restart: unless-stopped`, and replace its dependency on `db` with one on the proxy:

```yaml
  cloud-sql-proxy:
    image: gcr.io/cloud-sql-connectors/cloud-sql-proxy:2
    restart: unless-stopped
    command:
      - "--address=0.0.0.0"
      - "--port=5432"
      - "PROJECT_ID:europe-west3:cv-applier-db"
    environment:
      GOOGLE_APPLICATION_CREDENTIALS: /run/secrets/google_application_credentials.json
      # Docker injects the host's corporate proxy into every container (AGENTS.md); the proxy
      # needs direct access to Google, as the app does.
      HTTP_PROXY: ""
      HTTPS_PROXY: ""
      http_proxy: ""
      https_proxy: ""
    ports:
      - "127.0.0.1:5433:5432"
    secrets:
      - source: google_adc
        target: google_application_credentials.json
```

The proxy reaches the instance on outbound TCP port 3307. Check that first on this network
(`nc -vz INSTANCE_IP 3307`, the address from `gcloud sql instances describe`); a firewall
that blocks it breaks everything after this step.

`docker-compose.isolated.yml` holds the old `db` (PostgreSQL 16) and `gcs` (storage
emulator) services and points `app` at them, for offline work and for tests:
`docker compose -f docker-compose.yml -f docker-compose.isolated.yml up`. The exact
override syntax is settled while writing it; the contract is that the default command is
the Cloud SQL mode and the isolated mode needs no cloud at all.

`backend/.env` for the Cloud SQL mode:

```
DATABASE_URL=postgresql+psycopg://cv:DB_PASSWORD@cloud-sql-proxy:5432/cv_applier
GCS_BUCKET=cv-applier-uploads-PROJECT_ID
STORAGE_EMULATOR_HOST=
```

### 2.6 Schema, then data

```
docker compose up -d cloud-sql-proxy
docker compose run --no-deps --rm app alembic upgrade head
psql "postgresql://cv:$DB_PASSWORD@127.0.0.1:5433/cv_applier" -f ~/lazyjobs-backups/local-data.sql
```

Alembic builds the schema as the head revision and the data-only dump fills it, which is
why phase 1 comes first: a dump from a database whose model disagrees with its migrations
does not load. If a migration says `permission denied for schema public`, run
`GRANT ALL ON SCHEMA public TO cv;` as `postgres` (PLAN.md section 8).

Run the same count query against Cloud SQL through `psql` on port 5433. The counts must
equal the ones from 2.4.

### 2.7 Make a shared database safe to use

- **Pools.** `backend/app/db.py` sets an explicit small pool (for example `pool_size=3`,
  `max_overflow=2`, `pool_pre_ping=True`). A shared-core instance allows few connections:
  run `SHOW max_connections;` through `psql`, write the number in `docs/cloud.md`, and
  keep the sum of every process's pool under it. The API on up to three Cloud Run
  instances, the gatherer's workers and two laptops all draw from it.
- **One migration at a time.** `backend/alembic/env.py` takes
  `SELECT pg_advisory_lock(4242000)` before it migrates and releases it after, so two
  machines starting at once cannot run the same migration twice.
- **Uploaded CVs.** The emulator keeps files in memory only, so the two existing CVs are
  not in the real bucket. The extracted text is already in `profiles.cv_text`, which is
  what matching and letters use. Ask the two users to upload again, or copy the files from
  the emulator before stopping it.

### 2.8 A backup you have restored

```
gcloud sql backups create --instance=cv-applier-db
gcloud sql backups list --instance=cv-applier-db
```

Then prove a dump restores, into a scratch database, and drop it:

```
psql "postgresql://postgres:POSTGRES_PASSWORD@127.0.0.1:5433/postgres" -c "create database restore_check owner cv"
psql "postgresql://cv:$DB_PASSWORD@127.0.0.1:5433/restore_check" -f ~/lazyjobs-backups/local-full.sql
psql "postgresql://cv:$DB_PASSWORD@127.0.0.1:5433/restore_check" -c "select count(*) from jobs"
psql "postgresql://postgres:POSTGRES_PASSWORD@127.0.0.1:5433/postgres" -c "drop database restore_check"
```

(`POSTGRES_PASSWORD` is set with `gcloud sql users set-password postgres
--instance=cv-applier-db --password=...` and used only for this.)

### 2.9 Run on the cloud database

`docker compose up -d app` and, from `frontend/`, `npm run dev`. Open `http://localhost:5173`,
sign in, upload a CV and check it landed in `gs://cv-applier-uploads-PROJECT_ID/`. On a
second laptop with the same `.env`, the same commands show the same jobs.

**Verify**:

```
terraform -chdir=infra/main plan
gcloud sql instances list
gcloud sql backups list --instance=cv-applier-db
gcloud storage ls gs://cv-applier-uploads-PROJECT_ID/
curl -s localhost:8000/api/health
```

**Done when**: `terraform plan` reports no changes; the instance is `RUNNABLE` with a
backup listed; Cloud SQL's counts equal the dump's; the dump restored into a scratch
database; the app runs against Cloud SQL on this laptop and the second one shows the same
data; a CV upload is in the real bucket; `max_connections` and the trial's end date are
written down; and the billing upgrade is decided.

To stop paying while away: `gcloud sql instances patch cv-applier-db --activation-policy=NEVER`
stops the compute charge (storage is still billed) and `ALWAYS` starts it again. It is an
operational toggle, so it stays a command and not Terraform.

Effort: 3 hours.

---

## Phase 3. One global catalog

**Goal**: sources, companies and jobs belong to the catalog and not to a user, nothing the
crawler does depends on a profile, and only admins manage sources.

**Files**: a new Alembic revision `global_catalog`; `backend/app/models.py`,
`config.py`, `session.py`, `schemas.py`, `textnorm.py`, a new `backend/app/gather.py` (the
orchestration moves here), a one-off `backend/app/backfill.py`;
`backend/app/routers/auth.py`, `sources.py`, `companies.py`, `jobs.py`;
`backend/app/sources/crawl.py`, `aggregator.py`, `himalayas.py`, `career.py`, `ats.py`,
`discovery.py`, `directory.py`, `posting.py`; `backend/app/llm.py`;
`backend/tests/` throughout; `frontend/src/api.ts`, `router.tsx`, `pages/Home.tsx`,
`Profile.tsx`, `Sources.tsx`, `Companies.tsx`; `docs/sources.md`, `docs/auth.md`, `AGENTS.md`.

Take an on-demand backup first (`gcloud sql backups create --instance=cv-applier-db`): the
migration merges rows.

### 3.1 The schema, one revision

1. `job_sources`: for each `(kind, domain)` keep one row, preferring `active`, then the
   newest `last_refreshed_at`, then the lowest `id`, and delete the rest. Drop `user_id`.
   Add the unique constraint `uq_job_source_kind_domain`. Add `country` (2 characters,
   default empty). Backfill `country` to `RO` for boards, careers and employers, and to
   empty for aggregators and for any source whose stored jobs are at least 80% remote.
2. `companies`: for each `key` keep one row, preferring status `feed`, then `none`, then
   the highest `postings`, then the lowest `id`. Drop `user_id`. Add the unique constraint
   `uq_company_key`.
3. `jobs`: add `country` (backfilled to empty for remote jobs and to the source's country
   for the rest) and `last_seen_at` (backfilled from `fetched_at`).
4. A new table `dead_urls`: `id`, `source` (255), `url` (1024), `reason` (64), `seen_at`,
   unique on `(source, url)`.

### 3.2 The fingerprint

`textnorm.fingerprint(company, title, city)` stays, but callers now pass the **city name**
(the first location up to its first comma) in `_upsert_job` and everywhere else. A
one-off, idempotent `python -m app.backfill fingerprints` recomputes the stored value for
existing rows; run it inside Compose after the migration. The search stops recomputing a
key in Python (phase 5 uses the stored one).

### 3.3 The crawl takes no profile input

These signatures are the contract; callers and tests change to match.

```python
# backend/app/sources/crawl.py
def refresh_source(db: Session, source: JobSource, *, max_pages: int, max_llm_pages: int) -> dict: ...
# backend/app/sources/aggregator.py
def refresh_aggregator_source(db: Session, source: JobSource, countries: list[str]) -> dict: ...
# backend/app/sources/career.py
def refresh_career_source(db: Session, source: JobSource, countries: list[str]) -> dict: ...
# backend/app/sources/ats.py
def read_feed(feed: Feed, domain: str, countries: list[str], known: set[str], limit: int = 100) -> list[Posting]: ...
# backend/app/sources/discovery.py
def seed_companies(db: Session, countries: list[str]) -> int: ...
def discover_feeds(db: Session, countries: list[str], tick: timedelta) -> list[JobSource]: ...
def enrich_domains(db: Session, countries: list[str]) -> int: ...
# backend/app/sources/directory.py
def match_companies(db: Session) -> int: ...
```

What each one stops doing:

- `crawl.py`: no `pick_sitemaps` call and no `terms`. When a sitemap index has several
  category children, read all of them. Order the fresh URLs newest first. Caps come from
  `max_pages` and `max_llm_pages`. Record a URL that answers 404, 410, is not a posting, or
  whose posting is already expired, in `dead_urls` and skip `dead_urls` before fetching.
  Delete the in-memory `_dead` dict and set `last_seen_at` for every stored job whose URL
  is in the sitemap it just read. Posting gets a `country` field and `_upsert_job` stores it.
- `aggregator.py` and `himalayas.py`: search a fixed list of about thirty job-family terms
  with each country in `countries`, a few terms per run, rotating by the source's
  `last_refreshed_at`, so every term is covered each cycle. First check whether an empty
  `q` returns everything: `curl -s "https://himalayas.app/jobs/api/search?country=RO&page=1"`.
  If it does, page through it and drop the term list.
- `ats.py` and `career.py`: a posting is kept when it is located in any of `countries` or
  open to any of them; Workday is searched by the country's name, not a city.
- `discovery.py` and `directory.py`: no `user_id`; one `companies` list.
- `llm.py`: delete `pick_sitemaps` and `propose_employers`. `propose_job_boards(country)`
  stays and is called once per market by the gatherer in phase 4.

Move `refresh_due_sources`, `refresh_budget`, `_run_refresh`, `_refresh_one_source`,
`refresh_any` and `_discover_companies` out of `routers/jobs.py` into `app/gather.py`. They
iterate over the global sources with `settings.gather_countries` and no longer loop over
users. `scheduler.py` calls them as it does today; phase 4 replaces the loop.

### 3.4 Ownership and admins

- `config.py`: `admin_emails` (comma separated) and `gather_countries` (comma separated,
  default `RO`), with list accessors.
- `session.py`: `current_admin`, a dependency that returns the user when their email is in
  `ADMIN_EMAILS` and otherwise raises 403.
- `routers/auth.py`: `GET /api/auth/me` returns `is_admin`.
- Every route in `routers/sources.py` and `routers/companies.py` depends on
  `current_admin`. `POST /api/sources/discover` takes `country` (default: the first market)
  and drops `kind=employers`.
- `routers/jobs.py`: delete `POST /api/jobs/search` and the refresh-on-search code. `GET
  /api/jobs` reads jobs from every active source with no user filter. It is still the old
  Python filter and is replaced in phase 5.
- Frontend: `Me` gains `is_admin`; the Sources and Companies links and routes show only to
  admins; `Profile.tsx` drops `automaticSearch` and goes straight to the feed after an
  upload.

### 3.5 Tests on PostgreSQL

`backend/tests/conftest.py` builds the schema in a throwaway database `cv_applier_test` on
the isolated Compose `db`, from `TEST_DATABASE_URL`, and empties the tables between tests.
No in-memory SQLite remains. One test runs `alembic upgrade head` on an empty database and
then `alembic check`, so a model and its migrations cannot drift apart unnoticed. The test
command in `AGENTS.md` changes to run in the Compose network with `TEST_DATABASE_URL` set.
Tests that built `User` and `Profile` rows to drive the crawl are rewritten around sources
and markets.

**Verify**:

```
psql "$CLOUD_DB" -c "select count(*) from job_sources"                                        # 30
psql "$CLOUD_DB" -c "select count(*) from companies"                                          # 631
psql "$CLOUD_DB" -c "select kind, domain from job_sources group by 1,2 having count(*) > 1"   # no rows
rg -n "Profile|user_id" backend/app/sources                                                   # no matches
rg -n "_dead\b|pick_sitemaps|propose_employers" backend/app                                   # no matches
```

Sign in with the second account: `GET /api/sources` answers 403 and the nav shows no Sources
or Companies. Sign in as an admin: both work.

**Done when**: the counts above hold, the search still returns jobs for both accounts, a
refresh of one source reads every category of a category board and a profile never enters
the call, an admin refresh works and a non-admin one is refused, the whole suite passes on
PostgreSQL, and `docs/sources.md` matches what is built.

Effort: 8 hours.

---

# Part B - Gather, then serve

## Phase 4. The gatherer

**Goal**: a separate process that owns every write of postings, resumes from the database
at start, drains backlogs politely, and says plainly when it is behind. Then run it: the
gather period starts here.

**Files**: `backend/app/gather.py`, delete `backend/app/scheduler.py`,
`backend/app/main.py`, `backend/app/models.py` and one Alembic revision,
`backend/app/routers/catalog.py` (new), `routers/sources.py`, `backend/app/sources/crawl.py`,
`backend/app/config.py`, `docker-compose.yml`, `frontend/src/api.ts`, `pages/Sources.tsx`,
`pages/Home.tsx`, `docs/catalog.md` (new), `docs/sources.md`, `AGENTS.md`.

### 4.1 Schema

One revision: `job_sources.backlog` (int, default 0), `job_sources.draining` (bool, default
false), `job_sources.refresh_requested_at` (nullable timestamp), and a table `gather_runs`:
`id`, `started_at`, `finished_at` (nullable), `host`, `sources_refreshed`, `jobs_added`,
`sources_failed`, `stopped_by`, `error`.

### 4.2 The program

```python
# backend/app/gather.py
@dataclass
class RunSummary:
    sources_refreshed: int
    jobs_added: int
    sources_failed: int
    stopped_by: str      # "all done", "time budget" or "lease held"

def run_once(budget_minutes: int) -> RunSummary: ...
# python -m app.gather           one run, then exit (the Cloud Run job)
# python -m app.gather --loop    a run every 30 minutes, or one minute after the last finished
#                                if that took longer (the Compose gatherer service)
# python -m app.gather --report  print the coverage table and exit
```

`run_once` follows PLAN.md section 4: take the lease
(`pg_try_advisory_lock(4242001)` on a connection held for the run), log the catalog line,
bootstrap markets, refresh the due sources most-overdue first until `budget_minutes` is
spent, do the company work, write the `gather_runs` row. In loop mode the first run starts
immediately, with no startup delay.

The rules to implement, each from PLAN.md section 4:

- **Due**: the table there. Every attempt stamps `last_refreshed_at`. An error on a source
  that has stored postings leaves it `active` with `last refresh failed: ...`.
- **Backlog and draining**: after a run, `backlog` is the count of fresh unfetched URLs
  left; `draining` is true when `backlog > 0` and the run stored at least one page in ten.
  A draining source is due on the next run.
- **Refresh request**: `POST /api/sources/{id}/refresh` (admin) sets
  `refresh_requested_at = now()` and answers 202; the gatherer clears it after the attempt.
- **Market bootstrap**: for each market in `GATHER_COUNTRIES` with no `active` board, call
  `propose_job_boards` once and store each answer as a `candidate`; repeat about monthly.
- **Caps** are `PAGES_PER_RUN` and `LLM_PAGES_PER_RUN`; their defaults change to 600 and
  150 here. Phase 1's `.env` values already set them.

### 4.3 The API side

- `main.py` no longer starts a loop. At start, the API and the gatherer compare the
  database's Alembic revision with the code's head and exit with a message naming both
  when they differ.
- `GET /api/catalog`, for any signed-in user:

```json
{
  "jobs": 1730,
  "markets": ["RO"],
  "sources_active": 9,
  "last_refreshed_at": "2026-11-16T10:02:11",
  "gathering": true,
  "stale": false
}
```

`last_refreshed_at` is the newest successful refresh of an active source, `gathering` is
whether any source is draining, and `stale` is whether nothing has been refreshed for two
intervals. `GET /api/sources/runs` (admin) returns the last twenty `gather_runs`.

- `Sources.tsx` shows per source its state (`draining`, `queued`, `failed` with its
  reason), `backlog`, and the last run's stored and failed counts. Refresh now says
  "queued".
- `Home.tsx` reads `GET /api/catalog` and shows a plain banner when `stale` is true.

### 4.4 Compose

Add a `gatherer` service beside `app`, from the same image and credentials:

```yaml
  gatherer:
    build: ./backend
    restart: unless-stopped
    env_file:
      - backend/.env
    environment:
      GOOGLE_APPLICATION_CREDENTIALS: /run/secrets/google_application_credentials.json
      LOG_FILE: /var/log/cv-applier/gatherer.log
      HTTP_PROXY: ""
      HTTPS_PROXY: ""
      http_proxy: ""
      https_proxy: ""
    secrets:
      - source: google_adc
        target: google_application_credentials.json
    volumes:
      - ./backend/logs:/var/log/cv-applier
      - ./backend/app:/app/app
    command: ["python", "-m", "app.gather", "--loop"]
    depends_on:
      - cloud-sql-proxy
```

Share `app`'s definition with a YAML anchor or `extends` instead of repeating it. A laptop
that only serves the API starts `docker compose up -d app`; the one that gathers starts
`gatherer` too, and the lease keeps two from running at once.

### 4.5 Run it, and measure

`docker compose up -d gatherer`, with `PAGES_PER_RUN=600` and `LLM_PAGES_PER_RUN=150`. Leave
it running. It continues while phases 5 and 6 are built. After the first full pass, run
`docker compose exec gatherer python -m app.gather --report` and write the table here:

| Source | Tier | Listed | Stored | Backlog | Yield | State |
| --- | --- | --- | --- | --- | --- | --- |
| (filled in after the first full pass) | | | | | | |

`Listed` is stored plus dead plus backlog, from the database. The gather period is over
when PLAN.md section 4's three conditions hold; the third needs phase 5.

**Verify**:

```
docker compose up -d gatherer && docker compose logs -f gatherer
```

1. The first lines, with nobody signed in, say `catalog: N jobs, M sources, K due` and
   start refreshing.
2. `docker compose kill gatherer && docker compose up -d gatherer`: it resumes; sources
   refreshed under 12 hours ago are skipped, and `psql "$CLOUD_DB" -c "select count(*) from
   dead_urls"` is not lower than before.
3. While the first gatherer is in the middle of a run (its log says so), start a second
   with `docker compose run --rm gatherer python -m app.gather`: it prints that the lease
   is held and exits. Between runs the lease is free, so a second one started then simply
   runs.
4. The revision check, on the **isolated** database only and never the shared one: stamp it
   one revision back with `alembic stamp PREVIOUS_REVISION` (the id is in `alembic
   history`) and start the app: it exits naming the two revisions. `alembic stamp head`
   puts it back. A unit test calls the check directly as well.
5. In the Sources screen, click Refresh on a source: it shows queued, and the gatherer
   handles it on its next run.

**Done when**: the five checks pass; `gather_runs` has rows; `GET /api/catalog` is correct;
after a day the stored counts have grown and the coverage table is recorded here.

Effort: 6 hours, plus the gather period running in the background.

---

## Phase 5. The feed

**Goal**: sign in, upload a CV, and see your jobs at once, from one query over the catalog,
with a score and a reason on every card.

**Files**: `backend/app/matching.py` (pure functions), `backend/app/routers/jobs.py`,
`backend/app/schemas.py`, `backend/app/routers/profile.py`, `backend/app/sources/crawl.py`
(`_upsert_job` fills `search_text`), `backend/app/backfill.py`, one Alembic revision,
`backend/app/feed_check.py` (new), `backend/tests/`, `frontend/src/api.ts`,
`pages/Home.tsx`, `pages/Profile.tsx`, `docs/matching.md` (new), `docs/frontend.md`.

### 5.1 Contract

`GET /api/jobs?query=&location=&mode=&days=&min_score=&sort=match|recent&page=1&page_size=50`

```python
class CatalogInfo(BaseModel):
    jobs: int
    markets: list[str]
    sources_active: int
    last_refreshed_at: datetime | None
    gathering: bool
    stale: bool

class JobResponse(BaseModel):
    id: int
    title: str
    company: str
    logo_url: str
    locations: list[str]
    work_mode: str
    experience_level: str | None
    employment_type: str
    excerpt: str                 # the first 400 characters of the description
    url: str
    apply_url: str
    posted_at: datetime | None
    first_seen_at: datetime
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    source: str
    also_on: list[str]           # other sources that list the same job
    reposts: int
    score: int | None            # 0 to 100 on sort=match, None on sort=recent
    reason: str
    application_id: int | None   # set once the user favorited or dismissed it (phase 6)
    favorite: bool

class JobSearchResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
    sort: str
    market_covered: bool
    catalog: CatalogInfo
```

The matching TypeScript types in `frontend/src/api.ts` are the same fields. The full
`description` is no longer sent to the browser.

### 5.2 The query

The design is PLAN.md section 6. In order:

1. **SQL narrows.** Location or remote eligibility on `jobs.country` and
   `eligible_countries`, not expired, inside the window, work mode, company not hidden,
   not dismissed by this user, duplicates collapsed on `fingerprint` preferring an
   employer source, and a text match of the profile's terms over a stored, normalized
   `search_text` column (company, title and the first 2,000 characters of the description,
   run through `textnorm.normalise` when a job is written).
2. **Python ranks the top 300** (`matching.py`): the boolean `keyword_query`, the salary
   rule, the seniority check, the score and the reason.
3. `sort=recent` skips step 2's scoring and pages in SQL.

Start with a GIN index on `to_tsvector('simple', search_text)` and match each term as a
prefix (`term:*`) so Romanian inflections meet. Normalizing in Python means no `unaccent`
extension is needed. If the first `EXPLAIN` on the real catalog shows it too slow or
missing real matches, try `pg_trgm`; decide from the plan and write the choice in
`docs/matching.md`. Also add an index on `(country, work_mode, posted_at)`.

The revision adds `jobs.search_text` (filled by `_upsert_job` from then on, and for stored
rows by `python -m app.backfill search_text`, which keeps the migration free of app code),
`profiles.hidden_companies` (list of normalized names) and `profiles.keyword_query`, and
the indexes. `PATCH /api/profile` accepts both profile fields.

`matching.py` is pure functions over plain data and is unit tested without a database: a
remote posting restricted to another country is dropped; an expired one is dropped; a
hidden company is dropped; a known-too-low salary is dropped while an unstated one passes;
two postings with one fingerprint make one match listing both sources; two postings at one
company with a near-copy description collapse and keep the earlier date; `pandas OR r`
keeps a description containing `R` as a word and drops one containing only `recruiting`;
and a senior title ranks below a junior one for a candidate with one year of experience.
The SQL step is tested on PostgreSQL against a small fixture catalog.

### 5.3 The screen

`Home.tsx`: a strip under the title reading `Searched 12,431 jobs, updated 2 hours ago` (and
`still gathering` or the stale banner), ranked cards with the score and the reason, the
sources a job also appears on, the filters it has now plus a minimum score and a sort,
`hide this company` which appends to `hidden_companies` through `PATCH /api/profile`, and
an honest empty state when `market_covered` is false. `Profile.tsx` gains the keyword query
and the list of hidden companies with an unhide control. The card shows `excerpt`, not
the description.

### 5.4 The ten-profile check

`python -m app.feed_check` runs the feed for ten stand-in profiles (sales, accounting, HR,
marketing, logistics, customer support, mechanical engineering, software, healthcare,
teaching), each with a handful of titles and skills in Romanian and English, `country=RO`
and `city=Bucuresti`. For each it prints the count and the top five titles. It runs against
the real database and is read by a person; it is not part of the test suite.

**Verify**:

1. A brand-new account uploads a CV. The log shows one model call (`extract_profile`) and
   the feed loads with no `Crawl started` line and no board discovery after the upload.
2. `python -m app.feed_check`: read each of the ten lists. Sales and accounting look like
   sales and accounting.
3. Time the query: `EXPLAIN (ANALYZE, BUFFERS)` on the candidate SQL, and ten page loads
   with `curl -w "%{time_total}"`. Median under 200 ms and 95th percentile under 500 ms
   once the catalog is large, or write down why not and what to change (an index, or
   `db-g1-small`).
4. Hide a company: its cards go and stay gone after a reload. A job on two boards shows
   once with both boards listed. A boolean query narrows the list.

**Done when**: all four hold, the unit tests pass, and `docs/matching.md` records the index
choice, the duplicate-overlap threshold taken from real pairs, and the measured latency.

Effort: 8 hours.

---

## Phase 6. Favorites, and the CV and the letter on a click

**Goal**: star a job and get two buttons that call the model only when clicked.

**Files**: `backend/app/models.py` and one Alembic revision, `backend/app/routers/applications.py`
(new), `backend/app/llm.py`, `backend/app/schemas.py`, `backend/app/routers/profile.py`,
`backend/app/routers/jobs.py` (favorite and dismissed flags), `backend/tests/`,
`frontend/src/api.ts`, `pages/Home.tsx`, `pages/Saved.tsx` (new), `router.tsx`,
`docs/applications.md` (new), `docs/llm.md` (new), `docs/frontend.md`.

### 6.1 Schema

`applications` gains `cover_letter_at`, `cv_advice` (JSON), `cv_advice_at`, `generating`
(nullable string: `cover_letter` or `cv_advice`) and `generating_since`. A new table
`llm_usage`: `id`, `user_id`, `kind` (`profile`, `cover_letter`, `cv_advice`), `created_at`,
index on `(user_id, created_at)`.

### 6.2 Contract

The endpoints and the `CvAdvice` and `BulletRewrite` models are in PLAN.md section 7. The
application as the API returns it:

```python
class ApplicationResponse(BaseModel):
    id: int
    job: JobResponse
    status: str              # matched, drafted, submitted, interview, rejected, discarded
    notes: str
    cover_letter: str
    cover_letter_at: datetime | None
    cv_advice: CvAdvice | None
    cv_advice_at: datetime | None
    created_at: datetime
    submitted_at: datetime | None
```

Errors: 409 `generation already running`, 429 `daily limit reached`, 400 when the profile has
no CV, 503 when Vertex AI is not configured, 502 when it fails.

### 6.3 The two calls

`draft_cover_letter(profile, job) -> str` and `improve_cv(profile, job) -> CvAdvice` in
`llm.py`, through the same client as every other call. Both:

- take the CV text and the posting, truncated to fixed lengths, with the posting between
  `<<<POSTING BEGIN>>>` and `<<<POSTING END>>>` markers and told that it is data and not
  instructions; markers printed by the page are stripped;
- run behind one place that logs `Model call: kind=... user_id=...`, records the
  `llm_usage` row, holds the process-wide semaphore (`LLM_MAX_CONCURRENT`) and retries
  once on a transient error;
- forbid invented facts (PLAN.md section 7), and `improve_cv` returns a JSON schema-checked
  `CvAdvice`; the letter is under 250 words in the language of the posting.

CV extraction on upload (`profile.py`) goes through the same place so it counts toward the
daily cap.

### 6.4 The guard rails, as code

Each of PLAN.md section 7's six has a test:

1. Favoriting, listing, opening the feed and dismissing never call the model (a test with
   a model stub that fails if called).
2. A second `POST` while `generating` is set and fresh answers 409; a stale marker (older
   than two minutes) is overwritten. The marker is set with a single conditional `UPDATE`
   and cleared in a `finally`.
3. A `POST` on an application that already has the result returns it without a model call
   unless `regenerate` is true and the last generation is older than 60 seconds.
4. The 21st call in a rolling 24 hours answers 429.
5. Inputs are truncated and the output length is capped.
6. With `LLM_MAX_CONCURRENT=1`, two simultaneous requests are served one after the other.

### 6.5 The screens

`Home.tsx`: a star on each card (toggle: `POST` to favorite, `DELETE` to remove when
allowed) and a Not interested action (`POST` with `status: "discarded"`). A favorited card
shows the two buttons. `Saved.tsx` at `/saved`: tabs Saved, Applied (submitted, interview,
rejected) and Dismissed; each saved job shows the two buttons, a drawer that shows the
result with a Copy button and a Regenerate button (disabled during the cooldown and while
running), a notes field and the status control with the apply link next to the "I applied"
confirmation.

**Verify**:

1. Star five jobs and open Saved: `select count(*) from llm_usage` has not moved.
2. Click Create cover letter on one: the count is +1, the letter reads like the CV and
   names the company and the role, and in the posting's language. Reload and open it
   again: no new row.
3. Click it twice quickly: the second answers 409 and the button is disabled while it runs.
4. Set `LLM_DAILY_LIMIT=2` and click a third: 429 with a plain message.
5. Click Improve my CV: `gaps` lists what the posting wants that the CV does not show, and
   the revised CV contains no employer, number or skill that the CV does not.
6. Move an application through `drafted` to `submitted`; an invalid move (`matched`
   straight to `interview`) is refused and `submitted_at` is set once.

**Done when**: the six checks pass, the guard-rail tests pass, and `docs/applications.md`
and `docs/llm.md` (every prompt, the untrusted-input rule, the language rules, the cost)
match what is built.

Effort: 6 hours.

---

# Part C - Open it up

## Phase 7. Deploy the API and UI

**Goal**: other people can sign in at a public URL, and the catalog serves them.

**Files**: `infra/main/main.tf`, `infra/main/variables.tf`, `backend/Dockerfile`,
`docker-compose.yml`, `backend/app/main.py`, `backend/app/routers/auth.py`,
`backend/app/routers/profile.py`, `frontend/src/pages/` (privacy note, delete account),
`docs/cloud.md`, `docs/frontend.md`, `docs/auth.md`.

### 7.1 Decide first

Before this phase starts, settle PLAN.md section 10's items 5, 8 and 9: what the feed shows
of a posting, each source's terms for a catalog several people read, and who may sign in.
Then the two things other people need:

- **A privacy notice**, one short page: what is stored (CV text and file, profile,
  favorites, generated text), where (Cloud SQL and the bucket in Frankfurt), who processes
  it (Google Cloud, and Vertex AI on each model call) and how to delete it.
- **`DELETE /api/auth/me`**, which removes the user's applications, profile, identities and user
  rows and their objects in the bucket, with a confirm step in the UI.

### 7.2 One image for both halves

`backend/Dockerfile` becomes a multi-stage build; the build context is the repository root
and `docker-compose.yml` and the build commands change to
`build: { context: ., dockerfile: backend/Dockerfile }`:

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
COPY backend/alembic.ini .
COPY backend/alembic alembic
COPY --from=frontend /frontend/dist static
RUN mkdir -p /var/log/cv-applier
ENV PORT=8000
ENV LOG_FILE=/var/log/cv-applier/app.log
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} \
    --proxy-headers --forwarded-allow-ips="*"
```

`main.py` serves `static/` and falls back to `index.html` for any path not under `/api`,
because React Router owns `/saved` and a reload there would otherwise be a 404. One image
and one origin means no CORS in production and a first-party session cookie.

With the repository root as the build context, add a root `.dockerignore` (`.git`,
`frontend/node_modules`, `frontend/dist`, `backend/.venv`, `backend/logs`, `backend/.env`,
`infra`, `**/__pycache__`). Without it `COPY frontend .` copies the host's `node_modules`
over the install the image just made, and the build context carries `backend/.env`.

### 7.3 Terraform

The repository, with its cleanup policy on the resource:

```hcl
resource "google_artifact_registry_repository" "backend" {
  location               = "europe-west3"
  repository_id          = "cv-applier"
  format                 = "DOCKER"
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 2
    }
  }

  depends_on = [google_project_service.apis]
}
```

Build and push by hand, tagged by commit and never `latest` (phase 9 explains why):

```
gcloud auth configure-docker europe-west3-docker.pkg.dev
TAG=$(git rev-parse --short HEAD)
docker build -f backend/Dockerfile -t europe-west3-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG .
docker push europe-west3-docker.pkg.dev/PROJECT_ID/cv-applier/backend:$TAG
```

The service, which also hosts the settings the refresh job shares in phase 8:

```hcl
locals {
  app_env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    GCS_BUCKET           = google_storage_bucket.uploads.name
    VERTEX_LOCATION      = "global"
    VERTEX_MODEL         = "gemini-3.1-flash-lite"
    COOKIE_SECURE        = "true"
    GOOGLE_CLIENT_ID     = var.google_client_id
    ADMIN_EMAILS         = var.admin_emails
    GATHER_COUNTRIES     = "RO"
    LLM_DAILY_LIMIT      = "20"
  }
  app_secrets = {
    DATABASE_URL         = "database-url"
    JWT_SECRET           = "jwt-secret"
    GOOGLE_CLIENT_SECRET = "google-client-secret"
  }
}

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

      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.app_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.values[env.value].secret_id
              version = "latest"
            }
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

`variables.tf` gains `google_client_id` and `admin_emails`. `allUsers` is the Terraform form
of `--allow-unauthenticated`: the app does its own session auth and Google sign-in is
what gates it. `ignore_changes` on the image stops the next unrelated `apply` from rolling
the live service back to the tag in this file; run `plan` and `apply` back to back, never
apply a saved plan from before a deploy.

`FRONTEND_ORIGIN` and `GOOGLE_REDIRECT_URI` need the service's URL. If `gcloud run services
describe cv-applier` shows the deterministic form `https://cv-applier-PROJECT_NUMBER.europe-west3.run.app`,
add both to `app_env` from `var.project_number`. Otherwise read the URL after the first
apply and set them by hand:

```
SERVICE_URL=$(gcloud run services describe cv-applier --region=europe-west3 --format='value(status.url)')
gcloud run services update cv-applier --region=europe-west3 \
  --update-env-vars="FRONTEND_ORIGIN=$SERVICE_URL,GOOGLE_REDIRECT_URI=$SERVICE_URL/api/auth/google/callback"
```

In the console: add `$SERVICE_URL/api/auth/google/callback` as a second authorized
redirect URI on the OAuth client (keep the localhost one), and either list each person as
a test user on the consent screen or publish it; `openid email profile` are basic scopes.

Cloud Run does not run migrations. Apply them from a laptop through the proxy before a
deploy that changes the schema, as in phase 2.

**Verify**: `$SERVICE_URL/api/health`, then a real Google sign-in with a second account at
`$SERVICE_URL/`, a CV upload, and the feed. A reload on `/saved` works. `gcloud run
services logs read cv-applier --region=europe-west3 --limit=50` shows no errors.
`terraform -chdir=infra/main plan` reports no changes.

**Done when**: another person signs in at the public URL, uploads a CV and sees their feed
without waiting for a crawl, `DELETE /api/auth/me` removes them completely, the privacy note is
linked from the app, and `terraform plan` is clean.

Effort: 5 hours.

---

## Phase 8. The refresh in the cloud

**Goal**: the 12-hour refresh runs without a laptop, with the job and its trigger in
Terraform.

**Files**: `infra/main/main.tf`, `docs/cloud.md`, `docs/catalog.md`.

The job runs the same image as the service with a different command. It reuses
`local.app_env` and `local.app_secrets` from phase 7 (the job does not need `JWT_SECRET`,
`GOOGLE_CLIENT_SECRET` or `COOKIE_SECURE`, but carrying them is harmless):

```hcl
resource "google_cloud_run_v2_job" "gather" {
  name     = "cv-applier-gather"
  location = "europe-west3"

  template {
    template {
      service_account = google_service_account.runtime.email
      max_retries     = 0
      timeout         = "7200s"

      containers {
        image   = "europe-west3-docker.pkg.dev/${var.project_id}/cv-applier/backend:TAG"
        command = ["python"]
        args    = ["-m", "app.gather"]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        env {
          name  = "GATHER_RUN_MINUTES"
          value = "90"
        }

        dynamic "env" {
          for_each = local.app_env
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = local.app_secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.values[env.value].secret_id
                version = "latest"
              }
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
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  name     = google_cloud_run_v2_job.gather.name
  location = google_cloud_run_v2_job.gather.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_scheduler_job" "gather" {
  name      = "cv-applier-gather-tick"
  region    = "europe-west3"
  schedule  = "0 */2 * * *"
  time_zone = "Europe/Bucharest"

  http_target {
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/europe-west3/jobs/cv-applier-gather:run"
    http_method = "POST"
    oauth_token {
      service_account_email = google_service_account.runtime.email
    }
  }
}
```

A job nests an execution template inside the job template, so the `ignore_changes` path has
one more `template[0]` than the service's. Copying the service's path compiles and does
nothing; check that `terraform plan` shows no image diff after a deploy.

Add an alert when the refresh stops working, so a silent stop cannot last four days: a
Cloud Monitoring absence alert on the job's completed executions with result `succeeded`,
for about 23 hours (the longest an absence condition allows), notifying the email channel
bootstrap already created. Confirm the metric name in Metrics Explorer when writing it.

### The first run, and the one real unknown

Run it once by hand, then compare with the laptop:

```
terraform apply
gcloud run jobs execute cv-applier-gather --region=europe-west3 --wait
```

For each source, compare what the job stored and which sources failed against the laptop's
last run. Cloud Run's addresses are a datacenter's, and some boards answer those with 403
where a laptop is fine. A source blocked from Google's addresses is marked failed with its
reason and is not retried under another identity. If most are blocked, keep the steady-state
refresh on a machine outside a datacenter and record that in `docs/cloud.md`.

If it works, stop the laptop's `gatherer` (the lease means leaving it on is also safe) and
let the scheduler own the cycle.

**Verify**: `gcloud scheduler jobs run cv-applier-gather-tick --location=europe-west3`, then
`gcloud run jobs executions list --job=cv-applier-gather --region=europe-west3`; the next
morning `select max(last_refreshed_at) from job_sources` is within the last two hours, and
a refresh-requested source from the admin screen is handled in the next run.

**Done when**: a forced run succeeds, the scheduled runs keep the catalog inside 12 hours,
the alert exists and fires when the job is paused for a day (pause the scheduler and wait,
or lower the duration for the test), and the datacenter comparison is written down.

Effort: 3 hours.

---

## Phase 9. Deploy on push

**Goal**: a push to `main` ends up serving traffic without a laptop in the loop.

**Files**: `cloudbuild.yaml`, `infra/main/main.tf`, `infra/main/variables.tf`, `docs/cloud.md`.

```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "backend/Dockerfile", "-t", "europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA", "."]
  - name: gcr.io/cloud-builders/docker
    args: ["push", "europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA"]
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args: ["run", "deploy", "cv-applier", "--image=europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA", "--region=europe-west3"]
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args: ["run", "jobs", "update", "cv-applier-gather", "--image=europe-west3-docker.pkg.dev/$PROJECT_ID/cv-applier/backend:$SHORT_SHA", "--region=europe-west3"]
options:
  logging: CLOUD_LOGGING_ONLY
```

The job's update step matters: without it the refresh job never sees a new image after the
day it was created, and a refresh running last month's code looks healthy while being wrong.

Connecting the repository (`github.com/CatalinIonescu0922/LazyJobs`) is the one step outside
Terraform: install Google's Cloud Build GitHub App under Cloud Build, Repositories,
Connect Repository, GitHub (2nd generation), and name the connection `cv-applier-github`.
The provider has no data source for a connection, so Terraform refers to it by its path
and builds the repository and the trigger on top:

```hcl
resource "google_cloudbuildv2_repository" "repo" {
  location          = "europe-west3"
  name              = "cv-applier"
  parent_connection = "projects/${var.project_id}/locations/europe-west3/connections/cv-applier-github"
  remote_uri        = "https://github.com/CatalinIonescu0922/LazyJobs.git"
}

resource "google_cloudbuild_trigger" "on_push" {
  location = "europe-west3"

  repository_event_config {
    repository = google_cloudbuildv2_repository.repo.id
    push {
      branch = "^main$"
    }
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
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}
```

The trigger's `service_account` must be the full `projects/.../serviceAccounts/...` path.
Left unset it silently falls back to a default account without these roles, and every run
fails with an "invalid argument" that names neither account. `project_number` is
`gcloud projects describe PROJECT_ID --format='value(projectNumber)'`, added to
`variables.tf`. Images are tagged `$SHORT_SHA` and not `latest`, so a revision always names
the commit it came from and a rollback has an earlier tag to return to. A change to the
schema still needs the migration applied from a laptop first.

**Verify**: push a trivial change to `main`; `gcloud builds list --region=europe-west3
--limit=5`; `gcloud run revisions list --service=cv-applier --region=europe-west3`.

**Done when**: the push produced a green build, a revision whose image tag is that commit's
sha, a refresh job on the same tag, and `gcloud artifacts docker images list
europe-west3-docker.pkg.dev/PROJECT_ID/cv-applier/backend` shows no more than two images.

Effort: 2 hours.

---

## Phase 10. Observability, cost and teardown

**Goal**: see what the deployed app and the gatherer are doing, see what they cost, and know
how to switch it all off.

**Files**: `backend/app/logging.py`, `backend/app/main.py`, `backend/app/gather.py`,
`docs/cloud.md`.

Log one JSON object per line on stdout so Cloud Logging lifts the keys into `jsonPayload`
(`severity` and `message` are the two it treats specially). Log what is worth asking later:
a gather run with its per-source counts, a model call with its kind and user id, a CV
upload, and a failed start-up revision check.

```
gcloud logging read 'resource.type="cloud_run_job" jsonPayload.event="gather_run"' --limit=20
```

Then the money: Billing, Credits and Reports. Cloud SQL should be nearly the whole bill.
Check the budget is still attached (`gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID`),
write the real monthly figure into PROGRESS.md and compare it with PLAN.md section 8.

### Teardown checklist

Almost everything is Terraform, so two `terraform destroy` runs undo almost all of it,
`main` first and then `bootstrap`, because `main`'s state lives in the bucket `bootstrap`
manages.

1. **Dump first.** `pg_dump` the database through the proxy to somewhere outside the repo
   and copy the uploads bucket (`gcloud storage cp -r gs://cv-applier-uploads-PROJECT_ID .`).
   The instance holds other people's data now.
2. `cd infra/main && terraform destroy`, then `cd ../bootstrap && terraform destroy`.
3. Uninstall the Cloud Build GitHub App from GitHub's Applications settings.
4. `gcloud projects delete PROJECT_ID` removes anything left, including what Terraform
   never made. It is the bigger hammer: wrong if you expect to apply again on this project.

To keep the data and drop most of the bill without destroying anything, stop the instance
(`--activation-policy=NEVER`). Storage is still billed, so the bill falls to about $2.

**Done when**: the log query returns structured rows, the monthly figure is recorded, and
the teardown checklist is in `docs/cloud.md`.

Effort: 2 hours.

---

# Part D - Later

Each item has a trigger. None blocks anything above.

## Phase 11. Retire gone jobs

Trigger: the catalog is large enough that jobs which left the boards are noticeably in the
feed, or the database size starts to matter.

Use `last_seen_at`, which has been written since phase 3. A job is a candidate for removal
when it has not been seen in the last three complete listings of its source, which is about
36 hours. The rules that make this safe:

- Only a **complete** listing counts. A sitemap or feed read that failed or was cut short
  marks nothing.
- Never remove more than a fifth of one source's jobs in one run; more than that looks like
  the site changing, not that many closures. This generalizes the rule Himalayas already
  uses (three gone at once and none open means doubt).
- **A job that an application points at is kept**, marked closed, because
  `applications.job_id` is a foreign key and a user's saved job must not vanish.
- Remove or soft-delete (`closed_at`) first and delete for real after a grace period.
- Whether a source's sitemap lists every live posting or only recent ones is measured per
  source before it is trusted for removal.

Effort: 4 hours.

## Phase 12. Wider reach

Each one has its own trigger; do them in the order the data asks for.

- **More ATS readers**: Workable, Recruitee and Ashby cover 23 of the 35 directory-matched
  boards found. Ashby also needs a decision, because its `robots.txt` answers 401 and the
  fetcher treats that as a refusal. SuccessFactors, Oracle Recruiting, Taleo and iCIMS when
  employers a user cares about are on them. Each is one small reader in `ats.py`.
- **Region-wide remote** (`EMEA`, `Europe`, `EU`, `Worldwide`, `Anywhere`) accepted on
  feeds alongside the markets: 8 of 23 matched boards, 350 roles including 238 at
  Canonical, are tagged that way.
- **Apply-link harvesting**: when a posting's `apply_url` is on a known ATS host, parse it
  with `parse_ats_url` and store it as an employer candidate without fetching the link.
- **A second market**: board discovery is already per market. What a new language needs is
  its synonyms and seniority words in `matching.py`, and a check that the prompt names real
  boards. Trigger: a user whose country is not covered.
- **Browser rendering with Playwright** for boards that are empty until a script runs.
  Trigger: a board fails with `needs a browser` in the coverage table; none has so far.
  The rules in PLAN.md appendix B apply unchanged, every browser request goes through the
  address guard, and where Chromium runs is decided from measured image size and memory.
- **Embeddings for paraphrased reposts**, when one still shows as a new job after the
  word-overlap check.

Effort: about 12 hours for the first four.

## Phase 13. Polish

Empty states that explain the next action, error toasts, loading skeletons, a README for
setup and how to run both halves, and a read of the diff against
[.cursor/rules/coding-style.mdc](.cursor/rules/coding-style.mdc) to strip any comment that
restates its code.

Effort: 2 hours.

---

## Documentation deliverables

Each phase ships its doc in the same change as its code, written for an agent with no prior
context: what the subsystem is for, where it lives, the contract it exposes, and the
constraints the code cannot show.

- Phase 1: `AGENTS.md`, the restart note.
- Phase 2: `docs/cloud.md` (Cloud SQL, the bucket, the proxy and the two modes, backups,
  `max_connections`, the trial date), `AGENTS.md` (how to run each mode and the tests).
- Phase 3: `docs/sources.md` (global sources, no profile input, dead URLs, admin-only),
  `docs/auth.md` (`is_admin`).
- Phase 4: `docs/catalog.md` (the catalog, the gatherer, the lease, the due rules, draining,
  the coverage report and what each status means), `docs/sources.md` (the scheduled refresh).
- Phase 5: `docs/matching.md` (the query, the filters, the score and reason, the duplicate
  threshold, the index choice, the latency measured), `docs/frontend.md` (Home).
- Phase 6: `docs/applications.md` (favorites, the lifecycle, the endpoints, the guard
  rails), `docs/llm.md` (every prompt, the untrusted-input rule, the language rules, the
  cost, why Vertex AI and not AI Studio).
- Phases 7 to 10: `docs/cloud.md` (topology, roles, the deploy command, the cost table and
  the teardown) and `docs/frontend.md` (how the bundle is built into the image and served).
- Phases 11 and 12: `docs/catalog.md` and `docs/sources.md`.

## Parallel work and subagents

The lead fixes the contracts first, then splits. These split cleanly:

- After phase 3, **phases 4 and 5 are independent.** The gatherer (`gather.py`,
  `sources/*`, `routers/sources.py`, `routers/catalog.py`, `Sources.tsx`) and the feed
  (`matching.py`, `routers/jobs.py`, `Home.tsx`, the profile additions) share only the
  `jobs` columns in PLAN.md section 5 and `CatalogInfo`, which phase 4's endpoint and phase
  5's response both use. Fix `CatalogInfo` first.
- Within phases 5 and 6, the API and its screen are separable once `backend/app/schemas.py`
  and `frontend/src/api.ts` agree. One subagent owns the router and modules, the other the
  page, and neither edits outside its files.
- Phase 8's Terraform can be written during phases 6 and 7. It depends only on the command
  `python -m app.gather`.
- In phase 7, the Dockerfile and static serving are independent of the Terraform.

Everything else is sequential. Subagent output is a proposal until the lead has run the
whole thing: Compose up, the gatherer running, two accounts signed in, and the output read.

## Totals and sequencing

About 44 hours to the end of phase 10, and about 18 more for the later phases. These are
rough, like the ones before them.

The first moment you can use it is the end of phase 2, when your data is safe. The first
moment it does what you described is the end of phase 5 (a new user sees their jobs at
once), and it is complete at the end of phase 6. The first moment someone else can use it is
the end of phase 7.

## Deferred, with triggers

- Cloud SQL high availability and a second environment: when losing an hour of data or an
  hour of service would actually matter.
- More markets than one laptop and one job can gather: when the gather no longer fits in
  the run budget, fan out per source.
- Auto-filling ATS forms: after the tracker proves the workflow, and only with the confirm
  step. Out of scope until then.
