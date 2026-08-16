import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { signOut } from "../lib/session";
import { useAuthStore } from "../stores/authStore";
import { Button, Initials } from "./ui";

export function AppLayout({ children }: { children: ReactNode }) {
  const user = useAuthStore((state) => state.user);
  // The person's own name reads better than the address they signed up with.
  const firstName = user?.name.split(/\s+/)[0] ?? "";

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Link
            to="/batches"
            className="text-sm font-semibold tracking-tight text-slate-900 hover:text-slate-700"
          >
            Financial Records Import
          </Link>

          <div className="flex items-center gap-3">
            {user && (
              <span className="flex items-center gap-2">
                <Initials name={user.name} />
                <span className="hidden text-sm text-slate-700 sm:inline">
                  Hi, <span className="font-medium text-slate-900">{firstName}</span>
                </span>
              </span>
            )}
            <Button variant="ghost" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
