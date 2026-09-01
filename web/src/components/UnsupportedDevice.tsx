import { APP_NAME, CLI_NAME } from "@/lib/brand";

export function UnsupportedDevice({ detected }: { detected: string }) {
  return (
    <div className="min-h-screen bg-bg text-text font-mono flex items-center justify-center p-8">
      <div className="max-w-xl">
        <div className="flex items-center gap-2 mb-6">
          <span
            className="w-[7px] h-[7px] rounded-full bg-risk-reclaim"
            style={{ boxShadow: "0 0 10px var(--risk-reclaim)" }}
          />
          <span className="font-semibold text-[14px]">{APP_NAME}</span>
        </div>
        <h1 className="text-text text-[18px] font-medium mb-2">
          Not supported on this device
        </h1>
        <p className="text-text-dim text-[12px] leading-relaxed mb-4">
          {APP_NAME} is a desktop utility for local developer workstation
          resources. This build scans and cleans local filesystem caches. It's
          supported on:
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
          <code className="text-text-dim">{CLI_NAME} serve</code>, open
          this URL from a supported client instead.
        </p>
      </div>
    </div>
  );
}
