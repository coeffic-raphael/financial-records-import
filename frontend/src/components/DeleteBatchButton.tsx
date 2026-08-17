import { useState } from "react";

import { useDeleteBatch, useSummary } from "../hooks/useApi";
import type { Batch } from "../lib/types";

/**
 * Deleting a batch: the only way to undo an import.
 *
 * It is not refused on a batch holding approved records. That guard would be
 * defensible, but nothing un-approves a record, so it would leave batches that
 * can never be removed. This states what is about to go instead — including
 * how many records were approved — so the fact reaches the person at the
 * moment they decide.
 */
export function DeleteBatchButton({ batch }: { batch: Batch }) {
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteBatch();
  // Only fetched once asked for: a count per row on every visit would be a
  // request per batch to serve a rare click.
  const summary = useSummary(batch.id, confirming);

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="rounded-lg px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-red-50 hover:text-red-700"
        aria-label={`Delete batch ${batch.name}`}
      >
        Delete
      </button>
    );
  }

  const total = summary.data?.total_records;
  const approved = summary.data?.by_status.VALIDATED ?? 0;

  return (
    <span className="flex items-center gap-3 text-xs">
      <span className="text-slate-600" role="status">
        {summary.isLoading || total === undefined ? (
          "Checking what this holds…"
        ) : (
          <>
            Delete <strong>{batch.name}</strong> and its {total} record
            {total === 1 ? "" : "s"}?
            {approved > 0 && (
              <span className="text-red-700">
                {" "}
                {approved} {approved === 1 ? "is" : "are"} approved.
              </span>
            )}
          </>
        )}
      </span>
      <button
        type="button"
        disabled={remove.isPending || summary.isLoading}
        onClick={() => remove.mutate(batch.id)}
        className="rounded-lg bg-red-600 px-2.5 py-1 font-medium text-white transition hover:bg-red-700 disabled:opacity-50"
      >
        {remove.isPending ? "Deleting…" : "Delete"}
      </button>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        className="text-slate-500 underline underline-offset-2 hover:text-slate-700"
      >
        Cancel
      </button>
    </span>
  );
}
