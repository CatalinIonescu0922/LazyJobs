# CV Applier - Plan

A shared catalog of job openings that is gathered continuously, with no user involved, and
kept in the cloud, plus a personal view of that catalog for each person who signs in. A
user's CV decides which jobs they see. For the jobs they favorite there are two buttons,
improve my CV for this job and write a cover letter for it, and the model runs only when
one of them is clicked.

This plan replaces the one written on 2026-09-16 and last revised on 2026-11-10. It starts
from where the project stands on 2026-11-16 (section 2) and changes direction in the ways
section 1 lists. [BUILD.md](BUILD.md) has the steps, [PROGRESS.md](PROGRESS.md) the live
status and [LEARNING.md](LEARNING.md) the reasons (entries 36 to 40 belong to this plan).

**At a glance, 2026-11-16.** The scheduled refresh has been down for four days, a
half-hour fix (phase 1). All the data is on one laptop, so persistence in Cloud SQL comes
next and before any feature (phase 2). Then sources and companies become global (3), a
gatherer fills the catalog with no user involved (4), a new user's feed is one query over
it (5), and favorites get the two on-click buttons (6). The free trial ends by 2026-12-23,
so the billing upgrade is part of phase 2. The next action is phase 1.

---

## 1. The shift

Until now the app was built around one user: sign in, upload a CV, and the app goes out to
find jobs for that CV. The direction now is the reverse. The app gathers as many jobs as it
can on its own, keeps them in a database in Google Cloud, and each user gets a filtered
view of what is already there.

| | Until now | From now on |
| --- | --- | --- |
| Who the crawl serves | One user: sources, companies and crawl choices belong to a user and follow that user's CV | The catalog: sources, companies and jobs are global, and the crawl follows the market, never a person |
| What a new user waits for | A crawl. After the CV upload one request discovers boards, discovers employers and fetches pages before it answers | Only their own CV upload. Showing jobs is one query over what is stored |
| Where the data lives | A Docker volume on one laptop | Cloud SQL in `europe-west3`. Laptops and Cloud Run are clients of it |
| What a fresh process does | Waits 60 seconds, then refreshes only for users who have a profile and a country | Reads the database at once and carries on from what is there, whether or not anyone is signed in |
| Freshness | Each source about every 12 hours, once per user | Each source about every 12 hours, once for everybody (kept) |
| Model calls for a user | CV extraction on upload; sitemap and board picking per profile | CV extraction on upload. Improving a CV and drafting a letter happen only when a favorite's button is clicked |
| Jobs that are gone | Hidden at search time when expired | The same for now. Deleting them is later; from now on each refresh records which jobs it saw |

Seven rules follow from that. Every later section and phase exists to make one of them true.

1. **The database lives in GCP and is the only source of truth.** Laptops and Cloud Run
   are clients of it. Nothing worth keeping lives in a Docker volume.
2. **Gathering never depends on a user.** It starts by reading the database, continues
   from what is there, and never starts because someone signed in.
3. **Everything gathered is global.** Sources, companies and jobs belong to the catalog. A
   user owns only their profile, their favorites and what was generated for them.
4. **A user's wait is bounded by their own CV upload.** Showing jobs is a query. No crawl,
   board discovery or refresh happens at sign-in, on upload or on search.
5. **Freshness is a schedule, not an event.** Every active source is refreshed about every
   12 hours, once, for everybody.
6. **A model call for a user happens only on a click**, one call per click, with a cache,
   an in-flight guard and a daily cap.
7. **Deleting gone jobs comes later; recording starts now.** Each refresh notes which jobs
   it saw, so the later cleanup has history to act on.

Terms used throughout. A **market** is a country the gatherer covers (`GATHER_COUNTRIES`,
default `RO`). The **catalog** is the global tables: `jobs`, `job_sources`, `companies`,
`ats_boards`, `dead_urls`. The **gatherer** is the one program that writes postings into
it. A **feed** is one user's filtered view of the catalog. A **favorite** is an
`applications` row in status `matched`.

---

## 2. Where we are now

Measured on 2026-11-16 against the local Docker stack, the repository, `gcloud` and the
test suite.

### What is built

| Area | State | Reference |
| --- | --- | --- |
| Sign-in | Google OpenID Connect, own session cookie, no passwords. Two Google accounts have signed in live; sign-out has not been observed | [docs/auth.md](docs/auth.md) |
| Profile | PDF and DOCX upload, text extraction, Vertex AI profile extraction, editable Profile screen | [docs/profile.md](docs/profile.md) |
| Frontend | Vite, React, TypeScript, Tailwind: Sign-in, Home (job list), Profile, Sources, Companies | [docs/frontend.md](docs/frontend.md) |
| Crawler | One generic sitemap crawler with a JSON-LD tier and a model tier, and a safe fetcher (robots.txt, address guard, one request a second per host) | [docs/sources.md](docs/sources.md) |
| Aggregator | Himalayas search API, with its credit link and closed-job removal | [docs/sources.md](docs/sources.md) |
| Employers | Greenhouse and Workday feed readers, the 12,244-board ATS directory, company seeding and feed probing, the Companies screen. SmartRecruiters is built and refused by its robots.txt | [docs/sources.md](docs/sources.md) |
| Cloud foundation | Project, Terraform state bucket, $50 budget alert, runtime service account, enabled APIs | [docs/cloud.md](docs/cloud.md) |
| Local stack | Docker Compose with the app, PostgreSQL 16 and a storage emulator; Alembic owns the schema | [AGENTS.md](AGENTS.md) |

### What the database holds

The local PostgreSQL container, 2026-11-16. It is the only copy.

- 2 users, both in Timisoara, both with a CV, and 0 applications.
- 1,730 jobs, 17 MB in all, descriptions averaging 2,400 characters: eJobs 746, HiPo 438,
  BestJobs 264, RemoteOK 100, Himalayas 93, Accenture (Workday) 35, MyJob.ro 20, eMAG 19,
  Veeam 15. By work mode, 1,276 onsite, 326 remote and 128 hybrid. 129 are already past
  their `expires_at`.
- 49 `job_sources` rows but only 30 distinct sources, because each user has their own copy
  of every board. HiPo is `failed` in one copy and `active` in the other.
- 1,192 `companies` rows for 631 distinct names, for the same reason.
- 12,244 `ats_boards`.
- The newest refresh is 2026-11-12 08:54.

How much of each board is stored, from the `new_urls` figure in the crawl log:

