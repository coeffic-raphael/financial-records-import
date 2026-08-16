/** Presentational: the parent owns the offset, this renders the controls. */
export function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  // Nothing to page through: showing dead controls would only suggest there is
  // more to see than there is.
  if (total <= limit) return null;

  const first = offset + 1;
  const last = Math.min(offset + limit, total);
  const isFirstPage = offset === 0;
  const isLastPage = last >= total;

  return (
    <nav
      aria-label="Records pagination"
      className="flex items-center justify-between gap-4 border-t border-slate-200 px-4 py-3 text-sm"
    >
      <p className="tabular-nums text-slate-500" aria-live="polite">
        {first}–{last} of {total}
      </p>

      <div className="flex items-center gap-2">
        <PageButton
          disabled={isFirstPage}
          onClick={() => onChange(Math.max(0, offset - limit))}
          label="Previous"
        />
        <PageButton
          disabled={isLastPage}
          onClick={() => onChange(offset + limit)}
          label="Next"
        />
      </div>
    </nav>
  );
}

function PageButton({
  disabled,
  onClick,
  label,
}: {
  disabled: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-white"
    >
      {label}
    </button>
  );
}
