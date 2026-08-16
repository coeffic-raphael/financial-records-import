import { Link } from "react-router-dom";

import type { FinancialRecord } from "../lib/types";
import { ConfidenceBadge, StatusBadge } from "./ui";

/** Presentational. Receives rows, renders them, owns no data. */
export function RecordTable({ records }: { records: FinancialRecord[] }) {
  if (records.length === 0) {
    return <p className="text-sm text-slate-500">No record matches these filters.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-slate-400">
          <tr>
            <th className="pb-1">Reference</th>
            <th className="pb-1">Date</th>
            <th className="pb-1">Counterparty</th>
            <th className="pb-1 text-right">Net</th>
            <th className="pb-1">Status</th>
            <th className="pb-1">Issues</th>
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
  return (
    <tr className="hover:bg-slate-50">
      <td className="py-1.5">
        <Link to={`/records/${record.id}`} className="font-medium text-slate-800 hover:underline">
          {record.reference ?? <span className="italic text-slate-400">missing</span>}
        </Link>
      </td>
      <td className="py-1.5 text-slate-600">{record.transaction_date ?? "—"}</td>
      <td className="py-1.5 text-slate-600">{record.counterparty_name ?? "—"}</td>
      <td className="py-1.5 text-right tabular-nums text-slate-800">
        {record.net_amount ?? "—"} {record.currency ?? ""}
      </td>
      <td className="py-1.5">
        <StatusBadge status={record.status} />{" "}
        <ConfidenceBadge value={record.extraction_confidence} />
      </td>
      <td className="py-1.5 text-xs text-slate-500">
        {record.validation_errors.map((error) => error.code).join(", ") || "—"}
      </td>
    </tr>
  );
}
