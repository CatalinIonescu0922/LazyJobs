# CV Applier

A personal job-search assistant: parse a CV, match Romanian openings, draft cover
letters, and track applications.

## Stack

- Backend: FastAPI, SQLAlchemy 2, in `backend/`
- Frontend: Vite, React, TypeScript, Tailwind, in `frontend/` (not scaffolded yet)
- Auth: Google OpenID Connect. Accounts are an email plus `identities` rows. There
  is no password column.
- Target platform: Google Cloud Platform in `europe-west1`. Cloud Run, Cloud SQL for
  PostgreSQL, Cloud Storage, Vertex AI, provisioned with Terraform rather than the
  console. See [PLAN.md](PLAN.md) section 4.

## Running the backend

The backend currently runs directly on the host against SQLite. Phase 5 replaces this
with Docker Compose and PostgreSQL; until then:

```
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Health check: `curl localhost:8000/api/health`. OpenAPI: `http://localhost:8000/docs`.
CORS is locked to `FRONTEND_ORIGIN` (default `http://localhost:5173`).

Sign-in: set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `backend/.env`, then
open `http://localhost:8000/api/auth/google/login`.

There is no Alembic yet. `Base.metadata.create_all` runs on startup. If the schema
changes before phase 5, delete `backend/cv_applier.db` and restart. Phase 5 replaces
both of those with migrations, for the reasons in [LEARNING.md](LEARNING.md) entry 20.

## Cloud

Nothing is deployed. No GCP project exists yet and nothing is being billed. The design,
the cost model and the credit constraints are in [PLAN.md](PLAN.md) section 4; the
Terraform and commands that create each resource are in [BUILD.md](BUILD.md) phases 4,
12 to 15.

## Docs

Subsystem docs live in `docs/` and are written in the same change as the code they
describe.

- [Authentication](docs/auth.md)
- Design: [PLAN.md](PLAN.md)
- Phase checklist: [BUILD.md](BUILD.md)
- Live phase status: [PROGRESS.md](PROGRESS.md)
- Why the code looks like this: [LEARNING.md](LEARNING.md)
