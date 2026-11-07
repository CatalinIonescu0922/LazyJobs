# Job sources

Phase 8 adds one generic board crawler instead of one adapter per website. Sources are
stored in `job_sources`; the crawler reads sitemap URLs and extracts schema.org
`JobPosting` JSON-LD into the shared `Posting` shape.

## Workflow

- `POST /api/sources/discover?kind=boards` asks Vertex AI for board domains for the
  authenticated profile country and stores new domains as `candidate` sources.
- `POST /api/sources` adds a board domain manually.
- `POST /api/sources` also accepts a full HTTPS career-page URL. These `career` sources
  fetch the supplied page and same-domain career/job links, then extract `JobPosting`
  JSON-LD.
- `POST /api/sources/discover?kind=employers` asks Vertex for up to 15 employers in the
  profile city and country using the candidate's titles and skills, then stores their
  websites as `employer` sources for career-page crawling.
- `POST /api/sources/{id}/refresh` validates a candidate, then reads up to 100 sitemap
  entries and upserts postings.
- `PATCH /api/sources/{id}` enables or disables a source.

A candidate becomes active only after robots.txt, sitemap, and at least two JSON-LD posting
samples pass. A failed source retains a plain-language reason. The normal dashboard
refreshes the user's sources automatically after the first CV upload; the Sources screen
remains available for advanced management and recovery.

## Safety rules

`SafeFetcher` allows HTTPS only, checks every resolved address against private, loopback,
link-local, reserved, multicast, and unspecified ranges, reads robots.txt, follows redirects
manually, limits response sizes, limits redirects, restricts redirects to the source host,
and waits at least one second between requests to the same host. It uses an identifying
User-Agent and does not retry blocked requests with another identity.

Descriptions are converted to plain text before storage. JSON-LD is searched recursively,
including `@graph`; remote roles, eligible countries, dates, and salary values are mapped
into the common `Posting` model. Salary values are normalised to monthly amounts.

`textnorm.fingerprint` normalises company, title, and city so later matching can collapse
cross-board duplicates. `first_seen_at` is set only when a job is first inserted.

The local source APIs and screen are ready for Phase 9's LLM extraction fallback and Phase
20's employer ATS feeds. They intentionally do not use browser rendering or site-specific
adapters in Phase 8. A custom page that is mostly a JavaScript shell is marked `needs
browser rendering` instead of being reported as an empty source. Playwright is the right
open-source renderer for that next adapter, and it must retain the same HTTPS, robots,
host, DNS, redirect, and response-size guards as `SafeFetcher`.

Crawler timings are written to `backend/logs/app.log`. Timed entries include
`function=... time_taken_ms=...`; fetch entries also include the URL and response bytes,
and career discovery entries include the number of pages and queued links. This makes
network politeness, over-discovery, extraction, and database work distinguishable without
adding a separate profiling system.

Independent sources refresh through a bounded worker pool (`CRAWL_WORKERS`, default 6),
while a shared per-host limiter still honors the configured delay and any `Crawl-delay`
or `Retry-After` response. Successful responses are cached briefly and reused with
`ETag`/`Last-Modified` validators when available. Workers use separate database sessions;
source completion events are collected centrally so one failed source does not cancel the
others.
