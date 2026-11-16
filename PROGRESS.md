# CV Applier - Build Progress

Live status for the phases defined in [BUILD.md](BUILD.md). This is the first file to check
to see exactly where the build stands. The design is in [PLAN.md](PLAN.md) and the reasons
behind each decision are in [LEARNING.md](LEARNING.md).

Status values: `not started`, `in progress`, `blocked`, `done`.

The phases were renumbered on 2026-11-16, when the plan was rewritten. The notes below say
which old phase each one continues ("old 8"); the log keeps the numbers that were current
on the day each entry was written.

## Current position

The scheduled refresh has not succeeded since 2026-11-12 08:54, and 78 of 424 tests error,
both from one unapplied migration (PLAN.md section 2). Phase 1 fixes both and is the next
action. Nothing is deployed, and all the data exists on one laptop.

## Foundation (built before the replan)

| Area | Status | Notes |
| --- | --- | --- |
| Application skeleton, identity model, Google sign-in (old 1 to 3) | done | two Google accounts have signed in live (2026-11-08 and 2026-11-11); sign-out has not been observed |
| GCP project and guardrails (old 4) | done | project, Terraform state bucket, $50 budget, runtime service account; no Cloud SQL, no bucket for uploads, no Cloud Run |
| Local stack: Compose, PostgreSQL 16, Alembic (old 5) | done | the storage emulator keeps files in memory only |
| Frontend shell and screens (old 6) | done | Sign-in, Home, Profile, Sources, Companies |
| CV upload and profile (old 7) | done | |
| Generic crawler and the model tier (old 8 and 9) | done, with gaps | dead URLs only in memory; sources are per user; the crawl follows a profile |
| Employers and the ATS directory (old 20, in part) | done, with gaps | Greenhouse and Workday readers, `companies`, directory matching, trickle probing, Companies screen. Not built: Workable, Recruitee and Ashby readers, region-wide remote, apply-link harvesting (phase 12) |

## Phases

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 1 | Back to green | not started | remove the unapplied `dead_posting` change, page caps as settings, restart; 30 minutes. Do this first |
| 2 | Persist in GCP | not started | Cloud SQL, uploads bucket, secrets, `pg_dump` migration, proxy in Compose, a backup restored, billing upgrade decided. Continues old 12 |
| 3 | One global catalog | not started | sources and companies lose `user_id`, no profile input to the crawl, admin-only sources, tests on PostgreSQL |
| 4 | The gatherer | not started | `python -m app.gather`, lease, resume, draining, coverage report, staleness; the gather period starts |
| 5 | The feed | not started | SQL narrowing, deterministic score and reason, boolean query, hidden companies. Continues old 10 |
| 6 | Favorites and on-click CV and letter | not started | the star, `applications`, guard rails, the Saved screen. Continues old 11 |
| 7 | Deploy the API and UI | not started | Cloud Run, Artifact Registry, the UI served from the image, privacy note, delete account. Continues old 13 and 16 |
| 8 | The refresh in the cloud | not started | Cloud Run job and Scheduler, datacenter-address comparison, staleness alert. Continues old 14 |
| 9 | Deploy on push | not started | Cloud Build trigger on main. Continues old 15 |
| 10 | Observability, cost, teardown | not started | continues old 18 |
| 11 | Retire gone jobs | not started (later) | needs the `last_seen_at` that phase 3 starts writing |
| 12 | Wider reach | not started (later) | more ATS readers, region-wide remote, apply-link harvesting, a second market, rendering. Continues old 19 and 20 |
| 13 | Polish | not started (later) | continues old 17 |

## Cloud spend and the credit clock

| | |
| --- | --- |
| Project | `cv-applier-ionescu-catalin`, created 2026-09-22 |
| Billing account | "My Billing Account", open |
| Free trial started | no later than 2026-09-24 (the state bucket, which needs billing, was created that day). Read the exact date in Billing, Credits and write it here: ___ |
| Free trial ends | no later than 2026-12-23 if it is the usual 90 days. Exact date: ___ |
| Billing upgraded to paid | not yet. Do it before the trial ends (phase 2) |
| Spent so far | not read: the billing API answered with a quota error on 2026-11-16. Nothing always-on exists, only the state bucket and Vertex AI calls. Check Billing, Reports |
| Predicted steady state | about $12 to $15 a month (PLAN.md section 8) |

Record the real monthly figure here once phase 2 has run for a month, so the estimate in
PLAN.md can be checked against what happened.

## Log

Entries up to 2026-11-10 use the phase numbers of the plan that was current then.

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
- 2026-10-27: Phase 6 built: Vite, React, TypeScript, Tailwind, TanStack Query and React
  Router in `frontend/`, with sign-in, a protected Home and the API wrapper. Checked: the
  backend redirects to Google with the configured client, `/api` proxies to port 8000, and
  a signed-out visit to `/` lands on `/sign-in`. Status stays in progress until a real
  Google sign-in and sign-out are run in a browser. Decision: sign-in is a plain link, not
  a fetch, because the login is a chain of redirects. See `docs/frontend.md`.
