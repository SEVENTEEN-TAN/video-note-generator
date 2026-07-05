import type { MarkdownBlock, PreviewImage } from "./types";

export function parseMarkdown(markdown: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let list: Extract<MarkdownBlock, { type: "list" }> | null = null;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push(list);
      list = null;
    }
  };

  for (const line of markdown.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    const image = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(trimmed);
    const unordered = /^[-*]\s+(.+)$/.exec(trimmed);
    const ordered = /^\d+[.)]\s+(.+)$/.exec(trimmed);

    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim() });
    } else if (image) {
      flushParagraph();
      flushList();
      blocks.push({ type: "image", alt: image[1].trim(), src: image[2].trim() });
    } else if (unordered || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { type: "list", ordered: isOrdered, items: [] };
      }
      list.items.push((ordered?.[1] ?? unordered?.[1] ?? "").trim());
    } else {
      flushList();
      paragraph.push(trimmed);
    }
  }

  flushParagraph();
  flushList();
  return blocks;
}

export function extractMarkdownImages(markdown: string, jobId?: string, assetBasePath?: string): PreviewImage[] {
  if (!jobId) {
    return [];
  }
  return parseMarkdown(markdown)
    .filter((block): block is Extract<MarkdownBlock, { type: "image" }> => block.type === "image")
    .map((block, index) => ({
      label: block.alt || `frame_${index + 1}`,
      path: `${assetBasePath ? `${assetBasePath}/` : ""}${block.src}`.replace(/\\/g, "/"),
      asset_url: resolvePreviewAssetUrl(block.src, jobId, assetBasePath)
    }))
    .filter((image) => image.asset_url);
}

export function resolvePreviewAssetUrl(path: string, jobId?: string, assetBasePath?: string) {
  const value = path.trim().replace(/^["']|["']$/g, "");
  if (!jobId || !value || /^(?:[a-z][a-z\d+.-]*:|\/\/|\/)/i.test(value)) {
    return "";
  }
  const normalizedPath = assetBasePath ? `${assetBasePath.replace(/\/$/, "")}/${value}` : value;
  const segments = normalizedPath
    .replace(/\\/g, "/")
    .replace(/^\.?\//, "")
    .split("/")
    .filter((segment) => segment && segment !== "." && segment !== "..");
  if (segments.length === 0) {
    return "";
  }
  return `/api/jobs/${encodeURIComponent(jobId)}/assets/${segments.map(encodeURIComponent).join("/")}`;
}
