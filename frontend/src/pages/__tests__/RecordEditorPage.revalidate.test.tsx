// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeRecord } from "../../test/factories";

/**
 * The revalidate button, wired to the REAL hook.
 *
 * The other file mocks `useRecordActions`, which proves the screen reacts to a
 * successful mutation but not that clicking produces one. That gap is exactly
 * where "the button does nothing" could hide, so this exercises the real
 * mutation over a faked HTTP layer.
 */

const record = makeRecord({
  status: "NEEDS_REVIEW",
  validation_errors: [
    { field: "transaction_date", code: "INVALID_DATE", message: "Unreadable date." },
  ],
});

const post = vi.fn();
const get = vi.fn();

vi.mock("../../lib/apiClient", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    patch: vi.fn(),
    upload: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

vi.mock("../../components/SourceDocumentPanel", () => ({
  SourceDocumentPanel: () => null,
}));

vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")),
  useParams: () => ({ recordId: record.id }),
}));

const { RecordEditorPage } = await import("../RecordEditorPage");

let client: QueryClient;

beforeEach(() => {
  post.mockReset();
  get.mockReset().mockResolvedValue(record);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
});
afterEach(cleanup);

function show() {
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RecordEditorPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("with unsaved edits on screen", () => {
  it("refuses to re-check, because it would read the stored value", async () => {
    /* The bug this covers: the user corrects a bad date, clicks Re-run
       validation, and sees the SAME error -- because revalidation replays from
       raw_payload and the draft was never sent. Correct at the server, and
       indistinguishable from a broken button at the screen. */
    post.mockResolvedValue(record);
    show();
    const button = await screen.findByRole("button", { name: "Re-run validation" });
    expect((button as HTMLButtonElement).disabled).toBe(false);

    fireEvent.change(screen.getByLabelText("value date"), { target: { value: "2026-07-17" } });

    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(button.title).toMatch(/Save your changes first/);
  });

  it("allows it again once the draft is discarded", async () => {
    show();
    const button = await screen.findByRole("button", { name: "Re-run validation" });
    fireEvent.change(screen.getByLabelText("value date"), { target: { value: "2026-07-17" } });
    fireEvent.click(screen.getByRole("button", { name: /Discard/i }));

    expect((button as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("clicking Re-run validation", () => {
  it("calls the endpoint", async () => {
    post.mockResolvedValue(record);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Re-run validation" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/api/records/${record.id}/revalidate`)
    );
  });

  it("reports the outcome once the request resolves", async () => {
    post.mockResolvedValue(record);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Re-run validation" }));

    expect(await screen.findByText(/Re-checked the saved record/)).toBeTruthy();
    expect(screen.getByText(/1 issue still to resolve/)).toBeTruthy();
  });

  it("surfaces a failure instead of staying silent", async () => {
    post.mockRejectedValue(new Error("boom"));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Re-run validation" }));

    expect(await screen.findByText(/Action failed|boom/)).toBeTruthy();
  });

  it("puts the outcome next to the button that produced it", async () => {
    /* The form is long: a source document panel and fifteen fields. A
       confirmation rendered above all that lands off-screen, and a button whose
       result you cannot see is indistinguishable from a dead one. jsdom has no
       viewport, so position is asserted structurally instead. */
    post.mockResolvedValue(record);
    show();
    const button = await screen.findByRole("button", { name: "Re-run validation" });
    fireEvent.click(button);

    const outcome = await screen.findByRole("status");
    const actions = button.parentElement as HTMLElement;

    expect(actions.contains(outcome)).toBe(true);
  });
});
