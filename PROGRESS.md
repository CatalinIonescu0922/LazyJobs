# CV Applier - Build Progress

Live status for the phases defined in [BUILD.md](BUILD.md). This is the first file to
check to see exactly where the build stands; details of what each phase involves live in
BUILD.md, the reasoning behind the design lives in [PLAN.md](PLAN.md), and the reasoning
behind each individual decision lives in [LEARNING.md](LEARNING.md).

Status values: `not started`, `in progress`, `blocked`, `done`.

## Part 1 - Backend and frontend, running locally

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 1 | Application skeleton | done | verified: health 200, /docs 200, CORS preflight correct, 4 tables created |
| 2 | Data model for identity | done | verified: identities unique on (provider, subject); users has no password_hash |
| 3 | Google sign-in | done | verified: /me 401, unknown provider 404, unconfigured google 503, callback rejects missing state, second identity reuses the same user. Live Google round-trip needs GOOGLE_CLIENT_ID in .env |
| 4 | GCP project and guardrails | done | verified: both states in the tfstate bucket, bootstrap plan clean, 11 resources in main, Vertex call returned "Ready". Region europe-west3 |
| 5 | Local cloud-parity stack | done | Docker Compose, Postgres 16, fake-gcs-server, Alembic. SQLite and create_all removed |
| 6 | Frontend shell and sign-in | not started | first live Google login in a browser; needs the OAuth client from BUILD.md Prerequisites |
| 7 | CV upload and profile | not started | API plus Profile screen. Cloud Storage for the file, Vertex AI for extraction, adds `profiles.country`, `city` and `salary_currency` |
| 8 | Job sources and the generic crawler | not started | board discovery, validation, JSON-LD tier, Job boards screen, adds `job_sources`, fingerprints and salary |
| 9 | LLM extraction tier and coverage check | not started | the coverage table gets recorded in BUILD.md here |
| 10 | Matching and the Matches screen | not started | duplicate grouping including same-company description overlap, boolean keyword query, hidden companies, salary and seniority; adds `profiles.hidden_companies` and `keyword_query` |
| 11 | Applications, cover letters and the Tracker | not started | Vertex AI |

## Part 2 - Running on GCP

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 12 | Data plane | not started | Cloud SQL, bucket, secrets. The billing clock starts here, about $10 a month |
| 13 | First deploy | not started | Artifact Registry, Cloud Run, live Google sign-in |
| 14 | Scheduled refresh | not started | Cloud Run job plus Cloud Scheduler |
| 15 | Deploy on push | not started | Cloud Build trigger on main |

## Part 3 - Shipping the frontend

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 16 | Serve the UI from the image | not started | multi-stage Dockerfile, backend serves the build |
| 17 | Polish | not started | |

## Part 4 - Operating it

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 18 | Observability and cost hygiene | not started | structured logs, credit burn-down, teardown checklist |

## Part 5 - Extending reach

Block nothing; do them after the phase 9 coverage table says which is worth doing.

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 19 | Browser rendering for JavaScript-heavy boards | not started | Playwright; skip if the coverage table shows no such board. Decide where Chromium runs from measured size |
| 20 | Employers and their ATS feeds | not started | companies from the model, from an apply link, or from a pasted URL; Workday, SmartRecruiters, Greenhouse, Lever, Ashby, Workable, Recruitee; agencies labelled once and stored off |

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
- 2026-09-16: Terraform added to phases 4, 12 to 15, in two root modules,
  `infra/bootstrap` and `infra/main`, replacing one-off `gcloud` resource creation. The
  project itself, the database password, all secret values, and the GitHub App
  authorization for Cloud Build stay outside Terraform, each for a different reason
  recorded in LEARNING.md entries 21 to 26. No code changed.
- 2026-10-14: Phase 4 done. Fixed bootstrap `main.tf` (it no longer validated), imported
  the existing bucket, budget and channel into state, applied `infra/main`. Region is
  Region standardized to europe-west3 across PLAN.md and BUILD.md. State bucket was already there.
