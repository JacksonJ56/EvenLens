import { NextResponse } from "next/server";

export const runtime = "nodejs";

async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  // Explicit namespace only; no arbitrary proxy targets or user-controlled upstream hosts.
  if (!path.length || !["capabilities", "tasks", "datasets", "sessions"].includes(path[0]) ||
      path.some((part) => !/^[a-zA-Z0-9_-]+$/.test(part))) {
    return NextResponse.json({ detail: "无效的舆情 API 路径" }, { status: 404 });
  }
  const localAction = path[0] === "sessions" && request.method !== "GET";
  if (localAction) {
    const origin = request.headers.get("origin");
    if ((origin && origin !== new URL(request.url).origin) || request.headers.get("sec-fetch-site") === "cross-site") {
      return NextResponse.json({ detail: "请从本机 EventLens 页面操作平台登录" }, { status: 403 });
    }
  }
  try {
    let body: ArrayBuffer | undefined;
    if (request.method === "POST") {
      if (Number(request.headers.get("content-length")) > 5_000_000) {
        return NextResponse.json({ detail: "评论文件过大" }, { status: 413 });
      }
      body = await request.arrayBuffer();
      if (body.byteLength > 5_000_000) return NextResponse.json({ detail: "评论文件过大" }, { status: 413 });
    }
    const base = (process.env.EVENTLENS_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    const response = await fetch(`${base}/api/public-opinion/${path.join("/")}${new URL(request.url).search}`, {
      method: request.method, body, cache: "no-store", headers: { "Content-Type": "application/json",
        ...(localAction ? { "X-EventLens-Local-Action": "1" } : {}) },
      signal: AbortSignal.timeout(15000),
    });
    return new Response(await response.text(), { status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "无法连接舆情后端，请检查 FastAPI 是否启动及代理地址配置" }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
