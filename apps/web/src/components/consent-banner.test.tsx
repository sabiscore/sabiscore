import { fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import { analyticsConsented, CONSENT_STORAGE_KEY } from "@/lib/consent";

import { ConsentBanner, ConsentProvider } from "./consent-banner";

afterEach(() => localStorage.clear());

// v11 U14: the first visit stacked an 18+ gate and then a cookie banner over the
// market table at 360 px, and the banner's choices were read by nothing.
describe("ConsentBanner", () => {
  it("asks once, and closes after one choice with no second banner", async () => {
    const { container } = render(<ConsentBanner />);
    expect(await screen.findAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /18\+ · essential only/i }));
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    [/allow anonymous usage counts/i, true],
    [/essential only/i, false],
  ])("stores the analytics choice the tracker reads (%s)", async (name, allowed) => {
    render(<ConsentBanner />);
    fireEvent.click(await screen.findByRole("button", { name }));
    expect(JSON.parse(localStorage.getItem(CONSENT_STORAGE_KEY)!).analytics).toBe(allowed);
    expect(analyticsConsented()).toBe(allowed);
  });

  it("offers no advertising toggle: there is no advertising", async () => {
    render(<ConsentBanner />);
    await screen.findByRole("dialog");
    expect(screen.queryByText(/advertisement|marketing/i)).toBeNull();
  });
});

describe("ConsentProvider", () => {
  // Live 2026-09-27: every page's server HTML was a lone spinner (no <h1>), so
  // first paint waited for hydration while the content sat unused in the RSC
  // payload of the same response.
  it("server-renders the page, not a spinner in its place", () => {
    const html = renderToString(
      <ConsentProvider>
        <h1>Upcoming verified fixtures</h1>
      </ConsentProvider>,
    );
    expect(html).toContain("<h1>Upcoming verified fixtures</h1>");
    expect(html).not.toContain("animate-spin");
  });

  it("still asks a first-time visitor once the stored choice is read", async () => {
    render(
      <ConsentProvider>
        <h1>Page</h1>
      </ConsentProvider>,
    );
    expect(await screen.findAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Page" })).toBeInTheDocument();
  });
});