| Source | Stored | Listed, not fetched | Note |
| --- | --- | --- | --- |
| BestJobs | 264 | about 2,300 | model tier, 30 pages a run |
| HiPo | 438 | about 1,600 | |
| eJobs | 746 | not known | only 5 of its 68 category sitemaps are read, picked by the model for one profile |
| RemoteOK | 100 | about 24,600 | 95 to 100 of every 100 pages fetched are dead, and the list of dead URLs is lost on restart |
| MyJob.ro | 20 | 0 | 212,000 to 247,000 sitemap URLs, almost all older than 180 days |

So the store holds a tenth to a fifth of what BestJobs and HiPo list and an unknown share
of eJobs, and what it does hold follows the two owners' CVs: by a rough title count, 7% of
the stored jobs are sales roles and 23% are engineering roles.

### What is wrong today

1. **The refresh has stopped, and nothing said so.** The model gained a `dead_posting`
   column and a migration for it (`ae354c484b8a`) that was never applied: the database is
   at `f9a0b1c2d3e4`. The process running since 2026-11-12 08:57 loaded an earlier edit of
   the model that names the column `dead_postings`, so every query that loads
   `job_sources` fails with `column job_sources.dead_postings does not exist`. The
   scheduler runs that query on every tick: about 200 failed ticks are in the log, and
   none has succeeded since 2026-11-12 08:54. The job search and the Sources and
   Companies screens load the same table, so they fail the same way when next used; nobody
   has used them since 2026-11-11, which is why no failure was seen.
2. **Restarting does not fix it.** The container runs `alembic upgrade head` before it
   starts the server. That migration adds a NOT NULL column with no default to a table
   that has rows, which PostgreSQL rejects (reproduced on a throwaway table), so a
   restart would stop the app before it serves anything.
3. **78 of 424 tests error** (346 pass). The tests build their schema on in-memory SQLite,
   which cannot render the new `ARRAY` column. Production is PostgreSQL, so a test engine
   that differs is the wrong fix to keep.

### Why the present shape cannot do what section 1 asks

1. **Sources and companies belong to a user.** `job_sources` and `companies` carry
   `user_id`. Each user crawls and probes their own copy of the same sites: twice the
   requests and the model calls, and the copies disagree.
2. **The crawl is steered by a profile.** Vertex AI picks which 5 of eJobs' 68 category
   sitemaps to read for the profile's titles and skills, URLs are ranked by overlap with
   the profile's words, Himalayas is searched by the profile's first two titles, and
   Workday by the profile's city. A sales CV finds nothing there that was fetched for it.
3. **Nothing crawls without a user.** `refresh_due_sources` loops over users who have a
   profile and a country.
4. **A new user waits.** After the CV upload the Profile page calls `POST /api/jobs/search`
   with `refresh: true`. That one request can ask the model for boards and for employers,
   and crawls every source for that user at one page a second, before the response returns
   and the page moves on.
5. **The search is not a database query.** It loads the newest 500 rows of the user's
   sources and filters them in Python with substring matching, so older matches are never
   seen and "git" matches "digital".
6. **What the crawler learns is not kept.** Dead URLs live in an in-memory dict that is
   lost on every restart, and the half-built column that was meant to hold them is the
   cause of the outage above.
7. **Everyone can manage sources.** Any signed-in user can add, disable or refresh a
   source. In a shared catalog that is one person changing it for everybody, and it lets a
   user aim the server's crawler at a domain.
8. **The tests run on a different engine** from production, and the new work needs
   PostgreSQL features: advisory locks and text search.

### GCP today

`gcloud` shows the project `cv-applier-ionescu-catalin` (created 2026-09-22), the
Terraform state bucket (2026-09-24), the budget and the enabled APIs. There is **no Cloud
SQL instance, no uploads bucket and no Cloud Run service**. Everything the app has gathered
exists on one machine: one `docker compose down -v` or one disk failure from gone.

The state bucket needs billing, so the free trial started no later than 2026-09-24 and, if
it is the usual 90 days, ends no later than **2026-12-23**, about five weeks away. It may be
earlier: Billing, Credits shows the exact date. Section 8 explains why this matters for
persistence.

---

## 3. Scope and architecture

### In scope

- Sign in with Google. No passwords anywhere.
- CV upload in PDF and DOCX, parsed into a profile the user can correct, including the
  country and city, search preferences, a boolean keyword query and hidden companies.
- A catalog of jobs gathered from job boards that allow crawling, from remote-job
  aggregators with open APIs (Himalayas), and from employers' public ATS feeds, for each
  market. One generic crawler and a few small feed readers; no per-site board code.
- A feed per user: the catalog filtered by the profile, ranked deterministically, with a
  readable reason per match.
- Favorites, and on a favorite two actions that call the model only on a click: improve my
  CV for this job, and write a cover letter for it.
- A tracker: saved, drafted, submitted, interview, rejected, dismissed.
- Deployment on Google Cloud in `europe-west3`: Cloud SQL, Cloud Run for the API and UI,
  a Cloud Run job for the 12-hour refresh, Vertex AI, all in Terraform.

### Out of scope

- Automatic submission of applications. Nothing reaches `submitted` without a click.
- Browser automation that clicks, fills forms or signs in. A headless browser is allowed
  for one thing only, rendering pages that are empty until a script runs (phase 12).
- Passwords, and any storage of third-party logins.
- Paid third-party APIs, including job-data resellers and company directories.
- Working around a refusal. A site that blocks bots or forbids crawling is marked failed
  and left alone. LinkedIn and Indeed are out for that reason.
- Deleting gone jobs, until phase 11. Hiding expired ones at query time stays.

### Architecture

```mermaid
flowchart LR
  subgraph gatherer ["Gatherer (no user in it)"]
    Markets["Markets (GATHER_COUNTRIES)"]
    Boards["Boards and aggregator"]
    Feeds["Employer ATS feeds"]
  end
  subgraph api ["API (reads the catalog, never fetches a job page)"]
    Feed["Feed: the catalog filtered by a profile"]
    Fav["Favorites and tracker"]
    Act["On-click CV advice and letter"]
  end
  DB[("Cloud SQL: the catalog and every user's data")]
  Bucket[("Cloud Storage: uploaded CVs")]
  Vertex["Vertex AI"]
  UI["React UI"]

  Markets --> Boards --> DB
  Markets --> Feeds --> DB
  UI --> Feed --> DB
  UI --> Fav --> DB
  Fav --> Act --> Vertex
  Act --> DB
  UI -- upload CV --> Bucket
```

What a user's first visit looks like. The only slow step is the user's own upload.

