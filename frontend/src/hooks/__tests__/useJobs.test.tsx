// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useJobs } from "../useApi";
import * as apiClient from "../../lib/apiClient";
import { useAuthStore } from "../../stores/authStore";
import type { ExtractionJob } from "../../lib/types";

/**
 * Polling knew when extraction ended. Nothing told the records or the summary,
 * so the table kept showing the state from before the upload until the user
 * navigated away and back.
 *
 * A manual check missed this because navigating fresh made the data correct for
 * the wrong reason. That is what this test is here to prevent.
 */

const BATCH_ID = "batch-1";

function job(status: ExtractionJob["status"]): ExtractionJob {
  return {
    id: "job-1",
    batch_id: BATCH_ID,
    document_name: "invoice.pdf",
    status,
    provider: null,
    model: null,
    input_tokens: null,
    output_tokens: null,
    duration_ms: null,
    record_count: null,
    error: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  };
}

let client: QueryClient;
let invalidateSpy: ReturnType<typeof vi.spyOn>;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  invalidateSpy = vi.spyOn(client, "invalidateQueries");
  useAuthStore.setState({
    user: { id: "u1", email: "a@example.com", name: "Alice Martin", tenant_id: "t1" },
    accessToken: "token",
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ user: null, accessToken: null });
});

function invalidatedKeys(): string[] {
  return invalidateSpy.mock.calls.map((call: unknown[]) =>
    JSON.stringify((call[0] as { queryKey: unknown[] }).queryKey),
  );
}

describe("when an extraction finishes", () => {
  it("invalidates the records and the summary", async () => {
    const get = vi
      .spyOn(apiClient.api, "get")
      .mockResolvedValueOnce([job("PROCESSING")])
      .mockResolvedValue([job("SUCCEEDED")]);

    const { result, rerender } = renderHook(() => useJobs(BATCH_ID), { wrapper });

    await waitFor(() => expect(result.current.data?.[0].status).toBe("PROCESSING"));
    expect(invalidatedKeys().some((key) => key.includes("records"))).toBe(false);

    await client.refetchQueries();
    rerender();

    await waitFor(() => {
      const keys = invalidatedKeys();
      expect(keys.some((key) => key.includes("records"))).toBe(true);
      expect(keys.some((key) => key.includes("summary"))).toBe(true);
    });
    expect(get).toHaveBeenCalled();
  });

  it("does not invalidate while nothing has ever run", async () => {
    vi.spyOn(apiClient.api, "get").mockResolvedValue([]);

    const { result } = renderHook(() => useJobs(BATCH_ID), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidatedKeys().some((key) => key.includes("records"))).toBe(false);
  });
});
