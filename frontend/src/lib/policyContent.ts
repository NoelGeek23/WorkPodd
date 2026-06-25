export function getPolicySectionTitle(title: string): string {
  return title.trim().toLowerCase() === "examples" ? "FAQ" : title;
}

function stripHeadingMarkers(line: string): string {
  return line.replace(/^#{1,6}\s+/, "").trim();
}

function normalizeHeading(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

export function policyPreviewText(content: string, sectionTitle: string, limit = 260): string {
  const plain = content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => {
      if (!line.startsWith("#")) {
        return true;
      }
      return normalizeHeading(stripHeadingMarkers(line)) !== normalizeHeading(sectionTitle);
    })
    .map((line) => (line.startsWith("#") ? stripHeadingMarkers(line) : line))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();

  if (plain.length <= limit) {
    return plain;
  }

  return `${plain.slice(0, limit).trimEnd()}…`;
}

type PolicyBlock =
  | { type: "heading"; level: 2 | 3; text: string }
  | { type: "paragraph"; text: string }
  | { type: "list"; items: string[] };

export function parsePolicyContent(content: string, sectionTitle: string): PolicyBlock[] {
  const blocks: PolicyBlock[] = [];
  let paragraphLines: string[] = [];
  let listItems: string[] = [];

  function flushParagraph() {
    if (paragraphLines.length === 0) {
      return;
    }
    blocks.push({ type: "paragraph", text: paragraphLines.join(" ") });
    paragraphLines = [];
  }

  function flushList() {
    if (listItems.length === 0) {
      return;
    }
    blocks.push({ type: "list", items: listItems });
    listItems = [];
  }

  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      flushParagraph();
      continue;
    }

    if (line.startsWith("#")) {
      flushList();
      flushParagraph();
      const heading = stripHeadingMarkers(line);
      if (normalizeHeading(heading) === normalizeHeading(sectionTitle)) {
        continue;
      }
      const level = line.startsWith("### ") ? 3 : 2;
      blocks.push({ type: "heading", level, text: heading });
      continue;
    }

    if (line.startsWith("- ")) {
      flushParagraph();
      listItems.push(line.slice(2).trim());
      continue;
    }

    flushList();
    if (line.endsWith("?")) {
      flushParagraph();
      blocks.push({ type: "heading", level: 3, text: line });
      continue;
    }

    paragraphLines.push(line);
  }

  flushList();
  flushParagraph();
  return blocks;
}
