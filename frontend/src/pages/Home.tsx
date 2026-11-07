import { useEffect, useState } from "react";
import type { FormEventHandler } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Job, JobFilters, listJobs, logout, meQuery, profileQuery } from "../api";

const defaultFilters: JobFilters = {
  query: "",
  location: "",
  mode: "hybrid_onsite",
  days: null,
};

export default function Home() {
  const { data: me } = useQuery(meQuery);
  const profile = useQuery(profileQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [filters, setFilters] = useState(defaultFilters);
  const [submitted, setSubmitted] = useState(defaultFilters);
  const jobs = useQuery({
    queryKey: ["jobs", submitted],
    queryFn: () => listJobs(submitted),
    staleTime: 60_000,
  });
  useEffect(() => {
    if (jobs.isError) {
      console.error("Job search failed", { filters: submitted, error: jobs.error });
    }
    if (jobs.isSuccess) {
      console.info("Job search completed", { filters: submitted, resultCount: jobs.data.jobs.length, refreshed: jobs.data.refreshed });
    }
  }, [jobs.isError, jobs.isSuccess, jobs.error, jobs.data, submitted]);
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: meQuery.queryKey });
      navigate("/sign-in", { replace: true });
    },
  });
  const submit: FormEventHandler<HTMLFormElement> = (event) => {
    event.preventDefault();
    setSubmitted({ ...filters });
  };

  if (!me) return null;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-950/95 px-4 py-4 sm:px-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-300">CV Applier</p>
            <h1 className="mt-1 text-xl font-semibold">Your next move</h1>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <Link to="/profile" className="rounded-md px-3 py-2 text-slate-300 hover:bg-white/10 hover:text-white">Profile</Link>
            <Link to="/sources" className="rounded-md px-3 py-2 text-slate-300 hover:bg-white/10 hover:text-white">Sources</Link>
            <button type="button" onClick={() => signOut.mutate()} disabled={signOut.isPending} className="rounded-md border border-white/15 px-3 py-2 text-slate-200 hover:bg-white/10 disabled:opacity-50">Sign out</button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-8">
        <section className="mb-8 max-w-3xl">
          <p className="text-sm font-medium text-teal-300">Matched to your CV</p>
          <h2 className="mt-2 text-4xl font-semibold tracking-tight sm:text-5xl">Work worth opening.</h2>
          <p className="mt-3 text-slate-400">Fresh roles are gathered around your profile. The first search uses your CV titles, skills, and preferred city automatically.</p>
          {profile.data && <p className="mt-3 text-sm text-teal-200">Using {profile.data.city || "your saved locations"} · {profile.data.titles.slice(0, 2).join(" · ") || profile.data.headline || "your CV profile"}</p>}
        </section>

        <form onSubmit={submit} className="mb-8 grid gap-3 border border-white/10 bg-white/[0.06] p-4 sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto_auto_auto]">
          <input value={filters.query ?? ""} onChange={(event) => setFilters({ ...filters, query: event.target.value })} placeholder="Search title, skill, or company" className="rounded-md border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-teal-400" />
          <input value={filters.location ?? ""} onChange={(event) => setFilters({ ...filters, location: event.target.value })} placeholder={profile.data?.city || "City or location"} className="rounded-md border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-teal-400" />
          <select value={filters.mode ?? "hybrid_onsite"} onChange={(event) => setFilters({ ...filters, mode: event.target.value })} className="rounded-md border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-white outline-none focus:border-teal-400">
            <option value="hybrid_onsite">Hybrid + onsite</option>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">Onsite</option>
            <option value="all">All modes</option>
          </select>
          <select value={filters.days ?? ""} onChange={(event) => setFilters({ ...filters, days: event.target.value ? Number(event.target.value) : null })} className="rounded-md border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-white outline-none focus:border-teal-400">
            <option value="">Any age</option>
            <option value="1">Past day</option>
            <option value="7">Past week</option>
            <option value="30">Past month</option>
          </select>
          <button type="submit" className="rounded-md bg-teal-400 px-5 py-2.5 text-sm font-semibold text-slate-950 hover:bg-teal-300">Search</button>
          <button type="button" onClick={() => { const allFilters = { query: "", location: "", mode: "all", days: null }; setFilters(allFilters); setSubmitted(allFilters); }} className="rounded-md border border-white/15 px-4 py-2.5 text-sm text-slate-200 hover:bg-white/10">Show all jobs</button>
        </form>

        <div className="mb-4 flex items-center justify-between gap-3">
          <p className="text-sm text-slate-400">{jobs.isPending ? "Finding roles..." : `${jobs.data?.jobs.length ?? 0} roles found`}</p>
          {jobs.data?.match_scope !== "profile_and_location" && jobs.data?.jobs.length ? <p className="text-xs text-amber-300">Showing broader matches because no exact city/profile match was found.</p> : null}
        </div>

        {jobs.isError && <p className="border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-200">Could not load jobs. {jobs.error instanceof Error ? jobs.error.message : "Try again shortly."}</p>}
        {!jobs.isPending && !jobs.isError && jobs.data?.jobs.length === 0 && <div className="border border-dashed border-white/15 p-12 text-center"><h3 className="text-lg font-medium">No roles match this search</h3><p className="mt-2 text-sm text-slate-400">Try a wider location, a different mode, or clear the search terms.</p></div>}
        <section className="grid gap-4 lg:grid-cols-2">
          {jobs.data?.jobs.map((job) => <JobCard key={job.id} job={job} />)}
        </section>
      </main>
    </div>
  );
}

function JobCard({ job }: { job: Job }) {
  return (
    <article className="flex min-h-[250px] flex-col border border-white/10 bg-white/[0.06] p-5 transition-colors hover:border-teal-300/50">
      <div className="flex items-start gap-4">
        <img src={job.logo_url} alt="" className="h-11 w-11 rounded-md bg-white object-contain p-1" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-lg font-semibold text-white">{job.title}</h3>
          <p className="mt-1 text-sm text-teal-200">{job.company || job.source}</p>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-300">
        {job.locations.length > 0 && <span className="border border-white/10 px-2 py-1">{job.locations[0]}</span>}
        <span className="border border-white/10 px-2 py-1">{modeLabel(job.work_mode)}</span>
        {job.experience_level && <span className="border border-white/10 px-2 py-1">{job.experience_level}</span>}
        {job.employment_type && <span className="border border-white/10 px-2 py-1">{job.employment_type}</span>}
      </div>
      <p className="mt-4 line-clamp-3 text-sm leading-6 text-slate-400">{job.description || "No description was provided."}</p>
      <div className="mt-auto flex items-center justify-between gap-3 pt-5">
        <span className="text-xs text-slate-500">{postedLabel(job.posted_at)}{job.salary_min ? ` · ${job.salary_min}${job.salary_max ? `-${job.salary_max}` : ""} ${job.salary_currency}` : ""}</span>
        <a href={job.apply_url || job.url} target="_blank" rel="noreferrer" className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-200">View role</a>
      </div>
    </article>
  );
}

function modeLabel(mode: string): string {
  return mode === "onsite" ? "Onsite" : mode === "hybrid" ? "Hybrid" : mode === "remote" ? "Remote" : "Work mode unknown";
}

function postedLabel(value: string | null): string {
  if (!value) return "Date not listed";
  const days = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 86400000));
  return days === 0 ? "Posted today" : `${days}d ago`;
}
