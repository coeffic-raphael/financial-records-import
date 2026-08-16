import type { ExtractionJob } from "../lib/types";
import { Panel, StatusBadge } from "./ui";

/** Presentational: shows extraction progress. Polling lives in the hook. */
export function ExtractionJobList({ jobs }: { jobs: ExtractionJob[] }) {
  if (jobs.length === 0) return null;

  return (
    <Panel title="Extractions">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-slate-400">
          <tr>
            <th className="pb-1">Document</th>
            <th className="pb-1">Status</th>
            <th className="pb-1 text-right">Records</th>
            <th className="pb-1 text-right">Tokens</th>
            <th className="pb-1 text-right">Duration</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {jobs.map((job) => (
            <tr key={job.id}>
              <td className="py-1.5 text-slate-700">{job.document_name}</td>
              <td className="py-1.5">
                <StatusBadge status={job.status} />
                {job.error && <span className="ml-2 text-xs text-red-700">{job.error}</span>}
              </td>
              <td className="py-1.5 text-right text-slate-600">{job.record_count ?? "—"}</td>
              <td className="py-1.5 text-right text-slate-500">
                {job.input_tokens === null
                  ? "—"
                  : `${job.input_tokens} / ${job.output_tokens ?? 0}`}
              </td>
              <td className="py-1.5 text-right text-slate-500">
                {job.duration_ms === null ? "—" : `${(job.duration_ms / 1000).toFixed(1)} s`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
