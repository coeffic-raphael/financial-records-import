import { useEffect, useState } from "react";

import { api } from "../lib/apiClient";
import { Panel, Spinner } from "./ui";

/**
 * The document a record was extracted from, next to the values it produced.
 *
 * Reviewing an extraction means comparing it to its source. Without this the
 * approval step confirms the machine's own consistency check rather than the
 * data, which is not what approving is supposed to mean.
 *
 * What "showing the source" means depends on the source. A PDF is a page to
 * look at; a CSV is one line among many, and rendering the file would bury the
 * line that matters. So each kind gets the view that answers the question.
 */
export function SourceDocumentPanel({
  recordId,
  filename,
  reference,
  available,
}: {
  recordId: string;
  filename: string;
  reference: string | null;
  available: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const isPdf = filename.toLowerCase().endsWith(".pdf");

  useEffect(() => {
    if (!available) return;
    let revoked: string | null = null;

    void (async () => {
      try {
        // Fetched through the API client so the bearer token travels: the
        // document is tenant-scoped like everything else, and a plain <object
        // data> would arrive unauthenticated.
        const blob = await api.blob(`/api/records/${recordId}/document`);
        revoked = URL.createObjectURL(blob);
        setUrl(revoked);
        if (!isPdf) setText(await blob.text());
      } catch {
        setFailed(true);
      }
    })();

    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [recordId, available, isPdf]);

  if (!available) {
    return (
      <Panel title="Source document">
        <p className="text-sm text-slate-500">
          This record has no stored document. Records imported before documents were kept
          cannot be checked against their source.
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      title="Source document"
      actions={
        <span className="flex items-center gap-3 text-xs text-slate-500">
          <span>{filename}</span>
          {url && (
            <a
              href={url}
              download={filename}
              className="underline underline-offset-2 hover:text-slate-700"
            >
              Download
            </a>
          )}
        </span>
      }
    >
      {failed && <p className="text-sm text-slate-500">The document could not be loaded.</p>}
      {!failed && !url && <Spinner label="Loading the document…" />}

      {url && isPdf && (
        <object
          data={url}
          type="application/pdf"
          className="h-[32rem] w-full rounded-lg border border-slate-200"
        >
          <p className="p-4 text-sm text-slate-600">
            This browser cannot display the file inline.{" "}
            <a href={url} download={filename} className="underline">
              Download {filename}
            </a>
            .
          </p>
        </object>
      )}

      {url && !isPdf && text !== null && <CsvExcerpt text={text} reference={reference} />}
    </Panel>
  );
}

/**
 * The header and the one line this record came from.
 *
 * Rendering thirty rows would make the reviewer hunt for the relevant one,
 * which is the opposite of what a source view is for.
 */
function CsvExcerpt({ text, reference }: { text: string; reference: string | null }) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  const header = lines[0] ?? "";
  const match = reference
    ? lines.slice(1).find((line) => line.split(",")[0] === reference)
    : undefined;

  if (!match) {
    return (
      <div>
        <p className="mb-2 text-sm text-slate-500">
          The originating line could not be located; here are the first lines of the file.
        </p>
        <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
          {lines.slice(0, 4).join("\n")}
        </pre>
      </div>
    );
  }

  const columns = header.split(",");
  const values = match.split(",");

  return (
    <div>
      <p className="mb-2 text-sm text-slate-500">The line this record was imported from.</p>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-xs">
          <tbody className="divide-y divide-slate-100">
            {columns.map((column, index) => (
              <tr key={column} className="even:bg-slate-50/60">
                <th className="w-52 px-3 py-1.5 text-left font-medium text-slate-500">
                  {column}
                </th>
                <td className="px-3 py-1.5 font-mono text-slate-800">
                  {values[index] || <span className="text-slate-300">empty</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
