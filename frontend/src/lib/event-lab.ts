import type { EventLabSelection } from "@/types/event-lab";
import type { BoardQuery } from "@/types/trending";
import { categories } from "./catalog";

export function resolveEventLabSource(selection: EventLabSelection) {
  const category = categories.find(({ id }) => id === selection.categoryId);
  const platform = category?.platforms.find(({ id }) => id === selection.platformId);
  const board = platform?.boards.length === 1 ? platform.boards[0] : platform?.boards.find(({ id }) => id === selection.boardId);
  const query: BoardQuery | undefined = platform && board ? { platform: platform.id, board: board.id } : undefined;
  return { category, platform, board, query };
}
