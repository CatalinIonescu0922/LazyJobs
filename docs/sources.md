# Job sources

Phase 8 adds one generic board crawler instead of one adapter per website. Sources are
stored in `job_sources`; the crawler reads sitemap URLs and extracts schema.org
`JobPosting` JSON-LD into the shared `Posting` shape.

## Workflow

- `POST /api/sources/discover?kind=boards` asks Vertex AI for board domains for the
  authenticated profile country and stores new domains as `candidate` sources.
- `POST /api/sources` adds a board domain manually.
- `POST /api/sources/{id}/refresh` validates a candidate, then reads up to 100 sitemap
  entries and upserts postings.
- `PATCH /api/sources/{id}` enables or disables a source.

A candidate becomes active only after robots.txt, sitemap, and at least two JSON-LD posting
samples pass. A failed source retains a plain-language reason. The Sources screen refreshes
one board at a time.

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
adapters in Phase 8.
