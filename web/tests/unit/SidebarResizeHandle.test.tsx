import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SidebarResizeHandle } from "@/components/SidebarResizeHandle";

function renderHandle(props: Partial<React.ComponentProps<typeof SidebarResizeHandle>> = {}) {
  const setWidth = props.setWidth ?? vi.fn();
  const finalize = props.finalize ?? vi.fn();
  const width = props.width ?? 180;
  const maxWidth = props.maxWidth ?? 288;
  const hidden = props.hidden ?? false;
  render(
    <SidebarResizeHandle
      width={width}
      maxWidth={maxWidth}
      setWidth={setWidth}
      finalize={finalize}
      hidden={hidden}
    />,
  );
  return { setWidth, finalize };
}

describe("SidebarResizeHandle", () => {
  it("renders a separator with correct aria attributes", () => {
    renderHandle({ width: 180, maxWidth: 288 });
    const sep = screen.getByRole("separator");
    expect(sep).toBeInTheDocument();
    expect(sep.getAttribute("aria-orientation")).toBe("vertical");
    expect(sep.getAttribute("aria-label")).toBe("Resize sidebar");
    expect(sep.getAttribute("aria-valuenow")).toBe("180");
    expect(sep.getAttribute("aria-valuemin")).toBe("48");
    expect(sep.getAttribute("aria-valuemax")).toBe("288");
  });

  it("does not render when hidden=true", () => {
    renderHandle({ hidden: true });
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  });

  function createPointerEvent(type: string, clientX: number, pointerId: number) {
    const event = new MouseEvent(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clientX", { value: clientX, configurable: true });
    Object.defineProperty(event, "pointerId", { value: pointerId, configurable: true });
    return event;
  }

  it("pointerdown + move updates width via setWidth", () => {
    const { setWidth } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    sep.dispatchEvent(createPointerEvent("pointerdown", 200, 1));
    sep.dispatchEvent(createPointerEvent("pointermove", 260, 1));
    // startWidth 180 + (260 - 200) = 240
    expect(setWidth).toHaveBeenCalledWith(240);
  });

  it("pointerup above the snap threshold calls finalize with the current width", () => {
    const { setWidth, finalize } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    sep.dispatchEvent(createPointerEvent("pointerdown", 200, 1));
    sep.dispatchEvent(createPointerEvent("pointermove", 260, 1));
    sep.dispatchEvent(createPointerEvent("pointerup", 260, 1));
    expect(setWidth).toHaveBeenLastCalledWith(240);
    expect(finalize).toHaveBeenCalledWith(240);
  });

  it("pointerup below the snap threshold (<80) calls finalize(48) to snap", () => {
    const { setWidth, finalize } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    sep.dispatchEvent(createPointerEvent("pointerdown", 200, 1));
    sep.dispatchEvent(createPointerEvent("pointermove", 60, 1));
    // setWidth call for the move will have clamped to 48 inside the hook's setter,
    // but the handle itself calls setWidth with the raw (negative-ish) delta.
    // What we care about here is the snap on release:
    sep.dispatchEvent(createPointerEvent("pointerup", 60, 1));
    expect(finalize).toHaveBeenCalledWith(48);
    void setWidth; // silence unused
  });

  it("ArrowLeft decreases width by 16 via setWidth", () => {
    const { setWidth } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    fireEvent.keyDown(sep, { key: "ArrowLeft" });
    expect(setWidth).toHaveBeenCalledWith(164);
  });

  it("ArrowRight increases width by 16 via setWidth", () => {
    const { setWidth } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    fireEvent.keyDown(sep, { key: "ArrowRight" });
    expect(setWidth).toHaveBeenCalledWith(196);
  });

  it("Home jumps to 48 and End jumps to maxWidth", () => {
    const { setWidth } = renderHandle({ width: 180, maxWidth: 288 });
    const sep = screen.getByRole("separator");
    fireEvent.keyDown(sep, { key: "Home" });
    expect(setWidth).toHaveBeenCalledWith(48);
    fireEvent.keyDown(sep, { key: "End" });
    expect(setWidth).toHaveBeenCalledWith(288);
  });

  it("pointercancel drops the drag without snapping (finalize not called)", () => {
    const { finalize } = renderHandle({ width: 180 });
    const sep = screen.getByRole("separator");
    sep.dispatchEvent(createPointerEvent("pointerdown", 200, 1));
    sep.dispatchEvent(createPointerEvent("pointermove", 60, 1));
    sep.dispatchEvent(createPointerEvent("pointercancel", 60, 1));
    expect(finalize).not.toHaveBeenCalled();
  });
});
