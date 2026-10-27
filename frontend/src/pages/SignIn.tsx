export default function SignIn() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-6">
        <h1 className="text-2xl font-semibold">CV Applier</h1>
        <a
          href="/api/auth/google/login"
          className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700"
        >
          Continue with Google
        </a>
      </div>
    </main>
  );
}
