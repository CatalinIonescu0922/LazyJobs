# CV Applier

A personal job-search assistant: parse a CV, match Romanian openings, draft cover
letters, and track applications.

## Stack

- Backend: FastAPI, SQLAlchemy 2, SQLite, in `backend/`
- Frontend: Vite, React, TypeScript, Tailwind, in `frontend/` (not scaffolded yet)
- Auth: Google OpenID Connect. Accounts are an email plus `identities` rows. There
  is no password column.

## Running the backend

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

There is no Alembic. `Base.metadata.create_all` runs on startup. If the schema changes
during early development, delete `backend/cv_applier.db` and restart.

## Docs

Subsystem docs live in `docs/` and are written in the same change as the code they
describe.

- [Authentication](docs/auth.md)
- Design: [PLAN.md](PLAN.md)
- Phase checklist: [BUILD.md](BUILD.md)
- Live phase status: [PROGRESS.md](PROGRESS.md)
