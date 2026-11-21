import { connection, errorResponse, localAction } from "@/lib/copilot/http";
export const runtime = "nodejs";
async function result(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    localAction(request);
    const { id } = await context.params,
      thread = new URL(request.url).searchParams.get("thread_id");
    if (!/^[a-f0-9]{32}$/.test(id) || !thread || !/^[a-f0-9]{32}$/.test(thread))
      return Response.json({ detail: "结果标识无效" }, { status: 422 });
    const { backend } = await connection();
    return Response.json(
      await backend.call(
        `results/${id}?thread_id=${thread}`,
        undefined,
        undefined,
        request.method,
      ),
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (e) {
    return errorResponse(e);
  }
}
export const GET = result;
export const DELETE = result;
