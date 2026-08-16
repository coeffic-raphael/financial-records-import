import type { ReactNode } from "react";

/** Small presentational pieces shared across screens. Rendering only. */

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-slate-900 text-white hover:bg-slate-700",
    ghost: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50",
    danger: "bg-red-600 text-white hover:bg-red-500",
  }[variant];
  return (
    <button
      {...props}
      className={`rounded px-3 py-1.5 text-sm font-medium transition disabled:opacity-40 ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

const STATUS_STYLES: Record<string, string> = {
  VALID: "bg-emerald-100 text-emerald-800",
  VALIDATED: "bg-sky-100 text-sky-800",
  NEEDS_REVIEW: "bg-amber-100 text-amber-900",
  PENDING: "bg-slate-100 text-slate-700",
  PROCESSING: "bg-indigo-100 text-indigo-800",
  SUCCEEDED: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-800",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700"
      }`}
    >
      {status.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

/** Extraction confidence, shown only when there is one: CSV rows have none. */
export function ConfidenceBadge({ value }: { value: string | null }) {
  if (value === null) return null;
  const score = Number(value);
  const tone = score >= 0.9 ? "text-emerald-700" : score >= 0.7 ? "text-amber-700" : "text-red-700";
  return <span className={`text-xs font-medium ${tone}`}>{Math.round(score * 100)}%</span>;
}

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded border border-slate-200 bg-white">
      <h2 className="border-b border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700">
        {title}
      </h2>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
      {message}
    </p>
  );
}

export function Spinner({ label }: { label: string }) {
  return <p className="text-sm text-slate-500">{label}</p>;
}
