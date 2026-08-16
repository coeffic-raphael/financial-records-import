import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, EmptyState, ErrorNotice, Panel, Spinner, TextInput } from "../components/ui";
import { useBatches, useCreateBatch } from "../hooks/useApi";

export function BatchListPage() {
  const batches = useBatches();
  const create = useCreateBatch();
  const [name, setName] = useState("");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-slate-900">Import batches</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          A batch groups the documents imported together and the records they produced.
        </p>
      </div>

      <Panel title="New batch">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim()) return;
            create.mutate(name, { onSuccess: () => setName("") });
          }}
        >
          <TextInput
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="July 2026"
          />
          <Button type="submit" disabled={create.isPending || !name.trim()}>
            Create
          </Button>
        </form>
        {create.isError && <ErrorNotice message="Could not create the batch." />}
      </Panel>

      <Panel title="Batches">
        {batches.isLoading && <Spinner label="Loading batches…" />}
        {batches.isError && <ErrorNotice message="Could not load batches." />}
        {batches.data?.length === 0 && (
          <EmptyState title="No batch yet" hint="Create one above, then upload a CSV or PDFs." />
        )}
        {batches.data && batches.data.length > 0 && (
          <ul className="-m-4 divide-y divide-slate-100">
            {batches.data.map((batch) => (
              <li key={batch.id}>
                <Link
                  to={`/batches/${batch.id}`}
                  className="flex items-center justify-between px-4 py-3 transition hover:bg-slate-50"
                >
                  <span className="text-sm font-medium text-slate-800">{batch.name}</span>
                  <span className="text-xs tabular-nums text-slate-400">
                    {new Date(batch.created_at).toLocaleString()}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
