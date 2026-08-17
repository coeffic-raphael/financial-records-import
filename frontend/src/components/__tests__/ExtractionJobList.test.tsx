// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExtractionJobList } from "../ExtractionJobList";
import { makeJob } from "../../test/factories";

/**
 * Processing status for background extraction.
 *
 * A PDF upload answers 202 and finishes later, so this table is the only place
 * a user learns whether anything happened. Two things matter: that a running
 * job is visibly running, and that a failed one says why -- an extraction that
 * fails silently looks exactly like one that found nothing.
 */

afterEach(cleanup);

const show = (jobs = [makeJob()]) => render(<ExtractionJobList jobs={jobs} />);

describe("when there is nothing to report", () => {
  it("renders nothing at all", () => {
    const { container } = render(<ExtractionJobList jobs={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("a job in flight", () => {
  it("is announced while it runs", () => {
    show([makeJob({ status: "PROCESSING", record_count: null, duration_ms: null })]);
    expect(screen.getByText("1 in progress…")).toBeTruthy();
  });

  it("counts every job that has not finished, queued ones included", () => {
    show([
      makeJob({ id: "1", status: "PENDING" }),
      makeJob({ id: "2", status: "PROCESSING" }),
      makeJob({ id: "3", status: "SUCCEEDED" }),
    ]);
    expect(screen.getByText("2 in progress…")).toBeTruthy();
  });

  it("stops announcing once everything has finished", () => {
    show([makeJob({ status: "SUCCEEDED" })]);
    expect(screen.queryByText(/in progress/)).toBeNull();
  });

  it("shows dashes rather than zeros for what is not known yet", () => {
    show([
      makeJob({
        status: "PROCESSING",
        record_count: null,
        input_tokens: null,
        output_tokens: null,
        duration_ms: null,
      }),
    ]);
    expect(screen.getAllByText("—").length).toBe(3);
  });
});

describe("a job that finished", () => {
  it("reports the document, the records and the cost", () => {
    show([makeJob()]);
    expect(screen.getByText("invoice.pdf")).toBeTruthy();
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText("1005 / 2548")).toBeTruthy();
  });

  it("reports the duration in seconds rather than milliseconds", () => {
    show([makeJob({ duration_ms: 24426 })]);
    expect(screen.getByText("24.4 s")).toBeTruthy();
  });
});

describe("a job that failed", () => {
  it("says why, naming every provider that was tried", () => {
    const error =
      "Every provider failed. gemini: Gemini call failed: RateLimitError | " +
      "openai: OpenAI call failed: RateLimitError";
    show([makeJob({ status: "FAILED", error, record_count: null, duration_ms: null })]);
    expect(screen.getByText(error)).toBeTruthy();
  });

  it("does not pretend it produced records", () => {
    show([makeJob({ status: "FAILED", error: "boom", record_count: null, duration_ms: null })]);
    expect(screen.queryByText("1")).toBeNull();
  });
});
