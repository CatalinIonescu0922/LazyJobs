# CV Applier - Build Progress

Live status for the phases defined in [BUILD.md](BUILD.md). This is the first file to
check to see exactly where the build stands; details of what each phase involves live in
BUILD.md, the reasoning behind the design lives in [PLAN.md](PLAN.md), and the reasoning
behind each individual decision lives in [LEARNING.md](LEARNING.md).

Status values: `not started`, `in progress`, `blocked`, `done`.

## Part 1 - Backend, running locally

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 1 | Application skeleton | done | verified: health 200, /docs 200, CORS preflight correct, 4 tables created |
| 2 | Data model for identity | done | verified: identities unique on (provider, subject); users has no password_hash |
| 3 | Google sign-in | done | verified: /me 401, unknown provider 404, unconfigured google 503, callback rejects missing state, second identity reuses the same user. Live Google round-trip needs GOOGLE_CLIENT_ID in .env |
| 4 | GCP project and guardrails | not started | creates nothing chargeable. Budget alert goes in before any resource |
| 5 | Local cloud-parity stack | not started | Docker Compose, Postgres 16, fake-gcs-server, Alembic. SQLite dropped here |
| 6 | CV upload and profile | not started | Cloud Storage for the file, Vertex AI for extraction |
| 7 | eJobs source | not started | |
| 8 | ATS source and coverage check | not started | the Romania-eligible count gets recorded here |
| 9 | Matching | not started | |
| 10 | Applications API | not started | |
| 11 | Cover letters | not started | Vertex AI |

## Part 2 - Running on GCP

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 12 | Data plane | not started | Cloud SQL, bucket, secrets. The billing clock starts here, about $10 a month |
| 13 | First deploy | not started | Artifact Registry, Cloud Run, live Google sign-in |
| 14 | Scheduled refresh | not started | Cloud Run job plus Cloud Scheduler |
| 15 | Deploy on push | not started | Cloud Build trigger on main |

## Part 3 - Frontend

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 16 | Shell and sign-in | not started | also makes the Dockerfile multi-stage |
| 17 | Profile screen | not started | |
| 18 | Matches screen | not started | |
| 19 | Tracker screen | not started | |
| 20 | Polish | not started | |

## Part 4 - Operating it

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 21 | Observability and cost hygiene | not started | structured logs, credit burn-down, teardown checklist |

## Cloud spend

Nothing is billed yet. No GCP project exists. Record the real figure here once phase 12
creates the first chargeable resource, so the estimate in PLAN.md section 4 can be checked
against what actually happened.

| | |
| --- | --- |
| Billing account created | not yet |
| Credit expires | 90 days after that date |
| Spent so far | $0 |
| Predicted steady state | about $12 a month |

## Log

- 2026-09-15: Phase 1 done. Note: config.py, db.py, models.py and requirements.txt from
  the pre-plan scaffolding had gone missing from disk; recreated them as documented in
  PLAN.md's Current state section (password-based User, no Identity table yet) before
  building main.py, the extended config, .env.example and .gitignore on top.
- 2026-09-16: Phase 2 done. Removed `password_hash`, added `name` / `avatar_url` /
  `last_login_at` on User, added Identity with `uq_identity_provider_subject`, dropped
  bcrypt, deleted `cv_applier.db` and recreated the schema. AGENTS.md added (missed in
  phase 1).
- 2026-09-16: Phase 3 done. Google OIDC login/callback, JWT session cookie,
  find-or-create with verified-email linking. Live browser sign-in not run:
  `GOOGLE_CLIENT_ID` is still empty.
- 2026-09-16: Plan reworked for GCP after a $300 / 90-day free trial credit became
  available. Fourteen phases became twenty-one in four parts: phases 4 and 5 are new and
  come before the remaining backend work, the old phases 4 to 9 shifted to 6 to 11, part 2
  is the new cloud deployment work, and phase 21 is new. SQLite is dropped for PostgreSQL
  everywhere, the LLM moves from an OpenAI-compatible key to Vertex AI, and LEARNING.md
  was added as the decision log. Decisions recorded: Vertex AI rather than the AI Studio
  Gemini API, because the credit cannot pay for AI Studio; prove everything under Docker
  Compose before creating a chargeable resource, so the credit is spent on a system that
  already works; Alembic in phase 5 rather than at deploy time, because `create_all` races
  across Cloud Run instances. No code changed and nothing was deployed.

---

## How this file is maintained

Updated at the end of every phase, in the same change as the phase's code: flip its
status, add one line to the log with the date and a short note, and record any decision
the phase produced (for example, the Romania-coverage number from phase 8, or the first
real monthly bill from phase 12). Work stops for a quick check-in between phases rather
than running through all twenty-one in one pass.
