import { spawn, spawnSync } from "node:child_process";
import { accessSync, constants, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const scriptDir = resolve(fileURLToPath(new URL(".", import.meta.url)));
const projectRoot = resolve(scriptDir, "..");
const packageJson = JSON.parse(readFileSync(join(projectRoot, "package.json"), "utf8"));
const appArgument = process.argv.indexOf("--app");

if (process.platform !== "darwin") {
  throw new Error("当前冒烟脚本验证 macOS unpacked 应用；请在目标平台提供对应脚本。");
}

const appPath = resolve(
  appArgument >= 0 && process.argv[appArgument + 1]
    ? process.argv[appArgument + 1]
    : process.env.SMOKE_APP_PATH || join(projectRoot, "release", "mac", `${packageJson.build.productName}.app`),
);
const resourcesPath = join(appPath, "Contents", "Resources");
const agentPath = join(resourcesPath, "agent", "ai-workbench-agent", "ai-workbench-agent");
const converterRoot = join(resourcesPath, "agent", "ai-workbench-agent", "doc-converter");
const converterManifest = join(converterRoot, "converter.json");

function requireFile(filePath, executable = false) {
  if (!existsSync(filePath)) throw new Error(`缺少打包资源：${filePath}`);
  if (executable) accessSync(filePath, constants.X_OK);
}

function bundledConverterPath() {
  requireFile(converterManifest);
  const { executable } = JSON.parse(readFileSync(converterManifest, "utf8"));
  if (typeof executable !== "string" || !executable) throw new Error("DOC 转换器清单无效。");
  const converterPath = resolve(converterRoot, executable);
  if (relative(converterRoot, converterPath).startsWith("..")) throw new Error("DOC 转换器路径越出资源目录。");
  requireFile(converterPath, true);
  return converterPath;
}

function runCommand(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: null, maxBuffer: 32 * 1024 * 1024, ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} 执行失败：${Buffer.from(result.stderr || []).toString("utf8")}`);
  }
  return result.stdout || Buffer.alloc(0);
}

const GLYPHS = {
  " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
  O: ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
  C: ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
  R: ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
  T: ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
  E: ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
  N: ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
  D: ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
  0: ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
  2: ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
  6: ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
};

function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) {
    value ^= byte;
    for (let index = 0; index < 8; index += 1) value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0);
  }
  return (value ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const name = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([length, name, data, checksum]);
}

function writeScannedPng(filePath, text) {
  const width = 1600;
  const height = 400;
  const scale = 16;
  const stride = width * 3 + 1;
  const pixels = Buffer.alloc(stride * height, 0xff);
  for (let y = 0; y < height; y += 1) pixels[y * stride] = 0;
  const drawPixel = (x, y) => {
    const offset = y * stride + 1 + x * 3;
    pixels[offset] = 0;
    pixels[offset + 1] = 0;
    pixels[offset + 2] = 0;
  };
  [...text].forEach((character, characterIndex) => {
    const glyph = GLYPHS[character];
    if (!glyph) throw new Error(`扫描 PDF 样本文字不支持：${character}`);
    glyph.forEach((row, rowIndex) => {
      [...row].forEach((bit, columnIndex) => {
        if (bit !== "1") return;
        for (let y = 0; y < scale; y += 1) {
          for (let x = 0; x < scale; x += 1) drawPixel(80 + (characterIndex * 6 + columnIndex) * scale + x, 140 + rowIndex * scale + y);
        }
      });
    });
  });
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  writeFileSync(filePath, Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), pngChunk("IHDR", header), pngChunk("IDAT", deflateSync(pixels)), pngChunk("IEND", Buffer.alloc(0))]));
}

function createDocumentFixtures(root, converterPath) {
  const legacyMarker = "LEGACY DOC TENDER 2026";
  const ocrMarker = "OCR TENDER 2026";
  const rtfPath = join(root, "legacy.rtf");
  const docPath = join(root, "legacy.doc");
  const pngPath = join(root, "scanned.png");
  const pdfPath = join(root, "scanned.pdf");
  writeFileSync(rtfPath, `{\\rtf1\\ansi\\fs36 ${legacyMarker}}`, "utf8");
  runCommand(converterPath, ["--headless", "--convert-to", "doc:MS Word 97", "--outdir", root, rtfPath], {
    env: { ...process.env, HOME: root },
  });
  if (!readFileSync(docPath).subarray(0, 8).equals(Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]))) {
    throw new Error("未生成有效的旧版 DOC 样本。");
  }

  writeScannedPng(pngPath, ocrMarker);
  writeFileSync(pdfPath, runCommand("/usr/sbin/cupsfilter", ["-i", "image/png", "-m", "application/pdf", pngPath]));
  const pdf = readFileSync(pdfPath);
  if (!pdf.subarray(0, 5).equals(Buffer.from("%PDF-")) || pdf.includes(Buffer.from(ocrMarker))) {
    throw new Error("未生成纯图像扫描 PDF 样本。");
  }
  return { docPath, legacyMarker, ocrMarker, pdfPath };
}

async function requestJson(url, path, options = {}) {
  const response = await fetch(`${url}${path}`, options);
  const body = await response.text();
  let payload;
  try {
    payload = body ? JSON.parse(body) : null;
  } catch {
    payload = body;
  }
  if (!response.ok) throw new Error(`${path} 请求失败（${response.status}）：${typeof payload === "string" ? payload : JSON.stringify(payload)}`);
  return payload;
}

async function verifyDocumentParsing(url, dataRoot) {
  const appSecret = "packaged-agent-smoke";
  const appHeaders = { "X-App-Auth-Secret": appSecret };
  const registration = await requestJson(url, "/api/v1/auth/register", {
    method: "POST",
    headers: { ...appHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({ username: "smoke", password: "smoke-password" }),
  });
  const headers = { ...appHeaders, Authorization: `Bearer ${registration.token}` };
  const project = await requestJson(url, "/api/v1/projects", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ title: "打包解析冒烟" }),
  });
  const conversation = await requestJson(url, "/api/v1/conversations", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: project.id, title: "文件解析" }),
  });
  const profile = await requestJson(url, "/api/v1/provider-profiles", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: "smoke-key" }),
  });
  const upload = async (filePath, fileName) => {
    const form = new FormData();
    form.append("conversation_id", conversation.id);
    form.append("provider_profile_id", profile.id);
    form.append("file", new Blob([readFileSync(filePath)]), fileName);
    return requestJson(url, "/api/v1/bid-workflows", { method: "POST", headers, body: form });
  };
  const converterPath = bundledConverterPath();
  const fixtures = createDocumentFixtures(dataRoot, converterPath);
  const legacyWorkflow = await upload(fixtures.docPath, "legacy.doc");
  const scannedWorkflow = await upload(fixtures.pdfPath, "scanned.pdf");
  const readWorkflowText = (id) => {
    const result = runCommand("/usr/bin/sqlite3", ["-json", join(dataRoot, "data", "app.db"), `SELECT file_text FROM bid_workflows WHERE id = '${id.replaceAll("'", "''")}'`]);
    return JSON.parse(result.toString("utf8"))[0]?.file_text || "";
  };
  if (!readWorkflowText(legacyWorkflow.id).includes(fixtures.legacyMarker)) throw new Error("旧版 DOC 未解析出预期文本。");
  const scannedText = readWorkflowText(scannedWorkflow.id);
  if (!["OCR", "TENDER", "2026"].every((token) => scannedText.includes(token))) {
    throw new Error(`扫描 PDF OCR 未解析出预期文本：${scannedText}`);
  }
  console.log("真实旧版 DOC 与扫描 PDF OCR 解析通过。");
}

