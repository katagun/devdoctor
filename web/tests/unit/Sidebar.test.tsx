import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { Sidebar } from "@/components/Sidebar";
import { __testReloadSettings } from "@/hooks/useSettings";

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    localStorage.clear();
    __testReloadSettings();
  });

  it("renders a chevron toggle with aria-expanded=true when expanded", () => {
    renderSidebar();
    const btn = screen.getByRole("button", { name: /collapse sidebar/i });
    expect(btn).toBeInTheDocument();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });

  it("renders all five workspace nav links with their labels", () => {
    renderSidebar();
    for (const label of ["scan", "snapshots", "history", "providers", "settings"]) {
      expect(screen.getByRole("link", { name: new RegExp(label, "i") })).toBeInTheDocument();
    }
  });

  it("each nav link renders its glyph", () => {
    renderSidebar();
    const expected = [
      { label: "scan", glyph: "◆" },
      { label: "snapshots", glyph: "⏱" },
      { label: "history", glyph: "≡" },
      { label: "providers", glyph: "⚙" },
      { label: "settings", glyph: "⚡" },
    ];
    for (const { label, glyph } of expected) {
      const link = screen.getByRole("link", { name: new RegExp(label, "i") });
      expect(link.textContent).toContain(glyph);
    }
  });

  describe("when collapsed", () => {
    beforeEach(() => {
      localStorage.clear();
      localStorage.setItem(
        "diskdoctor.settings.v1",
        JSON.stringify({ sidebarWidth: 48, sidebarExpandedWidth: 180 }),
      );
      __testReloadSettings();
    });

    it("hides the workspace section header", () => {
      renderSidebar();
      expect(screen.queryByText(/^workspace$/i)).not.toBeInTheDocument();
    });

    it("each nav link has its full label text marked sr-only", () => {
      renderSidebar();
      const scanLink = screen.getByRole("link", { name: /scan/i });
      const label = scanLink.querySelector(".sr-only");
      expect(label).not.toBeNull();
      expect(label?.textContent).toBe("scan");
    });

    it("each nav link carries a title attribute equal to its label", () => {
      renderSidebar();
      const expected = [
        ["/", "scan"],
        ["/snapshots", "snapshots"],
        ["/history", "history"],
        ["/providers", "providers"],
        ["/settings", "settings"],
      ] as const;
      for (const [href, label] of expected) {
        const link = screen
          .getAllByRole("link")
          .find((l) => l.getAttribute("href") === href);
        expect(link).toBeDefined();
        expect(link?.getAttribute("title")).toBe(label);
      }
    });

    it("renders a chevron toggle with aria-expanded=false when collapsed", () => {
      renderSidebar();
      const btn = screen.getByRole("button", { name: /expand sidebar/i });
      expect(btn).toBeInTheDocument();
      expect(btn.getAttribute("aria-expanded")).toBe("false");
    });
  });

  describe("when the viewport forces collapsed", () => {
    let originalMatchMedia: typeof window.matchMedia;

    beforeEach(() => {
      localStorage.clear();
      __testReloadSettings();
      // Force matchMedia to match so useSidebarWidth sees
      // forceCollapsedByViewport=true.
      originalMatchMedia = window.matchMedia;
      window.matchMedia = ((query: string) => {
        if (query.includes("max-width: 767px")) {
          return {
            matches: true,
            media: query,
            addEventListener: () => {},
            removeEventListener: () => {},
            dispatchEvent: () => true,
          } as MediaQueryList;
        }
        return originalMatchMedia(query);
      }) as typeof window.matchMedia;
    });

    afterEach(() => {
      // Restore so later tests (or reordered tests) don't inherit the mock.
      window.matchMedia = originalMatchMedia;
    });

    it("does not render the chevron button", () => {
      renderSidebar();
      expect(
        screen.queryByRole("button", { name: /(collapse|expand) sidebar/i }),
      ).not.toBeInTheDocument();
    });
  });
});
