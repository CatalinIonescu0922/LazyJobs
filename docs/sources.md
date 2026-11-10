# Job sources

One generic crawler reads job boards, a model reads the pages that carry no structured
data, and one small reader per applicant-tracking system (ATS) reads employers. Sources are stored in `job_sources`; every posting ends up in the
shared `Posting` shape and the `jobs` table.

Code lives in `backend/app/sources/`: `fetch.py` (network guard), `crawl.py` (boards),
`career.py` (employers), `ats.py` (ATS feed readers), `extract.py` (JSON-LD),
`llm_extract.py` (the model tier). The API is
`backend/app/routers/sources.py`; the automatic refresh is in `backend/app/routers/jobs.py`.

## Workflow

- `POST /api/sources/discover?kind=boards` asks Vertex AI for board domains for the
  authenticated profile country and stores new domains as `candidate` sources.
- `POST /api/sources` adds a board domain manually.
- `POST /api/sources` also accepts a full HTTPS career-page URL. These `career` sources
  fetch the supplied page and same-domain career/job links, then extract `JobPosting`
  JSON-LD.
- `POST /api/sources` with a Greenhouse, SmartRecruiters or Workday company URL creates an
  `employer` source whose feed is already known, so it skips the career-page search. That
  company has no domain of its own and the column must be unique, so `domain` is
  `{slug}.greenhouse.io`, `{slug}.smartrecruiters.com`, or
  `{site}.{tenant}.myworkdayjobs.com` (a Workday tenant can run several careers sites).
  Workday cannot be found any other way than a pasted URL or a link on the company's own
  pages, because tenant, cluster and site cannot be guessed from a domain.
- `POST /api/sources` with `https://himalayas.app` creates an `aggregator` source (below).
- `POST /api/sources/discover?kind=employers` asks Vertex for up to 15 employers in the
  profile city and country using the candidate's titles and skills, then stores their
  websites as `employer` sources.
- `POST /api/sources/{id}/refresh` validates a candidate or failed source, then reads
  postings.
- `PATCH /api/sources/{id}` enables or disables a source.

The automatic refresh (after the first CV upload and on a search with refresh) only
touches `active` sources, or every `candidate` when none is active yet. A `failed` source
is retried only by its Refresh button. A failed source keeps a plain-language reason.

## Boards: validation (`crawl.py`)

The sitemap is the `Sitemap:` line of robots.txt, else `/sitemap.xml`. A sitemap index is
expanded one level without reading every child:

1. Children whose file name says they list landing pages are dropped: `by` (as in
   `jobs_by_city`), tags, users, companies, employers, cities, domains, skills, articles,
   pages, general, sections, categories, expired. The rest are tried in order, job-looking
   names first, at most four.
2. For each candidate, three pages spread across it are fetched. Two must yield a
   `JobPosting` with a title and a description. Sampling is spread out because a flat
   sitemap lists its home page and section pages first.
3. The first candidate that passes stores `sitemap_url` (the root), `posting_prefix`, the
   folder the good URLs share, and `extraction = jsonld`.
4. If no candidate passes and Vertex is configured, the first group that had pages but no
   JSON-LD is tried once more with the model tier (below), on the same three fetched pages.
   Two must yield a posting; the source then stores `extraction = llm`. A hopeless source
   therefore costs three model calls and not one per candidate.

Only entries whose `lastmod` is within the last 180 days count, in validation and in
refresh. Entries with no real date (missing, 1970, 0001) are kept. This is what keeps an
archive sitemap from validating: MyJob.ro lists 212,094 URLs, mostly 2005 to 2013, and only
15 are recent. A sitemap with entries but none recent fails with `sitemap has no postings
from the last 180 days`.

The prefix matters because some sitemaps mix postings and landing pages. HipoJobs has
`sitemap_joburi.xml` (category pages, no JSON-LD) next to `sitemap_lastjobs.xml` (real
postings); the refresh keeps only URLs under the prefix, so the wrong file is harmless.

## Boards: refresh (`crawl.py`)

The root sitemap is read again each time. When it is an index, the same name filter
applies and then:

- Up to 5 candidates are all read.
- More than 5 candidates that differ only by a number (`sitemap-jobs-1.xml`, `-2.xml`)
  are numbered shards: the first 5 are read, newest first, with no model call.
- More than 5 candidates with different names are categories (eJobs has 68). Vertex AI
  picks the 5 that suit the profile's titles and skills. If that call fails the first 5
  are read, which for a category board is usually the wrong 5, so a Vertex outage shows up
  as irrelevant jobs and not as an error.

