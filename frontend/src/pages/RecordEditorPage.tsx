import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { FieldErrorList } from "../components/FieldErrorList";
import { Button, ConfidenceBadge, ErrorNotice, Panel, Spinner, StatusBadge } from "../components/ui";
import { useRecord, useRecordActions } from "../hooks/useApi";
import { ApiError } from "../lib/apiError";
import type { FinancialRecord } from "../lib/types";

const EDITABLE_FIELDS = [
  "reference",
  "transaction_date",
  "value_date",
  "description",
  "gross_amount",
  "fee_amount",
  "tax_amount",
  "net_amount",
  "currency",
  "counterparty_name",
  "counterparty_account",
  "country",
  "category",
  "invoice_number",
  "payment_method",
] as const;

export function RecordEditorPage() {
  const { recordId = "" } = useParams();
  const record = useRecord(recordId);

  if (record.isLoading) return <Spinner label="Loading…" />;
  if (record.isError || !record.data) {
    return <ErrorNotice message="This record is not available." />;
  }
  return <RecordEditor record={record.data} />;
}

/** Container for one record: owns the draft and the three actions. */
function RecordEditor({ record }: { record: FinancialRecord }) {
  const { correct, revalidate, validate } = useRecordActions(record);
  const [draft, setDraft] = useState<Record<string, string>>({});

  const errorsFor = (field: string) =>
    record.validation_errors.filter((error) => error.field === field);

  const actionError = [correct.error, revalidate.error, validate.error].find(Boolean);

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/batches/${record.batch_id}`} className="text-sm text-slate-500 hover:underline">
          ← Back to batch
        </Link>
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-slate-900">
            {record.reference ?? "Untitled record"}
          </h1>
          <StatusBadge status={record.status} />
          <ConfidenceBadge value={record.extraction_confidence} />
        </div>
        <p className="text-sm text-slate-500">
          {record.source_type} · {record.source_document_name}
        </p>
      </div>

      {actionError && (
        <ErrorNotice
          message={actionError instanceof ApiError ? actionError.message : "Action failed."}
        />
      )}

      <Panel title="Fields">
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            // The raw string is sent as typed: normalisation is server-side, so
            // "1 200,00" is handled there exactly as it is on import.
            correct.mutate(draft, { onSuccess: () => setDraft({}) });
          }}
        >
          {EDITABLE_FIELDS.map((field) => {
            const fieldErrors = errorsFor(field);
            const confidence = record.field_confidence?.[field];
            return (
              <label key={field} className="block">
                <span className="flex items-center gap-2 text-sm text-slate-700">
                  {field.replace(/_/g, " ")}
                  {confidence !== undefined && (
                    <ConfidenceBadge value={String(confidence)} />
                  )}
                </span>
                <input
                  value={draft[field] ?? record[field] ?? ""}
                  onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                  className={`mt-1 w-full rounded border px-3 py-1.5 text-sm ${
                    fieldErrors.length ? "border-red-400 bg-red-50" : "border-slate-300"
                  }`}
                />
                <FieldErrorList errors={fieldErrors} />
              </label>
            );
          })}

          <div className="sm:col-span-2 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
            <Button type="submit" disabled={correct.isPending || Object.keys(draft).length === 0}>
              Save and revalidate
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={revalidate.isPending}
              onClick={() => revalidate.mutate()}
            >
              Re-run validation
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={validate.isPending || record.status !== "VALID"}
              onClick={() => validate.mutate()}
              title={record.status !== "VALID" ? "Only a valid record can be validated" : ""}
            >
              Validate
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  );
}
