import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, ErrorNotice, Panel, Spinner } from "../components/ui";
import { useBatches, useCreateBatch } from "../hooks/useApi";

export function BatchListPage() {
  const batches = useBatches();
  const create = useCreateBatch();
  const [name, setName] = useState("");

  return (
    <div className="space-y-6">
      <Panel title="New import batch">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim()) return;
            create.mutate(name, { onSuccess: () => setName("") });
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="July 2026"
            className="flex-1 rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
          <Button type="submit" disabled={create.isPending}>
            Create
          </Button>
        </form>
        {create.isError && <ErrorNotice message="Could not create the batch." />}
      </Panel>

      <Panel title="Batches">
        {batches.isLoading && <Spinner label="Loading…" />}
        {batches.isError && <ErrorNotice message="Could not load batches." />}
        {batches.data?.length === 0 && (
          <p className="text-sm text-slate-500">No batch yet. Create one above.</p>
        )}
        <ul className="divide-y divide-slate-100">
          {batches.data?.map((batch) => (
            <li key={batch.id} className="py-2">
              <Link
                to={`/batches/${batch.id}`}
                className="flex items-center justify-between text-sm hover:underline"
              >
                <span className="font-medium text-slate-800">{batch.name}</span>
                <span className="text-slate-400">
                  {new Date(batch.created_at).toLocaleString()}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
