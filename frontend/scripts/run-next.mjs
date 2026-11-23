import { spawn } from "node:child_process";
import { X509Certificate } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "dotenv";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// Node reads NODE_EXTRA_CA_CERTS at process startup. Load only this setting
// before spawning Next; do not export other .env secrets into its environment.
export function nextEnvironment(cwd = frontend, inherited = process.env) {
  const local = {};
  for (const name of [".env", ".env.local"]) {
    try {
      Object.assign(local, parse(readFileSync(resolve(cwd, name))));
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  const environment = { ...inherited };
  const configured = inherited.NODE_EXTRA_CA_CERTS ?? local.NODE_EXTRA_CA_CERTS;
  if (!configured?.trim()) return environment;
  const filename = resolve(cwd, configured.trim());
  try {
    new X509Certificate(readFileSync(filename));
  } catch {
    throw new Error(
      "NODE_EXTRA_CA_CERTS 文件不存在或不是有效 PEM 证书，请检查 frontend/.env.local 中的路径。",
    );
  }
  environment.NODE_EXTRA_CA_CERTS = filename;
  return environment;
}

export function runNext(args = process.argv.slice(2)) {
  if (!["dev", "start"].includes(args[0]))
    throw new Error("启动器仅支持 dev 或 start");
  const env = nextEnvironment();
  if (env.NODE_EXTRA_CA_CERTS)
    console.info(
      "[EventLens] 已加载配置的额外可信 CA；HTTPS 证书校验保持开启。",
    );
  const require = createRequire(import.meta.url);
  const child = spawn(
    process.execPath,
    [require.resolve("next/dist/bin/next"), ...args],
    {
      cwd: frontend,
      env,
      stdio: "inherit",
    },
  );
  const listeners = ["SIGINT", "SIGTERM"].map((signal) => {
    const listener = () => {
      if (!child.killed) child.kill(signal);
    };
    process.on(signal, listener);
    return [signal, listener];
  });
  const cleanup = () =>
    listeners.forEach(([signal, listener]) => process.off(signal, listener));
  child.once("error", () => {
    cleanup();
    console.error("[EventLens] 无法启动 Next.js，请检查依赖安装。");
    process.exitCode = 1;
  });
  child.once("exit", (code, signal) => {
    cleanup();
    process.exitCode =
      code ?? (signal === "SIGINT" ? 130 : signal === "SIGTERM" ? 143 : 1);
  });
  return child;
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    runNext();
  } catch (error) {
    console.error("[EventLens] " + error.message);
    process.exitCode = 1;
  }
}
