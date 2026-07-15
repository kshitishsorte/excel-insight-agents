import type { Report } from "../../types";

const K = {
  col: "column",
  dtype: "dtype: before → after",
  mBefore: "missing% before",
  mAfter: "missing% after",
  strategy: "strategy",
  imputed: "cells imputed",
  finalized: "finalized",
  reasoning: "reasoning",
};

export function CleaningLog({ report }: { report: Report }) {
  const rows = report.cleaning_log as Record<string, string | number>[];
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r, i) => (
        <div key={i} className="rounded-xl border border-hairline bg-surface px-3 py-2.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[13px] font-600 text-primary">{r[K.col]}</span>
            <span className="rounded-md bg-raised px-1.5 py-0.5 font-mono text-[10.5px] text-azure">
              {r[K.strategy]}
            </span>
          </div>
          <div className="mt-1 font-mono text-[11px] text-muted">{r[K.dtype]}</div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-[11px] text-muted">
            <span>
              missing {r[K.mBefore]} → <span className="text-primary">{r[K.mAfter]}</span>
            </span>
            <span>imputed {r[K.imputed]}</span>
          </div>
          {r[K.reasoning] && (
            <p className="mt-1.5 text-[12px] leading-snug text-muted">{r[K.reasoning]}</p>
          )}
          {r[K.finalized] && (
            <p className="mt-1 text-[10.5px] italic text-muted/70">{r[K.finalized]}</p>
          )}
        </div>
      ))}
    </div>
  );
}
