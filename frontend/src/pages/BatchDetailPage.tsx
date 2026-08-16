import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BatchSummaryPanel } from "../components/BatchSummaryPanel";
import { ExtractionJobList } from "../components/ExtractionJobList";
import { RecordFilters, type Filters } from "../components/RecordFilters";
import { RecordTable } from "../components/RecordTable";
import { UploadPanel } from "../components/UploadPanel";
import { ErrorNotice, Panel, Spinner } from "../components/ui";
import { useBatch, useJobs, useRecords, useSummary } from "../hooks/useApi";

/** Container: owns the queries and the filter state, renders panels. */
export function BatchDetailPage() {
  const { batchId = "" } = useParams();
  const [filters, setFilters] = useState<Filters>({});

  const batch = useBatch(batchId);
  const records = useRecords(batchId, filters);
  const summary = useSummary(batchId);
  const jobs = useJobs(batchId);

  if (batch.isLoading) return <Spinner label="Loading…" />;
  if (batch.isError) return <ErrorNotice message="This batch is not available." />;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/batches" className="text-sm text-slate-500 hover:underline">
          ← All batches
        </Link>
        <h1 className="text-lg font-semibold text-slate-900">{batch.data?.name}</h1>
      </div>

      <UploadPanel batchId={batchId} />
      {jobs.data && <ExtractionJobList jobs={jobs.data} />}
      {summary.data && <BatchSummaryPanel summary={summary.data} />}

      <RecordFilters filters={filters} onChange={setFilters} />

      <Panel title="Records">
        {records.isLoading && <Spinner label="Loading…" />}
        {records.isError && <ErrorNotice message="Could not load records." />}
        {records.data && <RecordTable records={records.data} />}
      </Panel>
    </div>
  );
}
