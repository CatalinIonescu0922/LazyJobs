# CV Applier - Build Progress

Live status for the phases defined in [BUILD.md](BUILD.md). This is the first file to
check to see exactly where the build stands; details of what each phase involves live in
BUILD.md, and the reasoning behind the design lives in [PLAN.md](PLAN.md).

Status values: `not started`, `in progress`, `blocked`, `done`.

## Part 1 - Backend foundation

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 1 | Application skeleton | done | verified: health 200, /docs 200, CORS preflight correct, 4 tables created |
| 2 | Data model for identity | done | verified: identities unique on (provider, subject); users has no password_hash |
| 3 | Google sign-in | done | verified: /me 401, unknown provider 404, unconfigured google 503, callback rejects missing state, second identity reuses the same user. Live Google round-trip needs GOOGLE_CLIENT_ID in .env |
| 4 | CV upload and profile | not started | |
| 5 | eJobs source | not started | |
| 6 | ATS source and coverage check | not started | |
| 7 | Matching | not started | |
| 8 | Applications API | not started | |
| 9 | Cover letters | not started | needs an LLM key, optional |

## Part 2 - Frontend

| Phase | What | Status | Notes |
| --- | --- | --- | --- |
| 10 | Shell and sign-in | not started | |
| 11 | Profile screen | not started | |
| 12 | Matches screen | not started | |
| 13 | Tracker screen | not started | |
| 14 | Polish | not started | |

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

---

## How this file is maintained

Updated at the end of every phase, in the same change as the phase's code: flip its
status, add one line to the log with the date and a short note, and record any decision
the phase produced (for example, the Romania-coverage number from phase 6). Work stops for
a quick check-in between phases rather than running through all fourteen in one pass.
