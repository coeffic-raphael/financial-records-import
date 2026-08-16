import { useUploadCsv, useUploadPdfs } from "../hooks/useApi";
import { ApiError } from "../lib/apiError";
import { ErrorNotice, Panel } from "./ui";

/** Container: owns the upload mutations, renders two file inputs. */
export function UploadPanel({ batchId }: { batchId: string }) {
  const csv = useUploadCsv(batchId);
  const pdfs = useUploadPdfs(batchId);

  const message = (error: unknown) =>
    error instanceof ApiError ? error.message : "Upload failed.";

  return (
    <Panel title="Upload">
      <div className="flex flex-wrap items-center gap-6">
        <label className="text-sm">
          <span className="mr-2 text-slate-600">CSV</span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="text-sm"
            onChange={(event) => {
              const file = event.target.files?.[0];
              // Cleared so that picking the SAME file again still fires change.
              event.target.value = "";
              if (file) csv.mutate(file);
            }}
          />
        </label>

        <label className="text-sm">
          <span className="mr-2 text-slate-600">PDF</span>
          <input
            type="file"
            accept="application/pdf"
            multiple
            className="text-sm"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (files.length) pdfs.mutate(files);
            }}
          />
        </label>

        {(csv.isPending || pdfs.isPending) && (
          <span className="text-sm text-slate-500">Uploading…</span>
        )}
      </div>

      {csv.isSuccess && (
        <p className="mt-3 text-sm text-slate-600">
          Imported {csv.data.imported} rows from {csv.data.document_name}.
        </p>
      )}
      {pdfs.isSuccess && (
        <p className="mt-3 text-sm text-slate-600">
          {pdfs.data.jobs.length} document(s) queued for extraction.
        </p>
      )}
      {csv.isError && <ErrorNotice message={message(csv.error)} />}
      {pdfs.isError && <ErrorNotice message={message(pdfs.error)} />}
    </Panel>
  );
}
