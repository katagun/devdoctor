import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColumnsPicker } from "@/components/ColumnsPicker";

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

function renderPicker() {
  return render(<ColumnsPicker />);
}

describe("ColumnsPicker", () => {
  it("button is collapsed by default", () => {
    renderPicker();
    const btn = screen.getByRole("button", { name: /columns/i });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("clicking the button opens the panel with aria-expanded=true", () => {
    renderPicker();
    const btn = screen.getByRole("button", { name: /columns/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("renders one menuitemcheckbox per column (provider is disabled)", () => {
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const items = screen.getAllByRole("menuitemcheckbox");
    expect(items).toHaveLength(6);
    const providerItem = items.find((el) => /provider/i.test(el.textContent ?? ""));
    expect(providerItem?.getAttribute("aria-disabled")).toBe("true");
  });

  it("toggling a checkbox persists the change", () => {
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const items = screen.getAllByRole("menuitemcheckbox");
    const staleItem = items.find((el) => /stale/i.test(el.textContent ?? ""))!;
    expect(staleItem.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(staleItem);
    expect(staleItem.getAttribute("aria-checked")).toBe("false");
    const stored = JSON.parse(localStorage.getItem("devdoctor.settings.v1") ?? "{}");
    expect(stored.scanTableHiddenColumns).toContain("stale");
  });

  it("clicking the disabled provider item does NOT change state", () => {
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    const items = screen.getAllByRole("menuitemcheckbox");
    const providerItem = items.find((el) => /provider/i.test(el.textContent ?? ""))!;
    fireEvent.click(providerItem);
    expect(providerItem.getAttribute("aria-checked")).toBe("true");
    const stored = JSON.parse(localStorage.getItem("devdoctor.settings.v1") ?? "{}");
    expect(stored.scanTableHiddenColumns ?? []).not.toContain("provider");
  });

  it("Escape closes the panel and returns aria-expanded to false", () => {
    renderPicker();
    const btn = screen.getByRole("button", { name: /columns/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("click outside closes the panel", () => {
    render(
      <div>
        <ColumnsPicker />
        <div data-testid="outside">outside</div>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: /columns/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
