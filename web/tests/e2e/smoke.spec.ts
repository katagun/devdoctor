import { test, expect } from "@playwright/test";
import { spawn, ChildProcess } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let server: ChildProcess | null = null;

test.beforeAll(async () => {
  const repoRoot = path.resolve(__dirname, "../../..");
  const yaml = path.join(repoRoot, "web/tests/e2e/paths.yaml");
  fs.writeFileSync(
    yaml,
    `- name: e2e-sample
  description: smoke
  risk: safe
  platforms: [darwin, linux]
  paths: [/tmp]
  recipe: "echo noop"
`,
  );
  server = spawn("uv", ["run", "diskdoctor", "serve", "--port", "8731", "--no-browser"], {
    cwd: repoRoot,
    env: { ...process.env, DISKDOCTOR_PATHS_YAML: yaml },
    stdio: "inherit",
  });
  for (let i = 0; i < 20; i++) {
    try {
      const res = await fetch("http://127.0.0.1:8731/api/providers");
      if (res.ok) return;
    } catch { /* retry */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("server did not start in time");
});

test.afterAll(() => {
  if (server) server.kill("SIGTERM");
});

test("scan page loads with at least one row", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/caches/i).first()).toBeVisible();
  await expect(page.getByText(/e2e-sample/i)).toBeVisible({ timeout: 5000 });
});

test("providers page renders registered providers", async ({ page }) => {
  await page.goto("/providers");
  await expect(page.getByText(/ollama/).first()).toBeVisible();
  await expect(page.getByText(/docker/).first()).toBeVisible();
});
