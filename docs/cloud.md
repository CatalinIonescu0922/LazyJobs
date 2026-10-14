# Cloud foundation

The GCP project, its spending alarm, the enabled APIs and the runtime identity. All of it is
Terraform except project creation and billing linkage. Nothing chargeable exists yet.

## Where it lives

- `infra/bootstrap/` - state bucket, budget, notification channel, and the APIs they need.
- `infra/main/` - the remaining APIs, the `cv-applier-run` service account and its roles.
- Both use the bucket `cv-applier-tfstate-cv-applier-ionescu-catalin`, prefixes `bootstrap`
  and `main`. Each has its own state; they never share one.
- `terraform.tfvars` in each folder holds real ids and is gitignored.

## Facts other code depends on

- Project id `cv-applier-ionescu-catalin`, region `europe-west3`.
- Runtime service account `cv-applier-run@cv-applier-ionescu-catalin.iam.gserviceaccount.com`
  with `cloudsql.client`, `aiplatform.user`, `secretmanager.secretAccessor`. The
  `storage.objectAdmin` grant is added with the uploads bucket in phase 12.
- Vertex AI is called with `genai.Client(vertexai=True, project=..., location="global")`.
  Credentials are Application Default Credentials; there are no key files. Locally that is
  `gcloud auth application-default login` plus `set-quota-project`.
- Budget is $50 a month, alerting by email at 50, 70 and 90 percent. It only alerts, it
  does not stop spending.

## Constraints

- An API is enabled by exactly one module. `storage.googleapis.com` belongs to bootstrap.
- The `backend "gcs"` bucket name is a literal because backends cannot use variables.
- The budget needs the provider's `billing_project` and `user_project_override`, otherwise
  the Billing Budgets API returns 403 under user credentials.
- The project itself and its billing link were created by hand with `gcloud`, because
  Terraform needs a project to attach a quota project to before it can run.
- The bootstrap resources were created before their state existed, so they were brought under
  management with `terraform import`.
