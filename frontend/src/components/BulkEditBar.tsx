import { useState } from "react";

import { useCorrectRecords } from "../hooks/useApi";
import { ApiError } from "../lib/apiError";
import { BULK_EDITABLE_FIELDS, fieldLabel } from "../lib/fields";
import type { FinancialRecord } from "../lib/types";
import { Button, ErrorNotice, TextInput } from "./ui";

/**
 * One correction, applied to every selected record.
 *
 * The reason it exists: the supplied bank statement yields eight records that
 * name no counterparty, because the document names none. Sixteen corrections
 * one screen at a time, for a value the reviewer knows once.
 */
export function BulkEditBar({
  batchId,
  records,
  selected,
  onDone,
}: {
  batchId: string;
  records: FinancialRecord[];
  selected: Set<string>;
  onDone: () => void;
}) {
  const [field, setField] = useState<string>("counterparty_name");
  const [value, setValue] = useState("");
  const correct = useCorrectRecords(batchId);

  if (selected.size === 0) return null;

  const chosen = records.filter((record) => selected.has(record.id));
  const approved = chosen.filter((record) => record.status === "VALIDATED").length;

  function apply() {
    correct.mutate(
      { record_ids: [...selected], changes: { [field]: value } },
      // Only on success: a failure keeps the selection so it can be retried
      // without ticking twenty boxes again.
      { onSuccess: onDone },
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-medium text-slate-700">{selected.size} selected</span>

        <select
          value={field}
          onChange={(event) => setField(event.target.value)}
          aria-label="Field to set"
          className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm"
        >
          {BULK_EDITABLE_FIELDS.map((name) => (
            <option key={name} value={name}>
              {fieldLabel(name)}
            </option>
          ))}
        </select>

        <TextInput
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="New value"
          aria-label="New value"
        />

        <Button type="button" disabled={correct.isPending} onClick={apply}>
          {correct.isPending ? "Applying…" : "Apply"}
        </Button>
        <button
          type="button"
          onClick={onDone}
          className="text-slate-500 underline underline-offset-2 hover:text-slate-700"
        >
          Cancel
        </button>
      </div>

      {/* Correcting a record drops it out of VALIDATED -- the assignment's own
          rule. Across forty rows that can undo approvals nobody meant to touch,
          so it is said before, not discovered after. Not refused: nothing
          re-approves in bulk either, and blocking would be a dead end. */}
      {approved > 0 && (
        <p className="mt-2 text-sm text-amber-800">
          {approved} of them {approved === 1 ? "is" : "are"} approved and will go back to
          needing validation.
        </p>
      )}

      {correct.isSuccess && (
        <p className="mt-2 text-sm text-slate-600" role="status">
          {correct.data.updated} record{correct.data.updated === 1 ? "" : "s"} updated —{" "}
          {Object.entries(correct.data.by_status)
            .map(([status, count]) => `${count} ${status.toLowerCase().replace("_", " ")}`)
            .join(", ")}
          .
        </p>
      )}

      {correct.isError && (
        <div className="mt-2">
          <ErrorNotice
            message={
              correct.error instanceof ApiError ? correct.error.message : "Could not apply."
            }
          />
        </div>
      )}
    </div>
  );
}

/** The header tick, counting what is actually on screen. */
export function SelectAllOnThisPage({
  records,
  selected,
  enabled,
  onChange,
}: {
  records: FinancialRecord[];
  selected: Set<string>;
  enabled: boolean;
  onChange: (next: Set<string>) => void;
}) {
  const allOnPage = records.every((record) => selected.has(record.id));

  return (
    <label className="flex items-center gap-2 px-4 pb-2 text-sm text-slate-600">
      <input
        type="checkbox"
        checked={records.length > 0 && allOnPage}
        disabled={!enabled || records.length === 0}
        onChange={() =>
          onChange(allOnPage ? new Set() : new Set(records.map((record) => record.id)))
        }
        className="size-4 rounded border-slate-300"
      />
      {/* The real count, not the page size: "the 25 on this page" on a last page
          of seven is the sentence that makes someone lose work. */}
      Select the {records.length} on this page
    </label>
  );
}
