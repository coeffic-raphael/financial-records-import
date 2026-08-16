import type { ReactNode } from "react";

/** Small presentational pieces shared across screens. Rendering only. */

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "subtle";
}) {
  const styles = {
    primary:
      "bg-slate-900 text-white hover:bg-slate-800 focus-visible:outline-slate-900 shadow-sm",
    ghost:
      "bg-white text-slate-700 border border-slate-300 hover:border-slate-400 hover:bg-slate-50",
    subtle: "bg-slate-100 text-slate-700 hover:bg-slate-200",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-40 ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm transition placeholder:text-slate-400 focus:border-slate-400 focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-slate-300 ${props.className ?? ""}`}
    />
  );
}

const STATUS_STYLES: Record<string, string> = {
  VALID: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  VALIDATED: "bg-sky-50 text-sky-700 ring-sky-600/20",
  NEEDS_REVIEW: "bg-amber-50 text-amber-800 ring-amber-600/20",
  PENDING: "bg-slate-50 text-slate-600 ring-slate-500/20",
  PROCESSING: "bg-indigo-50 text-indigo-700 ring-indigo-600/20",
  SUCCEEDED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  FAILED: "bg-red-50 text-red-700 ring-red-600/20",
};

export function StatusBadge({ status }: { status: string }) {
  const pulse = status === "PROCESSING" || status === "PENDING";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
        STATUS_STYLES[status] ?? "bg-slate-50 text-slate-600 ring-slate-500/20"
      }`}
    >
      {pulse && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {status.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

/** Extraction confidence, shown only when there is one: CSV rows have none. */
export function ConfidenceBadge({ value }: { value: string | null }) {
  if (value === null) return null;
  const score = Number(value);
  const tone =
    score >= 0.9 ? "text-emerald-700" : score >= 0.7 ? "text-amber-700" : "text-red-700";
  return (
    <span className={`text-xs font-medium tabular-nums ${tone}`} title="Extraction confidence">
      {Math.round(score * 100)}%
    </span>
  );
}

export function Panel({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-slate-200 bg-slate-50/60 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
        {actions}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <p
      className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 ring-1 ring-inset ring-red-600/20"
      role="alert"
    >
      {message}
    </p>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-slate-500">
      <span className="size-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-500" />
      {label}
    </p>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
    </div>
  );
}

/** A person's initials, used instead of an avatar we do not have. */
export function Initials({ name }: { name: string }) {
  const letters = name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <span className="grid size-7 place-items-center rounded-full bg-slate-900 text-xs font-semibold text-white">
      {letters || "?"}
    </span>
  );
}
