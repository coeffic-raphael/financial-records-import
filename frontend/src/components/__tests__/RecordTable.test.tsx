// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecordTable } from "../RecordTable";
import { makeRecord } from "../../test/factories";

/**
 * The record list and its field-level errors -- two of the assignment's
 * frontend requirements, and the screen a reviewer spends their time on.
 *
 * The issue count used to say how many problems a row had and nothing else,
 * which is a number you cannot act on. These pin the part that makes it
 * actionable.
 */

const navigate = vi.fn();
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
  useNavigate: () => navigate,
}));

afterEach(() => {
  cleanup();
  navigate.mockReset();
});

function show(records = [makeRecord()]) {
  render(
    <MemoryRouter>
      <RecordTable records={records} />
    </MemoryRouter>
  );
}

describe("the list itself", () => {
  it("says so plainly when a filter matches nothing", () => {
    show([]);
    expect(screen.getByText("No record matches these filters")).toBeTruthy();
  });

  it("shows what identifies a row", () => {
    show([makeRecord()]);
    for (const value of ["TX-2026-0001", "2026-07-01", "ACME Advisory", "1170.00", "EUR"]) {
      expect(screen.getByText(value)).toBeTruthy();
    }
  });

  it("marks a record that has no reference rather than leaving a blank", () => {
    show([makeRecord({ reference: null })]);
    expect(screen.getByText("no reference")).toBeTruthy();
  });

  it("shows a dash where a value is missing", () => {
    show([makeRecord({ counterparty_name: null, transaction_date: null })]);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("distinguishes an imported row from an extracted one", () => {
    show([makeRecord({ source_type: "PDF" })]);
    expect(screen.getByText("PDF")).toBeTruthy();
  });
});

describe("opening a record", () => {
  it("the whole row is the target, not just the reference", () => {
    show([makeRecord()]);
    fireEvent.click(screen.getByRole("link", { name: "Open record TX-2026-0001" }));
    expect(navigate).toHaveBeenCalledWith("/records/rec-1");
  });

  it("the row is reachable from the keyboard", () => {
    show([makeRecord()]);
    fireEvent.keyDown(screen.getByRole("link", { name: "Open record TX-2026-0001" }), {
      key: "Enter",
    });
    expect(navigate).toHaveBeenCalledWith("/records/rec-1");
  });
});

describe("field-level errors", () => {
  const withIssues = () =>
    makeRecord({
      status: "NEEDS_REVIEW",
      validation_errors: [
        { field: "transaction_date", code: "INVALID_DATE", message: "Unreadable date: '2026-13-16'" },
        { field: "country", code: "INVALID_COUNTRY_CODE", message: "Not a two-letter code." },
      ],
    });

  it("counts the issues before they are opened", () => {
    show([withIssues()]);
    expect(screen.getByRole("button", { name: /2 issues/ })).toBeTruthy();
  });

  it("uses the singular for one issue", () => {
    show([makeRecord({ validation_errors: [{ field: "country", code: "X", message: "y" }] })]);
    expect(screen.getByRole("button", { name: /^1 issue/ })).toBeTruthy();
  });

  it("names the field, the code and the reason once expanded", () => {
    show([withIssues()]);
    fireEvent.click(screen.getByRole("button", { name: /2 issues/ }));

    expect(screen.getByText("transaction date")).toBeTruthy();
    expect(screen.getByText("INVALID_DATE")).toBeTruthy();
    expect(screen.getByText("Unreadable date: '2026-13-16'")).toBeTruthy();
    expect(screen.getByText("Not a two-letter code.")).toBeTruthy();
  });

  it("peeking does not navigate away", () => {
    show([withIssues()]);
    fireEvent.click(screen.getByRole("button", { name: /2 issues/ }));
    expect(navigate).not.toHaveBeenCalled();
  });

  it("offers the way to fix them", () => {
    show([withIssues()]);
    fireEvent.click(screen.getByRole("button", { name: /2 issues/ }));
    fireEvent.click(screen.getByRole("button", { name: /Open this record to fix it/ }));
    expect(navigate).toHaveBeenCalledWith("/records/rec-1");
  });

  it("collapses again", () => {
    show([withIssues()]);
    const toggle = screen.getByRole("button", { name: /2 issues/ });
    fireEvent.click(toggle);
    expect(screen.queryByText("INVALID_DATE")).toBeTruthy();
    fireEvent.click(toggle);
    expect(screen.queryByText("INVALID_DATE")).toBeNull();
  });

  it("a clean record offers nothing to expand", () => {
    show([makeRecord()]);
    expect(screen.queryByRole("button", { name: /issue/ })).toBeNull();
  });
});


describe("selecting rows", () => {
  const onToggle = vi.fn();

  function withSelection(enabled = true) {
    onToggle.mockReset();
    render(
      <MemoryRouter>
        <RecordTable
          records={[makeRecord()]}
          selection={{ selected: new Set(), onToggle, enabled }}
        />
      </MemoryRouter>
    );
    return screen.getByRole("checkbox");
  }

  it("ticks the box without opening the record", () => {
    const box = withSelection();
    fireEvent.click(box);

    expect(onToggle).toHaveBeenCalledWith("rec-1");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("does not open the record from the keyboard either", () => {
    /* The row opens on Enter AND on Space -- and Space is the key that ticks a
       checkbox. Stopping the click alone left the keyboard path navigating. */
    const box = withSelection();
    fireEvent.keyDown(box, { key: " " });

    expect(navigate).not.toHaveBeenCalled();
  });

  it("is disabled while the page is being replaced", () => {
    expect((withSelection(false) as HTMLInputElement).disabled).toBe(true);
  });

  it("offers no checkbox when the table is not selectable", () => {
    render(
      <MemoryRouter>
        <RecordTable records={[makeRecord()]} />
      </MemoryRouter>
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
