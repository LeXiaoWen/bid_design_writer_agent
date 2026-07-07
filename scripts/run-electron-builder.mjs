import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, delimiter } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");

// 直接用 node.exe 全路径运行 electron-builder 的 cli.js，绕过 .cmd 包装器。
// 避免 Node.js 安装在含空格路径（如 C:\Program Files\nodejs\）时 spawn .cmd 解析失败。
const cliEntry = join(projectRoot, "node_modules", "electron-builder", "cli", "cli.js");

// 创建 .local-bin/node.bat 代理，前置到 PATH 作为 electron-builder 内部 spawn node 的 fallback
const localBinDir = join(projectRoot, ".local-bin");
if (!existsSync(localBinDir)) {
  mkdirSync(localBinDir, { recursive: true });
}
const nodeBat = join(localBinDir, "node.bat");
if (!existsSync(nodeBat)) {
  writeFileSync(nodeBat, `@"${process.execPath}" %*`, "utf8");
}

const env = {
  ...process.env,
  ELECTRON_MIRROR: process.env.ELECTRON_MIRROR || "https://npmmirror.com/mirrors/electron/",
  PATH: `${localBinDir}${delimiter}${process.env.PATH || ""}`,
};

const result = spawnSync(process.execPath, [cliEntry, ...process.argv.slice(2)], {
  cwd: projectRoot,
  env,
  stdio: "inherit",
  shell: false,
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
