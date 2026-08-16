// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Pagination } from "../Pagination";

/**
 * The controls report a position inside a set the user cannot see all of, so
 * the numbers are the feature. A range that lies is worse than no range: it
 * tells a reviewer they have finished when they have not.
 */

// No global setup file enables it, so unmounting is explicit: without this
// each case would query a DOM still holding the previous render's buttons.
afterEach(cleanup);

function renderAt(offset: number, total: number, limit = 25) {
  const onChange = vi.fn();
  render(
    <Pagination offset={offset} limit={limit} total={total} onChange={onChange} />
  );
  return onChange;
}

describe("when everything already fits", () => {
  it("renders nothing at all", () => {
    const { container } = render(
      <Pagination offset={0} limit={25} total={25} onChange={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });
});

describe("the range it reports", () => {
  it("counts from one, not from zero", () => {
    renderAt(0, 120);
    expect(screen.getByText("1–25 of 120")).toBeTruthy();
  });

  it("follows the offset", () => {
    renderAt(50, 120);
    expect(screen.getByText("51–75 of 120")).toBeTruthy();
  });

  it("stops at the total on a partial last page", () => {
    renderAt(100, 120);
    expect(screen.getByText("101–120 of 120")).toBeTruthy();
  });
});

describe("what it lets the user do", () => {
  it("cannot go back from the first page", () => {
    renderAt(0, 120);
    expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);
  });

  it("cannot go past the last page", () => {
    renderAt(100, 120);
    expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(true);
  });

  it("moves forward by one page", () => {
    const onChange = renderAt(25, 120);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onChange).toHaveBeenCalledWith(50);
  });

  it("moves back by one page", () => {
    const onChange = renderAt(25, 120);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onChange).toHaveBeenCalledWith(0);
  });

  it("never asks for a negative offset", () => {
    const onChange = renderAt(10, 120);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onChange).toHaveBeenCalledWith(0);
  });
});
