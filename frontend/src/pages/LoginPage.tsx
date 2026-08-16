import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, ErrorNotice } from "../components/ui";
import { ApiError } from "../lib/apiError";
import { signIn, signUp } from "../lib/session";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("demo@example.com");
  const [password, setPassword] = useState("demo-password-123");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (mode === "signin" ? signIn(email, password) : signUp(email, password));
      navigate("/batches");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-24 max-w-sm px-4">
      <h1 className="mb-1 text-xl font-semibold text-slate-900">Financial Records Import</h1>
      <p className="mb-6 text-sm text-slate-500">
        {mode === "signin" ? "Sign in to your workspace." : "Create a workspace."}
      </p>

      <form onSubmit={submit} className="space-y-3">
        <label className="block">
          <span className="text-sm text-slate-700">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-sm text-slate-700">Password</span>
          <input
            type="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
        </label>

        {error && <ErrorNotice message={error} />}

        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "…" : mode === "signin" ? "Sign in" : "Create workspace"}
        </Button>
      </form>

      <button
        type="button"
        onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
        className="mt-4 text-sm text-slate-500 underline"
      >
        {mode === "signin" ? "Create a workspace instead" : "I already have an account"}
      </button>
    </main>
  );
}
