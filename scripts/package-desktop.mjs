import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const platformTarget = process.platform === "win32" ? "win" : process.platform === "darwin" ? "mac" : "linux";
const defaultTargets = {
  mac: ["zip", "dmg"],
  win: ["nsis", "zip"],
  linux: ["AppImage", "tar.gz"],
};

function command(name) {
  return process.platform === "win32" ? `${name}.cmd` : name;
}

function run(cmd, args, env = process.env) {
  // 仅 .cmd/.bat 文件需要 shell；直接使用 .exe 时开启 shell 会导致
  // "C:\Program Files\..." 等含空格路径被错误截断
  const needsShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(cmd);
  const result = spawnSync(cmd, args, {
    cwd: projectRoot,
    stdio: "inherit",
    shell: needsShell,
    env,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function readOptions(argv) {
  const options = {
    target: platformTarget,
    dir: false,
    targets: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--target") {
      options.target = argv[index + 1] ?? options.target;
      index += 1;
    } else if (arg === "--dir") {
      options.dir = true;
    } else if (arg === "--targets") {
      const value = argv[index + 1] ?? "";
      options.targets = value.split(",").map((item) => item.trim()).filter(Boolean);
      index += 1;
    } else {
      throw new Error(`未知打包参数：${arg}`);
    }
  }

  if (!["mac", "win", "linux"].includes(options.target)) {
    throw new Error(`不支持的打包平台：${options.target}`);
  }
  return options;
}

function assertHostPlatform(target) {
  const expected = target === "mac" ? "darwin" : target === "win" ? "win32" : "linux";
  if (process.platform === expected || process.env.ALLOW_CROSS_PLATFORM_PACKAGE === "true") return;

  throw new Error(
    [
      `当前系统是 ${process.platform}，不能直接打 ${target} 包。`,
      "本项目后端 agent 由 PyInstaller 生成，必须在目标系统上构建对应平台可执行文件。",
      "如确需 Electron 交叉打包外壳，可设置 ALLOW_CROSS_PLATFORM_PACKAGE=true，但生成的后端 agent 仍不会跨平台可用。",
    ].join("\n"),
  );
}

try {
  const options = readOptions(process.argv.slice(2));
  assertHostPlatform(options.target);

  const targets = options.dir ? [] : options.targets.length > 0 ? options.targets : defaultTargets[options.target];
  const builderArgs = [`--${options.target}`, ...targets];
  if (options.dir) builderArgs.push("--dir");

  // 当 release 目录被遗留锁定文件占用时，使用隔离配置切换到临时输出目录
  const tempConfig = join(projectRoot, "electron-builder-temp.yml");
  if (existsSync(tempConfig)) {
    builderArgs.push("--config", tempConfig);
  }

  run(process.execPath, ["scripts/sync-version.mjs"]);
  run(command("npm"), ["run", "build"]);
  run(command("npm"), ["run", "build:agent"]);
  run(process.execPath, ["scripts/run-electron-builder.mjs", ...builderArgs]);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
