import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "../lib/apiClient";
import { scopedKey } from "../lib/queryClient";
import type {
  Batch,
  BatchSummary,
  ExtractionJob,
  FinancialRecord,
  ImportResult,
  Page,
} from "../lib/types";
import { useAuthStore } from "../stores/authStore";

/**
 * Every server read and write lives here.
 *
 * The central flow of the application is correct -> revalidate -> refresh, which
 * is exactly mutation -> invalidation: the table and the summary bring
 * themselves up to date, with no derived state written by hand.
 */

function useUserId(): string | undefined {
  return useAuthStore((state) => state.user?.id);
}

export function useBatches() {
  const userId = useUserId();
  return useQuery({
    queryKey: scopedKey(userId, "batches"),
    queryFn: () => api.get<Batch[]>("/api/batches"),
  });
}

export function useBatch(batchId: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: scopedKey(userId, "batch", batchId),
    queryFn: () => api.get<Batch>(`/api/batches/${batchId}`),
  });
}

export const PAGE_SIZE = 25;

/**
 * One page of a batch's records.
 *
 * `placeholderData` keeps the previous page on screen while the next one
 * loads. Without it every page change empties the table for a moment, which
 * reads as "there is nothing here" rather than "this is loading".
 */
export function useRecords(
  batchId: string,
  filters: { status?: string; source_type?: string },
  offset = 0,
) {
  const userId = useUserId();
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  for (const [name, value] of Object.entries(filters)) {
    if (value) params.set(name, value);
  }
  return useQuery({
    // The pagination lives inside the same trailing object as the filters, so
    // invalidating the `records` prefix still reaches every page.
    queryKey: scopedKey(userId, "batch", batchId, "records", { ...filters, offset }),
    queryFn: () => api.get<Page<FinancialRecord>>(`/api/batches/${batchId}/records?${params}`),
    placeholderData: keepPreviousData,
  });
}

export function useRecord(recordId: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: scopedKey(userId, "record", recordId),
    queryFn: () => api.get<FinancialRecord>(`/api/records/${recordId}`),
  });
}

export function useSummary(batchId: string, enabled = true) {
  const userId = useUserId();
  return useQuery({
    queryKey: scopedKey(userId, "batch", batchId, "summary"),
    queryFn: () => api.get<BatchSummary>(`/api/batches/${batchId}/summary`),
    // Off until asked for: the delete confirmation needs one batch's counts,
    // and fetching them for every row of the list to serve a rare click would
    // be a request per batch on every visit.
    enabled,
  });
}

export function useDeleteBatch() {
  const client = useQueryClient();
  const userId = useUserId();
  return useMutation({
    mutationFn: (batchId: string) => api.del<void>(`/api/batches/${batchId}`),
    onSuccess: () => client.invalidateQueries({ queryKey: scopedKey(userId, "batches") }),
  });
}

function isRunning(jobs: ExtractionJob[] | undefined): boolean {
  return Boolean(jobs?.some((job) => job.status === "PENDING" || job.status === "PROCESSING"));
}

export function useJobs(batchId: string) {
  const userId = useUserId();
  const client = useQueryClient();
  const wasRunning = useRef(false);

  const query = useQuery({
    queryKey: scopedKey(userId, "batch", batchId, "jobs"),
    queryFn: () => api.get<ExtractionJob[]>(`/api/batches/${batchId}/jobs`),
    // Polls only while something is actually running. A permanent interval is
    // waste nobody notices until the bill arrives.
    refetchInterval: (q) => (isRunning(q.state.data as ExtractionJob[] | undefined) ? 1500 : false),
  });

  // Polling the jobs told us when extraction ended; nothing told the records or
  // the summary. Without this the table keeps showing the state from before the
  // upload until the user navigates away and back -- which is exactly what
  // happened to hide the bug during a manual check.
  useEffect(() => {
    const running = isRunning(query.data);
    if (wasRunning.current && !running) {
      void client.invalidateQueries({ queryKey: scopedKey(userId, "batch", batchId, "records") });
      void client.invalidateQueries({ queryKey: scopedKey(userId, "batch", batchId, "summary") });
    }
    wasRunning.current = running;
  }, [query.data, client, userId, batchId]);

  return query;
}

/** Everything a change to one record can affect. */
function useInvalidateBatch(batchId: string) {
  const client = useQueryClient();
  const userId = useUserId();
  return () => {
    void client.invalidateQueries({ queryKey: scopedKey(userId, "batch", batchId) });
    void client.invalidateQueries({ queryKey: scopedKey(userId, "batches") });
  };
}

export function useCreateBatch() {
  const client = useQueryClient();
  const userId = useUserId();
  return useMutation({
    mutationFn: (name: string) => api.post<Batch>("/api/batches", { name }),
    onSuccess: () => client.invalidateQueries({ queryKey: scopedKey(userId, "batches") }),
  });
}

export function useUploadCsv(batchId: string) {
  const invalidate = useInvalidateBatch(batchId);
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<ImportResult>(`/api/batches/${batchId}/uploads/csv`, form);
    },
    onSuccess: invalidate,
  });
}

export function useUploadPdfs(batchId: string) {
  const invalidate = useInvalidateBatch(batchId);
  return useMutation({
    mutationFn: (files: File[]) => {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      return api.upload<{ jobs: ExtractionJob[] }>(`/api/batches/${batchId}/uploads/pdf`, form);
    },
    onSuccess: invalidate,
  });
}

export function useRecordActions(record: FinancialRecord) {
  const client = useQueryClient();
  const userId = useUserId();

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: scopedKey(userId, "record", record.id) });
    await client.invalidateQueries({ queryKey: scopedKey(userId, "batch", record.batch_id) });
  };

  return {
    correct: useMutation({
      mutationFn: (changes: Record<string, string>) =>
        api.patch<FinancialRecord>(`/api/records/${record.id}`, changes),
      onSuccess: refresh,
    }),
    revalidate: useMutation({
      mutationFn: () => api.post<FinancialRecord>(`/api/records/${record.id}/revalidate`),
      onSuccess: refresh,
    }),
    validate: useMutation({
      mutationFn: () => api.post<FinancialRecord>(`/api/records/${record.id}/validate`),
      onSuccess: refresh,
    }),
  };
}