```mermaid
sequenceDiagram
  participant U as User
  participant A as API
  participant D as Cloud SQL
  participant M as Vertex AI
  U->>A: upload CV
  A->>M: one call, extract the profile
  A->>D: save profile
  U->>A: open the feed
  A->>D: one query over the catalog
  A->>U: ranked jobs with reasons
  Note over A,D: no board discovery, no crawl, no refresh
```

| Process | Runs as | Writes | Never does |
| --- | --- | --- | --- |
| API and UI | Compose `app` locally; a Cloud Run service (phase 7) | users, profiles, applications, `llm_usage`, source rows on an admin's request | fetch a job page, discover boards, validate or refresh a source |
| Gatherer | Compose `gatherer` locally in a loop; a Cloud Run job (phase 8) | postings, `job_sources` state, `companies`, `dead_urls`, `gather_runs` | read a user's profile |

---

## 4. The gatherer

`python -m app.gather` is the one program that writes postings. It has no user in it. Its
inputs are the database and the markets in `GATHER_COUNTRIES`.

### One run

1. Open the database and take the **gatherer lease**, a PostgreSQL advisory lock. If
   another gatherer holds it, say so and exit. This is what keeps two laptops, or a laptop
   and the Cloud Run job, from crawling at once and breaking the one-request-a-second rule
   between them.
2. Look at the catalog and say what is there: `catalog: 1,730 jobs, 30 sources, 14 due`.
   The first thing a new process does is read the database, whoever is signed in.
3. For each market with no active board, ask the model once for boards and store each as a
   `candidate`. Validation, as it works today, promotes or fails each one.
4. Refresh the due sources, most overdue first, up to `CRAWL_WORKERS` at once, until the
   run's time budget (`GATHER_RUN_MINUTES`) is used. No new source starts after the budget;
   the ones running finish inside their page caps.
5. Do the company work: seed `companies` from stored postings, import the ATS directory
   when it is stale, match companies to boards, look up logo domains, and probe a few
   companies for feeds.
6. Write a `gather_runs` row (start, end, sources refreshed, jobs added, failures) and
   release the lease.

### What it reads, with no profile anywhere

| Kind of source | Until now | From now on |
| --- | --- | --- |
| Board with category sitemaps (eJobs has 68) | Vertex AI picks 5 for the profile's titles and skills | All of them, newest first across categories, inside the per-run page cap |
| Board with flat or numbered sitemaps | URLs ranked by overlap with the profile's words | Newest first |
| Aggregator (Himalayas) | Searched by the profile's first two titles and its country | A fixed list of about thirty job-family terms (sales, marketing, finance, support, design, data, engineering and so on), each searched with every market's country, rotated so all are covered each cycle |
| ATS feeds (Greenhouse, Workday) | Filtered by the profile's country; Workday searched by the profile's city | Accept a posting located in any market or open to any market (region-wide remote such as "EMEA" is phase 12); Workday searched by the market's country name |
| Company discovery | `companies` per user, seeded from that user's sources | One list, seeded from every active board and aggregator |
| Board discovery | `propose_job_boards(profile.country)` when a user searches | Once per market when it has no active board, and about monthly after that |
| Employer discovery by the model | `propose_employers(city, titles, skills)` | Removed. 0 of 12 model-named employers had a feed we could read |

Whether Himalayas answers an empty query with everything is not known; phase 3 checks it
and falls back to the term list if not.

### Resuming and concurrency

Everything the gatherer needs is in the database, so a process that was killed loses at
most the source it was on, and running that source again is harmless: upserts are keyed on
`(source, external_id)` and stored URLs are skipped before any fetch. What the crawler
learns is persisted: dead URLs in `dead_urls`, backlog and refresh state on `job_sources`,
which jobs it saw in `jobs.last_seen_at`.

The API never fetches a job page. An admin's Refresh button sets
`job_sources.refresh_requested_at` and returns; the gatherer picks it up on its next run.
That removes the case of two processes crawling one host.

### Which sources are due

| State | Due when |
| --- | --- |
| `active` | never refreshed; or last attempt older than `REFRESH_INTERVAL_HOURS` (12); or draining; or a refresh was requested |
| `candidate` | its feed is already known (as today), or a refresh was requested, or it was just proposed for a market |
| `failed` | 7 days after the last attempt, or when an admin asks |
| `disabled` | never |

Two rules keep a global catalog from losing sources to blips. Every attempt, successful or
not, stamps `last_refreshed_at`. And an error never parks a source that has stored
postings: it stays `active` with `last refresh failed: ...` and is tried again at the next
interval, as aggregators and ATS-backed employers already behave. Only a failed validation
marks a source `failed`. Today one DNS error is enough to park HiPo, a quarter of the store.

### Budgets and politeness

- Per source and run, `PAGES_PER_RUN` pages (default 600) on the JSON-LD tier and
  `LLM_PAGES_PER_RUN` (default 150) on the model tier, each at one request a second per
  host. A 600-page run takes at least ten minutes.
- **Draining.** After a run, `backlog` is the number of fresh, unfetched URLs left. If the
  backlog is above zero and the run stored at least one page in ten, the source is
  `draining` and is due again on the next tick instead of in 12 hours. With a 30-minute
  tick a host sees a request about every three seconds on average even while draining.
- **Low yield is not drained.** A source whose runs mostly hit dead pages (RemoteOK:
  95 to 100 in every 100) keeps the normal 12-hour cycle. Its dead URLs are remembered, so
  each run reaches further instead of repeating itself. A page that is already expired is
  recorded as dead and not stored.
- The model tier costs about a tenth of a cent a page. BestJobs' whole backlog, about 2,300
  pages, is about $2 to $3 once.

The caps and the tick are starting values; phase 4 measures and tunes them.

### The gather period

The gather period is not a mode switch. It is the state in which sources still have a
backlog: the same code on the same schedule, run until the catalog is as complete as the
boards allow. Phase 4 builds and starts the gatherer; the period then runs in the
background while phases 5 and 6 are built.

It runs on a laptop against Cloud SQL. A crawler spends nearly all its time waiting at one
request a second, and a Cloud Run job bills for every second it runs, so gathering around
the clock in the cloud would cost tens of dollars a month, several times the database. The
same program on a laptop costs nothing and writes to the same place.

It is over when the coverage report (`python -m app.gather --report`) says that:

- every active source has a backlog of zero, or is low-yield;
- for each source with a complete listing, at least 90% of what it lists is stored; and
- the ten-profile check from phase 5 returns a usable list for each of ten stand-in
  profiles (sales, accounting, HR, marketing, logistics, customer support, mechanical
  engineering, software, healthcare, teaching).

