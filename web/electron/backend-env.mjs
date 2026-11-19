import path from "node:path";

// Where developer tools usually live. An app opened from Finder or the Dock
// inherits launchd's PATH (/usr/bin:/bin:/usr/sbin:/sbin), not the login
// shell's, so without these the backend finds none of brew, uv, go, pnpm or
// docker and most tool-backed providers report nothing.
const TOOL_DIRS = [
  "/opt/homebrew/bin",
  "/opt/homebrew/sbin",
  "/usr/local/bin",
  "~/.local/bin",
  "~/.cargo/bin",
  "~/.bun/bin",
  "~/go/bin",
  "~/.docker/bin",
  "~/Library/pnpm",
];

/**
 * The PATH for the backend: what the app was given, then each usual tool
 * directory that exists and is not already on it. Appended, never prepended,
 * so nothing here can shadow a tool the user's environment already resolves.
 */
export function backendPath(currentPath, home, exists) {
  const dirs = (currentPath ?? "").split(path.delimiter).filter(Boolean);
  for (const raw of TOOL_DIRS) {
    const dir = raw.startsWith("~/") ? path.join(home, raw.slice(2)) : raw;
    if (!dirs.includes(dir) && exists(dir)) dirs.push(dir);
  }
  return dirs.join(path.delimiter);
}
