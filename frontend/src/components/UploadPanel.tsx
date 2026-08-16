import { useState } from "react";

import { useUploadCsv, useUploadPdfs } from "../hooks/useApi";
import { ApiError } from "../lib/apiError";
import { DropZone } from "./DropZone";
import { ErrorNotice, Panel } from "./ui";

const CSV_PATTERN = /\.csv$/i;
const PDF_PATTERN = /\.pdf$/i;

/** Container: owns the upload mutations and routes files by kind. */
export function UploadPanel({ batchId }: { batchId: string }) {
  const csv = useUploadCsv(batchId);
  const pdfs = useUploadPdfs(batchId);
  const [rejected, setRejected] = useState<string[]>([]);

  const busy = csv.isPending || pdfs.isPending;

  /**
   * One zone rather than two.
   *
   * Asking someone to know in advance which box a document belongs in is work
   * the interface can do itself: the extension already says which endpoint it
   * needs. Mixed drops are handled by sending each kind where it belongs.
   */
  function handleFiles(files: File[]) {
    setRejected([]);
    const csvFiles = files.filter((file) => CSV_PATTERN.test(file.name));
    const pdfFiles = files.filter((file) => PDF_PATTERN.test(file.name));
    const unknown = files.filter(
      (file) => !CSV_PATTERN.test(file.name) && !PDF_PATTERN.test(file.name),
    );

    csvFiles.forEach((file) => csv.mutate(file));
    if (pdfFiles.length) pdfs.mutate(pdfFiles);
    if (unknown.length) setRejected(unknown.map((file) => file.name));
  }

  const message = (error: unknown) =>
    error instanceof ApiError ? error.message : "Upload failed.";

  return (
    <Panel
      title="Upload"
      actions={busy ? <span className="text-xs text-slate-500">Uploading…</span> : null}
    >
      <DropZone onFiles={handleFiles} accept=".csv,application/pdf" disabled={busy}>
        <p className="text-sm font-medium text-slate-700">
          Drop a CSV or PDF documents here
        </p>
        <p className="mt-1 text-sm text-slate-500">
          or <span className="underline underline-offset-2">browse your files</span>
        </p>
        <p className="mt-3 text-xs text-slate-400">
          Every CSV row is imported; invalid ones are flagged, never dropped. PDFs are read
          by a model in the background.
        </p>
      </DropZone>

      {(csv.isSuccess || pdfs.isSuccess || csv.isError || pdfs.isError || rejected.length > 0) && (
        <div className="mt-4 space-y-2">
          {csv.isSuccess && (
            <p className="text-sm text-slate-600">
              Imported <strong className="tabular-nums">{csv.data.imported}</strong> rows from{" "}
              {csv.data.document_name}.
            </p>
          )}
          {pdfs.isSuccess && (
            <p className="text-sm text-slate-600">
              {pdfs.data.jobs.length} document(s) queued for extraction.
            </p>
          )}
          {rejected.length > 0 && (
            <ErrorNotice
              message={`Only CSV and PDF files are accepted. Ignored: ${rejected.join(", ")}`}
            />
          )}
          {csv.isError && <ErrorNotice message={message(csv.error)} />}
          {pdfs.isError && <ErrorNotice message={message(pdfs.error)} />}
        </div>
      )}
    </Panel>
  );
}