URLs outside `posting_prefix` and URLs already stored are dropped before the cap, so each
refresh reaches further than the last. The rest are sorted newest `lastmod` first, which
keeps document order when every entry has the same date (RemoteOK says 1970 for all), and
only the freshest 300 are kept. Within those, a URL whose slug contains a word from the
profile (4 letters or more) comes first, and the top 100 are fetched. Relevance never
reaches past the freshest window, because the best slug match in a whole sitemap is often
an expired posting. The ranking is a hint and not a filter; the job search applies its own
profile filter afterwards.

A posting page that answers 404 or 410, or that is not a posting (no JSON-LD, or the model says
so), is remembered per source in memory and not requested again until the app restarts. A
closed posting stays in the sitemap, and without this every scheduled run re-asks for the same
dead pages: RemoteOK showed 95 failures in every 100 requests on 2026-11-10. A block (403,
429) is not remembered, since the page may be fine.

A sitemap's URLs are also grouped by top folder during validation, job-looking folders
first and at most two groups, because a flat sitemap can hold postings next to company and
article pages.

## Why a source is red

The reason is shown in the Sources screen. What each one means:

| Reason | Meaning and what to do |
| --- | --- |
| `source request failed (X)`, `robots.txt could not be read (X)` | The connection failed; X is the exception. Check the proxy first: Docker injects the host's proxy into containers and compose blanks it, see AGENTS.md. |
| `blocked (403)`, `blocked (429)` | The site refuses an honest crawler. There is no retry with another identity. |
| `disallowed by robots.txt` | robots.txt forbids this crawler. SmartRecruiters' API does for everyone except LinkedInBot. |
| `site redirects to HOST` | The domain moved. Add the new domain as a source. |
| `no sitemap found (...)` | Neither robots.txt nor `/sitemap.xml` gave a sitemap. |
| `no job sitemap found` | The index lists only landing-page files. |
| `job pages have no JobPosting data` | The pages carry no JSON-LD and Vertex is not configured, so the model tier was not tried. |
| `job pages have no JobPosting data and the model found no posting in them` | The model tier ran and the sampled pages were not job postings (Wellfound). |
| `sitemap has no postings from the last 180 days` | The sitemap is an archive. |
| `linked X feed has no posting in your country or cannot be read` | The careers page links to a Greenhouse, SmartRecruiters or Workday feed that `find_feed` rejected; the log line `ATS feed rejected` has the exact cause. |
| `set a job title and a country in your profile` | An aggregator source searches by the profile's first two titles and its country, and one of them is empty. |
| `last refresh failed: X` | An aggregator or an ATS-backed employer source hit an error (a 429, say). It keeps its status so the next scheduled run, an interval later, tries again. An aggregator's very first failure marks it failed instead. |
| `careers site uses X, which is not supported yet` | The careers page links to an ATS that has no reader here. |
| `needs browser rendering` | The page is a script shell (phase 19). |
| `no JobPosting data found` | An employer page with no JSON-LD and no recognisable ATS. |

## The model tier (`llm_extract.py`)

`extract_llm(html, url=..., source=...)` returns the same `Posting` as the JSON-LD tier, or
`None`. It never raises: with Vertex unconfigured it returns `None` without calling the
model, and any failure logs one warning naming the URL and the cause.

- The model sees a fixed prompt and then the page between `<<<PAGE CONTENT BEGIN>>>` and
  `<<<PAGE CONTENT END>>>`. The prompt calls the page untrusted data and tells the model to
  ignore instructions in it; marker text printed by the page is stripped so it cannot close
  the block early. The model has no tools.
- The page content is the visible text first (scripts, styles, nav, header, footer,
  noscript and svg removed), then each `application/json` and `application/ld+json` script,
  at most 6,000 characters per blob and 40,000 in total. BestJobs' `__NEXT_DATA__` is about
  360 KB, 349 KB of it one translation table that comes first, so any dict or list with
  more than 100 entries is dropped before the cap. The posting itself is under
  `props.pageProps.job`. BestJobs pages state no posting date anywhere, so `posted_at` is
  always empty there and the sitemap `lastmod` is the only date.
- The answer is parsed into capped fields: title 200, company 200, five locations of 200,
  employment type 60, description 20,000 plain-text characters, at least 80 to count.
  `is_job_posting` must be exactly `true`. Salary is converted to monthly, and dropped when
  the currency is not ISO 4217, a number is negative or not finite, the period is unknown,
  or the figure would overflow the 32-bit column.
