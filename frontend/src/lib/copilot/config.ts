import "server-only";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { parse } from "dotenv";
export interface CopilotConfig {
  key: string;
  model: string;
  baseUrl: string;
  backend: string;
  serviceToken: string;
  maxTools: number;
  maxRequests: number;
  tokenBudget: number;
  timeoutMs: number;
}
export function copilotConfig(): CopilotConfig {
  let shared: Record<string, string> = {};
  try {
    shared = parse(
      readFileSync(
        process.env.EVENTLENS_BACKEND_ENV_FILE ||
          resolve(process.cwd(), "../backend/.env"),
      ),
    );
  } catch {
    /* Explicit server env can provide all settings. */
  }
  const get = (name: string) => process.env[name] ?? shared[name];
  const key =
      get("COPILOT_LLM_API_KEY") || get("EVENT_TRACE_LLM_API_KEY") || "",
    model = get("COPILOT_LLM_MODEL") || get("EVENT_TRACE_LLM_MODEL") || "";
  if (!key || !model)
    throw new Error(
      "Copilot 尚未配置模型；请配置后端 EVENT_TRACE_LLM_API_KEY / EVENT_TRACE_LLM_MODEL 或服务端 COPILOT_LLM_*",
    );
  const baseUrl =
      get("COPILOT_LLM_BASE_URL") ||
      get("EVENT_TRACE_LLM_BASE_URL") ||
      "https://api.deepseek.com/v1",
    backend = process.env.EVENTLENS_BACKEND_URL || "http://127.0.0.1:8000";
  for (const value of [baseUrl, backend]) {
    const u = new URL(value);
    if (
      !["http:", "https:"].includes(u.protocol) ||
      u.username ||
      u.password ||
      u.search ||
      u.hash
    )
      throw new Error("服务端模型或后端地址配置无效");
  }
  const bound = (name: string, fallback: number, max: number) => {
    const n = Number(get(name) ?? fallback);
    if (!Number.isInteger(n) || n < 1 || n > max)
      throw new Error(`${name} 配置超出范围`);
    return n;
  };
  const serviceToken =
    get("COPILOT_SERVICE_TOKEN") ||
    createHash("sha256")
      .update((get("EVENT_TRACE_LLM_API_KEY") || "") + "\nEventLens Copilot")
      .digest("hex");
  return {
    key,
    model,
    baseUrl: baseUrl.replace(/\/$/, ""),
    backend: backend.replace(/\/$/, ""),
    serviceToken,
    maxTools: bound("COPILOT_MAX_TOOLS", 10, 24),
    maxRequests: bound("COPILOT_MAX_MODEL_REQUESTS", 8, 16),
    tokenBudget: bound("COPILOT_TOKEN_BUDGET", 60000, 160000),
    timeoutMs: bound("COPILOT_TIMEOUT_SECONDS", 120, 150) * 1000,
  };
}