### Steady state: every 12 hours

Locally the Compose `gatherer` service loops every 30 minutes. In the cloud (phase 8) a
Cloud Run job runs `python -m app.gather` and Cloud Scheduler triggers it every two hours.
A trigger does only what is due, so most are a ten-second no-op, and a run that failed or
ran out of time is continued two hours later. It is a job and not a route on the API for
the reasons in entry 17: it takes minutes, it is privileged, and it has no user session.

One thing is unknown until tried. Cloud Run's IP addresses are a datacenter's, and job
boards sometimes answer those with 403 where a laptop is fine. Phase 8's first step runs
the job once and compares each source with what the laptop got. A source that is blocked
from Google's addresses is marked failed with its reason, as any other refusal; the
crawler does not try another identity. If many are blocked, the steady-state refresh stays
on a machine that is not in a datacenter.

### Seeing it work

- `gather_runs` records every run. `GET /api/catalog` tells any signed-in user how many
  jobs the catalog holds, which markets it covers, when it was last refreshed, whether it
  is still gathering and whether it is stale (nothing refreshed for two intervals). The
  feed shows a plain banner when it is stale.
- The admin Sources screen shows per source its state, backlog, the last run's stored and
  failed counts, and a Refresh that says "queued".
- On start, the API and the gatherer compare the database's migration revision with the
  code's head and stop with a clear message when they differ. A mismatch that was silent
  for four days becomes a failed start.

---

## 5. Data model

Defined in [backend/app/models.py](backend/app/models.py).

| Table | Scope | What it holds and what changes |
| --- | --- | --- |
| `users`, `identities` | per user | Unchanged. No password column |
| `profiles` | per user | CV text, parsed fields, `country`, `city`, preferences. Phase 5 adds `hidden_companies` and `keyword_query` |
| `applications` | per user | The favorites and the tracker, unique on `(user_id, job_id)`. Phase 6 adds the generated content and an in-flight marker |
| `llm_usage` | per user | One row per model call made for a user: `(user_id, kind, created_at)`. The daily cap counts these. Phase 6 |
| `jobs` | global | Unique on `(source, external_id)`. Adds `country`, `last_seen_at`; `fingerprint` is recomputed (below) |
| `job_sources` | global | Loses `user_id`; unique on `(kind, domain)`. Adds `country`, `backlog`, `draining`, `refresh_requested_at` |
| `companies` | global | Loses `user_id`; unique on `key` |
| `ats_boards` | global | The cached public directory of about 12,000 ATS boards. Unchanged |
| `dead_urls` | global | `(source, url, reason, seen_at)`, unique on `(source, url)`. Replaces the in-memory dict |
| `gather_runs` | global | The gatherer's record of each run |

`jobs` in more detail:

- `country` is the ISO code of where the job is located: the source's market, or the
  address when the posting states one. It is empty for a remote job, whose reach is
  `eligible_countries` (empty means worldwide).
- `last_seen_at` is set on insert and moved forward each time a refresh sees the job in
  the listing it reads: the sitemap, or the feed. It is the one column the later cleanup
  needs, it cannot be backfilled after the fact, and it stops `fetched_at` being used for
  two things (Himalayas treats it as "last confirmed").
- `fingerprint` is the hash of the normalized company, title and **city name** (the first
  location up to its first comma). Today the stored value uses the whole first location
  string, which boards write differently, so the code recomputes a key in Python on every
  search. Storing the city-name hash lets the database collapse duplicates.
- `fetched_at`, `first_seen_at` and `posted_at` keep their meaning. `first_seen_at` is set
  once and never moved, which is what lets a repost keep its earliest date.

Rows that already exist are merged by the phase 3 migration: one `job_sources` row per
`(kind, domain)` (an `active` one first, then the most recently refreshed) and one
`companies` row per `key` (a feed first, then a checked one). The 49 source rows become 30
and the 1,192 company rows become 631. Take a Cloud SQL backup first.

The schema is owned by Alembic, as before. A migration is applied from Compose or by hand
through the proxy and never from a starting Cloud Run instance, because several can start
at once.

### Application lifecycle

```mermaid
stateDiagram-v2
  [*] --> matched: user favorites a job
  [*] --> discarded: user dismisses a job
  matched --> drafted: cover letter generated
  matched --> discarded: user dismisses
  drafted --> submitted: user applies and confirms
  submitted --> interview
  submitted --> rejected
```

`matched` is shown as Saved. Removing the star on a job that has nothing generated and no
notes deletes the row; dismissing a job keeps a `discarded` row, which is what keeps that
job out of that user's feed. The move to `submitted` is only ever triggered by an explicit
user action. That is the core design commitment of the product.

---

## 6. Serving a user

### First sign-in

Sign in with Google, upload a CV, wait for the one model call that extracts the profile,
and open the feed. Nothing else is fetched. If the catalog does not cover the user's
country the feed says so and still shows the remote jobs open to them; if the catalog is
still gathering or stale, it says that too.

### The feed query

One query narrows, then plain Python ranks the few hundred that remain.

1. **In SQL, on indexed columns:** the job is located in the user's country, or is remote
   and open to it (`eligible_countries` empty or containing it); it has not expired; it is
   inside the recency window; it matches the work mode; the company is not hidden and the
   user has not dismissed it; duplicates are collapsed by `fingerprint`, preferring an
   employer's own feed over a board so the apply link goes straight to the company. The
   profile's terms (titles, skills, extra keywords) narrow by text match over a stored,
   normalized `search_text`, with prefix matching so Romanian inflections ("dezvoltator",
   "dezvoltatori") meet. Whether the index is full-text search or trigram is decided in
   phase 5 by running `EXPLAIN` on the real catalog.
2. **In Python, on the top 300 candidates:** the boolean `keyword_query`, the salary rule,
   the seniority check, the 0 to 100 score and the reason string.

The rules:

- **Hard filters.** Location or remote eligibility; not expired; not a hidden company; a
  stated salary in the user's currency whose top figure is below their minimum is dropped,
  and a posting with no salary or another currency passes (there is no exchange rate here,
  and most postings state none). The boolean query is words, quoted phrases, `AND`, `OR`,
  `NOT` and parentheses, with adjacent words meaning `AND`; a one-letter word such as `R`
  matches only as its own word; an empty query filters nothing.
- **Duplicates.** Postings with one fingerprint become one match. Inside one normalized
  company, a description with high word overlap against an older posting joins that group
  too, which catches a repost with a rewritten title. The threshold is chosen in phase 5
  from real pairs and written to `docs/matching.md`. A match lists the other places the job
  appears and counts reposts.
