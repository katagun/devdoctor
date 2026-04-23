# OS / device detection gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate the web UI with a full-page "Not supported on this device" screen for Windows, iOS, iPadOS (with touch), Android, and unknown user-agents. macOS and Linux (including Chrome OS currently) are allowed.

**Architecture:** One pure-function detection module (`lib/deviceSupport.ts`) consumed by a zero-state hook, one presentational component (`UnsupportedDevice.tsx`), and one early-return insertion at the top of `AppShell`. Detection reads `navigator.userAgent` + `navigator.maxTouchPoints` once per render; no async, no persistence, no URL flag.

**Tech Stack:** TypeScript, React 18, Vite, Vitest + `@testing-library/react`, Tailwind 4. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-04-22-os-detection-design.md`.

**Working directory for every command below:** the worktree the executor creates (e.g. `/Users/shamil/projects/github/katagun/diskdoctor/.worktrees/os-detection`). All `cd` commands use the worktree's `web/` subdir unless stated.

---

## Task 1: Detection module + tests

**Files:**
- Create: `web/src/lib/deviceSupport.ts`
- Create: `web/tests/unit/deviceSupport.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/deviceSupport.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  evaluateDeviceSupport,
  useDeviceSupport,
} from "@/lib/deviceSupport";

// Representative UA strings. Keep this matrix visible so adding/editing
// rules stays easy to reason about.
const CASES: Array<[string, string, number, "supported" | string]> = [
  // [description, userAgent, maxTouchPoints, expected]
  [
    "macOS Chrome",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "supported",
  ],
  [
    "macOS Safari",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    0,
    "supported",
  ],
  [
    "Ubuntu Firefox",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    0,
    "supported",
  ],
  [
    "Fedora Chromium",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "supported",
  ],
  [
    "Chrome OS",
    "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "supported",
  ],
  [
    "Windows Chrome",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    0,
    "Windows",
  ],
  [
    "Windows Edge",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    0,
    "Windows",
  ],
  [
    "iPhone Safari",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    5,
    "iOS",
  ],
  [
    "iPad Safari (classic UA with iPad token)",
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    5,
    "iPadOS",
  ],
  [
    "iPad Safari (newer, reports Macintosh with touch)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    5,
    "iPadOS",
  ],
  [
    "Android Chrome",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    5,
    "Android",
  ],
  [
    "Unknown / exotic UA",
    "Mozilla/5.0 (compatible; SomeBotEmulator/1.0)",
    0,
    "unknown",
  ],
];

describe("evaluateDeviceSupport", () => {
  it.each(CASES)("%s → %s", (_desc, ua, mtp, expected) => {
    const result = evaluateDeviceSupport({ userAgent: ua, maxTouchPoints: mtp });
    if (expected === "supported") {
      expect(result).toEqual({ kind: "supported" });
    } else {
      expect(result).toEqual({ kind: "blocked", detected: expected });
    }
  });

  it("Mac desktop with maxTouchPoints=0 is supported even though the UA says Macintosh", () => {
    const result = evaluateDeviceSupport({
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      maxTouchPoints: 0,
    });
    expect(result).toEqual({ kind: "supported" });
  });

  it("iPadOS reporting as Macintosh with maxTouchPoints>1 is blocked", () => {
    const result = evaluateDeviceSupport({
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      maxTouchPoints: 5,
    });
    expect(result).toEqual({ kind: "blocked", detected: "iPadOS" });
  });

  it("falls through to 'unknown' when no rule matches", () => {
    const result = evaluateDeviceSupport({
      userAgent: "totally-made-up-no-os-here",
      maxTouchPoints: 0,
    });
    expect(result).toEqual({ kind: "blocked", detected: "unknown" });
  });

  it("Android UA containing 'Linux' is blocked as Android, not allowed as Linux", () => {
    const result = evaluateDeviceSupport({
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36",
      maxTouchPoints: 5,
    });
    expect(result).toEqual({ kind: "blocked", detected: "Android" });
  });
});

describe("useDeviceSupport", () => {
  const originalUA = navigator.userAgent;
  const originalMTP = navigator.maxTouchPoints;

  afterEach(() => {
    Object.defineProperty(navigator, "userAgent", {
      value: originalUA,
      configurable: true,
    });
    Object.defineProperty(navigator, "maxTouchPoints", {
      value: originalMTP,
      configurable: true,
    });
    vi.restoreAllMocks();
  });

  it("reads live navigator signals", () => {
    Object.defineProperty(navigator, "userAgent", {
      value:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
      configurable: true,
    });
    Object.defineProperty(navigator, "maxTouchPoints", {
      value: 0,
      configurable: true,
    });
    expect(useDeviceSupport()).toEqual({ kind: "blocked", detected: "Windows" });
  });
});
```

- [ ] **Step 2: Run tests and watch them fail**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/deviceSupport.test.ts
```