- Cost, measured on BestJobs: about 3,700 input and 200 to 800 output tokens a page, 2 to 3
  seconds, roughly a tenth of a cent. Refresh reads at most 30 pages a run on this tier.
- The model cannot tell an expired posting from a live one: it read an archived 2011
  MyJob.ro page as a valid posting. The 180-day window on `lastmod` is what guards against
  that, so a source whose sitemap has no real dates can store expired postings on this tier.

## Employers and ATS feeds (`career.py`, `ats.py`)

Employer sites rarely show postings in their HTML. Measured on twelve Timisoara employers,
following career links from the home page found no `JobPosting` page on any of them, so
the crawl is not extended. The ATS behind the careers site publishes a JSON feed instead.

`refresh_career_source` goes in this order: a source that already has `ats_provider` and
`ats_slug` reads its feed directly; otherwise the page is fetched and `find_feed` looks
for a feed; only when none is found does the old JSON-LD crawl run. If the company site
cannot be fetched at all, `find_feed` still tries slug guesses before the source fails.

`find_feed(domain, pages, country)` tries ATS links found in the HTML first, then slugs
guessed from the domain label (`continental.com` gives `continental`; a hyphenated label
is tried with and without the hyphen), at most 4 guesses and 10 requests. A feed is
accepted only if it has a posting in the profile's country. A guessed slug must also have
a company name that agrees with the domain, which is what rejects the unrelated `flex`
board on Greenhouse. A linked slug skips the name check.

`read_feed(feed, domain, country, known, limit, city=...)` returns up to 100 new
in-country postings, newest first, skipping stored `external_id`s before any detail
request. `Posting.source` is the source's `domain`, because the search joins on it. `city`
is the profile's city and only Workday uses it.

Providers:

- **Greenhouse** works. One request with `content=true` returns everything, about 20 KB
  a job, and `SafeFetcher`'s 5 MiB cap means a board of roughly 250 jobs or more fails
  with `response was too large`. `location.name` is often a bare city, so the country is
  matched in the office entries that only `content=true` returns; the lighter list that
  `find_feed` uses can therefore miss a board whose Romanian jobs are named by city only.
  Boards on a company's own domain tell jobs apart only by `?gh_jid=`, so that one query
  parameter stays in `external_id`.
- **Workday** has no documented feed; every careers site calls its own JSON endpoint, and
  Workday's robots.txt allows crawlers everywhere except `/refreshFacet/`. A feed's slug is
  `{tenant}.{cluster}/{site}`, for example `accenture.wd103/AccentureCareers`. The list is
  `POST /wday/cxs/{tenant}/{site}/jobs` through `SafeFetcher.post_json`, 20 per page, at
  most 5 pages, searched by the profile's city (diacritics folded; the country name when
  there is no city). The search is a plain text match over the whole posting, so a
  Timisoara search also returns postings that merely mention it. The list carries no
  country and only relative dates ("Posted 12 Days Ago"), so every candidate costs one
  detail request, filtered by the detail's country and ordered by its `startDate`; postings
  elsewhere cost a request but do not count toward the limit. `total` appears only on the
  first page. Measured on 2026-11-08: Accenture returns 34 Timisoara postings; Flex returns
  none in Romania and is therefore rejected, which is correct. The company name is the
  legal entity Workday gives ("5301 Accenture Services S.R.L Company").
- **SmartRecruiters** is implemented against its documented shapes and has never been run
  live: `api.smartrecruiters.com/robots.txt` allows only LinkedInBot and disallows
  everyone else, so `SafeFetcher` refuses every call with `disallowed by robots.txt`. The
  crawler does not change identity to get around that. The reader needs no change if
  they alter robots.txt.

ATS hosts and what their robots.txt says to us, measured 2026-11-10 with our User-Agent. This
is what the fetcher is allowed to do, not a licence: the vendors' terms of use were not read.

| ATS | API host | robots.txt | Fetcher may call it | Reader |
| --- | --- | --- | --- | --- |
| Greenhouse | `boards-api.greenhouse.io` | blocks only `/embed/` | yes | built |
| Workday | `{tenant}.{cluster}.myworkdayjobs.com` | blocks only `/refreshFacet/` | yes | built |
| Lever | `api.lever.co` | `Allow: /`, `Crawl-delay: 1` (the fetcher obeys it) | yes | not built |
| Workable | `apply.workable.com` | allows everything; content-signal `ai-train=no` | yes | not built |
| Recruitee | `{company}.recruitee.com` | each company sets its own; some disallow us | company by company | not built |
| Ashby | `api.ashbyhq.com` | the file answers 401 | no: the fetcher treats a 401, 403 or 429 on robots.txt as a refusal | not built |
| SmartRecruiters | `api.smartrecruiters.com` | only LinkedInBot is allowed | no | built, always refused |

