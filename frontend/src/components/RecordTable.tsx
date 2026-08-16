import { useState } from "react";
import { useNavigate } from "react-router-dom";

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
            <th className="w-8 px-4 py-2" />
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
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const issues = record.validation_errors;
  const open = () => navigate(`/records/${record.id}`);

  return (
    <>
      {/* The whole row opens the record. Making only the reference a link left
          the obvious target -- the issue count someone wants to act on -- inert,
          so the way to review was not discoverable at all. */}
      <tr
        onClick={open}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open();
          }
        }}
        tabIndex={0}
        role="link"
        aria-label={`Open record ${record.reference ?? "without reference"}`}
        className="cursor-pointer transition hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-slate-400"
      >
        <td className="px-4 py-2.5">
          <span className="font-medium text-slate-800">
            {record.reference ?? <span className="italic text-slate-400">no reference</span>}
          </span>
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
            <button
              type="button"
              // Stops the row from opening: this is a peek, not a departure.
              onClick={(event) => {
                event.stopPropagation();
                setExpanded(!expanded);
              }}
              className="rounded text-xs font-medium text-amber-800 underline underline-offset-2 hover:text-amber-900"
              aria-expanded={expanded}
            >
              {issues.length} issue{issues.length > 1 ? "s" : ""} {expanded ? "▴" : "▾"}
            </button>
          )}
        </td>
        <td className="px-4 py-2.5 text-right text-slate-300">›</td>
      </tr>

      {expanded && (
        <tr className="bg-amber-50/40">
          <td colSpan={7} className="px-4 py-3">
            <ul className="space-y-1.5">
              {issues.map((issue) => (
                <li key={issue.code + issue.field} className="flex gap-2 text-xs">
                  <span className="w-44 shrink-0 font-medium text-slate-700">
                    {issue.field.replace(/_/g, " ")}
                  </span>
                  <span className="font-mono text-[11px] text-red-800">{issue.code}</span>
                  <span className="text-slate-600">{issue.message}</span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={open}
              className="mt-2 text-xs font-medium text-slate-700 underline underline-offset-2 hover:text-slate-900"
            >
              Open this record to fix it →
            </button>
          </td>
        </tr>
      )}
    </>
  );
}