- **Score, 0 to 100.** Title overlap against the user's titles, skills overlap against the
  description, and a recency boost counted from the earliest of `posted_at` and
  `first_seen_at`, so a repost does not look new. A seniority check compares a level read
  from the title (intern, junior, senior, lead) with years of experience and takes points
  off a gap of two levels or more. No level word means no signal and no penalty.
- **Reason.** Every match stores a readable reason, such as "matches 7 of your skills:
  Python, FastAPI, Docker", with age and reposts appended when they matter, so the ranking
  is never a black box.

Text is normalized for Romanian diacritics, and a small synonym map handles the bilingual
market, where one role is posted as "Dezvoltator" or "Developer". The map is Romanian and
English only; for another language matching works on normalized overlap without synonyms.

Two sorts exist. `match` ranks the top 300 candidates and pages through them. `recent`
needs no scoring and pages through the whole filtered set in SQL, newest first.

### What the feed sends

The feed returns an **excerpt** (the first 400 characters of the description), the
company, location, salary, work mode, a credited link to the original posting and the
apply link. The full description stays on the server and is used for matching and for the
model calls on a user's favorites. This is the default for the question in section 10.

### Speed

Target: median under 200 ms and 95th percentile under 500 ms for a feed page, at 50,000
jobs, on the production database size. Phase 5 measures it and the result decides whether
`db-f1-micro` is enough (section 8).

---

## 7. Favorites and on-click actions

A star on a card creates the user's `applications` row for that job. A favorite, and only a
favorite, shows two buttons:

- **Improve my CV for this job** returns advice and a revised CV.
- **Create cover letter for this job** returns a letter.

```
POST   /api/applications                     {job_id, status?: "matched" | "discarded"}
GET    /api/applications?status=             the user's applications, each with its job
PATCH  /api/applications/{id}                {status?, notes?, cover_letter?}
DELETE /api/applications/{id}                only when matched, with nothing generated and no notes
POST   /api/applications/{id}/cover-letter   {regenerate?: bool}   one model call
POST   /api/applications/{id}/improve-cv     {regenerate?: bool}   one model call
```

Both `POST` actions answer with the whole application. The advice is structured so the
screen can show it and the user can check it:

```python
class BulletRewrite(BaseModel):
    original: str
    improved: str
    why: str

class CvAdvice(BaseModel):
    headline: str                  # a headline written for this job
    summary: str                   # a professional summary written for this job
    skills_to_lead_with: list[str] # from the CV's own skills, in the order this job wants them
    bullet_rewrites: list[BulletRewrite]   # at most 5
    keywords_to_add: list[str]     # words in the posting that the CV already supports but does not use
    gaps: list[str]                # what the posting asks for that the CV does not show
    revised_cv: str                # the CV rewritten for this job as plain text
```

Rules for both prompts, which belong in `docs/llm.md`:

- **Nothing is invented.** No employer, title, date, degree, number or skill that is not in
  the CV. A requirement the CV does not show goes in `gaps`, never into the text.
- **The posting is untrusted input.** It is passed as data between markers, as the page
  extractor does, the model has no tools, and the output is parsed into the fields above
  with length caps.
- **Language.** The letter is in the language of the posting. The CV advice keeps the
  language of the CV.
- **The user reviews everything.** Nothing is sent anywhere. A file export of the revised
  CV is later; today the user copies text.

### Guard rails: why a click cannot overload the system

1. **Never automatic.** Nothing calls the model when a job is favorited, when a list loads,
   in the background, or when a feed is built.
2. **One in flight.** A second click on the same button while its call runs answers 409.
   The marker is a column on the application (`generating`, `generating_since`), not a
   database lock held during the call, so the connection is free while Vertex AI works.
3. **Cached.** The result is stored on the application. Opening it again costs nothing.
   Regenerating is a second explicit click and is allowed after a 60-second cooldown.
4. **A daily cap per user**, `LLM_DAILY_LIMIT` (default 20), counted from `llm_usage`. Over
   it the answer is 429 with a plain message. CV extraction on upload counts too.
5. **Bounded input and output.** The CV and the posting are truncated to fixed lengths
   before the call and the output length is capped.
6. **Bounded concurrency.** A process makes at most a few model calls at once
   (`LLM_MAX_CONCURRENT`, default 4); the rest wait.

A call costs under a cent (about $0.25 per million input tokens and $1.50 per million
output tokens), so the cap bounds one user at about 10 to 20 cents a day.

---

## 8. Cloud

Everything is in one project in `europe-west3` (Frankfurt), except Vertex AI, which is
called on the `global` location because the global endpoint is the cheapest. Google brands
Vertex AI "Gemini Enterprise Agent Platform" now; this document says Vertex AI throughout.

### Persistence first

Section 2 is the reason: the catalog, two users' profiles and weeks of crawling exist on
one laptop. Phase 2 moves all of it to Cloud SQL and the real uploads bucket before any
feature work, and phase 1 comes first only because the schema must be consistent before it
is copied. After phase 2, a laptop is a client: `docker compose` starts the app and the
gatherer against the database through the Cloud SQL Auth Proxy, and a second laptop sees
the same data.

Persistence is only as durable as three things:

- **The disk.** Cloud SQL, with daily automated backups on from the start, and a
  `pg_dump` taken before any risky migration. A backup that has never been restored is a
  hope, so phase 2 restores one into a scratch database.
- **The process.** Nothing the app needs lives in a container or in memory (section 4).
- **The billing account.** A trial that ends stops the project's billable resources. A
  database in Cloud SQL is only as persistent as the billing account behind it, so
  upgrading the billing account before the trial ends is part of phase 2, not a later
  chore. The $50 budget alert stays in force.

### What runs where

| | Isolated local | Laptop and Cloud SQL | Cloud |
| --- | --- | --- | --- |
| Database | `postgres:16` container | Cloud SQL through the proxy container | Cloud SQL over the `/cloudsql/` unix socket |
| Uploaded CVs | storage emulator | the real bucket | the real bucket |
| API and UI | Compose `app` | Compose `app` | Cloud Run service `cv-applier` |
| Gatherer | Compose `gatherer` | Compose `gatherer` (the gather period) | Cloud Run job `cv-applier-gather`, triggered by Cloud Scheduler |
| Vertex AI | Vertex AI | Vertex AI | Vertex AI |
| Secrets | `backend/.env` | `backend/.env` | Secret Manager, injected as environment variables |

The isolated mode stays for offline work and for tests. The laptop mode is the default.

