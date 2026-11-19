import { describe, expect, it } from "vitest";
import { backendPath } from "../../electron/backend-env.mjs";

describe("backendPath", () => {
  const home = "/Users/me";
  const all = () => true;

  it("adds the usual tool directories after what launchd provided", () => {
    // An app opened from Finder gets launchd's PATH, not the login shell's, so
    // brew, uv, go and docker were invisible to the backend's providers.
    const result = backendPath("/usr/bin:/bin", home, all).split(":");
    expect(result.slice(0, 2)).toEqual(["/usr/bin", "/bin"]);
    expect(result).toContain("/opt/homebrew/bin");
    expect(result).toContain("/usr/local/bin");
    expect(result).toContain("/Users/me/.local/bin");
    expect(result).toContain("/Users/me/.cargo/bin");
  });

  it("keeps the existing order and never repeats a directory", () => {
    const result = backendPath("/opt/homebrew/bin:/usr/bin", home, all).split(":");
    expect(result[0]).toBe("/opt/homebrew/bin");
    expect(result.filter((dir) => dir === "/opt/homebrew/bin")).toHaveLength(1);
  });

  it("skips directories that do not exist", () => {
    const result = backendPath("/usr/bin", home, (dir) => dir === "/usr/local/bin");
    expect(result).toBe("/usr/bin:/usr/local/bin");
  });

  it("copes with no PATH at all", () => {
    expect(backendPath(undefined, home, () => false)).toBe("");
  });
});
