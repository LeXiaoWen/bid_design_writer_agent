import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..");
const localElectron = process.platform === "win32"
  ? path.join(projectRoot, "node_modules", ".bin", "electron.cmd")
  : path.join(projectRoot, "node_modules", ".bin", "electron");

const candidates = [
  process.env.ELECTRON_BIN
    ? { command: process.env.ELECTRON_BIN, args: [], cwd: projectRoot, label: "ELECTRON_BIN" }
    : null,
  existsSync(localElectron)
    ? { command: localElectron, args: [], cwd: projectRoot, label: "project electron" }
    : null,
  { command: "npx", args: ["electron"], cwd: os.homedir(), label: "home npx electron" },
].filter(Boolean);

function isRunnable(candidate) {
  const result = spawnSync(candidate.command, [...candidate.args, "-v"], {
    cwd: candidate.cwd,
    env: process.env,
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status === 0) {
    const version = `${result.stdout}${result.stderr}`.trim();
    console.log(`[electron] using ${candidate.label}${version ? ` (${version})` : ""}`);
    return true;
  }
  return false;
}

const selected = candidates.find(isRunnable);

if (!selected) {
  console.error("[electron] No runnable Electron binary found.");
  console.error("[electron] Set ELECTRON_BIN=/path/to/electron or run `cd ~ && npx electron -v` once.");
  process.exit(1);
}

if (process.argv.includes("--check")) {
  process.exit(0);
}

const child = spawn(selected.command, [...selected.args, projectRoot], {
  cwd: selected.cwd,
  env: process.env,
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