### The services and why those

| Service | What it does here | Why not the obvious alternative |
| --- | --- | --- |
| Cloud SQL, `cv-applier-db` | PostgreSQL 16, `db-f1-micro` to start, 10 GB SSD, one zone, daily backups. Reached through the Auth Proxy; the instance keeps its default address with an empty authorized-network list, so nothing on the internet can open a connection | Cloud Run instances are ephemeral and run concurrently, so a file database has no shared home. Firestore would give up the joins the feed needs. A private-IP-only instance needs a VPC and a connector for no gain here |
| Cloud Run service `cv-applier` | The API and the built UI, one image, one origin. `--min-instances=0`, `--max-instances=3`. The app does its own session auth | A VM bills while idle and needs patching. GKE is a control plane for one container |
| Cloud Run job `cv-applier-gather` | The refresh. Same image, command `python -m app.gather` | A route on the service would fight the request timeout, compete with users for instances and need a second auth scheme (entry 17) |
| Cloud Scheduler | One job that triggers the Cloud Run job every two hours | A scheduler tick that does nothing is cheaper than a missed refresh |
| Cloud Storage, `cv-applier-uploads-PROJECT_ID` | Uploaded CVs. Uniform access, not public | The container filesystem disappears with the instance |
| Vertex AI, `gemini-3.1-flash-lite` | CV extraction, board discovery, the model extraction tier, CV advice and letters (appendix B) | The Gemini API in AI Studio is the same model under a product the trial credit cannot pay for |
| Secret Manager | `jwt-secret`, `google-client-secret`, `database-url`. Terraform creates the containers; the values are set by hand | Terraform state is plaintext, so no credential goes through it |
| Artifact Registry | The image, tagged by commit sha, at most two kept | `latest` breaks the link between a revision and its code |
| Cloud Build | Builds and deploys on a push to main (phase 9) | Only that one laptop could ship otherwise |
| Cloud Logging | Structured JSON on stdout | The first 50 GiB a month is free |

### Sizing, and what would change it

Start on `db-f1-micro`: shared core, 0.6 GB of memory, about $10 a month with the disk. Two
things can outgrow it, and both are measured, not guessed:

- **Feed latency** at the real catalog size (section 6, Speed).
- **Connections.** A shared-core instance allows few concurrent connections (check
  `SHOW max_connections;` in phase 2; expect about 25), and the API's pool, up to three
  Cloud Run instances, the gatherer's workers and two laptops all draw from it. Every
  process sets an explicit small pool, and the total is kept under the limit.

If either fails, the fix is one line in Terraform (`db-g1-small`, roughly three times the
instance price) and a restart.

### Cost

| Item | About | Note |
| --- | --- | --- |
| Cloud SQL `db-f1-micro`, 10 GB SSD, daily backups | $10 to $12 a month | No free tier. The one fixed cost |
| Cloud Run service | $0 | Scales to zero; inside the free tier at this size. Re-check after a month |
| Cloud Run job | $0 to $2 a month | Two runs a day of 15 to 30 minutes fit the free CPU allowance. Around-the-clock gathering would not (section 4) |
| Vertex AI | cents | Backfill on the model tier about $3 once; each CV advice or letter under a cent |
| Storage, Secret Manager, Artifact Registry, Cloud Build, Scheduler, Logging | about $0 | Free tiers; keep two image tags |
| **Total** | **about $12 to $15 a month** | About $30 with `db-g1-small` |

The trial credit ends in about five weeks, so almost all of this is paid from the card after
that. The budget alert is the guard. When the trial ends without an upgrade it closes
rather than charging the card, and the app stops.

### Credentials and configuration

Application Default Credentials everywhere: `gcloud auth application-default login` on a
laptop, the attached service account on Cloud Run. No key file exists anywhere. The runtime
service account `cv-applier-run` has `cloudsql.client`, `aiplatform.user`,
`secretmanager.secretAccessor`, and `storage.objectAdmin` on the uploads bucket only.

Environment variables are the only configuration. In production Cloud Run injects the
secret ones from Secret Manager before the process starts, so the application never imports
a Secret Manager client.

| Variable | Isolated | Laptop and Cloud SQL | Cloud Run service | Cloud Run job |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://cv:cv@db:5432/cv_applier` | `postgresql+psycopg://cv:DB_PASSWORD@cloud-sql-proxy:5432/cv_applier` | secret `database-url`, unix socket | the same secret |
| `GCS_BUCKET` | `cv-applier-local` | `cv-applier-uploads-PROJECT_ID` | the same | not used |
| `STORAGE_EMULATOR_HOST` | `http://gcs:4443` | unset | unset | unset |
| `GATHER_COUNTRIES` | `RO` | `RO` | not used | `RO` |
| `REFRESH_INTERVAL_HOURS` | `12` | `12` | not used | `12` |
| `GATHER_RUN_MINUTES` | `25` | `25` | not used | `90` |
| `PAGES_PER_RUN`, `LLM_PAGES_PER_RUN` | `600`, `150` | `600`, `150` | not used | `600`, `150` |
| `ADMIN_EMAILS` | your email | your email | your email | not used |
| `LLM_DAILY_LIMIT`, `LLM_MAX_CONCURRENT` | `20`, `4` | `20`, `4` | `20`, `4` | not used |
| `COOKIE_SECURE` | `false` | `false` | `true` | not used |

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `JWT_SECRET`,
`FRONTEND_ORIGIN`, `GOOGLE_CLOUD_PROJECT`, `VERTEX_LOCATION` and `VERTEX_MODEL` are as
before. `REFRESH_INTERVAL_HOURS=0` no longer switches anything off: the loop is a separate
service and is simply not started.

### Terraform

Every resource is in Terraform in two root modules, `infra/bootstrap/` and `infra/main/`,
with state in the `cv-applier-tfstate-PROJECT_ID` bucket under separate prefixes. A config
file states the desired end state, `terraform plan` shows what would change, and
`terraform apply` is the only thing allowed to touch real infrastructure. The rules that
keep it safe:

- An API is enabled by exactly one module. `storage.googleapis.com` belongs to bootstrap.
- A secret's **container** is a Terraform resource; its **value** never is. State is a
  plaintext record, so no credential, including the database password, goes through it.
- The Cloud Run service's and job's **image** belongs to the deploy pipeline, so both carry
  `lifecycle { ignore_changes = [...image...] }` (the job's path has one extra `template[0]`).
  Always run `plan` and `apply` back to back; the provider sends the whole definition.
- Two things stay by hand: creating the project and linking billing, and installing
  Google's Cloud Build GitHub App (GitHub's own authorization flow).
