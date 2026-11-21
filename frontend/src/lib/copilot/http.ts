import "server-only";
import { cookies } from "next/headers";
import { createHash, randomUUID } from "node:crypto";
import { copilotConfig } from "./config";
import { Backend, BridgeError } from "./backend";

export function localAction(request: Request) {
  const host = request.headers.get("host");
  if (!host) throw new BridgeError("来源无效", 403);
  const expected = new URL(`${new URL(request.url).protocol}//${host}`),
    origin = request.headers.get("origin");
  if (
    !["localhost", "127.0.0.1", "[::1]"].includes(expected.hostname) ||
    expected.host !== host ||
    (origin && origin !== expected.origin) ||
    request.headers.get("sec-fetch-site") === "cross-site"
  )
    throw new BridgeError("请从本机 EventLens 页面操作 Copilot", 403);
}
export async function connection(create = false) {
  const jar = await cookies();
  let identity = jar.get("eventlens_copilot")?.value;
  if (!identity && create) {
    identity = randomUUID();
    jar.set("eventlens_copilot", identity, {
      httpOnly: true,
      sameSite: "strict",
      path: "/",
      maxAge: 2592000,
      secure: process.env.COPILOT_SECURE_COOKIE === "true",
    });
  }
  if (!identity || !/^[a-f0-9-]{36}$/.test(identity))
    throw new BridgeError("请先初始化对话", 401);
  const config = copilotConfig(),
    owner = createHash("sha256").update(identity).digest("hex");
  return { backend: new Backend(config, owner), config };
}
export function errorResponse(error: unknown) {
  return Response.json(
    { detail: error instanceof Error ? error.message : "Copilot 服务暂不可用" },
    {
      status: error instanceof BridgeError ? error.status : 503,
      headers: { "Cache-Control": "no-store" },
    },
  );
}
