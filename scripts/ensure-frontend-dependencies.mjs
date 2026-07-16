import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const frontendDir = join(projectRoot, "frontend");
const frontendRequire = createRequire(join(frontendDir, "package.json"));
const requiredPackages = [
  "next",
  "react",
  "react-dom",
  "react-markdown",
  "rehype-highlight",
  "rehype-raw",
  "rehype-sanitize",
  "remark-breaks",
  "remark-gfm",
];

const missingPackages = requiredPackages.filter((packageName) => {
  try {
    frontendRequire.resolve(packageName);
    return false;
  } catch {
    return true;
  }
});

if (missingPackages.length > 0) {
  console.log(`前端依赖缺失：${missingPackages.join(", ")}，正在按 frontend/package-lock.json 安装。`);
  execFileSync(process.platform === "win32" ? "npm.cmd" : "npm", ["--prefix", "frontend", "ci", "--ignore-scripts"], {
    cwd: projectRoot,
    stdio: "inherit",
  });
}
