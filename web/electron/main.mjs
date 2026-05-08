import { app, BrowserWindow, Menu, dialog, shell } from "electron";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  FULL_DISK_ACCESS_SETTINGS_URL,
  fullDiskAccessDialogOptions,
} from "./full-disk-access.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const bundledBackendPath = path.join(process.resourcesPath, "backend", backendExecutableName());
const START_TIMEOUT_MS = 30_000;
const HEALTH_INTERVAL_MS = 250;
const BACKEND_STOP_TIMEOUT_MS = 2_000;

let backend = null;
let mainWindow = null;
let backendExitedEarly = false;
let isQuitting = false;
let logStream = null;
let logPath = null;

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    try {
      setupLogging();
      installAppMenu();
      const port = await pickFreePort();
      backend = startBackend(port);
      const url = `http://127.0.0.1:${port}`;
      await waitForHealth(`${url}/api/health`, START_TIMEOUT_MS);
      createWindow(url);
    } catch (error) {
      await dialog.showMessageBox({
        type: "error",
        title: "DevDoctor failed to start",
        message: "DevDoctor could not start its local backend.",
        detail: error instanceof Error ? error.message : String(error),
      });
      app.quit();
    }
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0 && mainWindow) {
    mainWindow.show();
  }
});

app.on("before-quit", () => {
  stopBackend();
  closeLogStream();
});

function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    title: "DevDoctor",
    backgroundColor: "#0d1117",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url: targetUrl }) => {
    void shell.openExternal(targetUrl);
    return { action: "deny" };
  });

  mainWindow.loadURL(url).catch((error) => {
    void dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "DevDoctor failed to load",
      message: "The DevDoctor UI could not load.",
      detail: error instanceof Error ? error.message : String(error),
    });
  });
}

function startBackend(port) {
  const command = backendCommand(port);
  writeLog("electron", `backendCommand=${command.command} ${command.args.join(" ")}${os.EOL}`);

  const child = spawn(command.command, command.args, {
    cwd: command.cwd,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  child.stdout?.on("data", (chunk) => {
    writeLog("backend", chunk);
  });
  child.stderr?.on("data", (chunk) => {
    writeLog("backend", chunk);
  });
  child.on("exit", (code, signal) => {
    backend = null;
    if (isQuitting) return;
    backendExitedEarly = true;
    const detail = `Backend exited with code ${code ?? "null"} and signal ${signal ?? "null"}.`;
    if (!mainWindow) {
      writeLog("electron", `${detail}\n`);
      return;
    }
    void dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "DevDoctor backend stopped",
      message: "The local DevDoctor backend stopped unexpectedly.",
      detail,
    });
  });
  child.on("error", (error) => {
    backendExitedEarly = true;
    writeLog("electron", `Failed to start backend: ${error.message}\n`);
  });

  return child;
}

function stopBackend() {
  isQuitting = true;
  if (!backend || backend.killed) return;
  const child = backend;
  backend.kill("SIGTERM");
  setTimeout(() => {
    if (!child.killed && child.exitCode === null) {
      child.kill("SIGKILL");
    }
  }, BACKEND_STOP_TIMEOUT_MS).unref();
  backend = null;
}

function pickFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (address && typeof address === "object") resolve(address.port);
        else reject(new Error("Could not allocate a local backend port."));
      });
    });
  });
}

async function waitForHealth(url, timeoutMs) {
  const started = Date.now();
  let lastError = null;
  while (Date.now() - started < timeoutMs) {
    if (backendExitedEarly) {
      throw new Error(`Backend process exited before becoming ready.${startupHint()}`);
    }
    try {
      if (await healthOk(url)) return;
    } catch (error) {
      lastError = error;
    }
    await sleep(HEALTH_INTERVAL_MS);
  }
  throw new Error(
    `Timed out waiting for backend health at ${url}.${lastError ? ` Last error: ${lastError.message}` : ""}${startupHint()}`,
  );
}

function healthOk(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: 1_000 }, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on("timeout", () => {
      request.destroy(new Error("Health request timed out."));
    });
    request.on("error", reject);
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function setupLogging() {
  const dir = path.join(app.getPath("userData"), "logs");
  fs.mkdirSync(dir, { recursive: true });
  logPath = path.join(dir, "devdoctor-electron.log");
  logStream = fs.createWriteStream(logPath, { flags: "a" });
  writeLog("electron", `Starting DevDoctor ${new Date().toISOString()}\n`);
  writeLog("electron", `repoRoot=${repoRoot}${os.EOL}`);
}

function closeLogStream() {
  logStream?.end();
  logStream = null;
}

function writeLog(source, chunk) {
  const text = Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk);
  const prefixed = text
    .split(/\r?\n/)
    .filter((line) => line.length > 0)
    .map((line) => `[${source}] ${line}`)
    .join(os.EOL);
  if (!prefixed) return;
  const line = `${prefixed}${os.EOL}`;
  logStream?.write(line);
  if (source === "backend") process.stdout.write(line);
  else process.stderr.write(line);
}

function installAppMenu() {
  const template = [
    {
      label: "DevDoctor",
      submenu: [
        { role: "about" },
        { type: "separator" },
        {
          label: "Open Logs",
          click: () => openLogs(),
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
      ],
    },
    {
      label: "Window",
      submenu: [{ role: "minimize" }, { role: "close" }],
    },
    {
      label: "Help",
      submenu: [
        ...(process.platform === "darwin"
          ? [
              {
                label: "Full Disk Access...",
                click: () => showFullDiskAccessHelp(),
              },
            ]
          : []),
        {
          label: "Open Logs",
          click: () => openLogs(),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function showFullDiskAccessHelp() {
  const options = fullDiskAccessDialogOptions();
  const result = mainWindow
    ? await dialog.showMessageBox(mainWindow, options)
    : await dialog.showMessageBox(options);
  if (result.response === 0) {
    void shell.openExternal(FULL_DISK_ACCESS_SETTINGS_URL);
  }
}

function openLogs() {
  if (!logPath) return;
  void shell.openPath(logPath).then((error) => {
    if (!error) return;
    writeLog("electron", `Failed to open log file: ${error}\n`);
  });
}

function startupHint() {
  if (app.isPackaged) {
    return ` Expected bundled backend at ${bundledBackendPath}. Build the backend executable before packaging.`;
  }
  return " Make sure `uv` is installed and available on PATH, then run `uv run diskdoctor serve --port 0 --no-browser` from the repository to inspect backend startup errors.";
}

function backendCommand(port) {
  const commonArgs = ["serve", "--port", String(port), "--no-browser"];
  if (app.isPackaged) {
    if (!fs.existsSync(bundledBackendPath)) {
      throw new Error(`Bundled backend executable not found at ${bundledBackendPath}.`);
    }
    return {
      command: bundledBackendPath,
      args: commonArgs,
      cwd: path.dirname(bundledBackendPath),
    };
  }
  return {
    command: "uv",
    args: ["run", "diskdoctor", ...commonArgs],
    cwd: repoRoot,
  };
}

function backendExecutableName() {
  return process.platform === "win32" ? "diskdoctor.exe" : "diskdoctor";
}