Expected: FAIL with module-resolution errors on `@/lib/deviceSupport`.

- [ ] **Step 3: Implement the module**

Create `web/src/lib/deviceSupport.ts`:

```ts
export type SupportStatus =
  | { kind: "supported" }
  | { kind: "blocked"; detected: string };

export interface DeviceSignals {
  userAgent: string;
  maxTouchPoints: number;
}

export function evaluateDeviceSupport(sig: DeviceSignals): SupportStatus {
  const ua = sig.userAgent;
  // Order matters: Android UAs contain "Linux", iPadOS may report as Macintosh.
  if (/Android/i.test(ua)) return { kind: "blocked", detected: "Android" };
  if (/iPhone|iPod/.test(ua)) return { kind: "blocked", detected: "iOS" };
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && sig.maxTouchPoints > 1)) {
    return { kind: "blocked", detected: "iPadOS" };
  }
  if (/Windows/i.test(ua)) return { kind: "blocked", detected: "Windows" };
  if (/Mac/.test(ua)) return { kind: "supported" };
  if (/Linux/i.test(ua)) return { kind: "supported" };
  return { kind: "blocked", detected: "unknown" };
}

export function useDeviceSupport(): SupportStatus {
  return evaluateDeviceSupport({
    userAgent: typeof navigator === "undefined" ? "" : navigator.userAgent,
    maxTouchPoints: typeof navigator === "undefined" ? 0 : navigator.maxTouchPoints,
  });
}
```

- [ ] **Step 4: Run tests and watch them pass**

Run:
```bash
cd <worktree>/web
npx vitest run tests/unit/deviceSupport.test.ts
```

Expected: PASS. The `it.each` produces 12 rows + 5 dedicated tests + 1 hook test = 18 total in the file.

- [ ] **Step 5: Run the full test suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 88 tests total (70 prior + 18 new).

