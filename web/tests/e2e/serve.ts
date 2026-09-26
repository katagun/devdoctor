/**
 * Playwright's web server: build the hermetic fixture, then run `devdoctor serve`
 * under it. Runs as a child of Playwright, which stops it when the run ends.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PORT, buildFixture, envFile } from "./fixture";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const env = buildFixture();

// Providers that shell out (ollama, docker, xcrun, ...) probe PATH, so the
// server sees a PATH holding only the system tools the memory page reads. The
// tool-cache variables are dropped for the same reason: left in place they
// would point providers at the developer's real caches.
const bin = path.join(env.DEVDOCTOR_E2E_ROOT, "bin");
fs.mkdirSync(bin);
for (const tool of ["ps", "sysctl", "vm_stat"]) {
  const found = Bun.which(tool);
  if (found !== null) fs.symlinkSync(found, path.join(bin, tool));
}
// With no `docker` on PATH the docker provider falls back to Docker Desktop's CLI
// at a fixed path, which reaches a real daemon; the empty value turns that off.
const serverEnv: NodeJS.ProcessEnv = {
  ...process.env,
  ...env,
  PATH: bin,
  DEVDOCTOR_DOCKER_BUNDLED_CLI: "",
};
// UV_CACHE_DIR names a real cache on CI runners and UV marks a parent uv process;
// both would let the uv-cache provider see past the fixture home.
for (const name of [
  "CARGO_HOME",
  "ANDROID_HOME",
  "ANDROID_SDK_ROOT",
  "ANDROID_AVD_HOME",
  "UV_CACHE_DIR",
  "UV",
]) {
  delete serverEnv[name];
}

// The venv's entry point rather than `uv run`: under the fixture HOME, uv would
// look for its cache and managed interpreters in the wrong place.
const devdoctor = path.join(repoRoot, ".venv", "bin", "devdoctor");
if (!fs.existsSync(devdoctor)) {
  throw new Error(`${devdoctor} is missing; run \`uv sync --extra web\` first`);
}

const server = spawn(devdoctor, ["serve", "--port", String(PORT), "--no-browser"], {
  cwd: repoRoot,
  env: serverEnv,
  stdio: "inherit",
});

function cleanup(): void {
  if (server.exitCode === null) server.kill("SIGTERM");
  fs.rmSync(env.DEVDOCTOR_E2E_ROOT, { recursive: true, force: true });
  fs.rmSync(envFile(), { force: true });
}
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    cleanup();
    process.exit(0);
  });
}
server.on("exit", (code) => {
  cleanup();
  process.exit(code ?? 1);
});
