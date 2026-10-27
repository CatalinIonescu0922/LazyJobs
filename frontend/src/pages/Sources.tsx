import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addSource,
  discoverSources,
  refreshSource,
  profileQuery,
  sourcesQuery,
  Source,
  updateSource,
} from "../api";

export default function Sources() {
  const queryClient = useQueryClient();
  const sources = useQuery(sourcesQuery);
  const profile = useQuery(profileQuery);
  const [domain, setDomain] = useState("");
  const [message, setMessage] = useState("");
  const [refreshing, setRefreshing] = useState<number | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: sourcesQuery.queryKey });
  const discover = useMutation({
    mutationFn: () => discoverSources("boards"),
    onSuccess: (result) => {
      setMessage(`${result.created} new board${result.created === 1 ? "" : "s"} added`);
      invalidate();
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "Board discovery failed"),
  });
  const add = useMutation({
    mutationFn: () => addSource(domain),
    onSuccess: () => {
      setDomain("");
      setMessage("Board added");
      invalidate();
    },
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateSource(id, enabled),
    onSuccess: invalidate,
  });

  async function refresh(id: number) {
    setRefreshing(id);
    try {
      const result = await refreshSource(id);
      setMessage(`${result.added} added, ${result.failed} failed`);
      invalidate();
    } finally {
      setRefreshing(null);
    }
  }

  if (sources.isPending) return <p className="p-6 text-slate-500">Loading boards...</p>;
  if (sources.isError) return <p className="p-6 text-red-600">Could not load job boards.</p>;

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 text-slate-900 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium uppercase tracking-wide text-teal-700">Job sources</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Your job boards</h1>
            <p className="mt-2 text-slate-600">Discover crawlable job-board websites for {profile.data?.country || "your profile country"}, then verify them one at a time.</p>
          </div>
          {message && <p className="text-sm text-teal-700">{message}</p>}
        </header>

        <section className="mb-6 flex flex-wrap gap-3 border border-slate-200 bg-white p-5 shadow-sm">
          <button type="button" onClick={() => discover.mutate()} disabled={discover.isPending || !profile.data?.country} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50">
            {discover.isPending ? "Finding boards..." : profile.data?.country ? `Find boards for ${profile.data.country}` : "Set country in Profile"}
          </button>
          <form onSubmit={(event) => { event.preventDefault(); if (domain.trim()) add.mutate(); }} className="flex min-w-[280px] flex-1 gap-2">
            <input value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="Add a domain" className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm" />
            <button type="submit" disabled={add.isPending || !domain.trim()} className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 disabled:opacity-50">Add</button>
          </form>
        </section>
        {!profile.data?.country && (
          <p className="mb-6 border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            Add your country on the Profile page before discovering job boards.
          </p>
        )}

        <section className="overflow-x-auto border border-slate-200 bg-white shadow-sm">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-3">Board</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Tier</th><th className="px-4 py-3">Postings</th><th className="px-4 py-3">Reason</th><th className="px-4 py-3">Action</th></tr>
            </thead>
            <tbody>
              {sources.data.map((source) => (
                <tr key={source.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-4 font-medium">{source.domain}</td>
                  <td className="px-4 py-4"><span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusStyle[source.status] ?? "bg-slate-100 text-slate-700"}`}>{source.status}</span></td>
                  <td className="px-4 py-4 text-slate-600">{source.extraction || "pending"}</td>
                  <td className="px-4 py-4 text-slate-600">{source.posting_count}</td>
                  <td className="max-w-xs px-4 py-4 text-slate-600">{source.reason || "Ready to validate"}</td>
                  <td className="px-4 py-4"><div className="flex gap-2"><button type="button" onClick={() => refresh(source.id)} disabled={refreshing !== null || source.status === "disabled"} className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50">{refreshing === source.id ? "Refreshing..." : "Refresh"}</button><button type="button" onClick={() => toggle.mutate({ id: source.id, enabled: source.status === "disabled" })} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100">{source.status === "disabled" ? "Enable" : "Disable"}</button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
          {sources.data.length === 0 && <p className="p-8 text-center text-slate-500">No boards yet. Discover boards or add one above.</p>}
        </section>
      </div>
    </main>
  );
}

const statusStyle: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  candidate: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
  disabled: "bg-slate-200 text-slate-700",
};
