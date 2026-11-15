import type { Trend, TrendReadingBlock } from "@/types/trending";

function getImageUrl(value: string) {
  try {
    const url = new URL(value);
    if ((url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password) return url.href;
  } catch {
    // Invalid image URLs are omitted from the reading pane.
  }
}

export function TrendPreviewContent({ trend, hasSource }: { trend: Trend; hasSource: boolean }) {
  const blocks = (trend.preview?.blocks ?? []).flatMap<TrendReadingBlock>((block) => {
    if (block.type === "paragraph") return block.text.trim() ? [block] : [];
    const src = getImageUrl(block.src);
    return src ? [{ ...block, src }] : [];
  });
  const summary = trend.preview?.summary?.trim();

  return (
    <article className="trend-reader" aria-label="阅读内容">
      {blocks.length > 0 ? (
        blocks.map((block, index) => block.type === "paragraph" ? (
          <p key={index}>{block.text}</p>
        ) : (
          <figure key={index}>
            {/* The source API can supply external images with unknown dimensions. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={block.src} alt={block.alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" />
            {block.caption && <figcaption>{block.caption}</figcaption>}
          </figure>
        ))
      ) : (
        <div className="trend-reader-empty">
          {summary && <p><strong>摘要</strong>{summary}</p>}
          <p>{hasSource ? "暂无可阅读的正文，可在浏览器中查看来源页面。" : "暂无可阅读的正文或有效的来源链接。"}</p>
        </div>
      )}
    </article>
  );
}
