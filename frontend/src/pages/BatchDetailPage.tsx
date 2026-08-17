import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BatchSummaryPanel } from "../components/BatchSummaryPanel";
import { ExtractionJobList } from "../components/ExtractionJobList";
import { RecordFilters, type Filters } from "../components/RecordFilters";
import { BulkEditBar, SelectAllOnThisPage } from "../components/BulkEditBar";
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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cleared, setCleared] = useState(false);

  /**
   * A selection only means anything against the rows it was made on.
   *
   * Keeping it across a page would apply a correction to rows nobody can see;
   * dropping it silently would let someone believe thirty were selected when
   * twenty-five were. So it is dropped, and said.
   */
  const clearSelection = (announce: boolean) => {
    setSelected(new Set());
    setCleared(announce && selected.size > 0);
  };

  /** A new filter means a new set, so page 3 of the old one is meaningless. */
  const changeFilters = (next: Filters) => {
    setFilters(next);
    setOffset(0);
    clearSelection(true);
  };

  const changePage = (next: number) => {
    setOffset(next);
    clearSelection(true);
  };

  const toggle = (recordId: string) => {
    setCleared(false);
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(recordId)) next.add(recordId);
      return next;
    });
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
            {/* Off while a page is being replaced: keepPreviousData still shows
                the previous rows, and ticking "this page" then would select
                records that are no longer under this offset. */}
            <SelectAllOnThisPage
              records={records.data.items}
              selected={selected}
              enabled={!records.isPlaceholderData}
              onChange={setSelected}
            />
            {cleared && (
              <p className="px-4 pb-2 text-sm text-slate-500" role="status">
                Selection cleared — it only applied to the rows it was made on.
              </p>
            )}
            <RecordTable
              records={records.data.items}
              selection={{
                selected,
                onToggle: toggle,
                enabled: !records.isPlaceholderData,
              }}
            />
            <Pagination
              offset={records.data.offset}
              limit={records.data.limit}
              total={records.data.total}
              onChange={changePage}
            />
          </>
        )}
      </Panel>

      {records.data && (
        <BulkEditBar
          batchId={batchId}
          records={records.data.items}
          selected={selected}
          onDone={() => clearSelection(false)}
        />
      )}
    </div>
  );
}
