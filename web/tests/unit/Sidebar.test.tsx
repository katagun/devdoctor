import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { Sidebar } from "@/components/Sidebar";

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
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
});
