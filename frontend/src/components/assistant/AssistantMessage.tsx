import { ChatMarkdown } from "@/components/claim/ChatMarkdown";

interface ParsedSection {
  title: string;
  body: string;
  isBullets?: boolean;
}

const SECTION_PATTERNS: { key: string; title: string; bullets?: boolean; highlight?: boolean }[] = [
  { key: "summary", title: "Summary" },
  { key: "in short", title: "In short" },
  { key: "key findings", title: "Key findings", bullets: true },
  { key: "your numbers", title: "Your numbers", bullets: true },
  { key: "what this means for you", title: "What this means for you", bullets: true },
  { key: "recommended action", title: "Recommended action", highlight: true },
  { key: "do this next", title: "Do this next", highlight: true },
];

function isStructuredAssistantContent(content: string): boolean {
  const lower = content.toLowerCase();
  return (
    lower.includes("**summary:**") ||
    lower.includes("**in short:**") ||
    lower.includes("**recommended action:**") ||
    lower.includes("**do this next:**")
  );
}

function parseStructuredContent(content: string): ParsedSection[] | null {
  if (!isStructuredAssistantContent(content)) {
    return null;
  }

  const sections: ParsedSection[] = [];
  const regex = /\*\*([^*]+)\*\*:?\s*/g;
  const matches = [...content.matchAll(regex)];

  if (matches.length === 0) return null;

  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const titleRaw = match[1].trim().toLowerCase();
    const start = (match.index ?? 0) + match[0].length;
    const end = i + 1 < matches.length ? (matches[i + 1].index ?? content.length) : content.length;
    const body = content.slice(start, end).trim();
    const meta = SECTION_PATTERNS.find((p) => titleRaw.startsWith(p.key));
    sections.push({
      title: meta?.title ?? match[1].trim(),
      body,
      isBullets: meta?.bullets ?? body.includes("\n-"),
    });
  }

  return sections.length > 0 ? sections : null;
}

function renderBody(body: string, isBullets?: boolean) {
  if (isBullets || body.includes("\n-")) {
    const items = body
      .split("\n")
      .map((line) => line.replace(/^-\s*/, "").trim())
      .filter(Boolean);
    return (
      <ul className="mt-1 space-y-1 pl-4 list-disc text-sm leading-relaxed">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    );
  }
  return <p className="mt-1 text-sm leading-relaxed">{body}</p>;
}

export function AssistantMessage({ content }: { content: string }) {
  const sections = parseStructuredContent(content);
  const footerMatch = content.match(/_(.+?)_$/s);
  const footer = footerMatch?.[1]?.trim();

  if (!sections) {
    return <ChatMarkdown content={content} />;
  }

  return (
    <div className="space-y-2.5">
      {sections.map((section) => {
        const meta = SECTION_PATTERNS.find((p) => p.title === section.title);
        const highlighted = meta?.highlight;
        return (
          <div
            key={section.title}
            className={
              highlighted
                ? "rounded-lg border border-secondary/30 bg-secondary/5 px-2.5 py-2"
                : undefined
            }
          >
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {section.title}
            </p>
            {renderBody(section.body, section.isBullets)}
          </div>
        );
      })}
      {footer && <p className="text-xs text-muted-foreground italic pt-0.5">{footer}</p>}
    </div>
  );
}