- [ ] **Step 6: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd <worktree>
git add web/src/lib/deviceSupport.ts web/tests/unit/deviceSupport.test.ts
git commit -m "feat(web): deviceSupport module with UA-based OS detection"
```

---

## Task 2: `<UnsupportedDevice>` block-screen component

**Files:**
- Create: `web/src/components/UnsupportedDevice.tsx`

Pure presentational component. No test file — snapshot tests over JSX would be brittle (any copy edit breaks them) and there is no logic to assert. Visual correctness is verified in Task 3's browser check.

- [ ] **Step 1: Create the component**

Create `web/src/components/UnsupportedDevice.tsx`:

```tsx
export function UnsupportedDevice({ detected }: { detected: string }) {
  return (
    <div className="min-h-screen bg-bg text-text font-mono flex items-center justify-center p-8">
      <div className="max-w-xl">
        <div className="flex items-center gap-2 mb-6">
          <span
            className="w-[7px] h-[7px] rounded-full bg-risk-reclaim"
            style={{ boxShadow: "0 0 10px var(--risk-reclaim)" }}
          />
          <span className="font-semibold text-[14px]">diskdoctor</span>
        </div>
        <h1 className="text-text text-[18px] font-medium mb-2">
          Not supported on this device
        </h1>
        <p className="text-text-dim text-[12px] leading-relaxed mb-4">
          diskdoctor is a desktop utility that scans and cleans local filesystem
          caches. It's supported on:
        </p>
        <ul className="text-text-dim text-[12px] mb-4 space-y-1">
          <li className="flex gap-2">
            <span className="text-text-muted">·</span>
            <span>macOS (Intel / Apple Silicon)</span>
          </li>
          <li className="flex gap-2">
            <span className="text-text-muted">·</span>
            <span>Linux (x86_64 / arm64 desktop)</span>
          </li>
        </ul>
        <p className="text-text-dim text-[12px] mb-4">
          You appear to be on: <span className="text-text">{detected}</span>
        </p>
        <p className="text-text-muted text-[11px] leading-relaxed">
          If you're connecting remotely to a macOS or Linux host that's running{" "}
          <code className="text-text-dim">diskdoctor serve</code>, open this URL
          from a supported client instead.
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 3: Run the full test suite to confirm no regression**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 88 tests (no change; new component has no test file).

- [ ] **Step 4: Commit**

```bash
cd <worktree>
git add web/src/components/UnsupportedDevice.tsx
git commit -m "feat(web): UnsupportedDevice block-screen component"
```

---

## Task 3: Gate integration in `AppShell` + build + visual check

**Files:**
- Modify: `web/src/AppShell.tsx`

- [ ] **Step 1: Update `AppShell.tsx`**

Replace the ENTIRE contents of `web/src/AppShell.tsx` with:

```tsx
import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { UnsupportedDevice } from "./components/UnsupportedDevice";
import { useApplyTheme } from "./hooks/useApplyTheme";
import { useDeviceSupport } from "./lib/deviceSupport";
import { useSidebarWidth } from "./hooks/useSidebarWidth";

const MAC_LIKE = /^Mac/.test(
  typeof navigator !== "undefined" ? navigator.platform : "",
);

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export default function AppShell() {
  useApplyTheme();
  const support = useDeviceSupport();

  // Early return gate. A given browser session is either always blocked or
  // always supported — navigator.userAgent doesn't change within a mount —
  // so this never violates rules-of-hooks about consistent hook call order.
  if (support.kind === "blocked") {
    return <UnsupportedDevice detected={support.detected} />;
  }

  const { width, toggle, forceCollapsedByViewport } = useSidebarWidth();

  useEffect(() => {
    function onKeydown(e: KeyboardEvent) {
      if (forceCollapsedByViewport) return;
      if (e.key !== "b" && e.key !== "B") return;
      const modifier = MAC_LIKE ? e.metaKey : e.ctrlKey;
      if (!modifier) return;
      if (e.altKey || e.shiftKey) return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      toggle();
    }
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, [toggle, forceCollapsedByViewport]);

  return (
    <div
      className="min-h-screen grid bg-bg text-text font-sans"
      style={{ gridTemplateColumns: `${width}px 1fr` }}
    >
      <Sidebar />
      <main className="flex flex-col min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run:
```bash
cd <worktree>/web
npm run typecheck
```

Expected: PASS.

- [ ] **Step 3: Run the full test suite**

Run:
```bash
cd <worktree>/web
npx vitest run
```

Expected: PASS — 88 tests. AppShell is not tested directly; the early-return logic is trivial and the detection it consumes is covered by Task 1's tests.

- [ ] **Step 4: Production build**

Run:
```bash
cd <worktree>/web
npm run build
```

Expected: clean build. Bundle delta sub-kilobyte gzipped.

- [ ] **Step 5: Dev-server visual check**

Run:
```bash
cd <worktree>/web
npm run dev
```

Verify in a real browser:

1. **macOS desktop, non-touch** → app loads normally; sidebar + main content visible.
2. **Chrome DevTools → Device Toolbar → iPhone** (which changes the UA and enables touch emulation) → page shows `"Not supported on this device"` with `"You appear to be on: iOS"`.
3. **DevTools → Device Toolbar → iPad** → same block screen, `"detected: iPadOS"`.
4. **DevTools → Network conditions → override UA to Windows** (`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36`) → block screen with `"Windows"`.
5. **DevTools → override UA to Android** → block screen with `"Android"`.
6. **Turn off all overrides** → app returns to normal.
7. **Theme check**: toggle Settings → Appearance → Light. Reopen with a blocked UA; block screen respects the light theme.

- [ ] **Step 6: Commit**

```bash
cd <worktree>
git add web/src/AppShell.tsx
git commit -m "feat(web): gate AppShell behind useDeviceSupport

Early-return at the top of AppShell renders UnsupportedDevice for
Android / iOS / iPadOS / Windows / unknown. Theme still applies because
useApplyTheme is called above the gate. Consistent hook order is
preserved — a session's support status doesn't change within a mount."
```

---

## Out of scope

- No persistence of the gate decision (recomputed per load).
- No override / escape hatch.
- No URL flag to bypass.
- No telemetry.
- No Chromebook-specific block — falls through to Linux → supported.
- No snapshot/visual test for `UnsupportedDevice` — presentational only.

## Rollback

Two commits (Task 1 + Task 3 touch code; Task 2 adds a component not yet referenced until Task 3 lands). Revert in reverse:

```bash
cd <worktree>
git log --oneline main..HEAD
# git revert each in reverse order
```

No persisted state, no migration — reverts are clean.