async function smokeAgent() {
  requireFile(join(resourcesPath, "frontend", "index.html"));
  requireFile(agentPath, true);
  const converterPath = bundledConverterPath();
  const converter = spawnSync(converterPath, ["--version"], { encoding: "utf8", timeout: 10_000 });
  if (converter.status !== 0) throw new Error(`DOC 转换器无法启动：${converter.stderr || converter.stdout}`);

  const dataRoot = mkdtempSync(join(tmpdir(), "ai-workbench-packaged-smoke-"));
  const agent = spawn(agentPath, [], {
    env: {
      ...process.env,
      AGENT_PORT: "0",
      APP_AUTH_SECRET: "packaged-agent-smoke",
      AI_WORKBENCH_DATA_DIR: join(dataRoot, "data"),
      AI_WORKBENCH_TEST_CREDENTIALS: "1",
      HOME: dataRoot,
      LLVM_PROFILE_FILE: join(dataRoot, "default.profraw"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  let errors = "";

  try {
    const port = await new Promise((resolvePort, reject) => {
      const timeout = setTimeout(() => reject(new Error(`agent 启动超时：${errors || output}`)), 30_000);
      agent.stdout.on("data", (chunk) => {
        output += String(chunk);
        const match = output.match(/AI_WORKBENCH_BACKEND_READY=(\d+)/);
        if (!match) return;
        clearTimeout(timeout);
        resolvePort(Number(match[1]));
      });
      agent.stderr.on("data", (chunk) => {
        errors += String(chunk);
      });
      agent.once("error", (error) => {
        clearTimeout(timeout);
        reject(error);
      });
      agent.once("exit", (code) => {
        if (output.includes("AI_WORKBENCH_BACKEND_READY=")) return;
        clearTimeout(timeout);
        reject(new Error(`agent 提前退出（${code ?? "未知"}）：${errors}`));
      });
    });
    const response = await fetch(`http://127.0.0.1:${port}/health`);
    const health = await response.json();
    if (!response.ok || health.app !== "ai-workbench-desktop" || health.version !== packageJson.version) {
      throw new Error(`agent 健康检查失败：${JSON.stringify(health)}`);
    }
    await verifyDocumentParsing(`http://127.0.0.1:${port}`, dataRoot);
    console.log(`打包 agent 冒烟通过：端口 ${port}，DOC 转换器 ${basename(converterPath)}。`);
  } finally {
    agent.kill("SIGTERM");
    rmSync(dataRoot, { recursive: true, force: true });
  }
}

await smokeAgent();
