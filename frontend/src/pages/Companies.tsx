import { useEffect, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { CompanyCard, CompanyCounts, CompanyStatusFilter, FeedCard, companiesQuery, logout, meQuery } from "../api";

const PAGE_SIZE = 60;

const TABS: { status: CompanyStatusFilter; label: string }[] = [
  { status: "all", label: "All" },
  { status: "feed", label: "With a feed" },
  { status: "none", label: "No readable feed" },
  { status: "unchecked", label: "Not checked yet" },
];

const navLink = "rounded-md px-3 py-2 text-slate-300 hover:bg-white/10 hover:text-white";
const chip = "border border-white/10 px-2 py-1 text-xs text-slate-300";
const providerChip = "border border-teal-300/30 bg-teal-300/10 px-2 py-1 text-xs text-teal-200";

const feedStatusStyle: Record<string, string> = {
  candidate: "border-amber-300/30 bg-amber-300/10 text-amber-200",
  failed: "border-red-400/30 bg-red-400/10 text-red-200",
  disabled: "border-white/15 text-slate-400",
};

export default function Companies() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const overview = useQuery(companiesQuery({ status: "all", search: "", limit: PAGE_SIZE, offset: 0 }));
  const [status, setStatus] = useState<CompanyStatusFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: meQuery.queryKey });
      navigate("/sign-in", { replace: true });
    },
  });

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-950/95 px-4 py-4 sm:px-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-300">CV Applier</p>
            <h1 className="mt-1 text-xl font-semibold">Companies</h1>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <Link to="/" className={navLink}>Jobs</Link>
            <Link to="/profile" className={navLink}>Profile</Link>
            <Link to="/sources" className={navLink}>Sources</Link>
            <Link to="/companies" aria-current="page" className="rounded-md bg-white/10 px-3 py-2 text-white">Companies</Link>
            <button type="button" onClick={() => signOut.mutate()} disabled={signOut.isPending} className="rounded-md border border-white/15 px-3 py-2 text-slate-200 hover:bg-white/10 disabled:opacity-50">Sign out</button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-8">
        <p className="mb-6 max-w-3xl text-slate-400">Companies seen hiring in your country, and the ones whose job feed the app reads directly.</p>

        {overview.isPending && <p className="text-sm text-slate-400">Loading companies...</p>}
        {overview.isError && <LoadError error={overview.error} onRetry={() => overview.refetch()} />}
        {overview.data && (
          <>
            <Summary counts={overview.data.counts} />

            <section className="mb-10">
              <h2 className="text-xl font-semibold">Read directly</h2>
              {overview.data.feeds.length === 0 ? (
                <p className="mt-4 border border-dashed border-white/15 p-8 text-center text-sm text-slate-400">No employer feeds are read yet; they appear here as the app finds them.</p>
              ) : (
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  {overview.data.feeds.map((feed) => <FeedItem key={feed.source_id} feed={feed} />)}
                </div>
              )}
            </section>

            <section>
              <h2 className="text-xl font-semibold">Companies that hire in your country</h2>
              <div className="mb-6 mt-4 flex flex-wrap items-center justify-between gap-3">
                <div role="group" aria-label="Filter companies by feed status" className="flex flex-wrap gap-2">
                  {TABS.map((tab) => (
                    <button key={tab.status} type="button" aria-pressed={status === tab.status} onClick={() => setStatus(tab.status)} className={`rounded-md px-4 py-2 text-sm ${status === tab.status ? "bg-teal-400 font-semibold text-slate-950" : "border border-white/15 text-slate-200 hover:bg-white/10"}`}>{tab.label}</button>
                  ))}
                </div>
                <div className="w-full sm:w-72">
                  <label htmlFor="company-search" className="sr-only">Search companies by name</label>
                  <input id="company-search" type="search" value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search by company name" className="w-full rounded-md border border-white/10 bg-slate-900 px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-teal-400" />
                </div>
              </div>
              {/* Keyed so paging starts over at the first page whenever the filter changes. */}
              <CompanyList key={`${status}:${search}`} status={status} search={search} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function CompanyList({ status, search }: { status: CompanyStatusFilter; search: string }) {
  const [pageCount, setPageCount] = useState(1);
  const pages = useQueries({
    queries: Array.from({ length: pageCount }, (_, page) => companiesQuery({ status, search, limit: PAGE_SIZE, offset: page * PAGE_SIZE })),
  });
  const first = pages[0];
  const last = pages[pages.length - 1];
  const failed = pages.find((page) => page.isError);
  const companies = pages.flatMap((page) => page.data?.companies ?? []);
  const total = first.data?.total_matching ?? 0;

  if (first.isPending) return <p className="text-sm text-slate-400">Loading companies...</p>;

  return (
    <>
      {first.isSuccess && companies.length === 0 && (
        <div className="border border-dashed border-white/15 p-12 text-center">
          <h3 className="text-lg font-medium">No companies match this filter</h3>
          <p className="mt-2 text-sm text-slate-400">Try another tab or a different search.</p>
        </div>
      )}
      {companies.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {companies.map((company) => <CompanyItem key={company.id} company={company} />)}
        </div>
      )}
      {failed && <div className="mt-4"><LoadError error={failed.error} onRetry={() => failed.refetch()} /></div>}
      {!failed && companies.length < total && (
        <div className="mt-6 flex justify-center">
          <button type="button" onClick={() => setPageCount((count) => count + 1)} disabled={last.isFetching} className="rounded-md border border-white/15 px-5 py-2.5 text-sm text-slate-200 hover:bg-white/10 disabled:opacity-50">
            {last.isFetching ? "Loading..." : "Show more"}
          </button>
        </div>
      )}
    </>
  );
}

function Summary({ counts }: { counts: CompanyCounts }) {
  const stats = [
    { value: counts.total, label: counts.total === 1 ? "company" : "companies" },
    { value: counts.feed, label: "read directly" },
    { value: counts.none, label: "checked, no readable feed" },
    { value: counts.unchecked, label: "waiting to be checked" },
  ];
  return (
    <div className="mb-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((stat) => (
        <div key={stat.label} className="border border-white/10 bg-white/[0.06] p-4">
          <p className="text-2xl font-semibold text-white">{stat.value}</p>
          <p className="mt-1 text-sm text-slate-400">{stat.label}</p>
        </div>
      ))}
    </div>
  );
}

