import { render, screen, within } from "@testing-library/react";
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

  it("renders grouped nav links in resource-first order", () => {
    renderSidebar();
    const nav = screen.getByRole("navigation", { name: /primary/i });
    const labels = within(nav).getAllByRole("link").map((link) => link.textContent?.trim());
    expect(labels).toEqual([
      "◆ disk",
      "◫ memory",
      "▣ providers",
      "⏱ snapshots",
      "≡ history",
      "▤ planner",
      "▣ providers",
      "⏱ snapshots",
      "≡ history",
      "⚙ settings",
    ]);
  });

  it("renders section headers for the expanded sidebar", () => {
    renderSidebar();
    for (const label of ["resources", "disk tools", "memory tools", "app"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("each nav link renders its glyph", () => {
    renderSidebar();
    const expected = [
      ["/disk", "◆"],
      ["/memory", "◫"],
      ["/disk/providers", "▣"],
      ["/disk/snapshots", "⏱"],
      ["/disk/history", "≡"],
      ["/memory/planner", "▤"],
      ["/memory/providers", "▣"],
      ["/memory/snapshots", "⏱"],
      ["/memory/history", "≡"],
      ["/settings", "⚙"],
    ] as const;
    const links = screen.getAllByRole("link");
    for (const [href, glyph] of expected) {
      const link = links.find((item) => item.getAttribute("href") === href);
      expect(link).toBeDefined();
      expect(link?.textContent).toContain(glyph);
    }
  });

  it("can move tools out of the sidebar when page tabs are preferred", () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ toolNavigation: "tabs" }),
    );
    __testReloadSettings();
    renderSidebar();

    const nav = screen.getByRole("navigation", { name: /primary/i });
    const labels = within(nav).getAllByRole("link").map((link) => link.textContent?.trim());
    expect(labels).toEqual(["◆ disk", "◫ memory", "⚙ settings"]);
    expect(screen.queryByText(/^disk tools$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^memory tools$/i)).not.toBeInTheDocument();
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

    it("hides section headers", () => {
      renderSidebar();
      for (const label of ["resources", "disk tools", "memory tools", "app"]) {
        expect(screen.queryByText(new RegExp(`^${label}$`, "i"))).not.toBeInTheDocument();
      }
    });

    it("each nav link has its full label text marked sr-only", () => {
      renderSidebar();
      const diskLink = screen.getByRole("link", { name: /disk/i });
      const label = diskLink.querySelector(".sr-only");
      expect(label).not.toBeNull();
      expect(label?.textContent).toBe("disk");
    });

    it("each nav link carries a title attribute equal to its label", () => {
      renderSidebar();
      const expected = [
        ["/disk", "disk"],
        ["/memory", "memory"],
        ["/disk/providers", "providers"],
        ["/disk/snapshots", "snapshots"],
        ["/disk/history", "history"],
        ["/memory/planner", "planner"],
        ["/memory/providers", "providers"],
        ["/memory/snapshots", "snapshots"],
        ["/memory/history", "history"],
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
