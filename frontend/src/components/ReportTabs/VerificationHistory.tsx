import { AlertOctagon, CheckCircle2, RefreshCw } from "lucide-react";
import type { Report } from "../../types";

export function VerificationHistory({ report }: { report: Report }) {
  const v = report.verification;
  return (
    <div className="flex flex-col gap-3">
      {/* Unresolved disagreements — flagged prominently, never smoothed over */}
      {v.unresolved_issues.length > 0 && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2.5">
          <div className="mb-1.5 flex items-center gap-2 text-[12.5px] font-600 text-red-300">
            <AlertOctagon size={15} /> Unresolved after {v.n_rounds} rounds
          </div>
          {v.unresolved_issues.map((i, k) => (
            <div key={k} className="text-[12px] text-red-200/90">
              <span className="font-600">{i.column}:</span> {i.problem}
              {i.suggested_fix && <span className="text-red-200/60"> → {i.suggested_fix}</span>}
            </div>
          ))}
        </div>
      )}

      {v.rounds.map((r) => (
        <div key={r.round_no} className="rounded-xl border border-hairline bg-surface px-3 py-2.5">
          <div className="mb-1.5 flex items-center gap-2 text-[12.5px] font-600 text-primary">
            {r.approved ? (
              <CheckCircle2 size={14} className="text-aqua" />
            ) : (
              <RefreshCw size={14} className="text-violet" />
            )}
            Round {r.round_no}
            <span className="font-400 text-muted">
              {r.approved ? "approved" : `${r.issues.length} issue(s), changes requested`}
            </span>
          </div>
          {r.error && <p className="text-[12px] text-red-300">verifier error: {r.error}</p>}
          {r.issues.map((i, k) => (
            <div key={k} className="mt-1 text-[12px] text-muted">
              <span className="font-500 text-primary">{i.column}:</span> {i.problem}
              {i.suggested_fix && <span className="text-azure/80"> → {i.suggested_fix}</span>}
            </div>
          ))}
          {r.revised_columns.length > 0 && (
            <p className="mt-1.5 font-mono text-[10.5px] text-muted">
              revised: {r.revised_columns.join(", ")}
            </p>
          )}
        </div>
      ))}

      {v.notes.length > 0 && (
        <div className="rounded-xl border border-hairline bg-surface px-3 py-2.5">
          <div className="mb-1 text-[11px] font-600 uppercase tracking-wide text-muted">Run notes</div>
          {v.notes.map((n, k) => (
            <p key={k} className="text-[11.5px] leading-snug text-muted">
              • {n}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
