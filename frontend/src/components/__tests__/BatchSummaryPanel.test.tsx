// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BatchSummaryPanel } from "../BatchSummaryPanel";
import { makeSummary } from "../../test/factories";

/**
 * The batch summary.
 *
 * The one rule worth a test here is that currencies are never added together.
 * A single total across EUR and CHF would be a number that looks authoritative
 * and means nothing, and it is the kind of mistake a summary invites.
 */

afterEach(cleanup);

const show = (overrides = {}) => render(<BatchSummaryPanel summary={makeSummary(overrides)} />);

/** The three columns repeat numbers, so a bare getByText is ambiguous. */
function column(label: string) {
  return screen.getByText(label).parentElement as HTMLElement;
}

describe("how much is in the batch", () => {
  it("gives the total", () => {
    show();
    expect(within(column("Records")).getByText("30")).toBeTruthy();
  });

  it("breaks it down by status, which is what says how much work is left", () => {
    show();
    const records = within(column("Records"));
    for (const count of ["18", "11", "1"]) {
      expect(records.getByText(count)).toBeTruthy();
    }
  });
});

describe("where it came from", () => {
  it("names each source document with its share", () => {
    show();
    expect(screen.getByText("transactions_import.csv")).toBeTruthy();
  });

  it("shows a dash rather than an empty column for a batch with no upload yet", () => {
    show({ documents: [], totals_by_currency: [], total_records: 0, by_status: {} });
    expect(screen.getAllByText("—").length).toBe(2);
  });
});

describe("money", () => {
  it("keeps each currency on its own line", () => {
    show();
    expect(screen.getByText("EUR")).toBeTruthy();
    expect(screen.getByText("CHF")).toBeTruthy();
    expect(screen.getByText("25449.42")).toBeTruthy();
    expect(screen.getByText("100795.78")).toBeTruthy();
  });

  it("says out loud that they are not added together", () => {
    show();
    expect(screen.getByText("Never summed across currencies.")).toBeTruthy();
  });

  it("prints the amount exactly as the server sent it", () => {
    /* The server is the only arithmetic authority; amounts arrive as strings
       so a float never rounds one before it is displayed. */
    show({ totals_by_currency: [{ currency: "EUR", net_amount: "0.10" }] });
    expect(screen.getByText("0.10")).toBeTruthy();
  });

  it("survives a currency whose total the server could not give", () => {
    const { container } = render(
      <BatchSummaryPanel
        summary={makeSummary({ totals_by_currency: [{ currency: "USD", net_amount: null }] })}
      />
    );
    expect(within(container).getByText("USD")).toBeTruthy();
  });
});
