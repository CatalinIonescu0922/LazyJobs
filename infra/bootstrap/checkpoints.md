Checkpoint 1 — fill bootstrap (still no apply)
Type, do not paste-and-forget. Order:

variables.tf — project_id, billing_account_id, no defaults.
terraform.tfvars — real values (gitignored). Billing id from gcloud billing accounts list.
main.tf — provider ~> 7.44, europe-west1, billing_project + user_project_override = true, then three resources:
four APIs (cloudresourcemanager, serviceusage, billingbudgets, storage)
state bucket cv-applier-tfstate-${var.project_id} (versioned, force_destroy = false)
budget display name cv-applier, $50, thresholds 0.5 / 0.9 / 1.0
outputs.tf — bucket name.
No backend "gcs" in this file yet.

From infra/bootstrap/:

terraform init
terraform fmt
terraform validate
terraform plan
Plan must show: those APIs, one bucket, one budget. Not SQL, not Cloud Run, not an uploads bucket.

If the budget 403s: quota project + those two provider fields. That is the phase-4 trap.

Checkpoint 2 — first apply (local state)
terraform apply. Expected: a terraform.tfstate on disk in infra/bootstrap/. Gitignore should hide it.

Check:

terraform state list
gcloud billing budgets list --billing-account=… → cv-applier, three thresholds
gcloud storage ls gs://cv-applier-tfstate-cv-applier-ionescu-catalin
You are still on the default plan: Terraform owns the budget. Do not recreate it with gcloud.

Checkpoint 3 — move state into that bucket
Add the backend "gcs" block to bootstrap (bucket is a literal with your project id; backends cannot use variables). Prefix bootstrap.

terraform init -migrate-state
Confirm yes. Then: state in the bucket, not on the laptop. terraform plan → No changes.

Checkpoint 4 — infra/main/ (only after 3)
New folder, its own state (prefix main, same bucket). variables.tf + terraform.tfvars with project_id only.

Resources: remaining APIs (not storage — bootstrap owns it), SA cv-applier-run, three project roles (cloudsql.client, aiplatform.user, secretmanager.secretAccessor). No storage.objectAdmin, no SQL, no uploads bucket.

Provider does not need billing_project here.

init → plan → apply. First init should talk to GCS. If it wants local state, the backend block is wrong.

Checkpoint 5 — prove phase 4
Vertex ping from BUILD.md (google-genai, gemini-3.1-flash-lite, location global). Credit pays for Vertex, not AI Studio.
Both prefixes in the state bucket.
terraform state list in both folders.
Still no Cloud SQL, no uploads bucket.
Then write docs/cloud.md in your own words (split, ADC, what is missing). Add google-genai to requirements / .env.example as BUILD.md lists. Flip phase 4 in PROGRESS.md.

Stop. Phase 5 is Compose/Postgres, not more Terraform.

Work now: checkpoint 0, then fill the three empty bootstrap files and stop at plan. Paste the plan summary if you want a check before apply.