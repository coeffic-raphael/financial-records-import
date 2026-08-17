// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeSummary } from "../../test/factories";
import type { Batch } from "../../lib/types";

/**
 * Deleting a batch is the one irreversible action in the interface, and it
 * reaches further than it looks: records, extraction jobs and stored documents
 * all go with it. The control is built to say so before it is used.
 */

const remove = { mutate: vi.fn(), isPending: false };
const summary = { data: undefined as ReturnType<typeof makeSummary> | undefined, isLoading: false };
let enabledWith: boolean | undefined;

vi.mock("../../hooks/useApi", () => ({
  useDeleteBatch: () => remove,
  useSummary: (_id: string, enabled?: boolean) => {
    enabledWith = enabled;
    return summary;
  },
}));

const { DeleteBatchButton } = await import("../DeleteBatchButton");

const batch: Batch = { id: "b1", name: "July 2026", created_at: "2026-07-01T00:00:00Z" };

beforeEach(() => {
  remove.mutate.mockReset();
  remove.isPending = false;
  summary.data = undefined;
  summary.isLoading = false;
  enabledWith = undefined;
});
afterEach(cleanup);

const show = () => render(<DeleteBatchButton batch={batch} />);

describe("before anything is clicked", () => {
  it("offers a delete control that names its batch", () => {
    show();
    expect(screen.getByRole("button", { name: "Delete batch July 2026" })).toBeTruthy();
  });

  it("does not fetch the counts", () => {
    /* One request per row on every visit, to serve a rare click. */
    show();
    expect(enabledWith).toBe(false);
  });

  it("deletes nothing on the first click", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Delete batch July 2026" }));
    expect(remove.mutate).not.toHaveBeenCalled();
  });
});

describe("once confirmation is asked for", () => {
  function confirm() {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Delete batch July 2026" }));
  }

  it("fetches the counts only then", () => {
    summary.data = makeSummary();
    confirm();
    expect(enabledWith).toBe(true);
  });

  it("says how much is about to go", () => {
    summary.data = makeSummary({ total_records: 30, by_status: { VALID: 30 } });
    confirm();
    expect(screen.getByText(/and its 30 records\?/)).toBeTruthy();
  });

  it("warns when approved records are among them", () => {
    /* Not refused -- nothing un-approves a record, so a guard would leave the
       batch undeletable. Said out loud instead. */
    summary.data = makeSummary({ total_records: 30, by_status: { VALID: 29, VALIDATED: 1 } });
    confirm();
    expect(screen.getByText(/1 is approved/)).toBeTruthy();
  });

  it("stays silent about approvals when there are none", () => {
    summary.data = makeSummary({ total_records: 30, by_status: { VALID: 30 } });
    confirm();
    expect(screen.queryByText(/approved/)).toBeNull();
  });

  it("waits for the counts before allowing the click", () => {
    summary.isLoading = true;
    confirm();
    const buttons = screen.getAllByRole("button", { name: "Delete" });
    expect((buttons[0] as HTMLButtonElement).disabled).toBe(true);
  });

  it("deletes when confirmed", () => {
    summary.data = makeSummary();
    confirm();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(remove.mutate).toHaveBeenCalledWith("b1");
  });

  it("can be backed out of", () => {
    summary.data = makeSummary();
    confirm();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(remove.mutate).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete batch July 2026" })).toBeTruthy();
  });
});
