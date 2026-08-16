import type { BatchSummary } from "../lib/types";
import { Panel, StatusBadge } from "./ui";

/** Presentational. Amounts are printed as received: the server is the only
 *  arithmetic authority, and currencies are never added together. */
export function BatchSummaryPanel({ summary }: { summary: BatchSummary }) {
  return (
    <Panel title="Summary">
      <div className="grid gap-6 sm:grid-cols-3">
        <div>
          <p className="text-xs uppercase text-slate-400">Records</p>
          <p className="text-2xl font-semibold text-slate-900">{summary.total_records}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {Object.entries(summary.by_status).map(([status, count]) => (
              <span key={status}>
                <StatusBadge status={status} /> <span className="text-xs text-slate-500">{count}</span>
              </span>
            ))}
          </div>
        </div>

        <div>
          <p className="text-xs uppercase text-slate-400">Sources</p>
          <ul className="mt-1 text-sm text-slate-700">
            {Object.entries(summary.by_source_type).map(([source, count]) => (
              <li key={source}>
                {source}: {count}
              </li>
            ))}
          </ul>
          <ul className="mt-2 text-xs text-slate-500">
            {summary.documents.map((document) => (
              <li key={document.source_document_name}>
                {document.source_document_name} ({document.count})
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="text-xs uppercase text-slate-400">Net by currency</p>
          <ul className="mt-1 text-sm text-slate-700">
            {summary.totals_by_currency.map((total) => (
              <li key={total.currency} className="flex justify-between gap-4">
                <span>{total.currency}</span>
                <span className="tabular-nums">{total.net_amount}</span>
              </li>
            ))}
            {summary.totals_by_currency.length === 0 && (
              <li className="text-slate-400">—</li>
            )}
          </ul>
        </div>
      </div>
    </Panel>
  );
}