- `deletion_protection = false` on the Cloud SQL instance, so the teardown checklist in
  phase 10 can destroy it. Every teardown starts with a dump, because the instance now
  holds users' data.

### Details that bite on the first deploy

- Cloud Run injects `PORT`; the container must bind `0.0.0.0:$PORT`.
- Cloud Run terminates TLS and sends `X-Forwarded-Proto`. Uvicorn needs `--proxy-headers
  --forwarded-allow-ips="*"` or the app builds an `http://` OAuth redirect and Google
  rejects it.
- `COOKIE_SECURE` is `true` on Cloud Run and `false` on `http://localhost`.
- PostgreSQL 15 and later do not let an ordinary user create tables in `public`. Users made
  through the Cloud SQL API are in `cloudsqlsuperuser` and can; if a migration says
  `permission denied for schema public`, run `GRANT ALL ON SCHEMA public TO cv;` as
  `postgres`.
- Never put `create_all` or an automatic migration on a Cloud Run start.

### The billing trap

The trial credit can pay for Vertex AI and cannot pay for the Gemini API in Google AI
Studio. They serve the same models and are different products with different billing paths,
and picking the wrong one is a card charge next to unspent credit. Every model call in this
project goes through Vertex AI.

---

## 9. Roadmap

Thirteen phases. Phases 1 to 10 are the plan; 11 to 13 are later and each has a trigger.
Effort is rough.

| Phase | What | What you get | Effort |
| --- | --- | --- | --- |
| 1 | Back to green | The refresh runs again, the schema and code agree, tests pass | 0.5 h |
| 2 | Persist in GCP | Cloud SQL and the real bucket hold everything; every laptop is a client | 3 h |
| 3 | One global catalog | Sources, companies and jobs are global; the crawl takes no profile input; sources are admin-only | 8 h |
| 4 | The gatherer | A separate process that resumes from the database, drains backlogs and reports coverage; the gather period starts | 6 h |
| 5 | The feed | Sign in, upload a CV, see your jobs at once from one query | 8 h |
| 6 | Favorites and on-click CV and letter | The star, the two buttons, the Saved screen | 6 h |
| 7 | Deploy the API and UI | Other people can sign in at a public URL | 5 h |
| 8 | The refresh in the cloud | The 12-hour refresh without a laptop | 3 h |
| 9 | Deploy on push | A push to main ships | 2 h |
| 10 | Observability, cost, teardown | JSON logs, the credit burn-down, a written teardown | 2 h |
| 11 | Retire gone jobs (later) | Jobs that left the boards leave the catalog | 4 h |
| 12 | Wider reach (later) | More feed readers, more markets, rendering | 12 h |
| 13 | Polish (later) | Empty states, errors, a README | 2 h |

About 44 hours to the end of phase 10.

Why this order:

- **1 and 2 first.** The data is on one disk and the schema is inconsistent; persistence
  comes before features, and phase 1 only because the schema must be sound before it is
  copied.
- **3 before 4.** Data ownership changes before the process that writes it is rebuilt.
- **4 early.** The feed is only as good as what is gathered, and gathering takes days, so
  it starts as soon as it can and runs while 5 and 6 are built. The first useful moment
  for you is the end of phase 5; the product you described is complete at the end of 6.
- **7 after 6**, because there is little to show other people before favorites exist.
  Nothing in 6 depends on it, so it can move earlier if you want others in sooner.
- **8 after 7**, because the job reuses the image and the Terraform.

### Not in this plan

Embeddings for paraphrased reposts, more ATS providers than phase 12 lists, a second
cloud environment, high availability, billing users, and anything that submits an
application. Each has a trigger in BUILD.md.

---

## 10. Decisions to confirm, and risks

### Defaults chosen, to confirm or change

Each has a default in the plan. Change any of them before the phase that needs it.

| # | Decision | Default | Needed by |
| --- | --- | --- | --- |
| 1 | Upgrade the billing account from the trial before it ends | Yes, in phase 2; read the end date in Billing, Credits | phase 2, before 2026-12-23 |
| 2 | Who may manage sources | The emails in `ADMIN_EMAILS`, your own to start | phase 3 |
| 3 | Markets | `RO` only; a user in another country sees remote jobs and a plain notice | phase 3 |
| 4 | Where the gather period runs | A laptop, writing to Cloud SQL | phase 4 |
| 5 | What the feed shows of a posting | An excerpt, the company, location, salary, a credited link and the apply link; the full text stays on the server | phase 5 |
| 6 | Database size | Start `db-f1-micro`; move to `db-g1-small` when a measurement says so | phases 2 and 5 |
| 7 | Daily model calls per user | 20 | phase 6 |
| 8 | Sources whose terms restrict passing jobs on (Himalayas, Remotive) | Keep Himalayas with its credit and apply link; re-read each source's terms before phase 7 | phase 7 |
| 9 | Who may sign in | Named test users on the consent screen until a privacy notice and delete-my-data exist, then publish | phase 7 |

### Risks

- **The trial ends in about five weeks.** If the billing account is not upgraded, the
  project's resources stop, and the database with them. Decision 1.
- **The sourcing question reopens.** The app began as a personal tool: descriptions were
  stored to rank and to draft letters and were not shown to anyone else, with the note that
  a hosted product would reopen the question. A catalog that several people read is that
  case. Himalayas asks for a credit link and forbids passing jobs on to other job boards or
  aggregators; Remotive's terms say the same. The feed's excerpt-and-link default, the
  credit lines and the apply links are the mitigation, and each source's terms are re-read
  before phase 7. If one is unclear, ask the site, as hiring.cafe's terms suggest, or drop
  that source from the shared catalog.
- **Other people's CVs are personal data**, in Frankfurt, processed by Google Cloud and
  sent to Vertex AI on each call. Before anyone else signs in there is a short privacy
  notice (what is stored, where, who processes it) and a delete-my-data action that removes
  the profile, the CV file and the applications.
- **The threat model changes.** The crawler fetches addresses given by a model or an admin,
  so the address guard stays a security control with tests. Making sources admin-only
  removes the case of any user aiming it at a domain. DNS rebinding was out of scope for a
  single-user tool; reread that decision before phase 7.
- **Cloud Run's addresses may be blocked by boards** that accept a laptop (section 4).
- **A gather period is polite but not free.** At one request a second per host and a duty
  cycle near one third, it averages about one request every three seconds per host. A host
  that answers 403 or 429 stops that source for the run, as always.