Ashby's posting API answered a plain request in an earlier test, and RFC 9309 treats a 4xx
robots.txt as "no rules", so the refusal is this project's stricter choice and not Ashby's.
Whether to make an exception for a documented public API is a decision still open.

Not covered: SuccessFactors, Oracle Recruiting, Teamtailor, Taleo, iCIMS, Lever, Ashby,
Workable, Recruitee and custom portals. A careers page that links to one of them
fails with a reason naming it.

## Aggregator APIs (`aggregator.py`, `himalayas.py`)

A company ATS feed is one employer per request, so it cannot answer "devops jobs in Romania".
Remote-job aggregators that publish an open API can: they search across companies by
keyword and country. The one built is Himalayas (`himalayas.app`, source kind `aggregator`),
a remote-only board, so it adds remote roles and no on-site ones.

- `refresh_aggregator_source` runs one search per profile title (the first two) with the
  profile's country, 20 jobs a page and at most 3 pages a search, so at most about 120 jobs
  and 6 requests a run. Two seconds pass between pages and between searches, on top of
  `SafeFetcher`'s own one-second delay, because every keyless caller shares one allowance
  and the data only refreshes every 24 hours.
- The API takes the ISO country code. `country=RO` and `country=Romania` both gave 304 matches
  for `devops` on 2026-11-09. `locationRestrictions` lists country names, and an empty list
  means worldwide, which is stored as an empty `eligible_countries`. Names are old ISO names
  ("Turkey", "Cabo Verde") or not ISO at all ("Kosovo"), so exact `pycountry` names and a
  one-entry alias are tried before the fuzzy match.
- `external_id` and `url` are the job's `guid`, a stable himalayas.app URL. `apply_url` is the
  API's `applicationLink`. Both are required by the terms: every Apply must use that link,
  the card shows a visible "via Himalayas" credit, and the jobs must not be passed on to other
  job boards or aggregators.
- `pubDate` is when the job was last updated, not first posted, so `posted_at` moves forward
  when the employer edits a job. `salaryPeriod` is sent even without a salary, so a salary is
  kept only with a known period and a currency, converted to monthly. None of the first 20
  live jobs stated a salary.
- Closed jobs must be removed, and a job can close before its `expiryDate`. Each run asks the
  per-job endpoint about up to 10 stored jobs, the least recently confirmed first, and deletes
  a job on HTTP 410 (closed) or 404 ("no job at this path in the API", which for a job the feed
  once listed means it was taken down without a 410; measured on 2026-11-10). If 3 or more
  checked jobs all report gone and none is open, nothing is deleted, because that looks like a
  change in the API and not that many closures. `Job.fetched_at` is moved forward when the API
  still has the job, and it is the only column used for "last confirmed", so for this source it
  does not mean when the job was first fetched. Any other error (a 429, a block) stops the
  checks for that run. This is the one place
  rows are deleted; every other source keeps its postings and only the search hides expired
  ones.
- An aggregator that already stored jobs stays `active` after an error, because the schedule
  skips failed sources.

Jobicy, Remotive and Arbeitnow also publish APIs and are not built. Their published terms:
Jobicy serves the last 7 days, wants credit and polling at most hourly; Remotive advises at
most 4 requests a day, delays jobs 24 hours and forbids passing them to other job sites;
Arbeitnow's site terms restrict commercial use and public display, and it is unclear whether
they cover the API.

## Scheduled refresh (`scheduler.py`)

While the app runs, a background task refreshes sources so jobs accumulate without clicking.
`REFRESH_INTERVAL_HOURS` (default 12, so twice a day; 0 turns it off) is the only setting.

- 60 seconds after startup and then every 30 minutes, `refresh_due_sources` picks the `active`
  sources whose `last_refreshed_at` is empty or older than the interval, for every user with a
  profile and a country, and refreshes them through the same worker pool as a manual refresh.
  Using `last_refreshed_at` makes a restart harmless: sources refreshed an hour ago are
  skipped, and after a long downtime everything due runs at once.
- `failed` and `candidate` sources are skipped; a failed source is retried only by its Refresh
  button.
