import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/**
 * The hermetic home the e2e server runs under.
 *
 * `serve.ts` builds it and starts `devdoctor serve` with every knob devdoctor
 * reads (HOME, XDG dirs, project roots, the YAML path providers) pointed into
 * it, so a scan never touches the developer's machine and the snapshots the
 * tests write land here. It holds one YAML cache of a known size and one node
 * project with a lockfile, so a scan yields a safe row and a reclaimable row in
 * seconds. The specs read the same layout through `fixtureEnv()`.
 */
export const ENV_FILE = path.join(os.tmpdir(), "devdoctor-e2e-env.json");
export const PORT = 8731;
export const CACHE_LABEL = "e2e-sample-cache";
export const PROJECT_NAME = "e2e-app";
export const CACHE_BYTES = 300_000;
export const NODE_MODULES_BYTES = 200_000;

export interface FixtureEnv {
  HOME: string;
  XDG_DATA_HOME: string;
  XDG_CONFIG_HOME: string;
  DEVDOCTOR_PROJECT_ROOTS: string;
  DEVDOCTOR_PATHS_YAML: string;
  DEVDOCTOR_E2E_ROOT: string;
}

export function buildFixture(): FixtureEnv {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "devdoctor-e2e-"));
  const home = path.join(root, "home");
  const projects = path.join(root, "projects");
  const cache = path.join(root, "cache");
  fs.mkdirSync(home, { recursive: true });
  fs.mkdirSync(cache, { recursive: true });
  fs.writeFileSync(path.join(cache, "blob.bin"), Buffer.alloc(CACHE_BYTES, 1));

  const project = path.join(projects, PROJECT_NAME);
  fs.mkdirSync(path.join(project, "node_modules", "pkg"), { recursive: true });
  fs.writeFileSync(path.join(project, "package.json"), "{}\n");
  fs.writeFileSync(path.join(project, "package-lock.json"), "{}\n");
  fs.writeFileSync(
    path.join(project, "node_modules", "pkg", "index.js"),
    Buffer.alloc(NODE_MODULES_BYTES, 2),
  );

  const yaml = path.join(root, "paths.yaml");
  fs.writeFileSync(
    yaml,
    `- name: ${CACHE_LABEL}
  description: e2e fixture cache
  risk: safe
  platforms: [darwin, linux]
  paths: [${cache}]
  recipe: "rm -rf {path}"
`,
  );

  const env: FixtureEnv = {
    HOME: home,
    XDG_DATA_HOME: path.join(home, ".local", "share"),
    XDG_CONFIG_HOME: path.join(home, ".config"),
    DEVDOCTOR_PROJECT_ROOTS: projects,
    DEVDOCTOR_PATHS_YAML: yaml,
    DEVDOCTOR_E2E_ROOT: root,
  };
  fs.writeFileSync(ENV_FILE, JSON.stringify(env));
  return env;
}

export function fixtureEnv(): FixtureEnv {
  return JSON.parse(fs.readFileSync(ENV_FILE, "utf8")) as FixtureEnv;
}

export function cachePath(): string {
  return path.join(fixtureEnv().DEVDOCTOR_E2E_ROOT, "cache", "blob.bin");
}

export function nodeModulesPath(): string {
  return path.join(fixtureEnv().DEVDOCTOR_PROJECT_ROOTS, PROJECT_NAME, "node_modules");
}

export function autoSnapshots(): string[] {
  const dir = path.join(fixtureEnv().XDG_DATA_HOME, "devdoctor", "snapshots");
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((name) => name.endsWith("--auto.json")).sort();
}
