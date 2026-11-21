import { z } from "zod";
import { categories, platforms } from "../catalog";
const id = z.string().min(1).max(120);
export const pageSchema = z
  .object({
    category_id: id,
    platform_id: id,
    feed_id: id,
    mode: z.enum(["mock", "live"]),
    selected_event_id: id.optional(),
    items: z
      .array(
        z.object({
          id,
          title: z.string().max(1000),
          rank: z.number().int().positive(),
        }),
      )
      .max(30),
  })
  .strict();
export const requestSchema = z
  .object({
    thread_id: z.string().regex(/^[a-f0-9]{32}$/),
    request_id: z.uuid(),
    user_id: z.uuid(),
    question: z.string().trim().min(1).max(4000),
    page: pageSchema,
    reference: z
      .object({ category_id: id, platform_id: id, feed_id: id, id })
      .strict()
      .optional(),
  })
  .strict();
export function canonicalPage(page: z.infer<typeof pageSchema>) {
  const category = categories.find((c) => c.id === page.category_id),
    platform = category?.platforms.find((p) => p.id === page.platform_id),
    board = platform?.boards.find((b) => b.id === page.feed_id);
  if (!category || !platform || !board)
    throw new Error("页面分类、平台与榜单不匹配，请刷新后重试");
  return {
    category_id: category.id,
    category_name: category.name,
    platform_id: platform.id,
    platform_name: platforms[platform.id].name,
    feed_id: board.id,
    board_id: platform.boards.length > 1 ? board.id : null,
    board_name: board.label,
  };
}
// Only the trusted Node route sends this; Python keeps no duplicate category list.
export function boardCatalog() {
  return categories.flatMap(category => category.platforms.flatMap(platform =>
    platform.boards.map(board => canonicalPage({category_id:category.id,platform_id:platform.id,feed_id:board.id,mode:"live",items:[]}))));
}
export const sourceSchema = z.object({ title: z.string(), url: z.url() });
export const artifactSchema = z.object({
  id: z.string().regex(/^[a-f0-9]{32}$/),
  kind: z.enum(["trace", "opinion"]),
  title: z.string(),
  status: z.string(),
  message: z.string(),
  created_at: z.number(),
});
export const envelopeSchema = z.object({
  data: z.unknown(),
  sources: z.array(sourceSchema).optional(),
  artifact: artifactSchema.optional(),
});
const toolSchema = z.object({
  id: z.string(),
  name: z.string(),
  label: z.string(),
  status: z.enum(["running", "done", "error"]),
});
export const eventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("start"), thread_id: z.string() }),
  z.object({ type: z.literal("delta"), text: z.string() }),
  z.object({ type: z.literal("tool"), tool: toolSchema }),
  z.object({ type: z.literal("sources"), sources: z.array(sourceSchema) }),
  z.object({ type: z.literal("artifact"), artifact: artifactSchema }),
  z.object({ type: z.literal("error"), message: z.string() }),
  z.object({
    type: z.literal("done"),
    status: z.enum(["done", "error", "cancelled"]),
  }),
]);
