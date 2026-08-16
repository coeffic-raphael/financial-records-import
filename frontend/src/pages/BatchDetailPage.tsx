import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BatchSummaryPanel } from "../components/BatchSummaryPanel";
import { ExtractionJobList } from "../components/ExtractionJobList";
import { RecordFilters, type Filters } from "../components/RecordFilters";
import { Pagination } from "../components/Pagination";
import { RecordTable } from "../components/RecordTable";
import { UploadPanel } from "../components/UploadPanel";
import { ErrorNotice, Panel, Spinner } from "../components/ui";
import { useBatch, useJobs, useRecords, useSummary } from "../hooks/useApi";

/** Container: owns the queries and the filter state, renders panels. */
export function BatchDetailPage() {
  const { batchId = "" } = useParams();
  const [filters, setFilters] = useState<Filters>({});
  const [offset, setOffset] = useState(0);

  /** A new filter means a new set, so page 3 of the old one is meaningless. */
  const changeFilters = (next: Filters) => {
    setFilters(next);
    setOffset(0);
  };

  const batch = useBatch(batchId);
  const records = useRecords(batchId, filters, offset);
  const summary = useSummary(batchId);
  const jobs = useJobs(batchId);

  if (batch.isLoading) return <Spinner label="Loading batch…" />;
  if (batch.isError) return <ErrorNotice message="This batch is not available." />;

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/batches"
          className="text-sm text-slate-500 underline-offset-2 hover:text-slate-700 hover:underline"
        >
          ← All batches
        </Link>
        <h1 className="mt-1 text-lg font-semibold tracking-tight text-slate-900">
          {batch.data?.name}
        </h1>
      </div>

      <UploadPanel batchId={batchId} />
      {jobs.data && <ExtractionJobList jobs={jobs.data} />}
      {summary.data && <BatchSummaryPanel summary={summary.data} />}

      <Panel
        title="Records"
        actions={
          <RecordFilters filters={filters} onChange={changeFilters} count={records.data?.total} />
        }
      >
        {records.isLoading && <Spinner label="Loading records…" />}
        {records.isError && <ErrorNotice message="Could not load records." />}
        {records.data && (
          <>
            <RecordTable records={records.data.items} />
            <Pagination
              offset={records.data.offset}
              limit={records.data.limit}
              total={records.data.total}
              onChange={setOffset}
            />
          </>
        )}
      </Panel>
    </div>
  );
}
