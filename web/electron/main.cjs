const { app, BrowserWindow, ipcMain } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const steam = require("./steam.cjs");

const repoRoot = path.resolve(__dirname, "..", "..");
const host = "127.0.0.1";

let backend = null;
let mainWindow = null;

const log = (...args) => console.log("[electron]", ...args);
const warn = (...args) => console.warn("[electron]", ...args);

const readDotEnv = (filePath) => {
  if (!fs.existsSync(filePath)) return {};
  const env = {};
  for (const line of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const index = trimmed.indexOf("=");
    const key = trimmed.slice(0, index).trim();
    let value = trimmed.slice(index + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (key) env[key] = value;
  }
  return env;
};

const findOpenPort = () =>
  new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });

const waitForBackend = (port, timeoutMs = 45000) => {
  const startedAt = Date.now();
  const urlPath = "/api/menu/status";
  return new Promise((resolve, reject) => {
    const tick = () => {
      const request = http.get({ host, port, path: urlPath, timeout: 1500 }, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      request.on("timeout", () => {
        request.destroy(new Error("timeout"));
      });
      request.on("error", retry);
    };

    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error(`FastAPI did not become ready on ${host}:${port}`));
        return;
      }
      setTimeout(tick, 300);
    };

    tick();
  });
};

const pythonExecutable = () => {
  const venvPython = path.join(repoRoot, ".venv", os.platform() === "win32" ? "Scripts/python.exe" : "bin/python");
  if (fs.existsSync(venvPython)) return venvPython;
  return os.platform() === "win32" ? "python" : "python3";
};

const startBackend = async () => {
  const port = await findOpenPort();
  const dotenv = readDotEnv(path.join(repoRoot, ".env"));
  const env = {
    ...process.env,
    ...dotenv,
    MING_SIM_DUMP_LLM: process.env.MING_SIM_DUMP_LLM || dotenv.MING_SIM_DUMP_LLM || "1",
    MING_SIM_ELECTRON: "1",
    MING_SIM_USER_DATA_DIR: path.join(app.getPath("userData"), "python-data"),
    PYTHONUNBUFFERED: "1",
  };

  backend = spawn(pythonExecutable(), ["-m", "uvicorn", "web_app:app", "--host", host, "--port", String(port)], {
    cwd: repoRoot,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  backend.stdout.on("data", (chunk) => process.stdout.write(`[fastapi] ${chunk}`));
  backend.stderr.on("data", (chunk) => process.stderr.write(`[fastapi] ${chunk}`));
  backend.on("exit", (code, signal) => {
    log(`FastAPI exited code=${code ?? "null"} signal=${signal ?? "null"}`);
    backend = null;
    if (!app.isQuitting) app.quit();
  });

  await waitForBackend(port);
  log(`FastAPI ready at http://${host}:${port}`);
  return port;
};

const stopBackend = () => {
  if (!backend) return;
  const child = backend;
  backend = null;
  if (child.killed) return;
  if (os.platform() === "win32") {
    spawn("taskkill", ["/pid", String(child.pid), "/f", "/t"]);
  } else {
    child.kill("SIGTERM");
    setTimeout(() => {
      if (!child.killed) child.kill("SIGKILL");
    }, 3000).unref();
  }
};

const registerSteamIpc = () => {
  ipcMain.handle("steam:getStatus", () => steam.getStatus());
  ipcMain.handle("steam:getAuthTicket", (_event, identity) => steam.getAuthTicket(identity));
  ipcMain.handle("steam:cancelAuthTicket", (_event, ticketId) => steam.cancelAuthTicket(ticketId));
  ipcMain.handle("steam:authenticateWithServer", (_event, options) => steam.authenticateWithServer(options));
  ipcMain.handle("steam:addStatInt", (_event, name, delta) => steam.addStatInt(name, delta));
  ipcMain.handle("steam:setStatInt", (_event, name, value) => steam.setStatInt(name, value));
  ipcMain.handle("steam:flushStats", () => steam.flushStats());
};

const createWindow = async (port) => {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: "#160f0a",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  await mainWindow.loadURL(`http://${host}:${port}`);
};

app.whenReady().then(async () => {
  registerSteamIpc();
  const status = steam.getStatus();
  if (status.available) {
    log(`Steam user ${status.personaName || "(unknown)"} appId=${status.appId}`);
  } else {
    warn(`Steam unavailable: ${status.error || "unknown error"}`);
  }

  try {
    const port = await startBackend();
    await createWindow(port);
  } catch (error) {
    warn(error instanceof Error ? error.stack || error.message : String(error));
    stopBackend();
    app.quit();
  }
});

app.on("before-quit", () => {
  app.isQuitting = true;
  stopBackend();
});

app.on("window-all-closed", () => {
  app.quit();
});
