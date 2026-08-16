import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, ErrorNotice, Field, TextInput } from "../components/ui";
import { ApiError } from "../lib/apiError";
import { signIn, signUp } from "../lib/session";

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("demo@example.com");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("demo-password-123");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signingUp = mode === "signup";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (signingUp ? signUp(email, name, password) : signIn(email, password));
      navigate("/batches");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            Financial Records Import
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {signingUp
              ? "Create a workspace of your own."
              : "Import, validate and approve financial records."}
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
        >
          {signingUp && (
            <Field label="Name">
              <TextInput
                required
                autoFocus
                value={name}
                placeholder="Marie Dupont"
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
          )}

          <Field label="Email">
            <TextInput
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>

          <Field label="Password" hint={signingUp ? "At least 12 characters." : undefined}>
            <TextInput
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>

          {error && <ErrorNotice message={error} />}

          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "One moment…" : signingUp ? "Create workspace" : "Sign in"}
          </Button>
        </form>

        <p className="mt-4 text-center text-sm text-slate-500">
          {signingUp ? "Already have an account?" : "No account yet?"}{" "}
          <button
            type="button"
            onClick={() => {
              setMode(signingUp ? "signin" : "signup");
              setError(null);
            }}
            className="font-medium text-slate-700 underline underline-offset-2 hover:text-slate-900"
          >
            {signingUp ? "Sign in" : "Create a workspace"}
          </button>
        </p>
      </div>
    </main>
  );
}
