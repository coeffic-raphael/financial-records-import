import { Link } from "react-router-dom";

import type { FinancialRecord } from "../lib/types";
import { ConfidenceBadge, EmptyState, StatusBadge } from "./ui";

/** Presentational. Receives rows, renders them, owns no data. */
export function RecordTable({ records }: { records: FinancialRecord[] }) {
  if (records.length === 0) {
    return <EmptyState title="No record matches these filters" hint="Try widening them." />;
  }

  return (
    <div className="-m-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <th className="px-4 py-2">Reference</th>
            <th className="px-4 py-2">Date</th>
            <th className="px-4 py-2">Counterparty</th>
            <th className="px-4 py-2 text-right">Net</th>
            <th className="px-4 py-2">Status</th>
            <th className="px-4 py-2">Issues</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {records.map((record) => (
            <RecordRow key={record.id} record={record} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecordRow({ record }: { record: FinancialRecord }) {
  const issues = record.validation_errors;

  return (
    <tr className="transition hover:bg-slate-50">
      <td className="px-4 py-2.5">
        <Link
          to={`/records/${record.id}`}
          className="font-medium text-slate-800 underline-offset-2 hover:underline"
        >
          {record.reference ?? <span className="italic text-slate-400">no reference</span>}
        </Link>
        <span className="ml-2 text-xs text-slate-400">{record.source_type}</span>
      </td>
      <td className="px-4 py-2.5 tabular-nums text-slate-600">
        {record.transaction_date ?? "—"}
      </td>
      <td className="max-w-52 truncate px-4 py-2.5 text-slate-600">
        {record.counterparty_name ?? "—"}
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-right font-medium tabular-nums text-slate-900">
        {record.net_amount ?? "—"}
        <span className="ml-1 text-xs font-normal text-slate-400">{record.currency ?? ""}</span>
      </td>
      <td className="px-4 py-2.5">
        <span className="flex items-center gap-2">
          <StatusBadge status={record.status} />
          <ConfidenceBadge value={record.extraction_confidence} />
        </span>
      </td>
      <td className="px-4 py-2.5">
        {issues.length === 0 ? (
          <span className="text-slate-300">—</span>
        ) : (
          <span className="text-xs text-amber-800" title={issues.map((e) => e.message).join("\n")}>
            {issues.length} issue{issues.length > 1 ? "s" : ""}
          </span>
        )}
      </td>
    </tr>
  );
}
