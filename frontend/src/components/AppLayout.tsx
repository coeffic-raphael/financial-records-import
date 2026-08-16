import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { signOut } from "../lib/session";
import { useAuthStore } from "../stores/authStore";
import { Button } from "./ui";

export function AppLayout({ children }: { children: ReactNode }) {
  const user = useAuthStore((state) => state.user);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/batches" className="text-sm font-semibold text-slate-900">
            Financial Records Import
          </Link>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-500">{user?.email}</span>
            <Button variant="ghost" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-6xl px-4 py-6">{children}</div>
    </div>
  );
}