- It takes the same lock as a manual refresh without waiting, and skips the tick when a manual
  refresh is running.
- Each run reads up to 100 new postings per JSON-LD board and 30 per model-tier board, so twice
  a day it costs up to about 60 model calls a day (roughly a tenth of a cent each) for BestJobs
  and MyJob.ro together. Politeness is unchanged: one request a second per host.
- On Cloud Run the app scales to zero and a loop inside it cannot be relied on. Set
  `REFRESH_INTERVAL_HOURS=0` there and call `refresh_due_sources` from the scheduled job
  (phase 14).

## Company discovery (`discovery.py`, `Company`)

The Romanian boards only show who is hiring, but an employer's own ATS board is richer and keeps
its direct apply link. To find those boards at scale the app keeps a list of companies that hire in
the user's country and works out, one at a time, which of them have a feed it may read.

- `seed_companies` fills the `companies` table (one row per user and normalised name) from the
  stored postings of the user's active `board` and `aggregator` sources that are open to the
  profile's country: a country-restricted posting must name it, an unrestricted one counts.
  Legal suffixes are dropped so "Bosch Romania" and "BOSCH ROMANIA SRL" are one company, and
  `postings` is how many stored postings it has. Employer sources are skipped because their feed is
  already read; names under 4 characters and "Confidential" are skipped.
- `discover_feeds` probes the companies with the most postings first, at most 20 per run. A
  company is `unchecked`, `feed` (a source was created) or `none`. A `none` company is asked
  again only after 30 days; a `feed` company is never probed again.
- A probe tries up to two Greenhouse slugs made from the name (the whole name without legal
  suffixes, and its first word if it has 4 letters or more) and accepts a board only if it has a
  posting in the country and its name agrees with the slug. That is the same check `find_feed`
  uses, and it is what rejects a different company with the same name. Greenhouse is the only
  provider probed: SmartRecruiters refuses us, a Workday tenant and site cannot be guessed
  from a name, and no real Lever or Workable board turned up in testing.
- Probing is slow on purpose: one fetcher for the whole run, at least a second between
  requests and a further second between companies, so a run is roughly 60 requests. A block
  (429, 403) or a failed connection stops the run and leaves the remaining companies
  `unchecked`; it never marks a company `none`.
- A found feed becomes an `employer` source with its provider and slug already set and is
  refreshed in the same run.
- It runs from the scheduled refresh, on a tick that refreshes sources, so twice a day and not
  every half hour. A failure in discovery is logged and does not stop the refresh.
- The list is stored, not recomputed: `companies` is in Postgres, in the `lazyjobs_pgdata` volume,
  and survives `docker compose down` and a rebuild; only `down -v` removes it. Every probe answer
  is kept (`feed` or `none` with `checked_at`), seeding never resets a checked company, and rows
  are never deleted, so the days of probing are not repeated.
- A found company stays on the 12-hour schedule. Its source starts as a `candidate` with the
  provider and slug already set, is refreshed in the run that found it, and is then refreshed
  whenever `last_refreshed_at` is older than the interval, like any active source. A failed
  refresh of a feed-backed source (a 429, a dropped connection) does not mark it `failed`: it keeps
  its status, records `last refresh failed: ...`, and stamps `last_refreshed_at` as the attempt, so
  the next try is a full interval later and a permanent refusal costs about two requests a day. A
  user who disables a source is respected: it is not refreshed and its company is not probed again.
- Each company also gets a website domain, only so the Companies screen can show its logo.
  The model proposes domains in batches of 40 (the best-known companies first, in the same scheduled
  run, before the feed probe) and the code keeps one only if it plausibly belongs to the company: the
  domain's name must contain, or be contained in, the company name without legal suffixes and the
  country word, or start with its first word. A rejected or missing answer is stored as an empty
  string, which means "asked, unknown", while a null `domain` means nobody has asked yet, so a
  made-up domain never produces a wrong logo and nothing is asked twice. A failed lookup leaves the
  companies null to be asked again, and never stops the feed probe. The logo is the favicon the Google
  service returns for the domain, the same service the job cards already use, and the screen falls back
  to initials when there is no domain or the image does not load.
- Measured on 2026-11-10 on the 34 largest companies in the stored board postings: 2 had a
  readable Greenhouse board with Romanian postings, Veeam (15) and eMAG (18), about 6%. Model-named
  companies gave none in 50.

## Safety rules

