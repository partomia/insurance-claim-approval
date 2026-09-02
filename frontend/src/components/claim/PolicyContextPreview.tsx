interface PolicyContext {
  coverage_summary?: string;
  exclusions?: string[];
  key_sections?: { ref: string; category: string; summary: string }[];
  llm_analysis?: string;
  source?: string;
  document_count?: number;
  sections_loaded?: string[];
}

export function PolicyContextPreview({ context }: { context: PolicyContext }) {
  if (!context?.coverage_summary && !context?.llm_analysis) return null;

  return (
    <div className="mt-4 p-4 bg-success-subtle border border-success-border rounded-lg space-y-3">
      <h4 className="font-semibold text-success">Motor Policy Analysis (Groq AI)</h4>
      {context.coverage_summary && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Coverage Summary</p>
          <p className="text-sm">{context.coverage_summary}</p>
        </div>
      )}
      {context.exclusions && context.exclusions.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Exclusions</p>
          <div className="flex flex-wrap gap-1 mt-1">
            {context.exclusions.map((e) => (
              <span key={e} className="px-2 py-0.5 bg-destructive/10 text-destructive text-xs rounded">
                {e}
              </span>
            ))}
          </div>
        </div>
      )}
      {context.key_sections && context.key_sections.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Key Sections</p>
          {context.key_sections.map((s, i) => (
            <div key={i} className="text-sm border-l-2 border-info pl-2">
              <span className="font-medium">{s.ref}</span> — {s.summary}
            </div>
          ))}
        </div>
      )}
      {context.llm_analysis && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Detailed Analysis</p>
          <p className="text-sm text-muted-foreground">{context.llm_analysis}</p>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Source: {context.source} · {context.document_count} documents loaded
      </p>
    </div>
  );
}
