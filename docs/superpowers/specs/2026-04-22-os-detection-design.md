# OS / device detection gate — design

Date: 2026-04-22
Status: approved for implementation plan

## Goal

Block the web UI with a full-page "not supported" screen when the user opens it from a non-desktop / non-macOS-or-Linux browser. Prevents confusing broken behaviour on Windows (no backend), iOS/Android/iPadOS (unsupported layouts), and unknown platforms.

## Scope

- Frontend-only gate. Backend is unchanged — it continues to refuse to install on Windows via `pyproject.toml` platform constraints.
- No persistence, no override, no URL flag escape hatch.
- Runs once per session at mount; detection is static for the session.
- Independent of the existing `<768px` responsive-chrome rule (which still force-collapses the sidebar on narrow windows regardless of OS).

## Architecture

Two new files plus a three-line change to `AppShell`:

```
web/src/lib/deviceSupport.ts        → pure function + hook
web/src/components/UnsupportedDevice.tsx  → full-page block screen
web/src/AppShell.tsx                → gate at top of render (edit)
```

Detection logic is a pure function taking `DeviceSignals` so it is unit-testable without touching global `navigator`. The hook reads `navigator.userAgent` / `navigator.maxTouchPoints` at render and forwards them.

## Detection rules

`evaluateDeviceSupport(signals)` evaluates in this order; first match wins:

1. UA matches `/Android/i` → **blocked**, `detected: "Android"` (Linux UAs also contain "Linux"; Android must be checked first)
2. UA matches `/iPhone|iPod/` → **blocked**, `detected: "iOS"`
3. UA matches `/iPad/` OR (`/Macintosh/` AND `maxTouchPoints > 1`) → **blocked**, `detected: "iPadOS"` (newer iPad Safari reports as Macintosh; touch check disambiguates)
4. UA matches `/Windows/i` → **blocked**, `detected: "Windows"`
5. UA matches `/Mac/` → **supported** (regular Mac, iPad already caught above)
6. UA matches `/Linux/i` → **supported** (Android already caught above; catches Linux desktop and Chrome OS)
7. Fallthrough → **blocked**, `detected: "unknown"` (fail closed)

Chromebooks fall through rule 6 (Linux) → supported. If we later want to explicitly block Chrome OS, add `/CrOS/` check before rule 6. Not blocking it for now.

## Types

```ts
export type SupportStatus =
  | { kind: "supported" }
  | { kind: "blocked"; detected: string };

export interface DeviceSignals {
  userAgent: string;
  maxTouchPoints: number;
}
```

## `deviceSupport.ts` contents

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

No `useState` / `useEffect`. The hook is a pure computation that reads live `navigator` on every render. Tests that mutate `navigator.userAgent` / `maxTouchPoints` between renders see the change take effect on the next render.

## `UnsupportedDevice.tsx` contents

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

Styling matches the terminal-refined theme: same `bg-bg` / `text-text*` palette, same brand dot + wordmark treatment as the Sidebar header, same font-mono family.

## `AppShell.tsx` integration

Gate at the top of the component, after `useApplyTheme()` (so the theme still applies to the block screen) and before any other hook. Full edited shape:

```tsx
export default function AppShell() {
  useApplyTheme();
  const support = useDeviceSupport();
  if (support.kind === "blocked") {
    return <UnsupportedDevice detected={support.detected} />;
  }
  const { width, toggle, forceCollapsedByViewport } = useSidebarWidth();
  // ... existing keyboard shortcut useEffect and JSX unchanged
}
```

### Rules-of-hooks consideration

An early return skips the hooks below it (`useSidebarWidth`, the keyboard `useEffect`). React's rule is that hooks must be called in the same order across renders of the same component instance. A given browser session is either always blocked (new fresh mount) or always supported — the status cannot flip between renders because `navigator.userAgent` does not change. So the hook order is stable across the lifetime of every mounted `AppShell`. The rule is honoured.

## Testing

### `web/tests/unit/deviceSupport.test.ts` (new)

Table-driven test over representative user-agent strings. One `describe` block, one `it.each(...)` covering:

```
macOS Chrome       → supported
macOS Safari       → supported
Ubuntu Firefox     → supported
Fedora Chromium    → supported
Chrome OS          → supported (falls through to Linux rule)
Windows Chrome     → blocked (Windows)
Windows Edge       → blocked (Windows)
iPhone Safari      → blocked (iOS)
iPad Safari (with maxTouchPoints=5, UA=Macintosh) → blocked (iPadOS)
Mac desktop (maxTouchPoints=0, UA=Macintosh)       → supported
iPad Safari (classic UA with iPad)                 → blocked (iPadOS)
Android Chrome                                     → blocked (Android)
Made-up UA with no OS match                        → blocked (unknown)
```

Plus dedicated tests for the tricky cases:
- "iPadOS reporting as Macintosh with touch is blocked"
- "Mac desktop with maxTouchPoints=0 is supported"
- "Chrome OS is supported (currently) because it falls through to Linux rule"
- "Fallthrough on unknown UA blocks with 'unknown' detected string"

### No `UnsupportedDevice.test.tsx`

Pure presentational component. Snapshot tests here would be brittle (any copy tweak breaks the snapshot) and wouldn't catch real defects. Skipped.

### No new AppShell test

The gate is one line of logic. `AppShell` has no existing test file and setting one up requires `MemoryRouter` + providers scaffolding that's more effort than the feature warrants. The detection is verified by the unit tests; the component composition is trivial.

## Bundle and performance

- No new dependencies.
- `deviceSupport.ts` adds ~40 LOC. `UnsupportedDevice.tsx` adds ~40 LOC. Total bundle delta sub-kilobyte gzipped.
- Detection is synchronous at first render — no flash of app before the gate kicks in.

## Non-goals

- No "Continue anyway" escape hatch. (Per brainstorming Q3 — if someone really needs to override, they can devtools their way past; not a security feature.)
- No persistence of the decision. (Recomputed per load; UA rarely changes.)
- No server-side enforcement. (Backend platform restriction is the server-side gate.)
- No telemetry on how many users hit the block screen.
- No Chromebook-specific behaviour yet; revisit if user feedback suggests it.
- No routing change. The block screen replaces the entire `AppShell` content, not just the route outlet, so the URL is irrelevant while blocked.

## Open questions resolved during brainstorming

- **Gate severity** (Q1): full-page takeover (option A). No dismissible banner.
- **Detection criteria** (Q2): rule-set above, accepted as-is. Chrome OS currently falls through to Linux → supported.
- **Block screen content** (Q3): shown verbatim above. Detected-OS debug hint included; no escape hatch; no support link.
