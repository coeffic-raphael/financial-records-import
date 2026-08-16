export interface Filters {
  status?: string;
  source_type?: string;
}

const SELECT =
  "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 shadow-sm focus:border-slate-400 focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-slate-300";

/** Presentational: the parent owns the state, this renders the controls. */
export function RecordFilters({
  filters,
  onChange,
  count,
}: {
  filters: Filters;
  onChange: (filters: Filters) => void;
  count?: number;
}) {
  const active = Boolean(filters.status || filters.source_type);

  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <label className="flex items-center gap-2">
        <span className="text-slate-500">Status</span>
        <select
          value={filters.status ?? ""}
          onChange={(event) => onChange({ ...filters, status: event.target.value || undefined })}
          className={SELECT}
        >
          <option value="">All</option>
          <option value="NEEDS_REVIEW">Needs review</option>
          <option value="VALID">Valid</option>
          <option value="VALIDATED">Validated</option>
        </select>
      </label>

      <label className="flex items-center gap-2">
        <span className="text-slate-500">Source</span>
        <select
          value={filters.source_type ?? ""}
          onChange={(event) =>
            onChange({ ...filters, source_type: event.target.value || undefined })
          }
          className={SELECT}
        >
          <option value="">All</option>
          <option value="CSV">CSV</option>
          <option value="PDF">PDF</option>
        </select>
      </label>

      {active && (
        <button
          type="button"
          onClick={() => onChange({})}
          className="text-slate-500 underline underline-offset-2 hover:text-slate-700"
        >
          Clear
        </button>
      )}

      {count !== undefined && (
        <span className="ml-auto tabular-nums text-slate-400">{count} shown</span>
      )}
    </div>
  );
}
