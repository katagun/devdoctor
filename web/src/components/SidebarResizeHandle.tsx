import { useRef } from "react";

const SNAP_THRESHOLD = 80;
const COLLAPSED_WIDTH = 48;
const KEY_STEP = 16;

export interface SidebarResizeHandleProps {
  width: number;
  maxWidth: number;
  setWidth: (px: number) => void;
  finalize: (px: number) => void;
  hidden?: boolean;
}

export function SidebarResizeHandle({
  width,
  maxWidth,
  setWidth,
  finalize,
  hidden = false,
}: SidebarResizeHandleProps) {
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null);
  const lastWidthRef = useRef<number>(width);
  lastWidthRef.current = width;

  if (hidden) return null;

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    // Only process left-mouse-button or primary touch; button is sometimes undefined in tests
    if (e.button && e.button !== 0) return;
    dragState.current = { startX: e.clientX, startWidth: width };

    // setPointerCapture isn't always implemented in jsdom; guard it.
    if (typeof e.currentTarget.setPointerCapture === "function") {
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        /* ignore — move/up handlers still fire */
      }
    }
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragState.current) return;
    const next = dragState.current.startWidth + (e.clientX - dragState.current.startX);
    setWidth(next);
  }

  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragState.current) return;
    const rawFinal = dragState.current.startWidth + (e.clientX - dragState.current.startX);
    dragState.current = null;

    if (typeof e.currentTarget.releasePointerCapture === "function") {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    }

    // Snap-to-collapsed: below the threshold, finalize at the collapsed width.
    if (rawFinal < SNAP_THRESHOLD) {
      finalize(COLLAPSED_WIDTH);
    } else {
      // Clamp the final value against maxWidth to match what the hook accepted.
      const finalWidth = Math.max(
        COLLAPSED_WIDTH,
        Math.min(rawFinal, maxWidth),
      );
      finalize(finalWidth);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    switch (e.key) {
      case "ArrowLeft":
        e.preventDefault();
        setWidth(width - KEY_STEP);
        break;
      case "ArrowRight":
        e.preventDefault();
        setWidth(width + KEY_STEP);
        break;
      case "Home":
        e.preventDefault();
        setWidth(COLLAPSED_WIDTH);
        break;
      case "End":
        e.preventDefault();
        setWidth(maxWidth);
        break;
    }
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuenow={width}
      aria-valuemin={COLLAPSED_WIDTH}
      aria-valuemax={maxWidth}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
      className="absolute top-0 bottom-0 w-1 -right-0.5 cursor-col-resize hover:bg-border-strong focus:bg-border-strong focus:outline-none"
    />
  );
}
