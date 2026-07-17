import { app, BrowserWindow, dialog, ipcMain, net, protocol, shell } from "electron";
import { spawn, ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes } from "node:crypto";
import { accessSync, constants, existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:3000";
let backendUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8765";
const APP_AUTH_SECRET = process.env.APP_AUTH_SECRET ?? randomBytes(32).toString("base64url");
const BACKEND_READY_TIMEOUT_MS = 30_000;
const BACKEND_READY_INTERVAL_MS = 300;
const BACKEND_SHUTDOWN_GRACE_MS = 1_500;
const PACKAGED_FRONTEND_CSP = [
  "default-src 'self'",
  "base-uri 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:* http://localhost:*",
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  "form-action 'self'",
].join("; ");
let backendProcess: ChildProcessWithoutNullStreams | null = null;
let backendStartPromise: Promise<void> | null = null;
let mainWindow: BrowserWindow | null = null;

protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);

ipcMain.handle("workspace:select-directory", async () => {
  const result = await dialog.showOpenDialog({
    title: "选择项目工作目录",
    properties: ["openDirectory", "createDirectory"],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  const folderPath = result.filePaths[0];
  return {
    name: path.basename(folderPath),
    path: folderPath,
  };
});

ipcMain.handle("auth:get-app-secret", async () => APP_AUTH_SECRET);
ipcMain.handle("backend:get-url", async () => backendUrl);

async function backendIsReady(): Promise<boolean> {
  try {
    const response = await fetch(`${backendUrl}/health`);
    if (!response.ok) return false;
    const payload = await response.json();
    return payload?.app === "ai-workbench-desktop";
  } catch {
    return false;
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isSafeExternalUrl(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

async function waitForBackendReady(): Promise<void> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < BACKEND_READY_TIMEOUT_MS) {
    if (await backendIsReady()) return;
    await delay(BACKEND_READY_INTERVAL_MS);
  }
  throw new Error(`本地后端启动超时：${backendUrl}`);
}

function executableFileExists(filePath: string): boolean {
  try {
    const stat = statSync(filePath);
    if (!stat.isFile()) return false;
    // Windows 没有 POSIX 可执行权限位，X_OK 检查行为不确定，只校验是否为 .exe
    if (process.platform === "win32") {
      return filePath.toLowerCase().endsWith(".exe");
    }
    accessSync(filePath, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function parseEnvFile(filePath: string): Record<string, string> {
  if (!existsSync(filePath)) return {};
  const parsed: Record<string, string> = {};
  const content = readFileSync(filePath, "utf8");
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separatorIndex = line.indexOf("=");
    if (separatorIndex <= 0) continue;
    const key = line.slice(0, separatorIndex).trim();
    let value = line.slice(separatorIndex + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    parsed[key] = value;
  }
  return parsed;
}

function loadEnvFiles(): Record<string, string> {
  const candidates = [
    path.resolve(__dirname, "..", ".env"),
    path.join(process.cwd(), ".env"),
    path.join(process.resourcesPath, ".env"),
    path.join(app.getPath("userData"), ".env"),
  ];
  const env: Record<string, string> = {};
  for (const filePath of [...new Set(candidates)]) {
    Object.assign(env, parseEnvFile(filePath));
  }
  return env;
}

function startBackend(): Promise<void> {
  if (backendProcess) return Promise.resolve();
  const dataDir = path.join(app.getPath("userData"), "data");
  const packagedAgentName = process.platform === "win32" ? "ai-workbench-agent.exe" : "ai-workbench-agent";
  const packagedAgentCandidates = [
    path.join(process.resourcesPath, "agent", "ai-workbench-agent", packagedAgentName),
    path.join(process.resourcesPath, "agent", packagedAgentName),
  ];
  const packagedAgentPath = packagedAgentCandidates.find((candidate) => executableFileExists(candidate));
  const env = {
    ...loadEnvFiles(),
    ...process.env,
    APP_AUTH_SECRET,
    AGENT_HOST: "127.0.0.1",
    AGENT_PORT: "0",
    AI_WORKBENCH_DATA_DIR: dataDir,
    FRONTEND_ORIGINS: process.env.FRONTEND_ORIGINS ?? "http://localhost:3000,http://127.0.0.1:3000,app://frontend,null",
  };

  if (app.isPackaged && packagedAgentPath) {
    backendProcess = spawn(packagedAgentPath, [], {
      detached: process.platform !== "win32",
      env,
      windowsHide: true,
    });
  } else {
    const pythonCmd = process.platform === "win32" ? "python" : "python3";
    const projectRoot = path.resolve(__dirname, "..");
    backendProcess = spawn(pythonCmd, ["-m", "backend.server"], {
      cwd: projectRoot,
      detached: process.platform !== "win32",
      env,
    });
  }
  return new Promise((resolve, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("本地后端启动超时。")), BACKEND_READY_TIMEOUT_MS);
    backendProcess!.stdout.on("data", (data) => {
      const text = String(data);
      output += text;
      console.log(`[backend] ${text}`);
      const match = output.match(/AI_WORKBENCH_BACKEND_READY=(\d+)/);
      if (match) {
        clearTimeout(timeout);
        backendUrl = `http://127.0.0.1:${match[1]}`;
        void waitForBackendReady().then(resolve, reject);
      }
      output = output.slice(-4096);
    });
    backendProcess!.stderr.on("data", (data) => console.error(`[backend] ${data}`));
    backendProcess!.on("error", (error) => {
      clearTimeout(timeout);
      backendProcess = null;
      reject(error);
    });
    backendProcess!.on("exit", (code) => {
      backendProcess = null;
      clearTimeout(timeout);
      if (!output.includes("AI_WORKBENCH_BACKEND_READY=")) {
        reject(new Error(`本地后端启动失败（退出码 ${code ?? "未知"}）。`));
      }
    });
  });
}

function stopBackend(): void {
  const processToStop = backendProcess;
  if (!processToStop?.pid) return;
  const pid = processToStop.pid;
  backendProcess = null;

  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
    return;
  }

  try {
    process.kill(-pid, "SIGTERM");
  } catch {
    try {
      processToStop.kill("SIGTERM");
    } catch {
      return;
    }
  }

  setTimeout(() => {
    try {
      process.kill(-pid, "SIGKILL");
    } catch {
      // Process tree already exited.
    }
  }, BACKEND_SHUTDOWN_GRACE_MS).unref();
}

function registerPackagedFrontendProtocol(): void {
  if (!app.isPackaged) return;

  const frontendRoot = path.join(process.resourcesPath, "frontend");
  protocol.handle("app", async (request) => {
    const url = new URL(request.url);
    if (url.hostname !== "frontend") {
      return new Response("Not found", { status: 404 });
    }

    const rawPathname = decodeURIComponent(url.pathname);
    const pathname = rawPathname === "/" ? "/index.html" : rawPathname;
    const filePath = path.normalize(path.join(frontendRoot, pathname));
    const rootWithSeparator = `${path.normalize(frontendRoot)}${path.sep}`;

    if (filePath !== frontendRoot && !filePath.startsWith(rootWithSeparator)) {
      return new Response("Forbidden", { status: 403 });
    }

    const response = await net.fetch(pathToFileURL(filePath).toString());
    const headers = new Headers(response.headers);
    headers.set("Content-Security-Policy", PACKAGED_FRONTEND_CSP);
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  });
}

async function prepareBackend(): Promise<void> {
  if (backendStartPromise) return backendStartPromise;
  backendStartPromise = (async () => {
    await startBackend();
  })();
  return backendStartPromise;
}

async function createWindow(): Promise<void> {
  await prepareBackend();
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1180,
    minHeight: 760,
    title: "建筑设计标书方案助手",
    backgroundColor: "#f6f7f2",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) {
      void shell.openExternal(url).catch((error) => console.error("[desktop] failed to open external URL", error));
    }
    return { action: "deny" };
  });

  const packagedFrontend = path.join(process.resourcesPath, "frontend", "index.html");
  if (app.isPackaged && existsSync(packagedFrontend)) {
    await mainWindow.loadURL("app://frontend/index.html");
  } else {
    await mainWindow.loadURL(FRONTEND_URL);
  }
}

app.whenReady().then(() => {
  registerPackagedFrontendProtocol();
  createWindow().catch((error) => {
    console.error("[desktop] failed to create window", error);
  });
});

app.on("window-all-closed", () => {
  app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow().catch((error) => {
      console.error("[desktop] failed to create window", error);
    });
  }
});

app.on("before-quit", () => {
  stopBackend();
});

app.on("will-quit", () => {
  stopBackend();
});
