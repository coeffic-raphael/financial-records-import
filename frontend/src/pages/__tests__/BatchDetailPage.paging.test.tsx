// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Filtering while on a later page used to be the obvious way to end up staring
 * at an empty table: page 3 of "everything" is rarely a page of "needs review".
 * The offset has to go back to the start whenever the set changes underneath it.
 */

const useRecords = vi.fn();
const idle = { data: undefined, isLoading: false, isError: false };

vi.mock("../../hooks/useApi", () => ({
  useBatch: () => ({ data: { id: "b1", name: "Q3" }, isLoading: false, isError: false }),
  useSummary: () => idle,
  useJobs: () => idle,
  useUploadCsv: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useUploadPdfs: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useRecords,
}));

const { BatchDetailPage } = await import("../BatchDetailPage");

const TOTAL = 120;
const LIMIT = 25;

beforeEach(() => {
  useRecords.mockReset();
  // The mock answers with the offset it was asked for, so the controls behave
  // as they would against the real endpoint.
  useRecords.mockImplementation((_batchId: string, _filters: unknown, offset = 0) => ({
    data: { items: [], total: TOTAL, limit: LIMIT, offset },
    isLoading: false,
    isError: false,
  }));
});

afterEach(cleanup);

function lastOffset() {
  return useRecords.mock.calls.at(-1)?.[2];
}

describe("paging a batch's records", () => {
  it("starts at the beginning", () => {
    render(
      <MemoryRouter>
        <BatchDetailPage />
      </MemoryRouter>
    );
    expect(lastOffset()).toBe(0);
    expect(screen.getByText(`1–${LIMIT} of ${TOTAL}`)).toBeTruthy();
  });

  it("asks the server for the next page", () => {
    render(
      <MemoryRouter>
        <BatchDetailPage />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(lastOffset()).toBe(LIMIT);
  });

  it("returns to the first page when the filter changes", () => {
    render(
      <MemoryRouter>
        <BatchDetailPage />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(lastOffset()).toBe(LIMIT * 2);

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "NEEDS_REVIEW" } });

    expect(lastOffset()).toBe(0);
    expect(useRecords.mock.calls.at(-1)?.[1]).toEqual({ status: "NEEDS_REVIEW" });
  });

  it("reports the size of the whole filtered set, not of the page", () => {
    render(
      <MemoryRouter>
        <BatchDetailPage />
      </MemoryRouter>
    );
    expect(screen.getByText(`${TOTAL} records`)).toBeTruthy();
  });
});