- 2026-10-27: Phase 7 built: CV upload and PDF/DOCX extraction, Vertex AI structured profile
  parsing, emulator-compatible Cloud Storage, profile migration and editor. Verified with
  the frontend build, container startup, migration head `7c4f1b8e2d9a`, and API health.
- 2026-10-27: Phase 8 built: generic board discovery, robots/address-safe sitemap fetching,
  JSON-LD `JobPosting` extraction, monthly salary and fingerprint fields, source API and
  Sources screen. Migration head is `8d2f3c4b5a6e`; focused crawler tests pass and the
  frontend build is clean. Live board discovery remains a browser verification step.

- 2026-11-08: Source coverage repaired after 19 of 20 sources showed red. Causes found in
  the logs: Docker injected a corporate proxy that dropped or rate-limited job-site
  connections (compose now blanks it); validation sampled the first three URLs of a
  flattened sitemap and so hit login and landing pages; eJobs' 68 category sitemaps were
  cut at 20, alphabetically, before any IT category; the career crawler never followed a
  link from a home page. Sitemap validation now probes job-looking child sitemaps, verifies
  by extracting postings and records `posting_prefix`; categories are chosen by Vertex AI
  for the profile. Phase 20 started with Greenhouse and SmartRecruiters readers, but
  SmartRecruiters' robots.txt forbids us, which removes the feeds behind Continental, Bosch
  and Aumovio. Workday was added to phase 20 (reads Accenture's 34 Timisoara postings from a
  pasted URL; Flex has none in Romania) and the phase 9 LLM tier was built, which turned
  BestJobs and MyJob.ro green. Result: 6 of 21 sources read, 395 postings stored, 33 shown
  for the profile. Decisions in docs/sources.md and the table in BUILD.md.
- 2026-11-09: Source work continued. Job search now hides duplicate and expired postings.
  Himalayas, a remote-jobs aggregator with a documented search API, was added as the first
  `aggregator` source (304 matches for devops in Romania; credit link and closed-job removal
  follow its terms). hiring.cafe was checked and refused: its pages and API answer an honest
  crawler with a Cloudflare challenge. Survey of 50 Romanian employers across Greenhouse,
  Lever, Workable and Recruitee found no Romanian posting. An in-process scheduler now
  refreshes active sources twice a day (phase 14's Cloud Run job is still not started).
- 2026-11-10: Company discovery and persistence added. `companies` seeds employers seen
  hiring on active boards and aggregators (399 companies), looks up domains via Vertex AI
  with a plausibility check for logos, imports the ~12,000-board public ATS directory into
  `ats_boards` (`directory.py`), matches companies by whole name (35 matched: 12 Ashby, 9
  Greenhouse, 6 Workable, 5 Recruitee, 1 Workday, 1 Personio, 1 Rippling), and probes a few
  on every 30-minute tick (`DISCOVERY_COVER_DAYS=5`), finding Veeam and eMAG on Greenhouse.
  Added `GET /api/companies` and the `/companies` screen. Tests now fail on any network
  access (`conftest.py`). Updated `PLAN.md` and `BUILD.md` to pull Phase 12 (Cloud SQL +
  GCS bucket via `cloud-sql-proxy` in Docker Compose, plus `pg_dump` migration of local
  data) ahead of Phases 10 and 11 so two laptops share one cloud database and bucket.

- 2026-11-16: Plan rewritten around a global catalog that is gathered without any user and
  kept in Cloud SQL, a per-user feed over it, and CV advice and cover letters for favorites
  that run only on a click. Thirteen phases replace the old twenty; old 1 to 9 became the
  foundation and the rest were renumbered (the mapping is in the tables above and in the
  header of LEARNING.md). The state was measured first, because the notes had drifted: the
  local database holds 1,730 jobs, 49 source rows for 30 distinct sources and 1,192 company
  rows for 631 names, for two users. The scheduled refresh has failed on every tick since
  2026-11-12, because the model has a `dead_posting` column whose migration was never
  applied and the running process loaded an earlier name for it, so nothing has refreshed
  for four days. A restart would crash the app, since the migration adds a NOT NULL column
  to a populated table. 78 of 424 tests error because they build the schema on SQLite,
  which cannot render the new ARRAY column. GCP has the project, the state bucket and the
  budget, but no Cloud SQL, no uploads bucket and no Cloud Run, and the free trial ends by
  2026-12-23. Nothing in the code or the running stack was changed. Decisions in
  LEARNING.md entries 36 to 40.

---

## How this file is maintained

Updated at the end of every phase, in the same change as the phase's code: flip its
status, add one line to the log with the date and a short note, and record any decision
the phase produced (for example, the coverage table from phase 4, or the first
real monthly bill from phase 2). Work stops for a quick check-in between phases rather
than running through the whole plan in one pass.
