import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(__dirname, "..");
const backendName = process.platform === "win32" ? "devdoctor.exe" : "devdoctor";
const backendPath = path.join(webRoot, "dist-backend", backendName);

if (!fs.existsSync(backendPath)) {
  console.error(`Missing bundled backend executable: ${backendPath}`);
  console.error("Build the standalone backend first, then place it in web/dist-backend/.");
  process.exit(1);
}

try {
  fs.accessSync(backendPath, fs.constants.X_OK);
} catch {
  console.error(`Bundled backend is not executable: ${backendPath}`);
  console.error(`Run: chmod +x ${backendPath}`);
  process.exit(1);
}
