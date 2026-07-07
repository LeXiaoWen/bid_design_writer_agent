import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const builderBin = process.platform === "win32"
  ? join(projectRoot, "node_modules", ".bin", "electron-builder.cmd")
  : join(projectRoot, "node_modules", ".bin", "electron-builder");

const env = {
  ...process.env,
  ELECTRON_MIRROR: process.env.ELECTRON_MIRROR || "https://npmmirror.com/mirrors/electron/",
};

const result = spawnSync(builderBin, process.argv.slice(2), {
  cwd: projectRoot,
  env,
  stdio: "inherit",
  shell: false,
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
