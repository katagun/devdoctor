import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach } from "vitest";
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
        JSON.stringify({ sidebarCollapsed: true }),
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
  });
});
