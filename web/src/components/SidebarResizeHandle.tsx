import { useRef, useState } from "react";
import { SIDEBAR_MIN_WIDTH } from "@/hooks/useSettings";

const SNAP_THRESHOLD = 80;
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
  const [isDragging, setIsDragging] = useState(false);

  if (hidden) return null;

  function releaseCapture(e: React.PointerEvent<HTMLDivElement>) {
    if (typeof e.currentTarget.releasePointerCapture === "function") {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    }
  }

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    // Only process left-mouse-button or primary touch; button is sometimes undefined in tests
    if (e.button && e.button !== 0) return;
    dragState.current = { startX: e.clientX, startWidth: width };
    setIsDragging(true);

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
    setIsDragging(false);
    releaseCapture(e);

    // Snap-to-collapsed: below the threshold, finalize at the collapsed width.
    if (rawFinal < SNAP_THRESHOLD) {
      finalize(SIDEBAR_MIN_WIDTH);
    } else {
      // Clamp the final value against maxWidth to match what the hook accepted.
      const finalWidth = Math.max(
        SIDEBAR_MIN_WIDTH,
        Math.min(rawFinal, maxWidth),
      );
      finalize(finalWidth);
    }
  }

  function onPointerCancel(e: React.PointerEvent<HTMLDivElement>) {
    // Per spec: cancelled or lost-capture drops the drag without applying snap.
    // Stored width stays at whatever the last onPointerMove -> setWidth wrote.
    if (!dragState.current) return;
    dragState.current = null;
    setIsDragging(false);
    releaseCapture(e);
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
        setWidth(SIDEBAR_MIN_WIDTH);
        break;
      case "End":
        e.preventDefault();
        setWidth(maxWidth);
        break;
    }
  }

  const activeClass = isDragging ? "bg-border-strong" : "";

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuenow={width}
      aria-valuemin={SIDEBAR_MIN_WIDTH}
      aria-valuemax={maxWidth}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onKeyDown={onKeyDown}
      className={`absolute top-0 bottom-0 w-1 -right-0.5 cursor-col-resize hover:bg-border-strong focus:bg-border-strong focus:outline-none ${activeClass}`}
    />
  );
}
