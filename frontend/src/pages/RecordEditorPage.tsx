import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { FieldErrorList } from "../components/FieldErrorList";
import { SourceDocumentPanel } from "../components/SourceDocumentPanel";
import {
  Button,
  ConfidenceBadge,
  ErrorNotice,
  Panel,
  Spinner,
  StatusBadge,
} from "../components/ui";
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

  if (record.isLoading) return <Spinner label="Loading record…" />;
  if (record.isError || !record.data) {
    return <ErrorNotice message="This record is not available." />;
  }
  return <RecordEditor record={record.data} />;
}

/**
 * What the document actually said, when it differs from what is stored now.
 *
 * Telling "the model read this" from "someone typed this" is half the work of
 * checking an extraction, and the raw payload has always held the answer.
 */
function AsExtracted({
  current,
  original,
}: {
  current: string | null;
  original: string | null | undefined;
}) {
  const shown = original ?? "";
  if (!shown || shown === (current ?? "")) return null;

  return (
    <p className="mt-1 text-xs text-slate-500">
      As extracted: <span className="font-mono text-slate-600">{shown}</span>
    </p>
  );
}


/** Container for one record: owns the draft and the three actions. */
function RecordEditor({ record }: { record: FinancialRecord }) {
  const { correct, revalidate, validate } = useRecordActions(record);
  const [draft, setDraft] = useState<Record<string, string>>({});

  const errorsFor = (field: string) =>
    record.validation_errors.filter((error) => error.field === field);

  const actionError = [correct.error, revalidate.error, validate.error].find(Boolean);
  const dirty = Object.keys(draft).length > 0;
  const issues = record.validation_errors.length;

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={`/batches/${record.batch_id}`}
          className="text-sm text-slate-500 underline-offset-2 hover:text-slate-700 hover:underline"
        >
          ← Back to batch
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold tracking-tight text-slate-900">
            {record.reference ?? "Record without a reference"}
          </h1>
          <StatusBadge status={record.status} />
          <ConfidenceBadge value={record.extraction_confidence} />
        </div>
        <p className="mt-0.5 text-sm text-slate-500">
          {record.source_type} · {record.source_document_name}
        </p>
      </div>

      {issues > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-medium text-amber-900">
            {issues} issue{issues > 1 ? "s" : ""} to resolve
          </p>
          <p className="mt-0.5 text-sm text-amber-800">
            The affected fields are outlined below. Correcting one revalidates the whole record.
          </p>
        </div>
      )}

      {actionError && (
        <ErrorNotice
          message={actionError instanceof ApiError ? actionError.message : "Action failed."}
        />
      )}


      <SourceDocumentPanel
        recordId={record.id}
        filename={record.source_document_name}
        reference={record.raw_payload.reference ?? record.reference}
        available={record.has_source_document}
      />

      <Panel title="Fields">
        <form
          className="grid gap-x-6 gap-y-4 sm:grid-cols-2"
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
            const edited = field in draft;

            return (
              <label key={field} className="block">
                <span className="mb-1 flex items-center gap-2 text-sm font-medium text-slate-700">
                  {field.replace(/_/g, " ")}
                  {confidence !== undefined && <ConfidenceBadge value={String(confidence)} />}
                  {edited && <span className="text-xs font-normal text-sky-700">edited</span>}
                </span>
                <input
                  value={draft[field] ?? record[field] ?? ""}
                  onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                  className={`w-full rounded-lg border px-3 py-2 text-sm shadow-sm transition focus:outline focus:outline-2 focus:outline-offset-1 ${
                    fieldErrors.length
                      ? "border-red-300 bg-red-50 text-red-900 focus:outline-red-300"
                      : "border-slate-300 bg-white text-slate-900 focus:border-slate-400 focus:outline-slate-300"
                  }`}
                />
                <FieldErrorList errors={fieldErrors} />
                <AsExtracted current={record[field]} original={record.raw_payload[field]} />
              </label>
            );
          })}

          <div className="sm:col-span-2 mt-2 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
            <Button type="submit" disabled={correct.isPending || !dirty}>
              {correct.isPending ? "Saving…" : "Save and revalidate"}
            </Button>
            {/* Refused while the form is dirty. This re-checks the record AS
                STORED, replaying the pipeline from raw_payload -- a draft the
                user has typed but not saved is not part of it. Left enabled, it
                re-reads the old value while the screen shows the new one and
                reports the same issue, which reads as a broken button rather
                than as "you have not saved yet". */}
            <Button
              type="button"
              variant="ghost"
              disabled={revalidate.isPending || dirty}
              onClick={() => revalidate.mutate()}
              title={
                dirty
                  ? "Save your changes first — this re-checks the record as stored"
                  : "Check the stored record again against the current state of its batch"
              }
            >
              {revalidate.isPending ? "Re-checking…" : "Re-run validation"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={validate.isPending || record.status !== "VALID"}
              onClick={() => validate.mutate()}
              title={
                record.status === "VALID"
                  ? "Approve this record"
                  : "Only a record with no issues can be validated"
              }
            >
              Validate
            </Button>
            {/* Next to the buttons, not at the top of the page.
                The form is long -- a source document panel and fifteen fields --
                so a confirmation rendered above it lands off-screen, and a
                button whose result you cannot see reads as a broken one.

                Re-running validation replays the pipeline from raw_payload, so
                on an unchanged record it legitimately reaches the same verdict.
                Saying "nothing changed" is the useful answer: it tells a
                reviewer the remaining issues are real, not stale. */}
            {revalidate.isSuccess && !revalidate.isPending && (
              <p className="basis-full text-sm text-slate-600" role="status">
                Re-checked the saved record against its batch —{" "}
                {revalidate.data.validation_errors.length === 0
                  ? "no issues remain."
                  : `${revalidate.data.validation_errors.length} issue${
                      revalidate.data.validation_errors.length > 1 ? "s" : ""
                    } still to resolve.`}
              </p>
            )}
            {dirty && (
              <button
                type="button"
                onClick={() => setDraft({})}
                className="text-sm text-slate-500 underline underline-offset-2 hover:text-slate-700"
              >
                Discard changes
              </button>
            )}
          </div>
        </form>
      </Panel>
    </div>
  );
}
