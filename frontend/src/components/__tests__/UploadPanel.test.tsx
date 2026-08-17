// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * One drop zone for two endpoints.
 *
 * The interface decides where a file goes from its extension, rather than
 * asking someone to know in advance which box a document belongs in. That
 * routing is the whole behaviour here, and it is invisible until it is wrong:
 * a PDF sent to the CSV endpoint fails deep in the server instead of at the
 * point where the answer was obvious.
 */

const csvMutate = vi.fn();
const pdfMutate = vi.fn();
const idle = { isPending: false, isSuccess: false, isError: false, data: undefined, error: null };

vi.mock("../../hooks/useApi", () => ({
  useUploadCsv: () => ({ ...idle, mutate: csvMutate }),
  useUploadPdfs: () => ({ ...idle, mutate: pdfMutate }),
}));

const { UploadPanel } = await import("../UploadPanel");

const file = (name: string, type = "application/octet-stream") =>
  new File(["x"], name, { type });

function drop(...files: File[]) {
  render(<UploadPanel batchId="batch-1" />);
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  Object.defineProperty(input, "files", { value: files, configurable: true });
  fireEvent.change(input);
}

beforeEach(() => {
  csvMutate.mockReset();
  pdfMutate.mockReset();
});
afterEach(cleanup);

describe("routing a file to the endpoint it needs", () => {
  it("sends a CSV to the CSV import", () => {
    drop(file("transactions.csv", "text/csv"));
    expect(csvMutate).toHaveBeenCalledTimes(1);
    expect(pdfMutate).not.toHaveBeenCalled();
  });

  it("sends PDFs to extraction, in one call", () => {
    drop(file("a.pdf", "application/pdf"), file("b.pdf", "application/pdf"));
    expect(pdfMutate).toHaveBeenCalledTimes(1);
    expect(pdfMutate.mock.calls[0][0]).toHaveLength(2);
    expect(csvMutate).not.toHaveBeenCalled();
  });

  it("splits a mixed drop rather than refusing it", () => {
    drop(file("rows.csv", "text/csv"), file("invoice.pdf", "application/pdf"));
    expect(csvMutate).toHaveBeenCalledTimes(1);
    expect(pdfMutate).toHaveBeenCalledTimes(1);
  });

  it("recognises the kind whatever the case of the extension", () => {
    drop(file("ROWS.CSV"), file("INVOICE.PDF"));
    expect(csvMutate).toHaveBeenCalledTimes(1);
    expect(pdfMutate).toHaveBeenCalledTimes(1);
  });

  it("uploads one CSV per file rather than batching them", () => {
    drop(file("january.csv"), file("february.csv"));
    expect(csvMutate).toHaveBeenCalledTimes(2);
  });
});

describe("a file that belongs to neither", () => {
  it("is named back rather than silently dropped", () => {
    drop(file("photo.png", "image/png"));
    expect(screen.getByText(/Ignored: photo\.png/)).toBeTruthy();
  });

  it("does not stop the files that were usable", () => {
    drop(file("rows.csv"), file("photo.png"));
    expect(csvMutate).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Ignored: photo\.png/)).toBeTruthy();
  });

  it("lists every one of them", () => {
    drop(file("a.png"), file("b.docx"));
    expect(screen.getByText(/a\.png, b\.docx/)).toBeTruthy();
  });
});

describe("what the zone tells the user", () => {
  it("states that a bad row is flagged, never dropped", () => {
    render(<UploadPanel batchId="batch-1" />);
    expect(screen.getByText(/invalid ones are flagged, never dropped/)).toBeTruthy();
  });

  it("says PDFs are read in the background", () => {
    render(<UploadPanel batchId="batch-1" />);
    expect(screen.getByText(/read by a model in the background/)).toBeTruthy();
  });
});
