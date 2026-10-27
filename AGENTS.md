# CV Applier

A personal job-search assistant: parse a CV, match Romanian openings, draft cover
letters, and track applications.

## Stack

- Backend: FastAPI, SQLAlchemy 2, in `backend/`
- Frontend: Vite, React, TypeScript, Tailwind, in `frontend/`
- Auth: Google OpenID Connect. Accounts are an email plus `identities` rows. There
  is no password column.
- Target platform: Google Cloud Platform in `europe-west3`. Cloud Run, Cloud SQL for
  PostgreSQL, Cloud Storage, Vertex AI, provisioned with Terraform rather than the
  console. See [PLAN.md](PLAN.md) section 4.

## Running the backend

The backend runs in Docker Compose against PostgreSQL. From the repo root:

```
cp backend/.env.example backend/.env
docker compose up --build
```

Health check: `curl localhost:8000/api/health`. OpenAPI: `http://localhost:8000/docs`.
CORS is locked to `FRONTEND_ORIGIN` (default `http://localhost:5173`).

Sign-in: set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `backend/.env`, then
open the frontend and click Continue with Google. The backend alone can be checked at
`http://localhost:8000/api/auth/google/login`.

## Running the frontend

The frontend runs on the host, next to the compose stack, with hot reload. From
`frontend/`:

```
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to port 8000.

If the code runs on a remote machine reached over SSH, the browser on your own
computer has to reach both ports on that machine. Forward them when you connect:

```
ssh -L 5173:localhost:5173 -L 8000:localhost:8000 user@remote-host
```

Then open `http://localhost:5173` on your own computer. The Google OAuth redirect
goes to `http://localhost:8000` on your computer, which the same forwarding carries to
the backend. Without the forwarding, sign-in fails with a connection error.

Schema changes are Alembic revisions applied with
`docker compose run --rm app alembic upgrade head`. The process does not create or
alter tables on startup. See [LEARNING.md](LEARNING.md) entry 20.

Compose also runs Postgres 16 as `db` and a Cloud Storage emulator as `gcs`.
`STORAGE_EMULATOR_HOST` in `backend/.env` points the storage client at the emulator.

## Cloud

Nothing is deployed. No GCP project exists yet and nothing is being billed. The design,
the cost model and the credit constraints are in [PLAN.md](PLAN.md) section 4; the
Terraform and commands that create each resource are in [BUILD.md](BUILD.md) phases 4,
12 to 15.

## Docs

Subsystem docs live in `docs/` and are written in the same change as the code they
describe.

- [Authentication](docs/auth.md)
- [Frontend](docs/frontend.md)
- [Cloud foundation](docs/cloud.md)
- [How jobs are found and used](docs/how-it-works.md) (design, not built yet)
- Design: [PLAN.md](PLAN.md)
- Phase checklist: [BUILD.md](BUILD.md)
- Live phase status: [PROGRESS.md](PROGRESS.md)
- Why the code looks like this: [LEARNING.md](LEARNING.md)
