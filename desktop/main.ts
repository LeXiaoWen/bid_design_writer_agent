import { app, BrowserWindow, dialog, ipcMain, net, protocol, shell } from "electron";
import { spawn, ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes } from "node:crypto";
import { accessSync, constants, existsSync, statSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { pathToFileURL } from "node:url";

const FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:3000";
let backendUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8765";
const APP_AUTH_SECRET = process.env.APP_AUTH_SECRET ?? randomBytes(32).toString("base64url");
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

function findAvailablePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (address && typeof address === "object") {
          resolve(address.port);
        } else {
          reject(new Error("无法分配本地后端端口。"));
        }
      });
    });
  });
}

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

function backendPort(): string {
  return new URL(backendUrl).port || "80";
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

function startBackend(): void {
  if (backendProcess) return;
  const dataDir = path.join(app.getPath("userData"), "data");
  const packagedAgentName = process.platform === "win32" ? "ai-workbench-agent.exe" : "ai-workbench-agent";
  const packagedAgentCandidates = [
    path.join(process.resourcesPath, "agent", "ai-workbench-agent", packagedAgentName),
    path.join(process.resourcesPath, "agent", packagedAgentName),
  ];
  const packagedAgentPath = packagedAgentCandidates.find((candidate) => executableFileExists(candidate));
  const env = {
    ...process.env,
    APP_AUTH_SECRET,
    AGENT_PORT: backendPort(),
    AI_WORKBENCH_DATA_DIR: dataDir,
    FRONTEND_ORIGINS: process.env.FRONTEND_ORIGINS ?? "http://localhost:3000,http://127.0.0.1:3000,app://frontend,null",
  };

  if (app.isPackaged && packagedAgentPath) {
    backendProcess = spawn(packagedAgentPath, [], { env });
  } else {
    const pythonCmd = process.platform === "win32" ? "python" : "python3";
    // packaged 模式下使用 app.getAppPath() 避免 ASAR 虚拟路径传给 spawn cwd
    const projectRoot = app.isPackaged
      ? path.dirname(app.getAppPath())
      : path.resolve(__dirname, "..");
    backendProcess = spawn(pythonCmd, ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", backendPort()], {
      cwd: projectRoot,
      env,
    });
  }
  backendProcess.stdout.on("data", (data) => console.log(`[backend] ${data}`));
  backendProcess.stderr.on("data", (data) => console.error(`[backend] ${data}`));
  backendProcess.on("error", (error) => {
    console.error("[backend] failed to start", error);
    backendProcess = null;
  });
  backendProcess.on("exit", () => {
    backendProcess = null;
  });
}

function registerPackagedFrontendProtocol(): void {
  if (!app.isPackaged) return;

  const frontendRoot = path.join(process.resourcesPath, "frontend");
  protocol.handle("app", (request) => {
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

    return net.fetch(pathToFileURL(filePath).toString());
  });
}

async function prepareBackend(): Promise<void> {
  if (backendStartPromise) return backendStartPromise;
  backendStartPromise = (async () => {
    if (await backendIsReady()) return;
    const port = await findAvailablePort();
    backendUrl = `http://127.0.0.1:${port}`;
    startBackend();
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
    },
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
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
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow().catch((error) => {
      console.error("[desktop] failed to create window", error);
    });
  }
});

app.on("before-quit", () => {
  backendProcess?.kill();
});
