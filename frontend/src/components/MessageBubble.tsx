import type { AnalysisResult, Message } from "../types";

function fmt(v: string | number | null): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/\.?0+$/, "");
  return String(v);
}

function AnalysisBlock({ a }: { a: AnalysisResult }) {
  return (
    <div className="mt-2 overflow-hidden rounded-lg border border-hairline bg-void/50">
      {a.error ? (
        <div className="px-3 py-2 font-mono text-[11.5px] text-red-300">{a.error}</div>
      ) : a.table ? (
        <div className="max-h-[280px] overflow-auto">
          <table className="w-full border-collapse font-mono text-[11.5px]">
            <thead className="sticky top-0 bg-raised">
              <tr>
                {a.table.columns.map((c) => (
                  <th key={c} className="border-b border-hairline px-2.5 py-1.5 text-left font-600 text-primary">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {a.table.rows.map((row, i) => (
                <tr key={i} className="odd:bg-surface/40">
                  {row.map((cell, j) => (
                    <td key={j} className="whitespace-nowrap border-b border-hairline/50 px-2.5 py-1 text-muted">
                      {fmt(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : a.value !== null ? (
        <div className="px-3 py-2.5 font-mono text-[15px] font-600 text-aqua">{a.value}</div>
      ) : null}

      {a.table?.truncated && (
        <div className="px-3 py-1 font-mono text-[10.5px] text-muted">showing first {a.table.rows.length} rows</div>
      )}

      <details className="border-t border-hairline">
        <summary className="cursor-pointer px-3 py-1.5 text-[11px] text-muted hover:text-primary">
          View pandas
        </summary>
        <pre className="overflow-x-auto whitespace-pre-wrap px-3 pb-2.5 font-mono text-[11px] leading-relaxed text-muted">
          {a.code}
        </pre>
      </details>
    </div>
  );
}

/** User = right-aligned accent bubble; assistant = left surface bubble;
 *  system = centered quiet notice. Status lines are handled separately. */
export function MessageBubble({ message, streaming = false }: { message: Message; streaming?: boolean }) {
  if (message.role === "system") {
    return (
      <div className="animate-fade-in py-2 text-center">
        <span className="rounded-full border border-hairline bg-surface px-3 py-1 text-[12px] text-muted">
          {message.content}
        </span>
      </div>
    );
  }

  const isUser = message.role === "user";
  const hasAnalysis = !isUser && !!message.analysis;
  return (
    <div className={`flex animate-fade-in ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-[14px] leading-relaxed ${
          hasAnalysis ? "max-w-[95%] w-full" : "max-w-[85%]"
        } ${
          isUser
            ? "bg-azure/15 text-primary ring-1 ring-azure/30"
            : "border border-hairline bg-surface text-primary"
        }`}
      >
        {message.content}
        {streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-azure align-middle motion-reduce:animate-none" />}
        {hasAnalysis && <AnalysisBlock a={message.analysis!} />}
      </div>
    </div>
  );
}