function FeedItem({ feed }: { feed: FeedCard }) {
  const notWorking = feed.status !== "active";
  return (
    <article className="flex flex-col border border-white/10 bg-white/[0.06] p-5 transition-colors hover:border-teal-300/50">
      <div className="flex items-start gap-4">
        <Logo name={feed.name} url={feed.logo_url} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-lg font-semibold text-white">{feed.name}</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {feed.provider_label && <span className={providerChip}>{feed.provider_label}</span>}
            {notWorking && <span className={`border px-2 py-1 text-xs capitalize ${feedStatusStyle[feed.status] ?? "border-white/15 text-slate-400"}`}>{feed.status}</span>}
          </div>
          {notWorking && feed.reason && <p className="mt-2 text-sm text-slate-400">{feed.reason}</p>}
        </div>
      </div>
      <div className="mt-auto flex items-center justify-between gap-3 pt-5">
        <span className="text-xs text-slate-500">
          {plural(feed.jobs, "job", "jobs")} · {feed.last_refreshed_at ? `updated ${ago(feed.last_refreshed_at)}` : "not read yet"}
        </span>
        <a href={feed.careers_url} target="_blank" rel="noreferrer" className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-slate-200 hover:bg-white/10">
          Careers page<span className="sr-only"> for {feed.name}, opens in a new tab</span>
        </a>
      </div>
    </article>
  );
}

function CompanyItem({ company }: { company: CompanyCard }) {
  return (
    <article className="flex flex-col border border-white/10 bg-white/[0.06] p-4">
      <div className="flex items-center gap-3">
        <Logo name={company.name} url={company.logo_url} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-semibold text-white">{company.name}</h3>
          <p className="mt-0.5 text-xs text-slate-400">{plural(company.postings, "posting", "postings")} seen</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {company.status === "feed" ? (
          <>
            {company.provider_label && <span className={providerChip}>{company.provider_label}</span>}
            {company.jobs !== null && <span className={chip}>reading {plural(company.jobs, "job", "jobs")}</span>}
          </>
        ) : company.status === "none" ? (
          <>
            <span className={chip}>No readable feed</span>
            {company.checked_at && <span className="text-xs text-slate-500">checked {ago(company.checked_at)}</span>}
          </>
        ) : (
          <span className={chip}>Not checked yet</span>
        )}
      </div>
    </article>
  );
}

const AVATAR_COLORS = [
  "bg-teal-500/20 text-teal-200",
  "bg-emerald-500/20 text-emerald-200",
  "bg-cyan-500/20 text-cyan-200",
  "bg-sky-500/20 text-sky-200",
  "bg-slate-500/30 text-slate-200",
];

function Logo({ name, url }: { name: string; url: string }) {
  const [failed, setFailed] = useState(false);
  if (url && !failed) {
    return <img src={url} alt="" onError={() => setFailed(true)} className="h-11 w-11 shrink-0 rounded-md bg-white object-contain p-1" />;
  }
  return (
    <div aria-hidden="true" className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-sm font-semibold ${AVATAR_COLORS[nameHash(name) % AVATAR_COLORS.length]}`}>
      {initials(name)}
    </div>
  );
}

function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-200">
      <p>Could not load companies. {error instanceof Error ? error.message : "Try again shortly."}</p>
      <button type="button" onClick={onRetry} className="rounded-md border border-red-300/40 px-3 py-1.5 text-red-100 hover:bg-red-400/10">Try again</button>
    </div>
  );
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join("").toUpperCase();
}

function nameHash(name: string): number {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

// The API sends UTC timestamps without a timezone suffix, which Date would read as local time.
function ago(timestamp: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(`${timestamp}Z`).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${plural(minutes, "minute", "minutes")} ago`;
  if (minutes < 1440) return `${plural(Math.floor(minutes / 60), "hour", "hours")} ago`;
  return `${plural(Math.floor(minutes / 1440), "day", "days")} ago`;
}
