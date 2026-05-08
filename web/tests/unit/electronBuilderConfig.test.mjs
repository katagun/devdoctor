import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(__dirname, "../..");

describe("electron builder config", () => {
  it("uses the DevDoctor macOS icon", () => {
    const config = JSON.parse(
      fs.readFileSync(path.join(WEB_ROOT, "electron-builder.json"), "utf8"),
    );
    const iconPath = path.join(WEB_ROOT, config.mac.icon);

    expect(config.mac.icon).toBe("assets/devdoctor.icns");
    expect(fs.existsSync(iconPath)).toBe(true);
  });
});
