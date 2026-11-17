const noStore = { "Cache-Control": "no-store" };

export async function POST(request: Request) {
  const backend = (process.env.EVENTLENS_BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
  const timeout = AbortSignal.timeout(130_000);
  try {
    const upstream = await fetch(`${backend}/api/event-trace`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
      signal: AbortSignal.any([request.signal, timeout]),
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { ...noStore, "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    const detail = timeout.aborted ? "事件溯源请求超时，请重试" : "无法连接事件溯源后端，请检查 FastAPI 是否运行";
    return Response.json({ detail }, { status: timeout.aborted ? 504 : 502, headers: noStore });
  }
}
