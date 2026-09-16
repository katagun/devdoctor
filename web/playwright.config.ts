import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PORT } from "./tests/e2e/fixture";

const here = path.dirname(fileURLToPath(import.meta.url));

// One env file per run, shared with the web server and the workers through the
// environment (both inherit it from this process).
process.env.DEVDOCTOR_E2E_ENV_FILE ??= path.join(os.tmpdir(), `devdoctor-e2e-${process.pid}.json`);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  // serve.ts builds a throwaway home and runs `devdoctor serve` inside it, so the
  // tests never scan the developer's machine (#105).
  webServer: {
    command: "bun run tests/e2e/serve.ts",
    cwd: here,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    // SIGTERM before SIGKILL, so serve.ts gets to remove the fixture home.
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
  },
});
