import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const checkOnly = process.argv.slice(2).includes("--check");
const semverPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function writeJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

const rootPackagePath = join(projectRoot, "package.json");
const rootPackage = readJson(rootPackagePath);
const version = rootPackage.version;

if (typeof version !== "string" || !semverPattern.test(version)) {
  throw new Error(`根 package.json 的 version 必须是 SemVer：${String(version)}`);
}

const targets = [
  join(projectRoot, "package-lock.json"),
  join(projectRoot, "frontend", "package.json"),
  join(projectRoot, "frontend", "package-lock.json"),
];

const outOfSync = [];
for (const target of targets) {
  const content = readJson(target);
  const rootPackageEntry = content.packages?.[""];
  const mismatched = content.version !== version || (rootPackageEntry && rootPackageEntry.version !== version);

  if (!mismatched) continue;
  outOfSync.push(target);
  if (checkOnly) continue;

  content.version = version;
  if (rootPackageEntry) rootPackageEntry.version = version;
  writeJson(target, content);
}

if (outOfSync.length === 0) {
  console.log(`版本已同步：${version}`);
} else if (checkOnly) {
  console.error(`版本未同步为 ${version}：\n${outOfSync.map((path) => `- ${path}`).join("\n")}`);
  process.exitCode = 1;
} else {
  console.log(`已同步版本 ${version}：\n${outOfSync.map((path) => `- ${path}`).join("\n")}`);
}
