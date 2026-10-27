# Candidate profile

The profile flow lives in `backend/app/routers/profile.py`. `POST /api/profile/cv` accepts
one PDF or DOCX file up to 5 MB, extracts plain text, stores the original file under
`cv/{user_id}/{filename}`, and sends the text to Vertex AI for structured profile fields.
The extracted text is capped before the model call and is retained in `profiles.cv_text` for
later matching and letter generation.

`PATCH /api/profile` saves corrections to the extracted fields and search preferences.
`GET /api/profile` returns the authenticated user's profile. Both endpoints create the
empty profile row when needed and always scope access through the current session user.

Local Compose uses the GCS emulator through `STORAGE_EMULATOR_HOST`; emulator uploads use
anonymous credentials. Production leaves that setting empty, so the same storage client
uses the Cloud Run service account and the configured `GCS_BUCKET`.

Vertex AI uses Application Default Credentials locally and the Cloud Run service account in
production. Run `gcloud auth application-default login` on the host before starting Compose;
the Compose service exposes only that ADC file as a read-only secret at
`/run/secrets/google_application_credentials.json`. Configure `GOOGLE_CLOUD_PROJECT`,
`VERTEX_LOCATION`, and `VERTEX_MODEL`. The
model is instructed to return only the validated profile schema; missing CV details remain
empty rather than being guessed.

The frontend screen is `/profile`. It lets the candidate upload a CV, review the extracted
fields, edit them, and save search preferences including country, city, remote-only, and
minimum monthly salary.
