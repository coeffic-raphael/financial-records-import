import { Panel } from "./ui";

export interface Filters {
  status?: string;
  source_type?: string;
}

/** Presentational: the parent owns the state, this renders the controls. */
export function RecordFilters({
  filters,
  onChange,
}: {
  filters: Filters;
  onChange: (filters: Filters) => void;
}) {
  return (
    <Panel title="Filters">
      <div className="flex flex-wrap gap-4 text-sm">
        <label>
          <span className="mr-2 text-slate-600">Status</span>
          <select
            value={filters.status ?? ""}
            onChange={(event) => onChange({ ...filters, status: event.target.value || undefined })}
            className="rounded border border-slate-300 px-2 py-1"
          >
            <option value="">All</option>
            <option value="NEEDS_REVIEW">Needs review</option>
            <option value="VALID">Valid</option>
            <option value="VALIDATED">Validated</option>
          </select>
        </label>

        <label>
          <span className="mr-2 text-slate-600">Source</span>
          <select
            value={filters.source_type ?? ""}
            onChange={(event) =>
              onChange({ ...filters, source_type: event.target.value || undefined })
            }
            className="rounded border border-slate-300 px-2 py-1"
          >
            <option value="">All</option>
            <option value="CSV">CSV</option>
            <option value="PDF">PDF</option>
          </select>
        </label>
      </div>
    </Panel>
  );
}