- 2026-10-26: Phase 5 done. The app container runs against Postgres 16 and fake-gcs-server.
  Alembic owns the schema. SQLite and startup `create_all` are gone.
- 2026-10-27: Plan reworked for a generic crawler and an earlier frontend. Twenty-one phases
  became eighteen. Phases 7 and 8 (eJobs and ATS adapters) became phases 8 and 9 (one
  generic crawler with Vertex AI board discovery, then an LLM extraction tier). The screens
  moved from part 3 into the phase that builds their API, and phase 6 is now the frontend
  shell. Old to new: 6 to 7, 7 and 8 to 8 and 9, 9 to 10, 10 and 11 to 11, 16 to 6 and 16,
  17 to 7, 18 to 10, 19 to 11, 20 to 17, 21 to 18; phases 12 to 15 are unchanged. Evidence
  gathered first: twelve boards probed, five need no per-site code, one needs the LLM tier,
  six refuse an honest crawler; one Vertex AI call returned 20 real domains for Romania,
  with three uncrawlable giants and two unreachable. `GOOGLE_CLIENT_ID` is still empty, so
  phase 6 is the first live login. Decisions in LEARNING.md entries 27 to 29. No code
  changed and nothing was deployed.
- 2026-10-27: Three ideas from a public write-up of a large job scraper folded into
  phases 7, 8 and 10: duplicate and repost tracking by fingerprint and `first_seen_at`,
  a hide-this-company action, and salary and seniority signals that stay deterministic.
  Declined the rest: employers' career pages (none of 12 readable by the crawler; one of
  12 found on an ATS), per-posting LLM extraction, proxies and Elasticsearch. Effort is now
  about 45 hours. Decisions in LEARNING.md entries 30 and 31. No code changed.
- 2026-10-27: Two phases added in a new part 5, after the coverage table in phase 9:
  phase 19, Playwright rendering for JavaScript-heavy boards, and phase 20, LinkedIn and
  Indeed through JobSpy. JobSpy was read before it was planned: it reaches Indeed with the
  key of Indeed's own iOS app and LinkedIn through pages whose robots.txt disallows us,
  with browser impersonation and proxy support. That breaks the crawler's no-evasion rule,
  so it is an explicit opt-in exception kept in one module. Twenty phases in five parts,
  about 52 hours. Decisions in LEARNING.md entries 32 and 33. No code changed; nothing run.
- 2026-10-27: JobSpy and all LinkedIn and Indeed work removed at your request, and phase 20
  became employers and their ATS feeds. Tested first: the model named the 10 largest
  employers in each of Bucharest, Cluj-Napoca and Timisoara; 18 of 30 careers URLs it gave
  were reachable; 5 of 30 companies had a feed we could read (SmartRecruiters for Endava and
  Continental, Workday for Accenture and Flex, Greenhouse for BearingPoint) and 4 had jobs in
  the city; one guessed feed, `accenture` on Recruitee, belonged to a different company.
  The profile gains `city`. About 55 hours. Decision in LEARNING.md entry 34, which
  supersedes 33. No code changed.
- 2026-10-27: Employer feeds are now also discovered from an apply link and from a pasted
  ATS URL, after a check that Greenhouse publishes no index of every board (`/v1/boards`
  is 404) while a company slug returns jobs. SmartRecruiters `country=ro` on Endava
  returned 81 postings. Phase 10 gains a boolean keyword query and a same-company
  description overlap so a rewritten repost keeps its earliest date. An agency is labelled
  once per company and stored switched off. About 59 hours. Decision in LEARNING.md
  entry 35. No code changed.

---

## How this file is maintained

Updated at the end of every phase, in the same change as the phase's code: flip its
status, add one line to the log with the date and a short note, and record any decision
the phase produced (for example, the coverage table from phase 9, or the first
real monthly bill from phase 12). Work stops for a quick check-in between phases rather
than running through all twenty in one pass.