`SafeFetcher` allows HTTPS only, checks every resolved address against private, loopback,
link-local, reserved, multicast, and unspecified ranges, reads robots.txt, follows redirects
manually, limits response sizes, limits redirects, restricts redirects to the source host,
and waits at least one second between requests to the same host. It uses an identifying
User-Agent and does not retry blocked requests with another identity. ATS API hosts are
fetched through their own `SafeFetcher`, so the same rules apply to them.

Descriptions are converted to plain text before storage. JSON-LD is searched recursively,
including `@graph`; remote roles, eligible countries, dates, and salary values are mapped
into the common `Posting` model. Salary values are normalised to monthly amounts.

`first_seen_at` is set only when a job is first inserted. `Job.fingerprint` is
`textnorm.fingerprint` of company, title and the whole first location string; nothing
reads it yet.

The crawler does not use browser rendering. Playwright is the right open-source renderer
for a script shell, and it must retain the same HTTPS, robots, host, DNS, redirect, and
response-size guards as `SafeFetcher`. Page text sent to the model is untrusted input: its
output is parsed into fixed, length-capped fields and is never executed or rendered as
HTML.

## Duplicate postings (`routers/jobs.py`)

The job search hides postings of the same job before it filters, so a job listed twice, on
one board under two URLs or on two boards, appears once. Nothing is deleted from `jobs`;
the duplicates stay stored and only the search skips them, over the 500 newest rows it
loads.

- Two postings are the same job when `fingerprint(company, title, city)` matches, where
  city is the first location up to its first comma. The stored `Job.fingerprint` is not
  used because boards write an address differently (`Bucuresti, Bucuresti, RO` against
  `BUCURESTI ,, RO`), so the same job would never match across boards.
- Of a group, the posting from an `employer` or `career` source is kept, because it has the
  company's own apply link; otherwise the one with the earliest `first_seen_at`, which is
  the original and not a repost.
- The same title in another city or at another company is a different job. A posting with
  no company name is never merged, because nothing tells it apart from another employer's.
- Limits: matching is on normalised text only (legal suffixes dropped, accents and
  punctuation folded). `Bucharest` and `Bucuresti` differ, and a company that two boards
  spell differently (`Societe Generale GSC` against `SOCIETE GENERALE`) does not merge.

## Expired postings

The job search hides a posting whose `expires_at` (JSON-LD `validThrough`, Himalayas
`expiryDate`) is in the past and counts it under `rejected.expired` in the log. Nothing is
deleted for this, apart from the Himalayas closed-job rule above.

## Sources that refuse an honest crawler

hiring.cafe (now `hiringcafe.com`) is refused in `UNSUPPORTED_DOMAINS`. Checked 2026-11-09:

- robots.txt allows `/job/` and `/jobs/` and has no rule for `/api`, so robots.txt alone
  would allow a query.
- An honest request is refused anyway. Every page tried (the sitemaps,
  `/recently-posted-jobs`, the terms page) and one `POST /api/search-jobs/get-total-count`
  through `SafeFetcher` returned the Cloudflare "Just a moment..." challenge, HTTP 403.
- Web sources report that it has no public API, that its old `/api/search-jobs` endpoints
  were locked down, and that the extractors which still work drive a stealth browser. The
  public scraper `umur957/hiring-cafe-job-scraper` is of the older kind: it calls that API
  with a Chrome User-Agent and `sec-ch-ua` headers, 1000 jobs a page with no delay. Both
  routes are identity spoofing, which the crawler's rules forbid.
- The terms page could not be fetched (403). Through a search result they allow personal
  use under restrictions and forbid selling, renting or sub-licensing the material; a
  summary there also says copying and republishing are forbidden.

The way in is to ask. The terms give `ali@hiring.cafe` as the contact, and people asking
for an API are told a feed or partnership is the route.

## Operation

Crawler timings are written to `backend/logs/app.log`. Timed entries include
`function=... time_taken_ms=...`; fetch entries also include the URL and response bytes,
and career discovery entries include the number of pages and queued links. This makes
network politeness, over-discovery, extraction, and database work distinguishable without
adding a separate profiling system. A source that fails for an expected reason (404, 429,
robots) still writes a traceback, so search for `Source validation failed` first.

Independent sources refresh through a bounded worker pool (`CRAWL_WORKERS`, default 6),
while a shared per-host limiter still honors the configured delay and any `Crawl-delay`
or `Retry-After` response. Successful responses are cached briefly and reused with
`ETag`/`Last-Modified` validators when available. Workers use separate database sessions;
source completion events are collected centrally so one failed source does not cancel the
others.
