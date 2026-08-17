// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeRecord } from "../../test/factories";

/**
 * One correction across several records.
 *
 * The dangerous part is not the request: it is what the person believes they
 * selected, and what the correction quietly undoes.
 */

const correct = {
  mutate: vi.fn(),
  isPending: false,
  isSuccess: false,
  isError: false,
  data: undefined as { updated: number; by_status: Record<string, number> } | undefined,
  error: null as unknown,
};

vi.mock("../../hooks/useApi", () => ({ useCorrectRecords: () => correct }));

const { BulkEditBar, SelectAllOnThisPage } = await import("../BulkEditBar");

const records = [
  makeRecord({ id: "r1", reference: "A-1" }),
  makeRecord({ id: "r2", reference: "A-2" }),
  makeRecord({ id: "r3", reference: "A-3", status: "VALIDATED" }),
];

beforeEach(() => {
  correct.mutate.mockReset();
  correct.isPending = false;
  correct.isSuccess = false;
  correct.isError = false;
  correct.data = undefined;
});
afterEach(cleanup);

function show(ids: string[], onDone = vi.fn()) {
  render(
    <BulkEditBar
      batchId="b1"
      records={records}
      selected={new Set(ids)}
      onDone={onDone}
    />
  );
  return onDone;
}

describe("with nothing selected", () => {
  it("stays out of the way", () => {
    const { container } = render(
      <BulkEditBar batchId="b1" records={records} selected={new Set()} onDone={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });
});

describe("the correction it sends", () => {
  it("names the selected records once", () => {
    show(["r1", "r2"]);
    fireEvent.change(screen.getByLabelText("New value"), { target: { value: "Nordbank" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(correct.mutate).toHaveBeenCalledTimes(1);
    expect(correct.mutate.mock.calls[0][0]).toEqual({
      record_ids: ["r1", "r2"],
      changes: { counterparty_name: "Nordbank" },
    });
  });

  it("does not offer reference", () => {
    /* One reference across several records creates duplicates by construction.
       The server refuses it too -- a hidden menu entry is a suggestion. */
    show(["r1"]);
    const options = [...screen.getByLabelText("Field to set").querySelectorAll("option")];
    expect(options.map((option) => option.value)).not.toContain("reference");
  });

  it("counts what is selected", () => {
    show(["r1", "r2"]);
    expect(screen.getByText("2 selected")).toBeTruthy();
  });
});

describe("what it warns about", () => {
  it("says when approved records are in the selection", () => {
    /* Correcting drops a record out of VALIDATED. Across forty rows that undoes
       approvals nobody meant to touch, so it is said before, not after. */
    show(["r1", "r3"]);
    expect(screen.getByText(/1 of them is approved/)).toBeTruthy();
  });

  it("stays quiet when none are approved", () => {
    show(["r1", "r2"]);
    expect(screen.queryByText(/approved/)).toBeNull();
  });
});

describe("afterwards", () => {
  it("reports what the click unblocked", () => {
    correct.isSuccess = true;
    correct.data = { updated: 3, by_status: { VALID: 2, NEEDS_REVIEW: 1 } };
    show(["r1", "r2", "r3"]);

    expect(screen.getByRole("status").textContent).toMatch(/3 records updated/);
    expect(screen.getByRole("status").textContent).toMatch(/2 valid/);
  });

  it("clears the selection only on success", () => {
    const onDone = show(["r1"]);
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    // The mutation carries onSuccess; a failure never reaches it, so twenty
    // ticked boxes survive a retry.
    expect(correct.mutate.mock.calls[0][1]).toHaveProperty("onSuccess");
    expect(onDone).not.toHaveBeenCalled();
  });

  it("shows a failure without losing the selection", () => {
    correct.isError = true;
    correct.error = new Error("nope");
    const onDone = show(["r1"]);

    expect(screen.getByText(/Could not apply/)).toBeTruthy();
    expect(onDone).not.toHaveBeenCalled();
  });
});

describe("the header tick", () => {
  const onChange = vi.fn();
  const showHeader = (enabled = true, rows = records) =>
    render(
      <SelectAllOnThisPage
        records={rows}
        selected={new Set()}
        enabled={enabled}
        onChange={onChange}
      />
    );

  beforeEach(() => onChange.mockReset());

  it("counts the rows actually on screen", () => {
    /* "the 25 on this page" on a last page of three is the sentence that makes
       someone lose work. */
    showHeader(true, records.slice(0, 3));
    expect(screen.getByText(/Select the 3 on this page/)).toBeTruthy();
  });

  it("selects them all", () => {
    showHeader();
    fireEvent.click(screen.getByRole("checkbox"));
    expect([...onChange.mock.calls[0][0]]).toEqual(["r1", "r2", "r3"]);
  });

  it("is disabled while the page is being replaced", () => {
    /* keepPreviousData still shows the previous rows; ticking then would select
       records no longer under this offset. */
    showHeader(false);
    expect((screen.getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
  });
});
