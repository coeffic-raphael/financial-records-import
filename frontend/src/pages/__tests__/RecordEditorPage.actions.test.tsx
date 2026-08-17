// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeRecord } from "../../test/factories";
import type { FinancialRecord } from "../../lib/types";

/**
 * The three actions on one record: correct, revalidate, approve.
 *
 * The button states are the assignment's ordering rule made visible -- a
 * record with issues cannot be approved. The server enforces it and answers
 * 409; the interface should not offer the click in the first place.
 *
 * These assert the affordance only. That the rule holds against a caller who
 * ignores the interface is a server concern, covered in
 * backend/tests/api/test_status_transitions.py.
 */

const correct = { mutate: vi.fn(), isPending: false, error: null };
const revalidate = {
  mutate: vi.fn(),
  isPending: false,
  isSuccess: false,
  data: undefined as FinancialRecord | undefined,
  error: null,
};
const validate = { mutate: vi.fn(), isPending: false, error: null };

let current: FinancialRecord;

vi.mock("../../hooks/useApi", () => ({
  useRecord: () => ({ data: current, isLoading: false, isError: false }),
  useRecordActions: () => ({ correct, revalidate, validate }),
}));

vi.mock("../../components/SourceDocumentPanel", () => ({
  // The source document is a separate concern with its own fetch.
  SourceDocumentPanel: () => null,
}));

const { RecordEditorPage } = await import("../RecordEditorPage");

function show(overrides: Partial<FinancialRecord> = {}) {
  current = makeRecord(overrides);
  render(
    <MemoryRouter>
      <RecordEditorPage />
    </MemoryRouter>
  );
}

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

beforeEach(() => {
  correct.mutate.mockReset();
  revalidate.mutate.mockReset();
  revalidate.isSuccess = false;
  revalidate.data = undefined;
  validate.mutate.mockReset();
});
afterEach(cleanup);

describe("approving a record", () => {
  it("is offered when the record is valid", () => {
    show({ status: "VALID" });
    expect(button("Validate").disabled).toBe(false);
  });

  it("is refused while the record still has issues", () => {
    show({
      status: "NEEDS_REVIEW",
      validation_errors: [{ field: "country", code: "INVALID_COUNTRY_CODE", message: "no" }],
    });
    expect(button("Validate").disabled).toBe(true);
  });

  it("explains why it is refused rather than being inertly grey", () => {
    show({ status: "NEEDS_REVIEW" });
    expect(button("Validate").title).toBe("Only a record with no issues can be validated");
  });

  it("is not offered again on a record already approved", () => {
    show({ status: "VALIDATED" });
    expect(button("Validate").disabled).toBe(true);
  });

  it("asks the server when clicked", () => {
    show({ status: "VALID" });
    fireEvent.click(button("Validate"));
    expect(validate.mutate).toHaveBeenCalled();
  });
});

describe("correcting a record", () => {
  it("saving is offered only once something has changed", () => {
    // The fixture already holds FR, so the new value has to be a different
    // one -- setting a field to what it already says is not a change.
    show({ status: "NEEDS_REVIEW", country: "FRA" });
    expect(button("Save and revalidate").disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("country"), { target: { value: "FR" } });
    expect(button("Save and revalidate").disabled).toBe(false);
  });

  it("sends only the fields that were touched", () => {
    show({ status: "NEEDS_REVIEW", country: "FRA" });
    fireEvent.change(screen.getByLabelText("country"), { target: { value: "FR" } });
    fireEvent.click(button("Save and revalidate"));

    expect(correct.mutate).toHaveBeenCalled();
    expect(correct.mutate.mock.calls[0][0]).toEqual({ country: "FR" });
  });

  it("a correction can be abandoned", () => {
    show({ status: "NEEDS_REVIEW", country: "FRA" });
    fireEvent.change(screen.getByLabelText("country"), { target: { value: "XX" } });
    fireEvent.click(screen.getByRole("button", { name: /Discard|Cancel|Reset/i }));
    expect(button("Save and revalidate").disabled).toBe(true);
  });
});

describe("revalidating without changing anything", () => {
  it("is always available", () => {
    show({ status: "NEEDS_REVIEW" });
    expect(button("Re-run validation").disabled).toBe(false);
  });

  it("asks the server when clicked", () => {
    show({ status: "NEEDS_REVIEW" });
    fireEvent.click(button("Re-run validation"));
    expect(revalidate.mutate).toHaveBeenCalled();
  });
});

describe("what the reviewer is told", () => {
  it("counts the issues to resolve", () => {
    show({
      status: "NEEDS_REVIEW",
      validation_errors: [
        { field: "country", code: "INVALID_COUNTRY_CODE", message: "Not a two-letter code." },
        { field: "currency", code: "UNSUPPORTED_CURRENCY", message: "Unsupported." },
      ],
    });
    expect(screen.getByText(/2 issues to resolve/)).toBeTruthy();
  });

  it("shows each message against its own field", () => {
    show({
      status: "NEEDS_REVIEW",
      validation_errors: [
        { field: "country", code: "INVALID_COUNTRY_CODE", message: "Not a two-letter code." },
      ],
    });
    expect(screen.getByText("Not a two-letter code.")).toBeTruthy();
    expect(screen.getByText("INVALID_COUNTRY_CODE")).toBeTruthy();
  });

  it("shows what the document said when it differs from what is stored", () => {
    show({
      status: "NEEDS_REVIEW",
      transaction_date: null,
      raw_payload: { transaction_date: "2026-13-16" },
    });
    expect(screen.getByText("2026-13-16")).toBeTruthy();
  });
});


describe("what re-running validation reports", () => {
  it("says nothing changed rather than staying silent", () => {
    /* The bug this covers: the request succeeded, the verdict was identical,
       and the screen did not move -- which reads as a dead button. */
    revalidate.isSuccess = true;
    revalidate.data = makeRecord({
      status: "NEEDS_REVIEW",
      validation_errors: [{ field: "country", code: "INVALID_COUNTRY_CODE", message: "no" }],
    });
    show({ status: "NEEDS_REVIEW" });

    expect(screen.getByText(/Re-checked the saved record/)).toBeTruthy();
    expect(screen.getByText(/1 issue still to resolve/)).toBeTruthy();
  });

  it("reports a record that came back clean", () => {
    revalidate.isSuccess = true;
    revalidate.data = makeRecord({ status: "VALID", validation_errors: [] });
    show({ status: "VALID" });

    expect(screen.getByText(/no issues remain/)).toBeTruthy();
  });

  it("says nothing before the button is used", () => {
    show({ status: "NEEDS_REVIEW" });
    expect(screen.queryByText(/Re-checked the saved record/)).toBeNull();
  });

  it("shows progress while the request is in flight", () => {
    revalidate.isPending = true;
    show({ status: "NEEDS_REVIEW" });
    expect(screen.getByRole("button", { name: "Re-checking…" })).toBeTruthy();
    revalidate.isPending = false;
  });
});
