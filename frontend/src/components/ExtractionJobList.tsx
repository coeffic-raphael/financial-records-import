import type { ExtractionJob } from "../lib/types";
import { Panel, StatusBadge } from "./ui";

/** Presentational: shows extraction progress. Polling lives in the hook. */
export function ExtractionJobList({ jobs }: { jobs: ExtractionJob[] }) {
  if (jobs.length === 0) return null;

  const running = jobs.filter((job) => job.status === "PENDING" || job.status === "PROCESSING");

  return (
    <Panel
      title="Extractions"
      actions={
        running.length > 0 ? (
          <span className="text-xs text-slate-500">{running.length} in progress…</span>
        ) : null
      }
    >
      <div className="-m-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2">Document</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">Records</th>
              <th className="px-4 py-2 text-right">Tokens in / out</th>
              <th className="px-4 py-2 text-right">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {jobs.map((job) => (
              <tr key={job.id}>
                <td className="max-w-64 truncate px-4 py-2.5 text-slate-700">
                  {job.document_name}
                </td>
                <td className="px-4 py-2.5">
                  <StatusBadge status={job.status} />
                  {job.error && (
                    <p className="mt-1 max-w-80 text-xs text-red-700">{job.error}</p>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-700">
                  {job.record_count ?? "—"}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                  {job.input_tokens === null
                    ? "—"
                    : `${job.input_tokens} / ${job.output_tokens ?? 0}`}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">
                  {job.duration_ms === null ? "—" : `${(job.duration_ms / 1000).toFixed(1)} s`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
