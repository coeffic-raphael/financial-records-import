import { useState } from "react";

import { useUploadCsv, useUploadPdfs } from "../hooks/useApi";
import { ApiError } from "../lib/apiError";
import { DropZone } from "./DropZone";
import { Button, ErrorNotice, Panel } from "./ui";

const CSV_PATTERN = /\.csv$/i;
const PDF_PATTERN = /\.pdf$/i;

/** Container: owns the upload mutations and routes files by kind. */
export function UploadPanel({ batchId }: { batchId: string }) {
  const csv = useUploadCsv(batchId);
  const pdfs = useUploadPdfs(batchId);
  const [rejected, setRejected] = useState<string[]>([]);
  // Held so the answer to the warning can send the very same files. Re-reading
  // them from the input would fail: the drop event is long gone.
  const [pending, setPending] = useState<{ csv: File[]; pdf: File[] } | null>(null);

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

    send(csvFiles, pdfFiles, false);
    if (unknown.length) setRejected(unknown.map((file) => file.name));
  }

  function send(csvFiles: File[], pdfFiles: File[], force: boolean) {
    setPending({ csv: csvFiles, pdf: pdfFiles });
    csvFiles.forEach((file) => csv.mutate({ file, force }));
    if (pdfFiles.length) pdfs.mutate({ files: pdfFiles, force });
  }

  const message = (error: unknown) =>
    error instanceof ApiError ? error.message : "Upload failed.";

  /**
   * A document already in this batch.
   *
   * Not an error to report and move on from: importing the supplied CSV twice
   * leaves 60 records, 42 of them needing review, and the only way back is
   * deleting the batch. So the answer is asked for, and the server is told it.
   */
  const duplicate = [csv.error, pdfs.error].find(
    (error): error is ApiError =>
      error instanceof ApiError && error.code === "DUPLICATE_DOCUMENT",
  );

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

      {duplicate && pending && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-medium text-amber-900">Already imported</p>
          <p className="mt-0.5 text-sm text-amber-800">
            {duplicate.message} Importing it again will add every row a second
            time, and each one will be flagged as a duplicate reference.
          </p>
          <div className="mt-3 flex items-center gap-3 text-sm">
            <Button type="button" onClick={() => send(pending.csv, pending.pdf, true)}>
              Import it again
            </Button>
            <button
              type="button"
              onClick={() => {
                setPending(null);
                csv.reset();
                pdfs.reset();
              }}
              className="text-slate-600 underline underline-offset-2 hover:text-slate-800"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {!duplicate &&
        (csv.isSuccess || pdfs.isSuccess || csv.isError || pdfs.isError || rejected.length > 0) && (
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
