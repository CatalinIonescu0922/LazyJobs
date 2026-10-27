import { ChangeEvent, FormEvent, ReactNode, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ProfileUpdate,
  profileQuery,
  updateProfile,
  uploadCv,
} from "../api";

const emptyForm: ProfileUpdate = {
  full_name: "",
  headline: "",
  summary: "",
  titles: [],
  skills: [],
  years_experience: 0,
  country: "",
  city: "",
  salary_currency: "",
  preferred_locations: [],
  remote_only: false,
  min_salary: 0,
  extra_keywords: [],
};

export default function Profile() {
  const profile = useQuery(profileQuery);
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ProfileUpdate>(emptyForm);
  const [titles, setTitles] = useState("");
  const [skills, setSkills] = useState("");
  const [locations, setLocations] = useState("");
  const [keywords, setKeywords] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!profile.data) return;
    setForm({
      full_name: profile.data.full_name,
      headline: profile.data.headline,
      summary: profile.data.summary,
      titles: profile.data.titles,
      skills: profile.data.skills,
      years_experience: profile.data.years_experience,
      country: profile.data.country,
      city: profile.data.city,
      salary_currency: profile.data.salary_currency,
      preferred_locations: profile.data.preferred_locations,
      remote_only: profile.data.remote_only,
      min_salary: profile.data.min_salary,
      extra_keywords: profile.data.extra_keywords,
    });
    setTitles(profile.data.titles.join(", "));
    setSkills(profile.data.skills.join(", "));
    setLocations(profile.data.preferred_locations.join(", "));
    setKeywords(profile.data.extra_keywords.join(", "));
  }, [profile.data]);

  const save = useMutation({
    mutationFn: updateProfile,
    onSuccess: (saved) => {
      queryClient.setQueryData(profileQuery.queryKey, saved);
      setMessage("Profile saved");
    },
  });

  const upload = useMutation({
    mutationFn: uploadCv,
    onSuccess: (saved) => {
      queryClient.setQueryData(profileQuery.queryKey, saved);
      setMessage("CV uploaded and profile extracted");
    },
  });

  function updateField<K extends keyof ProfileUpdate>(
    field: K,
    value: ProfileUpdate[K],
  ) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate({
      ...form,
      titles: splitList(titles),
      skills: splitList(skills),
      preferred_locations: splitList(locations),
      extra_keywords: splitList(keywords),
    });
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) upload.mutate(file);
  }

  if (profile.isPending) {
    return <p className="p-6 text-slate-500">Loading profile...</p>;
  }
  if (profile.isError) {
    return <p className="p-6 text-red-600">Could not load your profile.</p>;
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 text-slate-900 sm:px-8">
      <div className="mx-auto max-w-4xl">
        <header className="mb-8 flex items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium uppercase tracking-wide text-teal-700">
              Candidate profile
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              Make your next application easier.
            </h1>
            <p className="mt-2 max-w-2xl text-slate-600">
              Upload your CV to start, then correct anything the extraction missed.
            </p>
          </div>
          {message && <p className="text-sm text-teal-700">{message}</p>}
        </header>

        <section className="mb-6 border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="font-semibold">CV source</h2>
              <p className="mt-1 text-sm text-slate-500">
                {profile.data.has_cv
                  ? `Current file: ${profile.data.cv_filename}`
                  : "PDF or DOCX, up to 5 MB"}
              </p>
            </div>
            <label className="cursor-pointer rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800">
              {upload.isPending ? "Extracting..." : "Upload CV"}
              <input
                type="file"
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={chooseFile}
                disabled={upload.isPending}
                className="sr-only"
              />
            </label>
          </div>
          {upload.isError && (
            <p className="mt-3 text-sm text-red-600">
              {upload.error instanceof Error
                ? upload.error.message
                : "CV upload failed"}
            </p>
          )}
        </section>

        <form onSubmit={submit} className="space-y-6">
          <section className="border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-4 font-semibold">About you</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Full name">
                <input value={form.full_name} onChange={(event) => updateField("full_name", event.target.value)} />
              </Field>
              <Field label="Headline">
                <input value={form.headline} onChange={(event) => updateField("headline", event.target.value)} />
              </Field>
              <Field label="Country (ISO code)">
                <input maxLength={2} value={form.country} onChange={(event) => updateField("country", event.target.value.toUpperCase())} />
              </Field>
              <Field label="City">
                <input value={form.city} onChange={(event) => updateField("city", event.target.value)} />
              </Field>
            </div>
            <Field label="Summary" wide>
              <textarea rows={5} value={form.summary} onChange={(event) => updateField("summary", event.target.value)} />
            </Field>
          </section>

          <section className="border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-4 font-semibold">Experience and preferences</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Titles (comma separated)">
                <input value={titles} onChange={(event) => setTitles(event.target.value)} />
              </Field>
              <Field label="Skills (comma separated)">
                <input value={skills} onChange={(event) => setSkills(event.target.value)} />
              </Field>
              <Field label="Years of experience">
                <input type="number" min="0" step="0.5" value={form.years_experience} onChange={(event) => updateField("years_experience", Number(event.target.value))} />
              </Field>
              <Field label="Preferred locations (comma separated)">
                <input value={locations} onChange={(event) => setLocations(event.target.value)} />
              </Field>
              <Field label="Salary currency (ISO code)">
                <input maxLength={3} value={form.salary_currency} onChange={(event) => updateField("salary_currency", event.target.value.toUpperCase())} />
              </Field>
              <Field label="Minimum salary per month">
                <input type="number" min="0" value={form.min_salary} onChange={(event) => updateField("min_salary", Number(event.target.value))} />
              </Field>
              <Field label="Extra keywords (comma separated)" wide>
                <input value={keywords} onChange={(event) => setKeywords(event.target.value)} />
              </Field>
            </div>
            <label className="mt-4 flex items-center gap-3 text-sm text-slate-700">
              <input type="checkbox" checked={form.remote_only} onChange={(event) => updateField("remote_only", event.target.checked)} />
              Remote roles only
            </label>
          </section>

          <div className="flex justify-end">
            <button type="submit" disabled={save.isPending} className="rounded-md bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50">
              {save.isPending ? "Saving..." : "Save profile"}
            </button>
          </div>
          {save.isError && <p className="text-right text-sm text-red-600">Could not save your profile.</p>}
        </form>
      </div>
    </main>
  );
}

function splitList(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function Field({ label, wide = false, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <label className={wide ? "block sm:col-span-2" : "block"}>
      <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>
      <span className="*:w-full *:rounded-md *:border *:border-slate-300 *:px-3 *:py-2 *:text-sm *:outline-none focus-within:*:border-teal-600">{children}</span>
    </label>
  );
}
