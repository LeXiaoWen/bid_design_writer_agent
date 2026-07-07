import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));

if (process.platform === "win32") {
  const result = spawnSync("cmd", ["/c", "scripts\\setup-agent.bat"], {
    cwd: resolve(scriptDir, ".."),
    stdio: "inherit",
  });
  process.exit(result.status ?? 1);
} else {
  const result = spawnSync("bash", ["scripts/setup-agent.sh"], {
    cwd: resolve(scriptDir, ".."),
    stdio: "inherit",
  });
  process.exit(result.status ?? 1);
}
