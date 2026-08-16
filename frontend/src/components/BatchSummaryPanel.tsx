import type { BatchSummary } from "../lib/types";
import { Panel, StatusBadge } from "./ui";

/** Presentational. Amounts are printed as received: the server is the only
 *  arithmetic authority, and currencies are never added together. */
export function BatchSummaryPanel({ summary }: { summary: BatchSummary }) {
  return (
    <Panel title="Summary">
      <div className="grid gap-8 sm:grid-cols-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Records</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums tracking-tight text-slate-900">
            {summary.total_records}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {Object.entries(summary.by_status).map(([status, count]) => (
              <span key={status} className="flex items-center gap-1">
                <StatusBadge status={status} />
                <span className="text-xs tabular-nums text-slate-500">{count}</span>
              </span>
            ))}
          </div>
        </div>

        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Documents</p>
          <ul className="mt-2 space-y-1 text-sm">
            {summary.documents.map((document) => (
              <li key={document.source_document_name} className="flex justify-between gap-3">
                <span className="truncate text-slate-600">{document.source_document_name}</span>
                <span className="tabular-nums text-slate-400">{document.count}</span>
              </li>
            ))}
            {summary.documents.length === 0 && <li className="text-slate-400">—</li>}
          </ul>
        </div>

        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Net by currency
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {summary.totals_by_currency.map((total) => (
              <li key={total.currency} className="flex justify-between gap-4">
                <span className="text-slate-600">{total.currency}</span>
                <span className="font-medium tabular-nums text-slate-900">{total.net_amount}</span>
              </li>
            ))}
            {summary.totals_by_currency.length === 0 && <li className="text-slate-400">—</li>}
          </ul>
          <p className="mt-2 text-xs text-slate-400">Never summed across currencies.</p>
        </div>
      </div>
    </Panel>
  );
}
