import type { CopilotConfig } from "./config";
export class BridgeError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export class Backend {
  constructor(
    private config: Pick<CopilotConfig, "backend" | "serviceToken">,
    private owner: string,
  ) {}
  async call<T = unknown>(
    path: string,
    body?: unknown,
    signal?: AbortSignal,
    method?: string,
  ): Promise<T> {
    const response = await fetch(`${this.config.backend}/api/copilot/${path}`, {
      method: method ?? (body ? "POST" : "GET"),
      headers: {
        "Content-Type": "application/json",
        "X-EventLens-Copilot": this.config.serviceToken,
        "X-Copilot-Owner": this.owner,
      },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(40000)])
        : AbortSignal.timeout(40000),
    });
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail =
        data && typeof data === "object" && "detail" in data
          ? data.detail
          : undefined;
      throw new BridgeError(
        typeof detail === "string"
          ? detail.slice(0, 500)
          : "Copilot 业务服务暂不可用",
        response.status,
      );
    }
    return data as T;
  }
}
