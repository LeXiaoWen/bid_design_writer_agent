import { spawnSync } from "node:child_process";
import { cpSync, existsSync, rmSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDir, "..");
const venvDir = join(projectRoot, ".agent-venv");
const requirementsFile = join(projectRoot, "backend", "requirements-agent.txt");
const specFile = join(projectRoot, "packaging", "agent.spec");
const agentOutputDir = join(projectRoot, ".agent-dist", "ai-workbench-agent");
const pythonCandidates = process.platform === "win32" ? ["py", "python"] : ["python3", "python"];

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    stdio: "inherit",
    // 所有命令均为 Python 可执行文件（.exe 或 py/python 命令名），无需 shell
    shell: false,
    windowsHide: true,
    ...options,
  });

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function findPython() {
  for (const candidate of pythonCandidates) {
    const args = candidate === "py" ? ["-3", "--version"] : ["--version"];
    const result = spawnSync(candidate, args, { stdio: "ignore", shell: false });
    if (result.status === 0) {
      return candidate;
    }
  }
  throw new Error("未找到 Python。请先安装 Python 3.10+。");
}

function venvPythonPath() {
  return process.platform === "win32"
    ? join(venvDir, "Scripts", "python.exe")
    : join(venvDir, "bin", "python");
}

function venvExecutablePath(name) {
  return process.platform === "win32"
    ? join(venvDir, "Scripts", `${name}.exe`)
    : join(venvDir, "bin", name);
}

const python = findPython();

if (!existsSync(venvPythonPath())) {
  console.log("Creating backend packaging virtualenv...");
  const args = python === "py" ? ["-3", "-m", "venv", venvDir] : ["-m", "venv", venvDir];
  run(python, args);
}

const venvPython = venvPythonPath();

function readDocConverterConfig() {
  const source = process.env.DOC_CONVERTER_DIR?.trim();
  const executable = process.env.DOC_CONVERTER_EXECUTABLE?.trim();
  if (!source || !executable) {
    if (process.env.REQUIRE_DOC_CONVERTER === "true") {
      throw new Error("正式打包必须设置 DOC_CONVERTER_DIR 与 DOC_CONVERTER_EXECUTABLE，以随应用分发 LibreOffice headless 转换组件。");
    }
    console.warn("Skipping bundled DOC converter. Development mode will use an available system converter.");
    return null;
  }
  if (isAbsolute(executable) || executable.split(/[\\/]/).includes("..")) {
    throw new Error("DOC_CONVERTER_EXECUTABLE 必须是相对于 DOC_CONVERTER_DIR 的安全路径。");
  }
  const sourceDir = resolve(source);
  const executablePath = resolve(sourceDir, executable);
  if (!existsSync(executablePath)) {
    throw new Error(`未找到 DOC 转换器可执行文件：${executablePath}`);
  }
  return { executable, sourceDir };
}

function stageDocConverter(config) {
  if (!config) return;
  const { executable, sourceDir } = config;
  const targetDir = join(agentOutputDir, "doc-converter");
  rmSync(targetDir, { recursive: true, force: true });
  cpSync(sourceDir, targetDir, { recursive: true });
  writeFileSync(join(targetDir, "converter.json"), `${JSON.stringify({ executable })}\n`, "utf8");
}

const docConverter = readDocConverterConfig();

console.log("Installing backend packaging dependencies...");
run(venvPython, ["-m", "pip", "install", "--upgrade", "pip"]);
run(venvPython, ["-m", "pip", "install", "-r", requirementsFile]);
run(venvExecutablePath("rapidocr"), ["download_models"]);

console.log("Building packaged backend agent...");
rmSync(agentOutputDir, { recursive: true, force: true });
run(venvPython, [
  "-m",
  "PyInstaller",
  specFile,
  "--distpath",
  ".agent-dist",
  "--workpath",
  ".agent-build",
  "--noconfirm",
]);
stageDocConverter(docConverter);
