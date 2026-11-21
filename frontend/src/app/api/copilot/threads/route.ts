import { connection, errorResponse, localAction } from "@/lib/copilot/http";
export const runtime = "nodejs";
export async function GET(request: Request) {
  try {
    localAction(request);
    const { backend } = await connection(true);
    const id = new URL(request.url).searchParams.get("id");
    if (id && !/^[a-f0-9]{32}$/.test(id))
      return Response.json({ detail: "会话ID无效" }, { status: 422 });
    return Response.json(
      await backend.call("threads" + (id ? "?id=" + id : "")),
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (e) {
    return errorResponse(e);
  }
}

export async function DELETE(request: Request) {
  try {
    localAction(request);
    const id = new URL(request.url).searchParams.get("id");
    if (!id || !/^[a-f0-9]{32}$/.test(id))
      return Response.json({detail: "会话ID无效"}, {status: 422});
    const {backend} = await connection();
    return Response.json(await backend.call("threads?id="+id, undefined, undefined, "DELETE"),
      {headers: {"Cache-Control": "no-store"}});
  } catch (error) {
    return errorResponse(error);
  }
}
