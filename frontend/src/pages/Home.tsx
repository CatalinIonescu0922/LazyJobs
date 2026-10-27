import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { logout, meQuery } from "../api";

export default function Home() {
  const { data: me } = useQuery(meQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: meQuery.queryKey });
      navigate("/sign-in", { replace: true });
    },
  });

  if (!me) {
    return null;
  }

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-3">
        <span className="font-semibold">CV Applier</span>
        <div className="flex items-center gap-3">
          {me.avatar_url && (
            <img
              src={me.avatar_url}
              alt=""
              referrerPolicy="no-referrer"
              className="h-8 w-8 rounded-full"
            />
          )}
          <span className="text-sm text-slate-700">{me.name || me.email}</span>
          <Link
            to="/profile"
            className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
          >
            Profile
          </Link>
          <Link
            to="/sources"
            className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
          >
            Job boards
          </Link>
          <button
            type="button"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
            className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="p-6">
        <h1 className="text-xl">Welcome, {me.name || me.email}</h1>
      </main>
    </div>
  );
}