- **`db-f1-micro` may be too small**, for latency or for connections. Both are measured.
- **Coverage is partial by design.** About half of the boards probed were readable by a
  generic crawler (appendix A). More boards, employer feeds and rendering widen it; none
  needs per-site code.
- **Categories are only as good as the boards.** The stored mix follows two CVs today. The
  gather reads every category, and the ten-profile check says whether sales, accounting and
  the rest are really there.
- **Deleting a job a user favorited would break their application.** Phase 11 keeps any
  job an application points at.
- **Model quality.** CV advice can be wrong or bland. The prompts forbid invented facts and
  list gaps separately, and the user reviews everything, but the result is a draft.
- **Google OAuth in testing mode** allows only listed test users. Publishing the consent
  screen is a separate step; `openid email profile` are basic scopes.
- **Schema and code can drift**, as they did. The start-up revision check (section 4) and
  the test database being PostgreSQL are the guard.
- **Cold starts** are visible on the first request after an idle period, because
  `--min-instances=0`. Keeping an instance warm would add a standing charge to an app that
  is idle most of the day.
- **The Terraform state bucket** is what makes the cloud side reproducible. It has
  versioning and nothing deletes it casually.

---

## Appendix A. Evidence

Measured live between September and November 2026 with `robots.txt` honored, one request
per second per host and an identifying User-Agent.

### Can one generic extractor read many boards?

Twelve boards were probed: `robots.txt`, the sitemap, then two or three detail pages.

| Board | Result |
| --- | --- |
| eJobs.ro, HiPo.ro, Remotive, RemoteOK, We Work Remotely | Works. Detail pages carry a schema.org `JobPosting` in JSON-LD |
| BestJobs.eu | Allowed, but no JSON-LD. The posting is in a Next.js payload, so it needs the model tier |
| UndeLucram.ro | `robots.txt` allows crawlers, but its job sitemaps return 403 to an honest User-Agent |
| Jooble, Himalayas | Detail pages return 403 (Himalayas has a search API, used instead) |
| Jobicy | Detail pages return 429 |
| LinkedIn | `www.linkedin.com/robots.txt` disallows crawlers |
| Indeed | No sitemap in `robots.txt`; search pages return 403 |

Five of twelve need no per-site code, one needs the model tier, six refuse an honest
crawler. Four things in the probe became rules: a sitemap index names its children
unhelpfully (HiPo's `sitemap_joburi.xml` lists search pages and `sitemap_lastjobs.xml`
lists postings), so the model picks and the code verifies by extracting real postings; We
Work Remotely's JSON-LD has raw control characters, so the parser is lenient;
`robots.txt` is per host and the canonical host is resolved first; and remote postings
declare their audience (`TELECOMMUTE`, `applicantLocationRequirements`), which is what lets
matching drop remote roles that are closed to a user.

### Can the model name the boards for a country?

One call for Romania returned 20 real domains for under a tenth of a cent. Three of the
twelve "local" ones were LinkedIn, Indeed and Glassdoor, and two did not answer. So a
proposal is a candidate, never a source, and a domain can also be added by an admin.

### Can employers' own feeds be read?

Employers use an ATS, and most publish a JSON feed. Of 30 employers the model named in
three cities, 18 careers URLs were reachable and feeds we could read were found for 5; one
guessed slug (`accenture` on Recruitee) belonged to a different company, so a feed is
verified before it is trusted. Then `api.smartrecruiters.com/robots.txt` was found to allow
only LinkedInBot, which removed SmartRecruiters. Only Greenhouse and Workday remain
readable, and of the 12 employers the model named for Timisoara, none had a feed we may
read with a posting in Romania.

The better route was to seed `companies` from employers seen on real boards (399 at the
time) and match them to the public CC0 ATS directory: 35 matched (12 Ashby, 9 Greenhouse, 6
Workable, 5 Recruitee, 1 Workday, 1 Personio, 1 Rippling), and eMAG and Veeam were found
on Greenhouse. An ATS cannot be searched as one board: Greenhouse's `/v1/boards` is a 404
while `/v1/boards/stripe/jobs` returns jobs, and every other feed is one slug per request.

### Coverage, 2026-11-08

For a Timisoara DevOps profile, 6 of 21 sources were read and 395 postings stored. No board
failed with "needs a browser", so rendering (phase 12) has no board to test against yet.
Phase 4 records a new table for the catalog as a whole.

---

## Appendix B. Subsystems this plan does not change

- **Authentication** is Google OpenID Connect with the authorization code flow and PKCE;
  the session is the app's own JWT in an httpOnly, SameSite=Lax cookie; no Google token is
  stored; an account links to an existing email only when the provider reports it verified.
  See [docs/auth.md](docs/auth.md). This plan adds one thing: `GET /api/auth/me` reports
  `is_admin`, true when the email is in `ADMIN_EMAILS`.
- **CV parsing.** The upload goes to Cloud Storage under a per-user key, `pdfplumber` or
  `python-docx` produce text into `profiles.cv_text`, and one Vertex AI call returns the
  structured profile, including `country` and `city` from the address. The profile is fully
  editable because extraction will get things wrong. See [docs/profile.md](docs/profile.md).
- **The LLM module** is `backend/app/llm.py`. Every call is Vertex AI through the
  `google-genai` client with Application Default Credentials, model `gemini-3.1-flash-lite`
  on the `global` location, so there is no API key and no provider abstraction. The calls:
  `extract_profile` (on upload), `propose_job_boards(country)` (per market),
  `propose_domains` (company logos), the page extractor in `sources/llm_extract.py` (model
  tier), and, new in phase 6, `improve_cv` and `draft_cover_letter`. `pick_sitemaps` and
  `propose_employers` are removed in phase 3. If Vertex AI is unreachable the call fails and
  the endpoint says so; there is no keyless fallback.
- **The rules the crawler never breaks.** One request a second per host, longer when
  `robots.txt` asks, an identifying User-Agent and a page cap per run. `robots.txt` is read
  on the host that serves the page. A 403 or 429 marks the source failed for that run with
  no retry under another identity, proxy or browser. HTTPS only, and before every request
  and every redirect hop the host is resolved and refused if any address is private,
  loopback, link-local or reserved. URLs from a sitemap and redirect targets are fetched
  only on the source's own host or its `www.` counterpart. Responses are capped at 5 MB for
  a page and 20 MB for a sitemap. Descriptions are stored as plain text and rendered as
  text, never HTML. Page text sent to the model is untrusted input. A page that only renders
  in a browser is failed with `needs a browser` until phase 12. See
  [docs/sources.md](docs/sources.md) for the implementation.
